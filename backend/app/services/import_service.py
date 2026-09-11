# -*- coding: utf-8 -*-
"""前端导入服务：上传现金流表格 → 重建基础数据（中性 + 克隆乐观/悲观）

从 seed_from_excel.py 抽出的可复用逻辑，供
POST /api/v1/imports/rebuild 调用。幂等：重复导入就地重建「中性」v1，
克隆三方案对齐 2028-12 界。传入的 db session 为请求级会话（生产=Postgres），
不依赖本地 SQLite 路径或全局 SessionLocal。

事务边界：本模块内部只 flush，全流程在 rebuild_from_excel 末尾单次 commit；
任一步异常由调用方（imports.py 端点）rollback，整体回滚不留半重建态。

与脚本差异：
- 路径参数化（xls_path/report_xlsx），而非硬编码 ../docs/...
- 在传入 db 上执行；异常由调用方处理（端点捕获回滚）
"""
from __future__ import annotations

import json
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.engine.calculator import Params, run
from app.engine.excel_import import import_xls
from app.models.financial import Cell, ModelVersion, Scenario
from app.models.forecast import SalesActual
from app.services.fin_report import parse_report
from app.services.recalc_service import merge_params

SRC_NAME = "中性"
# 导入即差异化：克隆时对未来期销量套 ±20% 后重跑引擎（预算页可再细化）
CLONES = [
    ("乐观", "中性情景副本 · 乐观方案（未来期销量 ×1.2，预算页可再细化）", Decimal("1.2")),
    ("悲观", "中性情景副本 · 悲观方案（未来期销量 ×0.8，预算页可再细化）", Decimal("0.8")),
]
# 情景销量假设仅作用于未来期；已发生月（≤ 该界）保留中性实际值
SCALE_FROM_PERIOD = "2026-09"
QTY_KEYS = ("qty.online", "qty.offline")

# 已发生月（发售起点 2026-07 起）；真实销量到位后逐月追加，预测只从 sales_actuals 读历史
ACTUAL_MONTHS = ["2026-07", "2026-08"]


def _seed_actuals(db: Session, scenario: Scenario) -> int:
    """已发生月销量 → sales_actuals（幂等 upsert，source=seed）

    - 期间轴内月份（2026-08 起）：从「中性」v1 网格取 qty.online/offline
    - 轴外前置历史（2026-07，报表营业收入≈0）：直接写 qty=0 行
    """
    rows = (db.query(Cell)
            .filter(Cell.scenario_id == scenario.id, Cell.model_version == 1,
                    Cell.row_key.in_(["qty.online", "qty.offline"]),
                    Cell.period.in_(ACTUAL_MONTHS)).all())
    by_key_period = {(c.row_key, c.period): c for c in rows}
    n = 0
    for month in ACTUAL_MONTHS:
        for channel, row_key in (("online", "qty.online"), ("offline", "qty.offline")):
            cell = by_key_period.get((row_key, month))
            units = cell.value if cell else str(Decimal("0"))  # 轴外前置历史：0 销量
            existing = (db.query(SalesActual)
                        .filter(SalesActual.period == month,
                                SalesActual.channel == channel).first())
            if existing:
                existing.units, existing.source = units, "seed"
            else:
                db.add(SalesActual(period=month, channel=channel, units=units,
                                   source="seed", note="发售起点种子"))
            n += 1
    db.flush()
    return n


def _clone(db: Session, src: Scenario, name: str, desc: str,
           factor: Decimal, periods: list[str]) -> tuple[str, int] | None:
    """克隆源情景为差异化方案：未来期销量 ×factor 后重跑引擎 → (name, cells)。

    差异只加在未来期（≥ SCALE_FROM_PERIOD）；已发生月保留中性实际销量。
    重跑引擎使销售额/回款/现金流等下游行同步反映销量变化，语义与预算页保存一致。
    factor==1 时退化为逐格克隆（不重算）。复用已存在的克隆 Scenario 行
    （由 _reset_clones 先清空其 versions/cells），故重导入会刷新差异化。
    """
    latest = (db.query(ModelVersion)
              .filter(ModelVersion.scenario_id == src.id)
              .order_by(ModelVersion.version_no.desc()).first())
    if not latest:
        return None

    # 从源版本快照还原 params/inputs，对未来期销量套系数后重算
    params = merge_params(json.loads(latest.params_json or "{}"), None)
    inputs = {k: {p: Decimal(str(val)) for p, val in per.items()}
              for k, per in json.loads(latest.inputs_json or "{}").items()}
    for qk in QTY_KEYS:
        if qk in inputs:
            for p in inputs[qk]:
                if p >= SCALE_FROM_PERIOD:
                    inputs[qk][p] = inputs[qk][p] * factor
    grid = run(periods, params, inputs)

    dst = db.query(Scenario).filter(Scenario.name == name).first()
    if dst:
        dst.description, dst.is_active = desc, False
    else:
        dst = Scenario(name=name, description=desc, is_active=False,
                       created_by=src.created_by)
        db.add(dst)
    db.flush()
    inputs_snapshot = json.dumps(inputs, ensure_ascii=False, default=lambda o: str(o))
    db.add(ModelVersion(
        scenario_id=dst.id, version_no=1,
        comment=f"克隆自「{SRC_NAME}」v{latest.version_no}；未来期销量 ×{factor}",
        source="import",
        params_json=latest.params_json, inputs_json=inputs_snapshot,
        created_by=src.created_by,
    ))
    cells = [
        Cell(scenario_id=dst.id, model_version=1, period=p,
             row_key=row_key, value=str(cell["value"]), source=cell["source"])
        for row_key, per in grid.items()
        for p, cell in per.items()
    ]
    db.bulk_save_objects(cells)
    db.flush()
    return name, len(cells)


