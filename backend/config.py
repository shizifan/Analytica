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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
