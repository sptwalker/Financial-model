# -*- coding: utf-8 -*-
"""重算服务：参数快照 + 输入快照 + 用户覆盖 → 引擎重算 → 新版本（阶段 2/3 核心路径）

重算基线 = 上一版本的 inputs_json（原始 Excel 输入 + 引擎推导的月分布基准，含
2028 全年目标摊到各月所需的历史形状）+ 该版本上用户 override 的单元格。
参数 = 上一版本 params_json 快照 + 用户本次提交的增量。
结果：新 ModelVersion（携带新 inputs/params 快照）+ 全量 Cells。
"""
import json
from dataclasses import asdict, fields
from decimal import Decimal

from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from app.engine.calculator import run, Params
from app.models.financial import Scenario, ModelVersion, Cell

# 参与重建输入的源：Excel 导入输入 + 用户覆盖；引擎计算行跳过
_INPUT_SOURCES = {"input", "override"}


def _parse_json(raw: str | None) -> dict:
    """版本快照 JSON → dict（容错：旧版本/损坏 JSON 回退空）"""
    try:
        data = json.loads(raw) if raw else {}
        return data if isinstance(data, dict) else {}
    except (ValueError, TypeError):
        return {}


def _coerce_decimal(value) -> Decimal:
    return Decimal(str(value))


def _coerce_params(data: dict) -> dict:
    """把参数 dict 的数值字段转 Decimal；list 字段逐元素转（回款权重等）；purchase_lag 保持 int"""
    out = {}
    for k, v in data.items():
        if k == "financing_rounds":
            out[k] = v  # 轮次元数据 [{name, period, amount}]：引擎不读，原样透传
        elif isinstance(v, list):
            out[k] = [_coerce_decimal(x) for x in v]
        elif isinstance(v, bool):
            out[k] = v
        elif k == "purchase_lag":
            out[k] = int(v)
        else:
            out[k] = _coerce_decimal(v)
    return out


def merge_params(snapshot: dict | None, override: dict | None) -> Params:
    """默认参数 ← 版本快照 ← 用户本次修改，逐层覆盖；返回 Params 实例"""
    base = asdict(Params())
    merged = dict(base)
    if snapshot:
        merged.update(_coerce_params(snapshot))
    if override:
        merged.update(_coerce_params(override))
    # 丢弃引擎已废弃/改名的历史字段（旧快照可能残留，如 online_mkt_rate），否则 Params(**) 报错
    valid = {f.name for f in fields(Params)}
    return Params(**{k: v for k, v in merged.items() if k in valid})


def rebuild_inputs(cells: list[Cell]) -> dict[str, dict[str, Decimal]]:
    """回退方案：从 cells 重建 inputs（仅 input/override 源的行）"""
    inputs: dict[str, dict[str, Decimal]] = {}
    for c in cells:
        if c.source not in _INPUT_SOURCES:
            continue
        try:
            value = Decimal(c.value)
        except Exception:
            continue  # 脏数据跳过
        inputs.setdefault(c.row_key, {})[c.period] = value
    return inputs


def _load_baseline(db: Session, scenario_id: int) -> tuple[ModelVersion, dict, list[str]]:
    """加载情景最新版本 → 重算基线 (latest, inputs, periods)。recalc 与 preview 共用。

    inputs 基线 = inputs_json 快照（含全年目标摊月历史形状），否则从网格 input/override 重建；
    并把本版本上 override 的单元格叠加到基线。periods = 该版本单元格覆盖的期间全集。
    """
    scenario = db.query(Scenario).filter(Scenario.id == scenario_id).first()
    if not scenario:
        raise ValueError("scenario_not_found")
    latest = (db.query(ModelVersion)
              .filter(ModelVersion.scenario_id == scenario_id)
              .order_by(ModelVersion.version_no.desc()).first())
    if not latest:
        raise ValueError("no_version")

    cells = (db.query(Cell)
             .filter(Cell.scenario_id == scenario_id,
                     Cell.model_version == latest.version_no).all())
    if not cells:
        raise ValueError("no_cells")

    inputs = {rk: {p: _coerce_decimal(v) for p, v in per.items()}
              for rk, per in _parse_json(latest.inputs_json).items()}
    if not inputs:
        inputs = rebuild_inputs(cells)
    else:
        for c in cells:
            if c.source == "override":
                try:
                    inputs.setdefault(c.row_key, {})[c.period] = Decimal(c.value)
                except Exception:
                    continue
    if not inputs:
        raise ValueError("no_input_cells")

    periods = sorted({c.period for c in cells})
    if not periods:
        raise ValueError("no_input_cells")
    return latest, inputs, periods


def _apply_inputs_override(inputs: dict, inputs_override: dict | None) -> None:
    """把输入行增量 {row_key: {period: 值}} 叠加到基线 inputs（原地）"""
    for rk, per in (inputs_override or {}).items():
        inputs.setdefault(rk, {}).update({p: _coerce_decimal(v) for p, v in per.items()})


