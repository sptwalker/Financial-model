# -*- coding: utf-8 -*-
"""重算服务测试：v1 基线 → 无参重算逐格一致；参数覆盖按比例生效并保留输入行"""
import json
from dataclasses import asdict
from decimal import Decimal

import pytest

from app.engine.calculator import Params
from app.models.financial import Cell, ModelVersion, Scenario
from app.services.recalc_service import recalc, merge_params, preview_grid


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


def test_merge_params_ignores_stale_snapshot_keys():
    """旧快照残留的已废弃字段（如 online_mkt_rate）不应让 Params(**) 崩溃，只丢弃"""
    p = merge_params({"price_online": "1999", "online_mkt_rate": "0.3"}, None)
    assert p.price_online == Decimal("1999")
    assert not hasattr(p, "online_mkt_rate")


def test_preview_does_not_persist(seeded):
    """预览端点：叠加 inputs/params 实时算，不建版本；网格反映融资注入"""
    db = seeded
    before = _latest(db).version_no
    p0 = "2026-08"
    grid = preview_grid(db, 1, inputs_override={"cash.financing": {p0: "888"}})
    # 未建新版本
    assert _latest(db).version_no == before
    # 融资行透传，且期末现金较无融资抬升 888
    assert Decimal(grid["cash.financing"][p0]["value"]) == Decimal("888")
    base_grid = preview_grid(db, 1)
    assert (Decimal(grid["cash.closing"][p0]["value"])
            - Decimal(base_grid["cash.closing"][p0]["value"])) == Decimal("888")


def test_recalc_inputs_override_sticky(seeded):
    """recalc 带 inputs_override → 新版本落库且融资值粘性写入网格"""
    db = seeded
    r = recalc(db, 1, inputs_override={"cash.financing": {"2026-09": "500"}},
               comment="test: financing")
    new = _grid(db, r["version_no"])
    assert new["cash.financing|2026-09"] == Decimal("500")


# ---------- 错误路径与脏数据容错 ----------

def test_recalc_raises_on_missing_scenario_and_version(db):
    """不存在的场景 / 无版本 → 抛 ValueError，由路由层翻译成 404"""
    with pytest.raises(ValueError, match="scenario_not_found"):
        recalc(db, 987654, comment="test: missing")
    with pytest.raises(ValueError, match="scenario_not_found"):
        preview_grid(db, 987654)


def test_recalc_raises_no_version_for_empty_scenario(db):
    """新建情景无版本 → no_version（而非 500）"""
    from app.models.financial import Scenario
    sc = Scenario(name="empty-for-recalc-test")
    db.add(sc)
    db.commit()
    try:
        with pytest.raises(ValueError, match="no_version"):
            recalc(db, sc.id, comment="test: no version")
    finally:
        db.delete(sc)
        db.commit()


def test_parse_json_tolerates_corrupt_and_non_dict(seeded):
    """快照 JSON 损坏 / 不是对象 → 回退空 dict，不抛异常（旧版本兼容）"""
    from app.services.recalc_service import _parse_json
    assert _parse_json(None) == {}
    assert _parse_json("") == {}
    assert _parse_json("{不是合法 JSON") == {}
    assert _parse_json("[1,2,3]") == {}          # 合法 JSON 但非对象
    assert _parse_json('{"a": 1}') == {"a": 1}


def test_rebuild_inputs_skips_dirty_and_non_input_sources(seeded):
    """回退重建：仅收 input/override 源；脏 Decimal 跳过而不中断"""
    from app.services.recalc_service import rebuild_inputs

    class _C:
        def __init__(self, row_key, period, value, source):
            self.row_key, self.period, self.value, self.source = row_key, period, value, source

    cells = [
        _C("qty.online", "2026-08", "10", "input"),
        _C("qty.online", "2026-09", "11", "override"),
        _C("sale.online.amount", "2026-08", "99999", "engine"),   # 非输入源 → 不收
        _C("qty.offline", "2026-08", "坏数据", "input"),           # 脏值 → 跳过
    ]
    out = rebuild_inputs(cells)
    assert set(out) == {"qty.online"}
    assert out["qty.online"]["2026-09"] == Decimal("11")
    assert "2026-08" in out["qty.online"]

