"""ReportOutline data model — Step 1 of the outline refactor
(see spec/refactor_report_outline.md).

This module defines the intermediate representation that decouples
content collection (Stage 1) and planning (Stage 2) from rendering
(Stage 3). The four backend renderers (DOCX/PPTX/HTML/Markdown) all
consume the same ``ReportOutline``.

Design notes:
- Blocks are a discriminated union keyed by ``kind``. JSON serialisation
  round-trips via ``ReportOutline.to_json`` / ``from_json``.
- Assets are stored once in ``ReportOutline.assets`` and referenced by
  ``asset_id`` from blocks — lets the same chart/table appear in
  multiple places without duplicating the underlying payload.
- ID minting is process-global and resettable for test determinism;
  the ``reset_id_counters()`` helper is the only public knob.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass, field, asdict
from typing import Any, Literal, Union

from backend.tools.report._kpi_extractor import KPIItem


SCHEMA_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

BlockKind = Literal[
    "kpi_row",
    "paragraph",
    "table",
    "chart",
    "chart_table_pair",
    "comparison_grid",
    "growth_indicators",
    "section_cover",
]

SectionRole = Literal[
    "summary",
    "status",
    "analysis",
    "attribution",
    "recommendation",
    "appendix",
]

ParagraphStyle = Literal["body", "lead", "callout-warn", "callout-info"]

GridLayout = Literal["h", "v"]


# ---------------------------------------------------------------------------
# ID minting
# ---------------------------------------------------------------------------

_BLOCK_COUNTER: itertools.count = itertools.count(1)
_ASSET_COUNTERS: dict[str, itertools.count] = {
    "chart": itertools.count(1),
    "table": itertools.count(1),
    "stats": itertools.count(1),
}

_ASSET_PREFIX = {"chart": "C", "table": "T", "stats": "S"}


def new_block_id() -> str:
    return f"B{next(_BLOCK_COUNTER):04d}"


def new_asset_id(kind: str) -> str:
    if kind not in _ASSET_PREFIX:
        raise ValueError(f"Unknown asset kind: {kind!r}")
    return f"{_ASSET_PREFIX[kind]}{next(_ASSET_COUNTERS[kind]):04d}"


def reset_id_counters() -> None:
    """Reset both block and asset counters. Tests call this in setup
    so generated IDs are deterministic across runs."""
    global _BLOCK_COUNTER
    _BLOCK_COUNTER = itertools.count(1)
    for k in _ASSET_COUNTERS:
        _ASSET_COUNTERS[k] = itertools.count(1)


# ---------------------------------------------------------------------------
# Assets
# ---------------------------------------------------------------------------

@dataclass
class ChartAsset:
    asset_id: str
    source_task: str
    option: dict[str, Any]
    endpoint: str | None = None
    kind: Literal["chart"] = "chart"


@dataclass
class TableAsset:
    asset_id: str
    source_task: str
    df_records: list[dict[str, Any]]
    columns_meta: list[dict[str, Any]] = field(default_factory=list)
    endpoint: str | None = None
    kind: Literal["table"] = "table"


@dataclass
class StatsAsset:
    asset_id: str
    source_task: str
    summary_stats: dict[str, Any]
    endpoint: str | None = None
    kind: Literal["stats"] = "stats"


Asset = Union[ChartAsset, TableAsset, StatsAsset]

_ASSET_CLASS_BY_KIND: dict[str, type] = {
    "chart": ChartAsset,
    "table": TableAsset,
    "stats": StatsAsset,
}


# ---------------------------------------------------------------------------
# Blocks
# ---------------------------------------------------------------------------

@dataclass
class KpiRowBlock:
    block_id: str
    items: list[KPIItem] = field(default_factory=list)
    kind: Literal["kpi_row"] = "kpi_row"


@dataclass
class ParagraphBlock:
    block_id: str
    text: str
    style: ParagraphStyle = "body"
    kind: Literal["paragraph"] = "paragraph"


@dataclass
class TableBlock:
    block_id: str
    asset_id: str
    caption: str = ""
    highlight_rules: list[dict[str, Any]] = field(default_factory=list)
    kind: Literal["table"] = "table"


@dataclass
class ChartBlock:
    block_id: str
    asset_id: str
    caption: str = ""
    kind: Literal["chart"] = "chart"


@dataclass
class ChartTablePairBlock:
    block_id: str
    chart_asset_id: str
    table_asset_id: str
    layout: GridLayout = "h"
    kind: Literal["chart_table_pair"] = "chart_table_pair"


@dataclass
class GridColumn:
    title: str
    items: list[str] = field(default_factory=list)


@dataclass
class ComparisonGridBlock:
    block_id: str
    columns: list[GridColumn] = field(default_factory=list)
    kind: Literal["comparison_grid"] = "comparison_grid"


@dataclass
class GrowthIndicatorsBlock:
    block_id: str
    growth_rates: dict[str, dict[str, float | None]] = field(default_factory=dict)
    kind: Literal["growth_indicators"] = "growth_indicators"


@dataclass
class SectionCoverBlock:
    block_id: str
    index: int
    title: str
    subtitle: str = ""
    kind: Literal["section_cover"] = "section_cover"


Block = Union[
    KpiRowBlock,
    ParagraphBlock,
    TableBlock,
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GrowthIndicatorsBlock,
    SectionCoverBlock,
]

_BLOCK_CLASS_BY_KIND: dict[str, type] = {
    "kpi_row": KpiRowBlock,
    "paragraph": ParagraphBlock,
    "table": TableBlock,
    "chart": ChartBlock,
    "chart_table_pair": ChartTablePairBlock,
    "comparison_grid": ComparisonGridBlock,
    "growth_indicators": GrowthIndicatorsBlock,
    "section_cover": SectionCoverBlock,
}


# ---------------------------------------------------------------------------
# Section + Outline
# ---------------------------------------------------------------------------

@dataclass
class OutlineSection:
    name: str
    role: SectionRole = "status"
    blocks: list[Block] = field(default_factory=list)
    source_tasks: list[str] = field(default_factory=list)


PlannerMode = Literal["llm", "rule_fallback"]


@dataclass
class ReportOutline:
    metadata: dict[str, Any] = field(default_factory=dict)
    schema_version: str = SCHEMA_VERSION
    kpi_summary: list[KPIItem] = field(default_factory=list)
    sections: list[OutlineSection] = field(default_factory=list)
    assets: dict[str, Asset] = field(default_factory=dict)
    degradations: list[dict[str, Any]] = field(default_factory=list)
    planner_mode: PlannerMode = "rule_fallback"

    # ---- Convenience accessors used by renderers -----------------------

    def get_asset(self, asset_id: str) -> Asset:
        if asset_id not in self.assets:
            raise KeyError(f"asset_id {asset_id!r} not in outline.assets")
        return self.assets[asset_id]

    def find_block(self, block_id: str) -> Block | None:
        for sec in self.sections:
            for blk in sec.blocks:
                if blk.block_id == block_id:
                    return blk
        return None

    # ---- JSON round-trip -----------------------------------------------

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "metadata": dict(self.metadata),
            "kpi_summary": [_kpi_to_dict(k) for k in self.kpi_summary],
            "sections": [_section_to_dict(s) for s in self.sections],
            "assets": {aid: asdict(a) for aid, a in self.assets.items()},
            "degradations": [dict(d) for d in self.degradations],
            "planner_mode": self.planner_mode,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "ReportOutline":
        version = data.get("schema_version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            raise ValueError(
                f"Unsupported outline schema_version: {version!r} "
                f"(expected {SCHEMA_VERSION})"
            )
        return cls(
            schema_version=version,
            metadata=dict(data.get("metadata", {})),
            kpi_summary=[_kpi_from_dict(k) for k in data.get("kpi_summary", [])],
            sections=[_section_from_dict(s) for s in data.get("sections", [])],
            assets={aid: _asset_from_dict(a) for aid, a in data.get("assets", {}).items()},
            degradations=[dict(d) for d in data.get("degradations", [])],
            planner_mode=data.get("planner_mode", "rule_fallback"),
        )


# ---------------------------------------------------------------------------
# Internal serialisation helpers
# ---------------------------------------------------------------------------

def _kpi_to_dict(k: KPIItem) -> dict[str, Any]:
    return {"label": k.label, "value": k.value, "sub": k.sub, "trend": k.trend}


def _kpi_from_dict(d: dict[str, Any]) -> KPIItem:
    return KPIItem(
        label=d["label"],
        value=d["value"],
        sub=d.get("sub", ""),
        trend=d.get("trend"),
    )


def _section_to_dict(s: OutlineSection) -> dict[str, Any]:
    return {
        "name": s.name,
        "role": s.role,
        "blocks": [_block_to_dict(b) for b in s.blocks],
        "source_tasks": list(s.source_tasks),
    }


def _section_from_dict(d: dict[str, Any]) -> OutlineSection:
    return OutlineSection(
        name=d["name"],
        role=d.get("role", "status"),
        blocks=[_block_from_dict(b) for b in d.get("blocks", [])],
        source_tasks=list(d.get("source_tasks", [])),
    )


def _block_to_dict(b: Block) -> dict[str, Any]:
    raw = asdict(b)
    if isinstance(b, KpiRowBlock):
        raw["items"] = [_kpi_to_dict(it) for it in b.items]
    return raw


def _block_from_dict(d: dict[str, Any]) -> Block:
    kind = d.get("kind")
    cls = _BLOCK_CLASS_BY_KIND.get(kind)
    if cls is None:
        raise ValueError(f"Unknown block kind in JSON: {kind!r}")
    payload = {k: v for k, v in d.items() if k != "kind"}
    if cls is KpiRowBlock:
        payload["items"] = [_kpi_from_dict(it) for it in payload.get("items", [])]
    if cls is ComparisonGridBlock:
        payload["columns"] = [
            GridColumn(title=c["title"], items=list(c.get("items", [])))
            for c in payload.get("columns", [])
        ]
    return cls(**payload)


def _asset_from_dict(d: dict[str, Any]) -> Asset:
    kind = d.get("kind")
    cls = _ASSET_CLASS_BY_KIND.get(kind)
    if cls is None:
        raise ValueError(f"Unknown asset kind in JSON: {kind!r}")
    payload = {k: v for k, v in d.items() if k != "kind"}
    return cls(**payload)
