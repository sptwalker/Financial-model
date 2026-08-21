# -*- coding: utf-8 -*-
"""三情景种子（内测演示）：情景1 运行 plan_anchored 预测 → 生成悲观/中性/乐观三版本 + ForecastRun。

看板「情景对比」卡片需要一条 ForecastRun（base/lower/upper_version）才渲染三线；
全新 seed 后 forecast_runs 为空，故此脚本补一条。band 即 CI，稀疏历史下宽而诚实。

镜像前端 Forecast.jsx onApply 的渠道拆分：yhat/lower/upper 均为总量，按 ratio_online 拆 online/offline。
幂等：已存在 ForecastRun 则跳过。用法：从 backend 目录 `python scripts/seed_three_scenarios.py`
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal  # noqa: E402
from app.models.forecast import ForecastRun  # noqa: E402
from app.services import forecast_service as fs  # noqa: E402

SCENARIO_ID = 1
HORIZON = ("2026-08", "2027-12")


def _split(series: list[dict], key: str, ratio: Decimal) -> list[dict]:
    """总量口径 series[key] → {period, online, offline}（同前端 split）"""
    return [{"period": p["period"],
             "online": p[key] * ratio,
             "offline": p[key] * (1 - ratio)}
            for p in series]


def seed() -> None:
    db = SessionLocal()
    try:
        if db.query(ForecastRun).filter(ForecastRun.scenario_id == SCENARIO_ID).first():
            print("[seed] ForecastRun 已存在，跳过")
            return
        res = fs.run_forecast(db, SCENARIO_ID, horizon=HORIZON)
        series = res["series"]
        ratio = Decimal(res["ratio_online"])
        out = fs.apply_forecast(
            db, SCENARIO_ID,
            base=_split(series, "yhat", ratio),
            lower=_split(series, "lower", ratio),
            upper=_split(series, "upper", ratio),
            method=res["method"],
            comment=f"内测种子({res['method']})",
            user_id=1,
        )
        print(f"[seed] {res['method']}（有效历史 {res['n_actual']} 月）→ "
              f"中性 v{out['base_version']} / 悲观 v{out['lower_version']} / 乐观 v{out['upper_version']}")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
