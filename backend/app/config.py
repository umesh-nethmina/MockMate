from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables (and backend/.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "MockMate API"
    environment: str = "development"

    # Secrets: only ever set via environment (NFR-06)
    anthropic_api_key: str = ""
    jwt_secret: str = "change-me-in-production"

    claude_model: str = "claude-opus-5-5"
    database_url: str = "sqlite:///./mockmate.db"
    cors_origins: list[str] = ["http://localhost:5173"]

    default_question_limit: int = 8  # FR-14
    daily_cost_cap_usd: float = 5.0  # FR-62


@lru_cache
def get_settings() -> Settings:
    return Settings()
