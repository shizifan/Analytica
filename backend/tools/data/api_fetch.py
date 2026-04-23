"""API Data Fetch Skill — calls Mock/Real API endpoints and returns DataFrame.

Handles API-TOKEN injection, parameter validation, response parsing,
and data quality checks. Supports mock/prod mode via API_MODE env setting.

LLM-guided param resolution (added):
  Before the first call, an LLM analyzes the endpoint spec + planned params
  and emits (resolved_params, display_hint). On empty-result or business error,
  a second LLM pass diagnoses the problem and suggests fixed params for retry.
  Up to MAX_FETCH_RETRIES total attempts are made within a single execution.
"""
from __future__ import annotations

import logging
from typing import Any

import httpx
import pandas as pd

from backend.agent.api_registry import get_endpoint, get_endpoint_path, resolve_endpoint_id
from backend.tools.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.tools.registry import register_skill
from backend.tracing import make_span

logger = logging.getLogger("analytica.tools.api_fetch")


def _resolve_api_base() -> str:
    """Resolve API base URL from settings (lazy import to avoid init-time env load)."""
    from backend.config import get_settings
    settings = get_settings()
    if settings.API_MODE == "prod" and settings.PROD_API_BASE:
        return settings.PROD_API_BASE
    return settings.MOCK_SERVER_URL


def _is_prod_mode() -> bool:
    from backend.config import get_settings
    return get_settings().API_MODE == "prod"


def _build_auth_headers(path: str) -> dict[str, str]:
    """Build authentication headers for the given API path."""
    from backend.tools.data.token_map import get_token_for_path
    token = get_token_for_path(path)
    if token:
        return {"API-TOKEN": token}
    logger.warning("No token found for path %s, request may fail with 401", path)
    return {}


def _validate_required_params(endpoint_id: str, params: dict) -> str | None:
    """Validate required params for an endpoint. Returns error msg or None."""
    ep = get_endpoint(endpoint_id)
    if not ep:
        return None
    for rp in ep.required:
        if rp not in params:
            return f"缺少必填参数 {rp} (端点 {endpoint_id} 要求)"
    return None


def _autofill_year_pairs(endpoint_id: str, params: dict) -> None:
    """Derive `preYear = <base> - 1` when the endpoint accepts preYear but caller omitted it."""
    if "preYear" in params:
        return
    ep = get_endpoint(endpoint_id)
    if not ep or "preYear" not in (ep.required + ep.optional):
        return
    base = params.get("dateYear") if "dateYear" in params else params.get("currYear")
    if base is None:
        return
    try:
        pre = int(base) - 1
    except (TypeError, ValueError):
        return
    params["preYear"] = str(pre) if isinstance(base, str) else pre


def _is_retriable_business_error(error_message: str | None) -> bool:
    """Return True for errors that LLM-guided param adjustment might fix."""
    if not error_message:
        return False
    msg = error_message.lower()
    # Network / server errors are handled by the outer retry in execution.py
    if any(k in msg for k in ("timeout", "超时", "timed out", "429", "rate limit",
                               "500", "502", "503", "504", "服务端错误")):
        return False
    # Business / param errors are candidates for LLM fix
    return True


async def _http_get(
    url: str,
    params: dict,
    headers: dict,
    verify_ssl: bool,
) -> tuple[int, Any]:
    """Make a single HTTP GET. Returns (status_code, parsed_body).

    Raises httpx.TimeoutException on timeout, Exception on other errors.
    """
    async with httpx.AsyncClient(timeout=30.0, verify=verify_ssl, trust_env=False) as client:
        resp = await client.get(url, params=params, headers=headers)
    return resp.status_code, resp.json()


def _body_to_dataframe(body: Any) -> pd.DataFrame:
    """Extract data from API response body and convert to DataFrame."""
    if isinstance(body, dict) and "data" in body:
        raw = body["data"]
    else:
        raw = body

    if isinstance(raw, list):
        return pd.DataFrame(raw)
    if isinstance(raw, dict):
        return pd.DataFrame([raw])
    return pd.DataFrame()


