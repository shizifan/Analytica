"""PptxGenJS bridge — generates professional PPTX via Node.js subprocess.

Follows the design principles from the official Claude PPTX skill:
- "Sandwich" structure: dark cover + section dividers + thank-you, light content
- Every content slide has a visual element (chart, KPI cards, or table)
- Two-column layouts when narrative + chart co-exist in the same section
- Native PowerPoint charts from ECharts option JSON (BAR, LINE — editable!)
- Large KPI callouts for business metrics (not plain text bullets)
- No accent underlines, no decorative full-width bars (they read as AI slop)

Falls back to python-pptx when Node.js / pptxgenjs is unavailable.

ECharts → PptxGenJS conversion rules:
  bar (vertical)   → pres.charts.BAR + barDir:"col"
  bar (horizontal) → pres.charts.BAR + barDir:"bar"
  line             → pres.charts.LINE
  waterfall        → skipped (transparent stack not natively representable)
  dual-y line      → multi-series LINE on single y-axis (auto-scale)
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Any

from backend.skills._i18n import col_label, metric_label
from backend.skills.report._content_collector import (
    ChartDataItem,
    DataFrameItem,
    GrowthItem,
    NarrativeItem,
    ReportContent,
    StatsTableItem,
)

logger = logging.getLogger("analytica.skills.pptxgen_builder")

# ---------------------------------------------------------------------------
# Environment
# ---------------------------------------------------------------------------

def _find_node() -> str | None:
    return shutil.which("node") or shutil.which("node.exe")


def _find_pptxgenjs_root() -> str | None:
    """Return the directory that contains the pptxgenjs package, or None."""
    # 1) Try standard require resolution
    node = _find_node()
    if not node:
        return None
    try:
        r = subprocess.run(
            [node, "-e", "console.log(require.resolve('pptxgenjs'))"],
            capture_output=True, text=True, timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return None  # resolvable on PATH
    except Exception:
        pass

    # 2) Try global npm root
    try:
        r = subprocess.run(["npm", "root", "-g"], capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            npm_root = r.stdout.strip()
            pkg = os.path.join(npm_root, "pptxgenjs", "package.json")
            if os.path.exists(pkg):
                return npm_root
    except Exception:
        pass

    # 3) Homebrew hard-coded fallback (macOS)
    for candidate in ["/opt/homebrew/lib/node_modules", "/usr/local/lib/node_modules"]:
        if os.path.exists(os.path.join(candidate, "pptxgenjs", "package.json")):
            return candidate

    return None


_NODE_PATH: str | None = None   # resolved once
_PPTXGEN_AVAILABLE: bool | None = None  # cached

def check_pptxgen_available() -> bool:
    """Return True if Node.js + pptxgenjs are both reachable."""
    global _PPTXGEN_AVAILABLE, _NODE_PATH
    if _PPTXGEN_AVAILABLE is not None:
        return _PPTXGEN_AVAILABLE

    node = _find_node()
    if not node:
        _PPTXGEN_AVAILABLE = False
        return False

    root = _find_pptxgenjs_root()
    env = dict(os.environ)
    if root:
        env["NODE_PATH"] = root + os.pathsep + env.get("NODE_PATH", "")

    try:
        r = subprocess.run(
            [node, "-e", "require('pptxgenjs'); console.log('ok')"],
            capture_output=True, text=True, timeout=8, env=env,
        )
        _PPTXGEN_AVAILABLE = (r.returncode == 0 and "ok" in r.stdout)
        if _PPTXGEN_AVAILABLE:
            _NODE_PATH = root
    except Exception:
        _PPTXGEN_AVAILABLE = False

    return _PPTXGEN_AVAILABLE


# ---------------------------------------------------------------------------
# JS code helpers
# ---------------------------------------------------------------------------

def _js(v: Any) -> str:
    """Serialize a Python value to a JSON-compatible JS literal."""
    return json.dumps(v, ensure_ascii=False)


def _jsv(v: Any) -> str:
    """Serialize to JS, but if it's a bare string that looks like a JS
    expression (starts with 'C.' or 'FONT'), emit it unquoted."""
    if isinstance(v, str) and (v.startswith("C.") or v.startswith("FONT")):
        return v
    return _js(v)


# ---------------------------------------------------------------------------
# ECharts → PptxGenJS chart converter
# ---------------------------------------------------------------------------

def _is_waterfall(series_list: list[dict]) -> bool:
    """True if any series has transparent itemStyle (waterfall base)."""
    for s in series_list:
        style = s.get("itemStyle") or {}
        color = style.get("color", "")
        if isinstance(color, str) and "transparent" in color.lower():
            return True
    return False


def _echarts_series_values(raw: list) -> list[float]:
    out = []
    for v in raw:
        if v is None:
            out.append(0.0)
        elif isinstance(v, dict):
            out.append(float(v.get("value") or 0))
        else:
            try:
                out.append(float(v))
            except Exception:
                out.append(0.0)
    return out


def echarts_to_pptxgen(option: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an ECharts option to a PptxGenJS chart spec.

    Returns a dict with keys ``type``, ``data``, ``options``
    or None when the chart cannot be natively represented in PowerPoint.
    """
    series_list = option.get("series", [])
    if not series_list:
        return None
    if _is_waterfall(series_list):
        return None  # Render as table instead

    # x-axis categories
    x_axis = option.get("xAxis", {})
    if isinstance(x_axis, list):
        x_axis = x_axis[0] if x_axis else {}
    categories: list[str] = []
    if isinstance(x_axis, dict):
        categories = [str(c) for c in (x_axis.get("data") or [])]

    # Detect orientation: horizontal bar has yAxis.type == "category"
    y_axis = option.get("yAxis", {})
    if isinstance(y_axis, list):
        y_axis = y_axis[0] if y_axis else {}
    horizontal = isinstance(y_axis, dict) and y_axis.get("type") == "category"
    if horizontal:
        # For horizontal bar, y-axis carries categories
        categories = [str(c) for c in (y_axis.get("data") or categories)]

    type_map = {"bar": "BAR", "line": "LINE"}
    first_type = series_list[0].get("type", "bar")
    pptx_type = type_map.get(first_type)
    if not pptx_type:
        return None
    if not categories:
        return None

    # Build series data
    chart_data: list[dict] = []
    for s in series_list:
        chart_data.append({
            "name": s.get("name", "系列"),
            "labels": categories,
            "values": _echarts_series_values(s.get("data", [])),
        })

    # Title
    title_obj = option.get("title", {})
    title = ""
    if isinstance(title_obj, dict):
        title = title_obj.get("text", "")

    # Chart styling
    colors = ["1E3A5F", "F0A500", "E85454", "4CAF50", "9C27B0", "FF5722"]
    opts: dict[str, Any] = {
        "chartColors": colors[: len(chart_data)],
        "chartArea": {"fill": {"color": "FFFFFF"}, "roundedCorners": False},
        "catAxisLabelColor": "64748B",
        "valAxisLabelColor": "64748B",
        "valGridLine": {"color": "E2E8F0", "size": 0.5},
        "catGridLine": {"style": "none"},
        "showLegend": len(chart_data) > 1,
        "legendPos": "b",
        "showTitle": False,    # title rendered as slide text instead
    }
    if pptx_type == "BAR":
        opts["barDir"] = "bar" if horizontal else "col"
        opts["barGrouping"] = "clustered" if len(chart_data) > 1 else "standard"
        if len(chart_data) == 1:
            opts["showValue"] = True
            opts["dataLabelColor"] = "1E293B"
    elif pptx_type == "LINE":
        opts["lineSmooth"] = True
        opts["lineSize"] = 2

    return {
        "type": pptx_type,
        "data": chart_data,
        "options": opts,
        "title": title,        # slide-level title text
        "horizontal": horizontal,
    }


