from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    app_name: str = "smart-learning-agent"
    app_env: str = "dev"

    database_url: str
    redis_url: str

    jwt_secret: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 1440

    dashscope_api_key: str
    dashscope_base_url: str
    qwen_chat_model: str = "qwen-plus"
    qwen_embedding_model: str = "text-embedding-v4"

    chroma_host: str = "localhost"
    chroma_port: int = 8000
    rag_top_k: int = 5
    llm_temperature: float = 0.3
    llm_chat_timeout_seconds: float = 60.0
    llm_embedding_timeout_seconds: float = 20.0

    # LLM 语义路由开关（文档 Section 21 Step 8 / Section 26 Step 5）
    enable_llm_intent_router: bool = False
    # 第二阶段：LangGraph 编排开关。开启后统一 Agent 入口通过图节点编排执行。
    enable_agent_langgraph: bool = False
    # 第四阶段：自动抽取并写入长期记忆。建议先配合 LangGraph 灰度开启。
    enable_agent_memory_auto_extract: bool = False
    agent_memory_extract_use_llm: bool = True
    # qwen_json 更贴合当前通义千问直连接入；langmem 会使用 LangMem manager + ChatOpenAI。
    agent_memory_extract_engine: str = "qwen_json"
    agent_memory_extract_max_candidates: int = 8

    # Stage 6: Graphiti graph memory through an independent HTTP service.
    enable_agent_graphiti: bool = False
    graphiti_service_url: str = "http://localhost:8010"
    graphiti_http_timeout_seconds: float = 10.0
    graphiti_search_limit: int = 5

    # ── 本地文件修改 Agent（文档 Section 5.1） ─────────────────
    enable_local_file_agent: bool = False
    local_file_allowed_roots: str = ""
    local_file_artifact_dir: str = ".agent_file_ops"
    local_file_max_size_bytes: int = 524288
    local_file_allowed_extensions: str = ".txt,.md,.json,.py,.js,.ts,.vue,.html,.css,.java,.c,.cpp,.sql"

settings = Settings()
