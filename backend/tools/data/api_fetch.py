"""API Data Fetch Skill — calls Mock/Real API endpoints and returns DataFrame.

Handles API-TOKEN injection, parameter validation, response parsing,
and data quality checks. Supports mock/prod mode via API_MODE env setting.
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
    """Build authentication headers for the given API path.

    Both mock and prod use the API-TOKEN header with per-endpoint tokens.
    """
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
    """Derive `preYear = <base> - 1` when the endpoint accepts preYear but caller omitted it.

    Prod API rejects missing preYear even though the planner may treat it as optional.
    Mutates `params` in place, matching the type of the base year value.
    """
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


@register_skill("skill_api_fetch", SkillCategory.DATA_FETCH, "调用数据源 API 获取原始数据，返回 DataFrame",
                input_spec="endpoint_id + 查询参数（日期/区域等）",
                output_spec="DataFrame (JSON 数据)")
class ApiDataFetchSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        span_emit = inp.span_emit
        task_id = params.get("__task_id__", "")
        raw_endpoint_id = params.get("endpoint_id", "")

        # Resolve endpoint function name
        endpoint_id = resolve_endpoint_id(raw_endpoint_id)
        if not endpoint_id:
            return self._fail(f"未知的端点 ID: {raw_endpoint_id}")

        path = get_endpoint_path(endpoint_id)
        if not path:
            return self._fail(f"端点 {endpoint_id} 无对应 API 路径")

        # Validate required params
        query_params = {k: v for k, v in params.items() if k not in ("endpoint_id", "__task_id__")}
        _autofill_year_pairs(endpoint_id, query_params)
        validation_err = _validate_required_params(endpoint_id, query_params)
        if validation_err:
            return self._fail(validation_err)

        api_base = _resolve_api_base()
        url = f"{api_base}{path}"
        headers = _build_auth_headers(path)
        verify_ssl = not _is_prod_mode()  # prod uses self-signed cert

        import time as _time
        _start = _time.monotonic()
        if span_emit:
            await span_emit(make_span("api_call", task_id, status="start", input={
                "endpoint_id": endpoint_id,
                "url": url,
                "params": query_params,
            }))

        try:
            async with httpx.AsyncClient(timeout=30.0, verify=verify_ssl, trust_env=False) as client:
                resp = await client.get(
                    url,
                    params=query_params,
                    headers=headers,
                )

            if resp.status_code == 401:
                return self._fail(f"API 认证失败 (401): {resp.text}")
            if resp.status_code >= 500:
                return self._fail(f"API 服务端错误 ({resp.status_code}): {resp.text}")
            if resp.status_code >= 400:
                return self._fail(f"API 客户端错误 ({resp.status_code}): {resp.text}")

            body = resp.json()

            # 统一响应格式兼容:
            #   旧格式: {"success": false, "errorCode": ..., "errorInfo": "..."}
            #   新格式: {"code": 200, "msg": "success", "data": ...}
            if isinstance(body, dict):
                if body.get("success") is False:
                    return self._fail(f"API 业务错误: {body.get('errorInfo', 'unknown')}")
                if body.get("code") is not None and body["code"] != 200:
                    return self._fail(f"API 业务错误 (code={body['code']}): {body.get('msg', 'unknown')}")

            if isinstance(body, dict) and "data" in body:
                raw_data = body["data"]
            else:
                raw_data = body

            # Convert to DataFrame
            if isinstance(raw_data, list):
                df = pd.DataFrame(raw_data)
            elif isinstance(raw_data, dict):
                df = pd.DataFrame([raw_data])
            else:
                df = pd.DataFrame()

            # TopN truncation for getClientContributionOrder
            if endpoint_id == "getClientContributionOrder":
                top_n = params.get("topN", 50)
                if top_n > 50:
                    top_n = 50
                if len(df) > top_n:
                    df = df.head(top_n)
                    metadata_extra = {"truncated": True, "large_dataset_warning": f"截断为 {top_n} 条"}
                else:
                    metadata_extra = {}
            else:
                metadata_extra = {}

            # Data quality check
            row_count = len(df)
            metadata: dict[str, Any] = {
                "rows": row_count,
                "columns": list(df.columns),
                "endpoint": endpoint_id,
                "query_params": query_params,
                **metadata_extra,
            }

            if row_count < 10:
                metadata["quality_warning"] = "low_data_volume"

            if span_emit:
                await span_emit(make_span("api_call", task_id, status="ok", output={
                    "status_code": resp.status_code,
                    "rows": row_count,
                    "columns": list(df.columns)[:10],
                    "latency_ms": int((_time.monotonic() - _start) * 1000),
                    "quality_warning": metadata.get("quality_warning"),
                    "data": df.head(100).to_dict(orient="records"),
                }))
            return SkillOutput(
                skill_id=self.skill_id,
                status="success",
                output_type="dataframe",
                data=df,
                metadata=metadata,
            )

        except httpx.TimeoutException:
            if span_emit:
                await span_emit(make_span("api_call", task_id, status="error", output={
                    "error": "API 请求超时",
                    "latency_ms": int((_time.monotonic() - _start) * 1000),
                }))
            return self._fail("API 请求超时")
        except Exception as e:
            logger.exception("API fetch error for %s: %s", endpoint_id, e)
            if span_emit:
                await span_emit(make_span("api_call", task_id, status="error", output={
                    "error": str(e)[:300],
                    "latency_ms": int((_time.monotonic() - _start) * 1000),
                }))
            return self._fail(str(e))
