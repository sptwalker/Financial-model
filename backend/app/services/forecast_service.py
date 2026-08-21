# -*- coding: utf-8 -*-
"""预测服务（阶段 3 核心）：历史累积 → 方法阶梯 → 序列+CI → 回填引擎

现实校准（关键）：2026-07 为发售起点（已发生月前置历史，报表实际≈0 台），
引擎期间轴 2026-08 起，有效历史 ≈ 1 月。故：
- 历史唯一来源 = sales_actuals 表（绝不读模型网格，网格是前瞻计划非历史）；
- 方法阶梯当前只有 plan_anchored 可达（seasonal_naive≥12月、holt_winters≥24、sarima≥36）；
- 形状取自"计划曲线"（完整前瞻形状），历史推形状一律过 robust_shape 兜底，
  直接绕开引擎 seasonal_weights 在稀疏历史下把年度目标塌进个别月的 bug。

序列点：{period, yhat, lower, upper, online, offline}，值均 Decimal。
statsmodels 惰性 import（HW/SARIMA 函数体内），缺失只影响高档、不炸启动、不拖低档。
"""
import json
from decimal import Decimal

from sqlalchemy.orm import Session

from app.engine.calculator import periods_between, monthlyize
from app.models.financial import Cell, ModelVersion
from app.models.forecast import SalesActual, ForecastRun
from app.services.recalc_service import recalc, _coerce_decimal

# 方法阶梯门槛（有效非零历史月）
MIN_SEASONAL = 12
MIN_HW = 24
MIN_SARIMA = 36
_LADDER = ["plan_anchored", "seasonal_naive", "holt_winters", "sarima"]
_ZERO = Decimal("0")


# ---------- 小工具（纯 Decimal，避免 float 漂移） ----------

def _sqrt(x: Decimal) -> Decimal:
    return Decimal(x).sqrt() if x > 0 else _ZERO


def _mean(xs: list[Decimal]) -> Decimal:
    return sum(xs, _ZERO) / len(xs) if xs else _ZERO


def _std(xs: list[Decimal]) -> Decimal:
    """样本标准差（n<2 → 0）"""
    if len(xs) < 2:
        return _ZERO
    m = _mean(xs)
    var = sum(((x - m) ** 2 for x in xs), _ZERO) / (len(xs) - 1)
    return _sqrt(var)


def _metrics(pairs: list[tuple[Decimal, Decimal]]) -> dict:
    """pairs=[(actual, pred)] → sMAPE(%)/MAE/RMSE（值转 str 便于 JSON）"""
    n = len(pairs)
    smape = sum((2 * abs(a - p) / (abs(a) + abs(p)) if (abs(a) + abs(p)) > 0 else _ZERO
                 for a, p in pairs), _ZERO) / n * 100
    mae = sum((abs(a - p) for a, p in pairs), _ZERO) / n
    rmse = _sqrt(sum(((a - p) ** 2 for a, p in pairs), _ZERO) / n)
    return {"smape": str(smape), "mae": str(mae), "rmse": str(rmse), "n": n}


# ---------- 历史 ----------

def load_actuals(db: Session) -> dict[str, dict[str, Decimal]]:
    """唯一历史来源：sales_actuals → {'online':{period:units},'offline':{...}}"""
    out = {"online": {}, "offline": {}}
    for a in db.query(SalesActual).all():
        if a.channel in out:
            out[a.channel][a.period] = _coerce_decimal(a.units)
    return out


def _total_actual(actuals: dict) -> dict[str, Decimal]:
    """按期合计线上+线下"""
    periods = set(actuals["online"]) | set(actuals["offline"])
    return {p: actuals["online"].get(p, _ZERO) + actuals["offline"].get(p, _ZERO)
            for p in periods}


def effective_months(total_by_period: dict[str, Decimal]) -> int:
    """有效历史月数 = 总量>0 的月数"""
    return sum(1 for v in total_by_period.values() if v > 0)


# ---------- 选档 ----------

def choose_method(n_eff: int, requested: str | None = None) -> tuple[str, str]:
    """自动选最高可达档；用户 requested 永远honored（超门槛则在 reason 警示不可靠）"""
    if n_eff >= MIN_SARIMA:
        auto = "sarima"
    elif n_eff >= MIN_HW:
        auto = "holt_winters"
    elif n_eff >= MIN_SEASONAL:
        auto = "seasonal_naive"
    else:
        auto = "plan_anchored"
    if requested is None or requested == auto:
        return auto, f"有效历史 {n_eff} 月 → 自动选择 {auto}"
    if requested not in _LADDER:
        return auto, f"未知方法 {requested}，改用 {auto}"
    if _LADDER.index(requested) <= _LADDER.index(auto):
        return requested, f"按请求使用 {requested}（自动档 {auto}）"
    return requested, f"请求 {requested} 超历史支持（有效 {n_eff} 月 < 门槛），结果不可靠，建议 {auto}"


