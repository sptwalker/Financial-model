# -*- coding: utf-8 -*-
"""预算存档管理测试：按 version_no 归并的列表 / 改名 / 删除守卫

验证：
1. GET /scenarios/archives 仅 admin；按 version_no 归并（每档跨多情景）
2. PATCH 改名 → 同批 version_no 的各情景版本注释统一
3. DELETE 守卫：导入基线(source=import)不可删；删除普通存档连带清 cells
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.financial import Cell, ModelVersion, Scenario

BACKEND = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def db():
    from app.db.session import SessionLocal, init_db
    init_db()
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture(scope="module")
def seeded(db):
    """纯净 seed 基线 + 一个可删的普通存档（version_no=2，source=engine）"""
    import sys
    sys.path.insert(0, str(BACKEND))
    from scripts.seed_from_excel import main as seed_main
    seed_main()
    sc = db.query(Scenario).filter(Scenario.name == "中性").first()
    # 造第二个存档：复制 v1 的 cells 为 v2（source=engine），供删除测试
    if not db.query(ModelVersion).filter(ModelVersion.scenario_id == sc.id,
                                         ModelVersion.version_no == 2).first():
        db.add(ModelVersion(scenario_id=sc.id, version_no=2, comment="预算调整 · 中性",
                            source="engine", params_json="{}", inputs_json="{}"))
        for c in db.query(Cell).filter(Cell.scenario_id == sc.id, Cell.model_version == 1).limit(5):
            db.add(Cell(scenario_id=sc.id, model_version=2, period=c.period,
                        row_key=c.row_key, value=c.value, source=c.source))
        db.commit()
    return db


@pytest.fixture(scope="module")
def client(seeded):
    return TestClient(app)


def _auth(client):
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_list_archives_grouped(client):
    h = _auth(client)
    arcs = client.get("/api/v1/scenarios/archives", headers=h).json()["archives"]
    by_no = {a["version_no"]: a for a in arcs}
    assert 1 in by_no and by_no[1]["source"] == "import"
    # v1 存档去掉了「· 中性」后缀
    assert " · " not in by_no[1]["name"]


def test_rename_archive(client):
    h = _auth(client)
    r = client.patch("/api/v1/scenarios/archives/2", headers=h, json={"name": "Q4计划"})
    assert r.status_code == 200, r.text
    arcs = client.get("/api/v1/scenarios/archives", headers=h).json()["archives"]
    assert next(a for a in arcs if a["version_no"] == 2)["name"] == "Q4计划"


def test_delete_import_baseline_forbidden(client):
    h = _auth(client)
    r = client.delete("/api/v1/scenarios/archives/1", headers=h)
    assert r.status_code == 400  # 导入基线受保护


def test_delete_archive_clears_cells(client, db):
    h = _auth(client)
    r = client.delete("/api/v1/scenarios/archives/2", headers=h)
    assert r.status_code == 200, r.text
    assert db.query(Cell).filter(Cell.model_version == 2).count() == 0
    assert db.query(ModelVersion).filter(ModelVersion.version_no == 2).count() == 0
