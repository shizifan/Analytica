"""SlotFillingEngine — 感知层 Slot 填充引擎。

通过 LLM 提取用户意图中的槽位值，并驱动多轮追问对话以澄清分析意图。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from copy import deepcopy
from typing import Any, Optional

from backend.exceptions import SlotFillingError
from backend.models.schemas import (
    ALL_SLOT_NAMES,
    SLOT_SCHEMA,
    SLOT_SCHEMA_MAP,
    SlotValue,
    StructuredIntent,
)

logger = logging.getLogger("analytica.perception")

# ── LLM Prompt Templates ────────────────────────────────────

SLOT_EXTRACTION_PROMPT = """你是一个数据分析意图槽位提取专家。

【重要上下文】
当前日期：{current_date}

【当前已填充的槽位】
{current_slots_json}

【用户对话历史】
{conversation_history}

【用户最新输入】
{latest_user_message}

【任务】
从用户最新输入（结合对话历史）中识别以下槽位的值：
{target_slots_list}

【输出格式】（严格 JSON，无任何 markdown 包裹，无 <think> 块）
{{
  "extracted": {{
    "<slot_name>": {{
      "value": "<提取的值，无法确定时为 null>",
      "evidence": "支持此提取的原文片段",
      "confidence": "explicit | implicit"
    }}
  }}
}}

规则：
- 只输出有依据的槽位，无依据的不输出（宁缺毋滥）
- time_range 解析为 {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "description": "自然语言"}}
- 【重要】"今年""本年""当前年度"应基于【当前日期】推断年份：当前是{current_date}，则"今年"对应{current_year}年，"去年"对应{prev_year}年，"前年"对应{prev_prev_year}年
- 【重要】"Q1"对应第1季度(01-01至03-31)，"Q2"对应第2季度(04-01至06-30)，"Q3"对应第3季度(07-01至09-30)，"Q4"对应第4季度(10-01至12-31)
- output_complexity 判断（须有强关键词，否则不输出此槽位，走系统默认 simple_table）：
  * chart_text：用户明确说"图文""图表""可视化""带图"
  * full_report：用户明确说"报告""分析报告""PPT""Word""生成文档"
  * 仅说"查""看""分析""对比"等一般词汇 → 不输出，走默认
- attribution_needed：仅当用户明确说"归因""为什么""原因分析"时提取为 true，其余情况不输出
- analysis_subject 提取为列表形式，如 ["吞吐量"]。注意：用户未明确指定具体货类（集装箱、散杂货等）时，不要自行补充货类限定词
- 不推测用户未表达的内容
- comparison_type 对比方式提取：识别关键词映射——"同比"→yoy, "环比"→mom, "累计"→cumulative, "趋势"/"走势"/"变化"→trend, "实时"/"当前"→snapshot, "历年"/"历史"→historical。无对比关键词时输出 null
- region 区域提取：识别港区/区域名称（如"大连港区""营口港""全港"等）。未指定时输出 null
- data_granularity 数据粒度提取："各港区"/"按港区"/"分港区"→zone, "全港"→port, "各公司"/"按公司"→company, "客户"/"企业"→customer, "设备"/"单台"/"机种"→equipment, "项目"→project, "货类"→cargo, "资产"→asset, "业务板块"/"业务类型"→business。提及具体区域名则推断为 zone；未指定时输出 null
- domain 业务领域推断（参考关键词映射）：
  吞吐量/TEU/集装箱/散货/泊位/船舶/商品车/港存/装卸效率 → D1
  商务驾驶舱/市场/重点企业/业务板块 → D2
  客户/战略客户/客户贡献/客户信用 → D3
  投企/持股/董监事 → D4
  资产/房屋/土地/海域/设备设施(资产) → D5
  投资/资本项目/成本项目/计划进度/交付率 → D6
  设备利用率/完好率/台时效率/能耗/故障/可靠性 → D7
"""

CLARIFICATION_PROMPT = """你是一个友好的数据分析助手，正在帮助用户澄清分析需求。

