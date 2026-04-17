"""Generate sample reports (DOCX / PPTX / HTML) to disk for manual review.

Usage:
    cd /path/to/Analytica
    python -m tests.generate_sample_reports

Output:
    tests/output/港口年度运营分析报告.docx
    tests/output/港口年度运营分析报告.pptx
    tests/output/港口年度运营分析报告.html
"""
from __future__ import annotations

import asyncio
import pathlib
import sys

from backend.skills.base import SkillInput

# Reuse the rich mock data already defined in the test module
from tests.test_report_gen import _build_rich_context, REPORT_PARAMS

OUTPUT_DIR = pathlib.Path(__file__).parent / "output"


async def main() -> None:
    OUTPUT_DIR.mkdir(exist_ok=True)

    context = _build_rich_context()
    inp = SkillInput(params=REPORT_PARAMS)
    title = REPORT_PARAMS["report_metadata"]["title"]

    # ── DOCX ──────────────────────────────────────────────────────
    from backend.skills.report.docx_gen import DocxReportSkill

    docx_skill = DocxReportSkill()
    docx_skill.skill_id = "skill_report_docx"
    docx_result = await docx_skill.execute(inp, context)
    assert docx_result.status == "success", f"DOCX 生成失败: {docx_result.error_message}"

    docx_path = OUTPUT_DIR / f"{title}.docx"
    docx_path.write_bytes(docx_result.data)
    print(f"  DOCX  {docx_path}  ({docx_result.metadata['file_size_bytes']:,} bytes)")

    # ── PPTX ──────────────────────────────────────────────────────
    from backend.skills.report.pptx_gen import PptxReportSkill

    pptx_skill = PptxReportSkill()
    pptx_skill.skill_id = "skill_report_pptx"
    pptx_result = await pptx_skill.execute(inp, context)
    assert pptx_result.status == "success", f"PPTX 生成失败: {pptx_result.error_message}"

    pptx_path = OUTPUT_DIR / f"{title}.pptx"
    pptx_path.write_bytes(pptx_result.data)
    print(f"  PPTX  {pptx_path}  ({pptx_result.metadata['file_size_bytes']:,} bytes, "
          f"{pptx_result.metadata['slide_count']} slides)")

    # ── HTML ──────────────────────────────────────────────────────
    from backend.skills.report.html_gen import HtmlReportSkill

    html_skill = HtmlReportSkill()
    html_skill.skill_id = "skill_report_html"
    html_result = await html_skill.execute(inp, context)
    assert html_result.status == "success", f"HTML 生成失败: {html_result.error_message}"

    html_path = OUTPUT_DIR / f"{title}.html"
    html_path.write_text(html_result.data, encoding="utf-8")
    print(f"  HTML  {html_path}  ({len(html_result.data):,} chars, "
          f"{html_result.metadata['chart_count']} charts)")

    print(f"\n  所有报告已生成到 {OUTPUT_DIR.resolve()}")


if __name__ == "__main__":
    asyncio.run(main())
