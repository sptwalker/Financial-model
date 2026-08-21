from pydantic import BaseModel, Field
from typing import Optional


class ActualIn(BaseModel):
    """单条历史销量录入（upsert 键 = period+channel）"""
    period: str = Field(..., description="YYYY-MM")
    channel: str = Field(..., description="online / offline")
    units: str = Field(..., description="销量（万台，Decimal 字符串）")
    note: Optional[str] = None


class ActualBatch(BaseModel):
    actuals: list[ActualIn]


class RunRequest(BaseModel):
    """运行预测（无副作用）"""
    scenario_id: int
    method: Optional[str] = None                       # 不传=自动选档
    horizon: Optional[tuple[str, str]] = None          # (起, 止) YYYY-MM，不传用默认
    scale_targets: Optional[dict[int, str]] = None     # {年: 年度总目标（万台）}


class SeriesPoint(BaseModel):
    period: str
    online: str
    offline: str


class ApplyRequest(BaseModel):
    """接受预测 → 回填 qty + recalc（base 必填；给 lower/upper 则生成三情景）"""
    scenario_id: int
    method: str
    base: list[SeriesPoint]
    lower: Optional[list[SeriesPoint]] = None
    upper: Optional[list[SeriesPoint]] = None
    comment: Optional[str] = None