【当前已填充的槽位】
{current_slots_json}

【需要追问的槽位】
名称：{target_slot}
含义：{slot_meaning}

【要求】
1. 生成一条自然、友好的中文追问
2. 如果其他槽位已有推断值，在追问中提及（如"我理解时间范围为……是否正确？"）
3. 一次只问一个问题
4. 给用户确认的支点而非从零填写

只输出追问文本，不要输出其他内容。"""

MULTI_SLOT_CLARIFICATION_PROMPT = """你是一个友好的数据分析助手，正在帮助用户澄清分析需求。

【当前已填充的槽位】
{current_slots_json}

【需要追问的多个槽位】
{target_slots_info}

【要求】
1. 将多个需要确认的信息整合为一条自然流畅的中文追问
2. 清晰分隔各项，不超过 3 句话
3. 如果某些槽位已有推断值，在追问中提及供用户确认
4. 给用户确认的支点而非从零填写

只输出追问文本，不要输出其他内容。"""

SLOT_MEANINGS = {
    "analysis_subject": "分析对象（指标/实体）",
    "time_range": "分析的时间范围",
    "output_complexity": "结果期望的复杂程度（simple_table/chart_text/full_report）",
    "output_format": "输出格式（docx/pptx/pdf/html）",
    "attribution_needed": "是否需要归因分析",
    "predictive_needed": "是否需要预测分析",
    "time_granularity": "数据粒度（日/月/季/年）",
    "domain": "业务领域（D1生产运营/D2市场商务/D3客户管理/D4投企管理/D5资产管理/D6投资管理/D7设备子屏）",
    "domain_glossary": "用户自定义业务术语映射",
    "comparison_type": "对比方式（同比yoy/环比mom/累计cumulative/趋势trend/实时snapshot/历史historical）",
    "region": "分析涉及的港区或区域名称",
    "data_granularity": "数据分组维度（全港port/港区zone/公司company/客户customer/设备equipment/项目project/货类cargo/资产asset/业务板块business）",
}

# Source priority: higher number = higher priority, cannot be overwritten by lower
SOURCE_PRIORITY = {
    "default": 0,
    "inferred": 1,
    "memory_low_confidence": 2,
    "memory": 3,
    "history": 4,
    "user_input": 5,
}

# Bypass keywords
BYPASS_KEYWORDS = ["按你理解执行", "按你的理解执行", "你决定", "都行", "随便", "按默认"]

# Default values for inferable slots
SLOT_DEFAULTS = {
    "time_granularity": "monthly",
    "output_complexity": "simple_table",
    "output_format": "html",
    "attribution_needed": False,
    "predictive_needed": False,
    "domain": None,
    "domain_glossary": None,
    "comparison_type": None,
    "region": None,
    "data_granularity": None,
}

# Condition activation rules — only slots here will trigger clarification questions
# when their condition is met. attribution_needed / predictive_needed intentionally
# omitted: they default to False via SLOT_DEFAULTS and are enabled only when the
# user explicitly asks for 归因/预测 in their query.
CONDITION_RULES = {
    "output_format": lambda complexity: complexity == "full_report",
}


def _strip_think_tags(text: str) -> str:
    """Remove Qwen3's <think>...</think> reasoning blocks."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()


