# -*- coding: utf-8 -*-
"""重算服务测试：v1 基线 → 无参重算逐格一致；参数覆盖按比例生效并保留输入行"""
import json
from dataclasses import asdict
from decimal import Decimal

import pytest

from app.engine.calculator import Params
from app.models.financial import Cell, ModelVersion, Scenario
from app.services.recalc_service import (
    recalc, merge_params, preview_grid, scenario_scale,
)


@pytest.fixture(scope="module")
def db():
    from app.db.session import SessionLocal, init_db
    init_db()
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def seeded(db):
    """重置情景 1 到纯净 v1（幂等）"""
    old = db.query(Scenario).filter(Scenario.id == 1).first()
    if old:
        db.query(Cell).filter(Cell.scenario_id == 1).delete()
        db.query(ModelVersion).filter(ModelVersion.scenario_id == 1).delete()
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


def _latest(db):
    return db.query(ModelVersion).filter(ModelVersion.scenario_id == 1) \
        .order_by(ModelVersion.version_no.desc()).first()


def test_recalc_no_change_is_identical(seeded):
    """无参数变化重算 → 新版本与上一版逐格一致"""
    db = seeded
    r = recalc(db, 1, comment="test: no change")
    assert r["version_no"] == _latest(db).version_no
    v_prev = _grid(db, r["version_no"] - 1)
    v_new = _grid(db, r["version_no"])
    assert v_prev.keys() == v_new.keys()
    assert not [k for k in v_prev if v_prev[k] != v_new[k]]


def test_recalc_price_override_proportional(seeded):
    """改线上售价 → 线上销售额按比例变化；输入行/其他行不变"""
    db = seeded
    base_no = _latest(db).version_no
    base = _grid(db, base_no)
    r = recalc(db, 1, params_override={"price_online": "1999"}, comment="test: price")
    new = _grid(db, r["version_no"])
    p = "sale.online.amount|2026-08"
    assert new[p] == base[p] * Decimal("1999") / Decimal("1799")
    assert new["qty.online|2026-08"] == base["qty.online|2026-08"]
    assert new["exp.salary|2026-08"] == base["exp.salary|2026-08"]
    assert new["sale.offline.amount|2026-08"] == base["sale.offline.amount|2026-08"]


def test_recalc_snapshots_carried_forward(seeded):
    """新版本携带 inputs/params 快照；参数沿用上一版（覆盖后的值也延续）"""
    db = seeded
    prev = _latest(db)
    assert prev.inputs_json and prev.params_json
    r = recalc(db, 1, comment="test: snapshot")
    v = db.query(ModelVersion).filter(ModelVersion.scenario_id == 1,
                                      ModelVersion.version_no == r["version_no"]).first()
    assert json.loads(v.params_json) == json.loads(prev.params_json)
    assert v.inputs_json == prev.inputs_json


def test_merge_params_layering():
    """merge_params：默认 ← 快照 ← 用户增量，逐层覆盖"""
    base = asdict(Params())
    p = merge_params({"price_online": "1999"}, {"price_online": "2099"})
    assert p.price_online == Decimal("2099")
    p2 = merge_params({"price_online": "1999"}, None)
    assert p2.price_online == Decimal("1999")
    assert p2.price_offline == base["price_offline"]


def test_merge_params_ignores_stale_snapshot_keys():
    """旧快照残留的已废弃字段（如 online_mkt_rate）不应让 Params(**) 崩溃，只丢弃"""
    p = merge_params({"price_online": "1999", "online_mkt_rate": "0.3"}, None)
    assert p.price_online == Decimal("1999")
    assert not hasattr(p, "online_mkt_rate")


def test_scenario_scale_identity_for_baseline(seeded):
    """基线情景自己的系数恒为 1"""
    r = scenario_scale(seeded, 1, 1)
    assert Decimal(r["factor"]) == 1
    assert Decimal(r["qty_ratio"]) == 1


def test_scenario_scale_reads_baked_qty_ratio(seeded):
    """导入克隆把系数乘进 qty 行（qty_scale 仍为 1）→ 观测比值应还原出系数

    这是对比页调节系数不叠乘的前提：若只读 params.qty_scale 会得到 1，
    于是在已含 1.2 的情景上再乘 1.3 变成 1.56。
    """
    src = seeded.query(Scenario).filter(Scenario.id == 1).first()
    opt = Scenario(name="_test_乐观", description="t", is_active=False,
                   created_by=src.created_by)
    seeded.add(opt)
    seeded.flush()
    latest = _latest(seeded)
    inputs = json.loads(latest.inputs_json)
    for qk in ("qty.online", "qty.offline"):
        for p in inputs.get(qk, {}):
            if p >= "2026-09":
                inputs[qk][p] = str(Decimal(str(inputs[qk][p])) * Decimal("1.2"))
    seeded.add(ModelVersion(
        scenario_id=opt.id, version_no=1, comment="test clone ×1.2", source="import",
        params_json=latest.params_json,
        inputs_json=json.dumps(inputs, ensure_ascii=False),
        created_by=src.created_by,
    ))
    seeded.flush()
    # 网格单元格（_load_baseline 要求有 cells）
    for rk, per in preview_grid(seeded, 1, None).items():
        for p, c in per.items():
            seeded.add(Cell(scenario_id=opt.id, model_version=1, period=p,
                            row_key=rk, value=c["value"], source=c["source"]))
    seeded.flush()
    try:
        r = scenario_scale(seeded, opt.id, 1)
        assert Decimal(r["stored_scale"]) == 1          # 克隆没写 qty_scale
        assert Decimal(r["qty_ratio"]).quantize(Decimal("0.0001")) == Decimal("1.2000")
        assert Decimal(r["factor"]).quantize(Decimal("0.0001")) == Decimal("1.2000")
    finally:
        seeded.query(Cell).filter(Cell.scenario_id == opt.id).delete()
        seeded.query(ModelVersion).filter(ModelVersion.scenario_id == opt.id).delete()
        seeded.query(Scenario).filter(Scenario.id == opt.id).delete()
        seeded.commit()


