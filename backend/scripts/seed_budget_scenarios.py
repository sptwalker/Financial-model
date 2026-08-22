# -*- coding: utf-8 -*-
"""预算三方案种子（幂等）：把「中性」情景克隆为独立的「乐观」「悲观」情景。

方案模型 = 三套独立 Scenario（预算页顶部下拉切换）。克隆 = 复制中性最新版本的
全部 cells + params/inputs 快照 → 各建新 Scenario + v1。已存在则跳过，可重复安全运行。
用法：从 backend 目录 `python scripts/seed_budget_scenarios.py`
"""
from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.financial import Scenario, ModelVersion, Cell  # noqa: E402

SRC_NAME = "中性"
CLONES = [
    ("乐观", "中性情景副本 · 乐观方案（预算页可细化销售/成本/投融资）"),
    ("悲观", "中性情景副本 · 悲观方案（预算页可细化销售/成本/投融资）"),
]


def _clone(db, src: Scenario, name: str, desc: str) -> None:
    if db.query(Scenario).filter(Scenario.name == name).first():
        print(f"[seed] 情景「{name}」已存在，跳过")
        return
    latest = (db.query(ModelVersion)
              .filter(ModelVersion.scenario_id == src.id)
              .order_by(ModelVersion.version_no.desc()).first())
    if not latest:
        print(f"[seed] 源情景「{SRC_NAME}」无版本，跳过 {name}")
        return
    cells = (db.query(Cell)
             .filter(Cell.scenario_id == src.id,
                     Cell.model_version == latest.version_no).all())

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
    print(f"[seed] 已克隆「{name}」（{len(cells)} 单元格，源 v{latest.version_no}）")


def truncate_existing_clones(db) -> None:
    """克隆已存在时清理 2029 期单元格（预算法定期界 2028-12 起）。

    中性重种子后，已有「乐观/悲观」仍带着旧 41 期网格；本函数把 2029 期的
    单元格就地删除，使其与 2028-12 界对齐（版本行/inputs 快照保留，旧期间
    自然越出期间轴不再生效）。
    """
    for name, _desc in CLONES:
        dst = db.query(Scenario).filter(Scenario.name == name).first()
        if not dst:
            continue
        deleted = (db.query(Cell)
                   .filter(Cell.scenario_id == dst.id, Cell.period >= "2029-01")
                   .delete(synchronize_session=False))
        if deleted:
            db.commit()
            print(f"[seed] 「{name}」已清理 {deleted} 个 2029 期单元格（对齐 2028-12 界）")


def seed() -> None:
    db = SessionLocal()
    try:
        src = db.query(Scenario).filter(Scenario.name == SRC_NAME).first()
        if not src:
            print(f"[seed] 未找到源情景「{SRC_NAME}」，请先运行 seed_from_excel.py")
            return
        truncate_existing_clones(db)
        for name, desc in CLONES:
            _clone(db, src, name, desc)
    finally:
        db.close()


if __name__ == "__main__":
    seed()
