from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    QWEN_API_BASE: str = Field(..., description="Qwen3 API base URL (OpenAI compatible)")
    QWEN_API_KEY: str = Field(..., description="Qwen3 API key")
    QWEN_MODEL: str = Field(default="qwen3-235b-instruct", description="Qwen3 model name")

    REPORT_AGENT_ENABLED: bool = Field(
        default=True,
        description="Enable LLM agent loop for report generation; set False to use deterministic mode only",
    )

    DATABASE_URL: str = Field(
        default="mysql+aiomysql://root@localhost:3306/analytica",
        description="Async database URL",
    )
    DATABASE_URL_SYNC: str = Field(
        default="mysql+pymysql://root@localhost:3306/analytica",
        description="Sync database URL (for Alembic)",
    )

    MOCK_SERVER_URL: str = Field(
        default="http://localhost:18080",
        description="Mock Server base URL",
    )

    PROD_API_BASE: str = Field(
        default="",
        description="Production API base URL",
    )
    API_MODE: str = Field(
        default="mock",
        description="API mode: 'mock' or 'prod'",
    )

    # UI/UE revamp feature flags — see specs/ui-revamp-v2 phased plan.
    # All default to the pre-revamp behavior so flipping them off rolls back cleanly.
    FF_NEW_UI: bool = Field(
        default=False,
        description="Phase 1: enable three-pane workbench layout + new design tokens",
    )
    FF_THINKING_STREAM: bool = Field(
        default=True,
        description="Phase 2/3: persist thinking_events (node + tool + decision). "
                    "WS events are always forwarded so the inspector renders "
                    "in real time even when persistence is off.",
    )
    FF_EMPLOYEE_SOURCE: str = Field(
        default="db",
        description="Phase 4: 'yaml' (files are source of truth) or 'db' (employees table). "
                    "DB mode requires the seed script to have run. YAML is a safe fallback "
                    "(lifespan catches DB failure and falls back automatically).",
    )
    FF_API_REGISTRY_SOURCE: str = Field(
        default="code",
        description="Phase 6: 'code' (backend/agent/api_registry.py) or 'db' (api_endpoints table)",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
