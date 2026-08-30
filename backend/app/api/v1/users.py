from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.permissions import PermissionChecker
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.models.operation_log import OperationLog
from app.schemas.user import UserOut, UserRoleUpdate, UserStatusUpdate, LogItem, LogPage
from app.services.operation_log_service import OperationLogService
from app.services.user_service import UserService

router = APIRouter(prefix="/users", tags=["users"])


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id, feishu_user_id=u.feishu_user_id, name=u.name,
        avatar_url=u.avatar_url, department=u.department,
        role=u.role.value if hasattr(u.role, "value") else u.role,
        status=u.status.value if hasattr(u.status, "value") else u.status,
        created_at=u.created_at, last_login_at=u.last_login_at,
    )


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """用户列表（仅 admin — 管理菜单专属）"""
    PermissionChecker.require_admin(current_user)
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
        raise HTTPException(status_code=400, detail="不能修改自己的状态")
    was_pending = (user.status == UserStatus.PENDING or user.status == "pending")
    user.status = body.status
    db.commit()
    verb = {"active": "审批通过并启用" if was_pending else "启用",
            "disabled": "屏蔽", "pending": "置为待审批"}.get(body.status, body.status)
    OperationLogService.log(db, action="user.status",
                            description=f"{current_user.name} 将 {user.name} {verb}",
                            user_id=current_user.id)
    return _to_out(user)


@router.get("/logs", response_model=LogPage)
def list_logs(limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0),
              user_id: int | None = Query(None), action: str | None = Query(None),
              db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    """操作日志（仅 admin）：登录/审批/改角色/导入等审计记录，按时间倒序分页"""
    PermissionChecker.require_admin(current_user)
    q = db.query(OperationLog)
    if user_id is not None:
        q = q.filter(OperationLog.user_id == user_id)
    if action:
        q = q.filter(OperationLog.action == action)
    total = q.count()
    rows = (q.order_by(OperationLog.created_at.desc(), OperationLog.id.desc())
            .offset(offset).limit(limit).all())
    # user_id → name 映射（一次查全，避免 N+1）
    uid_set = {r.user_id for r in rows if r.user_id is not None}
    names = {}
    if uid_set:
        for u in db.query(User).filter(User.id.in_(uid_set)).all():
            names[u.id] = u.name
    items = [LogItem(id=r.id, created_at=r.created_at, user_id=r.user_id,
                     user_name=names.get(r.user_id), action=r.action,
                     description=r.description, ip=r.ip) for r in rows]
    return LogPage(items=items, total=total)
