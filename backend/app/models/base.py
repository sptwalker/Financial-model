from datetime import datetime
from sqlalchemy import Column, Integer, DateTime
from app.db.base import Base


class BaseModel(Base):
    """公共字段基类（id / 创建时间 / 更新时间）"""
    __abstract__ = True

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now, nullable=False)
