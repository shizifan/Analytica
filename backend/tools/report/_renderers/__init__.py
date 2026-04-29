"""Concrete BlockRenderer implementations.

Each renderer holds its own state (Document / Presentation / string
buffer) and is constructed fresh per render. Step 3-6 fill these in;
until then every ``emit_*`` raises ``NotImplementedError``.
"""
from backend.tools.report._renderers.docx import DocxBlockRenderer
from backend.tools.report._renderers.html import HtmlBlockRenderer
from backend.tools.report._renderers.markdown import MarkdownBlockRenderer
from backend.tools.report._renderers.pptx import PptxBlockRenderer

__all__ = [
    "DocxBlockRenderer",
    "HtmlBlockRenderer",
    "MarkdownBlockRenderer",
    "PptxBlockRenderer",
]
