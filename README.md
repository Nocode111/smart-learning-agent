# 智慧学习辅助系统

基于 AI Agent 的个性化学习平台，支持智能答疑、课程学习、学习画像、练习生成、长期记忆、目标推进和图谱记忆扩展。

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3、Vite、Vue Router、Pinia、Element Plus、ECharts、Axios |
| 后端 | FastAPI、Uvicorn、Pydantic v2、SQLAlchemy、Alembic |
| 鉴权与安全 | JWT、python-jose、passlib、bcrypt |
| 数据库 | MySQL 8 |
| 缓存 / 任务状态 | Redis |
| 向量检索 | ChromaDB |
| 图谱记忆（可选） | Graphiti、Neo4j、独立 graphiti-service |
| Agent 编排 | LangGraph |
| 长期记忆抽取（可选） | LangMem、通义千问 JSON 抽取策略 |
| 大模型接入 | OpenAI 兼容接口、阿里云百炼 / 通义千问 qwen-plus |
| Embedding | text-embedding-v4 |
| 实时通信 | SSE / EventSource |
| 定时任务 | APScheduler |
| 文档解析 | pypdf、python-docx、python-pptx |
| 部署 | Docker、Docker Compose |

## 核心能力

- 用户登录、课程管理、资源管理和学习行为记录
- 基于课程资料与向量检索的智能答疑
- 支持 SSE 的真实流式回答、后台任务查询与取消
- 学习画像、薄弱点识别和个性化推荐
- 练习题生成与对话式练习 Session
- Agent 长期记忆、记忆抽取、写入策略和回忆策略
- LangGraph 编排的统一 Agent 对话流程
- 学习目标创建、拆解、执行循环、守护提醒和推进记录
- 附件上传、文档解析、本地文件修改 Agent
- 可选 Graphiti + Neo4j 图谱记忆服务

## 快速开始

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入你的阿里云百炼 API_KEY，并按需调整数据库、Redis、Chroma 和 Graphiti 配置
```

### 2. Docker Compose 启动

基础服务：

```bash
docker-compose up -d
```

如果需要同时启动 Graphiti 图谱记忆和 Neo4j：

```bash
docker-compose --profile graphiti up -d
```

### 3. 手动启动

先启动 MySQL、Redis、Chroma；如果启用图谱记忆，还需要启动 Neo4j 和 `graphiti-service`。

```bash
# 初始化数据库
mysql -u root -p < backend/init_db.sql

# 启动后端
cd backend
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000

# 启动前端
cd frontend
npm install
npm run dev
```

可选启动 Graphiti 服务：

```bash
cd graphiti-service
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8010
```

### 4. 访问

- 前端：http://localhost:5173
- 后端 API 文档：http://localhost:8000/docs
- 后端健康检查：http://localhost:8000/health
- Graphiti 服务健康检查：http://localhost:8010/health

## 核心闭环

```text
学习行为采集 -> 学习画像构建 -> RAG 智能答疑 -> 长期记忆沉淀 -> 薄弱点识别 -> 个性化推荐/练习生成 -> 目标执行推进 -> 学习反馈 -> 画像与记忆更新
```

## 项目结构

```text
smart-learning-agent/
  backend/
    app/
      main.py              # FastAPI 应用入口
      config.py            # 环境变量和配置管理
      database.py          # SQLAlchemy 数据库连接
      security.py          # JWT 鉴权
      models/              # SQLAlchemy 数据模型
      schemas/             # Pydantic 请求/响应模型
      routers/             # REST API、SSE 和 Agent 路由
      services/            # 业务逻辑、Agent 编排、记忆、目标、推荐、练习等服务
      jobs/                # APScheduler 后台任务
      prompts/             # LLM Prompt 模板
      vector_store/        # Chroma 向量存储封装
      evals/               # 记忆回归评测用例
      utils/               # 通用工具
    migrations/            # 数据库增量迁移脚本
    scripts/               # 冒烟测试和回归测试脚本
    generated/             # 本地生成文件占位目录
    init_db.sql            # 数据库初始化脚本
    requirements.txt
    Dockerfile

  frontend/
    src/
      api/                 # Axios API 封装
      router/              # Vue Router 路由
      stores/              # Pinia 状态管理
      views/               # 登录、首页、课程、答疑、目标、工具等页面
      App.vue
      main.js
    package.json
    vite.config.js
    Dockerfile

  graphiti-service/
    app/
      main.py              # Graphiti 服务 API 入口
      config.py            # Graphiti / Neo4j / 模型配置
      graphiti_service.py  # 图谱记忆读写和检索封装
      schemas.py           # Graphiti 服务请求/响应模型
    requirements.txt
    Dockerfile

  docs/                    # 功能设计与阶段开发文档
  doc/                     # 阶段验收和梳理文档
  word/                    # 项目设计文档和 AI 使用记录
  docker-compose.yml       # MySQL、Redis、Chroma、后端、前端、可选 Neo4j/Graphiti 编排
```
