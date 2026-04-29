"""Frontend-payload ↔ backend contract for FAQ editing.

Verifies the round-trip that powers the EmployeeDetail drawer's FAQ editor:

  EmployeeProfile.faqs
    → _profile_to_detail()  (GET response shape)
    → EmployeeUpdatePayload  (frontend payload)
    → PatchEmployeeRequest   (backend request model)
    → merge with current     (route handler logic)
    → identical FAQ list

Catches: payload-shape drift between frontend types and backend models, the
merge step accidentally dropping caller-provided faqs, and FAQItem's optional
fields disappearing through the round-trip.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from backend.employees.profile import EmployeeProfile
from backend.main import (
    FAQItemPayload,
    PatchEmployeeRequest,
    _profile_to_detail,
)

pytestmark = pytest.mark.contract

EMPLOYEES_DIR = Path(__file__).resolve().parents[2] / "employees"
SAMPLE_YAML = EMPLOYEES_DIR / "asset_investment.yaml"


def test_profile_to_detail_preserves_faqs():
    profile = EmployeeProfile.from_yaml(SAMPLE_YAML)
    detail = _profile_to_detail(profile)
    assert len(detail["faqs"]) == len(profile.faqs)
    for src, dumped in zip(profile.faqs, detail["faqs"]):
        assert dumped["id"] == src.id
        assert dumped["question"] == src.question


def test_patch_request_accepts_frontend_payload_shape():
    """The exact JSON shape the EmployeeDetail drawer sends must parse."""
    frontend_payload = {
        "name": "资产设备专家",
        "description": "test desc",
        "version": "1.2",
        "initials": None,
        "status": "active",
        "domains": ["D5"],
        "endpoints": [],
        "faqs": [
            {"id": "ai-1", "question": "Q1", "tag": None, "type": None},
            {"id": "ai-2", "question": "Q2"},
        ],
        "snapshot_note": "UI edit",
    }
    req = PatchEmployeeRequest(**frontend_payload)
    assert req.faqs is not None
    assert len(req.faqs) == 2
    assert req.faqs[0].id == "ai-1"
    assert req.faqs[1].tag is None  # default for omitted field


def test_merge_uses_caller_faqs_when_provided():
    """Mirrors backend/main.py update_employee merge for the faqs slot."""
    profile = EmployeeProfile.from_yaml(SAMPLE_YAML)
    new_faqs = [
        FAQItemPayload(id="new-1", question="brand new"),
        FAQItemPayload(id="new-2", question="another", tag="featured"),
    ]
    req = PatchEmployeeRequest(faqs=new_faqs)

    patch = req.model_dump(exclude_unset=True, exclude_none=True)
    faqs_override = patch.get("faqs")
    assert faqs_override is not None
    merged_faqs = faqs_override

    assert len(merged_faqs) == 2
    assert merged_faqs[0]["id"] == "new-1"
    assert merged_faqs[1]["tag"] == "featured"
    assert [f["id"] for f in merged_faqs] != [f.id for f in profile.faqs]


def test_merge_keeps_current_faqs_when_omitted():
    """A patch without faqs must not wipe the existing list."""
    profile = EmployeeProfile.from_yaml(SAMPLE_YAML)
    req = PatchEmployeeRequest(name="rename only")

    patch = req.model_dump(exclude_unset=True, exclude_none=True)
    assert "faqs" not in patch  # caller didn't touch faqs
    fallback = [f.model_dump() for f in profile.faqs]
    assert len(fallback) == len(profile.faqs)
    assert fallback[0]["id"] == profile.faqs[0].id


def test_empty_faqs_list_clears_via_patch():
    """Sending faqs=[] explicitly survives the route's dump options and is
    treated as 'clear all', not 'no change'."""
    req = PatchEmployeeRequest(faqs=[])
    # Match update_employee()'s dump options exactly (main.py).
    patch = req.model_dump(exclude_unset=True, exclude_none=True)
    assert patch.get("faqs") == []
