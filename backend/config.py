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

    # ── SessionWorkspace (V6 §5.2) ──────────────────────────────────
    # Per-session workspace stores task outputs as durable artifacts so
    # cross-turn data reuse goes through `data_ref` resolution instead of
    # ad-hoc conversion_context.pkl. One directory per session under
    # WORKSPACE_ROOT, with a manifest.json index.
    WORKSPACE_ROOT: str = Field(
        default="workspace",
        description="Root directory for SessionWorkspace files. Each "
        "session gets {root}/{session_id}/workspace/. Relative paths "
        "resolve against CWD (analogous to REPORTS_DIR).",
    )
    WORKSPACE_MAX_ITEMS_PER_SESSION: int = Field(
        default=100,
        description="Soft cap on manifest items per session before "
        "eviction kicks in (V6 §5.2.5). Files are removed but manifest "
        "entries remain marked status=cleared for audit.",
    )

    # ── MCP (Model Context Protocol) 搜索服务 ───────────────────────────
    MCP_SEARCH_URL: str = Field(
        default="https://aiagentplatform.cmft.com/api/proxy/mcp",
        description="MCP 搜索服务端点 URL",
    )
    MCP_SEARCH_API_KEY: str = Field(
        default="d7qatlud83clu410ajog",
        description="MCP 搜索服务 API Key（作为 query 参数附加）",
    )

    # ── 搜索配置 ───────────────────────────────────────────
    SEARCH_TOP_K: int = Field(
        default=5,
        description="搜索返回的最大结果数",
    )
    SEARCH_LANG: str = Field(
        default="zh-CN",
        description="搜索语言偏好（如 zh-CN / en）",
    )
    SEARCH_PROVIDER_TIMEOUT: float = Field(
        default=60.0,
        description="单个 MCP 搜索请求的超时秒数",
    )

    # ── 搜索功能总开关 ──────────────────────────────────────
    ENABLE_WEB_SEARCH: bool = Field(
        default=False,
        description="联网搜索功能总开关（False=全局禁用，前端开关无效）",
    )

    # ── 超时 / 并发控制（per-type） ─────────────────────────
    # 覆盖 execution.py 中的 _CONCURRENCY_LIMITS / _TIMEOUT_PROFILE / _RETRY_POLICY
    # 格式: "type:lo,hi,mult" 如 "report_gen:120,300,2.5"
    # env 示例: ANALYTICA_TIMEOUT_REPORT_GEN=120,300,2.5
    ANALYTICA_TIMEOUT_REPORT_GEN: str = Field(
        default="120,300,2.5",
        description="report_gen 超时: lower,upper,multiplier",
    )
    ANALYTICA_TIMEOUT_ANALYSIS: str = Field(
        default="60,150,2.5",
        description="analysis 超时: lower,upper,multiplier",
    )
    ANALYTICA_TIMEOUT_DATA_FETCH: str = Field(
        default="15,90,3.0",
        description="data_fetch 超时: lower,upper,multiplier",
    )
    ANALYTICA_TIMEOUT_VISUALIZATION: str = Field(
        default="5,20,2.0",
        description="visualization 超时: lower,upper,multiplier",
    )
    ANALYTICA_TIMEOUT_SEARCH: str = Field(
        default="30,100,2.5",
        description="search 超时: lower,upper,multiplier",
    )

    # Per-type concurrency limits
    ANALYTICA_CONCURRENCY_REPORT_GEN: int = Field(default=1)
    ANALYTICA_CONCURRENCY_ANALYSIS: int = Field(default=2)
    ANALYTICA_CONCURRENCY_DATA_FETCH: int = Field(default=8)
    ANALYTICA_CONCURRENCY_VISUALIZATION: int = Field(default=4)
    ANALYTICA_CONCURRENCY_SEARCH: int = Field(default=1)

    # Global LLM concurrency
    ANALYTICA_LLM_CONCURRENCY: int = Field(
        default=3,
        description="进程级全局 LLM 并发上限",
    )

    # Retry: report_gen (disabled), analysis (rate-limit only to skip useless retries)
    ANALYTICA_RETRY_REPORT_GEN_ENABLED: bool = Field(
        default=False,
        description="report_gen 是否启用重试",
    )
    ANALYTICA_RETRY_ANALYSIS_RETRY_TIMEOUT: bool = Field(
        default=False,
        description="analysis 是否对 TIMEOUT 错误重试",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}


def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
