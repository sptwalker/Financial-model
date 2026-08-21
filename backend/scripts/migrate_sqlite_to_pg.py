"""SQLite → PostgreSQL 数据迁移（幂等，Docker api 容器启动时执行）。

来源：backend/data/financial_model.db（只读挂载 /mnt/sqlite-data/financial_model.db）
目标：DATABASE_URL 指向的 PostgreSQL（须先 alembic upgrade head）

规则：
- 表序保 id 外键：users → scenarios → model_versions → cells → sales_actuals → forecast_runs → operation_logs
- 目标表非空则跳过（幂等）；每表迁移后自增序列同步到 max(id)
- 不迁移 alembic_version（由 alembic 管理）

用法：python scripts/migrate_sqlite_to_pg.py
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from sqlalchemy import Boolean, MetaData, Table, create_engine, select, text

SQLITE_SOURCE = os.environ.get(
    "SQLITE_SOURCE", "/mnt/sqlite-data/financial_model.db"
)

# 表迁移顺序（外键依赖序）
TABLE_ORDER = [
    "users",
    "scenarios",
    "model_versions",
    "cells",
    "sales_actuals",
    "forecast_runs",
    "operation_logs",
]


def migrate() -> None:
    pg_url = os.environ.get("DATABASE_URL", "")
    if not pg_url:
        print("[migrate] 未设置 DATABASE_URL，跳过数据迁移")
        return
    if not Path(SQLITE_SOURCE).exists():
        print(f"[migrate] SQLite 源不存在: {SQLITE_SOURCE}，跳过（全新部署）")
        return

    conn = sqlite3.connect(f"file:{SQLITE_SOURCE}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    engine = create_engine(pg_url)
    meta = MetaData()

    try:
        with engine.begin() as pg:
            for table_name in TABLE_ORDER:
                if table_name not in meta.tables:
                    # 从 PG 反射目标表
                    Table(table_name, meta, autoload_with=engine)
                pg_table = meta.tables[table_name]

                # 幂等：目标表非空则跳过
                existing = pg.execute(select(pg_table.c.id).limit(1)).scalar()
                if existing is not None:
                    print(f"[migrate] {table_name}: 已存在数据，跳过")
                    continue

                rows = conn.execute(f'SELECT * FROM "{table_name}"').fetchall()
                if not rows:
                    print(f"[migrate] {table_name}: 源为空，跳过")
                    continue

                cols = [c.name for c in pg_table.columns]
                bool_cols = {
                    c.name for c in pg_table.columns
                    if isinstance(c.type, Boolean)
                }
                data = [
                    tuple(
                        _convert(row[c], c in bool_cols) if c in row.keys() else None
                        for c in cols
                    )
                    for row in rows
                ]
                pg.execute(pg_table.insert(), [dict(zip(cols, d)) for d in data])

                # 同步自增序列
                seq = f"{table_name}_id_seq"
                max_id = max(row["id"] for row in rows) if "id" in cols else None
                if max_id is not None:
                    pg.execute(
                        text(
                            f"SELECT setval('{seq}', :max_id, true)"
                        ),
                        {"max_id": max_id},
                    )
                print(f"[migrate] {table_name}: 迁移 {len(data)} 行，序列同步到 {max_id}")
    finally:
        conn.close()

    print("[migrate] 完成")


def _convert(v: object, is_bool: bool) -> object:
    """SQLite 无布尔型：仅 Boolean 列的 0/1 → bool（PostgreSQL BOOLEAN 需要）；
    整数 id/外键/版本号原样保留，避免误转成 True/False。"""
    if v is None:
        return None
    return bool(v) if is_bool else v


if __name__ == "__main__":
    migrate()
