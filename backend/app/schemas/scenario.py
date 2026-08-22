from datetime import datetime

from pydantic import BaseModel, Field
from typing import Optional


class ScenarioCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class ScenarioUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class ScenarioOut(BaseModel):
    id: int
    name: str
    description: Optional[str] = None
    is_active: bool
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class CellWrite(BaseModel):
    """单个单元格写入（override）"""
    value: str  # Decimal 字符串，如 "781.992"


class CellWriteBatch(BaseModel):
    """批量写入：{row_key: {period: value}}"""
    cells: dict[str, dict[str, str]]


class RecalcRequest(BaseModel):
    """重算/预览请求：改参数或覆盖输入后触发引擎重算"""
    comment: Optional[str] = None
    params: Optional[dict] = None  # 引擎参数增量（键=Params 字段名，如 price_online；不传则沿用快照）
    inputs: Optional[dict] = None  # 输入行增量 {row_key: {period: 值}}（销量/费用/融资等；不传则沿用快照）
