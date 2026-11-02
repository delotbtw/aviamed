from functools import lru_cache
from typing import Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

MIN_SECRET_LENGTH = 32


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
    login_max_attempts_ip: int = 20

    # Schedule (stage 2): storage is UTC, display and input use `schedule_timezone`.
    schedule_timezone: str = "Europe/Moscow"
    schedule_horizon_days: int = Field(60, ge=1)
    slot_min_minutes: int = Field(10, ge=1)
    slot_max_minutes: int = Field(240, ge=1)
    batch_max_slots: int = Field(50, ge=1)
    batch_max_window_hours: int = Field(12, ge=1)
    max_active_appointments: int = Field(20, ge=1)
    schedule_lock_timeout_ms: int = Field(5000, ge=1)  # 0 would mean "wait forever"

    # Medical organization details for the conclusion PDF header (docs/04 section 3).
    org_name: str = ""
    org_address: str = ""
    org_ogrn: str = ""

    @model_validator(mode="after")
    def _production_secret(self) -> Self:
        if not self.debug and (len(self.secret_key) < MIN_SECRET_LENGTH or "change-me" in self.secret_key.lower()):
            raise ValueError(
                f"SECRET_KEY must be at least {MIN_SECRET_LENGTH} characters and must not contain 'change-me' "
                "when DEBUG is off (generate one: python -c 'import secrets; print(secrets.token_urlsafe(48))')"
            )
        return self

    @model_validator(mode="after")
    def _slot_length_range(self) -> Self:
        if self.slot_min_minutes > self.slot_max_minutes:
            raise ValueError("slot_min_minutes must not exceed slot_max_minutes")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