def test_scenario_scale_multiplies_both_representations(db):
    """预算页写法（qty 中性 + qty_scale=1.2）与克隆写法（qty 已乘）应得到同一倍数"""
    seeded_ids = [s.id for s in db.query(Scenario).filter(Scenario.name == "中性").all()]
    assert seeded_ids, "无中性情景"
    src_id = seeded_ids[0]
    latest = (db.query(ModelVersion).filter(ModelVersion.scenario_id == src_id)
              .order_by(ModelVersion.version_no.desc()).first())
    if not latest:
        pytest.skip("中性情景无版本")

    params = json.loads(latest.params_json or "{}")
    params["qty_scale"] = "1.2"
    other = Scenario(name="_test_预算写法", description="t", is_active=False)
    db.add(other)
    db.flush()
    db.add(ModelVersion(scenario_id=other.id, version_no=1, comment="t", source="recalc",
                        params_json=json.dumps(params, ensure_ascii=False),
                        inputs_json=latest.inputs_json))
    db.flush()
    try:
        # qty 中性（未乘）→ 比值 1，但 qty_scale 1.2 ⇒ 合起来 1.2
        for rk, per in preview_grid(db, src_id, None).items():
            for p, c in per.items():
                db.add(Cell(scenario_id=other.id, model_version=1, period=p,
                            row_key=rk, value=c["value"], source=c["source"]))
        db.flush()
        r = scenario_scale(db, other.id, src_id)
        assert Decimal(r["stored_scale"]) == Decimal("1.2")
        assert Decimal(r["qty_ratio"]).quantize(Decimal("0.0001")) == Decimal("1.0000")
        assert Decimal(r["factor"]).quantize(Decimal("0.0001")) == Decimal("1.2000")
    finally:
        db.query(Cell).filter(Cell.scenario_id == other.id).delete()
        db.query(ModelVersion).filter(ModelVersion.scenario_id == other.id).delete()
        db.query(Scenario).filter(Scenario.id == other.id).delete()
        db.commit()


def test_preview_does_not_persist(seeded):
    """预览端点：叠加 inputs/params 实时算，不建版本；网格反映融资注入"""
    db = seeded
    before = _latest(db).version_no
    p0 = "2026-08"
    grid = preview_grid(db, 1, inputs_override={"cash.financing": {p0: "888"}})
    # 未建新版本
    assert _latest(db).version_no == before
    # 融资行透传，且期末现金较无融资抬升 888
    assert Decimal(grid["cash.financing"][p0]["value"]) == Decimal("888")
    base_grid = preview_grid(db, 1)
    assert (Decimal(grid["cash.closing"][p0]["value"])
            - Decimal(base_grid["cash.closing"][p0]["value"])) == Decimal("888")


def test_recalc_inputs_override_sticky(seeded):
    """recalc 带 inputs_override → 新版本落库且融资值粘性写入网格"""
    db = seeded
    r = recalc(db, 1, inputs_override={"cash.financing": {"2026-09": "500"}},
               comment="test: financing")
    new = _grid(db, r["version_no"])
    assert new["cash.financing|2026-09"] == Decimal("500")


# ---------- 错误路径与脏数据容错 ----------

def test_recalc_raises_on_missing_scenario_and_version(db):
    """不存在的场景 / 无版本 → 抛 ValueError，由路由层翻译成 404"""
    with pytest.raises(ValueError, match="scenario_not_found"):
        recalc(db, 987654, comment="test: missing")
    with pytest.raises(ValueError, match="scenario_not_found"):
        preview_grid(db, 987654)


def test_recalc_raises_no_version_for_empty_scenario(db):
    """新建情景无版本 → no_version（而非 500）"""
    from app.models.financial import Scenario
    sc = Scenario(name="empty-for-recalc-test")
    db.add(sc)
    db.commit()
    try:
        with pytest.raises(ValueError, match="no_version"):
            recalc(db, sc.id, comment="test: no version")
    finally:
        db.delete(sc)
        db.commit()


def test_parse_json_tolerates_corrupt_and_non_dict(seeded):
    """快照 JSON 损坏 / 不是对象 → 回退空 dict，不抛异常（旧版本兼容）"""
    from app.services.recalc_service import _parse_json
    assert _parse_json(None) == {}
    assert _parse_json("") == {}
    assert _parse_json("{不是合法 JSON") == {}
    assert _parse_json("[1,2,3]") == {}          # 合法 JSON 但非对象
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_rebuild_inputs_skips_dirty_and_non_input_sources(seeded):
    """回退重建：仅收 input/override 源；脏 Decimal 跳过而不中断"""
    from app.services.recalc_service import rebuild_inputs

    class _C:
        def __init__(self, row_key, period, value, source):
            self.row_key, self.period, self.value, self.source = row_key, period, value, source

    cells = [
        _C("qty.online", "2026-08", "10", "input"),
        _C("qty.online", "2026-09", "11", "override"),
        _C("sale.online.amount", "2026-08", "99999", "engine"),   # 非输入源 → 不收
        _C("qty.offline", "2026-08", "坏数据", "input"),           # 脏值 → 跳过
    ]
    out = rebuild_inputs(cells)
    assert set(out) == {"qty.online"}
    assert out["qty.online"]["2026-09"] == Decimal("11")
    assert "2026-08" in out["qty.online"]

