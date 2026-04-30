"""SlideCommand DSL — Step 0.1 of Sprint 2 closure (阶段 0).

This module defines the intermediate representation (IR) that decouples
the Python-side `PptxGenJSBlockRenderer` (Step 0.2) from the Node-side
`pptxgen_executor.js` (Step 0.3).

Why an IR:
- The Python renderer holds **all** layout decisions (positions, sizes,
  fonts, colours) and emits a sequence of *commands* — each command
  maps 1:1 to a single pptxgenjs API call.
- The Node executor stays small: it only walks the command list and
  dispatches to ``slide.addText`` / ``slide.addChart`` / etc.
- Adding a new visual capability is a 3-line change: extend the
  Command union here, emit it from a renderer method, handle it in the
  executor's switch.

Coordinate convention (matches pptxgenjs default LAYOUT_WIDE):
- Slide is 13.333 inches wide × 7.5 inches tall.
- All ``x`` / ``y`` / ``w`` / ``h`` are floats, in **inches**.

Colour convention (matches pptxgenjs 4.x):
- 6-digit hex strings, **without** leading ``#``. e.g. ``"1E3A5F"``.
- See ``tests/contract/test_pptxgen_constraints.py`` for invariants.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any, Literal, Union


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

CommandKind = Literal[
    "new_slide",
    "add_text",
    "add_chart",
    "add_table",
    "add_shape",
    "add_image",
]

ChartType = Literal["BAR", "LINE", "PIE", "DOUGHNUT", "COMBO"]
ShapeKind = Literal["rect", "rounded_rect", "ellipse"]
TextAlign = Literal["left", "center", "right"]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

@dataclass
class NewSlide:
    """Begin a fresh slide. All subsequent shape commands target this slide
    until the next ``NewSlide``.

    ``background``: 6-digit hex without ``#``; ``None`` keeps default white.
    """

    background: str | None = None
    type: Literal["new_slide"] = "new_slide"


@dataclass
class AddText:
    """Render a single text box.

    ``font_name`` is optional — None means pptxgenjs default (Calibri).
    """

    x: float
    y: float
    w: float
    h: float
    text: str
    font_size: int = 12
    bold: bool = False
    color: str = "000000"
    font_name: str | None = None
    alignment: TextAlign = "left"
    type: Literal["add_text"] = "add_text"


@dataclass
class AddChart:
    """Render a native (editable) PowerPoint chart.

    For single-type charts (BAR / LINE / PIE / DOUGHNUT) ``data`` is
    the pptxgenjs ``addChart`` series shape:
    ``[{"name": str, "labels": list[str], "values": list[float]}, ...]``

    For ``chart_type="COMBO"`` (multi-type chart, e.g. BAR + LINE on
    twin axes) ``data`` is a list of per-type entries:
    ``[{"type": "BAR", "data": [...], "options": {...}}, ...]``
    The Node executor unpacks this into the multi-type ``addChart``
    call where the first argument is itself an array.

    ``options`` is the pptxgenjs chart options dict — must already
    conform to the SOP invariants (see test_pptxgen_constraints.py):
    no ``#`` in colours, no ``chartTitle`` key, no 8-digit hex.
    """

    x: float
    y: float
    w: float
    h: float
    chart_type: ChartType
    data: list[dict[str, Any]]
    options: dict[str, Any] = field(default_factory=dict)
    type: Literal["add_chart"] = "add_chart"


@dataclass
class AddTable:
    """Render a table.

    ``rows`` is row-major; each cell is ``{"text": str, ...optional formatting}``.
    Cell-level keys passed through to pptxgenjs: ``fill``, ``color``,
    ``bold``, ``fontSize``, ``align``.
    """

    x: float
    y: float
    w: float
    h: float
    rows: list[list[dict[str, Any]]]
    options: dict[str, Any] = field(default_factory=dict)
    type: Literal["add_table"] = "add_table"


@dataclass
class AddShape:
    """Render a filled shape (rectangle / rounded rectangle / ellipse).

    Used as background for KPI cards, callouts, section covers, etc.
    Text is layered on top via a separate ``AddText`` command.

    Phase 3.5 additions:
    - ``rect_radius``: fractional rounded-corner radius (0.0-1.0).
      Only meaningful for ``shape="rounded_rect"``; ignored otherwise.
      Maps to pptxgenjs ``rectRadius`` (their convention is 0-100, but
      we keep the 0-1 fraction in Python for theme-friendly arithmetic;
      the JS side multiplies by 100).
    - ``shadow``: enable an outer drop shadow with theme-driven default
      opacity. The Node executor renders this via pptxgenjs ``shadow``;
      python-pptx side currently no-ops (Sprint 3 visual polish accepts
      this as a known fallback gap).
    """

    x: float
    y: float
    w: float
    h: float
    shape: ShapeKind
    fill: str
    line_color: str | None = None
    rect_radius: float | None = None
    shadow: bool = False
    type: Literal["add_shape"] = "add_shape"


@dataclass
class AddImage:
    """Render an inline image from a base64 data URI.

    ``data_uri`` example: ``"data:image/png;base64,iVBORw0KG..."``.
    Used by the chart-image fallback path (matplotlib PNG → embed) when
    the native chart type isn't supported.
    """

    x: float
    y: float
    w: float
    h: float
    data_uri: str
    type: Literal["add_image"] = "add_image"


SlideCommand = Union[NewSlide, AddText, AddChart, AddTable, AddShape, AddImage]


_COMMAND_CLASS_BY_KIND: dict[str, type] = {
    "new_slide": NewSlide,
    "add_text": AddText,
    "add_chart": AddChart,
    "add_table": AddTable,
    "add_shape": AddShape,
    "add_image": AddImage,
}


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def serialize_commands(commands: list[SlideCommand]) -> str:
    """Encode a command list as compact JSON for stdin transfer to Node.

    Output is a JSON array of objects, each carrying a discriminator
    ``"type"`` field. ``ensure_ascii=False`` so Chinese text doesn't bloat
    the payload with ``\\uXXXX`` escapes.
    """
    payload = [asdict(cmd) for cmd in commands]
    return json.dumps(payload, ensure_ascii=False)


def deserialize_commands(text: str) -> list[SlideCommand]:
    """Inverse of ``serialize_commands`` — used in tests to round-trip
    and verify schema integrity.

    Raises ``ValueError`` on unknown command kinds.
    """
    raw = json.loads(text)
    if not isinstance(raw, list):
        raise ValueError("Top-level payload must be a JSON array")

    out: list[SlideCommand] = []
    for idx, item in enumerate(raw):
        if not isinstance(item, dict):
            raise ValueError(f"commands[{idx}] is not an object")
        kind = item.get("type")
        cls = _COMMAND_CLASS_BY_KIND.get(kind)
        if cls is None:
            raise ValueError(f"commands[{idx}] unknown kind: {kind!r}")
        # Strip the discriminator before constructing — it's a class-level
        # default literal, not a constructor arg overridable per-instance.
        payload = {k: v for k, v in item.items() if k != "type"}
        try:
            out.append(cls(**payload))
        except TypeError as e:
            raise ValueError(
                f"commands[{idx}] (kind={kind}) field mismatch: {e}"
            ) from e
    return out


# ---------------------------------------------------------------------------
# Validation helpers (used by tests + renderer self-checks)
# ---------------------------------------------------------------------------

_HEX6_CHARS = set("0123456789abcdefABCDEF")


def is_valid_hex6(value: str) -> bool:
    """6 hex digits, no leading '#'. PptxGenJS 4.x rejects ``#RRGGBB``
    and 8-digit RGBA — see test_pptxgen_constraints.py for context."""
    return (
        isinstance(value, str)
        and len(value) == 6
        and all(c in _HEX6_CHARS for c in value)
    )


def validate_command(cmd: SlideCommand) -> None:
    """Raise ``ValueError`` on any invariant violation.

    Non-fatal — renderer methods can call this in development for early
    error detection; production path skips it for performance.
    """
    if isinstance(cmd, NewSlide):
        if cmd.background is not None and not is_valid_hex6(cmd.background):
            raise ValueError(
                f"NewSlide.background must be 6-hex no '#', got {cmd.background!r}"
            )
    elif isinstance(cmd, AddText):
        if not is_valid_hex6(cmd.color):
            raise ValueError(f"AddText.color must be 6-hex, got {cmd.color!r}")
    elif isinstance(cmd, AddShape):
        if not is_valid_hex6(cmd.fill):
            raise ValueError(f"AddShape.fill must be 6-hex, got {cmd.fill!r}")
        if cmd.line_color is not None and not is_valid_hex6(cmd.line_color):
            raise ValueError(
                f"AddShape.line_color must be 6-hex or None, got {cmd.line_color!r}"
            )
