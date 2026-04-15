"""TC-C01 ~ TC-C08: 空槽检测与追问测试。

TC-C01~C04, C07: 纯逻辑测试（不需要 LLM）
TC-C05~C06: 使用真实 LLM 生成追问
TC-C08: bypass 机制测试
"""
from unittest.mock import AsyncMock

import pytest

from backend.agent.perception import SlotFillingEngine
from backend.models.schemas import SlotValue, StructuredIntent, ALL_SLOT_NAMES


def make_empty_slots():
    return {name: SlotValue(value=None, source="default", confirmed=False) for name in ALL_SLOT_NAMES}


def make_partial_slots(**kwargs):
    slots = make_empty_slots()
    if "output_complexity" in kwargs:
        slots["output_complexity"] = SlotValue(value=kwargs["output_complexity"], source="user_input", confirmed=True)
    if "analysis_subject" in kwargs:
        slots["analysis_subject"] = SlotValue(value=kwargs["analysis_subject"], source="user_input", confirmed=True)
    if "time_range" in kwargs:
        slots["time_range"] = SlotValue(value=kwargs["time_range"], source="user_input", confirmed=True)
    if "output_complexity_inferred" in kwargs:
        slots["output_complexity"] = SlotValue(value=kwargs["output_complexity_inferred"], source="inferred", confirmed=False)
    return slots


def make_fully_filled_slots(complexity="simple_table"):
    slots = {
        "analysis_subject": SlotValue(value=["集装箱吞吐量"], source="user_input", confirmed=True),
        "time_range": SlotValue(value={"start": "2026-03-01", "end": "2026-03-31", "description": "上个月"}, source="user_input", confirmed=True),
        "output_complexity": SlotValue(value=complexity, source="user_input", confirmed=True),
        "output_format": SlotValue(value=None, source="default", confirmed=False),
        "attribution_needed": SlotValue(value=None, source="default", confirmed=False),
        "predictive_needed": SlotValue(value=None, source="default", confirmed=False),
        "time_granularity": SlotValue(value="monthly", source="inferred", confirmed=False),
        "domain": SlotValue(value="production", source="inferred", confirmed=False),
        "domain_glossary": SlotValue(value=None, source="default", confirmed=False),
    }
    if complexity == "full_report":
        slots["output_format"] = SlotValue(value="pptx", source="memory", confirmed=False)
        slots["attribution_needed"] = SlotValue(value=True, source="user_input", confirmed=True)
        slots["predictive_needed"] = SlotValue(value=False, source="inferred", confirmed=False)
    elif complexity == "chart_text":
        slots["attribution_needed"] = SlotValue(value=True, source="user_input", confirmed=True)
    return slots


_dummy = AsyncMock()


# ═══════════════════════════════════════════════════════════════
#  纯逻辑测试
# ═══════════════════════════════════════════════════════════════

def test_conditional_slots_not_activated_for_simple_table():
    """TC-C01: simple_table 时条件槽不进入必填集"""
    engine = SlotFillingEngine(llm=_dummy)
    slots = make_partial_slots(output_complexity="simple_table", analysis_subject=["集装箱"], time_range={"start": "2026-01-01", "end": "2026-03-31"})
    empty = engine.get_empty_required_slots(slots, current_complexity="simple_table")
    assert "output_format" not in empty
    assert "attribution_needed" not in empty
    assert "predictive_needed" not in empty


def test_attribution_activated_for_chart_text():
    """TC-C02: chart_text 时 attribution_needed 成为必填"""
    engine = SlotFillingEngine(llm=_dummy)
    slots = make_partial_slots(output_complexity="chart_text", analysis_subject=["集装箱"], time_range={"start": "2026-01-01", "end": "2026-03-31"})
    empty = engine.get_empty_required_slots(slots, current_complexity="chart_text")
    assert "attribution_needed" in empty


def test_all_conditional_slots_activated_for_full_report():
    """TC-C03: full_report 时三个条件槽全部激活"""
    engine = SlotFillingEngine(llm=_dummy)
    slots = make_partial_slots(output_complexity="full_report", analysis_subject=["吞吐量"], time_range={"start": "2026-01-01", "end": "2026-06-30"})
    empty = engine.get_empty_required_slots(slots, current_complexity="full_report")
    for slot_name in ["output_format", "attribution_needed", "predictive_needed"]:
        assert slot_name in empty


def test_empty_slots_sorted_by_priority():
    """TC-C04: 空槽按 priority 升序，time_range 排第一"""
    engine = SlotFillingEngine(llm=_dummy)
    empty = engine.get_empty_required_slots(make_empty_slots(), current_complexity=None)
    assert len(empty) >= 2
    assert empty[0] == "time_range"
    assert empty[1] == "analysis_subject"


def test_build_structured_intent_when_all_slots_filled():
    """TC-C07: 全槽填满后返回有效 StructuredIntent"""
    engine = SlotFillingEngine(llm=_dummy)
    intent = engine.build_structured_intent(make_fully_filled_slots("simple_table"), "上个月集装箱吞吐量")
    assert isinstance(intent, StructuredIntent)
    assert intent.slots["output_complexity"].value == "simple_table"


# ═══════════════════════════════════════════════════════════════
#  真实 LLM 测试
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_clarification_asks_one_slot_only(real_engine):
    """【真实LLM】TC-C05: 追问只针对单个槽"""
    slots = make_partial_slots(analysis_subject=["集装箱吞吐量"])
    question = await real_engine.generate_clarification_question("time_range", slots)
    assert len(question) > 5
    q_count = question.count("？") + question.count("?")
    assert q_count <= 3, f"追问含 {q_count} 个问号，疑似合并多问: {question}"
    print(f"  追问: {question}")


@pytest.mark.asyncio
async def test_clarification_includes_context(real_engine):
    """【真实LLM】TC-C06: 追问包含时间相关词汇"""
    slots = make_partial_slots(analysis_subject=["集装箱吞吐量"], output_complexity_inferred="chart_text")
    question = await real_engine.generate_clarification_question("time_range", slots)
    assert len(question) > 10
    assert any(kw in question for kw in ("时间", "时段", "时期", "哪", "请问", "范围", "月", "年", "季")), \
        f"追问应包含时间词汇: {question}"
    print(f"  追问: {question}")


@pytest.mark.asyncio
async def test_skip_to_default_on_user_bypass(real_engine):
    """TC-C08: 「按你理解执行」空槽取默认值"""
    slots = make_partial_slots(analysis_subject=["货量"])
    result = await real_engine.handle_bypass("按你理解执行", slots)
    assert result.get("bypass_triggered") is True
    assert slots["time_range"].value is not None
    assert slots["time_range"].source in ("inferred", "default")
