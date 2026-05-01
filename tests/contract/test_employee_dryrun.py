"""P3.1-1 — admin prompt dry-run endpoints.

Pins:
  * ``_profile_with_overrides`` merges partial perception/planning overrides
    onto the saved profile without mutating the manager-cached copy.
  * The dry-run endpoints accept the documented request shapes and reject
    malformed input with a 4xx (so the admin UI knows to keep "save"
    disabled).
  * 404 propagates when the employee doesn't exist.

LLM-touching paths are mocked — these tests must run on the default
regression suite without hitting any real model.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from backend.main import _profile_with_overrides, app

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module", autouse=True)
def _ensure_tools_loaded():
    """Tool registry needs explicit loading; employees are seeded into the
    DB and loaded into ``EmployeeManager`` by the session-scope conftest
    fixture, so we don't touch them here."""
    from backend.tools.loader import load_all_tools
    load_all_tools()


# ── Override merge helper ───────────────────────────────────────────


def test_override_helper_applies_perception_override():
    p = _profile_with_overrides(
        "asset_investment",
        perception_override={"system_prompt_suffix": "DRYRUN OVERRIDE"},
    )
    assert p.perception.system_prompt_suffix == "DRYRUN OVERRIDE"


def test_override_helper_applies_planning_override():
    p = _profile_with_overrides(
        "asset_investment",
        planning_override={"prompt_suffix": "DRYRUN PLANNING"},
    )
    assert p.planning.prompt_suffix == "DRYRUN PLANNING"


def test_override_helper_does_not_mutate_cached_profile():
    """Crucial: the manager singleton must keep its saved copy intact."""
    from backend.employees.manager import EmployeeManager

    saved = EmployeeManager.get_instance().get_employee("asset_investment")
    original_suffix = saved.perception.system_prompt_suffix

    _profile_with_overrides(
        "asset_investment",
        perception_override={"system_prompt_suffix": "TRANSIENT"},
    )

    after = EmployeeManager.get_instance().get_employee("asset_investment")
    assert after.perception.system_prompt_suffix == original_suffix


def test_override_helper_partial_merge_keeps_other_fields():
    """Override only ``system_prompt_suffix`` — ``extra_slots`` etc. survive."""
    p = _profile_with_overrides(
        "asset_investment",
        perception_override={"system_prompt_suffix": "X"},
    )
    # asset_investment.yaml defines several extra_slots; they must remain.
    assert p.perception.extra_slots, "extra_slots wiped by partial merge"


def test_override_helper_404_for_unknown_employee():
    with pytest.raises(HTTPException) as excinfo:
        _profile_with_overrides("does_not_exist")
    assert excinfo.value.status_code == 404


# ── HTTP endpoint contracts (LLM mocked) ────────────────────────────


@pytest.fixture
def client():
    return TestClient(app)


def test_dryrun_perception_requires_query(client):
    r = client.post(
        "/api/admin/employees/asset_investment/dryrun-perception",
        json={"query": ""},
    )
    assert r.status_code == 400
    assert "query" in r.json()["detail"]


def test_dryrun_perception_404_for_unknown_employee(client):
    r = client.post(
        "/api/admin/employees/missing_emp/dryrun-perception",
        json={"query": "hello"},
    )
    assert r.status_code == 404


def test_dryrun_perception_returns_intent_shape(client):
    """With mocked perception, the endpoint returns the documented keys."""
    fake_state = {
        "structured_intent": {"slots": {"analysis_subject": {"value": ["x"]}}},
        "empty_required_slots": ["time_range"],
        "current_target_slot": "time_range",
        "clarification_round": 1,
    }
    with patch("backend.agent.perception.run_perception", new=AsyncMock(return_value=fake_state)):
        r = client.post(
            "/api/admin/employees/asset_investment/dryrun-perception",
            json={"query": "查 2026 年资产净值", "perception": {"system_prompt_suffix": "X"}},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["structured_intent"] == fake_state["structured_intent"]
    assert body["empty_required_slots"] == ["time_range"]
    assert body["current_target_slot"] == "time_range"
    assert body["clarification_round"] == 1


def test_dryrun_perception_engine_failure_returns_422(client):
    with patch(
        "backend.agent.perception.run_perception",
        new=AsyncMock(side_effect=RuntimeError("LLM rejected prompt")),
    ):
        r = client.post(
            "/api/admin/employees/asset_investment/dryrun-perception",
            json={"query": "x"},
        )
    assert r.status_code == 422
    assert "perception 失败" in r.json()["detail"]


def test_dryrun_planning_requires_query_or_intent(client):
    r = client.post(
        "/api/admin/employees/asset_investment/dryrun-planning",
        json={},
    )
    assert r.status_code == 400


def test_dryrun_planning_uses_caller_intent(client):
    """If ``intent`` is supplied, perception is skipped — only planning runs."""
    intent = {
        "raw_query": "x",
        "analysis_goal": "x",
        "slots": {
            "analysis_subject": {"value": ["x"], "source": "user_input", "confirmed": True},
            "time_range": {
                "value": {"start": "2026-01-01", "end": "2026-12-31", "description": "2026"},
                "source": "user_input", "confirmed": True,
            },
            "output_complexity": {"value": "simple_table", "source": "user_input", "confirmed": True},
            "domain": {"value": "D5", "source": "user_input", "confirmed": True},
        },
    }

    class _FakePlan:
        version = 1
        tasks: list = []
        revision_log: list = []
        def model_dump(self):
            return {"version": 1, "tasks": [], "revision_log": []}

    with patch(
        "backend.agent.planning.PlanningEngine.generate_plan",
        new=AsyncMock(return_value=_FakePlan()),
    ), patch(
        "backend.agent.graph.build_llm", return_value=object(),
    ):
        r = client.post(
            "/api/admin/employees/asset_investment/dryrun-planning",
            json={"intent": intent},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["task_count"] == 0
    assert body["intent_used"] == intent
    assert body["plan"]["version"] == 1
