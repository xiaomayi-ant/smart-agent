# Financial Expert Python Backend

这是AI助手的Python后端实现，使用FastAPI和LangGraph构建。

## 功能特性

- 🚀 **FastAPI** - 高性能异步Web框架
- 🤖 **LangChain + LangGraph** - AI工作流管理
- 🗄️ **MySQL** - 关系型数据库
- 🔍 **Milvus** - 向量数据库搜索
- 📊 **股票数据查询** - 实时股票信息
- 📅 **日期计算** - 灵活的日期操作
- 🔄 **流式响应** - 实时AI回复

## 项目结构

```
backend_py/
├── src/
│   ├── api/           # FastAPI服务器
│   ├── core/          # 核心配置和工作流
│   ├── models/        # 数据模型
│   ├── tools/         # 工具函数
│   └── utils/         # 工具函数
├── tests/             # 测试文件
├── requirements.txt   # Python依赖
├── pyproject.toml     # 项目配置
├── main.py           # 主入口
└── README.md         # 说明文档
```

## 安装和运行

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `env.example` 到 `.env` 并配置：

```bash
cp env.example .env
```

编辑 `.env` 文件，设置必要的环境变量：

```env
OPENAI_API_KEY=your_openai_api_key_here
MYSQL_HOST=your_mysql_host
MYSQL_PASSWORD=your_mysql_password
# ... 其他配置
```

### 3. 启动服务器

```bash
python main.py
```

或者使用uvicorn直接启动：

```bash
uvicorn src.api.server:app --host 0.0.0.0 --port 3001 --reload
```

## API接口

### 创建线程
```http
POST /api/threads
```

### 流式对话
```http
POST /api/threads/{thread_id}/runs/stream
Content-Type: application/json

{
  "input": {
    "messages": [
      {"role": "user", "content": "查询AAPL的股票信息"}
    ]
  }
}
```

### 获取线程消息
```http
GET /api/threads/{thread_id}/messages
```

### 删除线程
```http
DELETE /api/threads/{thread_id}
```

## 工具功能

### 股票数据工具
- `get_company_facts_tool` - 获取公司基本信息
- `get_income_statements_tool` - 获取收入报表
- `get_balance_sheets_tool` - 获取资产负债表
- `get_cash_flow_statements_tool` - 获取现金流量表
- `get_stock_snapshot_tool` - 获取实时股票价格

### 搜索工具
- `hybrid_milvus_search_tool` - 混合向量搜索

### 日期工具
- `date_calculator_tool` - 日期计算

## 开发

### 代码格式化
```bash
black src/
isort src/
```

### 运行测试
```bash
pytest tests/
```

### 类型检查
```bash
mypy src/
```

## 部署

### Docker部署
```bash
docker build -t financial-expert-py .
docker run -p 3001:3001 financial-expert-py
```

### 生产环境
```bash
uvicorn src.api.server:app --host 0.0.0.0 --port 3001 --workers 4
```

## 与原TypeScript版本的对比

| 特性 | TypeScript版本 | Python版本 |
|------|----------------|-------------|
| 框架 | Express.js | FastAPI |
| AI框架 | LangChain.js | LangChain Python |
| 工作流 | LangGraph.js | LangGraph Python |
| 数据库 | MySQL + Milvus | MySQL + Milvus |
| 性能 | 良好 | 优秀 |
| 开发效率 | 中等 | 高 |
| 生态系统 | 丰富 | 更丰富 |

## 许可证

MIT License 