"""Summary Generation Skill — generates text summary paragraphs using LLM.

Rewritten in batch 3 to:
- route through backend.skills._llm.invoke_llm (unified retry/truncation/classification)
- support ``summary_style`` (executive / analytical / narrative)
- filter upstream narratives by structured ``[narrative_failed:*]`` tag
  (replaces the old ``[自动生成失败]`` prefix that hid the real cause)
- propagate llm_tokens + error_category to SkillOutput
"""
from __future__ import annotations

import logging
from typing import Any

from backend.skills._llm import infer_domain, invoke_llm, truncate
from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill

logger = logging.getLogger("analytica.skills.summary_gen")


_STYLE_PROMPTS: dict[str, str] = {
    "executive": (
        "你是向高管汇报的业务分析师。基于以下分析结果，写一段面向决策层的经营摘要（中文, 220 字以内）。\n\n"
        "主题: {topic}\n"
        "业务域: {domain}\n"
        "分析内容:\n{content}\n\n"
        "要求:\n"
        "- 结构: 先亮核心数字(完成率/同比/环比), 再指出最大风险, 最后给 1-2 条下一步建议\n"
        "- 不要重复罗列各章节已有的细节\n"
        "- 禁止提及: 缺失率、标准差、偏度、数据完整性\n"
        "- 数字保留 1-2 位小数, 大数用万/亿\n"
    ),
    "analytical": (
        "你是资深数据分析师。基于以下内容，写一段深度分析摘要（中文, 300 字以内）。\n\n"
        "主题: {topic}\n"
        "业务域: {domain}\n"
        "分析内容:\n{content}\n\n"
        "要求: 归纳 3 个关键发现, 指出驱动因素, 语言专业。"
    ),
    "narrative": (
        "基于以下分析结果, 写一段叙述性摘要（中文, 200 字以内）。\n\n"
        "主题: {topic}\n"
        "分析内容:\n{content}\n\n"
        "要求: 语言自然流畅, 不要机械复述数字。"
    ),
}


def _is_failed_narrative(text: str) -> bool:
    """Detect the new structured ``[narrative_failed:*]`` tag and the legacy
    ``[自动生成失败]`` prefix."""
    if not text:
        return True
    return text.startswith("[narrative_failed:") or text.startswith("[自动生成失败]")


@register_skill("skill_summary_gen", SkillCategory.REPORT, "摘要生成（纯文本摘要段落）",
                input_spec="data_refs + topic + summary_style + 上游数据引用",
                output_spec="中文摘要文本")
class SummaryGenSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        data_refs = params.get("data_refs", [])
        topic = params.get("topic", "数据分析")
        summary_style = params.get("summary_style", "executive")
        tmpl_meta = params.get("_template_meta", {}) or {}
        domain = infer_domain(tmpl_meta.get("template_id"))

        # Collect all narratives/data from context
        collected: list[str] = []
        refs_to_check = data_refs if data_refs else inp.context_refs
        for ref in refs_to_check:
            if ref not in context:
                continue
            ctx_out = context[ref]
            data = (
                ctx_out.data if hasattr(ctx_out, "data")
                else (ctx_out.get("data") if isinstance(ctx_out, dict) else None)
            )
            if isinstance(data, dict) and "narrative" in data:
                collected.append(data["narrative"])
            elif isinstance(data, str):
                collected.append(data)

        # Drop upstream narratives that failed to generate
        valid = [c for c in collected if not _is_failed_narrative(c)]
        dropped = len(collected) - len(valid)

        if not valid:
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="text",
                data=f"[摘要] 关于 {topic} 的分析已完成，详见各章节内容。",
                metadata={
                    "stub": True,
                    "upstream_total": len(collected),
                    "upstream_dropped_failed": dropped,
                },
            )

        # Cap total prompt content to protect against very long inputs
        combined = truncate("\n---\n".join(valid), max_chars=6000)
        style_key = summary_style if summary_style in _STYLE_PROMPTS else "executive"
        prompt = _STYLE_PROMPTS[style_key].format(
            topic=topic, domain=domain, content=combined,
        )

        result = await invoke_llm(prompt, temperature=0.3, timeout=90)
        if result["error"]:
            # Fall back to first valid narrative so the report isn't empty
            fallback = truncate(valid[0], max_chars=300)
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="text",
                data=f"[摘要] {fallback}",
                metadata={
                    "fallback": True,
                    "summary_style": style_key,
                    "upstream_dropped_failed": dropped,
                },
                llm_tokens=result["tokens"],
                error_category=result["error_category"],
                error_message=result["error"],
            )

        return SkillOutput(
            skill_id=self.skill_id,
            status="success",
            output_type="text",
            data=result["text"],
            metadata={
                "source_count": len(valid),
                "upstream_dropped_failed": dropped,
                "summary_style": style_key,
                "domain": domain,
            },
            llm_tokens=result["tokens"],
        )
