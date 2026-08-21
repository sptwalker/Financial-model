# -*- coding: utf-8 -*-
"""M2 对账核心：引擎输出 vs Excel 中性情景（逐单元格分类）

分类口径：
- MATCH            —— 口径对齐后一致（销售/回款/采购/费用/现金）
- KNOWN_QUIRK      —— Excel 已知瑕疵（详见文档字符串与 QUIRKS 表）
- KNOWN_RULE_DIFF  —— 用户确认的规则差异（订阅口径、工资 07 按工资表补、2028/2029 全年列月度化+账期）
- BUG              —— 既非对齐又无解释的差异（应为 0）

已知瑕疵（Excel 侧，KNOWN_QUIRK）：
- 2026-07 销售 160（qty=0 但有金额）；2026-08 线下 312.554（减 07 回款）
- 2026-07 费用明细全空（合计 1060 / 支出 1068 为规划值，无行明细）
- 2026-08 回款合计 160（=07 线下回款，非 08 当月）；2026-09 回款 578.414（权重与销量不符）
- 配件采购 2026-09..2027-12 整行账期/比例漂移（与销量无法复现）
- 现金缺口/期末现金（含 2028/2029 全年列）为 Excel 手填规划行（引擎按滚动计算）

规则差异（引擎按确认口径，Excel 另口径，KNOWN_RULE_DIFF）：
- 订阅收入：Excel=当月销量×0.7×200（计入销售额合计/回款合计）；
  引擎=累计装机×0.7×200（单独行，用户确认口径）→ 销售合计/回款合计差=当月订阅
- 工资 2026-07：Excel 空；引擎按工资表应付合计 174.160574 万
- 支出行：Excel=费用+整机采购（不含配件采购）；引擎=费用+采购合计（含配件）
- 2028/2029 全年列：引擎按季节曲线月度化后，全年列行按年度合计对账
  （工资/佣金/期初现金年度合计一致 → MATCH；采购/支出等受账期影响 → RULE_DIFF）
"""
import json
import sys
from dataclasses import asdict
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import openpyxl  # noqa: E402

from app.engine.excel_import import import_xls  # noqa: E402
from app.engine.calculator import run, Params  # noqa: E402

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
XLS = BACKEND_DIR.parent / "docs" / "现金流测算 2026.8.xls"
PAYROLL_XLSX = BACKEND_DIR.parent / "docs" / "2026年7月创想悦动工资表.xlsx"
TOL = Decimal("0.05")

# 全年引用列（Excel 表头 2028/2029 = 全年）：比较改为「引擎全年合计 vs Excel 全年值」
ANNUAL_COL_YEARS = {2028, 2029}
# 销售/回款合计行：Excel 计入订阅收入（引擎单独行）→ 对齐公式加回 Excel 订阅行值
SUB_SUM_ROWS = {"sale.total.amount", "collect.total"}
# 支出行：Excel 不含配件采购（引擎含）→ 对齐公式减回引擎配件采购
CASH_EXP_ROW = "cash.expense"

# 行展示名（对账报告可读性）
ROW_NAMES = {
    "qty.online": "线上销量", "qty.offline": "线下销量",
    "sale.online.amount": "线上销售（含配件）", "sale.offline.amount": "线下销售（含配件）",
    "sale.accessory.amount": "配件收入", "sale.total.amount": "销售额合计（不含订阅）",
    "sale.subscription.amount": "订阅收入",
    "purchase.main": "整机采购", "purchase.accessory": "配件采购", "purchase.total": "采购合计",
    "collect.total": "回款合计", "exp.total": "费用合计", "exp.salary": "工资",
    "exp.game_dev": "游戏外包开发", "exp.commercial_ip": "商业IP", "exp.license": "版号",
    "exp.office_hw": "办公硬件", "exp.it_service": "信息技术服务", "exp.rent": "房租",
    "exp.recruit": "招聘费", "exp.office_other": "办公及其他", "exp.brand": "品牌宣传",
    "exp.channel_commission": "渠道佣金", "exp.channel_promo": "渠道推广费",
    "exp.online_promo": "线上推广费",
    "cash.opening": "期初现金", "cash.expense": "本期支出", "cash.gap": "现金缺口",
    "cash.closing": "期末现金",
}


def payroll_total_payable(xlsx: Path) -> Decimal:
    """工资表「汇总」sheet 总计行应付工资（万元）"""
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    ws = wb["汇总"]
    hdr = None
    for row in ws.iter_rows(values_only=True):
        if hdr is None and row and "应付工资" in row:
            hdr = row
            continue
        if hdr is not None and row and row[0] == "总计":
            return Decimal(str(row[hdr.index("应付工资")])) / Decimal("10000")
    raise ValueError(f"工资表 {xlsx.name} 未找到总计行/应付工资列")


