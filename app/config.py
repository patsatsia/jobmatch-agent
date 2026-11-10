from functools import lru_cache

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    anthropic_api_key: SecretStr | None = None
    aws_region: str = "eu-central-1"
    log_level: str = "INFO"
    db_echo: bool = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
