from fastapi import APIRouter, Depends, Request, Query, HTTPException, status
from sqlalchemy.orm import Session
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.feishu import FeishuClient
from app.db.session import get_db
from app.models.user import User, UserRole, UserStatus
from app.schemas.user import LoginResponse, UserOut
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.services.operation_log_service import OperationLogService

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])


@router.get("/feishu/authorize")
def feishu_authorize():
    """前端跳转到飞书授权页"""
    client = FeishuClient()
    return {"authorize_url": client.get_oauth_url()}


@router.get("/feishu/callback", response_model=LoginResponse)
async def feishu_callback(code: str = Query(...), state: str | None = Query(None),
                          request: Request = None, db: Session = Depends(get_db)):
    """飞书回调：code 换 JWT"""
    service = AuthService(db)
    return await service.handle_callback(code, request)


@router.post("/refresh", response_model=LoginResponse)
async def refresh_token(refresh_token: str = Query(...), db: Session = Depends(get_db)):
    """刷新 access token"""
    service = AuthService(db)
    access_token = await service.refresh(refresh_token)
    return LoginResponse(access_token=access_token,
                         expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60)


@router.post("/dev-login", response_model=LoginResponse)
async def dev_login(db: Session = Depends(get_db)):
    """开发环境模拟登录（未配置飞书凭据时使用，一键进入 admin）

    生产环境（FEISHU_APP_ID 已配置）下返回 503，强制走飞书。
    """
    if settings.FEISHU_APP_ID:
        raise HTTPException(status_code=503, detail="飞书登录已配置，请使用飞书扫码")
    feishu_user_id = "dev_admin"
    user = UserService.get_by_feishu_id(db, feishu_user_id)
    if not user:
        user = UserService.create(db, feishu_user_id, name="开发管理员",
                                  role=UserRole.ADMIN, status=UserStatus.ACTIVE)
    user = UserService.update_last_login(db, user)
    OperationLogService.log(db, action="auth.dev_login",
                            description=f"开发模拟登录：{user.name}", user_id=user.id)
    return AuthService(db)._issue_tokens(user)


@router.get("/me", response_model=UserOut)
def me(user=Depends(get_current_user)):
    """当前登录用户信息"""
    return user
