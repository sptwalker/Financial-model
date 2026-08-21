# -*- coding: utf-8 -*-
"""探针：引擎全年合计 vs Excel 2028/2029 全年引用列（哪些行能对齐）"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.excel_import import import_xls  # noqa: E402
from app.engine.calculator import run, Params  # noqa: E402

BACKEND = Path(__file__).resolve().parent.parent
XLS = BACKEND.parent / "docs" / "现金流测算 2026.8.xls"

imp = import_xls(XLS)
inputs, excel, periods = imp["inputs"], imp["excel"], imp["periods"]
grid = run(periods, Params(), inputs)

ROWS = [
    "sale.online.amount", "sale.offline.amount", "sale.total.amount",
    "collect.total", "purchase.main", "purchase.accessory", "purchase.total",
    "exp.salary", "exp.channel_commission", "exp.total",
    "cash.opening", "cash.expense", "cash.gap", "cash.closing",
]
# 引擎行键（含配件拆分重建的键）
ENG = {
    "sale.online.amount": ["sale.online.amount"],
    "sale.offline.amount": ["sale.offline.amount"],
    "sale.total.amount": ["sale.online.amount", "sale.offline.amount", "sale.accessory.amount"],
    "collect.total": ["collect.online", "collect.offline"],
    "purchase.main": ["purchase.main"],
    "purchase.accessory": ["purchase.accessory"],
    "purchase.total": ["purchase.total"],
    "exp.salary": ["exp.salary"],
    "exp.channel_commission": ["exp.channel_commission"],
    "exp.total": ["exp.total"],
    "cash.opening": ["cash.opening"],
    "cash.expense": ["cash.expense"],
    "cash.gap": ["cash.gap"],
    "cash.closing": ["cash.closing"],
}

print(f"{'行':<24} {'2028 引擎全年':>14} {'2028 Excel':>14}  {'2029 引擎全年':>14} {'2029 Excel':>14}")
for row in ROWS:
    e28 = excel.get(row, {}).get("2028-12")
    e29 = excel.get(row, {}).get("2029-12")
    def annual(key, year):
        ms = [p for p in periods if p.startswith(str(year))]
        return sum((Decimal(grid[k][p]["value"]) for k in ENG[key] for p in ms), Decimal("0"))
    a28 = annual(row, 2028) if e28 is not None else None
    a29 = annual(row, 2029) if e29 is not None else None
    print(f"{row:<24} {str(a28):>14} {str(e28):>14}  {str(a29):>14} {str(e29):>14}")

# 订阅：Excel 订阅行 vs 引擎 sale.subscription
sub_excel = imp["excel"].get("sale.subscription.amount", {})
print("\n订阅 Excel 行值:", {k: v for k, v in sub_excel.items()})
print("引擎 sale.subscription 2027-07..12:", {p: grid["sale.subscription.amount"][p]["value"] for p in periods if p.startswith("2027")})
print("引擎 sale.subscription 2028-12/2029-12:", grid["sale.subscription.amount"]["2028-12"]["value"], grid["sale.subscription.amount"]["2029-12"]["value"])
