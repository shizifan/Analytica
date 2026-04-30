"""PptxGenJS environment + ECharts→pptxgenjs converter.

Post-阶段 0 (Sprint 2 closure) this module is intentionally thin —
the heavy lifting moved to ``_renderers/pptxgen.py`` (Python-side
SlideCommand emission) and ``pptxgen_executor.js`` (Node-side renderer).

What lives here:
- ``check_pptxgen_available`` — process-cached probe for Node + pptxgenjs
- ``_find_node`` / ``_find_pptxgenjs_root`` — used by ``_pptxgen_runtime``
  to set ``NODE_PATH`` for the executor subprocess
- ``echarts_to_pptxgen`` — the chart-spec converter consumed by the
  PptxGenJSBlockRenderer when emitting ``AddChart`` commands

The pre-Sprint-2 ``generate_pptxgen_script`` / ``render_to_pptx`` /
``_ScriptBuilder`` (~700 LOC of templated JS string generation) were
removed in Step 0.5 once the SlideCommand DSL replaced them.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from typing import Any

logger = logging.getLogger("analytica.tools.pptxgen_builder")

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


_DEFAULT_CHART_PALETTE = (
    "1E3A5F", "F0A500", "E85454", "4CAF50", "9C27B0", "FF5722",
)


def _extract_title(option: dict[str, Any]) -> str:
    title_obj = option.get("title", {})
    if isinstance(title_obj, dict):
        return title_obj.get("text", "") or ""
    if isinstance(title_obj, str):
        return title_obj
    return ""


def _base_options(n_series: int) -> dict[str, Any]:
    return {
        "chartColors": list(_DEFAULT_CHART_PALETTE[:n_series]),
        "chartArea": {"fill": {"color": "FFFFFF"}, "roundedCorners": False},
        "catAxisLabelColor": "64748B",
        "valAxisLabelColor": "64748B",
        "valGridLine": {"color": "E2E8F0", "size": 0.5},
        "catGridLine": {"style": "none"},
        "showLegend": n_series > 1,
        "legendPos": "b",
        "showTitle": False,    # title rendered as slide text instead
    }


def _convert_pie_like(
    option: dict[str, Any],
    series_list: list[dict],
    pptx_type: str,
) -> dict[str, Any] | None:
    """Convert a single-series PIE / DOUGHNUT option.

    ECharts pie data is ``[{name, value}, ...]``; pptxgenjs PIE expects
    ``[{name, labels: [str...], values: [float...]}]`` (legacy unified
    shape — labels carry the slice names, values the numbers).
    """
    s = series_list[0]
    raw = s.get("data") or []
    labels: list[str] = []
    values: list[float] = []
    for item in raw:
        if isinstance(item, dict):
            labels.append(str(item.get("name", "")))
            try:
                values.append(float(item.get("value") or 0))
            except (TypeError, ValueError):
                values.append(0.0)
    if not labels or sum(values) <= 0:
        return None

    chart_data = [{
        "name": s.get("name") or ("饼图" if pptx_type == "PIE" else "环形图"),
        "labels": labels,
        "values": values,
    }]
    opts = _base_options(len(labels))
    # Per-slice palette via chartColors length matching slice count
    opts["chartColors"] = [
        _DEFAULT_CHART_PALETTE[i % len(_DEFAULT_CHART_PALETTE)]
        for i in range(len(labels))
    ]
    opts["showLegend"] = True
    opts["showPercent"] = True
    opts["dataLabelColor"] = "FFFFFF"
    if pptx_type == "DOUGHNUT":
        opts["holeSize"] = 50  # 0–90, larger = wider hole

    return {
        "type": pptx_type,
        "data": chart_data,
        "options": opts,
        "title": _extract_title(option),
        "horizontal": False,
    }


def _convert_combo(
    option: dict[str, Any],
    series_list: list[dict],
    categories: list[str],
) -> dict[str, Any] | None:
    """BAR + LINE on shared category axis. Each series carries its own
    ``type`` so pptxgenjs renders a multi-type chart."""
    if not categories:
        return None

    # pptxgenjs multi-type chart shape: addChart accepts a list whose
    # elements each have {type, data, options}.
    bar_data: list[dict] = []
    line_data: list[dict] = []
    for s in series_list:
        stype = (s.get("type") or "").lower()
        entry = {
            "name": s.get("name", "系列"),
            "labels": categories,
            "values": _echarts_series_values(s.get("data") or []),
        }
        if stype == "bar":
            bar_data.append(entry)
        elif stype == "line":
            line_data.append(entry)

    if not bar_data or not line_data:
        return None

    bar_opts = _base_options(len(bar_data))
    bar_opts["barDir"] = "col"
    bar_opts["barGrouping"] = "clustered" if len(bar_data) > 1 else "standard"
    bar_opts["showLegend"] = True

    line_opts = _base_options(len(line_data))
    line_opts["lineSmooth"] = True
    line_opts["lineSize"] = 2
    line_opts["secondaryValAxis"] = True
    line_opts["secondaryCatAxis"] = True
    line_opts["showLegend"] = True

    return {
        "type": "COMBO",
        "data": [
            {"type": "BAR", "data": bar_data, "options": bar_opts},
            {"type": "LINE", "data": line_data, "options": line_opts},
        ],
        "options": {},  # outer options not used by Node executor for COMBO
        "title": _extract_title(option),
        "horizontal": False,
    }


def echarts_to_pptxgen(option: dict[str, Any]) -> dict[str, Any] | None:
    """Convert an ECharts option to a PptxGenJS chart spec.

    Returns a dict with keys ``type``, ``data``, ``options``, ``title``,
    ``horizontal`` — or ``None`` when the chart cannot be natively
    represented (e.g. waterfall, scatter, radar). Caller falls back to a
    data table.

    Supported types (Phase 2.3):
      - BAR (vertical / horizontal)
      - LINE
      - PIE
      - DOUGHNUT
      - COMBO (BAR + LINE on shared categories, line on secondary axis)
    """
    series_list = option.get("series", [])
    if not series_list:
        return None
    if _is_waterfall(series_list):
        return None

    # ── PIE / DOUGHNUT short-circuit (no axes) ──
    series_types = [(s.get("type") or "").lower() for s in series_list]
    first_type = series_types[0]
    if first_type in ("pie", "doughnut"):
        pptx_pie_type = "DOUGHNUT" if first_type == "doughnut" else "PIE"
        return _convert_pie_like(option, series_list, pptx_pie_type)

    # ── Cartesian: extract category axis ──
    x_axis = option.get("xAxis", {})
    if isinstance(x_axis, list):
        x_axis = x_axis[0] if x_axis else {}
    categories: list[str] = []
    if isinstance(x_axis, dict):
        categories = [str(c) for c in (x_axis.get("data") or [])]

    y_axis = option.get("yAxis", {})
    if isinstance(y_axis, list):
        y_axis = y_axis[0] if y_axis else {}
    horizontal = isinstance(y_axis, dict) and y_axis.get("type") == "category"
    if horizontal:
        categories = [str(c) for c in (y_axis.get("data") or categories)]

    if not categories:
        return None

    # ── COMBO (mixed BAR + LINE) ──
    if {"bar", "line"}.issubset(set(series_types)):
        return _convert_combo(option, series_list, categories)

    # ── Pure BAR / LINE ──
    type_map = {"bar": "BAR", "line": "LINE"}
    pptx_type = type_map.get(first_type)
    if not pptx_type:
        return None

    chart_data: list[dict] = []
    for s in series_list:
        chart_data.append({
            "name": s.get("name", "系列"),
            "labels": categories,
            "values": _echarts_series_values(s.get("data") or []),
        })

    opts = _base_options(len(chart_data))
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
        "title": _extract_title(option),
        "horizontal": horizontal,
    }