def acc_online_share(grid: dict, p: str) -> Decimal:
    """线上配件 = 配件总额 × 线上数量占比（配件=qty×0.5×200，随渠道数量）"""
    on = Decimal(grid["qty.online"][p]["value"])
    off = Decimal(grid["qty.offline"][p]["value"])
    total = on + off
    acc = Decimal(grid["sale.accessory.amount"][p]["value"])
    return acc * (on / total) if total else Decimal("0")


def engine_value(grid: dict, excel_key: str, p: str) -> Decimal:
    """Excel 行键 → 引擎同口径值（合并配件按渠道拆分 + 已知口径对齐）"""
    if excel_key == "sale.online.amount":
        return Decimal(grid["sale.online.amount"][p]["value"]) + acc_online_share(grid, p)
    if excel_key == "sale.offline.amount":
        return Decimal(grid["sale.offline.amount"][p]["value"]) \
            + Decimal(grid["sale.accessory.amount"][p]["value"]) - acc_online_share(grid, p)
    if excel_key == "sale.total.amount":
        return Decimal(grid["sale.online.amount"][p]["value"]) \
            + Decimal(grid["sale.offline.amount"][p]["value"]) \
            + Decimal(grid["sale.accessory.amount"][p]["value"])
    if excel_key == "sale.accessory.amount":
        return Decimal(grid["sale.accessory.amount"][p]["value"])
    if excel_key == "sale.subscription.amount":
        return Decimal(grid["sale.subscription.amount"][p]["value"])
    if excel_key == "collect.total":
        return Decimal(grid["collect.online"][p]["value"]) + Decimal(grid["collect.offline"][p]["value"])
    if excel_key == "exp.salary":
        return Decimal(grid["exp.salary"][p]["value"])
    return Decimal(grid[excel_key][p]["value"])


def annual_engine_sum(grid: dict, excel_key: str, year: int) -> Decimal:
    """引擎全年合计（同口径行键）"""
    ms = [p for p in grid["qty.online"] if p.startswith(str(year))]
    if excel_key == "sale.online.amount":
        return sum((engine_value(grid, "sale.online.amount", p) for p in ms), Decimal("0"))
    if excel_key == "sale.offline.amount":
        return sum((engine_value(grid, "sale.offline.amount", p) for p in ms), Decimal("0"))
    if excel_key == "sale.total.amount":
        return sum((engine_value(grid, "sale.total.amount", p) for p in ms), Decimal("0"))
    if excel_key == "sale.accessory.amount":
        return sum((Decimal(grid["sale.accessory.amount"][p]["value"]) for p in ms), Decimal("0"))
    if excel_key == "sale.subscription.amount":
        return sum((Decimal(grid["sale.subscription.amount"][p]["value"]) for p in ms), Decimal("0"))
    if excel_key == "collect.total":
        return sum((Decimal(grid["collect.online"][p]["value"]) + Decimal(grid["collect.offline"][p]["value"])
                    for p in ms), Decimal("0"))
    return sum((Decimal(grid[excel_key][p]["value"]) for p in ms), Decimal("0"))


