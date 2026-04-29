"""FAQ full-chain scenario — every employee YAML's `faqs` list run through
perception → planning, asserting we get structured intent + a non-empty plan.

Drives end-to-end coverage for the questions that are actually surfaced on the
home screen, so wiring regressions specific to those phrasings get caught
before users see them.

Marked `scenario` (excluded from default regression). First run must populate
the LLM cache:

    pytest tests/scenarios/test_faq_full_chain.py --llm-mode=record-missing

Subsequent runs use the cache and need no real LLM access.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.scenario

EMPLOYEES_DIR = Path(__file__).resolve().parents[2] / "employees"


def _load_all_faqs():
    """Yield (employee_id, faq_id, question) cases from every YAML."""
    cases = []
    for yaml_path in sorted(EMPLOYEES_DIR.glob("*.yaml")):
        with open(yaml_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        employee_id = data["employee_id"]
        for faq in data.get("faqs") or []:
            cases.append(
                pytest.param(
                    employee_id,
                    faq["id"],
                    faq["question"],
                    id=f"{employee_id}-{faq['id']}",
                )
            )
    return cases


@pytest.fixture(scope="module", autouse=True)
def _load_tools():
    from backend.tools.loader import load_all_tools

    load_all_tools()


@pytest.mark.parametrize("employee_id, faq_id, question", _load_all_faqs())
async def test_faq_full_chain(
    employee_id, faq_id, question, recorded_llm, test_db_session,
):
    from backend.agent.perception import run_perception
    from backend.agent.planning import PlanningEngine
    from backend.agent.graph import build_llm  # patched by recorded_llm

    state = {
        "messages": [{"role": "user", "content": question}],
        "raw_query": question,
        "session_id": f"faq-{employee_id}-{faq_id}",
        "user_id": f"faq_test_{employee_id}",
        "employee_id": employee_id,
    }
    state = await run_perception(state)
    intent = state.get("structured_intent")
    assert intent and intent.get("slots"), (
        f"perception produced no intent for {employee_id}/{faq_id}: {question[:60]}"
    )

    llm = build_llm("qwen3-235b", request_timeout=90)
    engine = PlanningEngine(llm=llm, llm_timeout=60.0, max_retries=2)
    plan = await engine.generate_plan(intent)
    assert plan.tasks, (
        f"planning produced empty plan for {employee_id}/{faq_id}"
    )
