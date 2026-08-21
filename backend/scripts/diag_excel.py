# -*- coding: utf-8 -*-
"""列出主表全部行名 + 非空行摘要，定位订阅收入实际所在"""
import sys
from pathlib import Path
import xlrd

XLS = Path(r"C:\Users\walker\Documents\walker\Vibecode\Financial-model\docs\现金流测算 2026.8.xls")
book = xlrd.open_workbook(str(XLS), formatting_info=True)
for sname in book.sheet_names():
    ws = book.sheet_by_name(sname)
    print(f"===== sheet: {sname} ({ws.nrows} rows x {ws.ncols} cols) =====")
    for r in range(ws.nrows):
        label = "".join(str(ws.cell_value(r, 0) or "").split())
        sub = "".join(str(ws.cell_value(r, 1) or "").split())
        nonempty = [c for c in range(2, ws.ncols) if ws.cell_type(r, c) not in (0, 6)]
        if label or sub or nonempty:
            peek = " ".join(f"{ws.cell_value(r, c)!r}" for c in nonempty[:3])
            print(f"  r{r:02d} [{label}|{sub}] cols={nonempty[:8]}  e.g. {peek}")
    if sname != book.sheet_names()[-1]:
        print()
