"""V6 §9.2.5 — multi-turn intent matrix.

Verifies that ``run_perception`` (continuation path) produces correct
``turn_type`` / clarification target / merged slots from a single LLM
shot. Uses an in-process LLM monkey-patch instead of ``recorded_llm``
so the suite stays in default ``replay`` mode without depending on
cached prompts.

Also covers the parser / merger building blocks (`_parse_multiturn_
intent_payload`, `_merge_slots_with_delta`) so failures localise
quickly when the matrix regresses.
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from backend.agent import perception as perception_mod
from backend.agent.perception import (
    _merge_slots_with_delta,
    _parse_multiturn_intent_payload,
    run_perception,
)


# ── monkeypatch helper: drive _call_multiturn_intent_llm directly ────

class _ScriptedLLM:
    """Returns a pre-baked JSON string. Optional ``classifier`` callable
    overrides the static script per-prompt for the matrix test."""

    def __init__(
        self,
        payload: dict[str, Any] | None = None,
        classifier=None,
    ):
        self._payload = payload or {}
        self._classifier = classifier
        self.calls: list[str] = []

    async def __call__(self, prompt: str, *, timeout: float = 60.0) -> str:
        self.calls.append(prompt)
        if self._classifier is not None:
            payload = self._classifier(prompt)
        else:
            payload = self._payload
        return json.dumps(payload, ensure_ascii=False)


# ── parser / merger tests ─────────────────────────────────────

class TestParser:

    def test_normalises_invalid_turn_type_to_continue(self):
        result = _parse_multiturn_intent_payload(json.dumps({
            "turn_type": "garbage",
            "structured_intent": {"slots": {}},
        }))
        assert result["turn_type"] == "continue"

    def test_supplies_defaults_for_missing_fields(self):
        result = _parse_multiturn_intent_payload(json.dumps({"turn_type": "continue"}))
        assert result["needs_clarification"] is False
        assert result["ask_target_slots"] == []
        assert result["structured_intent"] == {}
        assert result["slot_delta"] == {}

    def test_invalid_json_falls_back_to_continue(self):
        result = _parse_multiturn_intent_payload("not-json")
        assert result["turn_type"] == "continue"
        assert "parse_failed" in (result.get("reasoning") or "")

    def test_strips_think_blocks_and_markdown_fences(self):
        raw = "<think>blah</think>\n```json\n" + json.dumps({"turn_type": "amend"}) + "\n```"
        result = _parse_multiturn_intent_payload(raw)
        assert result["turn_type"] == "amend"


class TestMergeSlots:

    def test_delta_overrides_inferred_value(self):
        prev = {"region": {"value": "全港", "source": "inferred", "confirmed": False}}
        delta = {"region": {"value": "大窑湾港区", "evidence": "用户输入"}}
        merged = _merge_slots_with_delta(prev, delta, structured_intent=None)
        assert merged["region"]["value"] == "大窑湾港区"
        assert merged["region"]["source"] == "user_input"

    def test_intent_slots_fill_holes_only(self):
        prev = {"region": {"value": "大窑湾港区", "source": "user_input"}}
        intent = {"slots": {
            "region": {"value": "全港", "source": "inferred"},  # should NOT overwrite
            "comparison_type": {"value": "yoy", "source": "inferred"},
        }}
        merged = _merge_slots_with_delta(prev, slot_delta={}, structured_intent=intent)
        assert merged["region"]["value"] == "大窑湾港区"  # unchanged
        assert merged["comparison_type"]["value"] == "yoy"

    def test_empty_inputs_return_empty_dict(self):
        assert _merge_slots_with_delta({}, None, None) == {}


# ── run_perception flow under scripted LLM ────────────────────

class TestRunPerceptionRouting:

    @pytest.mark.asyncio
    async def test_first_turn_skips_multiturn_path(self, monkeypatch):
        """When state has no filled slots, run_perception must NOT call
        the multi-turn LLM — even if _multiturn_context is present."""
        scripted = _ScriptedLLM(payload={"turn_type": "amend"})
        monkeypatch.setattr(
            perception_mod, "_call_multiturn_intent_llm", scripted,
        )
        # First turn helpers (SLOT_EXTRACTION_PROMPT path) hit DB +
        # SlotFillingEngine — we don't exercise the full first-turn
        # path here, but we DO verify the multi-turn LLM isn't
        # accidentally called.
        called_first_turn = {"flag": False}

        async def fake_first_turn(state, profile=None):
            called_first_turn["flag"] = True
            return state

        monkeypatch.setattr(
            perception_mod, "_run_first_turn_perception", fake_first_turn,
        )

        state = {
            "session_id": "s1",
            "user_id": "u1",
            "slots": {},  # no filled slots
            "_multiturn_context": {"turn_index": 0, "workspace_manifest": {}},
            "messages": [{"role": "user", "content": "hello"}],
        }
        await run_perception(state)
        assert called_first_turn["flag"] is True
        assert scripted.calls == []  # multi-turn LLM never called

    @pytest.mark.asyncio
    async def test_continuation_path_routes_through_multiturn_llm(self, monkeypatch):
        scripted = _ScriptedLLM(payload={
            "turn_type": "continue",
            "reasoning": "drill down",
            "needs_clarification": False,
            "ask_target_slots": [],
            "structured_intent": {"analysis_goal": "按港区拆分", "slots": {}},
            "slot_delta": {"data_granularity": {"value": "zone", "evidence": "按港区"}},
        })
        monkeypatch.setattr(
            perception_mod, "_call_multiturn_intent_llm", scripted,
        )

        state = {
            "session_id": "s1",
            "user_id": "u1",
            "turn_index": 1,
            "slots": {
                "analysis_subject": {"value": ["吞吐量"], "source": "user_input"},
            },
            "_multiturn_context": {
                "turn_index": 1,
                "latest_summary": {"plan_title": "R0 — 吞吐量"},
                "workspace_manifest": {"items": {}},
            },
            "messages": [
                {"role": "user", "content": "分析 Q1 吞吐量"},
                {"role": "assistant", "content": "..."},
                {"role": "user", "content": "按港区拆分看看"},
            ],
        }
        result = await run_perception(state)
        assert len(scripted.calls) == 1
        assert result["turn_type"] == "continue"
        assert result["structured_intent"]["analysis_goal"] == "按港区拆分"
        assert result["slot_delta"]["data_granularity"]["value"] == "zone"
        assert result["current_target_slot"] is None
        # delta was merged into slots
        assert result["slots"]["data_granularity"]["value"] == "zone"

    @pytest.mark.asyncio
    async def test_continuation_path_emits_clarification_message(self, monkeypatch):
        scripted = _ScriptedLLM(payload={
            "turn_type": "continue",
            "reasoning": "vague",
            "needs_clarification": True,
            "ask_target_slots": ["time_range"],
            "structured_intent": {"slots": {}},
            "slot_delta": {},
        })
        monkeypatch.setattr(
            perception_mod, "_call_multiturn_intent_llm", scripted,
        )
        state = {
            "session_id": "s1",
            "user_id": "u1",
            "turn_index": 1,
            "slots": {"analysis_subject": {"value": ["吞吐量"], "source": "user_input"}},
            "_multiturn_context": {
                "turn_index": 1, "workspace_manifest": {"items": {}},
            },
            "messages": [{"role": "user", "content": "深入看看"}],
        }
        result = await run_perception(state)
        assert result["current_target_slot"] == "time_range"
        assert result["structured_intent"] is None
        assert any(
            m.get("role") == "assistant" and "time_range" in (m.get("content") or "")
            for m in result["messages"]
        )


# ── intent matrix (spec §9.2.5) ───────────────────────────────

INTENT_MATRIX: list[tuple[str, str]] = [
    # ── new ──
    ("换个话题，分析下设备完好率", "new"),
    ("新分析：港口投资回报", "new"),
    ("不相关的问题，集装箱客户名单怎么导出", "new"),

    # ── continue（深化/钻取）──
    ("按港区拆分看看", "continue"),
    ("为什么 3 月环比下降这么多", "continue"),
    ("和去年 Q1 对比一下", "continue"),
    ("详细说说大窑湾港区", "continue"),

    # ── continue（参数变化）──
    ("把时间范围扩大到全年", "continue"),
    ("再加 2024 年的数据做对比", "continue"),
    ("把粒度改成日度", "continue"),

    # ── amend（明确格式）──
    ("再加一个 PPTX 报告", "amend"),
    ("也来一份 Word", "amend"),
    ("还要个 PPT", "amend"),
    ("把 HTML 换成 PPTX", "amend"),
    ("导出为 PDF", "amend"),

    # ── 边界（应归 continue 而非 amend）──
    ("换个角度看吞吐量", "continue"),
    ("把分析换成同比口径", "continue"),
]


_USER_MSG_REGEX = __import__("re").compile(
    r"【本轮用户最新消息】\s*\n(.+?)(?:\n【|\Z)", __import__("re").DOTALL,
)


def _matrix_classifier(prompt: str) -> dict[str, Any]:
    """Lightweight stand-in for the real LLM. Pulls the latest user
    message from the prompt and applies a few heuristics that mimic
    the prompt's stated rules.

    This is NOT a substitute for the real LLM evaluation — it lets us
    keep the matrix file under default test selection and surface
    parser / state-merge regressions early. Real-LLM accuracy is
    measured by a separate `llm_replay`-marked run.
    """
    m = _USER_MSG_REGEX.search(prompt)
    msg = m.group(1).strip() if m else ""
    # Simplified rules — close to the prompt's "must be明确的格式词" logic.
    amend_format_tokens = ("PPTX", "PPT", "Word", "PDF", "HTML")
    msg_lower = msg.lower()
    if any(tok.lower() in msg_lower for tok in amend_format_tokens):
        # Edge case: "把 HTML 换成 PPTX" mentions both — still amend.
        # Edge case: "把分析换成同比口径" mentions 换成 but no format token → continue.
        return {
            "turn_type": "amend",
            "needs_clarification": False,
            "ask_target_slots": [],
            "structured_intent": {"analysis_goal": msg, "slots": {}},
            "slot_delta": {},
        }
    new_topic_signals = ("换个话题", "新分析", "不相关", "完全不同的", "重新分析")
    if any(sig in msg for sig in new_topic_signals):
        return {
            "turn_type": "new",
            "needs_clarification": False,
            "ask_target_slots": [],
            "structured_intent": {"analysis_goal": msg, "slots": {}},
            "slot_delta": {},
        }
    return {
        "turn_type": "continue",
        "needs_clarification": False,
        "ask_target_slots": [],
        "structured_intent": {"analysis_goal": msg, "slots": {}},
        "slot_delta": {},
    }


@pytest.mark.parametrize("user_msg, expected_turn", INTENT_MATRIX)
@pytest.mark.asyncio
async def test_intent_matrix_with_scripted_llm(
    monkeypatch, user_msg, expected_turn,
):
    """All 17 spec §9.2.5 cases pass through ``_run_multiturn_perception``.
    The scripted LLM matches the prompt's stated rules — failures here
    flag a regression in the prompt → parser → state-merge path, not a
    weakness of the actual LLM."""
    scripted = _ScriptedLLM(classifier=_matrix_classifier)
    monkeypatch.setattr(
        perception_mod, "_call_multiturn_intent_llm", scripted,
    )

    state = {
        "session_id": "s1",
        "user_id": "u1",
        "turn_index": 1,
        "slots": {
            "analysis_subject": {"value": ["吞吐量"], "source": "user_input"},
            "time_range": {
                "value": {"start": "2026-01-01", "end": "2026-03-31"},
                "source": "user_input",
            },
        },
        "_multiturn_context": {
            "turn_index": 1,
            "latest_summary": {"plan_title": "R0 — 吞吐量"},
            "workspace_manifest": {"items": {}},
        },
        "messages": [
            {"role": "user", "content": "分析 Q1 吞吐量"},
            {"role": "assistant", "content": "..."},
            {"role": "user", "content": user_msg},
        ],
    }
    result = await run_perception(state)
    assert result["turn_type"] == expected_turn, (
        f"msg={user_msg!r} expected {expected_turn} "
        f"got {result['turn_type']}"
    )