@register_skill("skill_api_fetch", SkillCategory.DATA_FETCH, "调用数据源 API 获取原始数据，返回 DataFrame",
                input_spec="endpoint_id + 查询参数（日期/区域等）",
                output_spec="DataFrame (JSON 数据)")
class ApiDataFetchSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        from backend.tools.data._param_resolver import (
            MAX_FETCH_RETRIES,
            diagnose_and_fix_params,
            resolve_params_with_llm,
        )

        params = inp.params
        span_emit = inp.span_emit
        task_id = params.get("__task_id__", "")
        raw_endpoint_id = params.get("endpoint_id", "")

        # ── Resolve endpoint ──────────────────────────────────
        endpoint_id = resolve_endpoint_id(raw_endpoint_id)
        if not endpoint_id:
            return self._fail(f"未知的端点 ID: {raw_endpoint_id}")

        path = get_endpoint_path(endpoint_id)
        if not path:
            return self._fail(f"端点 {endpoint_id} 无对应 API 路径")

        ep = get_endpoint(endpoint_id)

        # Strip internal keys before any param processing
        query_params = {
            k: v for k, v in params.items()
            if k not in ("endpoint_id", "__task_id__", "__task_name__")
        }
        _autofill_year_pairs(endpoint_id, query_params)

        # ── Step 1: LLM param resolution ─────────────────────
        if ep is not None:
            task_context = params.get("__task_name__", "")
            if span_emit:
                await span_emit(make_span("param_resolve", task_id, status="start", input={
                    "endpoint_id": endpoint_id,
                    "planned_params": query_params,
                }))
            resolved_params, display_hint = await resolve_params_with_llm(
                ep,
                query_params,
                task_context=task_context,
                span_emit=span_emit,
                task_id=task_id,
            )
            if span_emit:
                await span_emit(make_span("param_resolve", task_id, status="ok", output={
                    "resolved_params": resolved_params,
                    "display_hint": display_hint,
                }))
        else:
            resolved_params = query_params
            display_hint = {}

        # Validate required params on resolved params.
        # If LLM accidentally dropped a required param, fall back to planned params.
        validation_err = _validate_required_params(endpoint_id, resolved_params)
        if validation_err:
            logger.warning(
                "[api_fetch] LLM-resolved params failed validation (%s) — falling back to planned params",
                validation_err,
            )
            resolved_params = query_params
            validation_err = _validate_required_params(endpoint_id, resolved_params)
            if validation_err:
                return self._fail(validation_err)

        api_base = _resolve_api_base()
        url = f"{api_base}{path}"
        headers = _build_auth_headers(path)
        verify_ssl = not _is_prod_mode()

        # ── Step 2: Inner retry loop ──────────────────────────
        # Outer retry in execution.py handles TIMEOUT / SERVER_ERROR / RATE_LIMIT.
        # This inner loop handles business-logic errors (wrong params, empty data)
        # by asking LLM to diagnose and suggest corrected params.

        import time as _time

        current_params = resolved_params
        last_output: SkillOutput | None = None

        for attempt in range(1, MAX_FETCH_RETRIES + 1):
            _start = _time.monotonic()

            if span_emit:
                await span_emit(make_span("api_call", task_id, status="start", input={
                    "endpoint_id": endpoint_id,
                    "url": url,
                    "params": current_params,
                    "attempt": attempt,
                }))

            try:
                status_code, body = await _http_get(url, current_params, headers, verify_ssl)
            except httpx.TimeoutException:
                if span_emit:
                    await span_emit(make_span("api_call", task_id, status="error", output={
                        "error": "API 请求超时",
                        "latency_ms": int((_time.monotonic() - _start) * 1000),
                        "attempt": attempt,
                    }))
                # Timeout is handled by the outer retry — return immediately
                return self._fail("API 请求超时")
            except Exception as e:
                logger.exception("API fetch error for %s: %s", endpoint_id, e)
                if span_emit:
                    await span_emit(make_span("api_call", task_id, status="error", output={
                        "error": str(e)[:300],
                        "latency_ms": int((_time.monotonic() - _start) * 1000),
                        "attempt": attempt,
                    }))
                return self._fail(str(e))

            latency_ms = int((_time.monotonic() - _start) * 1000)

            # ── HTTP-level error checks ───────────────────────
            if status_code == 401:
                return self._fail(f"API 认证失败 (401)")
            if status_code >= 500:
                # Server error — defer to outer retry
                return self._fail(f"API 服务端错误 ({status_code})")

            # ── Business-level error checks ───────────────────
            error_info: str | None = None

            if status_code >= 400:
                error_info = f"HTTP {status_code}: 客户端错误"
            elif isinstance(body, dict):
                if body.get("success") is False:
                    error_info = f"API 业务错误: {body.get('errorInfo', 'unknown')}"
                elif body.get("code") is not None and body["code"] != 200:
                    error_info = f"API 业务错误 (code={body['code']}): {body.get('msg', 'unknown')}"

            if error_info:
                if span_emit:
                    await span_emit(make_span("api_call", task_id, status="error", output={
                        "error": error_info,
                        "latency_ms": latency_ms,
                        "attempt": attempt,
                    }))
                last_output = self._fail(error_info)
            else:
                # ── Parse into DataFrame ──────────────────────
                df = _body_to_dataframe(body)

                # TopN truncation for getClientContributionOrder
                if endpoint_id == "getClientContributionOrder":
                    top_n = min(params.get("topN", 50), 50)
                    if len(df) > top_n:
                        df = df.head(top_n)

                row_count = len(df)

                if span_emit:
                    await span_emit(make_span("api_call", task_id, status="ok", output={
                        "status_code": status_code,
                        "rows": row_count,
                        "columns": list(df.columns)[:10],
                        "latency_ms": latency_ms,
                        "attempt": attempt,
                        "data": df.head(100).to_dict(orient="records"),
                    }))

                if row_count > 0:
                    # Success — return immediately
                    metadata: dict[str, Any] = {
                        "rows": row_count,
                        "columns": list(df.columns),
                        "endpoint": endpoint_id,
                        "query_params": current_params,
                        "attempt": attempt,
                        "display_hint": display_hint,
                    }
                    if row_count < 10:
                        metadata["quality_warning"] = "low_data_volume"
                    return SkillOutput(
                        skill_id=self.skill_id,
                        status="success",
                        output_type="dataframe",
                        data=df,
                        metadata=metadata,
                    )

                # Empty result — treat as fixable error
                error_info = f"API 返回空数据（0行），参数：{current_params}"
                last_output = self._fail(error_info)

            # ── LLM-guided fix before next attempt ───────────
            if attempt >= MAX_FETCH_RETRIES:
                break

            if ep is None or not _is_retriable_business_error(error_info):
                break

            logger.info(
                "[api_fetch] %s attempt %d/%d failed: %s — asking LLM to fix params",
                endpoint_id, attempt, MAX_FETCH_RETRIES, (error_info or "")[:120],
            )
            fixed = await diagnose_and_fix_params(
                ep,
                current_params,
                error_info or "",
                attempt,
                span_emit=span_emit,
                task_id=task_id,
            )
            if fixed is None:
                logger.info(
                    "[api_fetch] %s: LLM could not suggest a fix; giving up after attempt %d",
                    endpoint_id, attempt,
                )
                break

            current_params = fixed

        # All attempts exhausted
        return last_output or self._fail(f"端点 {endpoint_id} 在 {MAX_FETCH_RETRIES} 次尝试后仍失败")
