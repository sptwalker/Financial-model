from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.feishu import FeishuClient
from app.core.security import create_access_token, verify_token
from app.models.user import User, UserStatus
from app.schemas.user import LoginResponse, UserOut
from app.services.user_service import UserService
from app.services.operation_log_service import OperationLogService

settings = get_settings()


class AuthService:
    """飞书 OAuth 登录（自 feishu_project_manager 移植）"""

    def __init__(self, db: Session):
        self.db = db
        self.feishu = FeishuClient()

    async def handle_callback(self, code: str, request: Request) -> LoginResponse:
        """飞书回调：换 token → 取用户信息 → 查/建用户 → 分配角色 → 签发 JWT"""
        try:
            user_access_token = await self.feishu.get_user_access_token(code)
            user_info = await self.feishu.get_user_info(user_access_token)
        except Exception as e:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail=f"飞书登录失败: {e}")

        feishu_user_id = user_info.get("open_id") or user_info.get("user_id")
        if not feishu_user_id:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                                detail="飞书未返回用户标识")

        user = UserService.get_by_feishu_id(self.db, feishu_user_id)
        if not user:
            role = UserService.resolve_role(feishu_user_id)
            user = UserService.create(
                self.db, feishu_user_id,
                name=user_info.get("name", ""),
                avatar_url=user_info.get("avatar_url"),
                department=user_info.get("department", ""),
                role=role,
                status=UserStatus.ACTIVE,
            )
        if user.status != UserStatus.ACTIVE:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")

        user = UserService.update_last_login(self.db, user)
        OperationLogService.log(
            self.db, action="auth.login",
            description=f"用户 {user.name} 登录",
            detail={"feishu_user_id": feishu_user_id},
            user_id=user.id, ip=request.client.host if request.client else None,
        )
        return self._issue_tokens(user)

    async def refresh(self, refresh_token: str) -> LoginResponse:
        """刷新令牌 → 完整登录响应（含用户信息，与登录流程一致）"""
        payload = verify_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="刷新令牌无效")
        user = UserService.get_by_id(self.db, int(payload["sub"]))
        if not user:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户不存在")
        return self._issue_tokens(user)

    def _issue_tokens(self, user: User) -> LoginResponse:
        return LoginResponse(
            access_token=create_access_token({"sub": str(user.id)}),
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserOut.model_validate(user),
        )
