"""Phase 6 / 6.1 — enhanced visual baseline.

Locks in 4-end output for an outline that exercises every visual block
introduced in Phases 1-5 (callouts, comparison_grid, section_cover,
chart_table_pair, table.highlight_rules, multi-chart, growth indicators).

This is the **structural** counterpart to ``test_report_outputs_baseline``;
visual fidelity (rendered pixels) is guarded separately by the perceptual
hash test in ``tests/visual/`` (Phase 6.2).

Regenerating goldens after an intentional output change::

    ANALYTICA_REGEN_BASELINE=1 pytest tests/contract/test_enhanced_baseline.py
"""
from __future__ import annotations

import pytest

from backend.tools.report._block_renderer import render_outline
from backend.tools.report._renderers import (
    DocxBlockRenderer,
    HtmlBlockRenderer,
    MarkdownBlockRenderer,
    PptxBlockRenderer,
)

from tests.contract._enhanced_baseline import make_enhanced_outline
from tests.contract._report_baseline import (
    docx_to_text_tree,
    golden_path,
    html_to_text_tree,
    markdown_normalize,
    pptx_to_text_tree,
    regen_baseline_enabled,
)

pytestmark = pytest.mark.contract

_FIXTURE = "enhanced"


def _check_or_regen(actual_payload, ext: str, normaliser):
    path = golden_path(_FIXTURE, ext)
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
        exp_lines = expected_tree.splitlines()
        act_lines = actual_tree.splitlines()
        first_diff = next(
            (
                i for i, (e, a) in enumerate(zip(exp_lines, act_lines))
                if e != a
            ),
            min(len(exp_lines), len(act_lines)),
        )
        lo = max(0, first_diff - 3)
        hi = first_diff + 4
        snippet: list[str] = []
        for j in range(lo, hi):
            e_ = exp_lines[j] if j < len(exp_lines) else "<EOF>"
            a_ = act_lines[j] if j < len(act_lines) else "<EOF>"
            marker = "  " if e_ == a_ else "≠ "
            snippet.append(f"  L{j+1:>4} {marker}exp: {e_}")
            snippet.append(f"           act: {a_}")
        pytest.fail(
            f"{ext.upper()} enhanced tree diverged from {path.name}.\n"
            "\n".join(snippet),
        )


def test_markdown_enhanced_baseline():
    outline = make_enhanced_outline()
    md = render_outline(outline, MarkdownBlockRenderer())
    assert isinstance(md, str)
    _check_or_regen(md, "md", markdown_normalize)


def test_html_enhanced_baseline():
    outline = make_enhanced_outline()
    html = render_outline(outline, HtmlBlockRenderer())
    assert isinstance(html, str)
    _check_or_regen(html, "html", html_to_text_tree)


def test_docx_enhanced_baseline():
    outline = make_enhanced_outline()
    data = render_outline(outline, DocxBlockRenderer())
    assert isinstance(data, (bytes, bytearray))
    _check_or_regen(data, "docx", docx_to_text_tree)


def test_pptx_enhanced_baseline():
    outline = make_enhanced_outline()
    data = render_outline(outline, PptxBlockRenderer())
    assert isinstance(data, (bytes, bytearray))
    _check_or_regen(data, "pptx", pptx_to_text_tree)
