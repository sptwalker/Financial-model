# -*- coding: utf-8 -*-
"""cash.financing 自检：某月注入融资 → 该月起期末现金抬升对应额，销售/费用行不变。"""
from decimal import Decimal

from app.engine.calculator import run, Params, periods_between, CASH_FINANCING


def _grid(financing=None):
    periods = periods_between("2026-07", "2027-06")
    inputs = {
        "qty.online": {p: Decimal("1") for p in periods},
        "cash.opening": {"2026-07": Decimal("100")},
    }
    if financing:
        inputs[CASH_FINANCING] = financing
    return periods, run(periods, Params(), inputs)


def test_financing_lifts_closing_cash():
    periods, base = _grid()
    _, inj = _grid({"2026-09": Decimal("500")})
    # 注入月之前：期末现金一致
    assert inj["cash.closing"]["2026-08"]["value"] == base["cash.closing"]["2026-08"]["value"]
    # 注入月及之后：每期期末现金恰好抬升 500（滚动累积）
    for p in periods[periods.index("2026-09"):]:
        assert inj["cash.closing"][p]["value"] - base["cash.closing"][p]["value"] == Decimal("500")
    # 销售/费用行不受融资影响
    assert inj["sale.total.amount"]["2026-09"]["value"] == base["sale.total.amount"]["2026-09"]["value"]
    assert inj["exp.total"]["2026-09"]["value"] == base["exp.total"]["2026-09"]["value"]
    # 融资行透传到网格
    assert inj[CASH_FINANCING]["2026-09"]["value"] == Decimal("500")


if __name__ == "__main__":
    test_financing_lifts_closing_cash()
    print("ok")
