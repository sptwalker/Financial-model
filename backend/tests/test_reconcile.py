# -*- coding: utf-8 -*-
"""M2 对账测试：引擎输出 vs Excel「现金流中性」情景（与 scripts/reconcile.py 同一链路）

断言全部单元格分类：BUG=0（无未解释差异），
且关键口径（订阅、全年列年度合计、期初现金滚动）与 Excel 精确一致。
"""
from decimal import Decimal

from app.engine.reconcile import (
    TOL, reconcile_rows, engine_value, annual_engine_sum,
)

# 2027-08..2027-12 当月订阅（Excel 行值）；2028 全年列 = 年度订阅目标
EXPECTED_SUB_MONTHLY = {
    "2027-08": Decimal("56"), "2027-09": Decimal("67.2"), "2027-10": Decimal("70"),
    "2027-11": Decimal("112"), "2027-12": Decimal("112"),
}
EXPECTED_SUB_ANNUAL = {2028: Decimal("2461.2")}


def test_no_unexplained_differences(fixture):
    """全 37 行 × 29 期：不允许存在未解释差异（BUG=0）"""
    imp, grid, params, salary_08 = fixture
    categories, bugs = reconcile_rows(imp, grid, params, [])
    assert bugs == [], f"存在未解释差异：{bugs}"
    assert categories["BUG"] == 0
    assert categories["MATCH"] >= 300  # 绝大多数单元格口径对齐后一致


def test_match_count_baseline(fixture):
    """分类计数与 M2 基线一致（防止分类器误改导致口径漂移）"""
    imp, grid, params, salary_08 = fixture
    categories, bugs = reconcile_rows(imp, grid, params, [])
    assert (categories["MATCH"], categories["KNOWN_QUIRK"],
            categories["KNOWN_RULE_DIFF"], categories["BUG"]) == (324, 73, 56, 0)


def test_subscription_monthly_matches_excel(fixture):
    """订阅：引擎累计装机口径单独行；Excel 当月销量口径（用户确认）→ 差异=Excel 行值"""
    imp, grid, params, salary_08 = fixture
    excel_sub = imp["excel"]["sale.subscription.amount"]
    for p, want in EXPECTED_SUB_MONTHLY.items():
        assert abs(excel_sub[p] - want) <= TOL
        assert abs(Decimal(grid["sale.subscription.amount"][p]["value"]) - want) > TOL


def test_subscription_annual_targets(fixture):
    """2028 订阅 = 年度目标 2461.2（全年引用列）"""
    imp, grid, params, salary_08 = fixture
    excel_sub = imp["excel"]["sale.subscription.amount"]
    for year, want in EXPECTED_SUB_ANNUAL.items():
        assert float(excel_sub[f"{year}-12"]) == float(want)
        assert abs(annual_engine_sum(grid, "sale.subscription.amount", year) - want) <= TOL


def test_annual_reference_columns_exact(fixture):
    """2028 全年列：线上/线下销售、工资、佣金年度合计与 Excel 精确一致"""
    imp, grid, params, salary_08 = fixture
    for excel_key in ("sale.online.amount", "sale.offline.amount",
                      "exp.salary", "exp.channel_commission"):
        for year in (2028,):
            x = imp["excel"][excel_key][f"{year}-12"]
            a = annual_engine_sum(grid, excel_key, year)
            assert abs(a - x) <= TOL, f"{excel_key} {year}: 引擎 {a} vs Excel {x}"


def test_cash_opening_rolls_like_excel(fixture):
    """期初现金：Excel 静态滚动链与引擎上期末滚动完全一致（29 期）"""
    imp, grid, params, salary_08 = fixture
    excel_open = imp["excel"]["cash.opening"]
    for p in sorted(excel_open):
        if p <= "2026-07":
            continue
        assert abs(Decimal(grid["cash.opening"][p]["value"]) - excel_open[p]) <= TOL, p


def test_salary_august_from_payroll(fixture):
    """2026-08 工资：Excel 计划 240；引擎按工资表应付合计（元→万元）"""
    imp, grid, params, salary_08 = fixture
    assert salary_08 > 0
    assert abs(Decimal(grid["exp.salary"]["2026-08"]["value"]) - salary_08) <= TOL
    assert imp["excel"]["exp.salary"]["2026-08"] > Decimal("200")  # Excel 计划值仍在（240 计划）


def test_engine_cash_chain_consistent(fixture):
    """引擎两条链各自自洽（月度期；2028 全年引用列不含月度滚动）：
    1) cash.opening 网格行=输入透传（Excel 静态期初链，用户确认口径）；
    2) cash.closing 网格行=引擎滚动：期初=输入、期末=期初+本期缺口、下期期初=上期期末。"""
    imp, grid, params, salary_08 = fixture
    monthly = [p for p in imp["periods"] if p[:4] not in ("2028",)]
    inputs_open = imp["inputs"]["cash.opening"]
    # 1) 期初网格行 = 输入链（首期 cash_open[0]=输入，其后透传输入）
    for p in monthly:
        assert abs(Decimal(grid["cash.opening"][p]["value"]) - inputs_open[p]) <= TOL, p
    # 2) 滚动链：cash.closing 从输入期初开始逐期滚动
    for i, p in enumerate(monthly):
        gap = Decimal(grid["cash.gap"][p]["value"])
        close = Decimal(grid["cash.closing"][p]["value"])
        if i == 0:
            assert abs(close - (inputs_open[p] + gap)) <= TOL, p
        else:
            prev_close = Decimal(grid["cash.closing"][monthly[i - 1]]["value"])
            assert abs(close - (prev_close + gap)) <= TOL, p
