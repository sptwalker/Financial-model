# -*- coding: utf-8 -*-
"""Excel(.xls) 导入器：把「现金流测算 2026.8.xls」解析为引擎输入

只读主表「现金流预测（2026-2028）」，规则：
- 参数区（第 1-10 行）→ Params
- 数据区（第 12 行起，第 0 列=项目名，第 1 列=子项名）
- 列映射：2026年=7-12月（第 2-7 列）、2027年=1-12月（第 8-19 列）、2028=全年（第 20 列）
- 引擎期间轴 2026-08 起（2026-07 为已发生月，由 seed 按财务报表实际值单独锚定）
- 2028 全年值写入该年 12 月作为年度目标行（引擎按季节曲线月度化）
- 2026-08 为已发生月（引擎对账基准）；2026-09 起公式应用

返回 {
  "params": Params,
  "inputs": {row_key: {period: Decimal}},   # 引擎输入行
  "excel": {row_key: {period: Decimal}},    # Excel 原始数值（对账用，含引擎计算行）
  "quirks": [str],                          # Excel 自身瑕疵记录（对账报告用）
}
"""

from decimal import Decimal
from pathlib import Path
import xlrd

# 主表行标签 → 引擎行键（(分组标签, 子标签) → row_key）
LABEL_MAP = {
    ("现金流情况", "期初现金"): "cash.opening",
    ("现金流情况", "本期支出"): "cash.expense",
    ("现金流情况", "本期回款"): "cash.incoming",
    ("现金流情况", "本期现金缺口"): "cash.gap",
    ("现金流情况", "期末现金"): "cash.closing",
    ("销售情况", "硬件销量（万台）"): None,   # 年度目标行，单独处理
    ("销售情况", "销售额合计"): "sale.total.amount",
    ("销售情况", "线上销售"): "sale.online.amount",
    ("销售情况", "线下销售"): "sale.offline.amount",
    ("销售情况", "订阅收入"): "sale.subscription.amount",
    ("销售情况", "回款合计"): "collect.total",
    ("采购款", "采购付款合计"): "purchase.total",
    ("采购款", "整机采购"): "purchase.main",
    ("采购款", "配件采购"): "purchase.accessory",
}

# 费用行（主表顺序，标签在 "费用支出" 分组下）
EXPENSE_LABELS = [
    ("工资", "exp.salary"),
    ("游戏外包开发", "exp.game_dev"),
    ("商业IP", "exp.commercial_ip"),
    ("版号", "exp.license"),
    ("办公硬件", "exp.office_hw"),
    ("信息技术服务", "exp.it_service"),
    ("房租", "exp.rent"),
    ("招聘费", "exp.recruit"),
    ("办公及其他", "exp.office_other"),
    ("品牌宣传", "exp.brand"),
    ("渠道佣金", "exp.channel_commission"),
    ("渠道推广费", "exp.channel_promo"),
    ("线上推广费", "exp.online_promo"),
    ("人数", "exp.headcount"),
]

# 年度目标行：子标签 → 引擎行键（全年列值写入该年 12 月）
ANNUAL_LABELS = {
    "硬件销量（万台）": "target.sales",
    "订阅收入": "target.subscription",
}


class Quirk:
    """Excel 瑕疵记录（不阻塞，进入对账报告）"""
    def __init__(self, period: str, row: str, desc: str):
        self.period, self.row, self.desc = period, row, desc

    def __repr__(self):
        return f"[{self.period}] {self.row}: {self.desc}"


def _num(v):
    """单元格 → Decimal（空/文本 → None）"""
    if v is None or v == "":
        return None
    if isinstance(v, float):
        return Decimal(str(v))
    if isinstance(v, int):
        return Decimal(v)
    try:
        return Decimal(str(v).strip())
    except Exception:
        return None


def _norm(s) -> str:
    """去空白（含换行）再匹配：'现金流\n情况' → '现金流情况'"""
    return "".join(str(s or "").split())


def periods_map() -> list[str]:
    """主表列 → 期间标签：2026-07..2026-12, 2027-01..2027-12, 2028-全年

    列 2 = 2026-07（已发生月，seed 锚定报表实际值）；列 3 = 2026-08、列 4 =
    2026-09、… 列 19 = 2027-12；列 20 = 2028 全年。
    """
    return ([f"2026-{m:02d}" for m in range(7, 13)]
            + [f"2027-{m:02d}" for m in range(1, 13)]
            + ["2028-12"])


