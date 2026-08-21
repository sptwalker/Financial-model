# -*- coding: utf-8 -*-
"""探针：Excel 主表全部行索引 + 标签 + 值（不跳过空行）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import xlrd  # noqa: E402

XLS = Path(__file__).resolve().parent.parent.parent / "docs" / "现金流测算 2026.8.xls"

wb = xlrd.open_workbook(str(XLS))
sh = wb.sheet_by_name("现金流中性")

print(f"sheet={sh.name} nrows={sh.nrows} ncols={sh.ncols}")
for r in range(sh.nrows):
    label = str(sh.cell_value(r, 0)).strip()
    label2 = str(sh.cell_value(r, 1)).strip()
    vals = []
    for c in range(2, sh.ncols):
        v = sh.cell_value(r, c)
        if isinstance(v, float):
            vals.append(round(v, 4))
        elif v == "":
            vals.append("")
        else:
            vals.append(str(v))
    print(f"[{r}] {label!r} ({label2!r}) | {vals}")
