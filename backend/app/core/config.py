from pydantic_settings import BaseSettings
from pydantic import model_validator
from functools import lru_cache
from pathlib import Path


class Settings(BaseSettings):
    """应用配置"""

    # 应用基础配置
    APP_NAME: str = "创想悦动现金流预测系统"
    APP_VERSION: str = "0.1.0"
    DEBUG: bool = True

    # 数据库（开发默认 SQLite，Docker 生产走 postgresql://）
    # 相对路径按 backend/ 目录解析（sqlite 不支持相对 CWD，脚本/服务启动目录可能不同）
    DATABASE_URL: str = f"sqlite:///{Path(__file__).resolve().parent.parent.parent / 'data' / 'financial_model.db'}"
    DATABASE_ECHO: bool = False

    # JWT 配置
    SECRET_KEY: str = "dev-only-secret-key-please-override-in-production-0123456789"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 12  # 看板场景，12 小时会话
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # 飞书应用配置（创想悦动自建应用）
    FEISHU_APP_ID: str = ""
    FEISHU_APP_SECRET: str = ""
    FEISHU_REDIRECT_URI: str = "http://localhost:8000/api/v1/auth/feishu/callback"

    # 初始管理员 / 编辑：这些飞书 open_id 登录时自动分配对应角色
    INITIAL_ADMIN_FEISHU_IDS: list[str] = []
    INITIAL_EDITOR_FEISHU_IDS: list[str] = []

    # 前端配置
    FRONTEND_URL: str = "http://localhost:5173"

    # 系统配置
    TIMEZONE: str = "Asia/Shanghai"
    LOG_LEVEL: str = "INFO"
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:3000"]

    # 期数边界（预测/规划起点 2026-08；2026-07 为已发生月，按财务报表实际值锚定）
    PERIOD_START: str = "2026-08"
    PERIOD_END: str = "2029-12"

    # 开发模拟登录开关（生产 compose 置 false，双保险关闭 dev-login）
    ENABLE_DEV_LOGIN: bool = True

    class Config:
        env_file = Path(__file__).resolve().parent.parent / ".env"
        case_sensitive = True

    @model_validator(mode="after")
    def _guard_secret_key(self):
        """生产环境（DEBUG=false）必须覆盖 dev-only 默认 SECRET_KEY，否则拒绝启动。"""
        if not self.DEBUG and (
            not self.SECRET_KEY
            or self.SECRET_KEY == "dev-only-secret-key-please-override-in-production-0123456789"
        ):
            raise ValueError(
                "生产环境必须通过环境变量覆盖 SECRET_KEY（见 backend/.env.example）"
            )
        return self


@lru_cache()
def get_settings() -> Settings:
    """获取配置单例"""
    return Settings()
