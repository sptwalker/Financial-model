# 创想悦动 · 现金流测算与预测系统

将现有 Excel 现金流测算模型（`docs/现金流测算 2026.8.xls`）升级为一套**部署在公司网站、飞书登录、手机适配、面向高管**的动态现金流测算与预测系统：所有收入/成本数据在线动态可调，输入历史与预测数据即可自动计算并用统计/ML 方法预测未来财务，并以 ECharts 动画图表直观呈现。

> 当前阶段：**设计方案书**。业务代码尚未开始，按方案分阶段开发。

## 📄 设计方案书

完整设计见 **[docs/设计方案书.md](docs/设计方案书.md)**，涵盖：模型解构、总体架构、计算引擎、预测模块、数据模型、API、前端信息架构、集成适配层、安全权限、部署、分阶段路线图，以及待财务确认的问题。

## 技术栈（拟）

| 层 | 选型 |
|---|---|
| 后端 | FastAPI · SQLAlchemy 2.0 · Alembic · Pydantic v2 · pandas/openpyxl · statsmodels · simpleeval |
| 前端 | React 18 · TypeScript · Vite · Ant Design · @tanstack/react-query · ECharts5 |
| 数据库 | PostgreSQL（生产） / SQLite（本地） |
| 登录 | 飞书自建应用 OAuth + JWT · 三级角色（管理员/编辑/查看） |
| 部署 | Docker Compose（api + postgres + nginx）+ Nginx |

## 路线图

- **MVP(v0.5)** 把 Excel 搬上网、可多人：登录/权限/审计、模型编辑、计算引擎、Excel 导入、高管驾驶舱、基线预测、导出。
- **v1** 预测与对比：预测工作台（回测/置信区间/回填驱动/目标对账）、情景对比、版本快照与复盘、移动端打磨。
- **v2** 连接与智能：HR/生产/营销 API 连接器、进阶 ML 预测、飞书消息推送。

## 目录

```
Financial-model/
├─ README.md
├─ .gitignore
└─ docs/
   ├─ 现金流测算 2026.8.xls   原始来源模型
   └─ 设计方案书.md          系统设计方案书
```
