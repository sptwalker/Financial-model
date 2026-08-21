from sqlalchemy import Column, String, Text, Integer
from app.models.base import BaseModel


class OperationLog(BaseModel):
    """操作审计日志"""
    __tablename__ = "operation_logs"

    user_id = Column(Integer, index=True, comment="操作用户ID")
    action = Column(String(50), nullable=False, index=True, comment="动作：login/update_scenario/recalc/import...")
    description = Column(Text, comment="描述")
    detail = Column(Text, comment="变更详情（JSON 文本）")
    ip = Column(String(50), comment="来源IP")
