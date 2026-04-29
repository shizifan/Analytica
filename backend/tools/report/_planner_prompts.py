"""LLM planner prompt templates — Step 8.

Centralised so the prompt can evolve without touching the planner
control flow. Each constant is the literal text fed to the LLM
(``OUTLINE_PLANNER_SYSTEM`` + ``build_planner_user_prompt``).
"""
from __future__ import annotations

import json
from typing import Any


OUTLINE_PLANNER_SYSTEM = """\
你是数据分析报告的总编辑。给定报告意图、章节定义、上游素材清单及可用 assets，
请规划每个章节内 block 的组合并合成必要的派生内容(执行摘要 KPI、归因表、建议三栏)。
严格按 JSON Schema 输出, 不要输出任何 JSON 之外的文字。
"""


_OUTPUT_SCHEMA_DOC = """\
## 输出 JSON Schema (严格)

{
  "kpi_summary": [
    {"label": str, "value": str, "sub": str, "trend": "positive" | "negative" | null}
  ],   // 0-4 项,顶部全局 KPI
  "sections": [
    {
      "name": str,           // 必须复用输入"章节定义"中给出的 name
      "role": str,           // 必须复用输入的 role
      "source_tasks": [str], // 该 section 的 block 涉及的 task_id 列表
      "blocks": [
        // 每个 block 必有 "kind" 字段, 其余字段按 kind 不同而不同
        {"kind": "kpi_row", "items": [...KPI...]},
        {"kind": "paragraph", "text": str, "style": "body"|"lead"|"callout-warn"|"callout-info"},
        {"kind": "table", "asset_id": str, "caption": str},        // asset_id 必须存在于"可用 assets"
        {"kind": "chart", "asset_id": str, "caption": str},
        {"kind": "chart_table_pair", "chart_asset_id": str, "table_asset_id": str, "layout": "h"|"v"},
        {"kind": "comparison_grid",
         "columns": [{"title": str, "items": [str]}]},             // 用于建议三栏等
        {"kind": "growth_indicators", "growth_rates": {col: {"yoy": float|null, "mom": float|null}}}
      ]
    }
  ]
}

## 角色 → 推荐编排

- summary    : 顶部 kpi_row + 1-2 paragraph(style=lead) 概述核心发现
- status     : table / chart 配 paragraph 解读
- analysis   : chart + paragraph 数据解读
- attribution: paragraph 概述 + (可选)对比 table 列出问题/原因/影响
- recommendation: comparison_grid 三栏(短期/中期/长期), 每列 2-3 条要点
- appendix   : 0-N paragraph(style=lead) 总结句

## 严格规则

1. 引用 asset_id 必须存在于"可用 assets"清单, 严禁编造
2. block kind 必须是上述 8 种之一(不要用 section_cover, 当前不渲染)
3. sections 顺序与输入"章节定义"完全一致, 数量也一致
4. 不要在 JSON 之外输出任何文字、注释、代码块标记
"""


def build_planner_user_prompt(
    intent: str,
    section_definitions: list[dict[str, str]],
    assets_summary: list[dict[str, Any]],
    raw_items_summary: list[dict[str, Any]],
) -> str:
    """Build the user message for the LLM planner.

    Args:
        intent: ``inp.params['intent']``
        section_definitions: ``[{"name": ..., "role": ...}]``
        assets_summary: ``[{"asset_id": ..., "kind": ..., "source_task": ...,
                            "preview": ...}]`` — 5-row preview for tables,
                          chart-type for charts.
        raw_items_summary: per-task brief (narrative / chart / stats / etc.)
    """
    return f"""\
【报告意图】
{intent or "(未指定)"}

【章节定义】
{json.dumps(section_definitions, ensure_ascii=False, indent=2)}

【上游素材清单(by task_id)】
{json.dumps(raw_items_summary, ensure_ascii=False, indent=2)}

【可用 assets(供 block 引用)】
{json.dumps(assets_summary, ensure_ascii=False, indent=2)}

{_OUTPUT_SCHEMA_DOC}
"""
