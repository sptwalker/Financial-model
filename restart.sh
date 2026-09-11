#!/bin/bash
# 一键发布：拉取最新代码并重建全部容器。
# 生产环境用法（仓库根目录下）：./restart.sh
# 注意：数据库数据在 pgdata 卷里，docker compose down 不会清除。
set -e
cd "$(dirname "$0")"
git pull
docker compose down
docker compose up -d --build