def preview_grid(db: Session, scenario_id: int, params_override: dict | None = None,
                 inputs_override: dict | None = None) -> dict:
    """非持久化预览：基线 ← 参数/输入增量 → run() → 网格（形状同 get_grid 的 cells，不写库）"""
    latest, inputs, periods = _load_baseline(db, scenario_id)
    _apply_inputs_override(inputs, inputs_override)
    params = merge_params(_parse_json(latest.params_json), params_override)
    grid = run(periods, params, inputs)
    return {row: {p: {"value": str(c["value"]), "source": c["source"]}
                  for p, c in per.items()}
            for row, per in grid.items()}


# 未来期销量系数的观测起点：已发生月（≤ 该界）三情景一致，不参与系数比较
_SCALE_FROM_PERIOD = "2026-09"
_QTY_KEYS = ("qty.online", "qty.offline")


def scenario_scale(db: Session, scenario_id: int,
                   baseline_id: int | None = None) -> dict:
    """情景的「未来期销量系数」——相对基线情景的倍数（基线缺省取第一个情景）。

    系数在库里没有单一存放处，两种写法并存，故两者相乘：
    - 导入克隆：系数直接乘进了 qty 输入行，params.qty_scale 仍是 1
    - 预算页保存：qty 输入行保持中性，系数写在 params.qty_scale
    相乘后两种写法都得到正确倍数（克隆 1.2×1=1.2；预算 1×1.2=1.2）。

    仅在基线与本情景共有的未来期上比较，避免期间轴不一致时算偏。
    """
    latest, inputs, periods = _load_baseline(db, scenario_id)
    params = merge_params(_parse_json(latest.params_json), None)
    stored = Decimal(str(params.qty_scale))

    if baseline_id is None or baseline_id == scenario_id:
        return {"scenario_id": scenario_id, "stored_scale": str(stored),
                "qty_ratio": "1", "factor": str(stored)}

    b_latest, b_inputs, b_periods = _load_baseline(db, baseline_id)
    fwd = [p for p in sorted(set(periods) & set(b_periods)) if p >= _SCALE_FROM_PERIOD]
    num = den = Decimal(0)
    for key in _QTY_KEYS:
        for p in fwd:
            cur, base = inputs.get(key, {}).get(p), b_inputs.get(key, {}).get(p)
            if cur is None or base is None:
                continue
            num += Decimal(str(cur))
            den += Decimal(str(base))
    # 基线销量为 0（或无共有未来期）→ 比值无意义，只用已存系数
    ratio = (num / den) if den else Decimal(1)
    return {"scenario_id": scenario_id, "stored_scale": str(stored),
            "qty_ratio": str(ratio), "factor": str(ratio * stored)}


def recalc(db: Session, scenario_id: int, params_override: dict | None = None,
           comment: str | None = None, user_id: int | None = None,
           inputs_override: dict | None = None) -> dict:
    """核心：加载情景 + 最新版本 → 快照合并 → 重算 → 持久化新版本 → 返回摘要

    并发安全：版本号冲突（两人同时基于 vN 重算）时重读最新版本重试，最多 3 次。
    inputs_override: {row_key: {period: Decimal}} 直接覆写输入行（预测回填 qty 用），
    随 inputs_json 快照持久 → 回填是粘性的。
    """
    for _ in range(3):
        try:
            return _recalc_once(db, scenario_id, params_override, comment, user_id,
                                inputs_override)
        except ValueError as e:
            if str(e) in ("version_conflict_retry", "db_locked_retry"):
                continue
            raise
    raise ValueError("version_conflict_retry")


def _recalc_once(db: Session, scenario_id: int, params_override: dict | None,
                 comment: str | None, user_id: int | None,
                 inputs_override: dict | None = None) -> dict:
    latest, inputs, periods = _load_baseline(db, scenario_id)

    # 预测回填/预算编辑：直接覆写输入行，并入 inputs_json 快照 → 粘性
    _apply_inputs_override(inputs, inputs_override)

    params = merge_params(_parse_json(latest.params_json), params_override)
    grid = run(periods, params, inputs)

    # 并发重算竞态：两人同时基于 vN 重算都会取 new_no = N+1，
    # 唯一约束 uq_model_version 冲突 → 捕获后重读最新版本重试
    new_no = latest.version_no + 1
    version = ModelVersion(
        scenario_id=scenario_id, version_no=new_no,
        comment=(comment or f"重算（基于版本 {latest.version_no}）"),
        source="engine",
        params_json=json.dumps(asdict(params), ensure_ascii=False,
                               default=lambda o: str(o)),
        inputs_json=json.dumps(inputs, ensure_ascii=False, default=lambda o: str(o)),
        created_by=user_id,
    )
    db.add(version)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise ValueError("version_conflict_retry")
    except OperationalError:
        # SQLite 并发写锁（database is locked）：回滚后重试
        db.rollback()
        raise ValueError("db_locked_retry")

    rows = []
    for row_key, per in grid.items():
        for p, cell in per.items():
            rows.append(Cell(scenario_id=scenario_id, model_version=new_no,
                             period=p, row_key=row_key,
                             value=str(cell["value"]), source=cell["source"]))
    db.bulk_save_objects(rows)
    db.commit()

    return {
        "scenario_id": scenario_id,
        "version_no": new_no,
        "source": "engine",
        "cell_count": len(rows),
        "comment": version.comment,
        "params": asdict(params),
    }