# ---------- 形状兜底（直接绕开 seasonal_weights 塌缩 bug） ----------

def robust_shape(values, alpha: Decimal = Decimal("0.5"), min_full: int = 12) -> list[Decimal]:
    """归一化季节形状：有效月≥min_full 用历史形状；0<有效<min_full 混合均匀×(1-α)；=0 纯均匀"""
    vals = [Decimal(str(v)) for v in values]
    n = len(vals)
    if n == 0:
        return []
    uniform = [Decimal(1) / n] * n
    eff = sum(1 for v in vals if v > 0)
    total = sum(vals, _ZERO)
    if total <= 0 or eff == 0:
        return uniform
    if eff >= min_full:
        return [v / total for v in vals]
    a = Decimal(str(alpha))
    sparse = [v / total for v in vals]
    blended = [a * s + (1 - a) * u for s, u in zip(sparse, uniform)]
    bt = sum(blended, _ZERO)
    return [b / bt for b in blended]  # 兜底重归一（防浮点/舍入）


# ---------- 各档预测（返回 [{period,yhat,lower,upper}]，总量口径） ----------

def forecast_plan_anchored(total_actual: dict, plan_curve: dict, horizon: list[str],
                           band_floor: Decimal = Decimal("0.35")) -> list[dict]:
    """形状=计划曲线；水平=Σ重叠月actual/Σ重叠月plan（clamp[0.5,2]）re-level 未来计划；
    已发生月直接用 actual；CI=经验残差带，不足则 yhat×(1±band_floor·√h) 标数据不足。"""
    overlap = [p for p in horizon
               if total_actual.get(p, _ZERO) > 0 and plan_curve.get(p, _ZERO) > 0]
    sum_a = sum((total_actual[p] for p in overlap), _ZERO)
    sum_p = sum((plan_curve[p] for p in overlap), _ZERO)
    level = (sum_a / sum_p) if sum_p > 0 else Decimal("1")
    level = min(max(level, Decimal("0.5")), Decimal("2"))
    ratios = [total_actual[p] / plan_curve[p] for p in overlap]
    rel_band = (_std(ratios) / _mean(ratios)) if len(ratios) >= 3 and _mean(ratios) > 0 else None

    series = []
    for h, p in enumerate(horizon, start=1):
        if total_actual.get(p, _ZERO) > 0:                     # 已发生月：actual 确定，零带
            y = total_actual[p]
            series.append({"period": p, "yhat": y, "lower": y, "upper": y})
            continue
        y = plan_curve.get(p, _ZERO) * level
        spread = (rel_band if rel_band is not None else band_floor) * _sqrt(Decimal(h))
        series.append({"period": p, "yhat": y,
                       "lower": max(_ZERO, y * (1 - spread)), "upper": y * (1 + spread)})
    return series


def forecast_seasonal_naive(total_actual: dict, horizon: list[str],
                            band_floor: Decimal = Decimal("0.35")) -> list[dict]:
    """季节朴素：同月最近一次观测，缺则整体均值；band 用 floor（≥12月才解锁）"""
    by_month: dict[int, list[Decimal]] = {}
    for p in sorted(total_actual):
        by_month.setdefault(int(p[5:7]), []).append(total_actual[p])
    overall = _mean(list(total_actual.values()))
    series = []
    for h, p in enumerate(horizon, start=1):
        seq = by_month.get(int(p[5:7]))
        y = seq[-1] if seq else overall
        spread = band_floor * _sqrt(Decimal(h))
        series.append({"period": p, "yhat": y,
                       "lower": max(_ZERO, y * (1 - spread)), "upper": y * (1 + spread)})
    return series


def forecast_holt_winters(total_actual: dict, horizon: list[str]) -> list[dict]:
    """Holt-Winters（statsmodels 惰性）——历史接近24月再装 statsmodels 才可达"""
    try:
        from statsmodels.tsa.holtwinters import ExponentialSmoothing
    except ImportError as e:
        raise RuntimeError("holt_winters 需要 statsmodels（历史接近24月时再安装）") from e
    ys = [float(total_actual[p]) for p in sorted(total_actual)]
    fit = ExponentialSmoothing(ys, trend="add", seasonal="add",
                               seasonal_periods=12).fit()
    fc = fit.forecast(len(horizon))
    resid = _std([Decimal(str(r)) for r in fit.resid]) if len(ys) > 2 else _ZERO
    series = []
    for h, (p, y) in enumerate(zip(horizon, fc), start=1):
        yd = Decimal(str(y))
        band = resid * _sqrt(Decimal(h))
        series.append({"period": p, "yhat": yd,
                       "lower": max(_ZERO, yd - band), "upper": yd + band})
    return series


