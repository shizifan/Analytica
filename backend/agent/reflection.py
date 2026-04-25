"""Reflection Node — 反思层核心。

在每次完整分析完成后自动触发，通过两次并行 LLM 调用提取：
- 调用 A：用户偏好 + 分析模板 + 槽位质量评审
- 调用 B：技能表现反馈

结果格式化为 Markdown 反思卡片，等待用户确认后持久化到记忆系统。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Optional

logger = logging.getLogger("analytica.reflection")


# ── LLM Prompt Templates ────────────────────────────────────

REFLECTION_PROMPT_A = """你是一个数据分析反思专家。根据本次分析的完整过程，提取用户偏好、可复用的分析模板和槽位填充质量评审。

【本次分析对话摘要】
{conversation_summary}

【Slot 填充历史】
{slot_history}

【执行任务列表】
{task_list}

【分析结果概要】
{execution_summary}

【任务】
1. 提取本次分析中明确体现的用户偏好（只提取有依据的，不推测）
2. 判断本次分析流程是否有通用复用价值，如有则生成分析模板骨架
3. 评审槽位填充质量：哪些自动填充正确、哪些被用户纠正

【重要约束】
- 只提取本次分析中明确体现的偏好，不要推测用户未表达的偏好
- 低价值分析（simple_table + 单任务、被降级的查询、数据不足提前终止、用户取消）不应生成偏好
- analysis_template 仅在分析流程有通用复用价值时生成（≥3个任务，非简单查询）
- 无纠正时 slots_corrected 为空列表
- domain_terms 无映射时为空字典

【输出格式】（严格 JSON，无 markdown 包裹，无 <think> 块）
{{
  "user_preferences": {{
    "output_format": "<pptx|docx|html|null>",
    "time_granularity": "<daily|monthly|quarterly|yearly|null>",
    "chart_types": ["<line|bar|waterfall|...>"],
    "analysis_depth": {{"attribution": <bool>, "predictive": <bool>}},
    "domain_terms": {{}}
  }},
  "analysis_template": {{
    "template_name": "<模板名称>",
    "applicable_scenario": "<适用场景描述>",
    "plan_skeleton": {{"tasks": [...]}}
  }} | null,
  "slot_quality_review": {{
    "slots_auto_filled_correctly": ["<slot_name>", ...],
    "slots_corrected": ["<slot_name>", ...],
    "slots_corrected_detail": {{
      "<slot_name>": {{"from": "<原值>", "to": "<纠正值>"}}
    }}
  }}
}}
"""

REFLECTION_PROMPT_B = """你是一个数据分析技能评审专家。根据本次分析中各任务的执行情况，给出技能表现反馈。

【任务执行状态】
{task_statuses}

【执行上下文摘要】
{execution_context_summary}

【任务】
评估各技能在本次分析中的表现：
1. 哪些技能表现良好（数据准确、执行快速）
2. 哪些技能存在问题（数据不完整、执行超时、结果质量低）
3. 改进建议

【输出格式】（严格 JSON，无 markdown 包裹，无 <think> 块）
{{
  "tool_feedback": {{
    "well_performed": ["<tool_id>", ...],
    "issues_found": [{{"tool": "<tool_id>", "issue": "<问题描述>"}}],
    "suggestions": ["<改进建议>"]
  }}
}}
"""


def _strip_think_tags(text: str) -> str:
    """Remove Qwen3's <think>...</think> reasoning blocks."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines)
    return text.strip()


def _extract_json(raw: str) -> Optional[dict]:
    """Extract JSON from LLM output, handling think tags and markdown fences."""
    cleaned = _strip_think_tags(raw)
    cleaned = _strip_markdown_fences(cleaned)
    # Try direct parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    # Try to find JSON object
    idx = cleaned.find("{")
    if idx >= 0:
        # Find matching closing brace
        depth = 0
        for i in range(idx, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[idx : i + 1])
                    except json.JSONDecodeError:
                        break
    return None


