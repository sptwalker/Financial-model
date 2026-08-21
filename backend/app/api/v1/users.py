from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.permissions import PermissionChecker
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.schemas.user import UserOut, UserRoleUpdate, UserStatusUpdate
from app.services.operation_log_service import OperationLogService
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id, feishu_user_id=u.feishu_user_id, name=u.name,
        avatar_url=u.avatar_url, department=u.department,
        role=u.role.value if hasattr(u.role, "value") else u.role,
        status=u.status.value if hasattr(u.status, "value") else u.status,
    )


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """用户列表（admin/editor 可见）"""
    PermissionChecker.require_edit(current_user)
    return [_to_out(u) for u in db.query(User).order_by(User.id).all()]


@router.patch("/{user_id}/role", response_model=UserOut)
def update_role(user_id: int, body: UserRoleUpdate, db: Session = Depends(get_db),
                current_user=Depends(get_current_user)):
    """修改角色（仅 admin）"""
    PermissionChecker.require_admin(current_user)
    if body.role not in (r.value for r in UserRole):
        raise HTTPException(status_code=400, detail="非法角色")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能修改自己的角色")
    user.role = body.role
    db.commit()
    OperationLogService.log(db, action="user.role", description=f"{current_user.name} 将 {user.name} 设为 {body.role}",
                            user_id=current_user.id)
    return _to_out(user)


@router.patch("/{user_id}/status", response_model=UserOut)
def update_status(user_id: int, body: UserStatusUpdate, db: Session = Depends(get_db),
                  current_user=Depends(get_current_user)):
    """启用/禁用账号（仅 admin）"""
    PermissionChecker.require_admin(current_user)
    if body.status not in (s.value for s in UserStatus):
        raise HTTPException(status_code=400, detail="非法状态")
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="不能禁用自己")
    user.status = body.status
    db.commit()
    OperationLogService.log(db, action="user.status", description=f"{current_user.name} 将 {user.name} {'禁用' if body.status == 'disabled' else '启用'}",
                            user_id=current_user.id)
    return _to_out(user)
