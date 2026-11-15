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
    # Absolute session lifetime. A session also expires after `session_idle_minutes`
    # without a user-driven refresh, which suits shared reception workstations.
    session_minutes: int = 480
    session_idle_minutes: int = 30
    model_artifact_dir: Path = Path("artifacts")
    max_upload_bytes: int = 5_000_000
    # Peers allowed to supply X-Forwarded-For (the Next.js web proxy and an optional
    # TLS reverse proxy on the Compose network). Direct clients cannot spoof their IP.
    trusted_proxies: list[str] | str = ["127.0.0.1/32", "::1/128", "172.16.0.0/12"]
    # Consecutive failed sign-ins before an account is temporarily locked.
    login_lockout_threshold: int = 5
    login_lockout_minutes: int = 15
    # Optional JSON file written by scripts/backup_demo.sh, mounted read-only.
    backup_status_path: Path | None = None

    @field_validator("allowed_origins", "trusted_proxies", mode="before")
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
    if settings.session_idle_minutes < 5 or settings.session_idle_minutes > settings.session_minutes:
        raise RuntimeError("SESSION_IDLE_MINUTES must be between 5 and SESSION_MINUTES")
    settings.model_artifact_dir.mkdir(parents=True, exist_ok=True)
    return settings


settings = get_settings()

