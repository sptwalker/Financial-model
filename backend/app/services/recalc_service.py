# -*- coding: utf-8 -*-
"""重算服务：参数快照 + 输入快照 + 用户覆盖 → 引擎重算 → 新版本（阶段 2/3 核心路径）

重算基线 = 上一版本的 inputs_json（原始 Excel 输入 + 引擎推导的月分布基准，含
2028/2029 全年目标摊到各月所需的历史形状）+ 该版本上用户 override 的单元格。
参数 = 上一版本 params_json 快照 + 用户本次提交的增量。
结果：新 ModelVersion（携带新 inputs/params 快照）+ 全量 Cells。
"""
import json
from dataclasses import asdict
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
        if isinstance(v, list):
            out[k] = [_coerce_decimal(x) for x in v]
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
    return Params(**merged)


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

    # 重算基线：优先 inputs_json 快照（含全年目标摊月所需历史形状），否则从网格重建
    inputs = {rk: {p: _coerce_decimal(v) for p, v in per.items()}
              for rk, per in _parse_json(latest.inputs_json).items()}
    if not inputs:
        inputs = rebuild_inputs(cells)
    else:
        # 用户在本版本上 override 过的单元格叠加到基线上
        for c in cells:
            if c.source == "override":
                try:
                    inputs.setdefault(c.row_key, {})[c.period] = Decimal(c.value)
                except Exception:
                    continue
    if not inputs:
        raise ValueError("no_input_cells")

    # 预测回填等：直接覆写输入行（qty.online/offline），并入 inputs_json 快照 → 粘性
    for rk, per in (inputs_override or {}).items():
        inputs.setdefault(rk, {}).update({p: _coerce_decimal(v) for p, v in per.items()})

    # periods 取该版本单元格覆盖的期间全集（原引擎 2026-07..2029-12 连续月度）
    periods = sorted({c.period for c in cells})
    if not periods:
        raise ValueError("no_input_cells")

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
