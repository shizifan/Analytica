"""Mock server health probe.

Sanity-check a sample of routes return 200 + parseable JSON. NOT validating
business correctness of responses — just that the server starts and routes
are wired.

Full-coverage scan of all 226 routes is opt-in via -m slow.
"""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.probe


# A small representative sample — one per backend domain — kept short
# so the default suite stays fast.
SAMPLE_ROUTES = [
    "/api/gateway/getInvestPlanByYear",                     # D6
    "/api/gateway/getThroughputAndTargetThroughputTon",     # D1
    "/api/gateway/getCustomerQty",                          # D3
    "/api/gateway/getEquipmentUsageRate",                   # D7
    "/api/gateway/getRegionalAnalysis",                     # D5
]


def test_mock_server_starts(mock_server_url):
    """The fixture itself must come up; this single test triggers it."""
    with httpx.Client() as client:
        r = client.get(f"{mock_server_url}/", timeout=2.0)
    # Any HTTP response (200/404) means server is up.
    assert r.status_code in (200, 404, 405), f"unexpected: {r.status_code}"


@pytest.mark.parametrize("path", SAMPLE_ROUTES)
def test_sample_route_returns_json(mock_server_url, path):
    """Sample-set routes must return JSON (any 2xx) without crashing."""
    with httpx.Client() as client:
        r = client.get(f"{mock_server_url}{path}", timeout=3.0)
    # Even 4xx is acceptable as long as body is JSON — means routing works.
    assert r.status_code < 500, f"{path}: server error {r.status_code}"
    try:
        body = r.json()
    except Exception as e:
        pytest.fail(f"{path}: response not JSON: {e}")
    assert isinstance(body, (dict, list)), f"{path}: unexpected body shape"


@pytest.mark.slow
def test_all_registered_routes_resolvable(mock_server_url):
    """Opt-in scan of every api_registry endpoint against mock_server.

    Skipped by default (slow). Run with: pytest -m slow tests/probes
    """
    from backend.agent.api_registry import BY_NAME

    failures: list[tuple[str, str]] = []
    with httpx.Client(timeout=2.0) as client:
        for name, ep in BY_NAME.items():
            try:
                r = client.get(f"{mock_server_url}{ep.path}")
            except httpx.RequestError as e:
                failures.append((name, f"request error: {e}"))
                continue
            if r.status_code >= 500:
                failures.append((name, f"500: {r.text[:100]}"))

    if failures:
        msg = f"{len(failures)} routes failed:\n" + "\n".join(
            f"  {n}: {err}" for n, err in failures[:20]
        )
        pytest.fail(msg)
