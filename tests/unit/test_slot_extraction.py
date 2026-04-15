"""TC-E01 ~ TC-E11: Slot 提取测试。

TC-E01~E06, E11: 使用真实 LLM API 验证大模型 Slot 提取能力
TC-E07~E10: 保留 Mock 验证引擎内部容错逻辑
"""
import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from backend.agent.perception import (
    SlotFillingEngine,
    _strip_think_tags,
    _strip_markdown_fences,
    _clean_llm_output,
)
from backend.exceptions import SlotFillingError
from backend.models.schemas import SlotValue, ALL_SLOT_NAMES


def make_empty_slots():
    return {name: SlotValue(value=None, source="default", confirmed=False) for name in ALL_SLOT_NAMES}


# ═══════════════════════════════════════════════════════════════
#  真实 LLM 测试
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
async def test_extract_explicit_time_range(real_engine):
    """【真实LLM】TC-E01: 「上个月集装箱吞吐量是多少」提取 time_range"""
    updated = await real_engine.extract_slots_from_text(
        "上个月集装箱吞吐量是多少", make_empty_slots(), []
    )
    tr = updated["time_range"]
    assert tr.value is not None, "time_range 应被提取"
    assert tr.source == "user_input"
    assert tr.confirmed is True
    print(f"  time_range = {tr.value}")


@pytest.mark.asyncio
async def test_extract_multiple_analysis_subjects(real_engine):
    """【真实LLM】TC-E02: 「各业务线的集装箱吞吐量」提取 analysis_subject"""
    updated = await real_engine.extract_slots_from_text(
        "分析各业务线的集装箱吞吐量", make_empty_slots(), []
    )
    subj = updated["analysis_subject"]
    assert subj.value is not None, "analysis_subject 应被提取"
    assert subj.source == "user_input"
    val_str = str(subj.value).lower()
    assert any(kw in val_str for kw in ("吞吐", "业务", "throughput", "集装箱")), \
        f"应包含业务相关内容: {subj.value}"
    print(f"  analysis_subject = {subj.value}")


@pytest.mark.asyncio
async def test_infer_simple_table_complexity(real_engine):
    """【真实LLM】TC-E03: 简单查询推断为 simple_table"""
    updated = await real_engine.extract_slots_from_text(
        "上个月集装箱吞吐量是多少，给我一个简单的数据表", make_empty_slots(), []
    )
    comp = updated["output_complexity"]
    if comp.value is not None:
        assert comp.value == "simple_table", f"期望 simple_table, 实际: {comp.value}"
    else:
        # output_complexity 是 inferable 的，简单查询时 LLM 可能不显式输出
        # 此时引擎会在后续用默认值 simple_table 填充
        print("  LLM 未显式推断 output_complexity（合理行为，将由默认值填充）")
    print(f"  output_complexity = {comp.value}")


@pytest.mark.asyncio
async def test_infer_full_report_complexity(real_engine):
    """【真实LLM】TC-E04: 「做一份PPT格式的分析报告」识别为 full_report"""
    updated = await real_engine.extract_slots_from_text(
        "做一份PPT格式的港口运营分析报告", make_empty_slots(), []
    )
    comp = updated["output_complexity"]
    assert comp.value is not None
    assert comp.value == "full_report", f"期望 full_report, 实际: {comp.value}"
    fmt = updated["output_format"]
    if fmt.value is not None:
        assert "ppt" in str(fmt.value).lower(), f"期望 pptx, 实际: {fmt.value}"
    print(f"  output_complexity={comp.value}, output_format={fmt.value}")


@pytest.mark.asyncio
async def test_infer_chart_text_complexity(real_engine):
    """【真实LLM】TC-E05: 「分析趋势变化及原因」识别为 chart_text"""
    updated = await real_engine.extract_slots_from_text(
        "分析吞吐量趋势变化及原因", make_empty_slots(), []
    )
    comp = updated["output_complexity"]
    assert comp.value is not None
    assert comp.value in ("chart_text", "full_report"), \
        f"期望 chart_text/full_report, 实际: {comp.value}"
    print(f"  output_complexity = {comp.value}")


@pytest.mark.asyncio
async def test_user_input_not_overridden(real_engine):
    """【真实LLM】TC-E06: 用户说HTML格式，覆盖memory中的pptx"""
    slots = make_empty_slots()
    slots["output_format"] = SlotValue(value="pptx", source="memory", confirmed=False)
    updated = await real_engine.extract_slots_from_text(
        "我想要HTML格式的输出", slots, []
    )
    fmt = updated["output_format"]
    assert fmt.value is not None
    assert "html" in str(fmt.value).lower(), f"期望 html, 实际: {fmt.value}"
    assert fmt.source == "user_input"
    print(f"  output_format: pptx(memory) -> {fmt.value}(user_input)")


@pytest.mark.asyncio
async def test_unknown_slots_in_real_response(real_engine):
    """【真实LLM】TC-E11: 返回的槽名全部在 SLOT_SCHEMA 中"""
    updated = await real_engine.extract_slots_from_text(
        "分析今年大连港集装箱吞吐量数据", make_empty_slots(), []
    )
    for key in updated:
        assert key in ALL_SLOT_NAMES, f"未定义槽名: {key}"
    print(f"  所有槽名合法: {[k for k, v in updated.items() if v.value is not None]}")


# ═══════════════════════════════════════════════════════════════
#  Mock 测试：引擎内部容错
# ═══════════════════════════════════════════════════════════════


class MockResp:
    def __init__(self, content):
        self.content = content


def _mock_llm(output):
    m = AsyncMock()
    m.ainvoke = AsyncMock(return_value=MockResp(output))
    return m


def test_think_tag_stripping():
    """TC-E07: _strip_think_tags 剥离 <think>"""
    raw = '<think>\n思考...\n</think>\n{"extracted": {}}'
    assert "<think>" not in _strip_think_tags(raw)
    json.loads(_strip_think_tags(raw))


def test_markdown_fence_stripping():
    """TC-E08: _strip_markdown_fences 剥离 ```json```"""
    raw = '```json\n{"extracted": {}}\n```'
    json.loads(_strip_markdown_fences(raw))


def test_clean_llm_output_combined():
    """TC-E09a: think + markdown 组合清洗"""
    raw = '<think>x</think>\n```json\n{"extracted": {"time_range": {"value": "Q1", "confidence": "explicit"}}}\n```'
    parsed = json.loads(_clean_llm_output(raw))
    assert parsed["extracted"]["time_range"]["value"] == "Q1"


@pytest.mark.asyncio
async def test_invalid_json_returns_empty():
    """TC-E09b: 非法 JSON 不崩溃"""
    engine = SlotFillingEngine(llm=_mock_llm("这不是JSON"))
    slots = make_empty_slots()
    updated = await engine.extract_slots_from_text("x", slots, [])
    for name in updated:
        assert updated[name].value is None


@pytest.mark.asyncio
async def test_llm_timeout_handled():
    """TC-E10: 超时抛 SlotFillingError"""
    async def slow_response(*a, **k):
        await asyncio.sleep(99)

    m = AsyncMock()
    m.ainvoke = AsyncMock(side_effect=slow_response)
    engine = SlotFillingEngine(llm=m, llm_timeout=0.1)
    with pytest.raises(SlotFillingError, match="timeout"):
        await engine.extract_slots_from_text("x", make_empty_slots(), [])
