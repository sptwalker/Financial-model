# -*- coding: utf-8 -*-
"""重算服务测试：v1 基线 → 无参重算逐格一致；参数覆盖按比例生效并保留输入行"""
import json
from dataclasses import asdict
from decimal import Decimal

import pytest

from app.engine.calculator import Params
from app.models.financial import Cell, ModelVersion, Scenario
from app.services.recalc_service import recalc, merge_params


@pytest.fixture(scope="module")
def db():
    from app.db.session import SessionLocal, init_db
    init_db()
    session = SessionLocal()
    yield session
    session.close()


@pytest.fixture(scope="module")
def seeded(db):
    """重置情景 1 到纯净 v1（幂等）"""
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


def _grid(db, version_no):
    return {c.row_key + "|" + c.period: Decimal(c.value)
            for c in db.query(Cell).filter(Cell.scenario_id == 1,
                                           Cell.model_version == version_no).all()}


def _latest(db):
    return db.query(ModelVersion).filter(ModelVersion.scenario_id == 1) \
        .order_by(ModelVersion.version_no.desc()).first()


def test_recalc_no_change_is_identical(seeded):
    """无参数变化重算 → 新版本与上一版逐格一致"""
    db = seeded
    r = recalc(db, 1, comment="test: no change")
    assert r["version_no"] == _latest(db).version_no
    v_prev = _grid(db, r["version_no"] - 1)
    v_new = _grid(db, r["version_no"])
    assert v_prev.keys() == v_new.keys()
    assert not [k for k in v_prev if v_prev[k] != v_new[k]]


def test_recalc_price_override_proportional(seeded):
    """改线上售价 → 线上销售额按比例变化；输入行/其他行不变"""
    db = seeded
    base_no = _latest(db).version_no
    base = _grid(db, base_no)
    r = recalc(db, 1, params_override={"price_online": "1999"}, comment="test: price")
    new = _grid(db, r["version_no"])
    p = "sale.online.amount|2026-08"
    assert new[p] == base[p] * Decimal("1999") / Decimal("1799")
    assert new["qty.online|2026-08"] == base["qty.online|2026-08"]
    assert new["exp.salary|2026-08"] == base["exp.salary|2026-08"]
    assert new["sale.offline.amount|2026-08"] == base["sale.offline.amount|2026-08"]


def test_recalc_snapshots_carried_forward(seeded):
    """新版本携带 inputs/params 快照；参数沿用上一版（覆盖后的值也延续）"""
    db = seeded
    prev = _latest(db)
    assert prev.inputs_json and prev.params_json
    r = recalc(db, 1, comment="test: snapshot")
    v = db.query(ModelVersion).filter(ModelVersion.scenario_id == 1,
                                      ModelVersion.version_no == r["version_no"]).first()
    assert json.loads(v.params_json) == json.loads(prev.params_json)
    assert v.inputs_json == prev.inputs_json


def test_merge_params_layering():
    """merge_params：默认 ← 快照 ← 用户增量，逐层覆盖"""
    base = asdict(Params())
    p = merge_params({"price_online": "1999"}, {"price_online": "2099"})
    assert p.price_online == Decimal("2099")
    p2 = merge_params({"price_online": "1999"}, None)
    assert p2.price_online == Decimal("1999")
    assert p2.price_offline == base["price_offline"]
