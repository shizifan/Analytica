"""Domain-aware KPI extraction for report cover blocks.

The HTML/DOCX themes ship with a ``.kpi-card`` style that went entirely
unused before batch 4 — nothing ever populated a KPI row. This module fills
the gap by pattern-matching upstream task outputs against per-domain rules
and emitting structured ``KPIItem``s that the renderers surface in the
first section.

Rules are intentionally narrow (task-id + field names specific to the port
analytics templates) so the extractor stays deterministic and fast. Domains
without explicit rules simply yield an empty list — the renderer skips the
KPI block cleanly.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import pandas as pd

logger = logging.getLogger("analytica.skills.report.kpi")


@dataclass
class KPIItem:
    """A single metric card surfaced above section 1 in the report.

    Attributes:
        label:  Short label shown at the top of the card (e.g. "吞吐量完成率").
        value:  Formatted primary value (e.g. "17.3%").
        sub:    Optional subtitle (e.g. "目标 48,000 万吨").
        trend:  ``"positive"`` / ``"negative"`` / None — drives CSS class.
    """
    label: str
    value: str
    sub: str = ""
    trend: str | None = None


# ── Primitives used by rules ─────────────────────────────────────

def _df_cell(output: Any, field: str) -> float | None:
    """Extract the first row's ``field`` value from a DataFrame output."""
    data = getattr(output, "data", None)
    if not isinstance(data, pd.DataFrame) or data.empty or field not in data.columns:
        return None
    try:
        return float(data.iloc[0][field])
    except Exception:
        return None


def _df_column_mean(output: Any, field: str) -> float | None:
    """Mean of ``field`` over all rows (skips NaNs)."""
    data = getattr(output, "data", None)
    if not isinstance(data, pd.DataFrame) or data.empty or field not in data.columns:
        return None
    series = pd.to_numeric(data[field], errors="coerce").dropna()
    if series.empty:
        return None
    return float(series.mean())


def _format_big_number(value: float, unit: str = "") -> str:
    """Human-readable: 1.23亿 / 456.7万 / 123.45 / 0.123."""
    if value is None:
        return "-"
    abs_v = abs(value)
    if abs_v >= 1e8:
        return f"{value / 1e8:.2f}亿{unit}"
    if abs_v >= 1e4:
        return f"{value / 1e4:.1f}万{unit}"
    if abs_v >= 1:
        return f"{value:,.2f}{unit}"
    return f"{value:.4f}{unit}"


def _format_percentage(ratio: float) -> str:
    if ratio is None:
        return "-"
    return f"{ratio * 100:.1f}%" if abs(ratio) < 5 else f"{ratio:.1f}%"


def _trend_of(value: float | None, positive_better: bool = True) -> str | None:
    if value is None:
        return None
    if value > 0:
        return "positive" if positive_better else "negative"
    if value < 0:
        return "negative" if positive_better else "positive"
    return None


# ── Per-domain extractors ────────────────────────────────────────

def _extract_throughput(context: dict[str, Any]) -> list[KPIItem]:
    """Throughput analyst template — expects T001 (吨 KPI), T002 (TEU KPI),
    T003 (monthly throughput with yoyRate in some APIs)."""
    items: list[KPIItem] = []

    # T001 / T002: completion rate = finishQty / targetQty
    for task_id, label, unit in [
        ("T001", "吞吐量完成率", "吨"),
        ("T002", "TEU 完成率", "TEU"),
    ]:
        out = context.get(task_id)
        if out is None or getattr(out, "status", "") not in ("success", "partial"):
            continue
        finish = _df_cell(out, "finishQty")
        target = _df_cell(out, "targetQty")
        if target in (None, 0) or finish is None:
            continue
        ratio = finish / target
        trend = "positive" if ratio >= 0.9 else "negative"
        items.append(KPIItem(
            label=label,
            value=_format_percentage(ratio),
            sub=f"实际 {_format_big_number(finish, unit)} / 目标 {_format_big_number(target, unit)}",
            trend=trend,
        ))

    # T003: YoY growth rate (mean of yoyRate across months if available)
    out = context.get("T003")
    if out is not None and getattr(out, "status", "") in ("success", "partial"):
        yoy_mean = _df_column_mean(out, "yoyRate")
        if yoy_mean is not None:
            items.append(KPIItem(
                label="吞吐量同比",
                value=_format_percentage(yoy_mean / 100 if abs(yoy_mean) > 1 else yoy_mean),
                sub="月度 YoY 均值",
                trend=_trend_of(yoy_mean, positive_better=True),
            ))

    return items


def _extract_customer(context: dict[str, Any]) -> list[KPIItem]:
    """Customer insight template — expects client contribution data."""
    items: list[KPIItem] = []
    # Best-effort: look for common customer-related fields across T001-T005
    for task_id in ("T001", "T002", "T003"):
        out = context.get(task_id)
        if out is None or getattr(out, "status", "") not in ("success", "partial"):
            continue
        for field, label in [
            ("clientCount", "客户总数"),
            ("yoyRate", "客户同比"),
            ("contributionRate", "头部集中度"),
        ]:
            val = _df_cell(out, field)
            if val is None:
                continue
            if "Rate" in field or "rate" in field:
                items.append(KPIItem(
                    label=label,
                    value=_format_percentage(val / 100 if abs(val) > 1 else val),
                    trend=_trend_of(val, positive_better=(field != "contributionRate")),
                ))
            else:
                items.append(KPIItem(
                    label=label,
                    value=_format_big_number(val),
                ))
            if len(items) >= 4:
                return items
    return items


def _extract_asset(context: dict[str, Any]) -> list[KPIItem]:
    """Asset investment template — expects investment completion & ops metrics."""
    items: list[KPIItem] = []
    for task_id in ("T001", "T002"):
        out = context.get(task_id)
        if out is None or getattr(out, "status", "") not in ("success", "partial"):
            continue
        finish = _df_cell(out, "finishAmount") or _df_cell(out, "finishQty")
        target = _df_cell(out, "targetAmount") or _df_cell(out, "targetQty")
        if target and finish is not None:
            ratio = finish / target
            items.append(KPIItem(
                label="投资完成率",
                value=_format_percentage(ratio),
                sub=f"实际 {_format_big_number(finish, '元')} / 目标 {_format_big_number(target, '元')}",
                trend="positive" if ratio >= 0.9 else "negative",
            ))
    return items


_DOMAIN_EXTRACTORS = {
    "throughput": _extract_throughput,
    "customer": _extract_customer,
    "asset": _extract_asset,
}


# ── Public API ───────────────────────────────────────────────────

def extract_kpis(template_meta: dict[str, Any], context: dict[str, Any]) -> list[KPIItem]:
    """Run the domain-appropriate KPI extractor.

    Returns an empty list when the domain is unknown or no rule matches —
    the renderers interpret an empty list as "don't render the KPI block".
    """
    from backend.skills._llm import infer_domain

    template_id = (template_meta or {}).get("template_id") or ""
    domain = infer_domain(template_id)
    extractor = _DOMAIN_EXTRACTORS.get(domain)
    if extractor is None:
        return []
    try:
        return extractor(context)
    except Exception as e:
        logger.warning("KPI extraction failed for domain=%s: %s", domain, e)
        return []