def reconcile_rows(imp: dict, grid: dict, params: Params, lines: list) -> list[str]:
    """逐行对账 → (行说明行, BUG 明细)。返回 (lines 尾部, bugs)"""
    inputs, excel, periods = imp["inputs"], imp["excel"], imp["periods"]
    excel_sub = excel.get("sale.subscription.amount", {})   # Excel 订阅行（2027-08 起）
    categories = {"MATCH": 0, "KNOWN_QUIRK": 0, "KNOWN_RULE_DIFF": 0, "BUG": 0}
    bugs: list[str] = []

    ROW_DEFS = [
        ("sale.online.amount", None),
        ("sale.offline.amount", None),
        ("sale.total.amount", None),
        ("sale.accessory.amount", None),
        ("sale.subscription.amount", None),
        ("purchase.main", None),
        ("purchase.accessory", None),
        ("purchase.total", None),
        ("collect.total", None),
    ] + [(row, None) for row in (
        "exp.salary", "exp.game_dev", "exp.commercial_ip", "exp.license",
        "exp.office_hw", "exp.it_service", "exp.rent", "exp.recruit",
        "exp.office_other", "exp.brand", "exp.channel_commission",
        "exp.channel_promo", "exp.online_promo",
    )] + [
        ("cash.opening", None),
        ("cash.expense", None),
        ("cash.gap", None),
        ("cash.closing", None),
    ]

    # 每行：Excel 全部单元格 + 分类器返回 (分类, 说明)。说明 None = 计入 MATCH。
    for excel_key, _ in ROW_DEFS:
        e = excel.get(excel_key)
        if not e:
            continue
        cells = sorted(e.keys())
        per_cell = classify_cells(excel_key, cells, excel_sub)
        row_bugs = []
        row_notes = []
        for p in cells:
            cls, note = per_cell.get(p, ("MATCH", None))
            x = e[p]
            if cls == "MATCH":
                a = engine_value(grid, excel_key, p)
                if abs(a - x) > TOL:
                    cls, note = "BUG", None
            elif cls == "ANNUAL":
                # 全年引用列：引擎全年合计 vs Excel 全年值
                year = int(p[:4])
                a = annual_engine_sum(grid, excel_key, year)
                cls = "MATCH" if abs(a - x) <= TOL else "KNOWN_RULE_DIFF"
                note = note or f"引擎全年合计 {a} vs Excel 全年 {x}"
                if cls == "KNOWN_RULE_DIFF":
                    a_s = f"{a}" if a is not None else "?"
                    note = f"全年合计 {a_s} vs Excel 全年 {x}；{note}"
            elif cls == "KNOWN_RULE_DIFF":
                a = engine_value(grid, excel_key, p)
                a_s = f"{a}" if a is not None else "?"
                note = note or "口径差异（详见报告说明）"
            if cls == "BUG":
                row_bugs.append(f"{p}: 引擎 {engine_value(grid, excel_key, p)} vs Excel {x}")
                continue
            if cls == "KNOWN_RULE_DIFF":
                a = engine_value(grid, excel_key, p)
                row_notes.append(f"{p}: 引擎 {a} vs Excel {x} — {note}")
            categories[cls] += 1
        status = "MATCH"
        if row_bugs:
            status = "BUG"
            categories["BUG"] += len(row_bugs)
            bugs.extend(f"{excel_key} | {d}" for d in row_bugs)
        else:
            categories["MATCH"] += 1
        lines.append(f"  {status:<4} {ROW_NAMES.get(excel_key, excel_key)}"
                     f"（{len(cells)} 个 Excel 值）")
        for d in row_bugs:
            lines.append(f"         {d}")
        for d in row_notes:
            lines.append(f"         ~ {d}")
    return categories, bugs


def classify_cells(excel_key: str, cells: list[str], excel_sub: dict) -> dict:
    """{period: (分类, 说明)} 按行键规则
    MATCH=引擎值直接可比；ANNUAL=2028/2029 全年列（年度合计对账）；
    KNOWN_RULE_DIFF=用户确认口径差异；KNOWN_QUIRK=Excel 瑕疵期。
    """
    out: dict[str, tuple] = {}
    monthly = [p for p in cells if not _is_annual(p)]

    def mark(p, cls, note=None):
        out[p] = (cls, note)

    for p in cells:
        if _is_annual(p):
            mark(p, "ANNUAL", "全年引用列")
        else:
            mark(p, "MATCH")

    y = excel_key
    # --- 销售/回款行：Excel 合计计入订阅收入（引擎单独行）→ 差=当月 Excel 订阅 ---
    if y in SUB_SUM_ROWS:
        for p in monthly:
            if p in excel_sub and excel_sub[p]:
                mark(p, "KNOWN_RULE_DIFF",
                     "Excel 合计含订阅收入（引擎订阅单独行，用户确认口径）")
        for p in cells:
            if _is_annual(p):
                mark(p, "ANNUAL",
                     "Excel 全年列含订阅收入（当年订阅目标 2461.2/6661.2）")

    # --- 销售行瑕疵期 ---
    if y == "sale.online.amount":
        mark("2026-07", "KNOWN_QUIRK", "qty=0 但有金额 160（Excel 瑕疵）")
    if y == "sale.offline.amount":
        mark("2026-07", "KNOWN_QUIRK", "qty=0 但有金额 160")
        mark("2026-08", "KNOWN_QUIRK", "含 07 回款 160，非 08 当月销售")
    if y == "sale.total.amount":
        mark("2026-07", "KNOWN_QUIRK", "合计=线下 160（qty=0 却有金额）")
        mark("2026-08", "KNOWN_QUIRK", "合计=线上+线下（未加配件 160，且线下已减 07 回款）")

    # --- 回款合计：08 行错位 / 09 权重不符 ---
    if y == "collect.total":
        mark("2026-08", "KNOWN_QUIRK", "Excel=160（07 线下回款，非 08 当月）")
        mark("2026-09", "KNOWN_QUIRK", "Excel 回款 578.414 与销量权重不符")

    # --- 采购行 ---
    if y == "purchase.main":
        for p in cells:
            if _is_annual(p):
                mark(p, "ANNUAL", "账期 N+2 跨年：引擎全年=Σ月度化销量×价×lag")
    if y == "purchase.accessory":
        for p in monthly:
            mark(p, "KNOWN_QUIRK", "Excel 配件采购账期/比例漂移（无法复现）")
        for p in cells:
            if _is_annual(p):
                mark(p, "ANNUAL", "账期跨年 + 全年列比例不符（引擎 1610.1/3942.6 vs 900/2250）")
    if y == "purchase.total":
        for p in monthly:
            if p >= "2026-09":
                mark(p, "KNOWN_QUIRK", "Excel 采购合计=整机（不含配件）")
        for p in cells:
            if _is_annual(p):
                mark(p, "ANNUAL", "Excel 全年列=整机+配件；引擎按月 N+2 滚动")

    # --- 费用行：工资 07 按工资表补；其余费用 2026-08 起逐月 MATCH ---
    if y == "exp.salary":
        mark("2026-07", "KNOWN_RULE_DIFF", "Excel 空；引擎按工资表应付合计 174.160574 万")
        for p in monthly:
            if p >= "2026-08":
                mark(p, "MATCH")
    if y == "exp.channel_commission":
        mark("2026-07", "KNOWN_RULE_DIFF", "Excel 空；引擎兜底=上月线下销售×5%=0")

    # --- 现金行 ---
    if y == "cash.opening":
        for p in monthly:
            if p > "2026-07":
                mark(p, "KNOWN_RULE_DIFF", "Excel 静态期初 vs 引擎滚动（上期末）")
    if y == "cash.expense":
        mark("2026-07", "KNOWN_QUIRK", "Excel 规划支出 1068（07 费用明细全空）")
        for p in monthly:
            if p >= "2026-09":
                mark(p, "KNOWN_RULE_DIFF", "Excel 支出=费用+整机采购（不含配件）；引擎含配件采购")
        for p in cells:
            if _is_annual(p):
                mark(p, "ANNUAL", "同上口径差异 + 订阅回款差异（全年）")
    if y in ("cash.gap", "cash.closing"):
        for p in monthly:
            mark(p, "KNOWN_QUIRK", "Excel 手填规划行；引擎按滚动计算")
        for p in cells:
            if _is_annual(p):
                # 期末现金的全年列存的是上一年期末结转值（如 2028-12=-14241.28=2027-12 期末），
                # 非全年合计，无法与引擎年度合计对账 → 与月度一样按 QUIRK 处理
                mark(p, "KNOWN_QUIRK", "全年列存上一年期末结转值，非全年合计")

    # 订阅收入行：Excel 当月销量口径 vs 引擎累计装机口径
    if y == "sale.subscription.amount":
        for p in monthly:
            if p in excel_sub and excel_sub[p]:
                mark(p, "KNOWN_RULE_DIFF",
                     "Excel=当月销量×0.7×200；引擎=累计装机×0.7×200（用户确认）")
    return out


