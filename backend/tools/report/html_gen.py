"""HTML Report Generation Skill — Step 6 (outline pipeline).

Two execution modes share the same outline:
- ``llm_agent``: agent calls the renderer's emit tools one block at a time
- ``deterministic``: ``render_outline`` walks the outline directly

Both produce structurally equivalent output (guarded by Step 0 baseline);
the agent path is the default per ``REPORT_AGENT_ENABLED`` and falls
back to deterministic on any failure.
"""
from __future__ import annotations

import logging
from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._renderers.html import HtmlBlockRenderer
from backend.tools.report._theme import get_theme

logger = logging.getLogger("analytica.tools.report_html")


@register_tool("tool_report_html", ToolCategory.REPORT, "HTML 报告生成（单页 HTML 文件）",
                input_spec="report_metadata + report_structure + 上游数据/图表引用",
                output_spec="HTML 文件路径")
class HtmlReportTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        try:
            outline = await plan_outline(
                inp.params, context,
                task_order=inp.params.get("_task_order"),
                intent=inp.params.get("intent", ""),
                task_id=inp.params.get("__task_id__", ""),
                span_emit=inp.span_emit,
            )

            from backend.config import get_settings

            theme = get_theme(
                (inp.params.get("report_metadata") or {}).get("theme"),
            )
            renderer = HtmlBlockRenderer(theme=theme)
            mode = "deterministic"

            if get_settings().REPORT_AGENT_ENABLED:
                try:
                    mode = await _run_html_agent(renderer, outline)
                except Exception as agent_err:
                    logger.warning(
                        "HTML agent loop failed (%s); falling back to deterministic",
                        agent_err,
                    )
                    mode = "deterministic_fallback_error"

                if mode != "llm_agent":
                    renderer = HtmlBlockRenderer(theme=theme)
                    render_outline(outline, renderer)
            else:
                render_outline(outline, renderer)

            html = renderer.end_document()

            meta: dict[str, Any] = {
                "format": "html",
                "title": outline.metadata.get("title", ""),
                "chart_count": renderer.chart_count,
                "mode": mode,
            }
            if outline.degradations:
                meta["degradations"] = outline.degradations
            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="file",
                data=html,
                metadata=meta,
            )

        except Exception as e:
            logger.exception("HTML generation failed: %s", e)
            return self._fail(str(e))


async def _run_html_agent(renderer: HtmlBlockRenderer, outline) -> str:
    """Drive the HTML renderer through the LLM agent loop.

    Returns ``"llm_agent"`` on success; ``"deterministic_fallback"`` if
    the agent did not finalise. Caller resets renderer before re-render.
    """
    from langchain_openai import ChatOpenAI

    from backend.config import get_settings
    from backend.tools.report._agent_loop import (
        run_report_agent,
        serialize_outline,
    )
    from backend.tools.report._html_tools import (
        HTML_OUTLINE_SYSTEM_PROMPT,
        make_html_outline_tools,
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

    tools = make_html_outline_tools(renderer, outline)
    user_message = serialize_outline(outline)
    success = await run_report_agent(
        llm, tools, HTML_OUTLINE_SYSTEM_PROMPT, user_message,
    )

    if success:
        return "llm_agent"
    logger.warning("HTML agent did not finalise; falling back to deterministic")
    return "deterministic_fallback"
