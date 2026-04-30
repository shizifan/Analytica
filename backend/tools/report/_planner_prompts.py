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
        {"kind": "table", "asset_id": str, "caption": str,
         "highlight_rules": [...规则数组,见下,可省略...]},   // asset_id 必须存在于"可用 assets"
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
- status     : table / chart 配 paragraph 解读;
               关键现状用 chart_table_pair 并排展示(图+表对照)
- analysis   : chart + paragraph 数据解读
- attribution: paragraph 概述 + 归因汇总表(见下)
- recommendation: comparison_grid 三栏(短期/中期/长期), 每列 2-3 条要点
- appendix   : 0-N paragraph(style=lead) 总结句

## attribution 归因汇总表格式

attribution 章节如有多个问题归因, 应优先合成结构化归因表
(让读者一眼对比). 输出形式:
{
  "kind": "table",
  "asset_id": "<新合成的归因表 asset, 见下>",
  "caption": "归因汇总"
}
归因表 asset 通过额外的 ``synthesised_assets`` 数组声明:

"synthesised_assets": [
  {
    "asset_id": "ATTR0001",
    "kind": "table",
    "df_records": [
      {"问题": "...", "数据依据": "...", "原因": "...",
       "影响": "...", "责任方": "..."},
      ...
    ],
    "columns_meta": [
      {"name": "问题"}, {"name": "数据依据"},
      {"name": "原因"}, {"name": "影响"}, {"name": "责任方"}
    ]
  }
]

引用 ATTR0001 时它必须出现在 synthesised_assets 中. 若上游素材
不足以归因, 退回 paragraph 方式描述, 不要编造.

## 视觉强调指引

- callout-warn  : 风险/预警/未达成/下降 N% 类信息
- callout-info  : 提示/建议关注/补充说明类信息
- 风险数据      : 段落使用 callout-warn 强调, 让读者第一眼捕获

## 表格高亮指引 (highlight_rules)

table block 可附带 ``highlight_rules`` 数组让渲染器对单元格染色。
每条规则形如:

  {"col": "<列名>", "predicate": "<可选>", "color": "<语义色>"}
  或
  {"row": <0-based 行号>, "color": "<语义色>"}    // 整行染色

- color 必须取自白名单:
  positive (利好/达成) | negative (风险/未达成) | neutral
  | accent (中性强调) | gold | silver | bronze (前 1/2/3 名)
- predicate 可选, 常用值: "max" | "min" | "negative" | "positive"
  | ">0" | "<0" | "rank<=3"; 渲染器对未知 predicate 容忍跳过.
- 当且仅当数据内有真正的对比意义时才上规则; 不要给所有数字加色.

示例: 归因表的"贡献度"列, max 染绿、negative 染红:
  "highlight_rules": [
    {"col": "contribution", "predicate": "max",      "color": "positive"},
    {"col": "contribution", "predicate": "negative", "color": "negative"}
  ]

## 图表选型指引

- 时间序列     : LINE 图;
- 类别比较     : 纵向 BAR;
- 排名 / TOP-N : 横向 BAR (yAxis.type="category"), 单系列时
                 渲染端自动添加数值标签;
- 占比         : PIE / DOUGHNUT(状态分类用 DOUGHNUT 视觉更专业);
- 二维相关     : COMBO (同一类别下指标 + 比率).

## 严格规则

1. 引用 asset_id 必须存在于"可用 assets"清单或 synthesised_assets 中,
   严禁编造
2. block kind 必须是上述 7 种之一. **不要输出 section_cover** —
   章节封面页由系统在每个非 appendix 章节自动注入, 你只需关注章节内容.
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
