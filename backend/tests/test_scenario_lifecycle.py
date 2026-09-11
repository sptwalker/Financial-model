# -*- coding: utf-8 -*-
"""情景生命周期测试：增删改 / 默认情景唯一性 / 版本发布 / 单元格覆盖 / 分权限

验证：
1. POST 新建情景；重名 400；viewer 403
2. PATCH 改名（重名 400）、改描述、切换默认情景 → 同一时刻仅一个 is_active
3. DELETE 连带清 cells 与版本；仅 admin；不存在 404
4. release / unrelease 版本 → released_at 落库与清除；仅 admin；版本不存在 404
5. PUT cells 覆盖 → source 变为 override；越界行×期回报 missing 而非静默丢弃
6. GET grid 指定版本 / 版本不存在 404
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.security import create_access_token
from app.main import app
from app.models.financial import Cell, ModelVersion, Scenario
from app.models.user import User, UserRole, UserStatus

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
    """纯净 seed 基线（中性/乐观/悲观三情景 + 中性 v1）"""
    import sys
    sys.path.insert(0, str(BACKEND))
    from scripts.seed_from_excel import main as seed_main
    seed_main()
    return db


@pytest.fixture(scope="module")
def client(seeded):
    return TestClient(app)


def _token(client):
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _viewer_token(db):
    """造一个已启用的 viewer 用户，返回其令牌（用于权限拒绝断言）"""
    u = db.query(User).filter(User.feishu_user_id == "test_lifecycle_viewer").first()
    if not u:
        u = User(feishu_user_id="test_lifecycle_viewer", name="生命周期查看员",
                 role=UserRole.VIEWER, status=UserStatus.ACTIVE)
        db.add(u)
        db.commit()
        db.refresh(u)
    else:
        u.role, u.status = UserRole.VIEWER, UserStatus.ACTIVE
        db.commit()
    return create_access_token({"sub": str(u.id)})


def test_create_duplicate_and_viewer_forbidden(client, db):
    tok = _token(client)
    r = client.post("/api/v1/scenarios", json={"name": "评审临时情景"}, headers=_h(tok))
    assert r.status_code == 200, r.text
    new_id = r.json()["id"]
    assert r.json()["name"] == "评审临时情景"

    # 重名 → 400
    r = client.post("/api/v1/scenarios", json={"name": "评审临时情景"}, headers=_h(tok))
    assert r.status_code == 400

    # viewer 无权新建
    r = client.post("/api/v1/scenarios", json={"name": "查看员尝试"},
                    headers=_h(_viewer_token(db)))
    assert r.status_code == 403

    # 收尾：删掉临时情景（同时验证 DELETE 通路）
    assert client.delete(f"/api/v1/scenarios/{new_id}", headers=_h(tok)).status_code == 200
    assert db.query(Scenario).filter(Scenario.id == new_id).first() is None


def test_create_scenario_recalc_error_on_empty(client, db):
    """新建情景尚无版本 → grid / recalc 均 404 并给出引导文案"""
    tok = _token(client)
    sid = client.post("/api/v1/scenarios", json={"name": "空情景"}, headers=_h(tok)).json()["id"]
    try:
        r = client.get(f"/api/v1/scenarios/{sid}/grid", headers=_h(tok))
        assert r.status_code == 404
        assert "尚未计算" in r.json()["detail"]
    finally:
        client.delete(f"/api/v1/scenarios/{sid}", headers=_h(tok))


def test_update_scenario_name_description_default(client, db):
    tok = _token(client)
    sid = client.post("/api/v1/scenarios", json={"name": "待改名"}, headers=_h(tok)).json()["id"]
    try:
        # 改名
        r = client.patch(f"/api/v1/scenarios/{sid}", json={"name": "已改名"}, headers=_h(tok))
        assert r.status_code == 200, r.text
        assert r.json()["name"] == "已改名"

        # 改成已存在的名字 → 400
        r = client.patch(f"/api/v1/scenarios/{sid}", json={"name": "中性"}, headers=_h(tok))
        assert r.status_code == 400
        assert "已存在" in r.json()["detail"]

        # 描述
        r = client.patch(f"/api/v1/scenarios/{sid}", json={"description": "评审用"},
                         headers=_h(tok))
        assert r.json()["description"] == "评审用"

        # 设为默认 → 原默认被摘掉，全局仅一个 is_active
        r = client.patch(f"/api/v1/scenarios/{sid}", json={"is_active": True}, headers=_h(tok))
        assert r.status_code == 200, r.text
        db.expire_all()
        assert db.query(Scenario).filter(Scenario.is_active.is_(True)).count() == 1
        assert db.query(Scenario).filter(Scenario.id == sid).first().is_active is True

        # 不存在的 id → 404
        r = client.patch("/api/v1/scenarios/999999", json={"name": "x"}, headers=_h(tok))
        assert r.status_code == 404
    finally:
        # 复位默认情景并清理，避免影响其它模块
        neutral = db.query(Scenario).filter(Scenario.name == "中性").first()
        if neutral:
            neutral.is_active = True
            db.commit()
        client.delete(f"/api/v1/scenarios/{sid}", headers=_h(tok))


def test_delete_scenario_admin_only_and_clears_children(client, db):
    tok = _token(client)
    # 造一个带 cells/版本的临时情景，验证级联清理
    sid = client.post("/api/v1/scenarios", json={"name": "级联测试"}, headers=_h(tok)).json()["id"]
    db.add(ModelVersion(scenario_id=sid, version_no=1, comment="t", source="engine",
                        params_json="{}", inputs_json="{}"))
    db.add(Cell(scenario_id=sid, model_version=1, period="2026-08",
                row_key="cash.gap", value="1", source="engine"))
    db.commit()
    assert db.query(Cell).filter(Cell.scenario_id == sid).count() == 1

    # viewer 无权删除
    assert client.delete(f"/api/v1/scenarios/{sid}",
                         headers=_h(_viewer_token(db))).status_code == 403

    r = client.delete(f"/api/v1/scenarios/{sid}", headers=_h(tok))
    assert r.status_code == 200, r.text
    assert db.query(Cell).filter(Cell.scenario_id == sid).count() == 0
    assert db.query(ModelVersion).filter(ModelVersion.scenario_id == sid).count() == 0

    # 再删 → 404
    assert client.delete(f"/api/v1/scenarios/{sid}", headers=_h(tok)).status_code == 404


def test_version_release_and_unrelease(client, db):
    tok = _token(client)
    sid = client.post("/api/v1/scenarios", json={"name": "发布测试"}, headers=_h(tok)).json()["id"]
    db.add(ModelVersion(scenario_id=sid, version_no=1, comment="t", source="engine",
                        params_json="{}", inputs_json="{}"))
    db.commit()
    try:
        # viewer 无权发布
        assert client.post(f"/api/v1/scenarios/{sid}/versions/1/release",
                           headers=_h(_viewer_token(db))).status_code == 403

        r = client.post(f"/api/v1/scenarios/{sid}/versions/1/release", headers=_h(tok))
        assert r.status_code == 200, r.text
        assert r.json()["released"] is True
        v = db.query(ModelVersion).filter(ModelVersion.scenario_id == sid,
                                          ModelVersion.version_no == 1).first()
        db.refresh(v)
        assert v.released_at is not None and v.released_by is not None

        # 版本列表带出已发布状态
        versions = client.get(f"/api/v1/scenarios/{sid}/versions", headers=_h(tok)).json()["versions"]
        assert versions[0]["released_at"] is not None

        r = client.post(f"/api/v1/scenarios/{sid}/versions/1/unrelease", headers=_h(tok))
        assert r.status_code == 200 and r.json()["released"] is False
        db.refresh(v)
        assert v.released_at is None and v.released_by is None

        # 不存在的版本 → 404
        assert client.post(f"/api/v1/scenarios/{sid}/versions/99/release",
                           headers=_h(tok)).status_code == 404
    finally:
        client.delete(f"/api/v1/scenarios/{sid}", headers=_h(tok))


def test_write_cells_overrides_and_reports_missing(client, db):
    """覆盖写入：命中 → source=override；越界行×期回报 missing（不静默丢弃）"""
    tok = _token(client)
    sid = client.post("/api/v1/scenarios", json={"name": "覆盖测试"}, headers=_h(tok)).json()["id"]
    db.add(ModelVersion(scenario_id=sid, version_no=1, comment="t", source="engine",
                        params_json="{}", inputs_json="{}"))
    db.add(Cell(scenario_id=sid, model_version=1, period="2026-08",
                row_key="cash.gap", value="1", source="engine"))
    db.commit()
    try:
        # viewer 无权写入
        assert client.put(f"/api/v1/scenarios/{sid}/cells", headers=_h(_viewer_token(db)),
                          json={"cells": {"cash.gap": {"2026-08": "5"}}}).status_code == 403

        r = client.put(f"/api/v1/scenarios/{sid}/cells", headers=_h(tok),
                       json={"cells": {"cash.gap": {"2026-08": "5", "2099-01": "9"},
                                       "not.a.row": {"2026-08": "1"}}})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["updated"] == 1
        assert len(body["missing"]) == 2
        assert "warning" in body

        c = db.query(Cell).filter(Cell.scenario_id == sid, Cell.row_key == "cash.gap").first()
        db.refresh(c)
        assert c.value == "5" and c.source == "override"

        # 情景不存在 → 404
        assert client.put("/api/v1/scenarios/999999/cells", headers=_h(tok),
                          json={"cells": {}}).status_code == 404
    finally:
        client.delete(f"/api/v1/scenarios/{sid}", headers=_h(tok))


def test_get_grid_specific_version_and_404(client, db):
    tok = _token(client)
    # 中性情景（seed 基线）有 v1
    neutral = db.query(Scenario).filter(Scenario.name == "中性").first()
    listed = client.get("/api/v1/scenarios", headers=_h(tok)).json()
    assert len(listed) >= 3  # 三方案基线仍在

    r = client.get(f"/api/v1/scenarios/{neutral.id}/grid?version_no=1", headers=_h(tok))
    assert r.status_code == 200, r.text
    assert r.json()["version_no"] == 1
    assert "cash.gap" in r.json()["cells"]

    # 不存在的版本 → 404
    assert client.get(f"/api/v1/scenarios/{neutral.id}/grid?version_no=99",
                      headers=_h(tok)).status_code == 404
