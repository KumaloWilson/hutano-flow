from functools import lru_cache
from pathlib import Path

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Hutano Flow"
    database_url: str = "sqlite:///./hutano-dev.sqlite3"
    secret_key: str = "local-development-secret-key-change-me"
    research_mode: bool = True
    cookie_secure: bool = False
    allowed_origins: list[str] | str = ["http://localhost:3000"]
    session_minutes: int = 480
    model_artifact_dir: Path = Path("artifacts")
    max_upload_bytes: int = 5_000_000

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def parse_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if not settings.research_mode:
        raise RuntimeError(
            "Production mode is intentionally disabled. A separate clinical, ethical and security review is required."
        )
    if len(settings.secret_key) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 characters")
    settings.model_artifact_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()

