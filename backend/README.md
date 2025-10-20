# Smart Agent Backend

这是Smart Agent平台的Python后端，基于FastAPI和LangGraph构建，提供AI工作流管理和API服务。

## 技术栈

- **FastAPI** - 高性能异步Web框架
- **LangChain + LangGraph** - AI工作流管理
- **MySQL** - 关系型数据库
- **Milvus** - 向量数据库

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 环境配置

复制环境变量模板：

```bash
cp env.example .env
```

编辑 `.env` 文件，配置必要的API密钥和数据库连接信息。

### 3. 启动服务

```bash
python main.py
```

或使用uvicorn：

```bash
uvicorn src.api.server:app --host 0.0.0.0 --port 3001 --reload
```

MIT License 
