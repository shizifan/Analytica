"""Perception Layer CLI Demo — 演示 Slot 填充多轮对话。

用法:
    uv run python -m backend.demo_perception

场景 A: "上个月集装箱吞吐量是多少" → 0 轮追问
场景 B: "分析货量趋势" → 追问 time_range、output_complexity
场景 C: "做一份港口运营分析报告" → full_report，追问时间范围和格式
场景 D: "按你理解执行" → 所有空槽取推断/默认值
"""
from __future__ import annotations

import asyncio
import json
import sys
from typing import Any

from backend.agent.perception import SlotFillingEngine, SLOT_MEANINGS
from backend.models.schemas import SlotValue, ALL_SLOT_NAMES


def print_slot_table(slots: dict[str, SlotValue]) -> None:
    """Print slot status as a formatted table."""
    print("\n┌─────────────────────┬──────────────────────────────┬──────────────┬──────────┐")
    print("│ 槽位名称            │ 值                           │ 来源         │ 已确认   │")
    print("├─────────────────────┼──────────────────────────────┼──────────────┼──────────┤")
    for name in ALL_SLOT_NAMES:
        sv = slots.get(name)
        if sv is None:
            val_str = "None"
            source = "-"
            confirmed = "-"
        else:
            val = sv.value
            if val is None:
                val_str = "None"
            elif isinstance(val, dict):
                val_str = json.dumps(val, ensure_ascii=False)
            elif isinstance(val, list):
                val_str = ", ".join(str(v) for v in val)
            else:
                val_str = str(val)
            if len(val_str) > 28:
                val_str = val_str[:25] + "..."
            source = sv.source
            confirmed = "✓" if sv.confirmed else "✗"
        print(f"│ {name:<19} │ {val_str:<28} │ {source:<12} │ {confirmed:<8} │")
    print("└─────────────────────┴──────────────────────────────┴──────────────┴──────────┘")


class MockLLM:
    """Mock LLM for CLI demo that generates deterministic responses."""

    def __init__(self):
        self._call_count = 0

    async def ainvoke(self, prompt: str) -> Any:
        """Simulate LLM response based on prompt content."""
        self._call_count += 1

        # If it's a clarification question prompt
        if "需要追问的槽位" in prompt:
            # Extract the target slot name from the prompt "名称：xxx"
            target_slot = ""
            for line in prompt.split("\n"):
                if line.strip().startswith("名称："):
                    target_slot = line.strip().replace("名称：", "").strip()
                    break
            if target_slot == "time_range":
                return MockResponse("请问您想分析哪个时间段的数据？比如「上个月」「今年Q1」「2025年全年」？")
            elif target_slot == "output_complexity":
                return MockResponse("请问您需要怎样的分析结果？简单数据查询（simple_table）、图文分析（chart_text）、还是完整报告（full_report）？")
            elif target_slot == "output_format":
                return MockResponse("请问您希望报告以什么格式输出？支持 DOCX、PPTX、PDF 格式。")
            elif target_slot == "attribution_needed":
                return MockResponse("请问是否需要归因分析？即分析数据变化背后的原因。")
            elif target_slot == "predictive_needed":
                return MockResponse("请问是否需要预测分析？即基于历史数据预测未来趋势。")
            return MockResponse("请提供更多信息以便继续分析。")

        # Slot extraction prompt — analyze the input text
        text = ""
        if "【用户最新输入】" in prompt:
            parts = prompt.split("【用户最新输入】")
            if len(parts) > 1:
                text_part = parts[1].split("【")[0].strip()
                text = text_part

        extracted = {}

        # Scene A: "上个月集装箱吞吐量是多少"
        if "上个月" in text and "吞吐量" in text:
            extracted = {
                "analysis_subject": {"value": ["集装箱吞吐量"], "evidence": "集装箱吞吐量", "confidence": "explicit"},
                "time_range": {"value": {"start": "2026-03-01", "end": "2026-03-31", "description": "上个月"}, "evidence": "上个月", "confidence": "explicit"},
                "output_complexity": {"value": "simple_table", "evidence": "是多少", "confidence": "implicit"},
            }
        # Scene C: "做一份港口运营分析报告"
        elif "报告" in text or "分析报告" in text:
            extracted = {
                "analysis_subject": {"value": ["港口运营"], "evidence": "港口运营", "confidence": "explicit"},
                "output_complexity": {"value": "full_report", "evidence": "分析报告", "confidence": "explicit"},
            }
        # Scene B: "分析货量趋势"
        elif "趋势" in text or "分析" in text:
            if "货量" in text or "吞吐" in text:
                extracted["analysis_subject"] = {"value": ["货量"], "evidence": "货量", "confidence": "explicit"}
            if "趋势" in text:
                extracted["output_complexity"] = {"value": "chart_text", "evidence": "趋势", "confidence": "implicit"}

        # Time range answers
        if any(kw in text for kw in ["Q1", "q1", "第一季度"]):
            extracted["time_range"] = {"value": {"start": "2026-01-01", "end": "2026-03-31", "description": "2026年Q1"}, "evidence": text, "confidence": "explicit"}
        elif "去年" in text:
            extracted["time_range"] = {"value": {"start": "2025-01-01", "end": "2025-12-31", "description": "去年"}, "evidence": "去年", "confidence": "explicit"}
        elif any(kw in text for kw in ["上个月", "3月"]):
            extracted["time_range"] = {"value": {"start": "2026-03-01", "end": "2026-03-31", "description": "上个月"}, "evidence": text, "confidence": "explicit"}

        # Format answers
        if "pptx" in text.lower() or "PPT" in text:
            extracted["output_format"] = {"value": "pptx", "evidence": "PPTX", "confidence": "explicit"}
        elif "docx" in text.lower():
            extracted["output_format"] = {"value": "docx", "evidence": "DOCX", "confidence": "explicit"}
        elif "pdf" in text.lower():
            extracted["output_format"] = {"value": "pdf", "evidence": "PDF", "confidence": "explicit"}

        # Yes/No for attribution/predictive
        if text in ("是", "是的", "需要", "yes", "要"):
            if "attribution_needed" in prompt:
                extracted["attribution_needed"] = {"value": True, "evidence": text, "confidence": "explicit"}
            if "predictive_needed" in prompt:
                extracted["predictive_needed"] = {"value": True, "evidence": text, "confidence": "explicit"}

        return MockResponse(json.dumps({"extracted": extracted}, ensure_ascii=False))


