# -*- coding: utf-8 -*-
"""M2 对账报告入口（核心逻辑在 app/engine/reconcile.py，此处只做加载与输出）

用法：`python scripts/reconcile.py`（输出报告 + 退出码 0=全部对齐）
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.reconcile import (  # noqa: E402
    BACKEND_DIR, load_fixture, build_report,
)

OUT = BACKEND_DIR / "data" / "reconcile_report.txt"


def main():
    imp, grid, params, salary_07 = load_fixture()
    report, bugs = build_report(imp, grid, params, salary_07)
    OUT.write_text(report, encoding="utf-8")
    print(report)
    print(f"\n报告已写入 {OUT}")
    sys.exit(1 if bugs else 0)


if __name__ == "__main__":
    main()