def forecast_sarima(total_actual: dict, horizon: list[str]) -> list[dict]:
    raise NotImplementedError("SARIMA 未启用（需≥36月历史）")


# ---------- 回测（rolling-origin 一步向前） ----------

def _one_step(train: dict[str, Decimal], target: str, method: str):
    """单期预测：仅纯 Python 档（seasonal_naive）可回测；其余返回 None（数据解锁后再扩）。

    ponytail: plan_anchored/HW 的逐期回测需各原点计划曲线/重拟合，历史<6月永远走"数据不足"，
    真正解锁（≥12月）时首个可回测的就是 seasonal_naive，故只实现它，其余 None。
    """
    if method != "seasonal_naive":
        return None
    m = int(target[5:7])
    same = [train[p] for p in sorted(train) if int(p[5:7]) == m]
    if same:
        return same[-1]
    return _mean(list(train.values())) if train else None


def backtest(total_actual: dict, method: str, min_train: int = 6, step: int = 1) -> dict:
    """rolling-origin 一步向前 → sMAPE/MAE/RMSE；数据不足则显式返回原因"""
    periods = sorted(total_actual)
    insufficient = {"reason": "数据不足，无法回测", "smape": None, "mae": None,
                    "rmse": None, "n": 0}
    if len(periods) < min_train + 1:
        return insufficient
    pairs = []
    for i in range(min_train, len(periods), step):
        train = {p: total_actual[p] for p in periods[:i]}
        pred = _one_step(train, periods[i], method)
        if pred is not None:
            pairs.append((total_actual[periods[i]], pred))
    return _metrics(pairs) if pairs else insufficient


# ---------- 渠道拆分 / 缩放 ----------

def split_ratio(actuals: dict, plan_online_sum: Decimal, plan_offline_sum: Decimal,
                n_eff: int, min_actual: int = 3) -> Decimal:
    """线上占比：≥min_actual 有效月用实际累计占比，否则计划占比（div0 → 0.5）"""
    on = sum(actuals["online"].values(), _ZERO)
    off = sum(actuals["offline"].values(), _ZERO)
    if n_eff >= min_actual and (on + off) > 0:
        return on / (on + off)
    tot = plan_online_sum + plan_offline_sum
    return (plan_online_sum / tot) if tot > 0 else Decimal("0.5")


def channel_split(series: list[dict], ratio: Decimal) -> list[dict]:
    """按 ratio 把 yhat 拆成 online/offline（原地写入每点）"""
    for pt in series:
        pt["online"] = pt["yhat"] * ratio
        pt["offline"] = pt["yhat"] * (1 - ratio)
    return series


def scale_to_annual(series: list[dict], targets: dict[int, Decimal]) -> list[dict]:
    """按各年目标缩放 yhat/lower/upper（保形，年合计精确，余数入末月，复用 monthlyize）"""
    by_year: dict[int, list[int]] = {}
    for i, pt in enumerate(series):
        by_year.setdefault(int(pt["period"][:4]), []).append(i)
    for year, idxs in by_year.items():
        if year not in targets:
            continue
        target = Decimal(str(targets[year]))
        cur = sum((series[i]["yhat"] for i in idxs), _ZERO)
        w = ([series[i]["yhat"] / cur for i in idxs] if cur > 0
             else [Decimal(1) / len(idxs)] * len(idxs))
        parts = monthlyize(target, w)
        for k, i in enumerate(idxs):
            old = series[i]["yhat"]
            f = (parts[k] / old) if old > 0 else Decimal("1")
            series[i]["yhat"] = parts[k]
            series[i]["lower"] = series[i]["lower"] * f
            series[i]["upper"] = series[i]["upper"] * f
    return series


# ---------- 编排 ----------

def _plan_curve(db: Session, scenario_id: int, horizon: list[str]) -> dict[str, dict]:
    """读最新版本 qty.online/offline cells → {period:{online,offline,total}}（前瞻计划曲线）"""
    latest = (db.query(ModelVersion)
              .filter(ModelVersion.scenario_id == scenario_id)
              .order_by(ModelVersion.version_no.desc()).first())
    if not latest:
        raise ValueError("no_version")
    hset = set(horizon)
    curve = {p: {"online": _ZERO, "offline": _ZERO, "total": _ZERO} for p in horizon}
    rows = (db.query(Cell)
            .filter(Cell.scenario_id == scenario_id,
                    Cell.model_version == latest.version_no,
                    Cell.row_key.in_(["qty.online", "qty.offline"]))
            .all())
    for c in rows:
        if c.period in hset:
            ch = "online" if c.row_key == "qty.online" else "offline"
            curve[c.period][ch] = _coerce_decimal(c.value)
    for p in horizon:
        curve[p]["total"] = curve[p]["online"] + curve[p]["offline"]
    return curve


