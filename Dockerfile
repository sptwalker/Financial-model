# ===== 创想悦动现金流预测系统 — 生产镜像 =====
# 两个构建目标（compose 各服务 build 自己的 target）：
#   target=api  →  python:3.12-slim，跑 alembic 迁移 + 数据迁移 + uvicorn
#   target=web  →  node 构建前端 → nginx:alpine 托管 dist 并反代 /api
# 分开的原因：编译型依赖（psycopg2/cryptography/pydantic-core）跨 glibc→musl 不可复制

# ---------- api ----------
FROM python:3.12-slim AS api

WORKDIR /app
COPY backend/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /app/

EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && python scripts/migrate_sqlite_to_pg.py && uvicorn app.main:app --host 0.0.0.0 --port 8000"]


# ---------- 前端构建 ----------
FROM node:24-alpine AS fe-build

WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build


# ---------- web ----------
FROM nginx:1.27-alpine AS web

COPY deploy/nginx-http.conf /etc/nginx/conf.d/default.conf
COPY --from=fe-build /fe/dist /usr/share/nginx/html

EXPOSE 80
