"""Step 0.1 — SlideCommand DSL schema tests.

Covers:
- All 6 command kinds construct cleanly with sane defaults
- ``serialize_commands`` produces JSON with discriminator ``type`` field
- ``deserialize_commands`` round-trips every kind
- Unknown command kind in JSON raises ValueError
- Color validators catch SOP-prohibited shapes (#-prefix, 8-digit hex)
"""
from __future__ import annotations

import json

import pytest

from backend.tools.report._pptxgen_commands import (
    AddChart,
    AddImage,
    AddShape,
    AddTable,
    AddText,
    NewSlide,
    deserialize_commands,
    is_valid_hex6,
    serialize_commands,
    validate_command,
)

pytestmark = pytest.mark.contract


# ---------------------------------------------------------------------------
# Construction defaults
# ---------------------------------------------------------------------------

def test_new_slide_defaults_to_white_background():
    s = NewSlide()
    assert s.background is None
    assert s.type == "new_slide"


def test_add_text_defaults_are_safe():
    t = AddText(x=0, y=0, w=1, h=1, text="hi")
    assert t.font_size == 12
    assert t.bold is False
    assert t.color == "000000"
    assert t.font_name is None
    assert t.alignment == "left"
    assert t.type == "add_text"


def test_add_chart_includes_required_fields():
    c = AddChart(
        x=0, y=0, w=1, h=1, chart_type="BAR",
        data=[{"name": "S1", "labels": ["A"], "values": [1]}],
    )
    assert c.chart_type == "BAR"
    assert c.options == {}
    assert c.type == "add_chart"


def test_add_shape_requires_fill():
    s = AddShape(x=0, y=0, w=1, h=1, shape="rounded_rect", fill="1E3A5F")
    assert s.line_color is None
    assert s.type == "add_shape"


# ---------------------------------------------------------------------------
# Serialise / deserialise round-trip
# ---------------------------------------------------------------------------

def _full_command_list() -> list:
    return [
        NewSlide(background="1E3A5F"),
        AddText(
            x=0.5, y=0.3, w=12, h=0.7, text="封面标题",
            font_size=44, bold=True, color="FFFFFF",
            font_name="Calibri", alignment="center",
        ),
        AddShape(
            x=1, y=1, w=2.5, h=1.2,
            shape="rounded_rect", fill="F0A500",
        ),
        AddChart(
            x=1, y=3, w=11, h=4,
            chart_type="BAR",
            data=[{"name": "吞吐量", "labels": ["大连", "营口"], "values": [4500.5, 3200.1]}],
            options={"chartColors": ["1E3A5F", "F0A500"], "showLegend": True},
        ),
        AddTable(
            x=0.5, y=2, w=12, h=4,
            rows=[
                [{"text": "港区", "bold": True, "fill": "1E3A5F", "color": "FFFFFF"}],
                [{"text": "大连"}],
            ],
            options={"colW": [3, 2, 2]},
        ),
        AddImage(
            x=1, y=1, w=8, h=4.5,
            data_uri="data:image/png;base64,iVBORw0KGgo=",
        ),
    ]


def test_serialize_produces_valid_json_array():
    cmds = _full_command_list()
    text = serialize_commands(cmds)
    decoded = json.loads(text)
    assert isinstance(decoded, list)
    assert len(decoded) == 6
    assert {item["type"] for item in decoded} == {
        "new_slide", "add_text", "add_shape",
        "add_chart", "add_table", "add_image",
    }


def test_serialize_keeps_chinese_unescaped():
    cmds = [AddText(x=0, y=0, w=1, h=1, text="港区吞吐量分析")]
    text = serialize_commands(cmds)
    assert "港区吞吐量分析" in text
    assert "\\u" not in text  # ensure_ascii=False


def test_round_trip_preserves_every_field():
    original = _full_command_list()
    rebuilt = deserialize_commands(serialize_commands(original))
    assert len(rebuilt) == len(original)
    for orig, back in zip(original, rebuilt):
        assert type(orig) is type(back)
        assert orig == back


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------

def test_deserialize_rejects_non_array_root():
    with pytest.raises(ValueError, match="Top-level payload"):
        deserialize_commands('{"foo": "bar"}')


def test_deserialize_rejects_unknown_kind():
    payload = json.dumps([{"type": "magic", "x": 0}])
    with pytest.raises(ValueError, match="unknown kind: 'magic'"):
        deserialize_commands(payload)


def test_deserialize_rejects_field_mismatch():
    # AddText requires `text`; missing it should raise via TypeError → ValueError
    payload = json.dumps([{"type": "add_text", "x": 0, "y": 0, "w": 1, "h": 1}])
    with pytest.raises(ValueError, match="field mismatch"):
        deserialize_commands(payload)


# ---------------------------------------------------------------------------
# Color validators
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("hex6", [
    "1E3A5F", "ffffff", "000000", "AbCdEf",
])
def test_is_valid_hex6_accepts_6_digit_hex(hex6):
    assert is_valid_hex6(hex6) is True


@pytest.mark.parametrize("bad", [
    "#1E3A5F",         # leading #
    "1E3A5F00",        # 8-digit RGBA
    "1E3A5",           # 5 digits
    "1E3A5G",          # non-hex char
    "",                # empty
    None,              # not a string
    123456,
])
def test_is_valid_hex6_rejects_invalid(bad):
    assert is_valid_hex6(bad) is False


def test_validate_command_catches_hash_prefix_in_text_color():
    cmd = AddText(x=0, y=0, w=1, h=1, text="x", color="#1E3A5F")
    with pytest.raises(ValueError, match="6-hex"):
        validate_command(cmd)


def test_validate_command_catches_8_digit_hex_in_shape_fill():
    cmd = AddShape(x=0, y=0, w=1, h=1, shape="rect", fill="1E3A5F00")
    with pytest.raises(ValueError, match="6-hex"):
        validate_command(cmd)


def test_validate_command_allows_valid_new_slide():
    validate_command(NewSlide(background="1E3A5F"))
    validate_command(NewSlide(background=None))  # no bg also valid


def test_validate_command_catches_invalid_new_slide_bg():
    with pytest.raises(ValueError, match="6-hex"):
        validate_command(NewSlide(background="#fff"))
