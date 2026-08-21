# -*- coding: utf-8 -*-
"""M2 种子脚本：Excel 中性情景 → 引擎重算 → 写入数据库（情景 + 版本 1 + 单元格网格）

数据来源：
- 现金流测算 2026.8.xls「现金流中性」主表（qty/回款/采购/费用/期初现金/年度目标）
- 2026年7月创想悦动工资表.xlsx 应付合计 → exp.salary 2026-07
  （主表 07 费用明细全空，工资按实际工资表补——对账报告中记为 KNOWN_RULE_DIFF）

用法：从 backend 目录运行 `python scripts/seed_from_excel.py`（幂等：重复运行重置为版本 1）
"""
import json
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import openpyxl  # noqa: E402

from app.engine.excel_import import import_xls  # noqa: E402
from app.engine.calculator import run, Params  # noqa: E402
from app.db.session import SessionLocal, init_db  # noqa: E402
from app.models.financial import Scenario, ModelVersion, Cell  # noqa: E402
from app.models.forecast import SalesActual  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
XLS = BACKEND_DIR.parent / "docs" / "现金流测算 2026.8.xls"
PAYROLL_XLSX = BACKEND_DIR.parent / "docs" / "2026年7月创想悦动工资表.xlsx"

# 已发生月（发售起点 2026-07 起）；真实销量到位后逐月追加，预测只从 sales_actuals 读历史
ACTUAL_MONTHS = ["2026-07", "2026-08"]


def seed_actuals(db) -> int:
    """从「中性」v1 网格取已发生月 qty.online/offline → sales_actuals（幂等 upsert，source=seed）"""
    scenario = db.query(Scenario).filter(Scenario.name == "中性").first()
    if not scenario:
        return 0
    rows = (db.query(Cell)
            .filter(Cell.scenario_id == scenario.id, Cell.model_version == 1,
                    Cell.row_key.in_(["qty.online", "qty.offline"]),
                    Cell.period.in_(ACTUAL_MONTHS)).all())
    n = 0
    for c in rows:
        channel = "online" if c.row_key == "qty.online" else "offline"
        existing = (db.query(SalesActual)
                    .filter(SalesActual.period == c.period,
                            SalesActual.channel == channel).first())
        if existing:
            existing.units, existing.source = c.value, "seed"
        else:
            db.add(SalesActual(period=c.period, channel=channel, units=c.value,
                               source="seed", note="发售起点种子"))
        n += 1
    db.commit()
    return n


def payroll_total_payable(xlsx: Path) -> Decimal:
    """工资表「汇总」sheet 总计行应付工资（万元）"""
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb["汇总"]
    hdr = None
    for row in ws.iter_rows(values_only=True):
        if hdr is None and row and "应付工资" in row:
            hdr = row
            continue
        if hdr is not None and row and row[0] == "总计":
            payable = row[hdr.index("应付工资")]
            return Decimal(str(payable)) / Decimal("10000")
    raise ValueError(f"工资表 {xlsx.name} 未找到总计行/应付工资列")


def main():
    imp = import_xls(XLS)
    inputs, periods = imp["inputs"], imp["periods"]
    params = Params()

    # 07 费用明细 Excel 全空：工资按实际工资表补（174.16 万），其余费用行保持空（引擎按 0）
    salary_07 = payroll_total_payable(PAYROLL_XLSX)
    inputs.setdefault("exp.salary", {})["2026-07"] = salary_07
    print(f"exp.salary 2026-07 = {salary_07}（工资表应付合计）")

    grid = run(periods, params, inputs)

    init_db()
    db = SessionLocal()
    try:
        # 幂等重置：删旧情景重写
        old = db.query(Scenario).filter(Scenario.name == "中性").first()
        if old:
            db.query(Cell).filter(Cell.scenario_id == old.id).delete()
            db.query(ModelVersion).filter(ModelVersion.scenario_id == old.id).delete()
            db.delete(old)
            db.commit()

        scenario = Scenario(name="中性", description="Excel「现金流中性」情景（2026.8 版数据）",
                            is_active=True)
        db.add(scenario)
        db.flush()

        params_snapshot = json.dumps(asdict(params), ensure_ascii=False,
                                     default=lambda o: str(o))
        inputs_snapshot = json.dumps(inputs, ensure_ascii=False, default=lambda o: str(o))
        version = ModelVersion(
            scenario_id=scenario.id, version_no=1,
            comment=f"Excel 导入；工资 07 按工资表补 {salary_07}",
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
        print(f"已写入：情景「中性」版本 1，{len(cells)} 个单元格，"
              f"期间 {periods[0]}..{periods[-1]}（{len(periods)} 期）")
        n_actual = seed_actuals(db)
        print(f"已写入：sales_actuals {n_actual} 条（{'/'.join(ACTUAL_MONTHS)} × 线上/线下）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
