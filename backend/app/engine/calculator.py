"""计算引擎：输入（销量/费用/参数）→ 全量行×期网格

口径（已与财务确认，2026-08 版）：
- 销售：线上金额=线上台数×线上售价；线下金额=线下台数×线下售价；配件收入=总台数×0.5×200
- 订阅：月度=累计装机量×0.7×(200/12)（单价 200 元/台/年，即时到账）；2026-07 前装机初值=现金流量表数值（0）；随新增装机持续累积，2028 不做年度目标覆盖
- 硬件销量 2028 仅年度目标（存于该年 12 月行），用 2026-2027 季节曲线月度化
- 回款：线上 [0.5,0.5]（当月50%+上月50%）；线下 [0,1]（N+1）；订阅/增值 [1]（即时）
- 采购：整机+配件均 N+2=[0,0,1]，可配置 N+3
- 费用：全部直接输入（kind=input），引擎不计算
- 现金：期初+回款-支出=期末，滚动；期初首期=输入
- 单位：万元；内部一律 Decimal(20,8)，展示层再换算

设计：纯函数、不依赖数据库。入参为"每期输入"，出参为完整网格。
计算结果保存在 cells 表；改参数→引擎重算→生成新版本号。
"""

from dataclasses import dataclass, field
from decimal import Decimal, getcontext
from typing import Optional

getcontext().prec = 28  # 保证 Decimal 运算精确，存储时按 20,8 截断

# ---------- 行键规范（引擎/导入器/前端共用契约） ----------

# 销量（万台）——输入行
QTY_ONLINE = "qty.online"       # 线上销量（万台）
QTY_OFFLINE = "qty.offline"     # 线下销量（万台）
QTY_TOTAL = "qty.total"         # 总销量（万台）= 线上+线下（引擎计算）
HEADCOUNT = "exp.headcount"     # 人数（输入）

# 年度目标（万台/万元）——输入行，存于该年 12 月；引擎用季节曲线摊到各月
TARGET_SALES = "target.sales"
TARGET_SUB = "target.subscription"

# 销售/收入（万元）——引擎计算
SALE_ONLINE = "sale.online.amount"
SALE_OFFLINE = "sale.offline.amount"
SALE_ACC = "sale.accessory.amount"
SALE_SUB = "sale.subscription.amount"
SALE_TOTAL = "sale.total.amount"

# 采购（万元）——引擎计算
PURCHASE_MAIN = "purchase.main"       # 整机采购（付款额，按账期）
PURCHASE_ACC = "purchase.accessory"   # 配件采购（付款额，按账期）
PURCHASE_TOTAL = "purchase.total"

# 回款（万元）——引擎计算
COLLECT_ONLINE = "collect.online"
COLLECT_OFFLINE = "collect.offline"
COLLECT_SUB = "collect.subscription"
COLLECT_TOTAL = "collect.total"

# 现金（万元）——引擎计算（期初首期为输入）
CASH_OPEN = "cash.opening"
CASH_IN = "cash.incoming"
CASH_EXP = "cash.expense"
CASH_GAP = "cash.gap"          # 本期缺口 = 回款 - 支出
CASH_CLOSE = "cash.closing"
CASH_FINANCING = "cash.financing"  # 投融资到账款（输入，特定月一次性注入现金，不摊分）

# 费用行（万元/月）——全部输入
EXPENSE_ROWS = [
    "exp.salary",              # 工资
    "exp.game_dev",            # 游戏外包开发
    "exp.commercial_ip",       # 商业IP
    "exp.license",             # 版号
    "exp.office_hw",           # 办公硬件
    "exp.it_service",          # 信息技术服务
    "exp.rent",                # 房租
    "exp.recruit",             # 招聘费
    "exp.office_other",        # 办公及其他
    "exp.brand",               # 品牌宣传
    "exp.channel_commission",  # 渠道佣金（默认=线下销售×5%，可覆盖）
    "exp.channel_promo",       # 渠道推广费
    "exp.online_promo",        # 线上推广费
]
EXPENSE_TOTAL = "exp.total"    # 费用合计 = 各行之和（引擎计算）

# 营销自动测算涉及的行（auto_marketing 开启时按销售额×费率，忽略输入）
AUTO_MKT_ROWS = frozenset({"exp.channel_commission", "exp.channel_promo", "exp.online_promo"})

