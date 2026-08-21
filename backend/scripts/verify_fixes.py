# -*- coding: utf-8 -*-
"""M2 关卡验证：引擎输出 vs Excel 中性情景

对账口径（已从 Excel 拆解确认）：
- Excel 线上/线下销售行 = 硬件销售 + 配件收入（引擎侧合并比较）
- Excel 销售额合计 = 线上+线下，不含订阅（订阅为独立 sheet，按用户确认口径=累计装机×0.7×200）
- 渠道佣金：Excel 08 起逐月有值 → 全部导入直通（引擎兜底=上月线下含配件×5% 仅用于空月）
- 采购付款：引擎 N+2；Excel 09/10 配件采购为已知瑕疵（N+1 且数值不匹配销量）
- 配件采购行 Excel 口径自相矛盾（详见 quirks），整行列为已知瑕疵，引擎按固定 N+2×0.5×60 计算
- 2026-08 线下/合计 312.554 / 502.454 与引擎一致（07 已发生月不进入引擎轴）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.excel_import import import_xls
from app.engine.calculator import run, Params

XLS = Path(__file__).resolve().parent.parent.parent / "docs" / "现金流测算 2026.8.xls"


def main():
    imp = import_xls(XLS)
    inputs, excel, periods = imp["inputs"], imp["excel"], imp["periods"]
    grid = run(periods, Params(), inputs)

    def gv(row, p):
        return float(grid[row][p]["value"])

    def ev(row, p):
        v = excel.get(row, {}).get(p)
        return None if v is None else float(v)

    def acc_online_share(p):
        """配件按渠道拆分：线上配件 = 总额 × 线上数量占比（配件=qty×0.5×200，随渠道数量）"""
        on, off = gv("qty.online", p), gv("qty.offline", p)
        total = on + off
        return gv("sale.accessory.amount", p) * (on / total if total else 0)

    ok, bad = [], []
    def check(name, actual, expect, tol=0.05):
        if abs(actual - expect) <= tol:
            ok.append(name)
        else:
            bad.append(f"{name}: 引擎 {actual:.4f} ≠ 期望 {expect:.4f}")

    # --- 导入器关键值 ---
    print("== 导入器 ==")
    assert inputs.get("qty.online", {}).get("2026-07") is None, "qty.online 07 应为空"
    assert str(inputs.get("qty.online", {}).get("2026-09")) == "0.08"
    assert str(inputs.get("qty.offline", {}).get("2026-09")) == "0.4"
    assert str(inputs["target.sales"].get("2028-12")) == "30.0"
    assert str(inputs["target.sales"].get("2029-12")) == "75.0"
    assert str(inputs["target.subscription"].get("2028-12")) == "2461.2"
    assert str(inputs["target.subscription"].get("2029-12")) == "6661.2"
    assert excel.get("qty.online", {}).get("2026-07") is None, "excel qty 不应被价格覆盖"
    print("  qty 行/年度目标/价格不覆盖: OK")

    # --- 2026-09 销售（Excel 合计 781.992 = 151.92 + 630.072） ---
    print("== 2026-09 销售 ==")
    check("sale.online 09（硬件）", gv("sale.online.amount", "2026-09"), 143.92)
    check("sale.offline 09（硬件）", gv("sale.offline.amount", "2026-09"), 590.072)
    check("sale.accessory 09", gv("sale.accessory.amount", "2026-09"), 48)
    # 线上行/线下行 = 硬件+该渠道配件；Excel 合计 781.992 = 线上+线下（配件已含），不含订阅
    on_acc = acc_online_share("2026-09")
    check("线上行(含配件) vs Excel", gv("sale.online.amount", "2026-09") + on_acc, 151.92)
    check("线下行(含配件) vs Excel", gv("sale.offline.amount", "2026-09") + gv("sale.accessory.amount", "2026-09") - on_acc, 630.072)
    check("sale.total vs Excel 合计", gv("sale.online.amount", "2026-09") + gv("sale.offline.amount", "2026-09") + gv("sale.accessory.amount", "2026-09"), 781.992)

    # --- 2026-10 回款/采购（Excel 800.982 / 460） ---
    print("== 2026-10 回款/采购 ==")
    check("collect.total 10（硬件+配件，不含订阅）",
          gv("collect.total", "2026-10") - gv("sale.subscription.amount", "2026-10"), 800.982)
    check("purchase.main 10（N+2）", gv("purchase.main", "2026-10"), 460)

    # --- 渠道佣金：Excel 逐月有值 → 全部导入直通 ---
    print("== 渠道佣金 ==")
    for p, expect in (("2026-08", 8.0), ("2026-09", 15.6277), ("2026-10", 31.5036), ("2026-12", 47.2554)):
        check(f"comm {p}（导入直通）", gv("exp.channel_commission", p), expect)
    # 2028/2029 列是全年引用 → 引擎按季节曲线月度化（销售/订阅/费用同口径）
    check("comm 2028 合计（月度化）", sum(gv("exp.channel_commission", p) for p in periods if p.startswith("2028")), 1575.18)
    check("comm 2029 合计（月度化）", sum(gv("exp.channel_commission", p) for p in periods if p.startswith("2029")), 3150.36)

    # --- 2028/2029 年度目标（Excel 精确值） ---
    print("== 2028/2029 年度 ==")
    for year, expect_sale, expect_sub, expect_qty, expect_exp in (
        ("2028", 52954.8, 2461.2, 30, 22960.18),
        ("2029", 136133.4, 6661.2, 75, 42973.86),
    ):
        ms = [p for p in periods if p.startswith(year)]
        sale = sum(gv("sale.total.amount", p) for p in ms)
        sub = sum(gv("sale.subscription.amount", p) for p in ms)
        qty = sum(gv("qty.online", p) + gv("qty.offline", p) for p in ms)
        exp = sum(gv("exp.total", p) for p in ms)
        check(f"{year} 销售合计", sale, expect_sale)
        check(f"{year} 订阅合计", sub, expect_sub)
        check(f"{year} 销量合计", qty, expect_qty)
        check(f"{year} 费用合计", exp, expect_exp)

    # --- 逐月对账（口径对齐后；排除已知瑕疵期） ---
    print("== 逐月对账（口径对齐） ==")
    quirks = {
        "sale.online.amount": {"2028-12", "2029-12"},            # 全年引用列（Excel 全年值 18990/66465）
        "sale.offline.amount": {"2026-08",                      # Excel 08 不含 07 回款 160
                                "2028-12", "2029-12"},          # 全年引用列（Excel 全年值 31503.6/63007.2）
        "sale.total.amount": {"2026-08",                          # 同上；2027-08 起 Excel 合计含订阅（用户确认口径）
                              "2027-08", "2027-09", "2027-10",
                              "2027-11", "2027-12", "2028-12", "2029-12"},
        "purchase.main": {"2028-12", "2029-12"},            # 全年引用列 vs 引擎月度
        "purchase.accessory": {"2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02",
                               "2027-03", "2027-04", "2027-05", "2027-06",
                               "2027-07", "2027-08", "2027-09", "2027-10",
                               "2027-11", "2027-12", "2028-12", "2029-12"},
        # 配件采购整行：Excel 口径自相矛盾（09 起 N+1、2027 起比例漂移、全年列 900/2250 与销量不符），引擎固定 N+2×0.5×60
        "exp.channel_commission": {"2028-12", "2029-12"},
    }
    # (显示名, Excel 键, 引擎行键列表)；线上/线下行=硬件+该渠道配件；合计行=线上+线下+配件（Excel 不含订阅）
    pairs = [
        ("线上销售（含配件）", "sale.online.amount",
         ["sale.online.amount", "sale.accessory.amount"], "online"),
        ("线下销售（含配件）", "sale.offline.amount",
         ["sale.offline.amount", "sale.accessory.amount"], "offline"),
        ("销售额合计", "sale.total.amount",
         ["sale.online.amount", "sale.offline.amount", "sale.accessory.amount"], "total"),
        ("整机采购", "purchase.main", ["purchase.main"], None),
        ("配件采购", "purchase.accessory", ["purchase.accessory"], None),
        ("渠道佣金", "exp.channel_commission", ["exp.channel_commission"], None),
    ]
    for name, xkey, gkeys, mode in pairs:
        diff = []
        for p in periods:
            if p in quirks.get(xkey, set()):
                continue
            e = ev(xkey, p)
            if e is None:
                continue
            if mode == "online":
                a = gv(gkeys[0], p) + acc_online_share(p)
            elif mode == "offline":
                a = gv(gkeys[0], p) + gv(gkeys[1], p) - acc_online_share(p)
            elif mode == "total":
                a = sum(gv(k, p) for k in gkeys)
            else:
                a = gv(gkeys[0], p)
            if abs(a - e) > 0.05:
                diff.append(f"{p}(引擎 {a:.2f} vs {e:.2f})")
        status = "OK " if not diff else "DIFF"
        print(f"  {status} {name}: {diff[:4] if diff else '无差异'}")

    print()
    print(f"通过 {len(ok)} 项: {ok}")
    if bad:
        print("失败:")
        for b in bad:
            print("  ", b)
        sys.exit(1)
    print("全部通过")


if __name__ == "__main__":
    main()
