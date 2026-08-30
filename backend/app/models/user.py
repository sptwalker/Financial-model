from sqlalchemy import Column, String, DateTime, Enum as SQLEnum
import enum
from app.models.base import BaseModel


class UserRole(str, enum.Enum):
    """用户角色枚举（三级：管理/编辑/查看）"""
    ADMIN = "admin"
    EDITOR = "editor"
    VIEWER = "viewer"


class UserStatus(str, enum.Enum):
    """用户准入状态枚举"""
    PENDING = "pending"    # 待审批：首登后等待管理员放行（初始名单用户除外）
    ACTIVE = "active"      # 已启用：正常访问
    DISABLED = "disabled"  # 已禁用：被踢出


class User(BaseModel):
    """用户模型（飞书登录用户）"""
    __tablename__ = "users"

    feishu_user_id = Column(String(100), unique=True, nullable=False, index=True, comment="飞书用户ID(open_id)")
    name = Column(String(100), nullable=False, comment="姓名")
    avatar_url = Column(String(500), comment="头像URL")
    department = Column(String(100), comment="部门")
    role = Column(SQLEnum(UserRole, values_callable=lambda x: [e.value for e in x]),
                  default=UserRole.VIEWER, nullable=False, comment="角色")
    status = Column(SQLEnum(UserStatus, values_callable=lambda x: [e.value for e in x]),
                    default=UserStatus.ACTIVE, nullable=False, index=True, comment="状态")
    last_login_at = Column(DateTime, comment="最后登录时间")

    def __repr__(self) -> str:
        return f"<User(id={self.id}, name={self.name}, role={self.role})>"
