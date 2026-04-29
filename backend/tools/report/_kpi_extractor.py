"""LLM-powered KPI extraction for report cover blocks.

Architecture: At execution time, examines actual upstream data summaries and
uses LLM to discover the 3-4 most meaningful KPI metrics. No hardcoded domain
rules, no task-id / field-name assumptions.

Entry point: extract_kpis_llm(intent, context, *, span_emit, task_id)
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

from backend.config import get_settings
from backend.tools._llm import invoke_llm
from backend.tools.analysis._data_summarizer import summarize_sources

logger = logging.getLogger("analytica.tools.report.kpi")


@dataclass
class KPIItem:
    """A single metric card surfaced above section 1 in the report.

    Attributes:
        label:  Short label shown at the top of the card (e.g. "吞吐量完成率").
        value:  Formatted primary value (e.g. "17.3%").
        sub:    Optional subtitle (e.g. "目标 48,000 万吨").
        trend:  ``"positive"`` / ``"negative"`` / None — drives CSS class.
    """
    label: str
    value: str
    sub: str = ""
    trend: str | None = None


_KPI_SYSTEM = (
    "你是数据分析专家，负责从分析结果中提炼最关键的KPI指标卡片。"
    "严格输出 JSON 数组，不加 markdown 标记，不加解释文字。"
)

_KPI_PROMPT = """【报告意图】
{intent}

【可用数据摘要】
{data_summary}

请从以上数据中提炼 3-4 个最关键的 KPI 指标，输出 JSON 数组（严格 JSON，不加 markdown）：
[
  {{"label": "指标名称", "value": "123.4万吨", "sub": "目标150万吨（可选）", "trend": "positive"}}
]

规则：
- 优先选择：完成率、同比/环比增长率、核心业务绝对量
- value 格式化为人类可读（万/亿/百分比），保留 1-2 位小数
- trend: "positive"=达成/增长, "negative"=未达成/下降, null=中性指标
- sub 填辅助说明（如目标值、对比值），若无意义则填空字符串 ""
- 若数据不足以支撑某类指标，宁可少写也不要编造"""


def _parse_kpi_json(text: str) -> list[dict] | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    text = re.sub(r"^```(?:json)?\s*", "", text).rstrip("` \n")
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if not m:
        return None
    try:
        result = json.loads(m.group())
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass
    return None


async def extract_kpis_llm(
    intent: str,
    context: dict[str, Any],
    *,
    span_emit=None,
    task_id: str = "",
) -> list[KPIItem]:
    """Discover KPI cards from upstream data using LLM.

    Returns empty list on any failure — renderers skip the KPI block cleanly.
    """
    if not context:
        return []

    all_refs = list(context.keys())
    data_summary = summarize_sources(context, all_refs)
    if data_summary == "（无可用数据）":
        return []

    prompt = _KPI_PROMPT.format(
        intent=intent or "数据分析报告",
        data_summary=data_summary,
    )

    result = await invoke_llm(
        prompt,
        system_prompt=_KPI_SYSTEM,
        temperature=get_settings().LLM_TEMPERATURE_DEFAULT,
        timeout=30,
        span_emit=span_emit,
        task_id=task_id,
    )

    if result.get("error"):
        logger.warning("KPI LLM failed [%s]: %s", result.get("error_category"), result.get("error"))
        return []

    parsed = _parse_kpi_json(result["text"])
    if not parsed:
        logger.warning("KPI JSON parse failed, text=%r", result["text"][:200])
        return []

    items: list[KPIItem] = []
    for raw in parsed[:4]:
        if not isinstance(raw, dict) or not raw.get("label") or not raw.get("value"):
            continue
        trend = raw.get("trend")
        if trend not in ("positive", "negative"):
            trend = None
        items.append(KPIItem(
            label=str(raw["label"]),
            value=str(raw["value"]),
            sub=str(raw.get("sub") or ""),
            trend=trend,
        ))

    logger.info("KPI extraction OK: %d cards for intent=%r", len(items), intent[:40])
    return items
