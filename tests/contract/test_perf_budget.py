"""Phase 6 / 6.6 — performance budget guard.

Per spec (visual_polish_plan.md §10.6):

  - Report generation total time ≤ 1.5× baseline (with embedded charts)
  - DOCX size ≤ 200 KB on the ``normal`` fixture
  - PPT size  ≤ 1 MB  on the ``normal`` fixture (incl. native charts)
  - Over budget → warn (xfail strict=False), not hard fail

The "warn don't fail" convention is implemented via ``pytest.xfail``: when
a metric blows past its budget the test is marked xfail with a reason,
keeping CI green while still surfacing the regression in test output.
Set ``ANALYTICA_PERF_STRICT=1`` to flip this into hard failures (used in
nightly runs / pre-release sweeps).

Budgets are intentionally loose to absorb LibreOffice / matplotlib / OS
font variance. Tighten them only after a few weeks of observed CI data.
"""
from __future__ import annotations

import os
import time

import pytest

from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._renderers import (
    DocxBlockRenderer,
    HtmlBlockRenderer,
    MarkdownBlockRenderer,
    PptxBlockRenderer,
)

from tests.contract._enhanced_baseline import make_enhanced_outline
from tests.contract._report_baseline import (
    disable_pptxgen_bridge,
    make_normal_fixture,
    stub_planner_llm,
)

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Budgets — keep loose for now, tighten as CI data accumulates
# ---------------------------------------------------------------------------

DOCX_NORMAL_MAX_BYTES = 200 * 1024        # 200 KB
PPTX_NORMAL_MAX_BYTES = 1024 * 1024       # 1 MB
END_TO_END_MAX_SECONDS_NORMAL = 30.0      # whole pipeline upper bound
PER_RENDERER_MAX_SECONDS = 15.0           # one renderer call


def _strict() -> bool:
    return os.getenv("ANALYTICA_PERF_STRICT") == "1"


def _budget_violation(metric: str, actual, limit, unit: str) -> None:
    """Fail or xfail depending on ``ANALYTICA_PERF_STRICT``."""
    msg = (
        f"perf budget exceeded — {metric}: "
        f"{actual:.2f}{unit} > limit {limit:.2f}{unit}"
    )
    if _strict():
        pytest.fail(msg)
    pytest.xfail(msg)


@pytest.fixture(autouse=True)
def _perf_env(monkeypatch):
    stub_planner_llm(monkeypatch)
    disable_pptxgen_bridge(monkeypatch)


# ---------------------------------------------------------------------------
# File size budgets — normal fixture (LLM planner stubbed, no agent loop)
# ---------------------------------------------------------------------------

async def _normal_outline():
    params, ctx, task_order = make_normal_fixture()
    return await plan_outline(params, ctx, task_order=task_order,
                              intent=params.get("intent", ""))


async def test_docx_normal_size_within_budget():
    blob = render_outline(await _normal_outline(), DocxBlockRenderer())
    size_kb = len(blob) / 1024
    if len(blob) > DOCX_NORMAL_MAX_BYTES:
        _budget_violation(
            "DOCX(normal)", size_kb, DOCX_NORMAL_MAX_BYTES / 1024, " KB"
        )


async def test_pptx_normal_size_within_budget():
    blob = render_outline(await _normal_outline(), PptxBlockRenderer())
    size_kb = len(blob) / 1024
    if len(blob) > PPTX_NORMAL_MAX_BYTES:
        _budget_violation(
            "PPTX(normal)", size_kb, PPTX_NORMAL_MAX_BYTES / 1024, " KB"
        )


# ---------------------------------------------------------------------------
# Time budgets — measured per-renderer + end-to-end
# ---------------------------------------------------------------------------

def _time_render(renderer_cls, outline) -> tuple[float, int]:
    t0 = time.perf_counter()
    blob = render_outline(outline, renderer_cls())
    dt = time.perf_counter() - t0
    size = len(blob) if isinstance(blob, (bytes, bytearray)) else len(
        blob.encode("utf-8") if isinstance(blob, str) else b""
    )
    return dt, size


async def test_per_renderer_time_normal_within_budget():
    outline = await _normal_outline()
    timings: dict[str, float] = {}
    for cls in (
        MarkdownBlockRenderer, HtmlBlockRenderer,
        DocxBlockRenderer, PptxBlockRenderer,
    ):
        dt, _ = _time_render(cls, outline)
        timings[cls.__name__] = dt

    breaches = [
        (name, dt) for name, dt in timings.items()
        if dt > PER_RENDERER_MAX_SECONDS
    ]
    if breaches:
        slowest_name, slowest_dt = max(breaches, key=lambda x: x[1])
        _budget_violation(
            f"renderer time ({slowest_name}, normal)",
            slowest_dt, PER_RENDERER_MAX_SECONDS, "s",
        )


async def test_end_to_end_normal_within_budget():
    outline = await _normal_outline()
    t0 = time.perf_counter()
    for cls in (
        MarkdownBlockRenderer, HtmlBlockRenderer,
        DocxBlockRenderer, PptxBlockRenderer,
    ):
        render_outline(outline, cls())
    dt = time.perf_counter() - t0
    if dt > END_TO_END_MAX_SECONDS_NORMAL:
        _budget_violation(
            "end-to-end(normal,4-renderer)",
            dt, END_TO_END_MAX_SECONDS_NORMAL, "s",
        )


# ---------------------------------------------------------------------------
# Enhanced fixture — looser bound; primarily catches catastrophic regressions
# ---------------------------------------------------------------------------

ENHANCED_END_TO_END_MAX_SECONDS = 45.0


def test_enhanced_end_to_end_within_budget():
    outline = make_enhanced_outline()
    t0 = time.perf_counter()
    for cls in (
        MarkdownBlockRenderer, HtmlBlockRenderer,
        DocxBlockRenderer, PptxBlockRenderer,
    ):
        render_outline(outline, cls())
    dt = time.perf_counter() - t0
    if dt > ENHANCED_END_TO_END_MAX_SECONDS:
        _budget_violation(
            "end-to-end(enhanced,4-renderer)",
            dt, ENHANCED_END_TO_END_MAX_SECONDS, "s",
        )
