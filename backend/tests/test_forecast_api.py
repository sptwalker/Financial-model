# -*- coding: utf-8 -*-
"""预测 API 端点测试（阶段 3 · Phase B）：actuals CRUD/导入 / run / apply / runs。

自带 seeded 复位（情景 1 → 纯净 v1），独立于 test_forecast.py 的服务级变更。
"""
import io

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.financial import Cell, ModelVersion, Scenario


@pytest.fixture(scope="module")
def db():
    from app.db.session import SessionLocal, init_db
    init_db()
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def seeded(db):
    old = db.query(Scenario).filter(Scenario.id == 1).first()
    if old:
        db.query(Cell).filter(Cell.scenario_id == 1).delete()
        db.query(ModelVersion).filter(ModelVersion.scenario_id == 1).delete()
        db.commit()
    from app.models.forecast import SalesActual
    db.query(SalesActual).delete()  # 全局历史表：先清空再种子，防跨模块残留
    db.commit()
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
    from scripts.seed_from_excel import main as seed_main
    seed_main()
    return db


@pytest.fixture(scope="module")
def client(seeded):
    return TestClient(app)


@pytest.fixture(scope="module")
def auth(client):
    r = client.post("/api/v1/auth/dev-login")
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---------- 历史 ----------

def test_list_actuals_seeded(client, auth):
    r = client.get("/api/v1/forecast/actuals", headers=auth)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["actuals"]) == 4                 # 2026-07/08 × 线上/线下
    assert body["n_effective"] == 1                  # 仅 2026-08 总量>0


def test_upsert_actuals_and_reflect(client, auth):
    r = client.post("/api/v1/forecast/actuals", headers=auth,
                    json={"actuals": [{"period": "2026-09", "channel": "online", "units": "0.15"},
                                      {"period": "2026-09", "channel": "offline", "units": "0.35"}]})
    assert r.status_code == 200 and r.json()["upserted"] == 2, r.text
    body = client.get("/api/v1/forecast/actuals", headers=auth).json()
    assert body["n_effective"] == 2                  # 08、09 均 >0
    assert body["total_by_period"]["2026-09"] == "0.50"


def test_upsert_actuals_rejects_bad_input(client, auth):
    r = client.post("/api/v1/forecast/actuals", headers=auth,
                    json={"actuals": [{"period": "2026-09", "channel": "web", "units": "1"}]})
    assert r.status_code == 400
    r = client.post("/api/v1/forecast/actuals", headers=auth,
                    json={"actuals": [{"period": "2026-13", "channel": "online", "units": "1"}]})
    assert r.status_code == 400
    r = client.post("/api/v1/forecast/actuals", headers=auth,
                    json={"actuals": [{"period": "2026-09", "channel": "online", "units": "-1"}]})
    assert r.status_code == 400


def test_import_actuals_xlsx(client, auth):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["月份", "线上(万台)", "线下(万台)"])
    ws.append(["2026-10", 0.2, 0.5])
    ws.append(["2026-11", 0.25, 0.6])
    buf = io.BytesIO()
    wb.save(buf)
    r = client.post("/api/v1/forecast/actuals/import", headers=auth,
                    files={"file": ("hist.xlsx", buf.getvalue(),
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 200, r.text
    assert r.json()["upserted"] == 4                 # 2 月 × 2 渠道
    body = client.get("/api/v1/forecast/actuals", headers=auth).json()
    assert "2026-10" in body["total_by_period"]


def test_import_rejects_non_xlsx(client, auth):
    r = client.post("/api/v1/forecast/actuals/import", headers=auth,
                    files={"file": ("x.csv", b"a,b", "text/csv")})
    assert r.status_code == 400


# ---------- 运行 ----------

def test_run_forecast_endpoint(client, auth):
    r = client.post("/api/v1/forecast/run", headers=auth, json={"scenario_id": 1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["method"] == "plan_anchored"
    assert len(body["series"]) == 17
    pt = body["series"][0]
    assert isinstance(pt["yhat"], str)               # Decimal 序列化为字符串（不丢精度）
    assert set(pt) >= {"period", "yhat", "lower", "upper", "online", "offline"}


def test_run_forecast_scenario_not_found(client, auth):
    r = client.post("/api/v1/forecast/run", headers=auth, json={"scenario_id": 9999})
    assert r.status_code == 404


# ---------- 接受（三情景，放最后，会改情景 1 版本链） ----------

def test_apply_three_scenarios_endpoint(client, auth):
    run = client.post("/api/v1/forecast/run", headers=auth, json={"scenario_id": 1}).json()
    ratio = float(run["ratio_online"])

    def scn(key):
        return [{"period": pt["period"],
                 "online": str(float(pt[key]) * ratio),
                 "offline": str(float(pt[key]) * (1 - ratio))} for pt in run["series"]]

    r = client.post("/api/v1/forecast/apply", headers=auth,
                    json={"scenario_id": 1, "method": run["method"],
                          "base": scn("yhat"), "lower": scn("lower"), "upper": scn("upper"),
                          "comment": "api测试"})
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["base_version"] > out["upper_version"] > out["lower_version"]

    runs = client.get("/api/v1/forecast/runs?scenario_id=1", headers=auth).json()["runs"]
    assert runs and runs[0]["base_version"] == out["base_version"]
    assert runs[0]["lower_version"] == out["lower_version"]
