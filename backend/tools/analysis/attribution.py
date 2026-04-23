"""Attribution Analysis Skill — identifies causal factors for metric changes.

Architecture: Planning provides only `intent` (what changed and why we care).
At execution time the skill:
  1. Summarizes all upstream DataFrames via _data_summarizer.
  2. Calls LLM with intent + data summaries — the LLM discovers attribution
     dimensions from real data, not Planning-guessed target_kpi/drivers.
  3. Returns structured JSON with primary_drivers, narrative, waterfall_data.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.tools._llm import invoke_llm
from backend.tools.analysis._data_summarizer import summarize_sources
from backend.tools.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.tools.registry import register_skill

logger = logging.getLogger("analytica.tools.attribution")


# ── JSON extraction ────────────────────────────────────────────────────────────

def _extract_json(text: str) -> dict | None:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    start, end = text.find("{"), text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


# ── Prompts ────────────────────────────────────────────────────────────────────

_ATTRIBUTION_SYSTEM = """你是资深数据分析师，擅长从多源数据中识别因果关系。

分析原则：
- 直接从数据中发现驱动因素，不要凭空假设
- 区分直接原因与背景原因
- 对不确定的归因必须说明置信度
- 避免仅凭时间相关性得出因果结论

输出格式（严格 JSON，不加 markdown 标记）：
{
  "primary_drivers": [
    {"factor": "因素名称", "direction": "+/-", "estimated_impact": "约+/-X%", "evidence": "来自数据的证据"}
  ],
  "secondary_factors": [
    {"factor": "因素名称", "direction": "+/-", "estimated_impact": "约+/-X%", "evidence": "来自数据的证据"}
  ],
  "uncertainty_note": "不确定性说明",
  "narrative": "归因分析叙述（2-3段中文，围绕分析意图展开）",
  "waterfall_data": [
    {"name": "基准值", "value": 100},
    {"name": "因素名", "value": -5},
    {"name": "汇总", "value": 95}
  ]
}"""

_ATTRIBUTION_USER = """【分析意图】
{intent}

【可用数据摘要】
{data_summary}

请基于以上数据进行归因分析。重点关注数据中可以直接观察到的变化模式和结构差异，
从数据维度出发识别驱动因素，避免引入数据中未体现的外部假设。"""


# ── Skill ──────────────────────────────────────────────────────────────────────

@register_skill(
    "skill_attribution", SkillCategory.ANALYSIS,
    "归因分析（变动因素拆解）",
    input_spec="intent + context_refs（上游数据任务）",
    output_spec="归因因素列表 JSON",
)
class AttributionAnalysisSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        intent = params.get("intent") or params.get("target_metric", "指标变化归因")
        task_id = params.get("__task_id__", "")

        # Collect all upstream refs: explicit params first, then context_refs
        explicit_refs: list[str] = []
        for key in ("internal_data_ref", "data_ref"):
            val = params.get(key)
            if isinstance(val, list):
                explicit_refs.extend(val)
            elif val:
                explicit_refs.append(val)

        all_refs = explicit_refs or (inp.context_refs or [])

        # ── Summarize upstream data ────────────────────────────
        data_summary = summarize_sources(context, all_refs)

        if data_summary == "（无可用数据）":
            return self._fail("归因分析：上游数据均为空，无法执行归因")

        # ── Single LLM call: intent + data summary → attribution ──
        user_prompt = _ATTRIBUTION_USER.format(
            intent=intent,
            data_summary=data_summary,
        )

        result = await invoke_llm(
            user_prompt,
            system_prompt=_ATTRIBUTION_SYSTEM,
            temperature=0.2,
            timeout=90,
            span_emit=inp.span_emit,
            task_id=task_id,
        )

        if result["error"]:
            return SkillOutput(
                skill_id=self.skill_id,
                status="failed",
                output_type="json",
                data=None,
                error_message=result["error"],
                error_category=result["error_category"],
                llm_tokens=result["tokens"],
            )

        parsed = _extract_json(result["text"])

        if parsed is None:
            # Return raw narrative so downstream can still use it
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="json",
                data={
                    "primary_drivers": [],
                    "secondary_factors": [],
                    "uncertainty_note": "LLM 输出无法解析为 JSON",
                    "narrative": result["text"],
                    "waterfall_data": [],
                },
                metadata={"parse_error": True, "refs_used": all_refs},
                llm_tokens=result["tokens"],
                error_category="PARSE_ERROR",
            )

        return SkillOutput(
            skill_id=self.skill_id,
            status="success",
            output_type="json",
            data={
                "primary_drivers":   parsed.get("primary_drivers", []),
                "secondary_factors": parsed.get("secondary_factors", []),
                "uncertainty_note":  parsed.get("uncertainty_note", ""),
                "narrative":         parsed.get("narrative", ""),
                "waterfall_data":    parsed.get("waterfall_data", []),
            },
            metadata={"refs_used": all_refs, "sources_count": len(all_refs)},
            llm_tokens=result["tokens"],
        )