def _strip_markdown_fences(text: str) -> str:
    """Remove ```json ... ``` markdown code fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Remove first line (```json) and last line (```)
        if lines[-1].strip() == "```":
            lines = lines[1:-1]
        else:
            lines = lines[1:]
        text = "\n".join(lines)
    return text.strip()


def _clean_llm_output(raw: str) -> str:
    """Clean LLM output: strip think tags, markdown fences."""
    cleaned = _strip_think_tags(raw)
    cleaned = _strip_markdown_fences(cleaned)
    return cleaned.strip()


class SlotFillingEngine:
    """Core slot filling engine for the perception layer."""

    def __init__(
        self,
        llm: Any = None,
        memory_store: Any = None,
        max_clarification_rounds: int = 3,
        llm_timeout: float = 30.0,
        extra_slot_defs: list[Any] | None = None,
        slot_constraints: dict[str, Any] | None = None,
        prompt_suffix: str = "",
    ):
        self.llm = llm
        self.memory_store = memory_store
        self.max_clarification_rounds = max_clarification_rounds
        self.llm_timeout = llm_timeout
        # 员工域扩展
        self.extra_slot_defs = extra_slot_defs or []
        self.slot_constraints = slot_constraints or {}
        self.prompt_suffix = prompt_suffix
        # 派生：额外槽位名 + 含义
        self._extra_slot_names = [s.name for s in self.extra_slot_defs]
        self._extra_slot_meanings = {
            s.name: s.meaning for s in self.extra_slot_defs if s.meaning
        }
        self._all_slot_names = list(ALL_SLOT_NAMES) + self._extra_slot_names

    def initialize_slots(self, user_memory: dict[str, Any]) -> dict[str, SlotValue]:
        """Initialize all slots, pre-filling inferable slots from user memory.

        Required slots with inferable=False are NOT pre-filled from memory.
        Also initializes extra_slots and applies slot_constraints defaults.
        """
        slots: dict[str, SlotValue] = {}
        for slot_def in SLOT_SCHEMA:
            name = slot_def.name
            # 检查 slot_constraints 中是否有默认值覆盖
            constraint = self.slot_constraints.get(name)
            constraint_default = getattr(constraint, "default_value", None) if constraint else None
            # Memory preferences can pre-fill any slot (user's past preferences)
            if name in user_memory and user_memory[name] is not None:
                slots[name] = SlotValue(
                    value=user_memory[name],
                    source="memory",
                    confirmed=False,
                )
            elif constraint_default is not None:
                slots[name] = SlotValue(
                    value=constraint_default,
                    source="default",
                    confirmed=False,
                )
            else:
                slots[name] = SlotValue(value=None, source="default", confirmed=False)

        # 初始化额外槽位
        for es in self.extra_slot_defs:
            slots[es.name] = SlotValue(value=None, source="default", confirmed=False)

        return slots

    async def apply_correction_rate_check(
        self, slots: dict[str, SlotValue], user_id: str
    ) -> None:
        """Downgrade memory-sourced slots if correction rate > 0.3."""
        if self.memory_store is None:
            return
        for name, slot in slots.items():
            if slot.source == "memory" and slot.value is not None:
                rate = await self.memory_store.get_correction_rate(user_id, name)
                if rate > 0.3:
                    slot.source = "memory_low_confidence"

    async def extract_slots_from_text(
        self,
        text: str,
        current_slots: dict[str, SlotValue],
        conversation_history: list[dict[str, str]],
    ) -> dict[str, SlotValue]:
        """Extract slot values from user text using LLM.

        Calls the LLM with retry logic (max 2 attempts), strips <think> tags,
        and parses extracted slots.
        """
        updated_slots = deepcopy(current_slots)

        # Build prompt
        current_slots_json = {}
        for name, sv in current_slots.items():
            current_slots_json[name] = {
                "value": sv.value,
                "source": sv.source,
                "confirmed": sv.confirmed,
            }

        history_text = ""
        if conversation_history:
            for msg in conversation_history:
                role = msg.get("role", "unknown")
                content = msg.get("content", "")
                history_text += f"{role}: {content}\n"
        if not history_text:
            history_text = "（无历史对话）"

        target_slots = ", ".join(self._all_slot_names)

        # 构建额外规则（extra_slots 含义 + slot_constraints 约束）
        extra_rules = ""
        if self.extra_slot_defs or self.slot_constraints:
            rule_lines = []
            for es in self.extra_slot_defs:
                rule = f"- {es.name}: {es.meaning}"
                if es.allowed_values:
                    rule += f"，可选值：{'|'.join(es.allowed_values)}"
                rule_lines.append(rule)
            for slot_name, constraint in self.slot_constraints.items():
                av = getattr(constraint, "allowed_values", [])
                if av:
                    rule_lines.append(
                        f"- {slot_name} 值域限定为：{'|'.join(str(v) for v in av)}"
                    )
            if rule_lines:
                extra_rules = "\n【额外槽位与约束规则】\n" + "\n".join(rule_lines)

        import datetime
        today = datetime.date.today()
        current_date = today.isoformat()
        current_year = today.year
        prev_year = current_year - 1
        prev_prev_year = current_year - 2
        prompt = SLOT_EXTRACTION_PROMPT.format(
            current_date=current_date,
            current_year=current_year,
            prev_year=prev_year,
            prev_prev_year=prev_prev_year,
            current_slots_json=json.dumps(current_slots_json, ensure_ascii=False, indent=2),
            conversation_history=history_text,
            latest_user_message=text,
            target_slots_list=target_slots,
        )
        if self.prompt_suffix:
            prompt += f"\n\n{self.prompt_suffix}"
        if extra_rules:
            prompt += extra_rules

        # Call LLM with retry
        raw_output = await self._call_llm_with_retry(prompt)
        if raw_output is None:
            return updated_slots

        # Parse LLM output
        cleaned = _clean_llm_output(raw_output)
        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            logger.warning("LLM output is not valid JSON after cleaning: %s", cleaned[:200])
            return updated_slots

        extracted = parsed.get("extracted", {})
        if not isinstance(extracted, dict):
            return updated_slots

        # Apply extracted values
        known_slot_names = set(SLOT_SCHEMA_MAP) | set(self._extra_slot_names)
        for slot_name, extraction in extracted.items():
            if slot_name not in known_slot_names:
                logger.debug("Ignoring unknown slot name from LLM: %s", slot_name)
                continue

            if not isinstance(extraction, dict):
                continue

            value = extraction.get("value")
            if value is None:
                continue

            confidence = extraction.get("confidence", "implicit")

            # Determine source and confirmed flag
            if confidence == "explicit":
                new_source = "user_input"
                new_confirmed = True
            else:
                new_source = "inferred"
                new_confirmed = False

            # Check source priority: only update if new source >= current source
            current_slot = updated_slots.get(slot_name)
            if current_slot is not None:
                current_priority = SOURCE_PRIORITY.get(current_slot.source, 0)
                new_priority = SOURCE_PRIORITY.get(new_source, 0)
                if current_slot.value is not None and new_priority < current_priority:
                    continue

            updated_slots[slot_name] = SlotValue(
                value=value, source=new_source, confirmed=new_confirmed
            )

        return updated_slots

    def get_empty_required_slots(
        self, slots: dict[str, SlotValue], current_complexity: str | None
    ) -> list[str]:
        """Get list of empty required + activated conditional slots, sorted by priority."""
        empty_slots = []

        for slot_def in SLOT_SCHEMA:
            name = slot_def.name
            slot_val = slots.get(name)

            # Check if this slot should be checked
            should_check = False
            if slot_def.required:
                should_check = True
            elif slot_def.condition is not None and current_complexity:
                # Check condition activation
                condition_fn = CONDITION_RULES.get(name)
                if condition_fn and condition_fn(current_complexity):
                    should_check = True

            if not should_check:
                continue

            # Skip inferable slots (priority 99) — they don't trigger clarification
            if slot_def.inferable and slot_def.priority == 99:
                continue

            # Check if empty
            if slot_val is None or slot_val.value is None:
                empty_slots.append((slot_def.priority, name))

        # 检查额外槽位中 required=True 的
        for es in self.extra_slot_defs:
            if es.required:
                slot_val = slots.get(es.name)
                if slot_val is None or slot_val.value is None:
                    empty_slots.append((es.priority, es.name))

        empty_slots.sort(key=lambda x: x[0])
        return [name for _, name in empty_slots]

    async def generate_clarification_question(
        self, target_slot: str, slots: dict[str, SlotValue]
    ) -> str:
        """Generate a clarification question for a specific slot using LLM."""
        slots_json = {}
        for name, sv in slots.items():
            if sv.value is not None:
                slots_json[name] = {
                    "value": sv.value,
                    "source": sv.source,
                    "confirmed": sv.confirmed,
                }

        slot_meaning = SLOT_MEANINGS.get(target_slot) or self._extra_slot_meanings.get(target_slot, target_slot)

        prompt = CLARIFICATION_PROMPT.format(
            current_slots_json=json.dumps(slots_json, ensure_ascii=False, indent=2),
            target_slot=target_slot,
            slot_meaning=slot_meaning,
        )

        raw_output = await self._call_llm_with_retry(prompt)
        if raw_output is None:
            # Fallback question
            return f"请问您希望的{slot_meaning}是什么？"

        cleaned = _strip_think_tags(raw_output).strip()
        if not cleaned:
            return f"请问您希望的{slot_meaning}是什么？"
        return cleaned

    async def generate_multi_slot_clarification(
        self, target_slots: list[str], slots: dict[str, SlotValue]
    ) -> str:
        """Generate a single clarification question covering multiple empty slots."""
        slots_json = {}
        for name, sv in slots.items():
            if sv.value is not None:
                slots_json[name] = {
                    "value": sv.value,
                    "source": sv.source,
                    "confirmed": sv.confirmed,
                }

        target_info_lines = []
        all_meanings = {**SLOT_MEANINGS, **self._extra_slot_meanings}
        for slot_name in target_slots:
            meaning = all_meanings.get(slot_name, slot_name)
            target_info_lines.append(f"- {slot_name}: {meaning}")
        target_slots_info = "\n".join(target_info_lines)

        prompt = MULTI_SLOT_CLARIFICATION_PROMPT.format(
            current_slots_json=json.dumps(slots_json, ensure_ascii=False, indent=2),
            target_slots_info=target_slots_info,
        )

        raw_output = await self._call_llm_with_retry(prompt)
        if raw_output is None:
            fallback_parts = [all_meanings.get(s, s) for s in target_slots]
            return f"请问您希望的{'、'.join(fallback_parts)}分别是什么？"

        cleaned = _strip_think_tags(raw_output).strip()
        if not cleaned:
            fallback_parts = [SLOT_MEANINGS.get(s, s) for s in target_slots]
            return f"请问您希望的{'、'.join(fallback_parts)}分别是什么？"
        return cleaned

    def build_structured_intent(
        self, slots: dict[str, SlotValue], raw_query: str
    ) -> StructuredIntent:
        """Build the final StructuredIntent from filled slots."""
        # Build analysis goal summary
        subject = slots.get("analysis_subject")
        time_range = slots.get("time_range")

        subject_text = ""
        if subject and subject.value:
            if isinstance(subject.value, list):
                subject_text = "、".join(str(v) for v in subject.value)
            else:
                subject_text = str(subject.value)

        time_text = ""
        if time_range and time_range.value:
            if isinstance(time_range.value, dict):
                time_text = time_range.value.get("description", "")
            else:
                time_text = str(time_range.value)

        # Enrich goal with region and comparison_type if available
        region_slot = slots.get("region")
        region_text = ""
        if region_slot and region_slot.value:
            region_text = str(region_slot.value)

        comp_type_slot = slots.get("comparison_type")
        comp_type_text = ""
        if comp_type_slot and comp_type_slot.value:
            ct_map = {"yoy": "同比", "mom": "环比", "cumulative": "累计",
                      "trend": "趋势", "snapshot": "实时", "historical": "历史"}
            # Handle list value (multiple comparison types)
            if isinstance(comp_type_slot.value, list):
                texts = [ct_map.get(v, v) for v in comp_type_slot.value if v in ct_map]
                comp_type_text = "".join(texts) if texts else str(comp_type_slot.value[0])
            else:
                comp_type_text = ct_map.get(comp_type_slot.value, comp_type_slot.value)

        if subject_text:
            goal_parts = ["分析"]
            if time_text:
                goal_parts.append(time_text)
            if region_text:
                goal_parts.append(region_text)
            goal_parts.append(subject_text)
            if comp_type_text:
                goal_parts.append(f"的{comp_type_text}数据")
            else:
                goal_parts.append("的数据")
            analysis_goal = "".join(goal_parts)
        else:
            analysis_goal = raw_query

        # Calculate empty required slots
        complexity = None
        comp_slot = slots.get("output_complexity")
        if comp_slot and comp_slot.value:
            complexity = comp_slot.value
        empty_required = self.get_empty_required_slots(slots, complexity)

        return StructuredIntent(
            raw_query=raw_query,
            analysis_goal=analysis_goal,
            slots=slots,
            empty_required_slots=empty_required,
        )

    async def handle_bypass(
        self, text: str, slots: dict[str, SlotValue]
    ) -> dict[str, Any]:
        """Handle user bypass (e.g., '按你理解执行').

        Fill all empty slots with inferred/default values.
        """
        is_bypass = any(kw in text for kw in BYPASS_KEYWORDS)
        if not is_bypass:
            return {"bypass_triggered": False}

        # Fill all empty slots with defaults/inferred values
        for slot_def in SLOT_SCHEMA:
            name = slot_def.name
            slot = slots.get(name)
            if slot is None or slot.value is None:
                default = SLOT_DEFAULTS.get(name)
                if default is not None:
                    slots[name] = SlotValue(
                        value=default, source="inferred", confirmed=False
                    )
                elif name == "time_range":
                    # Default to last month
                    import datetime
                    today = datetime.date.today()
                    first_of_month = today.replace(day=1)
                    last_month_end = first_of_month - datetime.timedelta(days=1)
                    last_month_start = last_month_end.replace(day=1)
                    slots[name] = SlotValue(
                        value={
                            "start": last_month_start.isoformat(),
                            "end": last_month_end.isoformat(),
                            "description": "上个月",
                        },
                        source="inferred",
                        confirmed=False,
                    )
                elif name == "analysis_subject":
                    slots[name] = SlotValue(
                        value=["综合运营数据"], source="inferred", confirmed=False
                    )

        # 填充额外槽位的默认值（slot_constraints 中的 default_value）
        for es in self.extra_slot_defs:
            slot = slots.get(es.name)
            if slot is None or slot.value is None:
                constraint = self.slot_constraints.get(es.name)
                cd = getattr(constraint, "default_value", None) if constraint else None
                if cd is not None:
                    slots[es.name] = SlotValue(value=cd, source="inferred", confirmed=False)

        return {"bypass_triggered": True}

    def handle_max_rounds_reached(
        self, slots: dict[str, SlotValue]
    ) -> dict[str, Any]:
        """Handle when max clarification rounds are reached.

        Fill remaining empty required slots with defaults and proceed.
        """
        for slot_def in SLOT_SCHEMA:
            name = slot_def.name
            slot = slots.get(name)
            if (slot is None or slot.value is None) and (slot_def.required or slot_def.inferable):
                default = SLOT_DEFAULTS.get(name)
                if default is not None:
                    slots[name] = SlotValue(
                        value=default, source="default", confirmed=False
                    )
                elif name == "time_range":
                    import datetime
                    today = datetime.date.today()
                    first_of_month = today.replace(day=1)
                    last_month_end = first_of_month - datetime.timedelta(days=1)
                    last_month_start = last_month_end.replace(day=1)
                    slots[name] = SlotValue(
                        value={
                            "start": last_month_start.isoformat(),
                            "end": last_month_end.isoformat(),
                            "description": "最近一个月（默认）",
                        },
                        source="default",
                        confirmed=False,
                    )
                elif name == "analysis_subject":
                    slots[name] = SlotValue(
                        value=["综合运营数据"], source="default", confirmed=False
                    )

        # 填充额外槽位的默认值
        for es in self.extra_slot_defs:
            slot = slots.get(es.name)
            if slot is None or slot.value is None:
                constraint = self.slot_constraints.get(es.name)
                cd = getattr(constraint, "default_value", None) if constraint else None
                if cd is not None:
                    slots[es.name] = SlotValue(value=cd, source="default", confirmed=False)

        return {"should_proceed_with_defaults": True}

    async def _call_llm_with_retry(
        self, prompt: str, max_retries: int = 3
    ) -> str | None:
        """Call LLM with timeout and retry logic.

        Retries up to max_retries times on timeout or API error.
        Wait ≥ 1s between retries with exponential backoff.
        """
        last_error: Exception | None = None

        for attempt in range(max_retries):
            if attempt > 0:
                await asyncio.sleep(1.0 * (2 ** (attempt - 1)))  # Backoff: 1s, 2s, 4s, ...

            try:
                result = await asyncio.wait_for(
                    self._invoke_llm(prompt),
                    timeout=self.llm_timeout,
                )
                return result
            except asyncio.TimeoutError as e:
                last_error = e
                logger.warning(
                    "LLM call timeout (attempt %d/%d)", attempt + 1, max_retries
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    "LLM call error (attempt %d/%d): %s", attempt + 1, max_retries, e
                )

        if isinstance(last_error, asyncio.TimeoutError):
            raise SlotFillingError(f"LLM call timeout after {max_retries} attempts")

        logger.error("LLM call failed after %d attempts: %s", max_retries, last_error)
        return None

    async def _invoke_llm(self, prompt: str) -> str:
        """Invoke the LLM and return raw text output."""
        if self.llm is None:
            raise SlotFillingError("LLM client not configured")

        # Support both callable and LangChain ChatModel
        if callable(self.llm) and not hasattr(self.llm, "ainvoke"):
            result = await self.llm(prompt)
            if isinstance(result, str):
                return result
            return str(result)

        # LangChain ChatModel interface
        response = await self.llm.ainvoke(prompt)
        if hasattr(response, "content"):
            return response.content
        return str(response)


async def run_perception(state: dict, profile: Any = None) -> dict:
    """LangGraph perception node implementation.

    Orchestrates the SlotFillingEngine within the agent graph.
    当 profile (EmployeeProfile) 提供时，注入员工域配置（extra_slots、slot_constraints、prompt_suffix）。
    """
    from backend.config import get_settings
    from backend.database import get_session_factory

    settings = get_settings()

    # Initialize LLM
    from langchain_openai import ChatOpenAI
    llm = ChatOpenAI(
        base_url=settings.QWEN_API_BASE,
        api_key=settings.QWEN_API_KEY,
        model=settings.QWEN_MODEL,
        temperature=0.1,
        request_timeout=90,
        extra_body={"enable_thinking": False},
    )

    # 从 profile 提取员工域扩展参数
    extra_slot_defs = []
    slot_constraints: dict[str, Any] = {}
    prompt_suffix = ""
    if profile is not None:
        extra_slot_defs = profile.perception.extra_slots
        slot_constraints = profile.perception.slot_constraints
        prompt_suffix = profile.perception.system_prompt_suffix or ""

    # Get DB session for memory
    from backend.memory.store import MemoryStore

    factory = get_session_factory()
    async with factory() as db_session:
        memory_store = MemoryStore(session=db_session)
        engine = SlotFillingEngine(
            llm=llm,
            memory_store=memory_store,
            max_clarification_rounds=3,
            llm_timeout=60.0,
            extra_slot_defs=extra_slot_defs,
            slot_constraints=slot_constraints,
            prompt_suffix=prompt_suffix,
        )

        user_id = state.get("user_id", "anonymous")
        messages = state.get("messages", [])
        user_message = ""
        for msg in reversed(messages):
            if msg.get("role") == "user":
                user_message = msg.get("content", "")
                break

        slots = state.get("slots", {})
        clarification_round = state.get("clarification_round", 0)

        # Convert dict slots back to SlotValue objects
        slot_values: dict[str, SlotValue] = {}
        if slots:
            for name, sv_data in slots.items():
                if isinstance(sv_data, SlotValue):
                    slot_values[name] = sv_data
                elif isinstance(sv_data, dict):
                    slot_values[name] = SlotValue(**sv_data)
        else:
            # First turn: initialize from memory
            user_prefs = await memory_store.get_user_preferences(user_id)
            slot_values = engine.initialize_slots(user_prefs)
            await engine.apply_correction_rate_check(slot_values, user_id)

        # Check bypass
        bypass_result = await engine.handle_bypass(user_message, slot_values)
        if bypass_result.get("bypass_triggered"):
            intent = engine.build_structured_intent(slot_values, user_message)
            state["slots"] = {n: sv.model_dump() for n, sv in slot_values.items()}
            state["structured_intent"] = intent.model_dump()
            state["empty_required_slots"] = []
            state["current_target_slot"] = None
            state["current_phase"] = "perception"
            state["messages"].append({
                "role": "assistant",
                "content": "好的，按我的理解为您执行分析。",
            })
            return state

        # Extract slots from text
        slot_values = await engine.extract_slots_from_text(
            user_message, slot_values, messages[:-1] if len(messages) > 1 else []
        )

        # ── 默认值回填（对 inferable 且仍为空的槽位） ──
        for slot_def in SLOT_SCHEMA:
            name = slot_def.name
            if not slot_def.inferable:
                continue
            sv = slot_values.get(name)
            if sv is None or sv.value is None:
                default = SLOT_DEFAULTS.get(name)
                if default is not None:
                    slot_values[name] = SlotValue(
                        value=default, source="inferred", confirmed=False
                    )

        # Get current complexity
        complexity = None
        comp_slot = slot_values.get("output_complexity")
        if comp_slot and comp_slot.value:
            complexity = comp_slot.value

        # Check empty required slots
        empty_required = engine.get_empty_required_slots(slot_values, complexity)

        # Record slots to history
        session_id = state.get("session_id", "")
        for name, sv in slot_values.items():
            if sv.value is not None and sv.source == "user_input":
                await memory_store.record_slot(
                    session_id, name, sv.value, sv.source,
                    round_num=clarification_round + 1,
                )

        # Update state
        state["slots"] = {n: sv.model_dump() for n, sv in slot_values.items()}
        state["empty_required_slots"] = empty_required
        state["current_phase"] = "perception"
        state["clarification_round"] = clarification_round + 1

        if empty_required:
            # Check max rounds
            if clarification_round >= engine.max_clarification_rounds:
                engine.handle_max_rounds_reached(slot_values)
                state["slots"] = {n: sv.model_dump() for n, sv in slot_values.items()}
                intent = engine.build_structured_intent(slot_values, user_message)
                state["structured_intent"] = intent.model_dump()
                state["empty_required_slots"] = []
                state["current_target_slot"] = None
                state["messages"].append({
                    "role": "assistant",
                    "content": "已达到最大追问轮数，使用默认值继续分析。",
                })
                return state

            # Generate clarification — multi-slot when possible
            if len(empty_required) > 1:
                question = await engine.generate_multi_slot_clarification(
                    empty_required, slot_values
                )
            else:
                question = await engine.generate_clarification_question(
                    empty_required[0], slot_values
                )
            state["current_target_slot"] = empty_required[0]  # 兼容前端展示
            state["structured_intent"] = None
            state["messages"].append({
                "role": "assistant",
                "content": question,
            })
        else:
            # All slots filled — build intent
            intent = engine.build_structured_intent(slot_values, user_message)
            state["structured_intent"] = intent.model_dump()
            state["current_target_slot"] = None
            state["messages"].append({
                "role": "assistant",
                "content": f"已理解您的分析需求：{intent.analysis_goal}",
            })

        return state
