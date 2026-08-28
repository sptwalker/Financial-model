# -*- coding: utf-8 -*-
"""前端导入服务：上传现金流表格 → 重建基础数据（中性 + 克隆乐观/悲观）

从 seed_from_excel.py / seed_budget_scenarios.py 抽出的可复用逻辑，供
POST /api/v1/imports/rebuild 调用。幂等：重复导入就地重建「中性」v1，
克隆三方案对齐 2028-12 界。传入的 db session 为请求级会话（生产=Postgres），
不依赖本地 SQLite 路径或全局 SessionLocal。

与脚本差异：
- 路径参数化（xls_path/payroll_xlsx/report_xlsx），而非硬编码 ../docs/...
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
from app.engine.reconcile import payroll_total_payable
from app.models.financial import Cell, ModelVersion, Scenario
from app.models.forecast import SalesActual
from app.services.fin_report import parse_report

SRC_NAME = "中性"
CLONES = [
    ("乐观", "中性情景副本 · 乐观方案（预算页可细化销售/成本/投融资）"),
    ("悲观", "中性情景副本 · 悲观方案（预算页可细化销售/成本/投融资）"),
]

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
    db.commit()
    return n


def _clone(db: Session, src: Scenario, name: str, desc: str) -> tuple[str, int] | None:
    """把源情景最新版本克隆为新情景（已存在则跳过）→ (name, cells)"""
    if db.query(Scenario).filter(Scenario.name == name).first():
        return None  # 已存在，跳过（不重复克隆）
    latest = (db.query(ModelVersion)
              .filter(ModelVersion.scenario_id == src.id)
              .order_by(ModelVersion.version_no.desc()).first())
    if not latest:
        return None
    cells = (db.query(Cell)
             .filter(Cell.scenario_id == src.id, Cell.model_version == latest.version_no).all())
    dst = Scenario(name=name, description=desc, is_active=False, created_by=src.created_by)
    db.add(dst)
    db.flush()
    db.add(ModelVersion(
        scenario_id=dst.id, version_no=1,
        comment=f"克隆自「{SRC_NAME}」v{latest.version_no}",
        source="import",
        params_json=latest.params_json, inputs_json=latest.inputs_json,
        created_by=src.created_by,
    ))
    db.bulk_save_objects([
        Cell(scenario_id=dst.id, model_version=1, period=c.period,
             row_key=c.row_key, value=c.value, source=c.source)
        for c in cells
    ])
    db.commit()
    return name, len(cells)


def _truncate_existing_clones(db: Session) -> int:
    """克隆已存在时清理 2029 期单元格（预算法定期界 2028-12 起）→ 删除条数。

    中性重种子后，已有「乐观/悲观」仍带着旧 41 期网格；本函数把 2029 期的
    单元格就地删除，使其与 2028-12 界对齐（版本行/inputs 快照保留，旧期间
    自然越出期间轴不再生效）。
    """
    deleted = 0
    for name, _desc in CLONES:
        dst = db.query(Scenario).filter(Scenario.name == name).first()
        if not dst:
            continue
        n = (db.query(Cell)
             .filter(Cell.scenario_id == dst.id, Cell.period >= "2029-01")
             .delete(synchronize_session=False))
        deleted += n
    if deleted:
        db.commit()
    return deleted


def rebuild_from_excel(db: Session, xls_path: str | Path,
                       payroll_xlsx: str | Path, report_xlsx: str | Path,
                       user_id: int | None = None) -> dict:
    """读取三个表格 → 重建基础数据（中性 v1 + 乐观/悲观克隆）→ 统计摘要。

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

    salary_07 = payroll_total_payable(payroll_xlsx)   # 工资表应付合计（万）
    report = parse_report(report_xlsx)                # 报表实际值
    cash_opening_08 = report["cash_opening_wan"]      # 07-31 货币资金余额 → 08 期初
    exp_07 = report["expenses_wan"]                   # 07 月已发生费用（万）

    # 08 期初现金锚点 = 报表 07-31 实际余额（替代计划 450 万）
    inputs.setdefault("cash.opening", {})["2026-08"] = cash_opening_08
    # 08 工资 = 工资表实际应付合计
    inputs.setdefault("exp.salary", {})["2026-08"] = salary_07
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
        db.commit()
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
    db.commit()

    n_actual = _seed_actuals(db, scenario)

    # 克隆乐观/悲观（先清理旧 2029 期，再按需克隆）
    truncated = _truncate_existing_clones(db)
    clone_res = []
    for name, desc in CLONES:
        r = _clone(db, scenario, name, desc)
        if r:
            clone_res.append({"name": r[0], "cells": r[1]})

    return {
        "scenario_id": scenario.id,
        "cells": len(cells),
        "periods": [periods[0], periods[-1]],
        "period_count": len(periods),
        "actuals": n_actual,
        "truncated_2029": truncated,
        "clones": clone_res,
    }
