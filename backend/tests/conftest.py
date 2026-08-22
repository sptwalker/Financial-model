# -*- coding: utf-8 -*-
"""pytest 夹具：加载 Excel 数据 → 引擎计算 → 对账网格（与 scripts/reconcile.py 同链路）"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.engine.reconcile import load_fixture  # noqa: E402


@pytest.fixture(scope="session")
def fixture():
    """(imp, grid, params, salary_07)：2026-07..2028-12 全期间引擎 vs Excel"""
    return load_fixture()


@pytest.fixture(scope="session", autouse=True)
def reset_db_after_all_tests():
    """会话收尾：清掉各模块测试改写情景 1 / 历史表的残留（v5-7、forecast_runs、
    manual/import actuals），重跑 seed 恢复到纯净 v1，保证全量测试后 dev DB 不被污染。
    模块级 seeded 只做前置复位、不做后置清理，因此必须以会话级兜底。

    seed_from_excel 就地更新「中性」(id 不漂移)，故预算克隆(2/3)不受影响、无需在此清理。"""
    yield
    from app.db.session import SessionLocal
    from app.models.financial import Cell, ModelVersion, Scenario
    from app.models.forecast import ForecastRun, SalesActual

    db = SessionLocal()
    try:
        if db.query(Scenario).filter(Scenario.id == 1).first():
            db.query(ForecastRun).delete()
            db.query(SalesActual).delete()
            db.query(Cell).filter(Cell.scenario_id == 1).delete()
            db.query(ModelVersion).filter(ModelVersion.scenario_id == 1).delete()
            db.commit()
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from scripts.seed_from_excel import main as seed_main
        seed_main()
        print("\n[conftest] 会话结束：已重置情景 1 到纯净 seed 状态")
    finally:
        db.close()
