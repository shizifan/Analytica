"""Attribution Analysis Skill — identifies causal factors for metric changes.

Batch 3 rewrite: routes through ``backend.skills._llm.invoke_llm`` to share
truncation, semaphore, and ErrorCategory classification. Reads the template's
``target_kpi`` and ``drivers`` fields so the prompt carries the model's
expected decomposition (previously ignored)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.skills._llm import infer_domain, invoke_llm, truncate
from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill

logger = logging.getLogger("analytica.skills.attribution")


def _extract_json(text: str) -> dict | None:
    """Extract JSON from LLM output that may be wrapped in markdown code blocks."""
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting from ```json ... ```
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding first { to last }
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            pass
    return None


ATTRIBUTION_SYSTEM_PROMPT = """你是资深数据分析师，擅长从多源数据推断因果关系。要求：
- 区分直接原因与背景原因
- 对不确定的归因必须说明置信度
- 避免仅凭时间相关性得出因果结论
- 对每个驱动因素提供具体证据

请以严格的 JSON 格式返回结果（不要添加任何 markdown 标记）：
{
  "primary_drivers": [{"factor": "因素名称", "direction": "+/-", "estimated_impact": "约+/-X%", "evidence": "证据描述"}],
  "secondary_factors": [{"factor": "因素名称", "direction": "+/-", "estimated_impact": "约+/-X%", "evidence": "证据描述"}],
  "uncertainty_note": "不确定性说明",
  "narrative": "归因分析叙述段落（2-3段，中文）",
  "waterfall_data": [{"name": "基准值", "value": 100}, {"name": "因素1", "value": -5}, {"name": "汇总", "value": 95}]
}"""


@register_skill("skill_attribution", SkillCategory.ANALYSIS, "归因分析（变动因素拆解）",
                input_spec="internal_data_ref + target_metric + time_period",
                output_spec="归因因素列表 JSON")
class AttributionAnalysisSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        internal_data_ref = params.get("internal_data_ref")
        external_context_ref = params.get("external_context_ref")
        target_metric = params.get("target_metric", "指标变化")
        time_period = params.get("time_period", "")
        # New (batch 3): consume template-provided decomposition hints.
        target_kpi = params.get("target_kpi") or []        # ["T001.finishQty/T001.targetQty", ...]
        drivers = params.get("drivers") or []              # ["港区贡献(T005)", "货种贡献(T006)"]
        focus_points = params.get("focus_points") or []
        tmpl_meta = params.get("_template_meta", {}) or {}
        domain = infer_domain(tmpl_meta.get("template_id"))

        # Get internal data from context — fallback to context_refs
        internal_data = None
        if internal_data_ref and internal_data_ref in context:
            ctx_out = context[internal_data_ref]
            if hasattr(ctx_out, "data"):
                internal_data = ctx_out.data
            elif isinstance(ctx_out, dict):
                internal_data = ctx_out.get("data")
        elif inp.context_refs:
            # Collect all non-empty upstream data (attribution benefits from
            # richer context when the template lists multiple drivers).
            collected: list[Any] = []
            for ref in inp.context_refs:
                if ref in context:
                    ctx_out = context[ref]
                    ref_data = ctx_out.data if hasattr(ctx_out, "data") else ctx_out
                    if ref_data is not None:
                        collected.append({"ref": ref, "data": ref_data})
            internal_data = collected if collected else None

        # Get external context
        external_data = None
        if external_context_ref and external_context_ref in context:
            ctx_out = context[external_context_ref]
            if hasattr(ctx_out, "data"):
                external_data = ctx_out.data
            elif isinstance(ctx_out, dict):
                external_data = ctx_out.get("data")

        # Build user prompt ─ includes template-specified drivers/KPIs so the
        # LLM is guided toward the exact decomposition the template wants.
        user_prompt_parts = [
            f"业务域: {domain}",
            f"目标指标: {target_metric}",
            f"分析时段: {time_period}",
        ]
        if target_kpi:
            user_prompt_parts.append(
                "关键 KPI 公式:\n" + "\n".join(f"- {k}" for k in target_kpi)
            )
        if drivers:
            user_prompt_parts.append(
                "候选驱动因素（模板指定）:\n" + "\n".join(f"- {d}" for d in drivers)
            )
        if focus_points:
            user_prompt_parts.append(
                "分析重点:\n" + "\n".join(f"- {p}" for p in focus_points)
            )
        if internal_data is not None:
            user_prompt_parts.append(
                "内部数据统计: " + truncate(
                    json.dumps(internal_data, ensure_ascii=False, default=str),
                    max_chars=3000,
                )
            )
        if external_data is not None:
            user_prompt_parts.append(
                "外部检索结果: " + truncate(
                    json.dumps(external_data, ensure_ascii=False, default=str),
                    max_chars=2000,
                )
            )
        else:
            user_prompt_parts.append(
                "注意：无外部检索数据，请仅基于内部数据进行归因，"
                "并在 uncertainty_note 中说明数据局限性。"
            )

        user_prompt = "\n".join(user_prompt_parts)

        result = await invoke_llm(
            user_prompt,
            system_prompt=ATTRIBUTION_SYSTEM_PROMPT,
            temperature=0.2,
            timeout=90,
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

        raw = result["text"]
        parsed = _extract_json(raw)

        if parsed is None:
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="json",
                data={
                    "primary_drivers": [],
                    "secondary_factors": [],
                    "uncertainty_note": "LLM 输出无法解析为 JSON",
                    "narrative": raw,
                    "waterfall_data": [],
                },
                metadata={
                    "raw_response_length": len(raw),
                    "domain": domain,
                },
                llm_tokens=result["tokens"],
                error_category="PARSE_ERROR",
            )

        ready = {
            "primary_drivers": parsed.get("primary_drivers", []),
            "secondary_factors": parsed.get("secondary_factors", []),
            "uncertainty_note": parsed.get("uncertainty_note", ""),
            "narrative": parsed.get("narrative", ""),
            "waterfall_data": parsed.get("waterfall_data", []),
        }

        return SkillOutput(
            skill_id=self.skill_id,
            status="success",
            output_type="json",
            data=ready,
            metadata={
                "has_external_context": external_data is not None,
                "drivers_count": len(drivers),
                "domain": domain,
            },
            llm_tokens=result["tokens"],
        )
