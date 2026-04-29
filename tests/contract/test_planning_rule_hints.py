"""P3.2 — per-employee ``rule_hints`` override of ``PLANNING_RULE_HINTS``.

Pins:
  * ``resolve_rule_hint`` semantics — default / skip / override.
  * Single-round prompt builder honours overrides.
  * ``PlanningConfig.rule_hints`` Pydantic field accepts dict / empty.
  * Multi-round path also receives the override (regression for the
    pre-P3.2 leak where multi-round used hardcoded globals only).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.agent.planning import (
    PLANNING_RULE_HINTS,
    resolve_rule_hint,
)
from backend.employees.profile import PlanningConfig

pytestmark = pytest.mark.contract


# ── resolve_rule_hint ────────────────────────────────────────────────


def test_resolve_returns_global_default_when_overrides_none():
    for key in ("minimization", "time_param", "cargo_selection"):
        assert resolve_rule_hint(key, None) == PLANNING_RULE_HINTS[key]


def test_resolve_returns_global_default_when_key_absent():
    assert resolve_rule_hint("minimization", {"time_param": "X"}) == PLANNING_RULE_HINTS["minimization"]


def test_resolve_returns_empty_string_to_skip_section():
    assert resolve_rule_hint("cargo_selection", {"cargo_selection": ""}) == ""


def test_resolve_returns_override_when_non_empty_string():
    assert (
        resolve_rule_hint("minimization", {"minimization": "ONLY 1 fetch please"})
        == "ONLY 1 fetch please"
    )


def test_resolve_unknown_key_returns_empty():
    """Unknown keys must not crash — they have no global default."""
    assert resolve_rule_hint("not_a_real_rule", None) == ""


# ── PlanningConfig field ─────────────────────────────────────────────


def test_planning_config_default_rule_hints_is_empty_dict():
    cfg = PlanningConfig()
    assert cfg.rule_hints == {}


def test_planning_config_accepts_partial_rule_hints():
    cfg = PlanningConfig(rule_hints={"cargo_selection": ""})
    assert cfg.rule_hints == {"cargo_selection": ""}


# ── Single-round prompt builder honours overrides ────────────────────


def test_build_prompt_uses_override_when_employee_provides_rule_hints():
    """End-to-end: ``_build_prompt`` substitutes overrides into the template."""
    from backend.agent.planning import PlanningEngine

    engine = PlanningEngine(llm=None, llm_timeout=10.0, max_retries=1)
    intent = {
        "raw_query": "x",
        "analysis_goal": "x",
        "slots": {
            "analysis_subject": {"value": ["x"], "source": "user_input", "confirmed": True},
            "time_range": {"value": {"start": "2026-01-01", "end": "2026-12-31", "description": ""},
                           "source": "user_input", "confirmed": True},
            "output_complexity": {"value": "chart_text", "source": "user_input", "confirmed": True},
            "domain": {"value": "D1", "source": "user_input", "confirmed": True},
        },
    }
    overrides = {"minimization": "EMPLOYEE-MINIMIZATION-OVERRIDE"}
    out = engine._build_prompt(
        intent, "chart_text",
        rule_hints=overrides,
    )
    assert "EMPLOYEE-MINIMIZATION-OVERRIDE" in out
    # The default cargo_selection rule should still be present (no override).
    assert PLANNING_RULE_HINTS["cargo_selection"][:20] in out


def test_build_prompt_skips_section_when_override_is_empty_string():
    from backend.agent.planning import PlanningEngine

    engine = PlanningEngine(llm=None, llm_timeout=10.0, max_retries=1)
    intent = {
        "raw_query": "x",
        "analysis_goal": "x",
        "slots": {
            "analysis_subject": {"value": ["x"], "source": "user_input", "confirmed": True},
            "time_range": {"value": {"start": "2026-01-01", "end": "2026-12-31", "description": ""},
                           "source": "user_input", "confirmed": True},
            "output_complexity": {"value": "chart_text", "source": "user_input", "confirmed": True},
            "domain": {"value": "D1", "source": "user_input", "confirmed": True},
        },
    }
    out = engine._build_prompt(
        intent, "chart_text",
        rule_hints={"cargo_selection": ""},
    )
    # The cargo-selection default contains a recognizable Chinese phrase.
    # The skip override removes it from the rendered prompt.
    assert "货类匹配原则" not in out


# ── Multi-round path receives overrides too ─────────────────────────


async def test_section_call_uses_override_rule_hints(monkeypatch):
    """Multi-round per-section prompt builder must thread rule_hints in.

    Pre-P3.2 the section path used ``PLANNING_RULE_HINTS`` directly,
    silently ignoring employee overrides.
    """
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import PlanSection

    captured = {}

    async def _fake_invoke(self, prompt):
        captured["prompt"] = prompt
        # Return enough to short-circuit parsing without raising.
        return '{"tasks": []}'

    monkeypatch.setattr(PlanningEngine, "_invoke_llm", _fake_invoke)

    engine = PlanningEngine(llm=None, llm_timeout=10.0, max_retries=1)
    intent = {"raw_query": "x", "analysis_goal": "x", "slots": {
        "domain": {"value": "D1"},
    }}
    section = PlanSection(
        section_id="S1", name="x", description="", focus_metrics=[],
        endpoint_hints=["getWeatherForecast"], expected_task_count=2,
    )

    overrides = {"time_param": "ONLY-EMPLOYEE-TIME-RULE"}
    await engine._call_section_llm(
        intent, section, valid_tools={"tool_api_fetch"},
        valid_endpoints={"getWeatherForecast"},
        rule_hints=overrides,
    )
    assert "ONLY-EMPLOYEE-TIME-RULE" in captured["prompt"]


# ── P3.2 follow-up: section path also receives prompt_suffix ────────


async def test_section_call_renders_employee_cookbook(monkeypatch):
    """Multi-round section prompts must include the employee Cookbook
    (``planning.prompt_suffix``). Pre-fix it was silently dropped, so
    full_report queries got plain global guidance only."""
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import PlanSection

    captured = {}

    async def _fake_invoke(self, prompt):
        captured["prompt"] = prompt
        return '{"tasks": []}'

    monkeypatch.setattr(PlanningEngine, "_invoke_llm", _fake_invoke)

    engine = PlanningEngine(llm=None, llm_timeout=10.0, max_retries=1)
    intent = {"raw_query": "x", "analysis_goal": "x", "slots": {"domain": {"value": "D1"}}}
    section = PlanSection(
        section_id="S1", name="x", description="", focus_metrics=[],
        endpoint_hints=["getWeatherForecast"], expected_task_count=2,
    )

    await engine._call_section_llm(
        intent, section, valid_tools={"tool_api_fetch"},
        valid_endpoints={"getWeatherForecast"},
        prompt_suffix="MY EMPLOYEE COOKBOOK 2026",
    )
    assert "员工专属规划提示" in captured["prompt"]
    assert "MY EMPLOYEE COOKBOOK 2026" in captured["prompt"]


async def test_section_call_omits_cookbook_block_when_suffix_empty(monkeypatch):
    """Empty / missing cookbook → no cookbook block at all (cleaner prompt)."""
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import PlanSection

    captured = {}

    async def _fake_invoke(self, prompt):
        captured["prompt"] = prompt
        return '{"tasks": []}'

    monkeypatch.setattr(PlanningEngine, "_invoke_llm", _fake_invoke)

    engine = PlanningEngine(llm=None, llm_timeout=10.0, max_retries=1)
    intent = {"raw_query": "x", "analysis_goal": "x", "slots": {"domain": {"value": "D1"}}}
    section = PlanSection(
        section_id="S1", name="x", description="", focus_metrics=[],
        endpoint_hints=["getWeatherForecast"], expected_task_count=2,
    )

    await engine._call_section_llm(
        intent, section, valid_tools={"tool_api_fetch"},
        valid_endpoints={"getWeatherForecast"},
        prompt_suffix="",  # employee has no cookbook
    )
    assert "员工专属规划提示" not in captured["prompt"]