class MockResponse:
    def __init__(self, content: str):
        self.content = content


async def run_interactive_demo(user_memory: dict[str, Any] | None = None) -> None:
    """Run interactive demo session."""
    if user_memory is None:
        user_memory = {}

    mock_llm = MockLLM()
    engine = SlotFillingEngine(llm=mock_llm, max_clarification_rounds=5)

    print("\n" + "=" * 60)
    if user_memory:
        print(f"【记忆预填充】{json.dumps(user_memory, ensure_ascii=False)}")
    else:
        print("【无记忆预填充】")
    print("=" * 60)

    # Initialize slots
    slots = engine.initialize_slots(user_memory)
    conversation_history: list[dict[str, str]] = []
    clarification_round = 0

    print("\n请输入分析需求（输入 quit 退出）：")

    while True:
        user_input = input("\n🧑 用户: ").strip()
        if user_input.lower() in ("quit", "exit", "q"):
            print("退出会话。")
            break

        conversation_history.append({"role": "user", "content": user_input})

        # Check bypass
        bypass = await engine.handle_bypass(user_input, slots)
        if bypass.get("bypass_triggered"):
            print("\n🤖 系统: 好的，按我的理解为您执行分析。")
            print_slot_table(slots)
            intent = engine.build_structured_intent(slots, user_input)
            print("\n✅ StructuredIntent:")
            print(json.dumps(intent.model_dump(), ensure_ascii=False, indent=2, default=str))
            break

        # Extract slots
        slots = await engine.extract_slots_from_text(
            user_input, slots,
            conversation_history[:-1] if len(conversation_history) > 1 else []
        )

        print_slot_table(slots)

        # Get complexity
        complexity = None
        comp_slot = slots.get("output_complexity")
        if comp_slot and comp_slot.value:
            complexity = comp_slot.value

        # Check empty
        empty = engine.get_empty_required_slots(slots, complexity)
        clarification_round += 1

        if empty:
            if clarification_round > engine.max_clarification_rounds:
                engine.handle_max_rounds_reached(slots)
                print("\n⚠️ 达到最大追问轮数，使用默认值。")
                print_slot_table(slots)
                intent = engine.build_structured_intent(slots, user_input)
                print("\n✅ StructuredIntent:")
                print(json.dumps(intent.model_dump(), ensure_ascii=False, indent=2, default=str))
                break

            target = empty[0]
            question = await engine.generate_clarification_question(target, slots)
            print(f"\n🤖 追问 [{target}]: {question}")
            conversation_history.append({"role": "assistant", "content": question})
        else:
            intent = engine.build_structured_intent(slots, conversation_history[0]["content"])
            print(f"\n🤖 系统: 已理解您的分析需求：{intent.analysis_goal}")
            print("\n✅ StructuredIntent:")
            print(json.dumps(intent.model_dump(), ensure_ascii=False, indent=2, default=str))
            break


