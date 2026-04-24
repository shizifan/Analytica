"""Summary Generation Skill — intent-driven universal summary via LLM.

Architecture: Planning provides only `intent`. At execution time:
  1. Collects upstream narrative texts from analysis skills.
  2. Summarizes upstream DataFrames via _data_summarizer.
  3. Single LLM call: intent + narratives + data_summary → summary paragraph.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.tools._llm import invoke_llm, truncate
from backend.tools.analysis._data_summarizer import summarize_sources
from backend.tools.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.tools.registry import register_skill

logger = logging.getLogger("analytica.tools.summary_gen")

_SUMMARY_SYSTEM = "你是资深商业分析师，擅长从多源分析结果中提炼核心洞察。"

_SUMMARY_PROMPT = """【报告意图】
{intent}

【上游分析叙述】
{narratives}

【上游数据摘要】
{data_summary}

请写一段报告摘要（中文，250 字以内）：
- 先亮出核心数字或结论（完成率/同比/环比/绝对量）
- 指出最重要的 2-3 个发现
- 给出 1-2 条可操作建议
- 数字保留 1-2 位小数，大数用万/亿
- 禁止提及：缺失率、标准差、偏度、数据完整性等统计术语"""


def _is_failed_narrative(text: str) -> bool:
    if not text:
        return True
    return text.startswith("[narrative_failed:") or text.startswith("[自动生成失败]")


@register_skill("tool_summary_gen", SkillCategory.REPORT, "摘要生成（纯文本摘要段落）",
                input_spec="intent + 上游数据/分析引用",
                output_spec="中文摘要文本")
class SummaryGenSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        intent = params.get("intent") or params.get("topic", "数据分析")
        task_id = params.get("__task_id__", "")
        data_refs = params.get("data_refs") or []

        refs_to_check = data_refs if data_refs else (inp.context_refs or [])

        # Collect upstream narrative texts
        narratives: list[str] = []
        for ref in refs_to_check:
            if ref not in context:
                continue
            ctx_out = context[ref]
            data = (
                ctx_out.data if hasattr(ctx_out, "data")
                else (ctx_out.get("data") if isinstance(ctx_out, dict) else None)
            )
            if isinstance(data, dict) and "narrative" in data:
                text = data["narrative"]
                if isinstance(text, str) and not _is_failed_narrative(text):
                    narratives.append(text)
            elif isinstance(data, str) and not _is_failed_narrative(data):
                narratives.append(data)

        # Summarize upstream DataFrames and non-DataFrame outputs
        data_summary = summarize_sources(context, refs_to_check)

        if not narratives and data_summary == "（无可用数据）":
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="text",
                data=f"[摘要] 关于 {intent} 的分析已完成，详见各章节内容。",
                metadata={"stub": True},
            )

        narratives_text = truncate(
            "\n---\n".join(narratives) if narratives else "（无叙述文本）",
            max_chars=3000,
        )
        prompt = _SUMMARY_PROMPT.format(
            intent=intent,
            narratives=narratives_text,
            data_summary=data_summary if data_summary != "（无可用数据）" else "（无数据摘要）",
        )

        result = await invoke_llm(
            prompt,
            system_prompt=_SUMMARY_SYSTEM,
            temperature=0.3,
            timeout=90,
            span_emit=inp.span_emit,
            task_id=task_id,
        )

        if result["error"]:
            fallback = truncate(
                narratives[0] if narratives else f"关于 {intent} 的分析已完成。",
                max_chars=300,
            )
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="text",
                data=f"[摘要] {fallback}",
                metadata={"fallback": True},
                llm_tokens=result["tokens"],
                error_category=result["error_category"],
                error_message=result["error"],
            )

        return SkillOutput(
            skill_id=self.skill_id,
            status="success",
            output_type="text",
            data=result["text"],
            metadata={"source_refs": refs_to_check, "narrative_count": len(narratives)},
            llm_tokens=result["tokens"],
        )
