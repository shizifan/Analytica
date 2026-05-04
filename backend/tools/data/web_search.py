"""Web Search Skill — 通过 MCP 协议调用 HiAgent 搜索服务，返回结构化搜索结果。
"""
from __future__ import annotations

import asyncio
import logging
import time as _time
from typing import Any
from urllib.parse import urlparse

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tracing import make_span

logger = logging.getLogger("analytica.tools.web_search")

# ── DEPRECATED: _optimize_search_query ──
# Replaced by _search_query_planner.plan_search_queries (multi-angle query
# decomposition with layered context). Kept in-file until confirmed stable,
# then will be removed.

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


# DEPRECATED: replaced by _search_query_planner.plan_search_queries
async def _optimize_search_query(raw_query: str, domain_context: str = "") -> str:
    """用 LLM 将用户的分析需求提炼为搜索引擎关键词。

    若 LLM 调用失败或返回空结果，降级为原始 query。

    DEPRECATED: 由 _search_query_planner.plan_search_queries 替代，保留至确认稳定后删除。
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
        optimized = optimized.replace("\n", " ").replace('"', "").replace("'", "")
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


# ── 结果去重 ──────────────────────────────────────────────────


def _dedupe_by_url(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按 URL (host + path) 去重，保留首次出现的记录。"""
    seen: set[str] = set()
    deduped: list[dict[str, Any]] = []
    for r in results:
        url = r.get("url", "")
        key = _normalize_url_key(url)
        if key and key not in seen:
            seen.add(key)
            deduped.append(r)
    return deduped


def _normalize_url_key(url: str) -> str:
    """提取 host + path 作为去重 key。"""
    try:
        parsed = urlparse(url)
        return f"{parsed.netloc}{parsed.path}"
    except Exception:
        return url


# ── 搜索工具 ──────────────────────────────────────────────────


@register_tool("tool_web_search", ToolCategory.SEARCH, "互联网检索，返回结构化摘要",
                input_spec="搜索关键词 (query)",
                output_spec="搜索结果 JSON (query/total_results/results[])")
class WebSearchTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        query = inp.params.get("query", "")
        if not query:
            return self._fail("缺少 query 参数")

        # ── 提取搜索上下文字段 ──
        search_prefix = inp.params.get("__search_domain_prefix__", "")
        domain_scope = search_prefix.split()[0] if search_prefix else ""

        # 若 query 中缺少公司名 scope，先补上
        if domain_scope and domain_scope not in query:
            query = f"{domain_scope} {query}"

        task_id = inp.params.get("__task_id__", "unknown")

        # ── LLM 查询规划（替代旧 _optimize_search_query）──
        from backend.tools.data._search_query_planner import plan_search_queries

        raw_query = inp.params.get("__raw_query__", query)
        public_hint = inp.params.get("__search_public_hint__", "")
        task_purpose = inp.params.get("__task_intent__", "")

        # Emit planner-input span so it's visible in the trace what prompt was used
        if inp.span_emit:
            await inp.span_emit(make_span(
                "plan_step", f"{task_id}_query_plan", status="start",
                input={
                    "raw_query": raw_query,
                    "domain_context": domain_scope,
                    "public_hint": public_hint,
                    "task_purpose": task_purpose,
                },
            ))

        plan_result = await plan_search_queries(
            raw_query=raw_query,
            domain_context=domain_scope,
            public_hint=public_hint,
            task_purpose=task_purpose,
            span_emit=inp.span_emit if inp.span_emit else None,
            task_id=task_id,
        )

        queries: list[str] = plan_result.get("queries", [raw_query])
        rationale = plan_result.get("rationale", "")
        stop_when = plan_result.get("stop_when", "")
        planner_failed = "降级" in rationale

        # Emit planner-output span showing the resulting search queries
        if inp.span_emit:
            await inp.span_emit(make_span(
                "plan_step", f"{task_id}_query_plan", status="ok",
                input={
                    "raw_query": raw_query,
                    "domain_context": domain_scope,
                    "public_hint": public_hint,
                    "task_purpose": task_purpose,
                },
                output={
                    "queries": queries,
                    "rationale": rationale,
                    "stop_when": stop_when,
                },
            ))
        logger.info(
            "Search query planner produced %d queries for task %s: %s",
            len(queries), task_id, queries,
        )

        # ── 每条 query 补充 domain scope ──
        effective_queries: list[str] = []
        for q in queries:
            if domain_scope and domain_scope not in q:
                q = f"{domain_scope} {q}"
            effective_queries.append(q)

        # ── 多轮自适应搜索 ──
        MIN_HITS = 3
        MAX_ROUNDS = 3
        _start = _time.monotonic()

        from backend.config import get_settings
        from backend.tools.data._mcp_client import call_mcp_search
        from backend.tools.data._search_sanitizer import sanitize_query
        from backend.tools.data._search_cache import get_cached, set_cached
        from backend.tools._llm import extract_json, invoke_llm
        from backend.tools.data._search_query_planner import _get_planner_semaphore

        settings = get_settings()
        provider_timeout = getattr(settings, "SEARCH_PROVIDER_TIMEOUT", 60.0)

        # ── Per-query MCP call (shared across rounds) ──
        async def _search_one(q: str, idx: int) -> dict[str, Any]:
            sub_start = _time.monotonic()
            q = sanitize_query(q)
            cached = get_cached(q)
            if cached is not None:
                logger.info("Cache hit for query %d: %r", idx, q[:60])
                if inp.span_emit:
                    await inp.span_emit(make_span(
                        "api_call", f"{task_id}_q{idx}", status="ok",
                        input={"query": q, "idx": idx},
                        output={"total_results": len(cached), "latency_ms": 0, "note": "cache_hit"},
                    ))
                return {"ok": True, "result": {"results": cached, "total_results": len(cached), "search_time": "cached"}, "query": q}
            try:
                result = await call_mcp_search(q, timeout=provider_timeout)
                if "error" in result:
                    elapsed_ms = int((_time.monotonic() - sub_start) * 1000)
                    error_reason = result["error"]
                    logger.warning("MCP returned error for query %d (%r): %s", idx, q[:60], error_reason[:120])
                    if inp.span_emit:
                        await inp.span_emit(make_span("api_call", f"{task_id}_q{idx}", status="error",
                            input={"query": q, "idx": idx}, output={"error": error_reason[:200], "latency_ms": elapsed_ms}))
                    return {"ok": False, "reason": error_reason[:200], "query": q}
                elapsed_ms = int((_time.monotonic() - sub_start) * 1000)
                if inp.span_emit:
                    await inp.span_emit(make_span("api_call", f"{task_id}_q{idx}", status="ok",
                        input={"query": q, "idx": idx},
                        output={"total_results": result.get("total_results", 0), "latency_ms": elapsed_ms}))
                if "results" in result:
                    set_cached(q, result["results"])
                return {"ok": True, "result": result, "query": q}
            except asyncio.TimeoutError:
                if inp.span_emit:
                    await inp.span_emit(make_span("api_call", f"{task_id}_q{idx}", status="error", output={"error": "timeout", "query": q}))
                return {"ok": False, "reason": "timeout", "query": q}
            except Exception as e:
                logger.warning("Search query %d (%r) failed: %s", idx, q[:60], e)
                if inp.span_emit:
                    await inp.span_emit(make_span("api_call", f"{task_id}_q{idx}", status="error", output={"error": str(e)[:200], "query": q}))
                return {"ok": False, "reason": str(e)[:200], "query": q}

        # ── Round loop ──
        round_queries = list(effective_queries)
        all_results: list[dict] = []
        queries_used: list[str] = []
        has_any_success = False
        errors: list[str] = []
        round_count = 0
        previous_snippets: list[str] = []

        for round_num in range(1, MAX_ROUNDS + 1):
            round_count = round_num
            search_results = await asyncio.gather(
                *(_search_one(q, i) for i, q in enumerate(round_queries)),
                return_exceptions=False,
            )
            for sr in search_results:
                if sr["ok"]:
                    has_any_success = True
                    queries_used.append(sr["query"])
                    hits = sr["result"].get("results", [])
                    all_results.extend(hits)
                else:
                    errors.append(f"{sr['query'][:40]}: {sr['reason']}")

            deduped = _dedupe_by_url(all_results)
            logger.info("Round %d: %d raw results, %d deduped", round_num, len(all_results), len(deduped))

            # Early stop: enough hits
            if len(deduped) >= MIN_HITS:
                break

            # Prepare next round's queries
            if round_num >= MAX_ROUNDS:
                break

            if round_num == 1 and has_any_success:
                # Round 2: LLM supplementary queries using round 1 snippets
                snippets = []
                for r in all_results[-30:]:  # last 30 raw hits as context
                    title = r.get("title", "")
                    snippet = r.get("snippet", "") or r.get("content", "")
                    if title or snippet:
                        snippets.append(f"标题：{title}\n摘要：{snippet[:200]}")
                snippet_text = "\n\n".join(snippets[:10]) or "（无有效摘要）"

                supp_prompt = (
                    "基于第一轮搜索结果的标题和摘要，产出 1~2 条补充检索词，填补信息缺口。\n\n"
                    f"第一轮已获取的信息（标题+摘要）：\n{snippet_text}\n\n"
                    "【输出要求】\n"
                    "- 产出 1~2 条补充检索词，每条 ≤ 12 字/词，名词短语优先\n"
                    "- 优先检索第一轮未覆盖的角度（政策 / 数据 / 趋势 / 对比）\n"
                    '- 输出纯 JSON：{"queries": [...], "rationale": "..."}\n'
                )
                try:
                    supp_result = await invoke_llm(
                        supp_prompt,
                        system_prompt="你是互联网搜索规划专家，负责产出补充检索词。只输出纯 JSON。",
                        temperature=getattr(settings, "LLM_TEMPERATURE_BALANCED", 0.2),
                        timeout=20,
                        max_prompt_chars=3000,
                        span_emit=inp.span_emit if inp.span_emit else None,
                        task_id=f"{task_id}_supp",
                        _semaphore=_get_planner_semaphore(),
                    )
                    if not supp_result.get("error"):
                        parsed = extract_json(supp_result.get("text", ""))
                        if parsed and isinstance(parsed.get("queries"), list) and parsed["queries"]:
                            round_queries = []
                            for sq in parsed["queries"]:
                                sq = str(sq).strip()
                                if sq and domain_scope and domain_scope not in sq:
                                    sq = f"{domain_scope} {sq}"
                                if sq:
                                    round_queries.append(sq)
                            logger.info("Round 2 supplementary queries: %s", round_queries)
                            if round_queries:
                                continue
                except Exception:
                    logger.warning("Supplementary query LLM failed, falling back to relaxation")

            if round_num == 2:
                # Round 3: deterministic query relaxation
                relaxed: list[str] = []
                for q in effective_queries:
                    import re as _relax_re
                    broad = _relax_re.sub(r'\b20\d{2}年?\b', '', q)
                    broad = _relax_re.sub(r'[（(].*?[）)]', '', broad)
                    broad = broad.strip()
                    if broad and broad != q:
                        relaxed.append(broad)
                if relaxed:
                    round_queries = relaxed[:2]
                    logger.info("Round 3 relaxed queries: %s", round_queries)
                else:
                    break  # no relaxation possible
            else:
                break  # no more round strategies

        deduped_results = _dedupe_by_url(all_results)
        total_latency_ms = int((_time.monotonic() - _start) * 1000)

        # ── 结果合成（LLM 摘要，带引用编号）──
        synthesized_summary = ""
        citations: list[dict] = []
        if deduped_results:
            try:
                items_text_parts: list[str] = []
                for i, r in enumerate(deduped_results[:15], start=1):
                    title = r.get("title", "")
                    snippet = r.get("snippet", "") or r.get("content", "") or ""
                    url = r.get("url", "")
                    items_text_parts.append(
                        f"[{i}] 标题：{title}\n   摘要：{snippet[:300]}\n   URL：{url}"
                    )
                results_text = "\n".join(items_text_parts)

                synth_prompt = (
                    "根据以下互联网搜索结果，用一段话（≤ 300 字）总结与"
                    f"\"{task_purpose or query}\"相关的行业背景和关键信息。\n\n"
                    f"搜索结果（编号对应 citations）：\n{results_text}\n\n"
                    "要求：\n"
                    "1. 每个关键事实必须标注信息来源编号，格式：[1]、[2] 等\n"
                    "2. 无确切依据的内容不要写\n"
                    "3. 不需要罗列所有结果，聚焦最重要的 3-5 个信息点\n\n"
                    '输出纯 JSON（不要 markdown 包裹）：\n'
                    '{"summary": "一段话总结，含编号引用 [1][2]...",'
                    ' "citations": [{"id": 1, "title": "...", "url": "..."}]}'
                )
                synth_result = await invoke_llm(
                    synth_prompt,
                    system_prompt="你是数据分析师辅助，负责根据搜索结果撰写简洁的行业背景摘要。只输出纯 JSON。",
                    temperature=getattr(settings, "LLM_TEMPERATURE_BALANCED", 0.2),
                    timeout=30,
                    max_prompt_chars=4000,
                    span_emit=inp.span_emit if inp.span_emit else None,
                    task_id=f"{task_id}_synth",
                    _semaphore=_get_planner_semaphore(),
                )
                if not synth_result.get("error"):
                    parsed = extract_json(synth_result.get("text", ""))
                    if parsed:
                        synthesized_summary = str(parsed.get("summary", ""))
                        raw_citations = parsed.get("citations", [])
                        if isinstance(raw_citations, list):
                            citations = [
                                {"id": c.get("id", i+1), "title": c.get("title", ""), "url": c.get("url", "")}
                                for i, c in enumerate(raw_citations) if isinstance(c, dict)
                            ]
                        logger.info("Synthesis produced summary (%d chars) with %d citations",
                                    len(synthesized_summary), len(citations))
            except Exception:
                logger.warning("Result synthesis LLM call failed, returning raw results")

        # ── 输出 ──
        if not deduped_results:
            # 部分成功或无结果 — 提供结构化 empty_reason 供下游决策
            if planner_failed:
                empty_reason = "planner_failed"
            elif not has_any_success:
                empty_reason = "all_mcp_errors"
            else:
                empty_reason = "mcp_returned_empty"
            status = "partial" if has_any_success else "failed"
            return ToolOutput(
                tool_id=self.tool_id,
                status=status,
                output_type="json",
                data={
                    "query": query,
                    "queries_used": queries_used,
                    "total_results": 0,
                    "results": [],
                    "rationale": rationale,
                    "stop_when": stop_when,
                    "empty_reason": empty_reason,
                    "rounds": round_count,
                    "synthesized_summary": "",
                    "citations": [],
                },
                metadata={
                    "query": query,
                    "queries_used": queries_used,
                    "total_results": 0,
                    "latency_ms": total_latency_ms,
                    "note": "所有查询均未找到结果" if errors else "未找到相关结果",
                    "empty_reason": empty_reason,
                    "rounds": round_count,
                    "errors": errors if errors else None,
                },
            )

        return ToolOutput(
            tool_id=self.tool_id,
            status="success",
            output_type="json",
            data={
                "query": query,
                "queries_used": queries_used,
                "search_time": "",
                "total_results": len(deduped_results),
                "results": deduped_results,
                "rationale": rationale,
                "stop_when": stop_when,
                "rounds": round_count,
                "synthesized_summary": synthesized_summary,
                "citations": citations,
            },
            metadata={
                "query": query,
                "queries_used": queries_used,
                "total_results": len(deduped_results),
                "latency_ms": total_latency_ms,
                "rounds": round_count,
                "errors": errors if errors else None,
            },
        )
