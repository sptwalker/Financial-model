# -*- coding: utf-8 -*-
"""M2 种子脚本：Excel 中性情景 + 财务报表 2026-07 期 → 引擎重算 → 写入数据库

数据来源：
- 现金流测算 2026.8.xls「现金流中性」主表（qty/回款/采购/费用/期初现金/年度目标）
- 2026年7月创想悦动工资表.xlsx 应付合计 → exp.salary 2026-07（实际已发生）
- 财务报表__202607期.xlsx：
  · 资产负债表 07-31 货币资金 8,598,066.12 元 → 期初现金锚点 cash.opening["2026-08"]
    （引擎现金链唯一锚点=期间轴首期期初现金，见 calculator.run）
  · 利润表 2026-07 实际费用 → 07 月已发生费用行（exp.salary/game_dev/online_promo/office_other）

期间轴 2026-08 起（41 期）：2026-07 为已发生月，按报表实际值锚定为前置历史
（qty=0 行写入 sales_actuals，预测从 2026-08 起）。

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
from scripts.fin_report import parse_report  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent
XLS = BACKEND_DIR.parent / "docs" / "现金流测算 2026.8.xls"
PAYROLL_XLSX = BACKEND_DIR.parent / "docs" / "2026年7月创想悦动工资表.xlsx"
FIN_REPORT_XLSX = BACKEND_DIR.parent / "docs" / "财务报表__202607期.xlsx"

# 已发生月（发售起点 2026-07 起）；真实销量到位后逐月追加，预测只从 sales_actuals 读历史
ACTUAL_MONTHS = ["2026-07", "2026-08"]


def seed_actuals(db) -> int:
    """已发生月销量 → sales_actuals（幂等 upsert，source=seed）

    - 期间轴内月份（2026-08 起）：从「中性」v1 网格取 qty.online/offline
    - 轴外前置历史（2026-07，报表营业收入≈0）：直接写 qty=0 行
    """
    scenario = db.query(Scenario).filter(Scenario.name == "中性").first()
    if not scenario:
        return 0
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

    # 2026-07 已发生月（前置历史）：从引擎期间轴剥离，按报表实际值锚定
    for row_key in list(inputs):
        inputs[row_key] = {p: v for p, v in inputs[row_key].items()
                           if not p.startswith("2026-07")}

    salary_07 = payroll_total_payable(PAYROLL_XLSX)          # 工资表应付合计（万）
    report = parse_report(FIN_REPORT_XLSX)                   # 报表实际值
    cash_opening_08 = report["cash_opening_wan"]             # 07-31 货币资金余额 → 08 期初
    exp_07 = report["expenses_wan"]                          # 07 月已发生费用（万）

    # 08 期初现金锚点 = 报表 07-31 实际余额（替代计划 450 万）
    inputs.setdefault("cash.opening", {})["2026-08"] = cash_opening_08
    # 08 工资 = 工资表实际应付合计（替代计划 240 万；对账报告记为 KNOWN_RULE_DIFF）
    inputs.setdefault("exp.salary", {})["2026-08"] = salary_07
    # 08 推广/办公费：计划 08 列空，按报表 07 实际值近似（研发费用与工资重叠，不重复映射）
    for key, v in exp_07.items():
        inputs.setdefault(key, {})["2026-08"] = v
    # 07 已发生月销量 = 0（报表营业收入 1,466.27 元 ≈ 0 台）→ actuals 前置历史行
    inputs.setdefault("qty.online", {})["2026-07"] = Decimal("0")
    inputs.setdefault("qty.offline", {})["2026-07"] = Decimal("0")

    print(f"报表锚定：cash.opening 2026-08 = {cash_opening_08} 万（资产负债表 07-31）")
    print(f"报表实际：exp.salary 2026-08 = {salary_07}（工资表应付合计）")
    for key, v in exp_07.items():
        if key != "exp.salary":
            print(f"报表实际：{key} 2026-08 ≈ {v}（利润表 07 月实际）")

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
        print(f"已写入：情景「中性」版本 1，{len(cells)} 个单元格，"
              f"期间 {periods[0]}..{periods[-1]}（{len(periods)} 期）")
        n_actual = seed_actuals(db)
        print(f"已写入：sales_actuals {n_actual} 条（{'/'.join(ACTUAL_MONTHS)} × 线上/线下）")
    finally:
        db.close()


if __name__ == "__main__":
    main()
