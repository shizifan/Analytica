"""Cross-cutting degradation channel — basic record / summarise behaviour."""
from __future__ import annotations

from backend.agent.degradation import (
    DegradationEvent,
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    record,
    summarize,
)


def test_record_appends_to_state():
    state: dict = {}
    record(state, DegradationEvent(layer="planning", severity=SEVERITY_WARN, reason="x"))
    assert len(state["degradations"]) == 1
    record(state, DegradationEvent(layer="execution", severity=SEVERITY_ERROR, reason="y"))
    assert len(state["degradations"]) == 2


def test_summarize_returns_none_when_empty():
    assert summarize({}) is None
    assert summarize({"degradations": []}) is None


def test_summarize_groups_by_severity():
    state: dict = {}
    record(state, DegradationEvent(layer="planning", severity=SEVERITY_WARN, reason="task dropped"))
    record(state, DegradationEvent(layer="collector", severity=SEVERITY_INFO, reason="m-code resolved"))
    record(state, DegradationEvent(layer="execution", severity=SEVERITY_ERROR, reason="data missing"))
    out = summarize(state)
    assert out is not None
    # Errors first, then warns, then info
    assert out.index("错误降级") < out.index("一般降级") < out.index("信息")
    assert "task dropped" in out
    assert "m-code resolved" in out
    assert "data missing" in out
