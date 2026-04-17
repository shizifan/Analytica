"""Summary Generation Skill — generates text summary paragraphs using LLM."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill

logger = logging.getLogger("analytica.skills.summary_gen")


def _strip_think_tags(text: str) -> str:
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


@register_skill("skill_summary_gen", SkillCategory.REPORT, "摘要生成（纯文本摘要段落）",
                input_spec="data_refs + topic + 上游数据引用",
                output_spec="中文摘要文本")
class SummaryGenSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        params = inp.params
        data_refs = params.get("data_refs", [])
        topic = params.get("topic", "数据分析")

        # Collect all narratives/data from context
        collected = []
        refs_to_check = data_refs if data_refs else inp.context_refs
        for ref in refs_to_check:
            if ref in context:
                ctx_out = context[ref]
                data = ctx_out.data if hasattr(ctx_out, "data") else (ctx_out.get("data") if isinstance(ctx_out, dict) else None)
                if isinstance(data, dict) and "narrative" in data:
                    collected.append(data["narrative"])
                elif isinstance(data, str):
                    collected.append(data)

        if not collected:
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="text",
                data=f"[摘要] 关于{topic}的分析已完成，详见各章节内容。",
                metadata={"stub": True},
            )

        # Filter out failed narrative fallbacks from upstream
        collected = [c for c in collected if not c.startswith("[自动生成失败]")]
        if not collected:
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="text",
                data=f"[摘要] 关于{topic}的分析已完成，详见各章节内容。",
                metadata={"stub": True, "filtered_failed_narratives": True},
            )

        combined = "\n---\n".join(collected)

        try:
            from backend.config import get_settings
            from langchain_openai import ChatOpenAI

            settings = get_settings()
            llm = ChatOpenAI(
                base_url=settings.QWEN_API_BASE,
                api_key=settings.QWEN_API_KEY,
                model=settings.QWEN_MODEL,
                temperature=0.3,
                request_timeout=90,
                extra_body={"enable_thinking": False},
            )

            prompt = (
                f"基于以下分析结果，写一段简洁的总结摘要（200字以内，中文）：\n"
                f"主题：{topic}\n\n"
                f"分析内容：\n{combined[:3000]}\n\n"
                "要求：提炼核心发现和关键数据，语言简洁专业。"
            )

            response = await llm.ainvoke(prompt)
            raw = response.content if hasattr(response, "content") else str(response)
            summary = _strip_think_tags(raw)

            return SkillOutput(
                skill_id=self.skill_id,
                status="success",
                output_type="text",
                data=summary,
                metadata={"source_count": len(collected)},
            )

        except Exception as e:
            logger.warning("Summary generation via LLM failed: %s", e)
            return SkillOutput(
                skill_id=self.skill_id,
                status="partial",
                output_type="text",
                data=f"[摘要] {combined[:300]}",
                metadata={"fallback": True},
            )
