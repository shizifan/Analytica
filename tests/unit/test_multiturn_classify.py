"""Unit tests for _classify_turn multi-turn intent classification.

V6 §4.4 deletes the keyword router. This file is slated for full
removal in S5 (spec §10.1); skipped at the module level during the
S4 → S5 transition so the suite stays green.
"""

import pytest

pytest.skip(
    "V6 §9.1 — _classify_turn deleted in S4; tests pending removal in S5",
    allow_module_level=True,
)


class TestClassifyTurn:
    """Test turn classification without LLM calls."""

    def test_first_turn_no_slots_returns_new(self):
        """First turn without prev slots should return 'new'."""
        prev_state = {"slots": {}}
        result = _classify_turn("分析今年Q1吞吐量", prev_state)
        assert result == "new"

    def test_amend_add_format(self):
        """'再加一个 PPTX' should be classified as 'amend'."""
        prev_state = {"slots": {"analysis_subject": {"value": "吞吐量"}}}
        result = _classify_turn("再加一个 PPTX 报告", prev_state)
        assert result == "amend"

    def test_amend_replace_format(self):
        """'换个格式' should be classified as 'amend'."""
        prev_state = {"slots": {"analysis_subject": {"value": "吞吐量"}}}
        result = _classify_turn("换成 PPTX 格式", prev_state)
        assert result == "amend"

    def test_explicit_new_topic(self):
        """Explicit new topic keywords should return 'new'."""
        prev_state = {"slots": {"analysis_subject": {"value": "吞吐量"}}}
        result = _classify_turn("换个话题，分析设备利用率", prev_state)
        assert result == "new"

        result2 = _classify_turn("新分析：设备利用率趋势", prev_state)
        assert result2 == "new"

    def test_continue_default(self):
        """A follow-up drill-down should default to 'continue'."""
        prev_state = {"slots": {"analysis_subject": {"value": "吞吐量"}}}
        result = _classify_turn("大连港为什么下降？", prev_state)
        assert result == "continue"

    def test_time_range_expansion_is_continue(self):
        """Expanding time range should be 'continue' (needs re-fetch)."""
        prev_state = {"slots": {"analysis_subject": {"value": "吞吐量"}}}
        result = _classify_turn("把时间范围扩展到去年全年", prev_state)
        assert result == "continue"


class TestClassifyTurnEdgeCases:
    """Edge cases for turn classification."""

    def test_empty_user_message(self):
        """Empty message with previous slots should still be 'continue'."""
        prev_state = {"slots": {"analysis_subject": {"value": "吞吐量"}}}
        result = _classify_turn("", prev_state)
        assert result == "continue"

    def test_new_topic_keyword_partial_match(self):
        """Partial keyword match should not trigger new topic detection."""
        prev_state = {"slots": {"analysis_subject": {"value": "吞吐量"}}}
        # "不相关" is not a substring of this message
        result = _classify_turn("给我更相关的分析", prev_state)
        assert result == "continue"
