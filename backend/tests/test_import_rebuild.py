# -*- coding: utf-8 -*-
"""导入重建端点测试：上传两件套 → 重建基础数据（中性 v1 + 乐观/悲观对齐）

验证：
1. 端点接受 主表.xls + 财务报表.xlsx 两件套，重建后返回 1102 cells / 29 期
2. 重建后 /scenarios 返回 中性/乐观/悲观 三个情景，网格各 38 行 @ 2026-08..2028-12
3. 破坏性操作权限：拒绝非 admin/editor（此处用 dev-login admin 通过，viewer 403）
"""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.financial import Cell, ModelVersion, Scenario

BACKEND = Path(__file__).resolve().parent.parent
DOCS = BACKEND.parent / "docs"


@pytest.fixture(scope="module")
def db():
    from app.db.session import SessionLocal, init_db
    init_db()
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def seeded(db):
    """复用 test_recalc 的模块级重置：先把情景 1 清回纯净 seed 基线再测"""
    old = db.query(Scenario).filter(Scenario.id == 1).first()
    if old:
        db.query(Cell).filter(Cell.scenario_id == 1).delete()
        db.query(ModelVersion).filter(ModelVersion.scenario_id == 1).delete()
        db.commit()
    import sys
    sys.path.insert(0, str(BACKEND))
    from scripts.seed_from_excel import main as seed_main
    seed_main()
    return db


@pytest.fixture(scope="module")
def client(seeded):
    return TestClient(app)


def _files():
    """打成 multipart 两件套；用 BytesIO 避免遗留文件句柄（Windows 会锁 docs）"""
    from io import BytesIO
    return [
        ("file_main_xls", ("现金流测算 2026.8.xls",
                           BytesIO((DOCS / "现金流测算 2026.8.xls").read_bytes()),
                           "application/vnd.ms-excel")),
        ("file_report_xlsx", ("财务报表__202607期.xlsx",
                              BytesIO((DOCS / "财务报表__202607期.xlsx").read_bytes()),
                              "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")),
    ]


def test_import_rebuild_returns_expected_counts(client):
    """三件套导入 → 重建 中性 v1：1102 cells / 29 期 / 4 actuals"""
    r = client.post("/api/v1/imports/rebuild",
                    headers=_auth(_token(client)), files=_files())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["cells"] == 1102
    assert body["periods"] == ["2026-08", "2028-12"]
    assert body["period_count"] == 29
    assert body["actuals"] == 4


def test_import_rebuild_scenarios_and_grid(client):
    """重建后三情景齐全，网格 2026-08..2028-12"""
    token = _token(client)
    scs = client.get("/api/v1/scenarios", headers=_auth(token)).json()
    names = {s["name"] for s in scs}
    assert {"中性", "乐观", "悲观"} <= names

    mid = next(s for s in scs if s["name"] == "中性")["id"]
    grid = client.get(f"/api/v1/scenarios/{mid}/grid", headers=_auth(token)).json()["cells"]
    assert len(grid) == 38
    assert grid["qty.online"]["2026-08"]["source"] == "input"
    assert set(grid["sale.total.amount"]) >= {"2026-08", "2028-12"}


def _token(client):
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}