def _execute(method: str, total_actual: dict, plan_total: dict,
             horizon: list[str]) -> tuple[list[dict], str | None]:
    """执行选定方法；HW/SARIMA 不可用则回退 plan_anchored 并说明"""
    try:
        if method == "seasonal_naive":
            return forecast_seasonal_naive(total_actual, horizon), None
        if method == "holt_winters":
            return forecast_holt_winters(total_actual, horizon), None
        if method == "sarima":
            return forecast_sarima(total_actual, horizon), None
        return forecast_plan_anchored(total_actual, plan_total, horizon), None
    except (NotImplementedError, RuntimeError, ImportError, ValueError) as e:
        return (forecast_plan_anchored(total_actual, plan_total, horizon),
                f"{method} 不可用（{e}），回退 plan_anchored")


def run_forecast(db: Session, scenario_id: int, method: str | None = None,
                 horizon: tuple[str, str] = ("2026-08", "2027-12"),
                 scale_targets: dict | None = None) -> dict:
    """编排（无副作用）：历史 → 选档 → 计划曲线 → 序列 → 拆渠道 → (可选)缩放 → 各档回测"""
    hp = periods_between(horizon[0], horizon[1])
    actuals = load_actuals(db)
    total_actual = _total_actual(actuals)
    n_eff = effective_months(total_actual)
    chosen, reason = choose_method(n_eff, method)

    plan = _plan_curve(db, scenario_id, hp)
    plan_total = {p: plan[p]["total"] for p in hp}
    series, exec_note = _execute(chosen, total_actual, plan_total, hp)
    if exec_note:
        chosen, reason = "plan_anchored", reason + "；" + exec_note

    plan_on = sum((plan[p]["online"] for p in hp), _ZERO)
    plan_off = sum((plan[p]["offline"] for p in hp), _ZERO)
    ratio = split_ratio(actuals, plan_on, plan_off, n_eff)
    if scale_targets:
        scale_to_annual(series, {int(y): v for y, v in scale_targets.items()})
    channel_split(series, ratio)

    candidates = {m: backtest(total_actual, m)
                  for m in ("plan_anchored", "seasonal_naive", "holt_winters")}
    return {"method": chosen, "reason": reason, "n_actual": n_eff,
            "data_sufficient": n_eff >= MIN_SEASONAL,
            "ratio_online": str(ratio), "candidates": candidates, "series": series}


def _to_override(series: list[dict]) -> dict[str, dict[str, Decimal]]:
    """序列 → recalc 的 inputs_override：回填 qty.online/qty.offline"""
    ov = {"qty.online": {}, "qty.offline": {}}
    for pt in series:
        ov["qty.online"][pt["period"]] = _coerce_decimal(pt["online"])
        ov["qty.offline"][pt["period"]] = _coerce_decimal(pt["offline"])
    return ov


def apply_forecast(db: Session, scenario_id: int, base: list[dict], method: str,
                   comment: str | None = None, user_id: int | None = None,
                   lower: list[dict] | None = None,
                   upper: list[dict] | None = None) -> dict:
    """回填 qty + recalc（×1 或 ×3）+ 记 ForecastRun。

    三情景=同情景三版本，按 lower→upper→base 顺序应用（base 中性留 latest）。
    每序列一次 recalc(inputs_override)，qty 随 inputs_json 快照持久（粘性回填）；
    override 仅含 horizon（默认18期）→ 2028/2029 年度目标原样保留、仍由引擎季节曲线月度化。
    """
    tag = comment or "预测"
    lower_v = upper_v = None
    if lower is not None:
        lower_v = recalc(db, scenario_id, inputs_override=_to_override(lower),
                         comment=f"{tag}·悲观", user_id=user_id)["version_no"]
    if upper is not None:
        upper_v = recalc(db, scenario_id, inputs_override=_to_override(upper),
                         comment=f"{tag}·乐观", user_id=user_id)["version_no"]
    base_v = recalc(db, scenario_id, inputs_override=_to_override(base),
                    comment=f"{tag}·中性", user_id=user_id)["version_no"]

    total_actual = _total_actual(load_actuals(db))
    metrics = {m: backtest(total_actual, m)
               for m in ("plan_anchored", "seasonal_naive", "holt_winters")}
    run = ForecastRun(
        scenario_id=scenario_id, method=method,
        horizon_start=base[0]["period"], horizon_end=base[-1]["period"],
        n_actual=effective_months(total_actual),
        metrics_json=json.dumps({"chosen": method, "candidates": metrics},
                                ensure_ascii=False, default=str),
        base_version=base_v, lower_version=lower_v, upper_version=upper_v,
        created_by=user_id,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return {"base_version": base_v, "lower_version": lower_v, "upper_version": upper_v,
            "forecast_run_id": run.id}
