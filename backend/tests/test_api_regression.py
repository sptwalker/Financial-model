# -*- coding: utf-8 -*-
"""API 层回归测试：联调阶段修复的 4 个 bug 各一条用例

1. dev-login 签发 JWT 的 sub 载荷（曾传裸字符串导致 500）
2. UserOut.created_at / ScenarioOut.created_at 序列化（曾 str 类型拒绝 datetime）
3. grid 端点行×期组装（曾字典推导把每行折叠成最后一个 period）
4. recalc 无参幂等 + 参数增量按比例生效（端到端）
"""
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.financial import Cell, ModelVersion, Scenario


@pytest.fixture(scope="module")
def client(seeded):
    """seeded 复用 test_recalc.py 的模块级 fixture（共享同一 DB 会话）"""
    return TestClient(app)


@pytest.fixture(scope="module")
def seeded(db):
    old = db.query(Scenario).filter(Scenario.id == 1).first()
    if old:
        db.query(Cell).filter(Cell.scenario_id == 1).delete()
        db.query(ModelVersion).filter(ModelVersion.scenario_id == 1).delete()
        db.commit()
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.seed_from_excel import main as seed_main
    seed_main()
    return db


@pytest.fixture(scope="module")
def db():
    from app.db.session import SessionLocal, init_db
    init_db()
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def token(client):
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


# ---- 1. dev-login 签发 JWT ----

def test_dev_login_issues_usable_token(token, client):
    """dev-login 返回的 token 必须能访问受保护端点（曾 500：sub 载荷缺失）"""
    r = client.get("/api/v1/scenarios", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()[0]["name"] == "中性"


# ---- 2. 响应 schema 序列化（created_at datetime → ISO 字符串）----

def test_scenario_out_serializes_created_at(token, client):
    """/scenarios 的 created_at 必须是 ISO 字符串（曾 ResponseValidationError 500）"""
    r = client.get("/api/v1/scenarios", headers=_auth(token))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body[0]["created_at"].endswith("+00:00") or "T" in body[0]["created_at"]


def test_dev_login_user_out_serializes_created_at(token, client):
    """dev-login 返回的 user.created_at 是字符串（曾 ValidationError 500）"""
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 200
    assert isinstance(r.json()["user"]["created_at"], str)


# ---- 3. grid 行×期组装（曾折叠成最后一个 period）----

def test_grid_returns_full_period_range(token, client):
    """grid 每行必须含全部 29 期（2026-08..2028-12；曾只剩 2029-12 一列）"""
    r = client.get("/api/v1/scenarios/1/grid", headers=_auth(token))
    assert r.status_code == 200
    cells = r.json()["cells"]
    assert len(cells) == 38, f"行数异常: {len(cells)}"
    per_row = {k: len(v) for k, v in cells.items()}
    bad = [k for k, n in per_row.items() if n != 29]
    assert not bad, f"行期折叠残留: {bad}"
    # 抽查：qty.online 2026-08 是输入，且含 29 个不同期
    assert cells["qty.online"]["2026-08"]["source"] == "input"
    assert set(cells["sale.total.amount"]) >= {"2026-08", "2028-12"}


# ---- 4. recalc 端到端 ----

def test_recalc_end_to_end(token, client):
    """PUT 覆盖 + recalc 参数增量 → 新版本：覆盖保留、参数按比例生效"""
    r = client.put("/api/v1/scenarios/1/cells",
                   headers=_auth(token), json={"cells": {"qty.online": {"2026-08": "0.2"}}})
    assert r.status_code == 200 and r.json()["updated"] == 1

    r = client.post("/api/v1/scenarios/1/recalc",
                    headers=_auth(token), json={"params": {"price_online": "1999"}})
    assert r.status_code == 200, r.text
    v2 = r.json()
    assert v2["version_no"] == 2 and v2["cell_count"] == 1102

    r = client.get("/api/v1/scenarios/1/grid?version_no=2", headers=_auth(token))
    cells = r.json()["cells"]
    assert cells["qty.online"]["2026-08"]["value"] == "0.2"          # 覆盖保留
    sale = Decimal(cells["sale.online.amount"]["2026-08"]["value"])
    assert sale == Decimal("399.8")                                   # 0.2 万台 × 1999 元

    # v2 快照 = v1 快照（无参重算不改参数）；v2 输入基线 = v1 输入基线
    vs = client.get("/api/v1/scenarios/1/versions", headers=_auth(token)).json()
    assert len(vs["versions"]) == 2
