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
    redis_url: str = "redis://localhost:6379/0"
    database_url: str = "mysql+asyncmy://zhongmei:zhongmei@localhost:3306/zhongmei"
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
