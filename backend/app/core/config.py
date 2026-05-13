from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "zhongmei-rag"
    app_env: str = "local"
    jwt_secret: SecretStr
    jwt_algorithm: str = "HS256"
    jwt_access_token_minutes: int = 30
    jwt_refresh_token_days: int = 7
    pdf_token_minutes: int = 5
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "mysql+asyncmy://zhongmei:zhongmei@localhost:3306/zhongmei?charset=utf8mb4"
    login_failed_limit: int = 5
    login_failed_window_seconds: int = 900
    admin_seed_username: str = "admin"
    admin_seed_password: SecretStr | None = None
    admin_seed_display_name: str = "系统管理员"
    user_seed_username: str = "user"
    user_seed_password: SecretStr = SecretStr("User@123456")
    user_seed_display_name: str = "普通用户"
    default_users_reset_passwords: bool = False
    log_level: str = "INFO"
    dashscope_api_key: SecretStr | None = None
    dashscope_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    dashscope_native_base_url: str = "https://dashscope.aliyuncs.com/api/v1"
    dashscope_chat_model: str = "qwen3.6-plus"
    dashscope_chat_model_fallback: str = "qwen3-turbo"
    dashscope_chat_enable_thinking: bool = False
    dashscope_embedding_model: str = "qwen3-vl-embedding"
    dashscope_embedding_dimension: int = 1024
    ocr_base_url: str = "http://222.195.4.65:8899"
    ocr_workstation_host: str = "222.195.4.65"
    ocr_callback_base_url: str = "http://127.0.0.1:18000"
    ocr_callback_token: SecretStr | None = None
    ocr_poll_interval_seconds: float = 5.0
    ocr_max_poll_minutes: int = 60
    upload_dir: str = "uploads/documents"
    upload_max_mb: int = 200
    upload_max_files: int = 50
    embed_batch_size: int = 25
    chunk_tokens: int = 512
    chunk_overlap: int = 64
    chat_history_limit: int = 50
    chat_min_score_threshold: float = 0.05
    chat_topk: int = 6
    chat_no_hit_message: str = "无法在知识库中找到依据，建议换个问法或先上传相关文档。"
    export_dir: str = "uploads/exports"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
