"""TC-M01 ~ TC-M06: Slot 模型与数据结构测试。"""
from uuid import uuid4

import pytest
from pydantic import ValidationError

from backend.models.schemas import (
    SLOT_SCHEMA,
    ALL_SLOT_NAMES,
    SlotValue,
    StructuredIntent,
)


# ── TC-M01: SLOT_SCHEMA 完整性 ─────────────────────────────

def test_slot_schema_completeness():
    """验证 SLOT_SCHEMA 包含所有 9 个预定义槽"""
    slot_names = {s.name for s in SLOT_SCHEMA}
    expected = {
        "analysis_subject", "time_range", "output_complexity",
        "output_format", "attribution_needed", "predictive_needed",
        "time_granularity", "domain", "domain_glossary",
    }
    assert slot_names == expected


# ── TC-M02: 必填槽定义正确 ─────────────────────────────────

def test_required_slots_definition():
    """验证必填槽只有 3 个且优先级正确"""
    required_slots = [s for s in SLOT_SCHEMA if s.required]
    assert len(required_slots) == 3
    priorities = {s.name: s.priority for s in required_slots}
    assert priorities["time_range"] == 1
    assert priorities["analysis_subject"] == 2
    assert priorities["output_complexity"] == 3


# ── TC-M03: 条件槽定义正确 ─────────────────────────────────

def test_conditional_slots_have_conditions():
    """验证条件槽均有 condition 字段"""
    conditional_names = {"output_format", "attribution_needed", "predictive_needed"}
    for slot in SLOT_SCHEMA:
        if slot.name in conditional_names:
            assert slot.condition is not None, f"{slot.name} 缺少 condition 定义"
            assert slot.required is False


# ── TC-M04: 可推断槽优先级为 99 ────────────────────────────

def test_inferable_slots_not_prompted():
    """验证 time_granularity/domain/domain_glossary 优先级为 99"""
    inferable_names = {"time_granularity", "domain", "domain_glossary"}
    for slot in SLOT_SCHEMA:
        if slot.name in inferable_names:
            assert slot.priority == 99, f"{slot.name}.priority 应为 99"
            assert slot.inferable is True


# ── TC-M05: StructuredIntent Pydantic 验证 ─────────────────

def test_structured_intent_validation():
    """验证 StructuredIntent 接受完整合法数据"""
    intent = StructuredIntent(
        intent_id=str(uuid4()),
        raw_query="分析上个月集装箱吞吐量",
        analysis_goal="分析 2026 年 3 月集装箱吞吐量的月度数据",
        slots={
            "analysis_subject": SlotValue(value=["集装箱吞吐量"], source="user_input", confirmed=True),
            "time_range": SlotValue(
                value={"start": "2026-03-01", "end": "2026-03-31", "description": "上个月"},
                source="user_input", confirmed=True,
            ),
            "output_complexity": SlotValue(value="simple_table", source="inferred", confirmed=False),
        },
    )
    assert intent.intent_id is not None
    assert intent.slots["output_complexity"].value == "simple_table"


# ── TC-M06: SlotValue source 枚举约束 ─────────────────────

def test_slot_value_source_enum():
    """验证 source 字段只接受合法枚举值"""
    with pytest.raises(ValidationError):
        SlotValue(value="pptx", source="magic", confirmed=False)

    valid_sources = ["user_input", "history", "memory", "memory_low_confidence", "inferred", "default"]
    for src in valid_sources:
        sv = SlotValue(value="test", source=src, confirmed=False)
        assert sv.source == src
