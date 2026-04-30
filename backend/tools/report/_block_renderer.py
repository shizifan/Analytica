"""BlockRenderer protocol + dispatcher — Step 2 of the outline refactor
(see spec/refactor_report_outline.md).

The four backend renderers (Markdown / DOCX / PPTX / HTML) implement the
``BlockRenderer`` protocol. ``render_outline`` walks an outline once and
calls the matching ``emit_*`` for each block kind. New block kinds are
added in three places only: ``_outline.py`` (data class), this dispatch,
and each renderer's ``emit_*`` method — never in business code.

``BlockRendererBase`` provides a default implementation that raises
``NotImplementedError`` for every method. Concrete renderers inherit
from it and override the methods they need; Step 3-6 fill these in
incrementally.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.tools.report._outline import (
    Asset,
    Block,
    ChartBlock,
    ChartTablePairBlock,
    ComparisonGridBlock,
    GrowthIndicatorsBlock,
    KpiRowBlock,
    OutlineSection,
    ParagraphBlock,
    ReportOutline,
    SectionCoverBlock,
    TableBlock,
)


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------

@runtime_checkable
class BlockRenderer(Protocol):
    """All four backends conform to this protocol.

    Each renderer holds its own internal state (a ``Document`` /
    ``Presentation`` / string buffer) and emits ``begin_document`` once
    at the start, then ``begin_section`` / ``emit_*`` / ``end_section``
    pairs per section, then ``end_document`` once at the end.

    ``end_document`` returns the final payload — ``bytes`` for binary
    formats (DOCX/PPTX) and ``str`` for text (HTML/Markdown).
    """

    def begin_document(self, outline: ReportOutline) -> None: ...
    def end_document(self) -> bytes | str: ...

    def begin_section(self, section: OutlineSection, index: int) -> None: ...
    def end_section(self, section: OutlineSection, index: int) -> None: ...

    def emit_kpi_row(self, block: KpiRowBlock) -> None: ...
    def emit_paragraph(self, block: ParagraphBlock) -> None: ...
    def emit_table(self, block: TableBlock, asset: Asset) -> None: ...
    def emit_chart(self, block: ChartBlock, asset: Asset) -> None: ...
    def emit_chart_table_pair(
        self,
        block: ChartTablePairBlock,
        chart_asset: Asset,
        table_asset: Asset,
    ) -> None: ...
    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None: ...
    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None: ...
    def emit_section_cover(self, block: SectionCoverBlock) -> None: ...


# ---------------------------------------------------------------------------
# Skeleton base — concrete renderers inherit and override
# ---------------------------------------------------------------------------

class BlockRendererBase:
    """Default skeleton: every method raises ``NotImplementedError``.

    Step 3 replaces these in ``MarkdownBlockRenderer``; Steps 4-6 do the
    same for DOCX/PPTX/HTML. Skeletons protect against silent no-ops —
    if a Step's renderer forgets to override ``emit_chart_table_pair``,
    rendering an outline that contains one will fail loudly.

    Phase 1 (Sprint 3) adds the ``theme`` keyword: every concrete renderer
    accepts an optional ``theme`` and falls back to the default
    ``corporate-blue`` preset. New visual code should read
    ``self._theme.*`` instead of the module-level legacy constants.
    """

    _step_label: str = "Step 3-6"

    def __init__(self, theme=None):  # noqa: ANN001 — Theme typed via late import
        from backend.tools.report._theme import get_theme

        self._theme = theme if theme is not None else get_theme()

    def _todo(self, method: str) -> None:
        raise NotImplementedError(
            f"{type(self).__name__}.{method} pending ({self._step_label})"
        )

    def begin_document(self, outline: ReportOutline) -> None:
        self._todo("begin_document")

    def end_document(self) -> bytes | str:
        self._todo("end_document")
        raise AssertionError("unreachable")  # for type-checkers

    def begin_section(self, section: OutlineSection, index: int) -> None:
        self._todo("begin_section")

    def end_section(self, section: OutlineSection, index: int) -> None:
        self._todo("end_section")

    def emit_kpi_row(self, block: KpiRowBlock) -> None:
        self._todo("emit_kpi_row")

    def emit_paragraph(self, block: ParagraphBlock) -> None:
        self._todo("emit_paragraph")

    def emit_table(self, block: TableBlock, asset: Asset) -> None:
        self._todo("emit_table")

    def emit_chart(self, block: ChartBlock, asset: Asset) -> None:
        self._todo("emit_chart")

    def emit_chart_table_pair(
        self,
        block: ChartTablePairBlock,
        chart_asset: Asset,
        table_asset: Asset,
    ) -> None:
        self._todo("emit_chart_table_pair")

    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None:
        self._todo("emit_comparison_grid")

    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None:
        self._todo("emit_growth_indicators")

    def emit_section_cover(self, block: SectionCoverBlock) -> None:
        self._todo("emit_section_cover")


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

def render_outline(
    outline: ReportOutline,
    renderer: BlockRenderer,
) -> bytes | str:
    """Walk the outline once, dispatching each block to the renderer.

    Order of calls:
        begin_document(outline)
        for each section:
            begin_section(section, idx)
            for each block: emit_*(block, [asset…])
            end_section(section, idx)
        end_document()  → bytes | str
    """
    renderer.begin_document(outline)
    for idx, section in enumerate(outline.sections):
        renderer.begin_section(section, idx)
        for block in section.blocks:
            _dispatch(block, outline, renderer)
        renderer.end_section(section, idx)
    return renderer.end_document()


def _dispatch(
    block: Block,
    outline: ReportOutline,
    renderer: BlockRenderer,
) -> None:
    """Route one block to the renderer's matching ``emit_*`` method.

    Raises ``ValueError`` for unknown block kinds — the outline data
    model is the single source of truth, so an unknown kind here means
    the renderer is out of sync with ``_outline.py``.
    """
    match block:
        case KpiRowBlock():
            renderer.emit_kpi_row(block)
        case ParagraphBlock():
            renderer.emit_paragraph(block)
        case TableBlock():
            renderer.emit_table(block, outline.get_asset(block.asset_id))
        case ChartBlock():
            renderer.emit_chart(block, outline.get_asset(block.asset_id))
        case ChartTablePairBlock():
            renderer.emit_chart_table_pair(
                block,
                outline.get_asset(block.chart_asset_id),
                outline.get_asset(block.table_asset_id),
            )
        case ComparisonGridBlock():
            renderer.emit_comparison_grid(block)
        case GrowthIndicatorsBlock():
            renderer.emit_growth_indicators(block)
        case SectionCoverBlock():
            renderer.emit_section_cover(block)
        case _:
            raise ValueError(
                f"Unknown block kind: {type(block).__name__} "
                f"(block_id={getattr(block, 'block_id', '?')})"
            )
