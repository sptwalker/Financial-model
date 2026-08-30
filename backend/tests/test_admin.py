# -*- coding: utf-8 -*-
"""管理员菜单测试：用户管理（审批/改角色/屏蔽）+ 操作日志 + 权限

验证：
1. GET /users 仅 admin 可见；返回含 last_login_at
2. 新建 pending 用户 → 登录被 403 拦截（模拟飞书回调状态校验逻辑）
3. admin 审批（status→active）后 → 用户可访问
4. admin 改角色 / 屏蔽；禁止修改自己；非法值 400
5. GET /users/logs 返回结构 + 分页 + 仅 admin
6. 启动补升：INITIAL_ADMIN 名单内的旧 viewer → sync_initial_roles → admin+active
"""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import app
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
def client(db):
    return TestClient(app)


def _token(client):
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _make_user(db, feishu_id, name, role=UserRole.VIEWER, status=UserStatus.PENDING):
    """造一个测试用户（幂等：已存在则复位角色/状态）"""
    u = db.query(User).filter(User.feishu_user_id == feishu_id).first()
    if u:
        u.role, u.status = role, status
        db.commit()
        return u
    u = User(feishu_user_id=feishu_id, name=name, role=role, status=status)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_list_users_admin_only_with_last_login(client, db):
    token = _token(client)
    r = client.get("/api/v1/users", headers=_auth(token))
    assert r.status_code == 200, r.text
    users = r.json()
    assert isinstance(users, list) and len(users) >= 1
    assert "last_login_at" in users[0]  # 字段暴露


def test_approve_pending_then_role_and_block(client, db):
    token = _token(client)
    u = _make_user(db, "test_pending_1", "待审批张三", status=UserStatus.PENDING)

    # 审批通过 → active
    r = client.patch(f"/api/v1/users/{u.id}/status", json={"status": "active"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "active"

    # 改角色 → editor
    r = client.patch(f"/api/v1/users/{u.id}/role", json={"role": "editor"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "editor"

    # 屏蔽 → disabled
    r = client.patch(f"/api/v1/users/{u.id}/status", json={"status": "disabled"},
                     headers=_auth(token))
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "disabled"

    # 非法角色 400
    r = client.patch(f"/api/v1/users/{u.id}/role", json={"role": "boss"},
                     headers=_auth(token))
    assert r.status_code == 400


def test_cannot_modify_self(client, db):
    token = _token(client)
    me = client.get("/api/v1/auth/me", headers=_auth(token)).json()
    r = client.patch(f"/api/v1/users/{me['id']}/status", json={"status": "disabled"},
                     headers=_auth(token))
    assert r.status_code == 400
    r = client.patch(f"/api/v1/users/{me['id']}/role", json={"role": "viewer"},
                     headers=_auth(token))
    assert r.status_code == 400


def test_disabled_user_blocked_by_deps(client, db):
    """被禁用用户持令牌访问 → get_current_user 403"""
    from app.core.security import create_access_token
    u = _make_user(db, "test_disabled_1", "禁用李四", status=UserStatus.DISABLED)
    tok = create_access_token({"sub": str(u.id)})
    r = client.get("/api/v1/users", headers=_auth(tok))
    assert r.status_code == 403


def test_pending_user_blocked_by_deps(client, db):
    """待审批用户持令牌访问 → 同样 403（未放行不得进入）"""
    from app.core.security import create_access_token
    u = _make_user(db, "test_pending_2", "待审批王五", status=UserStatus.PENDING)
    tok = create_access_token({"sub": str(u.id)})
    r = client.get("/api/v1/scenarios", headers=_auth(tok))
    assert r.status_code == 403


def test_logs_pagination_admin_only(client, db):
    token = _token(client)
    # 先制造若干日志：改一次状态
    u = _make_user(db, "test_pending_3", "日志赵六", status=UserStatus.PENDING)
    client.patch(f"/api/v1/users/{u.id}/status", json={"status": "active"},
                 headers=_auth(token))

    r = client.get("/api/v1/users/logs?limit=5&offset=0", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert "items" in body and "total" in body
    assert body["total"] >= 1
    assert len(body["items"]) <= 5
    if body["items"]:
        it = body["items"][0]
        assert {"id", "created_at", "action"} <= set(it.keys())

    # 非 admin（viewer 令牌）→ 403
    from app.core.security import create_access_token
    v = _make_user(db, "test_viewer_1", "查看用户", role=UserRole.VIEWER,
                   status=UserStatus.ACTIVE)
    vtok = create_access_token({"sub": str(v.id)})
    r = client.get("/api/v1/users/logs", headers=_auth(vtok))
    assert r.status_code == 403
    r = client.get("/api/v1/users", headers=_auth(vtok))
    assert r.status_code == 403  # 用户列表也仅 admin


def test_sync_initial_roles_promotes_existing(client, db, monkeypatch):
    """启动补升：预置名单内的旧 viewer/pending → admin + active"""
    from app.services.user_service import UserService
    from app.core import config as cfg

    u = _make_user(db, "test_liudan_openid", "刘丹",
                   role=UserRole.VIEWER, status=UserStatus.PENDING)

    # 注入名单（清 lru_cache 后打补丁 settings）
    settings = UserService.get_by_id.__globals__["get_settings"]()
    monkeypatch.setattr(settings, "INITIAL_ADMIN_FEISHU_IDS", ["test_liudan_openid"])

    n = UserService.sync_initial_roles(db)
    assert n >= 1
    db.refresh(u)
    assert u.role == UserRole.ADMIN
    assert u.status == UserStatus.ACTIVE
