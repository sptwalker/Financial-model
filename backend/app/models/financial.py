from sqlalchemy import Column, String, Text, Boolean, Integer, UniqueConstraint
from app.models.base import BaseModel


class Scenario(BaseModel):
    """测算情景（中性/乐观/悲观…），每个情景保存独立的参数与结果网格"""
    __tablename__ = "scenarios"

    name = Column(String(100), nullable=False, unique=True, comment="情景名称，如 中性/乐观/悲观")
    description = Column(Text, comment="情景说明")
    is_active = Column(Boolean, default=False, nullable=False, comment="是否当前默认展示情景")
    created_by = Column(Integer, comment="创建人用户ID")


class ModelVersion(BaseModel):
    """模型版本（快照单元）：每次重算/导入生成新版本，单元格按版本留存"""
    __tablename__ = "model_versions"

    scenario_id = Column(Integer, nullable=False, index=True, comment="情景ID")
    version_no = Column(Integer, nullable=False, comment="版本号（情景内自增）")
    comment = Column(String(500), comment="版本说明")
    source = Column(String(20), default="engine", comment="来源：import/engine/manual")
    params_json = Column(Text, comment="引擎参数快照（JSON，Decimal 序列化为字符串）")
    inputs_json = Column(Text, comment="引擎输入快照（{row_key: {period: 值}}，重算基线）")
    created_by = Column(Integer, comment="创建人用户ID")

    __table_args__ = (UniqueConstraint("scenario_id", "version_no", name="uq_model_version"),)


class Cell(BaseModel):
    """测算单元格（行×期网格）：row_key 是 Excel 行标识，period 是 YYYY-MM"""
    __tablename__ = "cells"

    scenario_id = Column(Integer, nullable=False, index=True, comment="情景ID")
    model_version = Column(Integer, nullable=False, comment="模型版本号")
    period = Column(String(7), nullable=False, comment="期间 YYYY-MM")
    row_key = Column(String(50), nullable=False, comment="行标识，如 sale.online.amount")
    value = Column(String(40), nullable=False, comment="数值（Decimal 字符串，防精度丢失）")
    source = Column(String(20), default="engine", comment="来源：actual/input/engine/override")

    __table_args__ = (
        UniqueConstraint("scenario_id", "model_version", "period", "row_key", name="uq_cell"),
    )
