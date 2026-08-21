# -*- coding: utf-8 -*-
"""重算服务冒烟测试：v1 → v2（无参数变化应逐格一致）→ v3（改价应生效）"""
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.db.session import SessionLocal  # noqa: E402
from app.models.financial import Cell  # noqa: E402
from app.services.recalc_service import recalc  # noqa: E402


def get_cells(db, scenario_id, version_no):
    return {c.row_key + "|" + c.period: Decimal(c.value)
            for c in db.query(Cell).filter(
                Cell.scenario_id == scenario_id,
                Cell.model_version == version_no).all()}


def main():
    db = SessionLocal()
    try:
        r2 = recalc(db, 1, comment="无参数变化重算")
        print(f"v2: {r2['version_no']}, cells={r2['cell_count']}")
        v1, v2 = get_cells(db, 1, 1), get_cells(db, 1, 2)
        assert v1.keys() == v2.keys(), "版本间行×期集合不一致"
        diffs = [k for k in v1 if v1[k] != v2[k]]
        print(f"v1 vs v2 逐格差异：{len(diffs)} 个（应为 0）")
        assert not diffs, diffs[:5]

        r3 = recalc(db, 1, params_override={"price_online": "1999"},
                    comment="线上售价 1799→1999")
        print(f"v3: {r3['version_no']}, price_online={r3['params']['price_online']}")
        v3 = get_cells(db, 1, 3)
        sale_old = v2["sale.online.amount|2026-08"]
        sale_new = v3["sale.online.amount|2026-08"]
        print(f"2026-08 线上销售额 {sale_old} → {sale_new}（应为 ×1999/1799）")
        assert abs(sale_new / sale_old - Decimal("1999") / Decimal("1799")) < Decimal("1e-4")
        # 输入行与未受影响行应保持不变
        assert v3["qty.online|2026-08"] == v2["qty.online|2026-08"]
        assert v3["exp.salary|2026-08"] == v2["exp.salary|2026-08"]
        print("全部断言通过")
    finally:
        db.close()


if __name__ == "__main__":
    main()
