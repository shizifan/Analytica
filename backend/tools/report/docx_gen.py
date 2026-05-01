"""DOCX Report Generation Skill — outline pipeline + LLM agent loop.

The agent walks the outline by calling the renderer's emit tools one
block at a time. There is no deterministic fallback: agent failures
propagate so the caller sees the actual cause instead of a silently
re-rendered output that hides whatever went wrong.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._renderers.docx import DocxBlockRenderer
from backend.tools.report._theme import get_theme

logger = logging.getLogger("analytica.tools.report_docx")


@register_tool("tool_report_docx", ToolCategory.REPORT, "Word 报告生成（.docx 文件）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="DOCX 文件路径")
class DocxReportTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        try:
            outline = await plan_outline(
                inp.params, context,
                task_order=inp.params.get("_task_order"),
                intent=inp.params.get("intent", ""),
                task_id=inp.params.get("__task_id__", ""),
                span_emit=inp.span_emit,
            )

            theme = get_theme(
                (inp.params.get("report_metadata") or {}).get("theme"),
            )
            renderer = DocxBlockRenderer(theme=theme)
            await _run_docx_agent(renderer, outline)
            docx_bytes = renderer.end_document()

            meta: dict[str, Any] = {
                "format": "docx",
                "title": outline.metadata.get("title", ""),
                "file_size_bytes": len(docx_bytes),
                "mode": "llm_agent",
            }
            if outline.degradations:
                meta["degradations"] = outline.degradations
            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="file",
                data=docx_bytes,
                metadata=meta,
            )

        except Exception as e:
            logger.exception("DOCX generation failed: %s", e)
            return self._fail(str(e))


async def _run_docx_agent(renderer: DocxBlockRenderer, outline) -> None:
    """Drive the DOCX renderer through the LLM agent loop.

    Raises ``RuntimeError`` if the agent did not finalise — the caller
    surfaces this as a tool failure rather than retry with a degraded
    output silently.
    """
    from langchain_openai import ChatOpenAI

    from backend.config import get_settings
    from backend.tools.report._agent_loop import (
        run_report_agent,
        serialize_outline,
    )
    from backend.tools.report._docx_tools import (
        DOCX_OUTLINE_SYSTEM_PROMPT,
        make_docx_outline_tools,
    )

    settings = get_settings()
    llm = ChatOpenAI(
        base_url=settings.QWEN_API_BASE,
        api_key=settings.QWEN_API_KEY,
        model=settings.QWEN_MODEL,
        temperature=settings.LLM_TEMPERATURE_BALANCED,
        request_timeout=90,
        extra_body={"enable_thinking": False},
    )

    tools = make_docx_outline_tools(renderer, outline)
    user_message = serialize_outline(outline)
    success = await run_report_agent(
        llm, tools, DOCX_OUTLINE_SYSTEM_PROMPT, user_message,
    )
    if not success:
        raise RuntimeError("DOCX agent did not finalise")
