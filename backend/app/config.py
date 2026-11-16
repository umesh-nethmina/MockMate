from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """App settings, read from environment variables (and backend/.env in dev)."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "MockMate API"
    environment: str = "development"

    # Secrets: only ever set via environment (NFR-06)
    anthropic_api_key: str = ""
    jwt_secret: str = "dev-only-insecure-jwt-secret-change-me"  # rejected in production

    claude_model: str = "claude-opus-5-5"
    # Reasoning effort per agent: low | medium | high. Interviewer is latency-sensitive (NFR-01).
    interviewer_effort: str = "low"
    evaluator_effort: str = "medium"
    report_effort: str = "low"
    # Server-side refusal fallback (Claude API only; turn off for Bedrock/Vertex/Foundry).
    llm_fallbacks: bool = True
    # Local dev only: canned interviewer/evaluator, no API key and no cost.
    use_fake_llm: bool = False
    database_url: str = "sqlite:///./mockmate.db"
    cors_origins: list[str] = ["http://localhost:5173"]

    default_question_limit: int = 8  # FR-14
    daily_cost_cap_usd: float = 5.0  # FR-62

    jwt_expire_hours: int = 24  # NFR-05
    admin_emails: list[str] = []  # accounts registered with these emails become administrators
    guest_question_limit: int = 5  # FR-02: one short text interview
    guest_ttl_hours: int = 24  # SRS 6.1: guest sessions deleted after 24 h
    cv_max_bytes: int = 5 * 1024 * 1024  # FR-06
    cv_max_chars: int = 12_000  # keeps prompts small and limits injection surface (NFR-09)

    # Code sandbox (FR-31, NFR-07): one throw-away Docker container per run
    sandbox_enabled: bool = True
    sandbox_python_image: str = "python:3.12-alpine"
    sandbox_node_image: str = "node:22-alpine"
    sandbox_cpu_seconds: int = 5  # total CPU time per run
    sandbox_test_seconds: float = 2.0  # CPU time per test case
    sandbox_memory_mb: int = 128
    sandbox_pids_limit: int = 64
    sandbox_wall_seconds: float = 20.0  # includes container start-up
    sandbox_max_output_bytes: int = 256 * 1024
    sandbox_max_concurrent: int = 4
    sandbox_queue_seconds: float = 15.0
    max_code_runs_per_session: int = 60


DEV_JWT_SECRET = "dev-only-insecure-jwt-secret-change-me"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment == "production" and (
        settings.jwt_secret in (DEV_JWT_SECRET, "change-me") or len(settings.jwt_secret) < 32
    ):
        raise RuntimeError("Set JWT_SECRET to a random string of at least 32 characters in production")
    return settings