def parse_main_sheet(book: xlrd.book.Book, sheet_name: str) -> dict:
    """解析主表 → {inputs, excel, quirks, params, annual}"""
    ws = book.sheet_by_name(sheet_name)
    periods = periods_map()
    n_cols = 21  # 0=项目, 1=子项, 2..19=月度, 20=2028全年
    # 引擎期间轴从 2026-08 起 → 列标签与列数据同步右移一列（periods[1:] 与 vals[1:] 对齐）
    period_cols = periods[1:]

    inputs: dict[str, dict[str, Decimal]] = {}
    excel: dict[str, dict[str, Decimal]] = {}
    quirks: list[Quirk] = []
    annual: dict[str, dict[str, Decimal]] = {}

    group = ""          # 当前分组（组标签只在组首行出现，后续行继承）
    skip_qty = False    # 销售区「硬件售价」以下：线上/线下=价格显示行（不导入）
    for r in range(ws.nrows):
        label = _norm(ws.cell_value(r, 0))
        sub = _norm(ws.cell_value(r, 1))
        if label in ("现金流情况", "销售情况", "采购款", "费用支出"):
            group = label
            # 组首行同时携带子标签（如 销售情况|硬件销量（万台）），继续处理
        if not sub:
            continue
        vals = [_num(ws.cell_value(r, c)) for c in range(2, n_cols)]
        # 列 2 = 2026-07（已发生月，不进入引擎轴）；引擎期间从列 3 起 → 数据与标签同步右移一列
        vals = vals[1:]

        # 费用行（费用支出组下，标签在第 1 列；2028/2029 全年值 → 该年 12 月槽）
        if group == "费用支出":
            for exp_label, row_key in EXPENSE_LABELS:
                if sub == exp_label:
                    for p, v in zip(period_cols, vals):
                        if v is not None:
                            inputs.setdefault(row_key, {})[p] = v
                            excel.setdefault(row_key, {})[p] = v
                    # 全年列 → 该年 12 月（引擎按季节曲线月度化）
                    for col, year in ((20, "2028"),):
                        av = _num(ws.cell_value(r, col))
                        if av is not None:
                            inputs.setdefault(row_key, {})[f"{year}-12"] = av
                    break
            continue

        # 线上/线下行：硬件销量（万台）之后 = 销量行；硬件售价之后 = 价格显示（不导入）
        if sub == "硬件售价":
            skip_qty = True
            continue
        if sub in ("线上", "线下") and not skip_qty:
            key = "qty.online" if sub == "线上" else "qty.offline"
            for p, v in zip(period_cols, vals):
                if v is not None:
                    inputs.setdefault(key, {})[p] = v
                    excel.setdefault(key, {})[p] = v
            # 渠道年度目标：全年列 → 该年 12 月槽（引擎按季节曲线月度化）
            for col, year in ((20, "2028"),):
                av = _num(ws.cell_value(r, col))
                if av is not None:
                    inputs.setdefault(key, {})[f"{year}-12"] = av
            continue

        # 年度目标行（硬件销量/订阅收入）：全年列 → 该年 12 月槽（引擎按季节曲线月度化）
        tgt = ANNUAL_LABELS.get(sub)
        if tgt:
            for col, year in ((20, "2028"),):
                av = _num(ws.cell_value(r, col))
                if av is not None:
                    inputs.setdefault(tgt, {})[f"{year}-12"] = av
                    annual.setdefault(tgt, {})[year] = av

        key = LABEL_MAP.get((group, sub))
        if key:
            for p, v in zip(period_cols, vals):
                if v is not None:
                    excel.setdefault(key, {})[p] = v
            # 期初现金：逐月直接输入（2028 列为引用值，忽略）
            if key == "cash.opening":
                for p, v in zip(period_cols, vals):
                    if v is not None:
                        inputs.setdefault(key, {})[p] = v

    return {"inputs": inputs, "excel": excel, "quirks": quirks, "annual": annual}


def parse_params(book: xlrd.book.Book, sheet_name: str):
    """参数区（主表第 1-9 行）：标签 → 值"""
    from app.engine.calculator import Params, _d
    ws = book.sheet_by_name(sheet_name)
    kv: dict[str, Decimal] = {}
    for r in range(min(ws.nrows, 10)):
        label = _norm(ws.cell_value(r, 0))
        if label and r < 9:
            v = _num(ws.cell_value(r, 2))
            if v is not None:
                kv[label] = v
    return Params(
        price_online=_d(kv.get("线上销售价", 1799)),
        price_offline=_d(kv.get("线下销售价", 1475.18)),
        cost_main=_d(kv.get("采购价", 1150)),
        acc_ratio=_d(kv.get("配件销售占比", 0.5)),
        acc_revenue_per_unit=_d(kv.get("单台配件收入", 200)),
        sub_ratio=_d(kv.get("订阅比例", 0.7)),
        sub_revenue_per_unit=_d(kv.get("单台订阅收益", 200)),
    )


def import_xls(path: str | Path) -> dict:
    """入口：读 xls → {params, inputs, excel, quirks, periods}"""
    from app.engine.calculator import periods_between
    book = xlrd.open_workbook(str(path))
    main_name = None
    for name in book.sheet_names():
        if "现金流预测" in name or "现金" in name:
            main_name = name
            break
    if main_name is None:
        main_name = book.sheet_names()[0]
    result = parse_main_sheet(book, main_name)
    result["params"] = parse_params(book, main_name)
    result["periods"] = periods_between("2026-08", "2028-12")
    return result
