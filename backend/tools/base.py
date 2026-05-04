"""Tool base classes and unified output model.

Defines BaseTool (abstract), ToolInput, ToolOutput, ToolCategory,
ErrorCategory enum, classify_exception helper, and the async tool_executor
with timeout support.
"""
from __future__ import annotations

import asyncio
import json as _json
import logging
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

logger = logging.getLogger("analytica.tools")


class ToolCategory(str, Enum):
    DATA_FETCH = "data_fetch"
    ANALYSIS = "analysis"
    VISUALIZATION = "visualization"
    REPORT = "report"
    SEARCH = "search"


class ErrorCategory(str, Enum):
    """Normalized error categories used by the retry policy and observability.

    A string enum so ToolOutput.error_category round-trips cleanly through
    JSON/pydantic without custom encoders.
    """
    TIMEOUT       = "TIMEOUT"         # asyncio/httpx/openai timeout (incl LLM)
    RATE_LIMIT    = "RATE_LIMIT"      # 429 or provider rate limit
    AUTH          = "AUTH"            # 401/403 or auth error
    SCHEMA        = "SCHEMA"          # upstream response shape unexpected
    EMPTY_DATA    = "EMPTY_DATA"      # zero-row DataFrame / empty dict
    DEP_FAILED    = "DEP_FAILED"      # upstream task failed; we were skipped
    PARSE_ERROR   = "PARSE_ERROR"     # JSON / LLM output parse failure
    CLIENT_ERROR  = "CLIENT_ERROR"    # other 4xx
    SERVER_ERROR  = "SERVER_ERROR"    # 5xx
    UNKNOWN       = "UNKNOWN"


def classify_exception(e: BaseException) -> ErrorCategory:
    """Map a raised exception to an ErrorCategory.

    Duck-typed on class name for openai SDK errors to avoid a hard dependency
    on the openai package (keeps import graph slim).
    """
    # 1) timeouts
    if isinstance(e, asyncio.TimeoutError):
        return ErrorCategory.TIMEOUT

    type_name = type(e).__name__
    if "Timeout" in type_name:
        return ErrorCategory.TIMEOUT

    # 2) httpx explicit matches
    try:
        import httpx
        if isinstance(e, httpx.TimeoutException):
            return ErrorCategory.TIMEOUT
        if isinstance(e, httpx.HTTPStatusError):
            code = e.response.status_code
            if code == 429: return ErrorCategory.RATE_LIMIT
            if code in (401, 403): return ErrorCategory.AUTH
            if 500 <= code < 600:  return ErrorCategory.SERVER_ERROR
            if 400 <= code < 500:  return ErrorCategory.CLIENT_ERROR
    except ImportError:
        pass

    # 3) openai SDK — duck-type
    if "RateLimit" in type_name:
        return ErrorCategory.RATE_LIMIT
    if "Authentication" in type_name or "PermissionDenied" in type_name:
        return ErrorCategory.AUTH
    # APIStatusError / APIError with status_code attr
    code = getattr(e, "status_code", None)
    if isinstance(code, int):
        if code == 429: return ErrorCategory.RATE_LIMIT
        if code in (401, 403): return ErrorCategory.AUTH
        if 500 <= code < 600:  return ErrorCategory.SERVER_ERROR
        if 400 <= code < 500:  return ErrorCategory.CLIENT_ERROR

    # 4) parse errors
    if isinstance(e, _json.JSONDecodeError):
        return ErrorCategory.PARSE_ERROR
    # Narrow typical parse issues without over-matching
    if isinstance(e, ValueError) and any(
        k in str(e).lower() for k in ("decode", "parse", "invalid literal", "unterminated")
    ):
        return ErrorCategory.PARSE_ERROR

    return ErrorCategory.UNKNOWN


class ToolInput(BaseModel):
    params: dict[str, Any] = {}
    context_refs: list[str] = []
    span_emit: Any = None  # Callable[[dict], Awaitable[None]] | None


class ToolOutput(BaseModel):
    tool_id: str
    status: str  # success | partial | failed | skipped
    output_type: str  # dataframe | chart | text | file | json
    data: Any = None
    storage_ref: Optional[str] = None
    metadata: dict[str, Any] = {}
    error_message: Optional[str] = None
    # ── Observability fields (batch 2) ─────────────────────
    # These are populated by tool_executor (elapsed) and execute_plan
    # (attempt_count, retry metadata). llm_tokens is reserved for batch 3
    # (unified LLM wrapper).
    elapsed_seconds: float = 0.0
    attempt_count: int = 1
    error_category: Optional[str] = None   # string form of ErrorCategory
    llm_tokens: dict[str, int] = {}        # {"prompt": int, "completion": int}

    model_config = {"arbitrary_types_allowed": True}


class BaseTool(ABC):
    tool_id: str = ""
    category: ToolCategory = ToolCategory.DATA_FETCH
    description: str = ""
    input_spec: str = ""    # 供规划层 prompt 使用，如 "endpoint_id + 查询参数"
    output_spec: str = ""   # 供规划层 prompt 使用，如 "DataFrame (JSON 数据)"
    planner_visible: bool = True  # 是否出现在规划层 prompt 中
    internal_llm_timeout: int = 0  # 工具内部最长 LLM 调用超时(秒)；0=未声明，_resolve_timeout 忽略

    @abstractmethod
    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        ...

    def _fail(self, message: str) -> ToolOutput:
        return ToolOutput(
            tool_id=self.tool_id,
            status="failed",
            output_type="json",
            data=None,
            error_message=message,
        )


async def tool_executor(
    tool: BaseTool,
    inp: ToolInput,
    context: dict[str, Any],
    timeout_seconds: float = 60.0,
) -> ToolOutput:
    """Execute a tool with timeout. Always returns a ToolOutput with
    elapsed_seconds populated; on failure also populates error_category."""
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            tool.execute(inp, context),
            timeout=timeout_seconds,
        )
        elapsed = time.monotonic() - start
        # Preserve any elapsed already set by the tool (rare); otherwise record
        if not result.elapsed_seconds:
            result.elapsed_seconds = elapsed
        logger.info(
            "Tool %s completed in %.2fs with status=%s",
            tool.tool_id, elapsed, result.status,
        )
        return result
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        logger.warning("Tool %s timed out after %.2fs", tool.tool_id, elapsed)
        return ToolOutput(
            tool_id=tool.tool_id,
            status="failed",
            output_type="json",
            data=None,
            error_message=f"Timeout after {timeout_seconds:.0f}s",
            elapsed_seconds=elapsed,
            error_category=ErrorCategory.TIMEOUT.value,
        )
    except Exception as e:
        elapsed = time.monotonic() - start
        category = classify_exception(e)
        logger.exception(
            "Tool %s failed after %.2fs [%s]: %s",
            tool.tool_id, elapsed, category.value, e,
        )
        return ToolOutput(
            tool_id=tool.tool_id,
            status="failed",
            output_type="json",
            data=None,
            error_message=str(e),
            elapsed_seconds=elapsed,
            error_category=category.value,
        )
