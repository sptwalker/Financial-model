# -*- coding: utf-8 -*-
"""预测服务测试（阶段 3）：选档门槛 / 形状不塌缩 / 缩放不变量 / 渠道拆分 /
稀疏兜底端到端 / CI 有序 / apply→recalc 三情景。复用 seed（情景 1）。
"""
from decimal import Decimal

import pytest

from app.models.financial import Cell, ModelVersion, Scenario
from app.models.forecast import ForecastRun, SalesActual
from app.services import forecast_service as fs


@pytest.fixture(scope="module")
def db():
    from app.db.session import SessionLocal, init_db
    init_db()
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def seeded(db):
    """重置情景 1 到纯净 v1 + sales_actuals（幂等）"""
    old = db.query(Scenario).filter(Scenario.id == 1).first()
    if old:
        db.query(Cell).filter(Cell.scenario_id == 1).delete()
        db.query(ModelVersion).filter(ModelVersion.scenario_id == 1).delete()
        db.commit()
    db.query(SalesActual).delete()  # 全局历史表：先清空再种子，防跨模块残留
    db.commit()
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.seed_from_excel import main as seed_main
    seed_main()
    return db


def _grid(db, version_no):
    return {c.row_key + "|" + c.period: Decimal(c.value)
            for c in db.query(Cell).filter(Cell.scenario_id == 1,
                                           Cell.model_version == version_no).all()}


# ---------- 纯函数：选档 ----------

def test_choose_method_thresholds():
    assert fs.choose_method(11)[0] == "plan_anchored"
    assert fs.choose_method(12)[0] == "seasonal_naive"
    assert fs.choose_method(24)[0] == "holt_winters"
    assert fs.choose_method(36)[0] == "sarima"
    # 用户强选低档永远honored
    assert fs.choose_method(1, "plan_anchored")[0] == "plan_anchored"


# ---------- 纯函数：形状不塌缩（绕开 seasonal_weights bug） ----------

def test_robust_shape_no_collapse_when_sparse():
    w = fs.robust_shape([Decimal(0)] * 10 + [Decimal("0.1"), Decimal("0.3")])
    assert len(w) == 12
    assert min(w) > 0, "稀疏历史下最小月权重必须 >0（不得塌缩）"
    assert abs(sum(w, Decimal(0)) - 1) < Decimal("1e-9")


def test_robust_shape_uses_history_when_full():
    vals = [Decimal(i) for i in range(1, 13)]  # 12 满月
    w = fs.robust_shape(vals)
    total = sum(vals, Decimal(0))
    assert w == [v / total for v in vals]


def test_robust_shape_all_zero_is_uniform():
    w = fs.robust_shape([Decimal(0)] * 6)
    assert w == [Decimal(1) / 6] * 6


# ---------- 纯函数：缩放到年度目标 ----------

def test_scale_to_annual_exact_and_proportional():
    series = [{"period": f"2027-{m:02d}", "yhat": Decimal(m),
               "lower": Decimal(m) / 2, "upper": Decimal(m) * 2} for m in range(1, 13)]
    total = sum(Decimal(m) for m in range(1, 13))  # 78
    fs.scale_to_annual(series, {2027: Decimal("40")})
    assert sum((pt["yhat"] for pt in series), Decimal(0)) == Decimal("40")  # 年合计精确
    # 前 11 月严格按比例（末月吸收余数）
    assert series[1]["yhat"] == Decimal("40") * Decimal(2) / total
    # lower/upper 同比缩放（factor = new/old）
    f = series[1]["yhat"] / Decimal(2)
    assert series[1]["lower"] == Decimal(1) * f


# ---------- 纯函数：渠道拆分 ----------