def _build_conversation_summary(state: dict) -> str:
    """Build a conversation summary from messages."""
    messages = state.get("messages", [])
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown")
        content = msg.get("content", "")
        if content and role in ("user", "assistant"):
            # Truncate long messages
            if len(content) > 300:
                content = content[:300] + "..."
            lines.append(f"{role}: {content}")
    return "\n".join(lines[-20:])  # Last 20 messages


def _build_slot_history(state: dict) -> str:
    """Build slot history summary."""
    slots = state.get("slots", {})
    if not slots:
        return "（无槽位数据）"
    lines = []
    for name, sv in slots.items():
        if isinstance(sv, dict):
            val = sv.get("value")
            src = sv.get("source", "unknown")
            confirmed = sv.get("confirmed", False)
        else:
            val = getattr(sv, "value", None)
            src = getattr(sv, "source", "unknown")
            confirmed = getattr(sv, "confirmed", False)
        if val is not None:
            lines.append(f"- {name}: {val} (source={src}, confirmed={confirmed})")
    return "\n".join(lines) if lines else "（无已填充槽位）"


def _build_task_list(state: dict) -> str:
    """Build task list summary from analysis plan."""
    plan = state.get("analysis_plan", {})
    if not plan:
        return "（无分析方案）"
    tasks = plan.get("tasks", [])
    lines = []
    for t in tasks:
        if isinstance(t, dict):
            tid = t.get("task_id", "?")
            name = t.get("name", "")
            tool = t.get("tool", "")
            ttype = t.get("type", "")
        else:
            tid = getattr(t, "task_id", "?")
            name = getattr(t, "name", "")
            tool = getattr(t, "tool", "")
            ttype = getattr(t, "type", "")
        lines.append(f"- {tid}: {name} (tool={tool}, type={ttype})")
    return "\n".join(lines) if lines else "（无任务）"


def _build_execution_summary(state: dict) -> str:
    """Build execution results summary."""
    task_statuses = state.get("task_statuses", {})
    if not task_statuses:
        return "（无执行结果）"
    lines = []
    for tid, status in task_statuses.items():
        lines.append(f"- {tid}: {status}")
    return "\n".join(lines)


def _build_task_statuses_json(state: dict) -> str:
    """Build task statuses JSON for prompt B."""
    task_statuses = state.get("task_statuses", {})
    plan = state.get("analysis_plan", {})
    tasks = plan.get("tasks", [])

    status_list = []
    for t in tasks:
        if isinstance(t, dict):
            tid = t.get("task_id", "?")
            tool = t.get("tool", "")
            est = t.get("estimated_seconds", 0)
        else:
            tid = getattr(t, "task_id", "?")
            tool = getattr(t, "tool", "")
            est = getattr(t, "estimated_seconds", 0)
        status_list.append({
            "task_id": tid,
            "tool": tool,
            "status": task_statuses.get(tid, "unknown"),
            "estimated_seconds": est,
        })
    return json.dumps(status_list, ensure_ascii=False, indent=2)


def _build_execution_context_summary(state: dict) -> str:
    """Build execution context summary for prompt B."""
    ctx = state.get("execution_context", {})
    if not ctx:
        return "（无执行上下文）"
    # Summarize: list keys and types/sizes
    lines = []
    for key, val in ctx.items():
        if hasattr(val, "shape"):
            lines.append(f"- {key}: DataFrame {val.shape}")
        elif isinstance(val, dict):
            lines.append(f"- {key}: dict ({len(val)} keys)")
        elif isinstance(val, list):
            lines.append(f"- {key}: list ({len(val)} items)")
        elif isinstance(val, str) and len(val) > 200:
            lines.append(f"- {key}: str ({len(val)} chars)")
        else:
            lines.append(f"- {key}: {type(val).__name__}")
    return "\n".join(lines) if lines else "（执行上下文为空）"


