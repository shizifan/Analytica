"""Regression: report content collector must never silently drop items.

Bug 2026-04-25: when LLM partially populated `task_refs` (some sections had
them, others didn't), the strict-matching path threw away every item whose
source wasn't explicitly listed — losing 15 of 20 task outputs in one
observed run. The fix reassigns unmatched items to a fallback section and
records the event in ReportContent.degradations.
"""
from __future__ import annotations

from backend.tools.report._content_collector import (
    NarrativeItem,
    SectionContent,
    _associate,
)


def _items(*pairs):
    return [NarrativeItem(text=t, source_task=s) for s, t in pairs]


def test_no_task_refs_round_robin():
    """Backward-compatible path: when no section declares task_refs,
    items distribute round-robin across sections."""
    sections = [{"name": "A", "task_refs": []}, {"name": "B", "task_refs": []}]
    items = _items(("T1", "a"), ("T2", "b"), ("T3", "c"))
    out = _associate(sections, items)
    assert sum(len(s.items) for s in out) == 3


def test_full_task_refs_no_drop():
    """When every item's source is covered by task_refs, strict mapping wins."""
    sections = [
        {"name": "A", "task_refs": ["T1"]},
        {"name": "B", "task_refs": ["T2", "T3"]},
    ]
    items = _items(("T1", "a"), ("T2", "b"), ("T3", "c"))
    out = _associate(sections, items)
    assert [it.source_task for it in out[0].items] == ["T1"]
    assert sorted([it.source_task for it in out[1].items]) == ["T2", "T3"]


def test_partial_task_refs_unmatched_reassigned_not_dropped():
    """Bug fix: previously items with sources not in any task_refs were
    dropped. Now they go to the first section with no task_refs (catch-all),
    or '其他' if none exists. Total item count must equal input."""
    sections = [
        {"name": "概览", "task_refs": ["T1"]},  # has refs → strict mode triggers
        {"name": "明细", "task_refs": []},        # catch-all (no refs)
    ]
    items = _items(("T1", "a"), ("T2", "b"), ("T3", "c"))
    degradations: list[dict] = []
    out = _associate(sections, items, degradations=degradations)
    total = sum(len(s.items) for s in out)
    assert total == 3, "all items must be assigned, not dropped"
    # T1 → 概览; T2/T3 → 明细 (catch-all)
    assert [it.source_task for it in out[0].items] == ["T1"]
    assert sorted([it.source_task for it in out[1].items]) == ["T2", "T3"]
    # degradation was recorded
    assert len(degradations) == 1
    assert degradations[0]["count"] == 2
    assert degradations[0]["fallback_section"] == "明细"


def test_partial_task_refs_no_catchall_creates_other_section():
    """If every section has task_refs and unmatched items remain, a new
    '其他' section is appended (rather than overflowing into a wrong one)."""
    sections = [
        {"name": "概览", "task_refs": ["T1"]},
        {"name": "趋势", "task_refs": ["T2"]},
    ]
    items = _items(("T1", "a"), ("T2", "b"), ("T3", "c"))
    degradations: list[dict] = []
    out = _associate(sections, items, degradations=degradations)
    assert sum(len(s.items) for s in out) == 3
    # New "其他" section appended
    assert out[-1].name == "其他"
    assert [it.source_task for it in out[-1].items] == ["T3"]
    assert degradations[0]["fallback_section"] == "其他"


def test_empty_sections_default_to_overview():
    """Sanity: no sections at all → single '数据概览' built."""
    out = _associate([], _items(("T1", "x")))
    assert len(out) == 1
    assert out[0].name == "数据概览"
    assert len(out[0].items) == 1


def test_sanitize_report_structure_strips_task_refs():
    """`_sanitize_report_structure` (called in planning.py) must strip
    task_refs from sections so collector always takes round-robin path."""
    from backend.agent.planning import _sanitize_report_structure

    rs = {"sections": [
        {"name": "A", "task_refs": ["T1"]},
        {"name": "B"},
    ]}
    cleaned = _sanitize_report_structure(rs)
    for s in cleaned["sections"]:
        assert "task_refs" not in s
