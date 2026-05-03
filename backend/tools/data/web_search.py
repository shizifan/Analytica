"""Web Search Skill — 通过 MCP 协议调用 HiAgent 搜索服务，返回结构化搜索结果。
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tracing import make_span

logger = logging.getLogger("analytica.tools.web_search")

# ── 搜索查询优化 ─────────────────────────────────────────────

_SEARCH_OPTIMIZER_SYSTEM = """\
你是一个搜索查询优化器。将用户的数据分析需求浓缩为 2-4 个最核心的搜索关键词。

规则：
1. 只保留 2-4 个关键词，空格分隔，宁少勿多
2. 去掉所有分析词、图表词、格式词（分析、对比、折线图、表格、前N名 等）
3. 去掉可由主关键词自然覆盖的次要指标（如"集装箱吞吐量 目标完成率 月度"中，保留"集装箱吞吐量"即可）
4. 去掉可由公司名覆盖的冗余限定（如"辽港集团 大连港"中，保留"辽港集团"即可）
5. 时间段仅保留年份，去掉月份
6. 只输出关键词，不输出任何其他内容

示例：
输入：辽港集团 2026年集装箱吞吐量目标完成率月度趋势，当年与上年对比，以折线图展示
输出：辽港集团 2026 集装箱吞吐量

输入：辽港集团 战略客户总数，贡献占比前10名，以表格列出
输出：辽港集团 战略客户 贡献

输入：辽港集团 大连港3月吞吐量对比去年同期，生成柱状图
输出：辽港集团 2026 吞吐量"""

_SEARCH_OPTIMIZER_USER = (
    "领域上下文：{domain}\n"
    "分析需求：{raw}"
)

_OPTIMIZER_TIMEOUT = 10.0  # 快速优化，不宜过慢


async def _optimize_search_query(raw_query: str, domain_context: str = "") -> str:
    """用 LLM 将用户的分析需求提炼为搜索引擎关键词。

    若 LLM 调用失败或返回空结果，降级为原始 query。
    """
    from backend.agent.graph import build_llm
    from langchain_core.messages import SystemMessage, HumanMessage

    user_prompt = _SEARCH_OPTIMIZER_USER.format(
        domain=domain_context or "无",
        raw=raw_query,
    )

    try:
        llm = build_llm("qwen3-235b", request_timeout=15)
        response = await llm.ainvoke(
            [SystemMessage(content=_SEARCH_OPTIMIZER_SYSTEM),
             HumanMessage(content=user_prompt)],
        )
        optimized = (response.content or "").strip()
        # 过滤掉 LLM 可能输出的引号、换行等
        optimized = optimized.replace("\n", " ").replace('"', "").replace("'", "")
        # 合理长度检查
        if not optimized or len(optimized) > 100:
            logger.debug(
                "Query optimizer returned invalid result (len=%d), falling back: %r",
                len(optimized) if optimized else 0, raw_query[:60],
            )
            return raw_query
        logger.debug("Query optimized: %r → %r", raw_query[:80], optimized)
        return optimized
    except Exception:
        logger.warning("Query optimization failed, using raw query: %r", raw_query[:80])
        return raw_query


@register_tool("tool_web_search", ToolCategory.SEARCH, "互联网检索，返回结构化摘要",
                input_spec="搜索关键词 (query)",
                output_spec="搜索结果 JSON (query/total_results/results[])")
class WebSearchTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        query = inp.params.get("query", "")
        if not query:
            return self._fail("缺少 query 参数")

        # ── 搜索领域上下文增强 + LLM 查询优化 ──
        search_prefix = inp.params.get("__search_domain_prefix__", "")
        domain_scope = search_prefix.split()[0] if search_prefix else ""

        # Layer 2: 若 query 中缺少公司名 scope，先补上
        if domain_scope and domain_scope not in query:
            query = f"{domain_scope} {query}"

        # LLM 优化：将分析需求（如"分析2026年计划外资本项目清单及金额，以表格列出"）
        # 提炼为搜索关键词（如"辽港集团 2026年 资本项目 计划外"）
        raw_before = query
        query = await _optimize_search_query(query, domain_context=domain_scope)
        if query != raw_before:
            logger.info("Search query optimized: %r → %r", raw_before[:100], query[:100])

        task_id = inp.params.get("__task_id__", "unknown")
        _start = _time.monotonic()

        # ── 发出搜索调用开始 span ──
        if inp.span_emit:
            await inp.span_emit(make_span(
                "api_call", task_id, status="start",
                input={"query": query, "service": "HiAgent-MCP-Server"},
            ))

        try:
            from backend.tools.data._mcp_client import call_mcp_search

            result = await call_mcp_search(query, timeout=60.0)
            latency_ms = int((_time.monotonic() - _start) * 1000)

            if "error" in result:
                if inp.span_emit:
                    await inp.span_emit(make_span(
                        "api_call", task_id, status="error",
                        output={"error": result["error"], "latency_ms": latency_ms},
                    ))
                return self._fail(result["error"])

            total = result.get("total_results", len(result.get("results", [])))
            results_list = result.get("results", [])

            if inp.span_emit:
                await inp.span_emit(make_span(
                    "api_call", task_id, status="ok",
                    output={"total_results": total, "latency_ms": latency_ms},
                ))

            if not results_list:
                return ToolOutput(
                    tool_id=self.tool_id,
                    status="partial",
                    output_type="json",
                    data={
                        "query": query,
                        "total_results": 0,
                        "results": [],
                    },
                    metadata={
                        "query": query,
                        "total_results": 0,
                        "note": "未找到相关结果",
                    },
                )

            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="json",
                data={
                    "query": result.get("query", query),
                    "search_time": result.get("search_time", ""),
                    "total_results": total,
                    "results": results_list,
                },
                metadata={
                    "query": result.get("query", query),
                    "total_results": total,
                },
            )

        except asyncio.TimeoutError:
            if inp.span_emit:
                await inp.span_emit(make_span(
                    "api_call", task_id, status="error",
                    output={"error": "timeout"},
                ))
            return self._fail("搜索请求超时，请稍后重试")
        except Exception as e:
            logger.exception("WebSearchTool execute error: %s", e)
            if inp.span_emit:
                await inp.span_emit(make_span(
                    "api_call", task_id, status="error",
                    output={"error": str(e)[:200]},
                ))
            return self._fail(f"搜索执行异常: {str(e)[:300]}")
