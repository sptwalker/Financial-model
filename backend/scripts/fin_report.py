# -*- coding: utf-8 -*-
"""财务报表解析器（2026-07 期）：资产负债表 + 利润表 → 引擎锚点/已发生月实际值

只读两处：
- 资产负债表 2026-07-31 货币资金期末余额 → 期初现金锚点 cash.opening["2026-08"]
  （引擎现金链唯一锚点=期间轴首期期初现金，见 calculator.run）
- 利润表 2026-07 行项目 → 07 月已发生费用（exp.*，单位换算 元→万元）

金额单位：报表为元，引擎为万元；本模块负责换算。
"""
import openpyxl
from decimal import Decimal


# 利润表行项目 → 引擎 exp 行（07 月已发生费用）
# 注：工资不在此映射（08 工资按工资表应付合计锚定，见 seed_from_excel）；
# 研发费用主要为人员薪酬，与工资表重叠，不映射（避免重复计入）。
# 财务费用 -6,228.07 引擎无对应行，不映射。
INCOME_MAP = {
    "销售费用": "exp.online_promo",
    "管理费用": "exp.office_other",
}

# 资产负债表（利润表末列）中资产负债表右上角的期初余额 8,598,066.12
BALANCE_SHEET_TITLE = "资产负债表"


def _norm(s) -> str:
    return str(s).replace(" ", "").replace("　", "")


def parse_report(path) -> dict:
    """读财务报表 xlsx → {cash_opening_wan: Decimal, expenses_wan: {exp_key: Decimal}}

    cash_opening_wan = 资产负债表 07-31 货币资金期末余额（元 → 万）
    expenses_wan[exp_key] = 利润表 2026-07 行项目实际值（元 → 万）
    """
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb[BALANCE_SHEET_TITLE]

    hdr_row = None
    for r in range(1, ws.max_row + 1):
        for c in range(1, ws.max_column + 1):
            if _norm(ws.cell(r, c).value or "") == "期末余额":
                hdr_row, col = r, c
                break
        if hdr_row is not None:
            break

    # 货币资金数据行：表头下方首个「货币资金」（资产区行首，行次=1）
    cash_row = None
    for r in range(hdr_row + 1, ws.max_row + 1):
        label = _norm(ws.cell(r, 1).value or "")
        if label.startswith("货币资金"):
            cash_row = r
            break
    if cash_row is None:
        raise ValueError(f"财务报表 {path.name}：资产负债表未找到「货币资金」数据行")
    cash_yuan = ws.cell(cash_row, col).value
    if not isinstance(cash_yuan, (int, float)):
        raise ValueError(f"财务报表 {path.name}：货币资金期末余额非数值: {cash_yuan!r}")
    cash_opening = round(Decimal(str(cash_yuan)) / Decimal("10000"), 4)

    expenses: dict[str, Decimal] = {}
    # 利润表为独立 sheet：行项目列 1，本月金额列 3
    income = wb["利润表"]
    for r in range(1, income.max_row + 1):
        label = _norm(income.cell(r, 1).value or "")
        key = INCOME_MAP.get(label)
        if not key:
            continue
        v = income.cell(r, 3).value
        if isinstance(v, (int, float)):
            expenses[key] = round(Decimal(str(v)) / Decimal("10000"), 4)

    return {"cash_opening_wan": cash_opening, "expenses_wan": expenses}


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path

    from decimal import Decimal
    p = Path(sys.argv[1] if len(sys.argv) > 1 else
             "../docs/财务报表__202607期.xlsx")
    r = parse_report(p)
    print(json.dumps({k: str(v) for k, v in r.items()}, ensure_ascii=False, indent=2))
