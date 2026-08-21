# -*- coding: utf-8 -*-
"""pytest 夹具：加载 Excel 数据 → 引擎计算 → 对账网格（与 scripts/reconcile.py 同链路）"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.engine.reconcile import load_fixture  # noqa: E402


@pytest.fixture(scope="session")
def fixture():
    """(imp, grid, params, salary_07)：2026-07..2029-12 全期间引擎 vs Excel"""
    return load_fixture()
