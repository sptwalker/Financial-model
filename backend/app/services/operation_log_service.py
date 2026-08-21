from sqlalchemy.orm import Session
from typing import Optional
import json
from app.models.operation_log import OperationLog


class OperationLogService:
    """审计日志（自 feishu_project_manager 移植）"""

    @staticmethod
    def log(db: Session, *, action: str, description: str, detail: Optional[dict] = None,
            user_id: Optional[int] = None, ip: Optional[str] = None):
        try:
            entry = OperationLog(
                user_id=user_id,
                action=action[:50],
                description=description,
                detail=json.dumps(detail, ensure_ascii=False) if detail else None,
                ip=ip,
            )
            db.add(entry)
            db.commit()
        except Exception:  # noqa: BLE001 - 审计失败不阻断主流程
            db.rollback()
