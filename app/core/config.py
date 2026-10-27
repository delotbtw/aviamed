from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Med Center"
    debug: bool = False

    database_url: str = "postgresql+asyncpg://medcenter:medcenter@localhost:5432/medcenter"
    redis_url: str = "redis://localhost:6379/0"

    # Secrets: no defaults that are safe to use in production, override via env.
    secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_ttl_min: int = 15
    refresh_token_ttl_days: int = 7

    login_max_attempts: int = 5
    login_window_s: int = 900

    # Medical organization details for the conclusion PDF header (docs/04 section 3).
    org_name: str = ""
    org_address: str = ""
    org_ogrn: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
