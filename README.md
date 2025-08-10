# Smart Agent Platform

一个智能AI助手平台，采用现代化的全栈架构构建。该项目使用Python后端（FastAPI + LangGraph）和TypeScript前端（Next.js + assistant-ui），提供强大的AI对话和工具集成能力。

前端部分主要参考了 [assistant-ui-stockbroker](https://github.com/Yonom/assistant-ui-stockbroker) 项目的设计和实现。

## 项目特性

- 🚀 **现代化架构**: Python后端 + TypeScript前端
- 🤖 **AI工作流**: 基于LangGraph的智能工作流管理
- 📁 **文件上传**: 支持多种文件格式的上传和处理
- 🗄️ **数据库支持**: MySQL + Milvus向量数据库
- 💬 **实时对话**: 流式AI响应和实时交互
- 🛠️ **工具集成**: 可扩展的工具系统

## 项目结构

项目采用monorepo架构，包含 `frontend` 和 `backend` 两个主要目录：
- `frontend`: Next.js应用，提供用户界面和AI交互功能
- `backend`: Python后端，提供API服务和AI工作流处理

## 快速开始

### 安装依赖

从项目根目录安装所有依赖：

```bash
pnpm install
```

这将安装前端和后端项目的所有依赖。你也可以从根目录运行共享命令：

```bash
pnpm format
pnpm build
```

## 环境变量配置

### 后端配置

后端需要以下API密钥才能正常运行：

- OpenAI API Key
- 其他第三方服务API密钥（根据需要）

在 [`./backend`](./backend) 目录下创建 `.env` 文件：

```bash
OPENAI_API_KEY=your_openai_api_key_here
MYSQL_HOST=your_mysql_host
MYSQL_PASSWORD=your_mysql_password
# ... 其他配置
```

### 前端配置

前端需要配置后端API端点和助手标识符。

在 [`./frontend`](./frontend) 目录下创建 `.env` 文件：

```bash
# 本地开发使用
LANGGRAPH_API_URL=http://localhost:3001/api
NEXT_PUBLIC_LANGGRAPH_ASSISTANT_ID=smartagent
```

## 致谢

本项目前端部分主要参考了 [assistant-ui-stockbroker](https://github.com/Yonom/assistant-ui-stockbroker) 项目的优秀设计和实现。感谢原作者的贡献。
