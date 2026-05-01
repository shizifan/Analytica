"""Baseline test helpers for report output regression.

Provides:
- ``make_normal_fixture()`` — synthetic ToolInput.params + context
  covering all current content item types (DataFrame, chart, narrative,
  stats, growth, summary text).
- ``stub_planner_llm(monkeypatch)`` — replaces the planner's
  ``invoke_llm`` call with a fixed JSON response so the LLM-driven
  outline pipeline produces byte-stable output across runs.
- ``disable_pptxgen_bridge(monkeypatch)`` — forces python-pptx
  rendering path on all four backends (no agent loop, no PptxGenJS).
- Four structural comparators that strip volatile bits (font sizes,
  exact spacing, ECharts data dumps) and emit a normalised text tree
  suitable for ``assert ==``.
- Golden-file IO helpers gated by ``ANALYTICA_REGEN_BASELINE=1``.
"""
from __future__ import annotations

import io
import json
import os
import re
import zipfile
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

import pandas as pd

from backend.tools.base import ToolOutput
from backend.tools.report._outline import KPIItem


GOLDEN_DIR = Path(__file__).parent.parent / "fixtures" / "report_baseline"


# ---------------------------------------------------------------------------
# Fixture: "normal" — covers every current content item type
# ---------------------------------------------------------------------------

def make_normal_fixture() -> tuple[dict, dict, list[str]]:
    """Returns (params, context, task_order).

    Coverage of ``_extract_items`` branches:
      T001 → DataFrame + endpoint metadata    → DataFrameItem
      T002 → ECharts option (dict w/ series)  → ChartDataItem
      T003 → narrative + summary_stats + growth_rates  → 3 items
      T004 → summary text (dict w/ summary)   → SummaryTextItem
    """
    df = pd.DataFrame({
        "regionName": ["大连港", "营口港", "锦州港"],
        "throughput": [4500.5, 3200.1, 1800.0],
    })

    chart_option = {
        "title": {"text": "港区吞吐量"},
        "xAxis": {"type": "category", "data": ["大连港", "营口港", "锦州港"]},
        "yAxis": {"type": "value"},
        "series": [{"type": "bar", "data": [4500.5, 3200.1, 1800.0]}],
    }

    descriptive = {
        "narrative": (
            "2026 Q1 大连港吞吐量达 4500.5 万吨，同比增长 12%，居三港之首；"
            "营口港 3200.1 万吨，锦州港 1800.0 万吨。"
        ),
        "summary_stats": {
            "throughput": {"max": 4500.5, "min": 1800.0, "mean": 3166.87},
        },
        "growth_rates": {
            "throughput": {"yoy": 0.12, "mom": 0.03},
        },
    }

    summary_payload = {
        "summary": "三港区集装箱吞吐量整体稳健增长，大连港持续领跑。",
    }

    context = {
        "T001": ToolOutput(
            tool_id="api_fetch", status="success", output_type="dataframe",
            data=df, metadata={"endpoint": "throughput_by_region"},
        ),
        "T002": ToolOutput(
            tool_id="chart_bar", status="success", output_type="chart",
            data=chart_option, metadata={"endpoint": "throughput_by_region"},
        ),
        "T003": ToolOutput(
            tool_id="descriptive_analysis", status="success", output_type="json",
            data=descriptive,
        ),
        "T004": ToolOutput(
            tool_id="summary_gen", status="success", output_type="json",
            data=summary_payload,
        ),
    }

    params = {
        "intent": "2026 Q1 港区吞吐量分析",
        "__task_id__": "T_REPORT",
        "report_metadata": {
            "title": "2026 Q1 港区吞吐量分析报告",
            "author": "Analytica Test",
            "date": "2026-04-29",
        },
        "report_structure": {
            "sections": [
                {"name": "一、港区吞吐量现状", "task_refs": ["T001", "T002"]},
                {"name": "二、关键指标分析", "task_refs": ["T003"]},
                {"name": "三、综合结论", "task_refs": ["T004"]},
            ],
        },
        "_task_order": ["T001", "T002", "T003", "T004"],
    }

    task_order = ["T001", "T002", "T003", "T004"]
    return params, context, task_order


