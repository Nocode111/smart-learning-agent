from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8-sig",
        extra="ignore",
    )

    app_name: str = "smart-learning-graphiti-service"
    app_env: str = "dev"

    graphiti_uri: str = "bolt://localhost:7687"
    graphiti_user: str = "neo4j"
    graphiti_password: str = "please_change_graphiti_password"
    graphiti_group_prefix: str = "smart_learning"
    graphiti_search_limit: int = 5
    graphiti_build_indices_on_start: bool = False

    dashscope_api_key: str = ""
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    qwen_chat_model: str = "qwen-plus"
    qwen_embedding_model: str = "text-embedding-v4"


settings = Settings()
