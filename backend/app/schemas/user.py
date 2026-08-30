from datetime import datetime

from pydantic import BaseModel


class UserOut(BaseModel):
    id: int
    feishu_user_id: str
    name: str
    avatar_url: str | None = None
    department: str | None = None
    role: str
    status: str
    created_at: datetime | None = None
    last_login_at: datetime | None = None

    class Config:
        from_attributes = True


class UserRoleUpdate(BaseModel):
    role: str  # admin / editor / viewer


class UserStatusUpdate(BaseModel):
    status: str  # pending / active / disabled


class LogItem(BaseModel):
    id: int
    created_at: datetime | None = None
    user_id: int | None = None
    user_name: str | None = None
    action: str
    description: str | None = None
    ip: str | None = None


class LogPage(BaseModel):
    items: list[LogItem]
    total: int


class LoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: UserOut


class RefreshResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str