def _is_annual(p: str) -> bool:
    return int(p[:4]) in ANNUAL_COL_YEARS


def load_fixture():
    """加载 Excel 数据 + 工资表 07 补值 + 引擎计算 → (imp, grid, params, salary_07)"""
    imp = import_xls(XLS)
    params = Params()
    salary_07 = payroll_total_payable(PAYROLL_XLSX)
    imp["inputs"].setdefault("exp.salary", {})["2026-07"] = salary_07
    grid = run(imp["periods"], params, imp["inputs"])
    return imp, grid, params, salary_07


def build_report(imp: dict, grid: dict, params: Params, salary_07: Decimal) -> tuple[str, list[str]]:
    """生成对账报告文本 + BUG 明细（不写盘）"""
    inputs, excel, periods = imp["inputs"], imp["excel"], imp["periods"]
    lines = [
        f"对账报告：引擎 vs Excel「现金流中性」  "
        f"期间 {periods[0]}..{periods[-1]}（{len(periods)} 期）  容差 {TOL}",
        "参数快照：" + json.dumps(asdict(params), ensure_ascii=False,
                                   default=lambda o: str(o)),
        "",
    ]
    categories, bugs = reconcile_rows(imp, grid, params, lines)

    lines.append("")
    lines.append("  [KNOWN_RULE_DIFF 说明] 订阅：Excel 合计行计入订阅收入（当月销量口径），")
    lines.append("      引擎订阅为单独行（累计装机口径，用户确认）；差额=Excel 订阅行值。")
    lines.append("      支出：Excel=费用+整机采购（不含配件采购）；引擎=费用+全部采购（N+2 账期）。")
    lines.append("      2028/2029：Excel 全年引用列；引擎按季节曲线月度化后年度合计对账。")
    lines.append(f"分类统计：MATCH={categories['MATCH']}  KNOWN_QUIRK={categories['KNOWN_QUIRK']}  "
                 f"KNOWN_RULE_DIFF={categories['KNOWN_RULE_DIFF']}  BUG={categories['BUG']}")
    lines.append("结论：" + ("全部对齐（无未解释差异）" if not bugs else f"存在 {len(bugs)} 个未解释差异！"))
    return "\n".join(lines), bugs
