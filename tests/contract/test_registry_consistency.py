"""Registry / employee profile / api_registry self-consistency.

Catches the kind of bug where:
  - DB still references endpoints that were removed from api_registry
  - YAML and DB.tools list drift apart (reseed wasn't run)
  - A tool is registered with missing metadata
  - A profile validates against an outdated registry copy
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from backend.tools.loader import load_all_tools
from backend.tools.registry import ToolRegistry
from backend.agent.api_registry import BY_NAME

pytestmark = pytest.mark.contract


def _load_yaml_employees() -> list[dict]:
    yaml_dir = Path(__file__).resolve().parent.parent.parent / "employees"
    out = []
    for f in sorted(yaml_dir.glob("*.yaml")):
        out.append(yaml.safe_load(f.read_text(encoding="utf-8")))
    return out


@pytest.fixture(scope="module", autouse=True)
def _ensure_tools_loaded():
    """Tools register at import time — load them once before any test runs."""
    load_all_tools()


# ── Tool registry ─────────────────────────────────────────────


def test_tool_registry_not_empty():
    assert len(ToolRegistry.get_instance().tool_ids) > 0, (
        "no tools registered — load_all_tools() failed silently?"
    )


def test_every_registered_tool_has_metadata():
    """Each tool must declare id, category, description, input_spec, output_spec.
    Empty strings are acceptable for input/output_spec but not for id/category/description.
    """
    registry = ToolRegistry.get_instance()
    for tid in sorted(registry.tool_ids):
        tool = registry.get_tool(tid)
        assert tool is not None
        assert tool.tool_id == tid, f"{tid}: tool.tool_id mismatch"
        assert tool.description, f"{tid}: empty description"
        assert tool.category, f"{tid}: missing category"


def test_no_legacy_skill_prefix_in_tool_ids():
    """All tool ids must use `tool_` prefix (skill→tool migration complete)."""
    registry = ToolRegistry.get_instance()
    legacy = [tid for tid in registry.tool_ids if tid.startswith("skill_")]
    assert legacy == [], f"legacy `skill_*` tool ids still registered: {legacy}"


# ── api_registry ──────────────────────────────────────────────


def test_api_registry_not_empty():
    assert len(BY_NAME) > 0


def test_api_registry_resolvable_by_name():
    """Every endpoint accessible by name."""
    from backend.agent.api_registry import get_endpoint
    for name in BY_NAME:
        ep = get_endpoint(name)
        assert ep is not None, f"endpoint {name!r} in BY_NAME but get_endpoint returned None"
        assert ep.name == name


# ── Employee profiles ─────────────────────────────────────────


def test_all_yaml_employees_validate_against_registry():
    """Each YAML file must validate cleanly against the live registry —
    catches stale endpoints / unknown tools that would otherwise survive
    until runtime planning failure."""
    from backend.employees.profile import EmployeeProfile
    yaml_dir = Path(__file__).resolve().parent.parent.parent / "employees"
    for yaml_path in sorted(yaml_dir.glob("*.yaml")):
        profile = EmployeeProfile.from_yaml(yaml_path)
        errors = profile.validate_against_registry()
        assert errors == [], (
            f"{yaml_path.name}: profile validation errors: {errors}"
        )


def test_employee_get_endpoint_names_filters_stale():
    """Critical regression: even if a profile references a stale endpoint,
    `get_endpoint_names()` must filter it out (prevents LLM from picking a
    dead endpoint and the orphan-task bug class)."""
    from backend.employees.profile import EmployeeProfile

    p = EmployeeProfile(
        employee_id="test_filter",
        name="t", domains=["D6"], tools=["tool_api_fetch"],
        endpoints=[
            "getInvestPlanByYear",      # real
            "getCostProjectFinishByYear",  # dead (was removed from registry)
        ],
    )
    eps = p.get_endpoint_names()
    assert "getInvestPlanByYear" in eps
    assert "getCostProjectFinishByYear" not in eps, (
        "stale endpoint not filtered — LLM could pick it and trigger orphan-task bug"
    )


def test_yaml_tools_present_in_registry():
    """Every tool listed in any employee YAML must be registered."""
    registry_ids = ToolRegistry.get_instance().tool_ids
    for emp in _load_yaml_employees():
        for tool_id in emp.get("tools", []):
            assert tool_id in registry_ids, (
                f"{emp['employee_id']}: yaml lists tool {tool_id!r} not in registry"
            )


def test_yaml_endpoints_present_in_api_registry():
    """Every endpoint listed in any employee YAML must exist in api_registry.
    (Empty endpoints list = derive-from-domains, which is automatically
    consistent.)"""
    for emp in _load_yaml_employees():
        listed = emp.get("endpoints", []) or []
        unknown = [e for e in listed if e not in BY_NAME]
        assert unknown == [], (
            f"{emp['employee_id']}: unknown endpoints in yaml: {unknown}"
        )
