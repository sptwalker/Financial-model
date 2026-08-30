from fastapi import FastAPI, Depends, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from app.core.config import get_settings
from app.db.session import engine
from app.db.base import Base
from app.models import (  # noqa: F401  确保模型注册到 metadata
    User, OperationLog, Scenario, ModelVersion, Cell, SalesActual, ForecastRun,
)
from app.api.v1 import auth, users, scenarios, forecast, imports

settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="创想悦动现金流预测系统 API",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(scenarios.router, prefix="/api/v1")
app.include_router(forecast.router, prefix="/api/v1")
app.include_router(imports.router, prefix="/api/v1")


@app.on_event("startup")
def on_startup():
    """开发环境自动建表（生产用 alembic 迁移）；按初始名单补升管理员/编辑"""
    if settings.DEBUG:
        from app.db.session import init_db
        init_db()
    # 初始名单补升（覆盖「加此功能前已登录过」的用户；幂等）
    from app.db.session import SessionLocal
    from app.services.user_service import UserService
    db = SessionLocal()
    try:
        n = UserService.sync_initial_roles(db)
        if n:
            print(f"[startup] 按初始名单补升 {n} 个用户为 admin/editor")
    finally:
        db.close()


@app.get("/health")
def health():
    return {"status": "ok", "app": settings.APP_NAME, "version": settings.APP_VERSION}
