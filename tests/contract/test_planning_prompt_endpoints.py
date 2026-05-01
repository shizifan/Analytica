"""Cross-cutting integrity for planning-prompt endpoint rendering.

Two regressions guarded here, both surfaced by the FAQ ai-2 incident
("2026年投资项目进度，以柱状图展示各项目完成率"):

  1. Per-endpoint ``disambiguate`` text recommends other endpoints by name.
     If an endpoint's hint points to an endpoint that was deliberately
     excluded from an employee's whitelist, the LLM follows the hint and
     emits hallucinated tasks → planning fails after retries.

  2. ``_format_ep_detail`` rendered ``field_schema`` rows by 3-tuple
     unpacking. After P2.3a allowed 4-element rows (``label_zh`` 4th elt),
     any endpoint adopting the new shape would crash the planner with
     ``ValueError: too many values to unpack``.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from backend.agent.api_registry import (
    ALL_ENDPOINTS,
    ApiEndpoint,
    BY_NAME,
    get_endpoints_description,
)

pytestmark = pytest.mark.contract

EMPLOYEES_DIR = Path(__file__).resolve().parents[2] / "employees"


def _employee_yamls():
    return sorted(EMPLOYEES_DIR.glob("*.yaml"))


def _endpoint_names_in_text(text: str) -> set[str]:
    """Extract `getXxx` style endpoint references from a free-form string."""
    if not text:
        return set()
    return set(re.findall(r"\bget[A-Z][A-Za-z0-9]+\b", text))


# ── Bug 1 — disambiguate text must not point to excluded endpoints ───


@pytest.mark.parametrize("yaml_path", _employee_yamls(), ids=lambda p: p.stem)
def test_disambiguate_hints_stay_within_employee_whitelist(yaml_path):
    """For every endpoint in an employee's allowed list, its
    ``disambiguate`` text must only reference endpoints that are also in
    that allowed list (or not endpoint references at all).

    Catches: deliberate exclusion of an endpoint while another endpoint's
    disambiguate keeps recommending it — the FAQ ai-2 root cause.
    """
    with open(yaml_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    allowed = set(cfg.get("endpoints") or [])
    if not allowed:
        pytest.skip(f"{yaml_path.stem}: no endpoint whitelist (auto-derive mode)")

    offences: list[str] = []
    for ep_name in allowed:
        ep = BY_NAME.get(ep_name)
        if ep is None:
            continue
        referenced = _endpoint_names_in_text(ep.disambiguate)
        # Any reference to a real endpoint that isn't in this employee's
        # whitelist is a misdirection. References to non-existent endpoint
        # names (typos / outdated) are caught by a separate test.
        for ref in referenced:
            if ref in BY_NAME and ref not in allowed:
                offences.append(
                    f"{ep_name}.disambiguate references {ref!r} "
                    f"which is excluded from {yaml_path.stem}"
                )

    assert not offences, "\n".join(offences)


def test_disambiguate_references_point_to_real_endpoints():
    """Catch typos / renamed endpoints whose names linger in disambiguate text."""
    valid_names = {ep.name for ep in ALL_ENDPOINTS}
    offences: list[str] = []
    for ep in ALL_ENDPOINTS:
        for ref in _endpoint_names_in_text(ep.disambiguate):
            if ref not in valid_names:
                offences.append(f"{ep.name}.disambiguate references unknown endpoint {ref!r}")
    assert not offences, "\n".join(offences)


# ── Bug 2 — _format_ep_detail must accept 3 or 4-element field_schema ──


def test_get_endpoints_description_renders_with_four_element_field_schema(monkeypatch):
    """Inject a fixture endpoint with a 4-element field_schema row and
    verify the prompt-builder doesn't crash."""
    fixture = ApiEndpoint(
        name="testFourEltSchemaEp",
        path="/x", domain="D1",
        intent="fixture: 4-element field_schema",
        time="T_RT", granularity="G_PORT",
        tags=("test",), required=(), optional=(),
        param_note="", returns="", disambiguate="",
        field_schema=(
            ("qty", "int", "throughput", "吨吞吐量"),
            ("dateMonth", "str", "month YYYY-MM"),  # mixed 3-elt
        ),
    )
    monkeypatch.setitem(BY_NAME, fixture.name, fixture)
    # Add to BY_DOMAIN bucket so the renderer iterates it.
    from backend.agent.api_registry import BY_DOMAIN
    monkeypatch.setitem(BY_DOMAIN, "D1", BY_DOMAIN.get("D1", []) + [fixture])

    # ``domain_hint`` triggers the detailed renderer (``_format_ep_detail``);
    # the condensed renderer omits ``field_schema`` entirely.
    out = get_endpoints_description(
        domain_hint="D1",
        allowed_endpoints=frozenset({fixture.name}),
    )
    assert "testFourEltSchemaEp" in out
    # The 4-elt row should render with the column name and type.
    assert "qty(int)" in out
    assert "dateMonth(str)" in out
    # The label_zh ("吨吞吐量") should NOT leak into the structure line —
    # that field is for downstream rendering, not the planning prompt.
    assert "字段结构: qty(int) | dateMonth(str)" in out
