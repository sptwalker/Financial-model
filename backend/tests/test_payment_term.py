# -*- coding: utf-8 -*-
"""付款账期自检：天→月权重折算，且 60 天与旧 N+2 逐月等价；缩短账期使采购付款提前。"""
from decimal import Decimal

from app.engine.calculator import (
    payment_weights, run, Params, periods_between, PURCHASE_TOTAL,
)


def test_weights_shape_and_sum():
    assert payment_weights(60) == [Decimal(0), Decimal(0), Decimal(1)]   # ≡ N+2
    assert payment_weights(30) == [Decimal(0), Decimal(1)]
    assert payment_weights(45) == [Decimal(0), Decimal("0.5"), Decimal("0.5")]
    assert payment_weights(120) == [Decimal(0)] * 4 + [Decimal(1)]
    for d in (15, 30, 45, 60, 75, 90, 105, 120):
        assert sum(payment_weights(d)) == Decimal(1)


def _purchase(days):
    periods = periods_between("2026-07", "2027-06")
    inputs = {"qty.online": {p: Decimal("10") for p in periods}}
    grid = run(periods, Params(purchase_term_days=days), inputs)
    return periods, grid[PURCHASE_TOTAL]


def test_shorter_term_pays_earlier():
    periods, p60 = _purchase(60)   # 采购付款落在第 3 个月起
    _, p30 = _purchase(30)         # 缩短到 30 天 → 落在第 2 个月起
    i = periods.index("2026-08")   # 首笔采购(07)在 30 天账期下 08 月付，60 天账期尚未付
    assert p30[periods[i]]["value"] > p60[periods[i]]["value"]
    # 全周期付款总额一致（只是时点前移；末尾未落地部分两者都被截断，故取共同已落地区间比较）
    assert sum(Decimal(p30[p]["value"]) for p in periods[:i + 2]) >= \
           sum(Decimal(p60[p]["value"]) for p in periods[:i + 2])
