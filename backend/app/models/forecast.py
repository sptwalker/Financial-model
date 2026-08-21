from sqlalchemy import Column, String, Integer, Text, UniqueConstraint
from app.models.base import BaseModel


class SalesActual(BaseModel):
    """真实历史出货（全局，情景无关）——从 2026-07 发售起点起逐月累积。

    唯一历史来源：预测服务只从本表读历史，绝不从模型网格读（网格是前瞻计划，非历史）。
    units 存万台（Decimal 字符串，与 Cell.value 同口径 → 回填 qty 行零换算）。
    """
    __tablename__ = "sales_actuals"

    period = Column(String(7), nullable=False, comment="期间 YYYY-MM")
    channel = Column(String(10), nullable=False, comment="渠道 online/offline")
    units = Column(String(40), nullable=False, comment="销量（万台，Decimal 字符串）")
    source = Column(String(20), default="manual", comment="来源：seed/manual/import")
    note = Column(String(200), comment="备注")

    __table_args__ = (UniqueConstraint("period", "channel", name="uq_sales_actual"),)


class ForecastRun(BaseModel):
    """一次已应用的预测（元数据 + 回测指标 + 三情景版本链接）。

    仅持久化"已 apply"的运行；预测序列本身不存（可从 base/lower/upper 版本 cells 重画），
    但回测分数无法从 cells 反推 → 留 metrics_json。
    """
    __tablename__ = "forecast_runs"

    scenario_id = Column(Integer, nullable=False, index=True, comment="情景ID")
    method = Column(String(20), nullable=False,
                    comment="plan_anchored/seasonal_naive/holt_winters/sarima")
    horizon_start = Column(String(7), nullable=False, comment="预测起 YYYY-MM")
    horizon_end = Column(String(7), nullable=False, comment="预测止 YYYY-MM")
    n_actual = Column(Integer, comment="有效历史月数（总量>0）")
    metrics_json = Column(Text, comment="{chosen,reason,candidates:{method:{smape,mae,rmse}}}")
    base_version = Column(Integer, comment="中性版本号")
    lower_version = Column(Integer, comment="悲观版本号（可空=未生成三情景）")
    upper_version = Column(Integer, comment="乐观版本号（可空）")
    created_by = Column(Integer, comment="创建人用户ID")
