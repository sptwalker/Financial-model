# 创想悦动 · 现金流测算与预测系统

将现有 Excel 现金流测算模型（`docs/现金流测算 2026.8.xls`）升级为一套**部署在公司网站、飞书登录、手机适配、面向高管**的动态现金流测算与预测系统：收入/成本数据在线动态可调，输入历史与预测数据即自动计算，并以 ECharts 动画图表直观呈现。

> 当前状态：**MVP 已交付并上线联调通过**。后端 66 项测试全绿（覆盖率 83%）、Excel 全口径对账 `BUG=0`、前端生产构建通过。
> 部署地址：`http://139.159.246.25`（详见 [deploy/README.md](deploy/README.md)）

## 技术栈（实际实现）

| 层 | 选型 |
|---|---|
| 后端 | FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · openpyxl · `decimal.Decimal` 全程建模 |
| 前端 | React 19 · Vite 8 · ECharts 6（`echarts/core` 按需引入）· react-router-dom 7 · axios · 手写移动优先 CSS |
| 数据库 | PostgreSQL 16（生产） / SQLite（本地开发） |
| 登录 | 飞书自建应用 OAuth + JWT · 三级角色（管理员 / 编辑 / 查看） |
| 部署 | Docker Compose（postgres + api + nginx）+ Nginx 反向代理 |
| 预测 | 统计口径（移动平均 / 指数平滑 / 趋势外推），`statsmodels` 惰性引入作为可选高档 |

设计文档里的 `simpleeval` 公式 DAG、`pandas`、Prophet/LightGBM、Celery/Redis **均未采用**——模型规模固定（29 期 × 37 行），直接用代码表达公式比引入公式引擎更可靠、更可测。详见下方「与设计方案的偏差」。

## 快速开始（本地开发）

```bash
# 后端 → http://127.0.0.1:8000  （Swagger: /docs）
cd backend
python -m venv .venv && .venv/Scripts/activate      # Windows
pip install -r requirements.txt
cp .env.example .env                                 # 保持 DEBUG=true
uvicorn app.main:app --reload

# 前端 → http://[::1]:5185
cd frontend
npm install
npm run dev
```

`DEBUG=true` 时后端自动建表（生产走 Alembic 迁移），并开放 `POST /api/v1/auth/dev-login` 一键以管理员身份登录，无需飞书应用凭据即可开发。

### 首次灌数据

```bash
cd backend
python -m scripts.seed_from_excel     # 从 docs/现金流测算 2026.8.xls 建基线情景并计算
python -m scripts.reconcile           # 对账引擎结果 vs Excel，输出 backend/data/reconcile_report.txt
```

### 测试

```bash
cd backend && python -m pytest -q     # 66 passed
pip install pytest-cov && python -m pytest -q --cov=app   # 覆盖率 83%
cd frontend && npm run lint && npm run build
```

## 目录结构

```
Financial-model/
├─ backend/
│  ├─ app/
│  │  ├─ api/v1/        auth · scenarios · imports · forecast · users
│  │  ├─ core/          config（Pydantic Settings + 生产 SECRET_KEY 守卫）· security(JWT) · feishu · permissions
│  │  ├─ engine/        calculator（计算引擎）· excel_import（.xls 解析）· reconcile（对账）
│  │  ├─ models/        user · financial（情景/期/单元格/版本）· forecast · operation_log
│  │  ├─ schemas/       Pydantic v2 出入参
│  │  ├─ services/      recalc · import · forecast · auth · user · fin_report · operation_log
│  │  └─ main.py        FastAPI 应用 + lifespan 启动钩子
│  ├─ alembic/          数据库迁移
│  ├─ scripts/          seed_from_excel · reconcile · migrate_sqlite_to_pg
│  └─ tests/            66 项 pytest
├─ frontend/src/
│  ├─ pages/            Dashboard（驾驶舱）· Params（参数）· Budget（预算）· Admin（管理）· Login
│  ├─ components/       Chart.jsx（ECharts 封装，按需注册）
│  ├─ api.js            后端接口封装（axios 实例 + 401 拦截）
│  ├─ rows.js           38 行行的元数据（名称/分组/类别/单位）
├─ deploy/              nginx-http.conf · nginx-https.conf.example · gen-cert.ps1
├─ docs/                设计方案书 · 开发计划 · 财务待确认问题 · 验收报告 · 原始 Excel
├─ Dockerfile           三阶段构建：api(python:3.12-slim) → fe-build(node:24) → web(nginx)
└─ docker-compose.yml   postgres + api + web
```