# ---------------------------------------------------------------------------
# JS script generator
# ---------------------------------------------------------------------------

class _ScriptBuilder:
    """Accumulates lines of JavaScript and exposes emit helpers."""

    def __init__(self) -> None:
        self._lines: list[str] = []

    def emit(self, *parts: str) -> None:
        self._lines.append(" ".join(parts) if parts else "")

    def script(self) -> str:
        return "\n".join(self._lines)

    # ── Slide helpers ────────────────────────────────────────────

    def _dark_slide(self, var: str = "s") -> None:
        self.emit(f"  let {var} = pres.addSlide();")
        self.emit(f"  {var}.background = {{ color: C.primary }};")

    def _light_slide(self, var: str = "s") -> None:
        self.emit(f"  let {var} = pres.addSlide();")
        self.emit(f"  {var}.background = {{ color: C.white }};")

    def _slide_title(
        self,
        text: str,
        var: str = "s",
        color: str = "C.primary",
        size: int = 20,
    ) -> None:
        self.emit(
            f"  {var}.addText({_js(text)}, "
            f"{{ x:0.4, y:0.12, w:9.2, h:0.6, fontSize:{size}, bold:true, "
            f"color:{color}, fontFace:FONT, margin:0, valign:'middle' }});"
        )

    def _divider_line(self, var: str = "s") -> None:
        self.emit(
            f"  {var}.addShape(pres.shapes.LINE, "
            f"{{ x:0.4, y:0.78, w:9.2, h:0, line:{{color:C.accent, width:1}} }});"
        )

    def _add_chart(
        self,
        spec: dict[str, Any],
        var: str = "s",
        x: float = 0.4,
        y: float = 0.88,
        w: float = 9.2,
        h: float = 4.5,
    ) -> None:
        opts = dict(spec["options"])
        opts.update({"x": x, "y": y, "w": w, "h": h})
        self.emit(
            f"  {var}.addChart(pres.charts.{spec['type']}, "
            f"{_js(spec['data'])}, "
            f"{json.dumps(opts, ensure_ascii=False)});"
        )

    # ── Cover slide ──────────────────────────────────────────────

    def cover(self, title: str, author: str, date: str) -> None:
        self.emit("// === COVER ===")
        self.emit("{")
        self._dark_slide()
        self.emit(
            f"  s.addShape(pres.shapes.RECTANGLE, "
            f"{{ x:0, y:0, w:0.38, h:5.625, fill:{{color:C.accent}}, line:{{color:C.accent}} }});"
        )
        self.emit(
            f"  s.addText({_js(title)}, "
            f"{{ x:0.62, y:1.4, w:9.0, h:2.0, fontSize:34, bold:true, color:C.white, "
            f"fontFace:FONT, align:'left', margin:0, wrap:true, valign:'middle' }});"
        )
        self.emit(
            f"  s.addText('编制：' + {_js(author)}, "
            f"{{ x:0.62, y:3.55, w:8, h:0.5, fontSize:15, color:C.accent, "
            f"fontFace:FONT, align:'left' }});"
        )
        self.emit(
            f"  s.addText({_js(date)}, "
            f"{{ x:0.62, y:4.08, w:8, h:0.4, fontSize:13, color:C.bgLight, "
            f"fontFace:FONT_NUM, align:'left', italic:true }});"
        )
        self.emit("}")
        self.emit()

    # ── TOC slide ────────────────────────────────────────────────

    def toc(self, section_names: list[str]) -> None:
        self.emit("// === TOC ===")
        self.emit("{")
        self._light_slide()
        self._slide_title("目  录", color="C.primary", size=26)
        self._divider_line()
        for i, name in enumerate(section_names[:9]):
            y = 1.0 + i * 0.48
            num_color = "C.accent" if i == 0 else "C.neutral"
            self.emit(
                f"  s.addText({_js(f'{i+1:02d}')}, "
                f"{{ x:0.4, y:{y:.2f}, w:0.55, h:0.4, fontSize:15, bold:true, "
                f"color:{num_color}, fontFace:FONT_NUM }});"
            )
            self.emit(
                f"  s.addText({_js(name)}, "
                f"{{ x:1.0, y:{y:.2f}, w:8.6, h:0.4, fontSize:15, "
                f"color:C.primary, fontFace:FONT }});"
            )
        self.emit("}")
        self.emit()

    # ── KPI Overview slide ───────────────────────────────────────

    def kpi_overview(self, kpi_cards: list) -> None:
        if not kpi_cards:
            return
        self.emit("// === KPI OVERVIEW ===")
        self.emit("{")
        self._light_slide()
        self._slide_title("核心经营指标", color="C.primary", size=22)
        self._divider_line()

        cards = kpi_cards[:6]
        cols = min(len(cards), 3)
        rows = (len(cards) + cols - 1) // cols
        card_w = 9.2 / cols
        card_h = 4.35 / rows

        for idx, kpi in enumerate(cards):
            col = idx % cols
            row = idx // cols
            cx = 0.4 + col * card_w
            cy = 0.9 + row * card_h
            cw = card_w - 0.18
            ch = card_h - 0.2

            # Card background with subtle shadow
            self.emit(
                f"  s.addShape(pres.shapes.RECTANGLE, {{ x:{cx:.2f}, y:{cy:.2f}, "
                f"w:{cw:.2f}, h:{ch:.2f}, fill:{{color:'F8FAFC'}}, "
                f"line:{{color:'CBD5E1', width:0.75}}, "
                f"shadow:{{ type:'outer', blur:4, offset:2, angle:135, color:'000000', opacity:0.08 }} }});"
            )
            # Accent left tab
            self.emit(
                f"  s.addShape(pres.shapes.RECTANGLE, {{ x:{cx:.2f}, y:{cy:.2f}, "
                f"w:0.06, h:{ch:.2f}, fill:{{color:C.accent}}, line:{{color:C.accent}} }});"
            )
            # Label
            self.emit(
                f"  s.addText({_js(kpi.label)}, {{ x:{cx+0.12:.2f}, y:{cy+0.12:.2f}, "
                f"w:{cw-0.2:.2f}, h:0.32, fontSize:11, color:C.neutral, fontFace:FONT }});"
            )
            # Value
            val_color = (
                "C.positive" if kpi.trend == "positive"
                else "C.negative" if kpi.trend == "negative"
                else "C.primary"
            )
            val_sz = 34 if len(str(kpi.value)) < 8 else 26
            self.emit(
                f"  s.addText({_js(kpi.value)}, {{ x:{cx+0.12:.2f}, y:{cy+0.44:.2f}, "
                f"w:{cw-0.2:.2f}, h:0.7, fontSize:{val_sz}, bold:true, color:{val_color}, "
                f"fontFace:FONT_NUM }});"
            )
            # Sub label
            if kpi.sub:
                self.emit(
                    f"  s.addText({_js(kpi.sub)}, {{ x:{cx+0.12:.2f}, y:{cy+1.14:.2f}, "
                    f"w:{cw-0.2:.2f}, h:0.28, fontSize:9, color:C.neutral, fontFace:FONT }});"
                )
        self.emit("}")
        self.emit()

    # ── Section divider ──────────────────────────────────────────

    def section_divider(self, number: int, name: str) -> None:
        self.emit(f"// === SECTION {number}: {name} ===")
        self.emit("{")
        self._dark_slide()
        # Large section number — decorative, top-right
        self.emit(
            f"  s.addText({_js(f'{number:02d}')}, "
            f"{{ x:6.5, y:0.2, w:3.1, h:2.8, fontSize:120, bold:true, "
            f"color:'FFFFFF', fontFace:FONT_NUM, align:'right', margin:0, "
            f"transparency:85 }});"
        )
        # Section title
        self.emit(
            f"  s.addText({_js(name)}, "
            f"{{ x:0.6, y:2.5, w:9.0, h:1.8, fontSize:30, bold:true, "
            f"color:C.white, fontFace:FONT, wrap:true, valign:'bottom' }});"
        )
        # Accent bottom bar — short, left-aligned
        self.emit(
            f"  s.addShape(pres.shapes.RECTANGLE, "
            f"{{ x:0.6, y:4.45, w:1.2, h:0.07, fill:{{color:C.accent}}, line:{{color:C.accent}} }});"
        )
        self.emit("}")
        self.emit()

    # ── Two-column: narrative left + chart right ─────────────────

    def two_column_chart(
        self, section_name: str, narrative: str, chart_spec: dict
    ) -> None:
        self.emit("{")
        self._light_slide()
        self._slide_title(section_name)
        self._divider_line()
        # Narrative bullets on the left
        lines = [l.strip() for l in narrative.split("\n") if l.strip()][:10]
        items = []
        for line in lines:
            items.append(
                f"{{ text:{_js(line)}, options:{{bullet:{{indent:5}}, breakLine:true, "
                f"fontSize:11, color:'1E293B', paraSpaceAfter:4}} }}"
            )
        self.emit(
            f"  s.addText([{', '.join(items)}], "
            f"{{ x:0.3, y:0.88, w:4.35, h:4.5, fontFace:FONT, wrap:true, valign:'top' }});"
        )
        # Chart on the right
        self._add_chart(chart_spec, x=4.8, y=0.88, w=4.95, h=4.5)
        self.emit("}")
        self.emit()

    # ── Full-width chart slide ───────────────────────────────────

    def full_chart(self, title: str, chart_spec: dict) -> None:
        self.emit("{")
        self._light_slide()
        self._slide_title(title or "图表分析")
        self._divider_line()
        self._add_chart(chart_spec, x=0.4, y=0.88, w=9.2, h=4.52)
        self.emit("}")
        self.emit()

    # ── Narrative-only slide ─────────────────────────────────────

    def narrative(self, title: str, text: str) -> None:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        max_per = 12
        chunks = [lines[i: i + max_per] for i in range(0, max(len(lines), 1), max_per)]
        for ci, chunk in enumerate(chunks):
            suffix = f"（{ci+1}/{len(chunks)}）" if len(chunks) > 1 else ""
            self.emit("{")
            self._light_slide()
            self._slide_title(f"{title}{suffix}")
            self._divider_line()
            items = []
            for line in chunk or ["（暂无内容）"]:
                items.append(
                    f"{{ text:{_js(line)}, options:{{bullet:{{indent:5}}, breakLine:true, "
                    f"fontSize:13, color:'1E293B', paraSpaceAfter:6}} }}"
                )
            self.emit(
                f"  s.addText([{', '.join(items)}], "
                f"{{ x:0.5, y:0.88, w:9.1, h:4.5, fontFace:FONT, wrap:true, valign:'top' }});"
            )
            self.emit("}")
            self.emit()

    # ── Growth / KPI cards slide ─────────────────────────────────

    def growth_cards(self, title: str, growth_rates: dict) -> None:
        items = [
            (col, rates)
            for col, rates in growth_rates.items()
            if isinstance(rates, dict)
            and (rates.get("yoy") is not None or rates.get("mom") is not None)
        ]
        if not items:
            return
        items = items[:4]
        self.emit("{")
        self._light_slide()
        self._slide_title(title)
        self._divider_line()

        n = len(items)
        card_w = 9.2 / n
        for i, (col, rates) in enumerate(items):
            cx = 0.4 + i * card_w
            cy = 1.0
            cw = card_w - 0.2
            ch = 4.3
            self.emit(
                f"  s.addShape(pres.shapes.RECTANGLE, "
                f"{{ x:{cx:.2f}, y:{cy:.2f}, w:{cw:.2f}, h:{ch:.2f}, "
                f"fill:{{color:'F8FAFC'}}, line:{{color:'CBD5E1', width:0.75}} }});"
            )
            self.emit(
                f"  s.addText({_js(col)}, "
                f"{{ x:{cx+0.1:.2f}, y:{cy+0.18:.2f}, w:{cw-0.2:.2f}, h:0.4, "
                f"fontSize:12, bold:true, color:C.neutral, fontFace:FONT, align:'center' }});"
            )
            y_off = cy + 0.72
            for rate_type, label in [("yoy", "同比"), ("mom", "环比")]:
                val = rates.get(rate_type)
                if val is None:
                    continue
                arrow = "↑" if val >= 0 else "↓"
                color = "C.positive" if val >= 0 else "C.negative"
                self.emit(
                    f"  s.addText({_js(f'{arrow}{abs(val)*100:.1f}%')}, "
                    f"{{ x:{cx+0.1:.2f}, y:{y_off:.2f}, w:{cw-0.2:.2f}, h:0.9, "
                    f"fontSize:34, bold:true, color:{color}, fontFace:FONT_NUM, align:'center' }});"
                )
                self.emit(
                    f"  s.addText({_js(label)}, "
                    f"{{ x:{cx+0.1:.2f}, y:{y_off+0.88:.2f}, w:{cw-0.2:.2f}, h:0.3, "
                    f"fontSize:11, color:C.neutral, fontFace:FONT, align:'center' }});"
                )
                y_off += 1.4
        self.emit("}")
        self.emit()

    # ── Stats table slide ────────────────────────────────────────

    def stats_table(self, title: str, summary_stats: dict) -> None:
        # Flatten nested stats if needed
        first_val = next(iter(summary_stats.values()), None)
        if isinstance(first_val, dict) and not any(
            k in first_val for k in ("mean", "median", "std", "min", "max")
        ):
            flat: dict = {}
            for gk, cols in summary_stats.items():
                if isinstance(cols, dict):
                    for cn, metrics in cols.items():
                        flat[f"{gk}/{cn}"] = metrics if isinstance(metrics, dict) else {}
            summary_stats = flat or summary_stats

        metrics = ["mean", "median", "std", "min", "max"]
        metric_labels = [metric_label(m) for m in metrics]
        col_names = [c for c, v in summary_stats.items() if isinstance(v, dict)]
        if not col_names:
            return

        self.emit("{")
        self._light_slide()
        self._slide_title(title)
        self._divider_line()

        headers = ["指标"] + metric_labels
        rows_data: list[list[str]] = [headers]
        for col in col_names[:12]:
            vals = summary_stats[col]
            row = [str(col)]
            for m in metrics:
                v = vals.get(m)
                row.append(
                    f"{v:,.2f}" if isinstance(v, float) and abs(v) >= 1
                    else f"{v:.4f}" if isinstance(v, float)
                    else (str(v) if v is not None else "-")
                )
            rows_data.append(row)

        # Build table spec
        row_height = min(0.55, 4.0 / len(rows_data))
        table_h = row_height * len(rows_data)
        col_w = [2.2] + [1.4] * len(metrics)  # first col wider

        table_opts = {
            "x": 0.4, "y": 0.9,
            "w": 9.2, "h": min(table_h, 4.5),
            "colW": col_w,
            "border": {"pt": 0.5, "color": "E2E8F0"},
            "fontFace": "Calibri",
            "fontSize": 10,
            "align": "center",
            "autoPage": True,
        }
        # Header row styling
        hdr_cells = [
            {"text": h, "options": {
                "bold": True, "fill": {"color": "1E3A5F"},
                "color": "FFFFFF", "align": "center",
            }}
            for h in headers
        ]
        # Data rows
        table_rows: list[list] = [hdr_cells]
        for ri, row in enumerate(rows_data[1:]):
            fill_color = "F5F7FA" if ri % 2 == 0 else "FFFFFF"
            table_rows.append([
                {"text": cell, "options": {
                    "fill": {"color": fill_color},
                    "color": "1E293B",
                    "align": "left" if ci == 0 else "right",
                }}
                for ci, cell in enumerate(row)
            ])
        self.emit(
            f"  s.addTable({json.dumps(table_rows, ensure_ascii=False)}, "
            f"{json.dumps(table_opts, ensure_ascii=False)});"
        )
        self.emit("}")
        self.emit()

    # ── DataFrame table slide ────────────────────────────────────

    def dataframe_table(self, title: str, df: Any, max_rows: int = 15) -> None:
        try:
            import pandas as pd
            if df is None or df.empty:
                return
        except Exception:
            return

        display = df.head(max_rows)
        col_headers = list(display.columns)
        n_cols = len(col_headers)
        if n_cols == 0:
            return

        self.emit("{")
        self._light_slide()
        self._slide_title(title)
        self._divider_line()

        col_w_each = round(9.2 / n_cols, 2)
        col_w_list = [col_w_each] * n_cols

        hdr_cells = [
            {"text": str(h), "options": {
                "bold": True, "fill": {"color": "1E3A5F"},
                "color": "FFFFFF", "align": "center",
                "fontSize": 10,
            }}
            for h in col_headers
        ]
        table_rows: list[list] = [hdr_cells]
        for ri, (_, row) in enumerate(display.iterrows()):
            fill_color = "F5F7FA" if ri % 2 == 0 else "FFFFFF"
            cells = []
            for ci, val in enumerate(row):
                if isinstance(val, float):
                    txt = f"{val:,.2f}" if abs(val) >= 1 else f"{val:.4f}"
                else:
                    txt = str(val) if val is not None else "-"
                cells.append({"text": txt, "options": {
                    "fill": {"color": fill_color}, "color": "1E293B",
                    "align": "right" if ci > 0 else "left",
                    "fontSize": 10,
                }})
            table_rows.append(cells)

        n_rows_total = len(table_rows)
        row_h = min(0.45, 4.4 / n_rows_total)
        table_opts = {
            "x": 0.4, "y": 0.9,
            "w": 9.2, "h": min(row_h * n_rows_total, 4.5),
            "colW": col_w_list,
            "border": {"pt": 0.5, "color": "E2E8F0"},
            "fontFace": "Calibri",
        }
        self.emit(
            f"  s.addTable({json.dumps(table_rows, ensure_ascii=False)}, "
            f"{json.dumps(table_opts, ensure_ascii=False)});"
        )
        if len(df) > max_rows:
            self.emit(
                f"  s.addText({_js(f'（仅展示前 {max_rows} 行，共 {len(df)} 行）')}, "
                f"{{ x:0.4, y:5.3, w:9.2, h:0.28, fontSize:9, color:C.neutral, "
                f"fontFace:FONT, italic:true }});"
            )
        self.emit("}")
        self.emit()

    # ── Summary slide ────────────────────────────────────────────

    def summary(self, summary_texts: list[str]) -> None:
        self.emit("// === SUMMARY ===")
        self.emit("{")
        self._dark_slide()
        self._slide_title("核心结论与建议", color="C.white", size=24)
        self.emit(
            "  s.addShape(pres.shapes.LINE, "
            "{ x:0.4, y:0.78, w:9.2, h:0, line:{color:C.accent, width:1} });"
        )
        texts = summary_texts[:6]
        if not texts:
            texts = ["以上分析基于数据，仅供参考。"]
        for i, text in enumerate(texts):
            short = text[:130] + "…" if len(text) > 130 else text
            y = 1.0 + i * 0.73
            # Accent dot
            self.emit(
                f"  s.addShape(pres.shapes.OVAL, "
                f"{{ x:0.38, y:{y+0.12:.2f}, w:0.14, h:0.14, "
                f"fill:{{color:C.accent}}, line:{{color:C.accent}} }});"
            )
            self.emit(
                f"  s.addText({_js(short)}, "
                f"{{ x:0.62, y:{y:.2f}, w:9.0, h:0.65, fontSize:12, "
                f"color:C.white, fontFace:FONT, wrap:true, valign:'middle' }});"
            )
        self.emit("}")
        self.emit()

    # ── Thank you slide ──────────────────────────────────────────

    def thank_you(self) -> None:
        self.emit("// === THANK YOU ===")
        self.emit("{")
        self._dark_slide()
        self.emit(
            f"  s.addShape(pres.shapes.RECTANGLE, "
            f"{{ x:0, y:0, w:0.38, h:5.625, fill:{{color:C.accent}}, line:{{color:C.accent}} }});"
        )
        self.emit(
            f"  s.addText('谢谢观看', "
            f"{{ x:1, y:1.6, w:8.6, h:1.6, fontSize:48, bold:true, "
            f"color:C.white, fontFace:FONT, align:'center', valign:'middle' }});"
        )
        self.emit(
            f"  s.addText('THANK YOU', "
            f"{{ x:1, y:3.4, w:8.6, h:0.7, fontSize:20, "
            f"color:C.accent, fontFace:FONT_NUM, align:'center' }});"
        )
        self.emit("}")
        self.emit()


