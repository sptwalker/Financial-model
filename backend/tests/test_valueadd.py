# -*- coding: utf-8 -*-
"""增值收入（第5类收入流）测试：默认关闭（ARPU=0 → 全期 0，不动对账基线），
启用后按累计装机×比例×ARPU/12 计入销售额合计，并即时回款进现金。"""
from decimal import Decimal

from app.engine.calculator import Params, run, periods_between


def _inputs():
    # 两期各卖 1 万台线上（累计装机 1→2）
    return {"qty.online": {"2026-08": Decimal("1"), "2026-09": Decimal("1")},
            "cash.opening": {"2026-08": Decimal("0")}}


def test_valueadd_zero_by_default():
    periods = periods_between("2026-08", "2026-09")
    grid = run(periods, Params(), _inputs())
    for p in periods:
        assert Decimal(grid["sale.valueadd.amount"][p]["value"]) == 0
        assert Decimal(grid["collect.valueadd"][p]["value"]) == 0


def test_valueadd_flows_into_total_and_cash():
    periods = periods_between("2026-08", "2026-09")
    # ARPU 120 元/台/年，付费占比 0.5 → 08 月增值 = 装机1 × 0.5 × 120 / 12 = 5 万元
    p = Params(valueadd_ratio=Decimal("0.5"), valueadd_revenue_per_unit=Decimal("120"))
    grid = run(periods, p, _inputs())
    va_08 = Decimal(grid["sale.valueadd.amount"]["2026-08"]["value"])
    va_09 = Decimal(grid["sale.valueadd.amount"]["2026-09"]["value"])
    assert va_08 == Decimal("5")           # 累计装机 1
    assert va_09 == Decimal("10")          # 累计装机 2
    # 计入销售额合计
    parts = sum(Decimal(grid[k]["2026-08"]["value"]) for k in
                ("sale.online.amount", "sale.offline.amount", "sale.accessory.amount",
                 "sale.subscription.amount", "sale.valueadd.amount"))
    assert Decimal(grid["sale.total.amount"]["2026-08"]["value"]) == parts
    # 即时回款：collect.valueadd == sale.valueadd，且计入回款合计
    assert Decimal(grid["collect.valueadd"]["2026-08"]["value"]) == va_08
    assert Decimal(grid["collect.total"]["2026-08"]["value"]) >= va_08
