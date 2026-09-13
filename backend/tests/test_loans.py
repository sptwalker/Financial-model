# -*- coding: utf-8 -*-
"""贷款先息后本自检：放款月注入现金、每满 12 月结息、到期一次性还本、负债余额到期归零。"""
from decimal import Decimal

from app.engine.calculator import run, Params


def _grid(loans=None):
    periods = [f"2026-{m:02d}" for m in range(1, 13)] + [f"2027-{m:02d}" for m in range(1, 13)]
    inputs = {"cash.opening": {"2026-01": Decimal("0")}}
    return periods, run(periods, Params(loans=loans or []), inputs)


def test_interest_only_then_bullet_repayment():
    # 1000 万，2026-01 放款，年利率 10%，期限 12 月 → 到期 2027-01
    loan = {"name": "经营贷", "period": "2026-01", "amount": 1000, "rate": 0.10, "term_months": 12}
    periods, g = _grid([loan])

    # 放款月现金流入本金
    assert g["loan.principal_in"]["2026-01"]["value"] == Decimal("1000")
    # 存续期负债余额恒为本金
    assert g["loan.balance"]["2026-06"]["value"] == Decimal("1000")
    assert g["loan.balance"]["2026-12"]["value"] == Decimal("1000")
    # 满 12 月结息一次（到期月 2027-01）：1000×10% = 100
    assert g["loan.interest"]["2027-01"]["value"] == Decimal("100")
    # 中途不结息
    assert g["loan.interest"]["2026-06"]["value"] == Decimal("0")
    # 到期一次性还本，且负债余额归零
    assert g["loan.repayment"]["2027-01"]["value"] == Decimal("1000")
    assert g["loan.balance"]["2027-01"]["value"] == Decimal("0")

    # 期末现金 = 放款+1000，结息还本月 -100-1000 → 期末回落到 -100（只受贷款影响）
    assert g["cash.closing"]["2026-12"]["value"] == Decimal("1000")
    assert g["cash.closing"]["2027-01"]["value"] == Decimal("-100")


if __name__ == "__main__":
    test_interest_only_then_bullet_repayment()
    print("ok")