# 全部引擎计算行
COMPUTED_ROWS = frozenset({
    QTY_TOTAL, SALE_ONLINE, SALE_OFFLINE, SALE_ACC, SALE_SUB, SALE_TOTAL,
    PURCHASE_MAIN, PURCHASE_ACC, PURCHASE_TOTAL,
    COLLECT_ONLINE, COLLECT_OFFLINE, COLLECT_SUB, COLLECT_TOTAL,
    CASH_IN, CASH_EXP, CASH_GAP, CASH_CLOSE, EXPENSE_TOTAL,
})

# 输入行全集
INPUT_ROWS = frozenset({
    QTY_ONLINE, QTY_OFFLINE, HEADCOUNT, TARGET_SALES, TARGET_SUB, CASH_OPEN,
    CASH_FINANCING,
    *EXPENSE_ROWS,
})


@dataclass
class Params:
    """引擎参数（默认值=Excel/财务确认值，全部可在前端修改）"""
    # 售价（元/台，含税）
    price_online: Decimal = Decimal("1799")
    price_offline: Decimal = Decimal("1475.18")
    # 采购价（元/台，含税）
    cost_main: Decimal = Decimal("1150")
    cost_accessory: Decimal = Decimal("60")        # 单台配件采购成本
    # 配件收入
    acc_ratio: Decimal = Decimal("0.5")            # 配件销售占比
    acc_revenue_per_unit: Decimal = Decimal("200")  # 单台配件收入（元）
    # 订阅
    sub_ratio: Decimal = Decimal("0.7")            # 订阅比例
    sub_revenue_per_unit: Decimal = Decimal("200")  # 单台订阅收益（元/台/年，月度收入 ÷12）
    # 营销费率
    online_mkt_rate: Decimal = Decimal("0.30")
    offline_mkt_rate: Decimal = Decimal("0.23")
    # 渠道佣金费率（渠道佣金=线下销售×费率）
    channel_commission_rate: Decimal = Decimal("0.05")
    # 营销费用自动测算（预算页开关）：开启后佣金/推广费按当期销售额×费率，忽略输入值
    auto_marketing: bool = False
    channel_promo_rate: Decimal = Decimal("0.02")          # 渠道推广费=线下销售额×费率
    # 线上推广费=线上销售额×费率，分年（2026/2027/2028）
    online_promo_rate_2026: Decimal = Decimal("0.30")
    online_promo_rate_2027: Decimal = Decimal("0.26")
    online_promo_rate_2028: Decimal = Decimal("0.23")
    # 回款权重（渠道 → [当月, 次月]；线下 N+1 即 [0,1]）
    collect_weight_online: list = field(default_factory=lambda: [Decimal("0.5"), Decimal("0.5")])
    collect_weight_offline: list = field(default_factory=lambda: [Decimal("0"), Decimal("1")])
    collect_weight_sub: list = field(default_factory=lambda: [Decimal("1")])
    # 采购付款账期（N+M）：[0,0,1]=N+2，[0,0,0,1]=N+3（可配置）
    purchase_lag: int = 2
    # 2026-07 前累计装机量（万台，按现金流量表数值）
    install_base_initial: Decimal = Decimal("0")
    # 情景销量系数（中性 1 / 乐观 1.2 / 悲观 0.8）：对最终销量整体缩放
    qty_scale: Decimal = Decimal("1")


def _d(x) -> Decimal:
    return Decimal(str(x))


def periods_between(start: str, end: str) -> list[str]:
    """'start'..'end'（含端点）逐月列表，如 '2026-08'..'2028-12'"""
    y1, m1 = map(int, start.split("-"))
    y2, m2 = map(int, end.split("-"))
    out = []
    y, m = y1, m1
    while (y, m) <= (y2, m2):
        out.append(f"{y:04d}-{m:02d}")
        m += 1
        if m > 12:
            m = 1
            y += 1
    return out


def seasonal_weights(periods: list[str], qty_by_period: dict[str, Decimal]) -> dict[int, list[Decimal]]:
    """年度季节曲线：以历史逐月销量形状为权重，按年归一化。

    例：2026 有 7-12 月形状 → 2028 各月权重 = 2026 对应月权重/年合计。
    有年度目标时用上年形状（2028→2026 形状）；无上年数据则用最新一年。
    """
    years = sorted({int(p[:4]) for p in periods})
    weights: dict[int, list[Decimal]] = {}
    for year in years:
        months = [p for p in periods if int(p[:4]) == year]
        vals = []
        for p in months:
            v = qty_by_period.get(p)
            vals.append(v if v is not None else Decimal(0))
        total = sum(vals, Decimal(0))
        weights[year] = [v / total for v in vals] if total > 0 else \
            [Decimal(1) / len(vals)] * len(vals)
    return weights


