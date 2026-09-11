import logging
import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import RedirectResponse, Response
from sqlalchemy.orm import Session

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.core.feishu import FeishuClient
from app.db.session import get_db
from app.models.user import UserRole, UserStatus
from app.schemas.user import LoginResponse, UserOut
from app.services.auth_service import AuthService
from app.services.user_service import UserService
from app.services.operation_log_service import OperationLogService

settings = get_settings()
router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("uvicorn.error")

_STATE_COOKIE = "feishu_oauth_state"
_STATE_TTL = 600  # 10 分钟


@router.get("/feishu/authorize")
def feishu_authorize(response: Response):
    """生成 state → httpOnly cookie → 跳转飞书授权页（防 CSRF 登录劫持）"""
    if not settings.FEISHU_APP_ID:
        raise HTTPException(status_code=503, detail="飞书登录未配置")
    state = secrets.token_urlsafe(24)
    response.set_cookie(
        key=_STATE_COOKIE, value=state, max_age=_STATE_TTL, httponly=True,
        samesite="lax",
    )
    client = FeishuClient()
    return {"authorize_url": client.get_oauth_url(state)}


@router.get("/feishu/callback")
async def feishu_callback(code: str = Query(...), state: str | None = Query(None),
                          request: Request = None, db: Session = Depends(get_db)):
    """飞书回调：校验 state → code 换 JWT → 重定向回前端

    token 经 URL **fragment**（#）传递而非 query：fragment 不会随请求发往服务端，
    因此不进反向代理访问日志、不进 Referer、不进服务端历史记录；
    前端 /login 读取后立即用 replaceState 清除。
    """
    expected = request.cookies.get(_STATE_COOKIE)
    if not expected or state != expected:
        raise HTTPException(status_code=400, detail="state 校验失败，请重新登录")
    base = f"{settings.FRONTEND_URL.rstrip('/')}/login"

    service = AuthService(db)
    try:
        result = await service.handle_callback(code, request)
    except HTTPException as e:
        # 飞书换 token/取用户信息失败：记录真实原因 + 带回登录页展示（不再返回坏掉的 401）
        logger.warning("飞书登录回调失败: %s", e.detail)
        response = RedirectResponse(url=f"{base}?{urlencode({'error': e.detail})}")
        response.delete_cookie(_STATE_COOKIE)
        return response

    # fragment 内仍用 query 编码，避免 JSON 中的 & / = 破坏解析
    fragment = urlencode({
        "access_token": result.access_token,
        "user": result.user.model_dump_json(),
    })
    response = RedirectResponse(url=f"{base}#{fragment}")
    response.delete_cookie(_STATE_COOKIE)
    return response


@router.post("/dev-login", response_model=LoginResponse)
async def dev_login(db: Session = Depends(get_db)):
    """开发环境模拟登录（未配置飞书凭据时使用，一键进入 admin）

    生产环境（FEISHU_APP_ID 已配置，或 ENABLE_DEV_LOGIN=false）下返回 503。
    """
    if settings.FEISHU_APP_ID or not settings.ENABLE_DEV_LOGIN:
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
