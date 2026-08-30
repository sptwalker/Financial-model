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
    def resolve_status(feishu_user_id: str) -> UserStatus:
        """首次登录状态分配：初始名单内（admin/editor）→ 直接 active；
        其余新用户 → pending（待管理员审批放行）。"""
        settings = get_settings()
        if (feishu_user_id in settings.INITIAL_ADMIN_FEISHU_IDS
                or feishu_user_id in getattr(settings, "INITIAL_EDITOR_FEISHU_IDS", [])):
            return UserStatus.ACTIVE
        return UserStatus.PENDING

    @staticmethod
    def sync_initial_roles(db: Session) -> int:
        """启动时按初始名单补升已存在的用户（覆盖「加此功能前已登录过」的情况）。

        名单内用户若角色/状态不符 → 补为对应角色 + active。幂等。返回补升条数。"""
        settings = get_settings()
        admin_ids = set(settings.INITIAL_ADMIN_FEISHU_IDS or [])
        editor_ids = set(getattr(settings, "INITIAL_EDITOR_FEISHU_IDS", []) or [])
        if not admin_ids and not editor_ids:
            return 0
        n = 0
        for fid in admin_ids | editor_ids:
            user = UserService.get_by_feishu_id(db, fid)
            if not user:
                continue
            want_role = UserRole.ADMIN if fid in admin_ids else UserRole.EDITOR
            changed = False
            if user.role != want_role:
                user.role = want_role
                changed = True
            if user.status != UserStatus.ACTIVE:
                user.status = UserStatus.ACTIVE
                changed = True
            if changed:
                n += 1
        if n:
            db.commit()
        return n

    @staticmethod
    def update_last_login(db: Session, user: User) -> User:
        user.last_login_at = datetime.now()
        db.commit()
        db.refresh(user)
        return user
