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
- 栈：docker compose 三服务 `api` / `postgres` / `web`（compose 项目名 `fm`，容器 `fm-*-1`）
- postgres 数据卷持久，重建**不影响** `./data`
- 验证：
  ```bash
  ssh root@139.159.246.25 "cd ~/walker/Financial-model && git rev-parse --short HEAD && docker compose ps"
  ```
  确认 HEAD = 刚推送的提交、三服务 healthy/Up。

---

# HTTPS 上线配置（留档；内测期间走 HTTP:80）

## 目录内容
- `nginx-https.conf.example` — 启用 443 的 nginx 配置（自签证书，正式域名证书替换即用）
- `gen-cert.ps1` — 生成自签证书（PowerShell，本机管理员权限）

## 切换步骤（内测通过后、正式上线前）
1. 生成自签证书（或向 CA 申请正式证书）：
   ```powershell
   .\deploy\gen-cert.ps1
   ```
   证书输出到 `deploy/certs/`（已 gitignore）。
2. 停掉内测栈：`docker compose down`
3. `docker-compose.yml` 中 nginx 端口映射 `"80:80"` 改为：
   - `"80:80"`（HTTP→HTTPS 跳转）
   - `"443:443"`（HTTPS）
   - 卷追加：`- ./deploy/certs:/etc/nginx/certs:ro`
   - 挂载 `./deploy/nginx-https.conf.example:/etc/nginx/conf.d/default.conf:ro`
4. 将 `FEISHU_REDIRECT_URI` / `FRONTEND_URL` 改为 `https://...`，重新构建：
   ```powershell
   docker compose up -d --build
   ```

## 正式域名上线清单
- [ ] 域名解析到服务器，防火墙放行 80/443
- [ ] 申请正式证书（acme.sh / certbot），替换 certs 目录
- [ ] 根 `.env`：SECRET_KEY 换新随机值、飞书应用重定向 URI 改为 `https://域名/api/v1/auth/feishu/callback`
- [ ] CORS_ORIGINS 更新为正式域名
- [ ] 验证：`https://域名/` 登录、看板、预测、参数全链路
