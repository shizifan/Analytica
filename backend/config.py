from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables / .env file."""

    QWEN_API_BASE: str = Field(..., description="Qwen3 API base URL (OpenAI compatible)")
    QWEN_API_KEY: str = Field(..., description="Qwen3 API key")
    QWEN_MODEL: str = Field(default="qwen3-235b-instruct", description="Qwen3 model name")

    # Qwen3.5-122B — lighter/faster model for planning or quick queries
    # External: opensseapi.cmhk.com  |  Online (prod): opensseapi.cmft.com
    QWEN3_5_122B_API_BASE: str = Field(
        default="https://opensseapi.cmhk.com/CMHK-LMMP-PRD_Qwen3_5_122B/CMHK-LMMP-PRD/v1",
        description="Qwen3.5-122B API base URL (OpenAI compatible)",
    )
    QWEN3_5_122B_API_KEY: str = Field(
        default="",
        description="Qwen3.5-122B API key (leave empty to reuse QWEN_API_KEY)",
    )
    QWEN3_5_122B_MODEL: str = Field(
        default="Qwen3-5-122B",
        description="Qwen3.5-122B model name",
    )

    # DeepSeek-R1
    # External: opensseapi.cmhk.com  |  Online (prod): opensseapi.cmft.com
    DEEPSEEK_R1_API_BASE: str = Field(
        default="https://opensseapi.cmhk.com/CMHK-LMMP-PRD_DeepSeek_R1/CMHK-LMMP-PRD/v1",
        description="DeepSeek-R1 API base URL (OpenAI compatible)",
    )
    DEEPSEEK_R1_API_KEY: str = Field(
        default="",
        description="DeepSeek-R1 API key (leave empty to reuse QWEN_API_KEY)",
    )
    DEEPSEEK_R1_MODEL: str = Field(
        default="DeepSeek-R1",
        description="DeepSeek-R1 model name",
    )

    REPORT_AGENT_ENABLED: bool = Field(
        default=True,
        description="Enable LLM agent loop for report generation; set False to use deterministic mode only",
    )

    REPORT_DEBUG_DUMP_OUTLINE: bool = Field(
        default=False,
        description="Dump the planned ReportOutline to data/reports/outline_<task_id>.json for debugging.",
    )

    # ── LLM sampling temperature ──────────────────────────────────────────
    # Three semantic tiers — pick by task type, not by feel:
    #   default  (0.1)  structured/deterministic output (param resolution, KPI extraction, chart mapping)
    #   balanced (0.2)  semi-generative (attribution narratives, HTML/DOCX assembly)
    #   creative (0.3)  generative prose (descriptive analysis, summary copy)
    LLM_TEMPERATURE_DEFAULT: float = Field(
        default=0.1,
        description="Temperature for structured/deterministic LLM calls",
    )
    LLM_TEMPERATURE_BALANCED: float = Field(
        default=0.2,
        description="Temperature for semi-generative LLM calls",
    )
    LLM_TEMPERATURE_CREATIVE: float = Field(
        default=0.3,
        description="Temperature for generative-prose LLM calls",
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

    REPORTS_DIR: str = Field(
        default="reports",
        description="Directory for persisted report artifacts (DOCX / "
        "PPTX / HTML / MD). Docker compose mounts /app/reports here.",
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
