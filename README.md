# Smart Agent Platform

基于 Python 后端（FastAPI + LangGraph）与 Next.js 前端的智能助手平台。

- 在线前端地址：https://sumoer.chat
- 仓库：`https://github.com/xiaomayi-ant/smart-agent`
- 许可证：MIT

## 目录结构
```
.
├── backend/   # FastAPI + LangGraph 服务
└── frontend/  # Next.js (App Router) + Prisma 客户端
```

## 运行环境
- Node.js 20+ 与 pnpm 9+
- Python 3.11+
- PostgreSQL（前端 Prisma 使用）
- 可选：uv（Python 包管理/运行）

## 本地开发

### 后端
```bash
cd backend
# 依赖（任选其一）
# A) uv
uv sync
# B) venv + pip
# python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt

# 启动（开发）
uv run uvicorn src.api.server:app --reload --host 0.0.0.0 --port 3001
# 文档: http://localhost:3001/docs
```

### 前端
```bash
cd frontend
pnpm install
pnpm dev   # 默认 http://localhost:3000
```

> 提示：本项目的运行依赖若干配置项（如数据库、第三方服务等）。请在本地以 `.env` 文件进行配置（不在本 README 展示具体内容），并确保前后端均已正确加载自身的配置文件。

## 部署

### 前端（sumoer.chat）
- 构建与启动：
```bash
pnpm build
pnpm start
```
- 确保前端可访问后端网关/API，反向代理/CORS 已正确配置。

### 后端
- 建议以 `uvicorn` 或 `gunicorn` + `uvicorn.workers.UvicornWorker` 方式运行，并置于反向代理后启用 HTTPS：
```bash
uvicorn src.api.server:app --host 0.0.0.0 --port 3001 --workers 4
```

### 数据库（PostgreSQL）
- 首次部署需要应用迁移：
```bash
cd frontend
pnpm prisma migrate deploy
```

## 常用脚本
- 根目录：
```bash
pnpm -r build
pnpm -r lint
pnpm -r format
```
- 前端：
```bash
pnpm dev
pnpm build && pnpm start
```
- 后端：
```bash
uv run uvicorn src.api.server:app --reload --port 3001
```

## 约定与注意
- 使用 `.env` 文件管理配置，勿将其提交至版本库。
- 请在团队内部文档中维护配置项清单与默认值，不在公开 README 中展示。

## 致谢
- 前端最初参考了 assistant-ui stockbroker 的思路，已按业务做定制化。

## 许可证
MIT
