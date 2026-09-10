# -*- coding: utf-8 -*-
"""auto_marketing 开关：佣金/推广费按当期销售额×费率自动测算。"""
from decimal import Decimal
from app.engine.calculator import run, Params, periods_between

TOL = Decimal("0.0001")


def _grid(auto):
    periods = periods_between("2026-01", "2028-12")
    params = Params(auto_marketing=auto, price_online=Decimal("1799"),
                    price_offline=Decimal("1000"))
    inputs = {"qty.online": {p: Decimal("1") for p in periods},
              "qty.offline": {p: Decimal("2") for p in periods}}
    return periods, run(periods, params, inputs)


def test_auto_marketing_formulas():
    periods, g = _grid(True)
    for p in periods:
        off = Decimal(g["sale.offline.amount"][p]["value"])   # 2 * 1000 = 2000元/万台→ 200万
        on = Decimal(g["sale.online.amount"][p]["value"])
        yr = int(p[:4])
        rate = {2026: Decimal("0.30"), 2027: Decimal("0.26"), 2028: Decimal("0.23")}[yr]
        assert abs(Decimal(g["exp.channel_commission"][p]["value"]) - off * Decimal("0.05")) <= TOL, p
        assert abs(Decimal(g["exp.channel_promo"][p]["value"]) - off * Decimal("0.02")) <= TOL, p
        assert abs(Decimal(g["exp.online_promo"][p]["value"]) - on * rate) <= TOL, p


def test_off_is_passthrough():
    # 关闭时这三行=输入（此处输入为 0）
    periods, g = _grid(False)
    assert Decimal(g["exp.channel_promo"]["2027-05"]["value"]) == 0


if __name__ == "__main__":
    test_auto_marketing_formulas(); test_off_is_passthrough(); print("OK")
