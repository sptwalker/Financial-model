from typing import Literal
from fastapi import HTTPException, status
from app.models.user import User, UserRole

# 可编辑数据（增删改假设/参数）的角色
EDITOR_ROLES = (UserRole.ADMIN, UserRole.EDITOR)


class PermissionChecker:
    """权限检查器（三级角色：admin 管理 / editor 编辑 / viewer 只读）"""

    @staticmethod
    def can_edit(user: User) -> bool:
        """是否具备编辑（增删改）权限"""
        return user.role in EDITOR_ROLES

    @staticmethod
    def is_admin(user: User) -> bool:
        return user.role == UserRole.ADMIN

    @staticmethod
    def _require(user: User, action: str, entity: str):
        if not PermissionChecker.can_edit(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You don't have permission to {action} this {entity}",
            )

    @staticmethod
    def require_edit(user: User, action: str = "modify", entity: str = "数据"):
        """要求编辑权限（admin/editor）"""
        PermissionChecker._require(user, action, entity)

    @staticmethod
    def require_admin(user: User, action: str = "modify", entity: str = "系统"):
        """要求管理员权限（仅 admin）"""
        if not PermissionChecker.is_admin(user):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"You don't have permission to {action} this {entity}",
            )
