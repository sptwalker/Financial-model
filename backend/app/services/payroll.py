# -*- coding: utf-8 -*-
"""工资表读取：从脱敏夹具取「应付工资合计」等汇总结论

为什么单独成模块：真实的 `2026年7月创想悦动工资表.xlsx` 含员工姓名/身份证/逐人
明细，属于个人隐私数据，已移出仓库。种子脚本与对账模块原本各写一份解析逻辑、直接
读该文件，导致仓库与测试基线都绑定在隐私文件上。这里统一收口为：

- 只读**脱敏夹具** `backend/fixtures/payroll_2026-07.xlsx`（仅含汇总总计行）
- 只对外暴露汇总口径（应付工资 / 社保 / 公积金），不提供任何逐人接口
- 解析逻辑单点维护，`scripts/build_payroll_fixture.py` 可重新生成夹具

口径（元 → 万元由调用方换算，本模块返回**元**）：
- 应付工资：汇总表总计行「应付工资」，2026-07 = 1,741,605.74 元
- 社保合计：202607 社保申报明细「合计」行 = 523,749.64 元（后续接费用时使用）
- 公积金合计：202607 公积金缴存清单 = 131,083.10 元（后续接费用时使用）
"""
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent   # backend/
FIXTURE = BACKEND_DIR / "fixtures" / "payroll_2026-07.xlsx"

# 202607 社保/公积金合计（元）：这两个数字来自已移出仓库的明细表，
# 作为脱敏结论保留在此，避免下游再依赖隐私文件。
SOCIAL_INSURANCE_TOTAL_YUAN = Decimal("523749.64")
HOUSING_FUND_TOTAL_YUAN = Decimal("131083.10")


class PayrollFixtureMissing(RuntimeError):
    """夹具缺失时的显式错误（避免静默返回 0 污染现金链）"""


def fixture_path() -> Path:
    return FIXTURE


def _load_total_row(xlsx: Path) -> tuple[list, list]:
    """返回 (表头, 总计行)；按列名定位，不依赖列序"""
    import openpyxl

    if not xlsx.exists():
        raise PayrollFixtureMissing(
            f"工资夹具不存在：{xlsx}\n"
            "生成方式：python -m scripts.build_payroll_fixture"
        )
    ws = openpyxl.load_workbook(xlsx, data_only=True)["汇总"]
    hdr, total = None, None
    for row in ws.iter_rows(values_only=True):
        if hdr is None and row and "应付工资" in [str(x) for x in row if x is not None]:
            hdr = list(row)
            continue
        if hdr is not None and row and row[0] == "总计":
            total = list(row)
            break
    if hdr is None or total is None:
        raise ValueError(f"工资夹具 {xlsx.name} 未找到表头或总计行")
    return hdr, total


def payroll_total_payable(xlsx: Path | None = None) -> Decimal:
    """应付工资合计（**元**）。调用方按需换算为万元。"""
    hdr, total = _load_total_row(xlsx or FIXTURE)
    return Decimal(str(total[hdr.index("应付工资")]))


def payroll_headcount(xlsx: Path | None = None) -> int:
    """汇总表在册人数（仅总数，不含个人信息）"""
    hdr, total = _load_total_row(xlsx or FIXTURE)
    if "人数" not in hdr:
        raise ValueError("工资夹具缺少「人数」列")
    return int(total[hdr.index("人数")])