def monthlyize(annual: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """年度目标 → 月度分布（按季节曲线），余数归入 12 月保证年度精确"""
    parts = [annual * w for w in weights]
    done = sum(parts[:-1], Decimal(0))
    return parts[:-1] + [annual - done]


def _row_year_targets(inputs: dict, row_key: str, periods: list[str]) -> dict[int, Decimal]:
    """{年: 全年值}：目标行存于该年 12 月输入槽。

    守卫：该年已有其他月份输入时，12 月视为普通月度值（如佣金 2026-12=47.2554），
    只有该年无任何月度输入时，12 月槽才是年度目标（如 2028-12=1575.18）。
    """
    out = {}
    for year in {int(p[:4]) for p in periods}:
        months = [p for p in periods if p.startswith(f"{year}-") and not p.endswith("-12")]
        has_monthly = any(inputs.get(row_key, {}).get(p) is not None for p in months)
        v = inputs.get(row_key, {}).get(f"{year}-12")
        if v is not None and not has_monthly:
            out[year] = v
    return out


def _shape_year(weights: dict[int, list], target_years: set, year: int) -> int:
    """目标年形状来源：最近一个有月度形状且非目标年的年份；没有则用目标年本身（均匀）"""
    candidates = [y for y in weights if y not in target_years]
    if candidates:
        return max(candidates)
    return max((y for y in weights if y < year), default=year)


def _monthlyize_row(values: list, periods: list[str], weights: dict[int, list],
                    target_years: set, annual_by_year: dict[int, Decimal]) -> None:
    """把 {年: 全年值} 摊到该年各月，替换 values 中对应月份（原地修改）"""
    for year, annual in annual_by_year.items():
        parts = monthlyize(annual, weights[_shape_year(weights, target_years, year)])
        for j, part in zip([j for j, pp in enumerate(periods) if int(pp[:4]) == year], parts):
            values[j] = part


def run(periods: list[str], params: Params,
        inputs: dict[str, dict[str, Decimal]] = None,
        overrides: dict[str, dict[str, Decimal]] = None) -> dict[str, dict[str, dict]]:
    """引擎主入口。

    入参：
    - periods: 期间列表 ['2026-07', ...]
    - params: Params
    - inputs: {row_key: {period: Decimal}}——销量、费用、期初现金、年度目标等输入行
    - overrides: {row_key: {period: Decimal}}——用户覆盖（优先级高于引擎计算）

    返回：{row_key: {period: {"value": str(Decimal), "source": str}}}
    """
    inputs = inputs or {}
    overrides = overrides or {}
    n = len(periods)
    zero = Decimal("0")

    def inp(row: str, i: int) -> Decimal:
        return inputs.get(row, {}).get(periods[i], zero)

    # 年度目标（存于各年 12 月）——订阅不再用年度目标覆盖，改为始终累积口径
    sales_targets = _row_year_targets(inputs, TARGET_SALES, periods)

    # ---------- 1. 销量：输入或年度目标季节化（线上/线下分渠道摊） ----------
    qty_online = [inp(QTY_ONLINE, i) for i in range(n)]
    qty_offline = [inp(QTY_OFFLINE, i) for i in range(n)]
    sales_targets = _row_year_targets(inputs, TARGET_SALES, periods)
    target_years = set(sales_targets)
    if sales_targets:
        # 渠道拆分：从 2028 线上/线下全年列（存于各渠道行 12 月槽）读取
        on_targets = _row_year_targets(inputs, QTY_ONLINE, periods)
        off_targets = _row_year_targets(inputs, QTY_OFFLINE, periods)
        hist_on = {p: inputs.get(QTY_ONLINE, {}).get(p, Decimal(0)) for p in periods}
        hist_off = {p: inputs.get(QTY_OFFLINE, {}).get(p, Decimal(0)) for p in periods}
        w_on = seasonal_weights(periods, hist_on)
        w_off = seasonal_weights(periods, hist_off)
        for year, annual in sales_targets.items():
            annual_on = on_targets.get(year, annual)   # 缺渠道拆分时全部算线上
            annual_off = off_targets.get(year, Decimal(0))
            parts_on = monthlyize(annual_on, w_on[_shape_year(w_on, target_years, year)])
            parts_off = monthlyize(annual_off, w_off[_shape_year(w_off, target_years, year)])
            months = [j for j, pp in enumerate(periods) if int(pp[:4]) == year]
            for j, (a, b) in enumerate(zip(parts_on, parts_off)):
                qty_online[months[j]] = a
                qty_offline[months[j]] = b

    # 情景销量系数：对最终月度销量整体缩放（含 2028 目标已月度化的结果）。
    # 必须在此处缩放而非改输入——否则给 2028 各月写 qty 会被 _row_year_targets
    # 判为「已有月度输入」，年度目标失效导致线下归零。
    p = params
    if p.qty_scale != 1:
        qty_online = [q * p.qty_scale for q in qty_online]
        qty_offline = [q * p.qty_scale for q in qty_offline]

    # ---------- 2. 销售/收入 ----------
    # 单位：qty=万台，价格/单位收入=元/台 → 金额=万元（无需缩放）
    sale_online = [q * p.price_online for q in qty_online]
    sale_offline = [q * p.price_offline for q in qty_offline]
    qty_total = [a + b for a, b in zip(qty_online, qty_offline)]
    # 配件收入跟随销售渠道（回款也按渠道）
    acc_online = [q * p.acc_ratio * p.acc_revenue_per_unit for q in qty_online]
    acc_offline = [q * p.acc_ratio * p.acc_revenue_per_unit for q in qty_offline]
    sale_acc = [a + b for a, b in zip(acc_online, acc_offline)]
    # 订阅：累计装机口径，随新增装机逐月累积（装机初值=现金流量表数值 0）
    # 单价 200 元为每台每年，月度订阅收入需 ÷12；2028 亦持续累积，不用年度目标覆盖
    # （旧逻辑用导入的年度订阅目标覆盖 2028 全年 → 断崖且不计新增用户，已废弃）
    install = [p.install_base_initial]
    for i in range(n):
        install.append(install[-1] + qty_total[i])
    # ÷12 产生循环小数，按 Decimal(20,8) 约定量化，避免尾数泄漏到现金合计
    _q8 = Decimal("0.00000001")
    sale_sub = [(install[i + 1] * p.sub_ratio * p.sub_revenue_per_unit / 12).quantize(_q8)
                for i in range(n)]
    sale_total = [a + b + c + d for a, b, c, d in
                  zip(sale_online, sale_offline, sale_acc, sale_sub)]

    # ---------- 3. 采购付款（N+M 账期） ----------
    buy_main = [q * p.cost_main for q in qty_total]
    buy_acc = [q * p.cost_accessory for q in qty_total]
    lag = p.purchase_lag
    pur_main = [zero] * n
    pur_acc = [zero] * n
    for i in range(n):
        if i + lag < n:
            pur_main[i + lag] += buy_main[i]
            pur_acc[i + lag] += buy_acc[i]
    pur_total = [a + b for a, b in zip(pur_main, pur_acc)]

    # ---------- 4. 回款（配件回款跟随销售渠道，与硬件同权重卷积） ----------
    col_online = [zero] * n
    col_offline = [zero] * n
    col_sub = [zero] * n
    for i in range(n):
        w = p.collect_weight_online
        for k, weight in enumerate(w):
            if i + k < n and weight != 0:
                col_online[i + k] += (sale_online[i] + acc_online[i]) * weight
        w = p.collect_weight_offline
        for k, weight in enumerate(w):
            if i + k < n and weight != 0:
                col_offline[i + k] += (sale_offline[i] + acc_offline[i]) * weight
        w = p.collect_weight_sub
        for k, weight in enumerate(w):
            if i + k < n and weight != 0:
                col_sub[i + k] += sale_sub[i] * weight
    col_total = [a + b + c for a, b, c in zip(col_online, col_offline, col_sub)]

    # ---------- 5. 费用（直接输入；目标年全年值 → 按月摊开） ----------
    exp_by_row = {row: [inp(row, i) for i in range(n)] for row in EXPENSE_ROWS}
    if p.auto_marketing:
        # 营销自动测算：佣金/渠道推广=当期线下销售额×费率；线上推广=当期线上销售额×分年费率
        online_rate = {2026: p.online_promo_rate_2026, 2027: p.online_promo_rate_2027,
                       2028: p.online_promo_rate_2028}
        for i in range(n):
            yr = int(periods[i][:4])
            exp_by_row["exp.channel_commission"][i] = sale_offline[i] * p.channel_commission_rate
            exp_by_row["exp.channel_promo"][i] = sale_offline[i] * p.channel_promo_rate
            exp_by_row["exp.online_promo"][i] = sale_online[i] * online_rate.get(yr, p.online_promo_rate_2028)
    else:
        # 渠道佣金默认 = 上月线下销售（含配件）×费率（Excel 口径：N+1；可覆盖）
        for i in range(n):
            if inputs.get("exp.channel_commission", {}).get(periods[i]) is None:
                exp_by_row["exp.channel_commission"][i] = (
                    (sale_offline[i - 1] + acc_offline[i - 1]) * p.channel_commission_rate
                    if i >= 1 else zero
                )
    # 费用年度目标（2028 全年值存于该年 12 月）：按季节曲线摊到全年
    for row in EXPENSE_ROWS:
        if p.auto_marketing and row in AUTO_MKT_ROWS:
            continue  # 自动测算行已逐月算出，不受年度目标覆盖
        annual_by_year = _row_year_targets(inputs, row, periods)
        if annual_by_year:
            hist = {pp: exp_by_row[row][j] for j, pp in enumerate(periods)}
            w = seasonal_weights(periods, hist)
            _monthlyize_row(exp_by_row[row], periods, w, target_years, annual_by_year)
    exp_total = [sum(exp_by_row[row][i] for row in EXPENSE_ROWS) for i in range(n)]

    # ---------- 6. 现金滚动 ----------
    cash_open = [zero] * n
    cash_close = [zero] * n
    financing = [inp(CASH_FINANCING, i) for i in range(n)]  # 投融资注入（不摊分）
    cash_exp = [exp_total[i] + pur_total[i] for i in range(n)]
    cash_gap = [col_total[i] - cash_exp[i] for i in range(n)]
    cash_open[0] = inp(CASH_OPEN, 0)
    for i in range(n):
        cash_close[i] = cash_open[i] + cash_gap[i] + financing[i]
        if i + 1 < n:
            cash_open[i + 1] = cash_close[i]

    # ---------- 7. 组装网格 ----------
    rows: dict[str, list] = {
        QTY_TOTAL: qty_total,
        SALE_ONLINE: sale_online, SALE_OFFLINE: sale_offline,
        SALE_ACC: sale_acc, SALE_SUB: sale_sub, SALE_TOTAL: sale_total,
        PURCHASE_MAIN: pur_main, PURCHASE_ACC: pur_acc, PURCHASE_TOTAL: pur_total,
        COLLECT_ONLINE: col_online, COLLECT_OFFLINE: col_offline,
        COLLECT_SUB: col_sub, COLLECT_TOTAL: col_total,
        CASH_OPEN: cash_open, CASH_IN: col_total, CASH_EXP: cash_exp,
        CASH_GAP: cash_gap,
        CASH_CLOSE: cash_close, EXPENSE_TOTAL: exp_total,
    }
    # 输入行直接透传（目标年已被月度化 → 用计算后的行值覆盖网格）
    for row in INPUT_ROWS:
        rows[row] = [inp(row, i) for i in range(n)]
    for row, vals in ((QTY_ONLINE, qty_online), (QTY_OFFLINE, qty_offline)):
        rows[row] = vals
    for row in EXPENSE_ROWS:
        rows[row] = exp_by_row[row]

    # 覆盖（用户手动改的值优先；不改 source 语义，仍标 override）
    grid = {}
    for row in INPUT_ROWS:
        grid[row] = {}
        for i, p_ in enumerate(periods):
            grid[row][p_] = {"value": rows[row][i], "source": "input"}
    for row in COMPUTED_ROWS:
        grid[row] = {}
        for i, p_ in enumerate(periods):
            grid[row][p_] = {"value": rows[row][i], "source": "engine"}
    for row, per in overrides.items():
        for p_, v in per.items():
            if p_ in periods:
                grid.setdefault(row, {})[p_] = {"value": v, "source": "override"}
    return grid
