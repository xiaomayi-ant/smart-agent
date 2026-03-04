<div align="center">

# Smart Agent Platform
### FastAPI + LangGraph + Next.js Intelligent Assistant System

[![Python](https://img.shields.io/badge/Python-3.11%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![Node.js](https://img.shields.io/badge/Node.js-20%2B-339933?style=for-the-badge&logo=node.js&logoColor=white)](https://nodejs.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115%2B-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.0.20%2B-121212?style=for-the-badge)](https://github.com/langchain-ai/langgraph)
[![Next.js](https://img.shields.io/badge/Next.js-15-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-Primary%20Store-336791?style=for-the-badge&logo=postgresql&logoColor=white)](https://www.postgresql.org/)

</div>

<hr>

<p align="center">
  <a href="./backend/README.md">Backend</a> |
  <a href="./frontend/README.md">Frontend</a> |
  <a href="./backend/env.example">Backend Env</a> |
  <a href="./frontend/env.example">Frontend Env</a> |
  <a href="./docker-compose.yml">Docker Compose</a>
</p>

> [!NOTE]
> 首次运行前请先准备 `backend/.env` 与 `frontend/.env`，并完成 Prisma 迁移；前后端 `JWT_SECRET` 必须一致。

## Introduction

本项目采用前后端分离架构：

- 前端（`frontend`）提供聊天 UI、会话管理、文件上传与 API 代理。
- 后端（`backend`）负责 Agent 编排、流式回答、工具调用与线程持久化。
- 对话与业务数据依赖 PostgreSQL / MySQL / 向量库等外部服务。

## Features

- 流式对话：`/api/threads/{thread_id}/runs/stream`
- 多子图编排：SQL / Vector / KG 子图聚合
- 线程与消息持久化（PostgreSQL）
- Prisma 会话与附件数据模型（PostgreSQL）
- 工具审批流（Tool approval）
- 可选能力：文档检索（Milvus）、知识图谱（Neo4j/Graphiti）、语音 ASR

## Architecture

```text
Browser
  -> Frontend (Next.js App Router)
      -> Frontend API Routes (auth/proxy/persistence)
          -> Backend FastAPI (/api/*)
              -> LangGraph Orchestrator
                  -> SQL tools (MySQL)
                  -> Vector tools (Milvus + Embeddings)
                  -> KG tools (Neo4j/Graphiti)
              -> PostgreSQL thread/checkpoint persistence (PG_DSN)

Frontend Prisma
  -> PostgreSQL (DATABASE_URL)
```

## Quick Start

### 1. Prerequisites

| Component | Version / Requirement |
| --- | --- |
| Node.js | 20+ |
| pnpm | 9+ |
| Python | 3.11+ |
| uv | 0.9+（建议） |
| PostgreSQL | 必需（前端 Prisma + 后端线程持久化） |
| MySQL | 建议准备（后端 SQL 工具配置要求） |
| Milvus / Neo4j | 可选（按功能启用） |

### 2. Install Dependencies

```bash
# repo root
pnpm install

# backend python deps
cd backend
uv sync
cd ..
```

### 3. Configure Environment

```bash
cp backend/env.example backend/.env
cp frontend/env.example frontend/.env
```

最小必填项（建议优先确认）：

| Scope | Keys |
| --- | --- |
| Frontend | `DATABASE_URL`, `LANGGRAPH_API_URL`, `JWT_SECRET` |
| Backend | `PG_DSN`, `JWT_SECRET`, `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` |
| LLM | `LLM_PROVIDER` 对应的 API Key（`DEEPSEEK_API_KEY` 或 `OPENAI_API_KEY`） |

说明：前后端 `JWT_SECRET` 需要一致，否则登录态无法互通。

### 4. Apply Prisma Migrations

```bash
cd frontend
pnpm prisma migrate deploy
cd ..
```

### 5. Run Services

终端 1：启动后端

```bash
cd backend
uv run uvicorn src.api.server:app --host 0.0.0.0 --port 3001 --reload
```

终端 2：启动前端

```bash
cd frontend
pnpm dev
```

访问：

- Frontend: `http://localhost:3000`
- Backend Health: `http://localhost:3001/health`
- Backend OpenAPI: `http://localhost:3001/docs`

## Docker Compose

项目包含 `docker-compose.yml`（使用 GHCR 预构建镜像）：

```bash
docker compose up -d
```

注意：当前 compose 文件不会自动启动 PostgreSQL / MySQL / Milvus / Neo4j；这些外部依赖需自行提供并在 `.env` 中配置连接地址。

## Project Structure

```text
.
├── backend/                 # FastAPI + LangGraph
│   ├── src/api/server.py    # HTTP/SSE entry
│   ├── src/core/graph.py    # Graph orchestration
│   ├── src/tools/           # SQL/Vector/KG tools
│   ├── env.example          # Backend env template
│   └── pyproject.toml       # uv project metadata
├── frontend/                # Next.js + Prisma
│   ├── app/api/             # API routes & proxy
│   ├── prisma/              # Prisma schema & migrations
│   └── env.example          # Frontend env template
├── docker-compose.yml
└── README.md
```

## Development

### Monorepo Commands

```bash
pnpm -r build
pnpm -r lint
pnpm -r format
```

### Backend (uv)

```bash
cd backend
uv sync
uv run uvicorn src.api.server:app --reload --port 3001
```

### Frontend

```bash
cd frontend
pnpm dev
pnpm build && pnpm start
```

## Troubleshooting

- `PG_DSN is not configured`
  - 检查 `backend/.env` 的 `PG_DSN`。
- `Missing required MySQL env vars`
  - 补全 `MYSQL_HOST/USER/PASSWORD/DATABASE`。
- `LANGGRAPH_API_URL is not configured`
  - 补全 `frontend/.env` 的 `LANGGRAPH_API_URL`。
- `Please run Prisma migrations first`
  - 在 `frontend` 执行 `pnpm prisma migrate deploy`。

## Documentation

- 后端说明：[backend/README.md](backend/README.md)
- 前端说明：[frontend/README.md](frontend/README.md)
- 后端环境模板：[backend/env.example](backend/env.example)
- 前端环境模板：[frontend/env.example](frontend/env.example)

## License

MIT
