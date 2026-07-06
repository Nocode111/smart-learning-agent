# 智慧学习辅助系统

基于 AI Agent 的个性化学习平台 - 最小落地版本

## 技术栈

| 层级 | 技术 |
|------|------|
| 前端 | Vue 3 + Vite + Element Plus + ECharts |
| 后端 | FastAPI + Uvicorn |
| 数据库 | MySQL 8 |
| 缓存 | Redis |
| 向量库 | Chroma |
| 大模型 | 通义千问 (qwen-plus) |
| Embedding | text-embedding-v4 |

## 快速开始

### 1. 配置环境变量

```bash
cp backend/.env.example backend/.env
# 编辑 backend/.env，填入你的阿里云百炼 API_KEY
```

### 2. Docker Compose 启动（推荐）

```bash
docker-compose up -d
```

### 3. 手动启动

**启动 MySQL、Redis、Chroma 后：**

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

### 4. 访问

- 前端：http://localhost:5173
- 后端 API 文档：http://localhost:8000/docs
- 健康检查：http://localhost:8000/health

## 核心闭环

```
学习行为采集 → 学习画像构建 → 千问智能答疑 → 薄弱点识别 → 个性化方案推送 → 学习反馈 → 画像更新
```

## 项目结构

```
smart-learning-agent/
  backend/
    app/
      main.py              # FastAPI 入口
      config.py            # 配置管理
      database.py          # 数据库连接
      security.py          # JWT 鉴权
      models/              # 12 张数据表模型
      schemas/             # Pydantic 请求/响应校验
      routers/             # 9 个路由模块
      services/            # 核心业务逻辑
      prompts/             # LLM Prompt 模板
      vector_store/        # Chroma 向量存储
    init_db.sql            # 数据库初始化脚本
    requirements.txt
    Dockerfile
  frontend/
    src/
      api/                 # Axios API 封装
      router/              # Vue Router
      stores/              # Pinia 状态管理
      views/               # 6 个页面视图
  docker-compose.yml
```
