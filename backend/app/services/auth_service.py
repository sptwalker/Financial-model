from fastapi import HTTPException, status, Request
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.core.feishu import FeishuClient
from app.core.security import create_access_token
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
            status_ = UserService.resolve_status(feishu_user_id)
            user = UserService.create(
                self.db, feishu_user_id,
                name=user_info.get("name", ""),
                avatar_url=user_info.get("avatar_url"),
                department=user_info.get("department", ""),
                role=role,
                status=status_,
            )
            OperationLogService.log(
                self.db, action="auth.register",
                description=f"新用户 {user.name} 首次登录（状态：{user.status.value}）",
                detail={"feishu_user_id": feishu_user_id, "role": role.value},
                user_id=user.id, ip=request.client.host if request.client else None,
            )
        if user.status == UserStatus.PENDING:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="账号待管理员审批，请联系管理员放行后再登录")
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

    def _issue_tokens(self, user: User) -> LoginResponse:
        return LoginResponse(
            access_token=create_access_token({"sub": str(user.id)}),
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=UserOut.model_validate(user),
        )