async def main():
    print("=" * 60)
    print("  Analytica 感知层 CLI Demo")
    print("  Phase 1 · Slot Filling Engine")
    print("=" * 60)

    print("\n【模式选择】")
    print("1. 交互模式（手动输入）")
    print("2. 自动演示（4 个场景自动运行）")

    choice = input("\n请选择 (1/2): ").strip()

    if choice == "1":
        print("\n--- 第 1 轮：无记忆 ---")
        await run_interactive_demo()

        cont = input("\n是否进行第 2 轮（带记忆预填充）？(y/n): ").strip()
        if cont.lower() == "y":
            print("\n--- 第 2 轮：带记忆预填充 ---")
            await run_interactive_demo(
                user_memory={"output_format": "pptx", "time_granularity": "monthly"}
            )
    else:
        await run_auto_scenarios()


async def run_auto_scenarios():
    """Run automated demo scenarios."""
    mock_llm = MockLLM()

    scenarios = [
        {
            "name": "场景 A：简单查询",
            "inputs": ["上个月集装箱吞吐量是多少"],
            "memory": {},
        },
        {
            "name": "场景 B：模糊查询",
            "inputs": ["分析货量趋势", "今年Q1"],
            "memory": {},
        },
        {
            "name": "场景 C：完整报告",
            "inputs": ["做一份港口运营分析报告", "上个月", "PPTX"],
            "memory": {},
        },
        {
            "name": "场景 D：按你理解执行",
            "inputs": ["分析货量趋势", "按你理解执行"],
            "memory": {},
        },
    ]

    for scenario in scenarios:
        print("\n" + "=" * 60)
        print(f"  {scenario['name']}")
        print("=" * 60)

        engine = SlotFillingEngine(llm=mock_llm, max_clarification_rounds=5)
        slots = engine.initialize_slots(scenario["memory"])
        conversation_history: list[dict[str, str]] = []
        round_num = 0

        for user_input in scenario["inputs"]:
            print(f"\n🧑 用户: {user_input}")
            conversation_history.append({"role": "user", "content": user_input})

            # Check bypass
            bypass = await engine.handle_bypass(user_input, slots)
            if bypass.get("bypass_triggered"):
                print("🤖 系统: 好的，按我的理解为您执行分析。")
                print_slot_table(slots)
                intent = engine.build_structured_intent(slots, conversation_history[0]["content"])
                print("\n✅ StructuredIntent:")
                print(json.dumps(intent.model_dump(), ensure_ascii=False, indent=2, default=str))
                break

            # Extract
            slots = await engine.extract_slots_from_text(
                user_input, slots,
                conversation_history[:-1] if len(conversation_history) > 1 else []
            )
            print_slot_table(slots)

            complexity = None
            comp_slot = slots.get("output_complexity")
            if comp_slot and comp_slot.value:
                complexity = comp_slot.value

            empty = engine.get_empty_required_slots(slots, complexity)
            round_num += 1

            if empty:
                target = empty[0]
                question = await engine.generate_clarification_question(target, slots)
                print(f"\n🤖 追问 [{target}]: {question}")
                conversation_history.append({"role": "assistant", "content": question})
            else:
                intent = engine.build_structured_intent(slots, conversation_history[0]["content"])
                print(f"\n🤖 系统: 已理解您的分析需求：{intent.analysis_goal}")
                print("\n✅ StructuredIntent:")
                print(json.dumps(intent.model_dump(), ensure_ascii=False, indent=2, default=str))
                break

        print()


if __name__ == "__main__":
    asyncio.run(main())