# ---------------------------------------------------------------------------
# Top-level script generator
# ---------------------------------------------------------------------------

def generate_pptxgen_script(report: ReportContent, output_path: str) -> str:
    """Return a complete, self-contained PptxGenJS Node.js script."""
    b = _ScriptBuilder()

    # ── Preamble ──────────────────────────────────────────────────────────
    b.emit("'use strict';")
    b.emit("const pptxgen = require('pptxgenjs');")
    b.emit()
    b.emit("const C = {")
    b.emit("  primary: '1E3A5F', secondary: '2D5F8A', accent: 'F0A500',")
    b.emit("  positive: '2E7D32', negative: 'C62828', neutral: '546E7A',")
    b.emit("  bgLight: 'F5F7FA', white: 'FFFFFF', text: '333333',")
    b.emit("};")
    b.emit("const FONT = 'Microsoft YaHei';")
    b.emit("const FONT_NUM = 'Calibri';")
    b.emit()
    b.emit("let pres = new pptxgen();")
    b.emit("pres.layout = 'LAYOUT_16x9';")
    b.emit(f"pres.author = {_js(report.author)};")
    b.emit(f"pres.title = {_js(report.title)};")
    b.emit()

    # ── Slides ────────────────────────────────────────────────────────────
    b.cover(report.title, report.author, report.date or "")
    b.toc([s.name for s in report.sections])

    if report.kpi_cards:
        b.kpi_overview(report.kpi_cards)

    for sec_idx, section in enumerate(report.sections, 1):
        narratives = [it for it in section.items if isinstance(it, NarrativeItem)]
        chart_items = [it for it in section.items if isinstance(it, ChartDataItem)]
        growth_items = [it for it in section.items if isinstance(it, GrowthItem)]
        stats_items = [it for it in section.items if isinstance(it, StatsTableItem)]
        df_items = [it for it in section.items if isinstance(it, DataFrameItem)]

        if not (narratives or chart_items or growth_items or stats_items or df_items):
            continue

        b.section_divider(sec_idx, section.name)

        # KPI / growth cards first (high-impact, visual)
        for gi in growth_items:
            b.growth_cards(section.name, gi.growth_rates)

        # Charts — pair with narrative when possible (two-column layout)
        remaining_narratives = list(narratives)
        for ci in chart_items:
            spec = echarts_to_pptxgen(ci.option)
            chart_title = ci.title or (spec["title"] if spec else "") or section.name
            if spec:
                if remaining_narratives:
                    nar = remaining_narratives.pop(0)
                    b.two_column_chart(chart_title, nar.text, spec)
                else:
                    b.full_chart(chart_title, spec)
            else:
                # Waterfall / unsupported → render chart data as a table
                x_axis = ci.option.get("xAxis", {})
                if isinstance(x_axis, list):
                    x_axis = x_axis[0] if x_axis else {}
                categories = (x_axis.get("data") or []) if isinstance(x_axis, dict) else []
                series_list = ci.option.get("series", [])
                if categories and series_list:
                    # Filter out transparent base series (waterfall)
                    visible = [
                        s for s in series_list
                        if "transparent" not in str(
                            (s.get("itemStyle") or {}).get("color", "")
                        )
                    ]
                    if visible:
                        # Build a mini DataFrame-like structure inline
                        import pandas as pd  # noqa: PLC0415
                        col_data: dict[str, list] = {"类别": [str(c) for c in categories]}
                        for s in visible:
                            raw = s.get("data", [])
                            col_data[s.get("name", "值")] = _echarts_series_values(raw)
                        df_tmp = pd.DataFrame(col_data)
                        b.dataframe_table(chart_title, df_tmp)

        # Remaining unpaired narratives
        for nar in remaining_narratives:
            b.narrative(section.name, nar.text)

        # Stats tables
        for si in stats_items:
            b.stats_table(f"{section.name} — 统计概览", si.summary_stats)

        # DataFrame tables
        for di in df_items:
            b.dataframe_table(section.name, di.df)

    # Summary + thank you
    summary_texts = [si.text for si in report.summary_items]
    b.summary(summary_texts)
    b.thank_you()

    # ── Write file ────────────────────────────────────────────────────────
    b.emit(f"pres.writeFile({{ fileName: {_js(output_path)} }})")
    b.emit("  .then(() => { console.log('PPTX_OK'); })")
    b.emit("  .catch(err => { console.error('PPTX_ERROR:', err.message); process.exit(1); });")

    return b.script()


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def render_to_pptx(report: ReportContent) -> bytes:
    """Generate a PPTX file via PptxGenJS and return the raw bytes.

    Raises ``RuntimeError`` when Node.js or pptxgenjs is unavailable,
    or when the script fails.  The caller should catch and fall back to
    python-pptx.
    """
    if not check_pptxgen_available():
        raise RuntimeError("PptxGenJS not available (Node.js or pptxgenjs missing)")

    node = _find_node()
    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = os.path.join(tmpdir, "report.pptx")
        js_path = os.path.join(tmpdir, "gen.js")

        script = generate_pptxgen_script(report, out_path)
        with open(js_path, "w", encoding="utf-8") as f:
            f.write(script)

        env = dict(os.environ)
        if _NODE_PATH:
            env["NODE_PATH"] = _NODE_PATH + os.pathsep + env.get("NODE_PATH", "")

        try:
            result = subprocess.run(
                [node, js_path],
                capture_output=True,
                text=True,
                timeout=60,
                env=env,
                cwd=tmpdir,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("PptxGenJS script timed out") from exc

        if result.returncode != 0:
            stderr_snippet = (result.stderr or "")[:500]
            raise RuntimeError(f"PptxGenJS script failed: {stderr_snippet}")
        if "PPTX_OK" not in result.stdout:
            raise RuntimeError(
                f"PptxGenJS did not emit PPTX_OK. stdout={result.stdout[:200]}"
            )
        if not os.path.exists(out_path):
            raise RuntimeError("PptxGenJS reported success but no output file found")

        with open(out_path, "rb") as f:
            return f.read()