# ---------------------------------------------------------------------------
# Deterministic stubs (LLM planner + Node bridge)
# ---------------------------------------------------------------------------

# Hand-crafted "what a sensible LLM would emit" response keyed to the
# normal fixture's 3 sections. Asset IDs (T0001/C0001/S0001) match what
# ``_items_to_assets`` mints for that fixture: T001 → DataFrame → T0001,
# T002 → ECharts → C0001, T003 narrative + summary_stats + growth_rates
# (DataFrame absent so first table id stays T0001) → S0001 for stats.
# The summary block in section 3 mirrors what the previous rule path
# would have surfaced from T004's summary text.
_FROZEN_PLANNER_RESPONSE = {
    "kpi_summary": [
        {"label": "总吞吐量", "value": "9500.6 万吨", "sub": "2026 Q1", "trend": "positive"},
        {"label": "同比增长", "value": "12.0%", "sub": "YoY", "trend": "positive"},
        {"label": "最高港区", "value": "大连港", "sub": "4500.5 万吨", "trend": None},
    ],
    "sections": [
        {
            "name": "一、港区吞吐量现状",
            "role": "status",
            "source_tasks": ["T001", "T002"],
            "blocks": [
                {"kind": "chart_table_pair", "chart_asset_id": "C0001",
                 "table_asset_id": "T0001", "layout": "h"},
                {"kind": "paragraph",
                 "text": "2026 Q1 大连港吞吐量达 4500.5 万吨，同比增长 12%，居三港之首；营口港 3200.1 万吨，锦州港 1800.0 万吨。",
                 "style": "body"},
            ],
        },
        {
            "name": "二、关键指标分析",
            "role": "status",
            "source_tasks": ["T003"],
            "blocks": [
                {"kind": "table", "asset_id": "S0001", "caption": "统计数据概览"},
                {"kind": "growth_indicators",
                 "growth_rates": {"throughput": {"yoy": 0.12, "mom": 0.03}}},
            ],
        },
        {
            "name": "三、综合结论",
            "role": "recommendation",
            "source_tasks": ["T004"],
            "blocks": [
                {"kind": "paragraph",
                 "text": "三港区集装箱吞吐量整体稳健增长，大连港持续领跑。",
                 "style": "lead"},
            ],
        },
    ],
}


def stub_planner_llm(
    monkeypatch,
    response: dict | str | None = None,
) -> None:
    """Replace ``invoke_llm`` inside the planner with a fixed response.

    Without an override, returns ``_FROZEN_PLANNER_RESPONSE`` — the
    canonical "good" LLM output for the normal fixture. Tests that need
    a different shape can pass their own dict / raw string.

    Patches the planner module's bound name (``invoke_llm`` was imported
    via ``from backend.tools._llm import invoke_llm`` so patching the
    source module wouldn't reach it).
    """
    payload = response if response is not None else _FROZEN_PLANNER_RESPONSE
    text = payload if isinstance(payload, str) else json.dumps(
        payload, ensure_ascii=False,
    )

    async def _stub(*args, **kwargs):  # noqa: ARG001
        return {"text": text}

    monkeypatch.setattr(
        "backend.tools.report._outline_planner.invoke_llm", _stub,
    )


# Modules that do ``from backend.config import get_settings`` at module
# level — patching ``backend.config.get_settings`` alone is not enough
# because the name has already been bound into these namespaces.
_GET_SETTINGS_IMPORT_SITES = (
    "backend.config",
    "backend.tools.report._outline_planner",
)


def disable_pptxgen_bridge(monkeypatch) -> None:
    """Force PPTX onto the python-pptx renderer (no Node bridge).

    The PptxGenJS Node-side bridge is the only optional path left in the
    report pipeline; turning it off keeps PPTX baseline tests deterministic
    on machines without Node installed.

    DOCX/HTML are LLM-agent-only (no deterministic fallback); tests that
    exercise their tool entry points must mock the agent.
    """
    # Patch both the source module AND pptx_gen's import site (the latter
    # binds the name at import time via ``from ... import``).
    monkeypatch.setattr(
        "backend.tools.report._pptxgen_builder.check_pptxgen_available",
        lambda: False,
    )
    monkeypatch.setattr(
        "backend.tools.report.pptx_gen.check_pptxgen_available",
        lambda: False,
    )


