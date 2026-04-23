"""Shared theme constants for all report generation skills."""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Colors (hex strings for HTML/CSS, tuples for python-docx/pptx RGBColor)
# ---------------------------------------------------------------------------
PRIMARY = "#1E3A5F"
SECONDARY = "#2D5F8A"
ACCENT = "#F0A500"
POSITIVE = "#2E7D32"
NEGATIVE = "#C62828"
NEUTRAL = "#546E7A"
BG_LIGHT = "#F5F7FA"
WHITE = "#FFFFFF"
TEXT_DARK = "#333333"

RGB_PRIMARY = (0x1E, 0x3A, 0x5F)
RGB_SECONDARY = (0x2D, 0x5F, 0x8A)
RGB_ACCENT = (0xF0, 0xA5, 0x00)
RGB_POSITIVE = (0x2E, 0x7D, 0x32)
RGB_NEGATIVE = (0xC6, 0x28, 0x28)
RGB_NEUTRAL = (0x54, 0x6E, 0x7A)
RGB_BG_LIGHT = (0xF5, 0xF7, 0xFA)
RGB_WHITE = (0xFF, 0xFF, 0xFF)
RGB_TEXT_DARK = (0x33, 0x33, 0x33)

# ---------------------------------------------------------------------------
# Fonts
# ---------------------------------------------------------------------------
FONT_CN = "Microsoft YaHei"
FONT_NUM = "Calibri"

# ---------------------------------------------------------------------------
# Font sizes (raw integers in points; callers wrap with Pt() as needed)
# ---------------------------------------------------------------------------
SIZE_TITLE = 28
SIZE_H1 = 22
SIZE_H2 = 18
SIZE_H3 = 16
SIZE_BODY = 12
SIZE_SMALL = 10
SIZE_KPI_LARGE = 36
SIZE_KPI_LABEL = 11
SIZE_TABLE_HEADER = 11
SIZE_TABLE_BODY = 10

# ---------------------------------------------------------------------------
# Slide dimensions (inches) — 10 x 7.5 widescreen
# ---------------------------------------------------------------------------
SLIDE_WIDTH = 10
SLIDE_HEIGHT = 7.5
