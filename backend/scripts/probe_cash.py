# -*- coding: utf-8 -*-
"""探针：现金/采购相关行 引擎 vs Excel 逐月明细（找差异起始期与规则）"""
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
    "cash.opening", "cash.expense", "cash.gap", "cash.closing",
    "purchase.main", "purchase.total", "exp.total",
]
# 辅助：配件线上份额
def acc_online(p):
    on = Decimal(grid["qty.online"][p]["value"])
    off = Decimal(grid["qty.offline"][p]["value"])
    t = on + off
    acc = Decimal(grid["sale.accessory.amount"][p]["value"])
    return acc * (on / t) if t else Decimal("0")

def eng(excel_key, p):
    if excel_key == "cash.expense":
        return Decimal(grid["cash.expense"][p]["value"])
    return Decimal(grid[excel_key][p]["value"])

for rk in ROWS:
    e = excel.get(rk, {})
    if not e:
        print(f"{rk}: (Excel 无该行)")
        continue
    print(f"--- {rk} ---")
    for p in periods:
        x = e.get(p)
        if x is None:
            continue
        if p.startswith("2028") or p.startswith("2029"):
            # 全年列：只印引擎年度合计
            if p.endswith("-12"):
                ms = [pp for pp in periods if pp[:4] == p[:4]]
                a = sum((Decimal(grid[rk][pp]["value"]) for pp in ms), Decimal("0"))
                flag = "OK" if abs(a - x) < Decimal("0.05") else f"DIFF {a - x}"
                print(f"  {p}(全年): 引擎全年 {a} vs Excel {x}  [{flag}]")
            continue
        a = eng(rk, p)
        diff = a - x
        flag = "OK" if abs(diff) < Decimal("0.05") else f"DIFF {diff}"
        print(f"  {p}: 引擎 {a} vs Excel {x}  [{flag}]")
