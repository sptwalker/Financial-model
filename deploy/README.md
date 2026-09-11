# 部署运维

## 日常更新（"推送+重建"）
本地提交并推送到 `main` 后，在服务器拉取并重建镜像：
```bash
# 本地
git push origin main
# 服务器（一条命令；restart.sh = git pull && docker compose down && docker compose up -d --build）
ssh root@139.159.246.25 "cd ~/walker/Financial-model && ./restart.sh"
```
- 服务器：`root@139.159.246.25`，项目目录 `~/walker/Financial-model`
- 对外域名：**https://fm.youdoogo.com**（nginx 容器映射宿主机 `8021`）
- 栈：docker compose 三服务 `api` / `postgres` / `web`（compose 项目名 `fm`，容器 `fm-*-1`）
- postgres 数据卷持久，重建**不影响** `./data`
- 验证：
  ```bash
  ssh root@139.159.246.25 "cd ~/walker/Financial-model && git rev-parse --short HEAD && docker compose ps"
  ```
  确认 HEAD = 刚推送的提交、三服务 healthy/Up。

## 仓库根 `.env`（部署配置的唯一来源）

所有环境相关取值都走根 `.env`，模板见仓库根 [.env.example](../.env.example)。**仓库内不再有需要手工改的部署配置**，服务器工作区应与 `origin/main` 完全一致。

| 变量 | 作用 | 默认 |
|---|---|---|
| `POSTGRES_PASSWORD` | 数据库密码 | 必填，无默认则拒绝启动 |
| `SECRET_KEY` | JWT 签名密钥 | 必填；生产仍为 dev 默认值时后端拒绝启动 |
| `FEISHU_APP_ID` / `FEISHU_APP_SECRET` | 飞书自建应用凭据 | 空（为空时开放 dev-login，仅限本地） |
| `FEISHU_REDIRECT_URI` | 飞书回调地址，须与开放平台「重定向 URL」完全一致 | `http://localhost:8021/...`（占位，生产必须覆盖） |
| `FRONTEND_URL` | 登录后跳转的前端地址 | `http://localhost:8021`（占位，生产必须覆盖） |
| `WEB_PORT` | 宿主机对外端口（容器内恒为 80） | `8021`；80 空闲可设 `80` |
| `PIP_INDEX_URL` / `PIP_TRUSTED_HOST` | 构建期 pip 源 | 华为云镜像（境内构建提速） |
| `INITIAL_ADMIN_FEISHU_IDS` / `INITIAL_EDITOR_FEISHU_IDS` | 初始角色名单（JSON 数组，飞书 open_id） | `[]` |

境外构建或需要官方 pypi 源时：
```bash
docker compose build --build-arg PIP_INDEX_URL=https://pypi.org/simple --build-arg PIP_TRUSTED_HOST=
```

---

# HTTPS 上线配置（现网已启用；以下为切换/迁移留档）

## 目录内容
- `nginx-https.conf.example` — 启用 443 的 nginx 配置
- `gen-cert.ps1` — 生成自签证书（PowerShell，本机管理员权限）

## 切换步骤
1. 生成自签证书（或向 CA 申请正式证书）：
   ```powershell
   .\deploy\gen-cert.ps1
   ```
   证书输出到 `deploy/certs/`（已 gitignore）。
2. 停掉当前栈：`docker compose down`
3. `docker-compose.yml` 中 nginx 端口映射按需追加：
   - `"443:443"`（HTTPS）
   - 卷追加：`- ./deploy/certs:/etc/nginx/certs:ro`
   - 挂载 `./deploy/nginx-https.conf.example:/etc/nginx/conf.d/default.conf:ro`
4. 将 `FEISHU_REDIRECT_URI` / `FRONTEND_URL` 改为 `https://...`，重新构建：
   ```bash
   docker compose up -d --build
   ```

## 正式域名上线清单
- [x] 域名解析到服务器，防火墙放行
- [x] 证书就位（现网 `fm.youdoogo.com`）
- [ ] 根 `.env`：SECRET_KEY 换新随机值、飞书应用重定向 URI 改为 `https://域名/api/v1/auth/feishu/callback`
- [ ] CORS_ORIGINS 更新为正式域名
- [ ] 验证：`https://域名/` 登录、看板、预测、参数全链路