def test_split_ratio_prefers_actual_when_enough():
    actuals = {"online": {"a": Decimal(6), "b": Decimal(6), "c": Decimal(8)},
               "offline": {"a": Decimal(4), "b": Decimal(4), "c": Decimal(2)}}
    # 3 有效月 → 用实际累计占比 20/30
    assert fs.split_ratio(actuals, Decimal(1), Decimal(9), n_eff=3) == Decimal(20) / Decimal(30)


def test_split_ratio_falls_back_to_plan():
    actuals = {"online": {"a": Decimal(1)}, "offline": {"a": Decimal(0)}}
    # <3 有效月 → 用计划占比 7/10
    assert fs.split_ratio(actuals, Decimal(7), Decimal(3), n_eff=1) == Decimal(7) / Decimal(10)


def test_channel_split_sums_to_yhat():
    series = [{"period": "2026-09", "yhat": Decimal("0.5")}]
    fs.channel_split(series, Decimal("0.4"))
    assert series[0]["online"] + series[0]["offline"] == Decimal("0.5")
    assert series[0]["online"] == Decimal("0.2")


# ---------- 端到端：稀疏兜底 + CI 有序 ----------

def test_run_forecast_sparse_fallback(seeded):
    db = seeded
    res = fs.run_forecast(db, 1)
    assert res["method"] == "plan_anchored"       # 仅 1 有效月 → 最低档
    assert res["data_sufficient"] is False         # 触发"数据不足"文案
    series = res["series"]
    assert len(series) == 18                        # 2026-07..2027-12
    # 非塌缩：远多于 2 个月有正 yhat（seasonal_weights bug 会把量塌进 2 月）
    assert sum(1 for pt in series if pt["yhat"] > 0) >= 12
    # CI 有序 + 未来月带宽 > 0
    for pt in series:
        assert pt["lower"] <= pt["yhat"] <= pt["upper"]
        assert pt["online"] + pt["offline"] == pt["yhat"]
    future = next(pt for pt in series if pt["period"] == "2027-12")
    assert future["upper"] > future["yhat"]         # 宽区间


def test_run_forecast_backtest_insufficient(seeded):
    db = seeded
    res = fs.run_forecast(db, 1)
    # 历史 < 7 月 → 各档回测均"数据不足"
    assert res["candidates"]["seasonal_naive"]["smape"] is None
    assert "数据不足" in res["candidates"]["seasonal_naive"]["reason"]


# ---------- 端到端：apply → recalc（三情景） ----------

def test_apply_forecast_three_scenarios(seeded):
    db = seeded
    before = _grid(db, 1)
    res = fs.run_forecast(db, 1)
    ratio = Decimal(res["ratio_online"])

    def scn(key):
        return [{"period": pt["period"], "online": pt[key] * ratio,
                 "offline": pt[key] * (1 - ratio)} for pt in res["series"]]

    base, lower, upper = scn("yhat"), scn("lower"), scn("upper")
    out = fs.apply_forecast(db, 1, base=base, method=res["method"],
                            lower=lower, upper=upper, comment="test预测")

    # 三情景 = 3 个新版本，base 最新
    assert out["base_version"] > out["upper_version"] > out["lower_version"]
    after = _grid(db, out["base_version"])
    # 回填生效：qty.online 2026-09 = base 序列值；下游 sale.online.amount 随动（默认价 1799）
    b09 = next(pt for pt in base if pt["period"] == "2026-09")
    assert after["qty.online|2026-09"] == b09["online"]
    assert after["sale.online.amount|2026-09"] == b09["online"] * Decimal("1799")
    # 2028 年度目标不受回填影响（仍由引擎季节曲线月度化）
    assert after["target.sales|2028-12"] == before["target.sales|2028-12"]
    # ForecastRun 落库，带三版本号
    run = (db.query(ForecastRun).filter(ForecastRun.scenario_id == 1)
           .order_by(ForecastRun.id.desc()).first())
    assert run and run.base_version == out["base_version"]
    assert run.lower_version == out["lower_version"]
    assert run.upper_version == out["upper_version"]