async def call_llm_a(llm: Any, state: dict, max_retries: int = 2) -> Optional[dict]:
    """Call LLM for preference + template extraction (Call A).

    Retries on invalid JSON up to max_retries times.
    """
    prompt = REFLECTION_PROMPT_A.format(
        conversation_summary=_build_conversation_summary(state),
        slot_history=_build_slot_history(state),
        task_list=_build_task_list(state),
        execution_summary=_build_execution_summary(state),
    )

    for attempt in range(max_retries):
        try:
            if callable(llm) and not hasattr(llm, "ainvoke"):
                raw = await llm(prompt)
                raw = str(raw)
            else:
                response = await llm.ainvoke(prompt)
                raw = response.content if hasattr(response, "content") else str(response)

            parsed = _extract_json(raw)
            if parsed is not None:
                return parsed
            logger.warning(
                "Reflection LLM-A returned invalid JSON (attempt %d/%d)",
                attempt + 1, max_retries,
            )
        except Exception as e:
            logger.warning(
                "Reflection LLM-A error (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)

    return None


async def call_llm_b(llm: Any, state: dict, max_retries: int = 2) -> Optional[dict]:
    """Call LLM for tool feedback extraction (Call B).

    Retries on invalid JSON up to max_retries times.
    """
    prompt = REFLECTION_PROMPT_B.format(
        task_statuses=_build_task_statuses_json(state),
        execution_context_summary=_build_execution_context_summary(state),
    )

    for attempt in range(max_retries):
        try:
            if callable(llm) and not hasattr(llm, "ainvoke"):
                raw = await llm(prompt)
                raw = str(raw)
            else:
                response = await llm.ainvoke(prompt)
                raw = response.content if hasattr(response, "content") else str(response)

            parsed = _extract_json(raw)
            if parsed is not None:
                return parsed
            logger.warning(
                "Reflection LLM-B returned invalid JSON (attempt %d/%d)",
                attempt + 1, max_retries,
            )
        except Exception as e:
            logger.warning(
                "Reflection LLM-B error (attempt %d/%d): %s",
                attempt + 1, max_retries, e,
            )
            if attempt < max_retries - 1:
                await asyncio.sleep(0.5)

    return None


def format_reflection_card(reflection_summary: dict) -> str:
    """Format reflection summary as a Markdown card for user display."""
    lines = ["**本次分析总结**", ""]

    # User preferences section
    prefs = reflection_summary.get("user_preferences", {})
    if prefs:
        lines.append("**发现的偏好：**")
        pref_labels = {
            "output_format": "输出格式",
            "time_granularity": "时间粒度",
            "chart_types": "图表偏好",
            "analysis_depth": "分析深度",
            "domain_terms": "业务术语",
        }
        for key, label in pref_labels.items():
            val = prefs.get(key)
            if val is not None and val != {} and val != []:
                if isinstance(val, list):
                    val_str = "、".join(str(v) for v in val)
                elif isinstance(val, dict):
                    if key == "analysis_depth":
                        parts = []
                        if val.get("attribution"):
                            parts.append("归因分析")
                        if val.get("predictive"):
                            parts.append("预测分析")
                        val_str = "、".join(parts) if parts else "无"
                    else:
                        val_str = json.dumps(val, ensure_ascii=False)
                else:
                    val_str = str(val)
                lines.append(f"- {label}：{val_str}")
        lines.append("")
    else:
        lines.append("**偏好提取：** 本次分析未发现明确偏好")
        lines.append("")

    # Check for degraded LLM-A
    if reflection_summary.get("_llm_a_failed"):
        lines.append("**偏好提取：** 偏好提取暂时不可用")
        lines.append("")

    # Analysis template section
    template = reflection_summary.get("analysis_template")
    if template:
        name = template.get("template_name", "未命名模板")
        scenario = template.get("applicable_scenario", "")
        lines.append(f"**可保存模板：**")
        lines.append(f"「{name}」— {scenario}")
        lines.append("")

    # Check for degraded LLM-B
    if reflection_summary.get("_llm_b_failed"):
        lines.append("**技能反馈：** 技能评审暂时不可用")
        lines.append("")

    # Tool feedback section
    feedback = reflection_summary.get("tool_feedback", {})
    if feedback:
        lines.append("**本次 AI 质量反馈：**")
        well = feedback.get("well_performed", [])
        for s in well:
            lines.append(f"- OK {s}：表现良好")
        issues = feedback.get("issues_found", [])
        for item in issues:
            if isinstance(item, dict):
                lines.append(f"- WARN {item.get('tool', '?')}：{item.get('issue', '')}")
            else:
                lines.append(f"- WARN {item}")
        suggestions = feedback.get("suggestions", [])
        if suggestions:
            for s in suggestions:
                lines.append(f"- TIP {s}")
        lines.append("")

    # Slot quality section
    slot_review = reflection_summary.get("slot_quality_review", {})
    corrected = slot_review.get("slots_corrected", [])
    if corrected:
        lines.append("**槽位纠正记录：**")
        detail = slot_review.get("slots_corrected_detail", {})
        for s in corrected:
            d = detail.get(s, {})
            if d:
                lines.append(f"- {s}: {d.get('from', '?')} -> {d.get('to', '?')}")
            else:
                lines.append(f"- {s}: 已纠正")
        lines.append("")

    # Action buttons
    lines.extend([
        "---",
        "[全部保存] [选择保存] [忽略本次]",
    ])

    return "\n".join(lines)


async def reflection_node(state: dict) -> dict:
    """LangGraph reflection node.

    Two parallel LLM calls:
    - Call A: preferences + templates + slot quality review
    - Call B: tool feedback

    Results are merged into reflection_summary and formatted as a
    Markdown reflection card. The node then pauses for user confirmation
    (Human-in-the-Loop via POST /api/sessions/{id}/reflection/save).
    """
    state["current_phase"] = "reflection"

    # Initialize LLM
    try:
        from backend.config import get_settings
        from langchain_openai import ChatOpenAI

        settings = get_settings()
        llm = ChatOpenAI(
            base_url=settings.QWEN_API_BASE,
            api_key=settings.QWEN_API_KEY,
            model=settings.QWEN_MODEL,
            temperature=0.1,
            request_timeout=90,
            extra_body={"enable_thinking": False},
        )
    except Exception as e:
        logger.error("Failed to initialize reflection LLM: %s", e)
        # Complete degradation: skip reflection entirely
        state["reflection_summary"] = {
            "user_preferences": {},
            "analysis_template": None,
            "slot_quality_review": {
                "slots_auto_filled_correctly": [],
                "slots_corrected": [],
                "slots_corrected_detail": {},
            },
            "tool_feedback": {},
            "_llm_a_failed": True,
            "_llm_b_failed": True,
        }
        card = format_reflection_card(state["reflection_summary"])
        state["messages"].append({
            "role": "assistant",
            "type": "reflection_card",
            "content": card,
        })
        return state

    # Parallel LLM calls with graceful degradation
    result_a, result_b = await asyncio.gather(
        call_llm_a(llm, state),
        call_llm_b(llm, state),
        return_exceptions=True,
    )

    # Handle exceptions from gather
    if isinstance(result_a, Exception):
        logger.warning("Reflection LLM-A raised exception: %s", result_a)
        result_a = None
    if isinstance(result_b, Exception):
        logger.warning("Reflection LLM-B raised exception: %s", result_b)
        result_b = None

    # Build reflection summary with graceful degradation
    reflection_summary: dict[str, Any] = {}

    if result_a is not None:
        reflection_summary["user_preferences"] = result_a.get("user_preferences", {})
        reflection_summary["analysis_template"] = result_a.get("analysis_template")
        reflection_summary["slot_quality_review"] = result_a.get("slot_quality_review", {
            "slots_auto_filled_correctly": [],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        })
    else:
        reflection_summary["user_preferences"] = {}
        reflection_summary["analysis_template"] = None
        reflection_summary["slot_quality_review"] = {
            "slots_auto_filled_correctly": [],
            "slots_corrected": [],
            "slots_corrected_detail": {},
        }
        reflection_summary["_llm_a_failed"] = True

    if result_b is not None:
        reflection_summary["tool_feedback"] = result_b.get("tool_feedback", {})
    else:
        reflection_summary["tool_feedback"] = {}
        reflection_summary["_llm_b_failed"] = True

    state["reflection_summary"] = reflection_summary

    # Format reflection card
    card = format_reflection_card(reflection_summary)
    state["messages"].append({
        "role": "assistant",
        "type": "reflection_card",
        "content": card,
    })

    return state


async def save_reflection(
    session_id: str,
    reflection_summary: dict,
    save_preferences: bool = True,
    save_template: bool = True,
    save_tool_notes: bool = True,
    user_id: str | None = None,
    db_session: Any = None,
) -> dict[str, Any]:
    """Persist reflection results to memory store.

    Called by POST /api/sessions/{id}/reflection/save after user confirmation.
    """
    from backend.memory.store import MemoryStore

    if db_session is None:
        from backend.database import get_session_factory
        factory = get_session_factory()
        async with factory() as session:
            return await _do_save(
                session, session_id, reflection_summary,
                save_preferences, save_template, save_tool_notes, user_id,
            )
    else:
        return await _do_save(
            db_session, session_id, reflection_summary,
            save_preferences, save_template, save_tool_notes, user_id,
        )


async def _do_save(
    db_session: Any,
    session_id: str,
    reflection_summary: dict,
    save_preferences: bool,
    save_template: bool,
    save_tool_notes: bool,
    user_id: str | None,
) -> dict[str, Any]:
    """Internal save implementation."""
    from backend.memory.store import MemoryStore

    store = MemoryStore(session=db_session)
    saved = {"preferences": 0, "template": False, "tool_notes": 0, "slots_corrected": 0}

    # Determine user_id from session if not provided
    if user_id is None:
        session_data = await store.get_session(session_id)
        if session_data:
            user_id = session_data.get("user_id", "anonymous")
        else:
            user_id = "anonymous"

    # Save preferences
    if save_preferences:
        prefs = reflection_summary.get("user_preferences", {})
        for key, value in prefs.items():
            if value is not None and value != {} and value != [] and value != "":
                await store.upsert_preference(user_id, key, value)
                saved["preferences"] += 1

    # Save template
    if save_template:
        template = reflection_summary.get("analysis_template")
        if template and isinstance(template, dict):
            name = template.get("template_name", "未命名模板")
            scenario = template.get("applicable_scenario", "")
            skeleton = template.get("plan_skeleton", {})
            # Infer domain/complexity from skeleton or use defaults
            domain = template.get("domain", "general")
            complexity = template.get("output_complexity", "chart_text")
            tags = template.get("tags", [])
            tid = await store.save_template(
                user_id, name, domain, complexity, tags, skeleton,
            )
            saved["template"] = True

    # Save tool notes
    if save_tool_notes:
        feedback = reflection_summary.get("tool_feedback", {})
        well = feedback.get("well_performed", [])
        for tool_id in well:
            await store.upsert_tool_note(user_id, tool_id, "表现良好", 1.0)
            saved["tool_notes"] += 1
        issues = feedback.get("issues_found", [])
        for item in issues:
            if isinstance(item, dict):
                sid = item.get("tool", "")
                issue = item.get("issue", "")
                if sid:
                    await store.upsert_tool_note(user_id, sid, f"问题：{issue}", 0.5)
                    saved["tool_notes"] += 1

    # Mark corrected slots
    slot_review = reflection_summary.get("slot_quality_review", {})
    corrected_slots = slot_review.get("slots_corrected", [])
    for slot_name in corrected_slots:
        await store.mark_corrected(session_id, slot_name)
        saved["slots_corrected"] += 1

    return saved
