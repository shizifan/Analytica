"""Step 0 baseline tests — guard report output structural equivalence
across the outline refactor (see spec/refactor_report_outline.md).

Each test:
  1. Forces deterministic fallback (no LLM, no Node bridge).
  2. Runs the corresponding report tool against the "normal" fixture.
  3. Diff-compares a normalised structural tree to the golden file.

Regenerating goldens after an intentional output change::

    ANALYTICA_REGEN_BASELINE=1 pytest tests/contract/test_report_outputs_baseline.py

The first run on a fresh checkout (no goldens present) auto-generates
them and skips with a message — re-run normally to verify.
"""
from __future__ import annotations

import pytest

from backend.tools.base import ToolInput
from backend.tools.report.docx_gen import DocxReportTool
from backend.tools.report.html_gen import HtmlReportTool
from backend.tools.report.markdown_gen import MarkdownReportTool
from backend.tools.report.pptx_gen import PptxReportTool

from tests.contract._report_baseline import (
    disable_skill_mode,
    docx_to_text_tree,
    freeze_kpis,
    golden_path,
    html_to_text_tree,
    make_normal_fixture,
    markdown_normalize,
    pptx_to_text_tree,
    regen_baseline_enabled,
)

pytestmark = pytest.mark.contract


@pytest.fixture(autouse=True)
def _baseline_env(monkeypatch):
    freeze_kpis(monkeypatch)
    disable_skill_mode(monkeypatch)


async def _run_tool(tool_cls, params: dict, context: dict):
    tool = tool_cls()
    inp = ToolInput(params=params)
    out = await tool.execute(inp, context)
    assert out.status == "success", (
        f"{tool_cls.__name__} failed: {out.error_message!r}"
    )
    return out.data


def _check_or_regen(actual_payload, ext: str, normaliser, fixture_name: str = "normal"):
    """Compare structural tree to golden; first run / regen mode writes
    the raw payload to disk and skips."""
    path = golden_path(fixture_name, ext)
    write_mode = "wb" if isinstance(actual_payload, (bytes, bytearray)) else "w"

    if regen_baseline_enabled() or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, write_mode, encoding=None if write_mode == "wb" else "utf-8") as f:
            f.write(actual_payload)
        pytest.skip(f"Baseline regenerated: {path.relative_to(path.parents[3])}")

    if isinstance(actual_payload, (bytes, bytearray)):
        expected = path.read_bytes()
    else:
        expected = path.read_text(encoding="utf-8")

    actual_tree = normaliser(actual_payload)
    expected_tree = normaliser(expected)
    if actual_tree != expected_tree:
        # Emit the first differing chunk to keep failure output readable.
        diff_msg = _short_diff(expected_tree, actual_tree)
        pytest.fail(
            f"{ext.upper()} structural tree diverged from golden "
            f"({path.name}).\n{diff_msg}"
        )


def _short_diff(expected: str, actual: str, context_lines: int = 3) -> str:
    exp_lines = expected.splitlines()
    act_lines = actual.splitlines()
    for i, (e, a) in enumerate(zip(exp_lines, act_lines)):
        if e != a:
            lo = max(0, i - context_lines)
            hi = min(max(len(exp_lines), len(act_lines)), i + context_lines + 1)
            chunk = []
            for j in range(lo, hi):
                e_ = exp_lines[j] if j < len(exp_lines) else "<EOF>"
                a_ = act_lines[j] if j < len(act_lines) else "<EOF>"
                marker = "  " if e_ == a_ else "≠ "
                chunk.append(f"  L{j+1:>4} {marker}expected: {e_}")
                chunk.append(f"           actual:   {a_}")
            return f"First diff at line {i+1}:\n" + "\n".join(chunk)
    if len(exp_lines) != len(act_lines):
        return (
            f"Trees match on overlap but length differs: "
            f"expected={len(exp_lines)} lines, actual={len(act_lines)} lines"
        )
    return "(diff not localised)"


# ---------------------------------------------------------------------------
# Per-backend tests
# ---------------------------------------------------------------------------

async def test_markdown_baseline():
    params, context, _ = make_normal_fixture()
    md = await _run_tool(MarkdownReportTool, params, context)
    assert isinstance(md, str)
    _check_or_regen(md, "md", markdown_normalize)


async def test_docx_baseline():
    params, context, _ = make_normal_fixture()
    data = await _run_tool(DocxReportTool, params, context)
    assert isinstance(data, (bytes, bytearray))
    _check_or_regen(data, "docx", docx_to_text_tree)


async def test_pptx_baseline():
    params, context, _ = make_normal_fixture()
    data = await _run_tool(PptxReportTool, params, context)
    assert isinstance(data, (bytes, bytearray))
    _check_or_regen(data, "pptx", pptx_to_text_tree)


async def test_html_baseline():
    params, context, _ = make_normal_fixture()
    html = await _run_tool(HtmlReportTool, params, context)
    assert isinstance(html, str)
    _check_or_regen(html, "html", html_to_text_tree)