def override_settings(monkeypatch, **overrides) -> None:
    """Stand up a frozen Settings with arbitrary overrides; replaces
    ``get_settings`` at every known import site so callers see the
    patched instance. Subsequent calls in the same test override the
    previous ones."""
    from backend import config as _cfg

    frozen = _cfg.Settings()
    for k, v in overrides.items():
        setattr(frozen, k, v)
    factory = lambda: frozen  # noqa: E731
    for module_path in _GET_SETTINGS_IMPORT_SITES:
        monkeypatch.setattr(f"{module_path}.get_settings", factory)


# ---------------------------------------------------------------------------
# DOCX comparator — extract paragraph/table skeleton from word/document.xml
# ---------------------------------------------------------------------------

_W_NS = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def docx_to_text_tree(docx_bytes: bytes) -> str:
    """Strip OOXML to a deterministic structural text tree.

    Compares: paragraph text, paragraph style ID, table cell text, page
    breaks, section breaks. Ignores: run-level formatting (bold/color/
    font), exact column widths, document-level metadata (date/revision).
    """
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as zf:
        doc_xml = zf.read("word/document.xml")
    root = ET.fromstring(doc_xml)
    body = root.find(f"{_W_NS}body")
    assert body is not None, "DOCX missing <w:body>"

    lines: list[str] = []
    for child in body:
        if child.tag == f"{_W_NS}p":
            lines.append(_serialize_paragraph(child))
        elif child.tag == f"{_W_NS}tbl":
            lines.extend(_serialize_table(child))
        elif child.tag == f"{_W_NS}sectPr":
            lines.append("[SECT]")
    return "\n".join(lines)


_PIC_TAGS = {
    "{http://schemas.openxmlformats.org/drawingml/2006/main}graphic",
    "{http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing}inline",
    "{http://schemas.openxmlformats.org/drawingml/2006/picture}pic",
}


def _has_picture(p) -> bool:
    """Detect any drawing/picture child to keep the comparator stable
    across embedded PNG bytes (Phase 2.2 — DOCX 嵌图 introduces images
    whose binary differs across matplotlib / OS / font runs)."""
    for elem in p.iter():
        if elem.tag in _PIC_TAGS:
            return True
    return False


def _serialize_paragraph(p) -> str:
    style = ""
    pPr = p.find(f"{_W_NS}pPr")
    if pPr is not None:
        pStyle = pPr.find(f"{_W_NS}pStyle")
        if pStyle is not None:
            style = pStyle.get(f"{_W_NS}val", "")
    text = "".join(t.text or "" for t in p.iter(f"{_W_NS}t")).strip()
    has_pgbreak = any(
        br.get(f"{_W_NS}type") == "page" for br in p.iter(f"{_W_NS}br")
    )
    has_pic = _has_picture(p)
    prefix = f"[P:{style}]" if style else "[P]"
    suffix = "[PAGEBREAK]" if has_pgbreak else ""
    pic_marker = "[PICTURE]" if has_pic else ""
    return f"{prefix}{pic_marker}{text}{suffix}"


def _serialize_table(tbl) -> list[str]:
    out = ["[TABLE]"]
    for tr in tbl.findall(f"{_W_NS}tr"):
        cells: list[str] = []
        for tc in tr.findall(f"{_W_NS}tc"):
            txt = "".join(t.text or "" for t in tc.iter(f"{_W_NS}t")).strip()
            cells.append(txt)
        out.append("  | " + " | ".join(cells))
    out.append("[/TABLE]")
    return out


# ---------------------------------------------------------------------------
# PPTX comparator — extract per-slide text from ppt/slides/slide*.xml
# ---------------------------------------------------------------------------

