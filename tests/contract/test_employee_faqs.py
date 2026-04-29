"""Employee FAQ contract.

Each employee YAML must define exactly 5 FAQ entries with unique non-empty IDs
and questions. Frontend FAQ cards on the empty-hero screen are sourced from
this list (`GET /api/employees/{id}.faqs`), so missing or malformed entries
silently break the home screen UX.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.employees.profile import EmployeeProfile

pytestmark = pytest.mark.contract

EMPLOYEES_DIR = Path(__file__).resolve().parents[2] / "employees"
EXPECTED_FAQ_COUNT = 5

EMPLOYEE_IDS = sorted(p.stem for p in EMPLOYEES_DIR.glob("*.yaml"))


@pytest.mark.parametrize("employee_id", EMPLOYEE_IDS)
def test_employee_yaml_has_expected_faq_count(employee_id):
    profile = EmployeeProfile.from_yaml(EMPLOYEES_DIR / f"{employee_id}.yaml")
    assert len(profile.faqs) == EXPECTED_FAQ_COUNT, (
        f"{employee_id}: expected {EXPECTED_FAQ_COUNT} faqs, got {len(profile.faqs)}"
    )


@pytest.mark.parametrize("employee_id", EMPLOYEE_IDS)
def test_employee_faqs_have_unique_non_empty_ids(employee_id):
    profile = EmployeeProfile.from_yaml(EMPLOYEES_DIR / f"{employee_id}.yaml")
    ids = [f.id for f in profile.faqs]
    assert all(i.strip() for i in ids), f"{employee_id}: empty FAQ id"
    assert len(set(ids)) == len(ids), f"{employee_id}: duplicate FAQ ids: {ids}"


@pytest.mark.parametrize("employee_id", EMPLOYEE_IDS)
def test_employee_faqs_have_non_empty_questions(employee_id):
    profile = EmployeeProfile.from_yaml(EMPLOYEES_DIR / f"{employee_id}.yaml")
    for f in profile.faqs:
        assert f.question.strip(), f"{employee_id}: FAQ {f.id} has empty question"
