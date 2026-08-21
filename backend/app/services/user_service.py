from datetime import datetime
from sqlalchemy.orm import Session
from typing import Optional
from app.models.user import User, UserRole, UserStatus
from app.core.config import get_settings


class UserService:
    """用户服务（自 feishu_project_manager 移植）"""

    @staticmethod
    def get_by_id(db: Session, user_id) -> Optional[User]:
        return db.query(User).filter(User.id == user_id).first()

    @staticmethod
    def get_by_feishu_id(db: Session, feishu_user_id: str) -> Optional[User]:
        return db.query(User).filter(User.feishu_user_id == feishu_user_id).first()

    @staticmethod
    def create(db: Session, feishu_user_id: str, name: str, avatar_url: Optional[str] = None,
               department: Optional[str] = None, role: UserRole = UserRole.VIEWER,
               status: UserStatus = UserStatus.ACTIVE) -> User:
        user = User(
            feishu_user_id=feishu_user_id,
            name=name or "未命名",
            avatar_url=avatar_url,
            department=department,
            role=role,
            status=status,
            last_login_at=datetime.now(),
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return user

    @staticmethod
    def resolve_role(feishu_user_id: str) -> UserRole:
        """首次登录角色分配：初始管理员名单 → admin；编辑名单 → editor；其余 → viewer。
        名单在 .env 配置：INITIAL_ADMIN_FEISHU_IDS / INITIAL_EDITOR_FEISHU_IDS"""
        settings = get_settings()
        if feishu_user_id in settings.INITIAL_ADMIN_FEISHU_IDS:
            return UserRole.ADMIN
        if feishu_user_id in getattr(settings, "INITIAL_EDITOR_FEISHU_IDS", []):
            return UserRole.EDITOR
        return UserRole.VIEWER

    @staticmethod
    def update_last_login(db: Session, user: User) -> User:
        user.last_login_at = datetime.now()
        db.commit()
        db.refresh(user)
        return user