## 核心模型口径（财务已确认）

四类收入流：**线上 / 线下 / 配件 / 订阅**，时间轴 **2026-08 ~ 2028-12 共 29 期**（38 行 × 29 期 = 1102 个单元格），可扩展至最长三年。

- **收款确认**：线上 `[0.5, 0.5]`（当月+次月各半）、线下 `[0, 1]`（全额次月）、订阅即时全额
- **采购付款**：`N+2` 滞后（可在参数中切到 `N+3`），按全量销售额驱动
- **订阅收入**：由**累计装机量**驱动，`200 元/台/年`
- **税务**：全部按含税口径，不含增值税/所得税模块
- **现金链**：`期末[i] = 期初[i] + 现金缺口[i] + 融资[i]`，`期初[i+1] = 期末[i]`
- **精度**：引擎内部全程 `Decimal`，仅在展示层转 `float`
- **期初现金**：沿用 Excel 的静态期初链（用户已确认口径），非引擎滚动推导

完整口径见 [docs/设计方案书.md](docs/设计方案书.md) §15 与 [docs/验收报告.md](docs/验收报告.md)。

## 角色权限

| 角色 | 权限 |
|---|---|
| 管理员 admin | 全部，含用户审批/角色变更/删除情景 |
| 编辑 editor | 编辑参数与单元格、触发重算、导入 Excel、发布版本 |
| 查看 viewer | 只读看板与报表 |

所有写操作经 `OperationLog` 审计。**登录仅走飞书 OAuth，用户表没有密码字段，无密码登录入口。**

## 与设计方案的偏差（已落地决策）

| 设计文档 | 实际实现 | 原因 |
|---|---|---|
| `simpleeval` 公式 DAG + `line_item`/`formula` 表 | 代码内显式公式 | 38 行模型固定，代码比公式引擎更可测、更易调试 |
| `connector`/`import_batch`/`staging_fact`/`period`/`forecast_result` 表 | 收敛为 `scenario`/`period`/`cell`/`model_version`/`forecast_run` | 实际数据量小，中间层是过度设计 |
| Prophet / LightGBM 进阶预测 | 统计口径为主，`statsmodels` 惰性可选 | 29 期样本量不足以支撑 ML，统计法更稳健可解释 |
| 增值收入（第 5 类收入流） | **未建模** | 无数据来源与口径，待财务补充 |

## 已知待办

- **隐私数据（高优先级）**：`docs/` 下三个真实人事文件（工资表、社保明细、公积金清单）含**真实个人隐私数据**，目前仍在仓库与测试基线中。本轮经确认未做改动，后续须迁出仓库、改为脱敏测试夹具。
- **预测页 `Forecast.jsx`**：已开发但**未接入路由**，当前不可达。产品侧确认后再决定接入或删除。
- 阶段路线图与后续拓展方向见 [docs/开发计划.md](docs/开发计划.md)。

## 文档索引

| 文档 | 内容 |
|---|---|
| [docs/设计方案书.md](docs/设计方案书.md) | 原始设计方案（v0.1），含数据模型/API/架构设想 |
| [docs/开发计划.md](docs/开发计划.md) | 分阶段路线图、里程碑、风险 |
| [docs/财务待确认问题.md](docs/财务待确认问题.md) | 9 个财务口径问题及答复 |
| [docs/验收报告.md](docs/验收报告.md) | 交付验收：功能对照、对账结果、测试覆盖、遗留项 |
| [deploy/README.md](deploy/README.md) | 生产部署与运维 |
