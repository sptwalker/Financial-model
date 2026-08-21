# -*- coding: utf-8 -*-
"""临时探针：列出 dev 库表 + alembic_version 状态"""
import sys
import sqlite3
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

DB = Path(__file__).resolve().parent.parent / "data" / "financial_model.db"
c = sqlite3.connect(str(DB))
print("tables:", [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'")])
try:
    print("alembic_version:", [r[0] for r in c.execute("SELECT version_num FROM alembic_version")])
except Exception as e:
    print("alembic_version: none ->", e)
print("cell count:", c.execute("SELECT COUNT(*) FROM cells").fetchone()[0])
c.close()
