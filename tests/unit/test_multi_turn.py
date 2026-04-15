"""TC-T01 ~ TC-T04: 多轮对话状态一致性测试。

TC-T01~T02: 使用真实 LLM 验证多轮对话 Slot 填充
TC-T03: 纯逻辑测试（max rounds 容错）
TC-T04: DB 写入测试（slot_history）
"""
import json
from uuid import uuid4

import pytest
from sqlalchemy import text

from backend.agent.perception import SlotFillingEngine
from backend.models.schemas import SlotValue, ALL_SLOT_NAMES


def make_empty_slots():
    return {name: SlotValue(value=None, source="default", confirmed=False) for name in ALL_SLOT_NAMES}


def make_partial_slots(**kwargs):
    slots = make_empty_slots()
    if "analysis_subject" in kwargs:
        slots["analysis_subject"] = SlotValue(value=kwargs["analysis_subject"], source="user_input", confirmed=True)
    if "time_range" in kwargs:
        slots["time_range"] = SlotValue(value=kwargs["time_range"], source="user_input", confirmed=True)
    if "output_complexity" in kwargs:
        slots["output_complexity"] = SlotValue(value=kwargs["output_complexity"], source="user_input", confirmed=True)
    return slots


# ═══════════════════════════════════════════════════════════════
#  真实 LLM 多轮对话测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_second_turn_fills_first_turn_missing_slot(real_engine):
    """【真实LLM】TC-T01: 两轮对话——第一轮识别主体，第二轮填入时间范围"""
    # Round 1: 仅包含分析对象，无时间范围
    slots = make_empty_slots()
    slots = await real_engine.extract_slots_from_text("分析集装箱吞吐量", slots, [])

    assert slots["analysis_subject"].value is not None, "第一轮应提取 analysis_subject"
    subj_r1 = slots["analysis_subject"].value
    print(f"  R1: analysis_subject={subj_r1}, time_range={slots['time_range'].value}")

    # Round 2: 补充时间范围
    history = [
        {"role": "user", "content": "分析集装箱吞吐量"},
        {"role": "assistant", "content": "请问您想看哪个时间段的数据？"},
    ]
    slots = await real_engine.extract_slots_from_text("看看去年Q4的数据", slots, history)

    assert slots["time_range"].value is not None, "第二轮应提取 time_range"
    assert slots["analysis_subject"].value is not None, "第一轮的 analysis_subject 应保持"
    print(f"  R2: analysis_subject={slots['analysis_subject'].value}, time_range={slots['time_range'].value}")


@pytest.mark.asyncio
async def test_current_turn_explicit_overrides_history(real_engine):
    """【真实LLM】TC-T02: 本轮「改成DOCX格式」覆盖历史中的PPTX"""
    history = [
        {"role": "user", "content": "做一份PPTX格式的报告"},
        {"role": "assistant", "content": "好的，我会生成PPTX格式的报告。"},
    ]
    # 模拟历史中已经填入 pptx
    slots = make_empty_slots()
    slots["output_format"] = SlotValue(value="pptx", source="history", confirmed=False)
    slots["analysis_subject"] = SlotValue(value=["港口运营"], source="user_input", confirmed=True)

    updated = await real_engine.extract_slots_from_text("改成DOCX格式", slots, history)

    fmt = updated["output_format"]
    assert fmt.value is not None, "output_format 应被更新"
    assert "docx" in str(fmt.value).lower(), f"期望 docx, 实际: {fmt.value}"
    assert fmt.source == "user_input", f"source 应为 user_input, 实际: {fmt.source}"
    print(f"  output_format: pptx(history) -> {fmt.value}({fmt.source})")


# ═══════════════════════════════════════════════════════════════
#  纯逻辑测试
# ═══════════════════════════════════════════════════════════════


def test_max_clarification_rounds_reached():
    """TC-T03: 连续追问 3 次后仍为空，使用默认值推进"""
    from unittest.mock import AsyncMock

    engine = SlotFillingEngine(llm=AsyncMock(), max_clarification_rounds=3)
    slots = make_partial_slots(
        analysis_subject=["集装箱吞吐量"],
        output_complexity="simple_table",
    )
    # time_range 仍为空

    result = engine.handle_max_rounds_reached(slots)
    assert result.get("should_proceed_with_defaults") is True
    assert slots["time_range"].value is not None, "time_range 应被填充默认值"
    assert slots["time_range"].source == "default"
    print(f"  默认 time_range = {slots['time_range'].value}")


# ═══════════════════════════════════════════════════════════════
#  DB 写入测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_slot_history_written_to_db(test_db_session):
    """TC-T04: 槽历史记录写入 slot_history 表"""
    from backend.memory.store import MemoryStore

    session_id = str(uuid4())
    store = MemoryStore(session=test_db_session)
    await store.record_slot(
        session_id,
        "time_range",
        {"start": "2026-01-01", "end": "2026-01-31", "description": "上个月"},
        "user_input",
        round_num=1,
    )
    result = await test_db_session.execute(
        text("SELECT slot_name, source, round_num FROM slot_history WHERE session_id = :sid"),
        {"sid": session_id},
    )
    rows = result.fetchall()
    assert len(rows) == 1, f"期望1条记录, 实际: {len(rows)}"
    assert rows[0][0] == "time_range"
    assert rows[0][1] == "user_input"
    assert rows[0][2] == 1
    print(f"  slot_history 写入成功: {rows[0]}")