_A_NS = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
_SLIDE_NAME_RE = re.compile(r"ppt/slides/slide(\d+)\.xml$")


def pptx_to_text_tree(pptx_bytes: bytes) -> str:
    with zipfile.ZipFile(io.BytesIO(pptx_bytes)) as zf:
        slide_entries: list[tuple[int, str]] = []
        for name in zf.namelist():
            m = _SLIDE_NAME_RE.match(name)
            if m:
                slide_entries.append((int(m.group(1)), name))
        slide_entries.sort()

        out: list[str] = []
        for idx, name in slide_entries:
            xml = zf.read(name)
            root = ET.fromstring(xml)
            out.append(f"=== slide{idx} ===")
            for elem in root.iter(f"{_A_NS}t"):
                txt = (elem.text or "").strip()
                if txt:
                    out.append(f"  T: {txt}")
        return "\n".join(out)


# ---------------------------------------------------------------------------
# HTML comparator — DOM skeleton via stdlib html.parser, scripts collapsed
# ---------------------------------------------------------------------------

_VOLATILE_TAGS = {"script", "style"}


class _HtmlSkeletonExtractor(HTMLParser):
    """Walk HTML emitting indented '<tag class=...>' lines + text content.

    Collapses <script> / <style> bodies to ``[INLINE_SCRIPT]`` / ``[STYLE]``
    placeholders since echarts initialiser blocks contain raw JSON whose
    key order is not guaranteed stable.
    """

    def __init__(self) -> None:
        super().__init__()
        self.lines: list[str] = []
        self._depth = 0
        self._suppress_text_in: list[str] = []  # stack of volatile tags

    def handle_starttag(self, tag, attrs):  # noqa: ANN001
        attr_dict = dict(attrs)
        attr_repr = ""
        if "class" in attr_dict:
            cls = ".".join(sorted(attr_dict["class"].split()))
            attr_repr = f" class={cls}"
        elif "id" in attr_dict:
            attr_repr = f" id={attr_dict['id']}"
        self.lines.append(f"{'  ' * self._depth}<{tag}{attr_repr}>")
        if tag in _VOLATILE_TAGS:
            placeholder = "[INLINE_SCRIPT]" if tag == "script" else "[STYLE]"
            self.lines.append(f"{'  ' * (self._depth + 1)}{placeholder}")
            self._suppress_text_in.append(tag)
        self._depth += 1

    def handle_endtag(self, tag):  # noqa: ANN001
        self._depth = max(0, self._depth - 1)
        if self._suppress_text_in and self._suppress_text_in[-1] == tag:
            self._suppress_text_in.pop()
        self.lines.append(f"{'  ' * self._depth}</{tag}>")

    def handle_startendtag(self, tag, attrs):  # noqa: ANN001
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_data(self, data):  # noqa: ANN001
        if self._suppress_text_in:
            return
        text = data.strip()
        if text:
            self.lines.append(f"{'  ' * self._depth}{text}")


def html_to_text_tree(html_str: str) -> str:
    extractor = _HtmlSkeletonExtractor()
    extractor.feed(html_str)
    extractor.close()
    return "\n".join(extractor.lines)


# ---------------------------------------------------------------------------
# Markdown comparator — line-trim + collapse runs of blank lines
# ---------------------------------------------------------------------------

def markdown_normalize(md: str) -> str:
    md = md.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    blank_run = 0
    for raw_line in md.split("\n"):
        line = raw_line.rstrip()
        if not line:
            blank_run += 1
            if blank_run <= 2:
                out.append("")
        else:
            blank_run = 0
            out.append(line)
    return "\n".join(out).rstrip() + "\n"


# ---------------------------------------------------------------------------
# Golden file IO
# ---------------------------------------------------------------------------

def golden_path(fixture_name: str, ext: str) -> Path:
    return GOLDEN_DIR / fixture_name / f"golden.{ext}"


def regen_baseline_enabled() -> bool:
    return os.getenv("ANALYTICA_REGEN_BASELINE") == "1"
