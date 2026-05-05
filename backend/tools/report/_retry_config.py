"""辽港数据期刊 PR-1 — 生成重试策略配置（共享层骨架）。

定义规划层和渲染层的重试次数、超时和退避策略。
renderer 在 PR-2/3/4 中接入重试装饰器。
"""
from __future__ import annotations

import functools
import logging
import time
from dataclasses import dataclass
from typing import Callable
import os


def _env_int(name: str, default: int) -> int:
    val = os.environ.get(name)
    return int(val) if val else default


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val else default


# ---------------------------------------------------------------------------
# 重试策略
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RetryPolicy:
    """单类错误的重试策略。"""

    max_retries: int          # 最大重试次数
    backoff_base_ms: int      # 首次退避等待 (ms)
    backoff_factor: float = 2.0  # 退避乘数
    max_backoff_ms: int = 16000  # 退避上限 (ms)


# ── 规划层 ─────────────────────────────────────────────────────

PLANNER_JSON_RETRY = RetryPolicy(
    max_retries=_env_int("ANALYTICA_RETRY_PLANNER_JSON", 2),
    backoff_base_ms=500,
)

PLANNER_MISSING_BLOCK_RETRY = RetryPolicy(
    max_retries=_env_int("ANALYTICA_RETRY_PLANNER_MISSING", 1),
    backoff_base_ms=500,
)

PLANNER_COLUMN_RETRY = RetryPolicy(
    max_retries=_env_int("ANALYTICA_RETRY_PLANNER_COLUMN", 1),
    backoff_base_ms=500,
)

PLANNER_TITLE_RETRY = RetryPolicy(
    max_retries=_env_int("ANALYTICA_RETRY_PLANNER_TITLE", 1),
    backoff_base_ms=300,
)

# ── 渲染层 ─────────────────────────────────────────────────────

RENDERER_BRIDGE_TIMEOUT_RETRY = RetryPolicy(
    max_retries=_env_int("ANALYTICA_RETRY_BRIDGE", 2),
    backoff_base_ms=1000,
)

RENDERER_OOM_RETRY = RetryPolicy(
    max_retries=_env_int("ANALYTICA_RETRY_OOM", 1),
    backoff_base_ms=500,
)

# ── 全局约束 ───────────────────────────────────────────────────

# 单 block 累计重试上限
MAX_RETRIES_PER_BLOCK: int = _env_int("ANALYTICA_MAX_RETRIES_PER_BLOCK", 3)

# 整文档累计重试上限
MAX_RETRIES_PER_DOCUMENT: int = _env_int(
    "ANALYTICA_MAX_RETRIES_PER_DOCUMENT", 12,
)

# Review 最大轮次
MAX_REVIEW_ROUNDS: int = _env_int("ANALYTICA_MAX_REVIEW_ROUNDS", 2)

# 全流程超时（秒）
TOTAL_GENERATION_TIMEOUT_SEC: float = _env_float(
    "ANALYTICA_GENERATION_TIMEOUT_SEC", 300.0,
)


# ---------------------------------------------------------------------------
# 可复用重试装饰器（PR-3：DOCX/PPTX 渲染层共享）
# ---------------------------------------------------------------------------

def renderer_retry(
    policy: RetryPolicy,
    on_exc: tuple[type[Exception], ...] = (Exception,),
    logger_name: str = "analytica.tools.report",
    fallback_value: object = None,
    reraise: bool = False,
) -> Callable:
    """渲染层通用重试装饰器 — 各 renderer 共用。

    按 ``policy`` 中的退避策略在指定异常类型上重试。
    ``fallback_value`` 非 None 时最后一次失败返回该值；
    否则 ``reraise=True`` 时抛出最终异常，默认记录 error 日志并返回 None。

    用法::

        @renderer_retry(RENDERER_OOM_RETRY, on_exc=(MemoryError,))
        def render_chart(self, option): ...

        @renderer_retry(RENDERER_BRIDGE_TIMEOUT_RETRY, on_exc=(TimeoutError,))
        def call_bridge(self, cmd): ...
    """
    _logger = logging.getLogger(logger_name)

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args: object, **kwargs: object) -> object:
            last_exc: Exception | None = None
            for attempt in range(policy.max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except on_exc as e:
                    last_exc = e
                    if attempt < policy.max_retries:
                        wait_ms = int(min(
                            policy.backoff_base_ms * (policy.backoff_factor ** attempt),
                            policy.max_backoff_ms,
                        ))
                        _logger.warning(
                            "%s attempt %d/%d failed (%s); retrying in %dms",
                            func.__qualname__,
                            attempt + 1,
                            policy.max_retries + 1,
                            e,
                            wait_ms,
                        )
                        time.sleep(wait_ms / 1000.0)
                    else:
                        _logger.error(
                            "%s exhausted all %d retries: %s",
                            func.__qualname__,
                            policy.max_retries + 1,
                            e,
                        )

            if reraise and last_exc:
                raise last_exc
            return fallback_value

        return wrapper

    return decorator