def _reset_clones(db: Session) -> int:
    """就地清空「乐观/悲观」的 versions/cells（保留 Scenario 行与 id）→ 清理条数。

    使重导入能按最新中性 + ±20% 逻辑重建克隆，而非保留旧平克隆。
    只 flush 不 commit —— 与 rebuild_from_excel 同属一个事务，失败可整体回滚。
    """
    cleared = 0
    for name, _desc, _f in CLONES:
        dst = db.query(Scenario).filter(Scenario.name == name).first()
        if not dst:
            continue
        cleared += db.query(Cell).filter(Cell.scenario_id == dst.id).delete(
            synchronize_session=False)
        db.query(ModelVersion).filter(ModelVersion.scenario_id == dst.id).delete(
            synchronize_session=False)
    db.flush()
    return cleared


def rebuild_from_excel(db: Session, xls_path: str | Path,
                       report_xlsx: str | Path,
                       user_id: int | None = None) -> dict:
    """读取两个表格 → 重建基础数据（中性 v1 + 乐观/悲观克隆）→ 统计摘要。

    幂等：就地重建「中性」（复用 Scenario 行、清空其 cells/versions），
    避免 delete+reinsert 令自增 id 漂移；克隆三方案同样对齐新界。
    """
    imp = import_xls(xls_path)
    inputs, periods = imp["inputs"], imp["periods"]
    params = Params()

    # 2026-07 已发生月（前置历史）：从引擎期间轴剥离，按报表实际值锚定
    for row_key in list(inputs):
        inputs[row_key] = {p: v for p, v in inputs[row_key].items()
                           if not p.startswith("2026-07")}

    report = parse_report(report_xlsx)                # 报表实际值
    cash_opening_08 = report["cash_opening_wan"]      # 07-31 货币资金余额 → 08 期初
    exp_07 = report["expenses_wan"]                   # 07 月已发生费用（万）

    # 08 期初现金锚点 = 报表 07-31 实际余额（替代计划 450 万）
    inputs.setdefault("cash.opening", {})["2026-08"] = cash_opening_08
    # 08 推广/办公费：计划 08 列空，按报表 07 实际值近似
    for key, v in exp_07.items():
        inputs.setdefault(key, {})["2026-08"] = v
    # 07 已发生月销量 = 0（报表营业收入 ≈ 0 台）→ actuals 前置历史行
    inputs.setdefault("qty.online", {})["2026-07"] = Decimal("0")
    inputs.setdefault("qty.offline", {})["2026-07"] = Decimal("0")

    grid = run(periods, params, inputs)

    # 就地重置「中性」的版本/单元格并复用同一 Scenario 行
    scenario = db.query(Scenario).filter(Scenario.name == SRC_NAME).first()
    if scenario:
        db.query(Cell).filter(Cell.scenario_id == scenario.id).delete()
        db.query(ModelVersion).filter(ModelVersion.scenario_id == scenario.id).delete()
        scenario.description = "Excel「现金流中性」情景（2026.8 版数据）"
        scenario.is_active = True
        db.flush()
    else:
        scenario = Scenario(name=SRC_NAME,
                            description="Excel「现金流中性」情景（2026.8 版数据）",
                            is_active=True)
        db.add(scenario)
    db.flush()

    params_snapshot = json.dumps(asdict(params), ensure_ascii=False,
                                 default=lambda o: str(o))
    inputs_snapshot = json.dumps(inputs, ensure_ascii=False, default=lambda o: str(o))
    version = ModelVersion(
        scenario_id=scenario.id, version_no=1,
        comment=("Excel 导入；08 期初现金按报表 07-31 余额锚定，08 工资按工资表实际值；"
                 "07 为已发生月前置历史（报表实际费用/0 销量）"),
        source="import",
        params_json=params_snapshot,
        inputs_json=inputs_snapshot,
    )
    db.add(version)
    db.flush()

    cells = []
    for row_key, per in grid.items():
        for p, cell in per.items():
            cells.append(Cell(scenario_id=scenario.id, model_version=1,
                              period=p, row_key=row_key,
                              value=str(cell["value"]), source=cell["source"]))
    db.bulk_save_objects(cells)
    db.flush()

    n_actual = _seed_actuals(db, scenario)

    # 克隆乐观/悲观（先清空旧克隆，再按 ±20% 未来期销量重算重建）
    cleared_clones = _reset_clones(db)
    clone_res = []
    for name, desc, factor in CLONES:
        r = _clone(db, scenario, name, desc, factor, periods)
        if r:
            clone_res.append({"name": r[0], "cells": r[1]})

    # 全流程唯一 commit：以上任一步异常 → 整体回滚（含情景清空），不留半重建态
    db.commit()

    return {
        "scenario_id": scenario.id,
        "cells": len(cells),
        "periods": [periods[0], periods[-1]],
        "period_count": len(periods),
        "actuals": n_actual,
        "cleared_clones": cleared_clones,
        "clones": clone_res,
    }
