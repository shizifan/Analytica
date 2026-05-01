# 报告生成架构重构实施方案 — Outline 中间层

**目标读者**：Claude Code 执行实例（无本会话上下文）
**作者**：架构方案讨论沉淀
**状态**：✅ 已交付（2026-04-29），✅ 灰度收尾完成（2026-05-01）

---

## 交付状态

| Step | 内容 | 完成日期 | 状态 |
|---|---|---|---|
| 0 | 4 端 baseline 测试 + golden fixtures | 2026-04-29 | ✅ |
| 1 | `_outline.py` 数据模型（8 block + 3 asset + JSON 序列化）| 2026-04-29 | ✅ |
| 2 | `_block_renderer.py` 协议 + dispatch + 4 空骨架 | 2026-04-29 | ✅ |
| 3 | Markdown renderer + `_outline_legacy.py` 转换器 | 2026-04-29 | ✅ |
| 4 | DOCX 双路径迁移（agent + deterministic）| 2026-04-29 | ✅ |
| 5 | PPTX section-buffer 模式 + PptxGenJS 约束测试 | 2026-04-29 | ✅ |
| 6 | HTML lazy-close 模式 + outline-driven tools | 2026-04-29 | ✅ |
| 7 | 死代码清理（`_pptx_tools.py` 删除 + `serialize_report_content` 删除） | 2026-04-29 | ✅ |
| 8 | LLM planner（合并 KPI + 章节编排 + 合成块）| 2026-04-29 | ✅ |
| 9 | 灰度文档 + 收尾 | 2026-04-29 | ✅ |
| 11 | **Sprint 2 真正闭环** — PptxGenJS outline 化（参见 [visual_polish_plan.md 阶段 0](./visual_polish_plan.md#4-阶段-0--sprint-2-收尾pptxgenjs-outline-化)）| 2026-04-29 | ✅ |
| 12 | **灰度收尾** — 翻 LLM 路径为唯一主路径，删除规则 fallback、`_outline_legacy.py`、`_kpi_extractor.py`、`REPORT_OUTLINE_PLANNER_ENABLED` 开关；baseline 改用 stub LLM | 2026-05-01 | ✅ |

**Step 11 (Sprint 2 闭环) 摘要**：原 Step 5 PPT 仅完成 50% outline 化（python-pptx fallback 路径），PptxGenJS 桥接保留旧 ReportContent 管道作为 scope-control 妥协。Step 11 新增 SlideCommand DSL（`_pptxgen_commands.py`）+ PptxGenJSBlockRenderer（`_renderers/pptxgen.py`）+ 重写的 Node 长期常驻脚本（`pptxgen_executor.js`），消除 PPT 双路径。**4 端真正 100% outline 化**。

**Step 12（灰度收尾）摘要**：经实际 LLM 调用验证后，删除规则 fallback。`_outline_legacy.py` 与 `_kpi_extractor.py` 整体删除——前者的 `_convert_item` / `_infer_role` 内联进 `_outline_planner.py`，`KPIItem` dataclass 搬到 `_outline.py` 作为数据模型一部分。`REPORT_OUTLINE_PLANNER_ENABLED` 开关与 `plan_outline` 中的 try/except fallback 块一并删除，LLM 失败现在直接抛 `_LLMPlannerFailure`（无兜底）。Baseline 测试改为 stub `invoke_llm`：`tests/contract/_report_baseline.py::stub_planner_llm` 返回固定 JSON，4 端 golden 文件随之 regen。`PlannerMode` Literal 收紧为 `"llm"`。

**测试覆盖**（Step 12 后）：

- 全套 tests/contract + tests/integration **384 PASSED**（baseline 4 + outline_model 18 + planner_llm 14 + planner_visual 13 + 既有约 335）
- 1 skipped / 1 xfailed 与 outline 无关（throughput_analyst 模板预存在状态）
- Step 12 后零回归

**Feature flag 默认值**（`backend/config.py`）：

| Flag | 默认 | 用途 |
|---|---|---|
| `REPORT_AGENT_ENABLED` | `True` | DOCX/HTML 是否走 LLM agent 编排 |
| `REPORT_DEBUG_DUMP_OUTLINE` | `False` | 把 outline JSON dump 到 `data/reports/outline_<task_id>.json` 调试用 |

`REPORT_OUTLINE_PLANNER_ENABLED` 在 Step 12 已删除——LLM 路径是唯一路径，无开关切换。

---

> ⚠️ **Step 12 后注**：以下 Mission / Steps 文档保留作为重构史，但 Step 8 描述的"LLM + 规则 fallback 双路径"已在 Step 12 简化为"仅 LLM 路径"。`_outline_legacy.py` / `_kpi_extractor.py` / `REPORT_OUTLINE_PLANNER_ENABLED` 在代码库中已不存在。下文中提及它们的位置仅供历史参照，不要按其结构去找当前代码。

## 0. Mission

把当前 `task → item → 直接渲染` 的扁平管道重构为 `task → ReportOutline → BlockRenderer × N端` 的策展式管道，解决以下深层问题：

1. **数据模型平面化** — `SectionContent.items` 是无序无关系扁平列表，章节内做不了「这张表配那张图配一段文字」的二维编排
2. **渲染逻辑硬编码** — DOCX/PPTX/HTML/MD 四端各自写 `isinstance` switch，新增内容类型要改四处
3. **章节定义只有 name** — 没有 role 语义（"现状"/"归因"/"建议"），LLM 无法基于意图合成内容
4. **合成内容无入口** — 「执行摘要 3 大发现」「归因表」「建议三栏」等 cross-section 派生内容当前只能塞进 `summary_items` 字符串列表
5. **四端不一致** — 加新能力（callout、grid、嵌图）要在四个 builder 各实现一次

**核心交付**：

- `_outline.py` 数据模型 + `_block_renderer.py` 协议 + 4 个 Renderer 实现
- `_outline_planner.py`（LLM 主路径 + 规则 fallback），合并当前 KPI 抽取
- 4 端（DOCX/PPTX/HTML/MD）切到 outline 管道，**输出文件与重构前等价**（baseline 测试守卫）
- Skill 模式（LLM agent loop）同步迁移到 outline 抽象

---

## 1. Non-goals（本次不做）

- ❌ 视觉效果改造（嵌入图表、深色分节封面页、callout 强调框、PPT 环形图等）—— 留到下一个 Sprint，新架构上加方法即可
- ❌ 主题切换 / 多模板 —— `_theme.py` 不动
- ❌ `summary_gen.py` —— 独立工具，不在 ReportContent 管道
- ❌ `_kpi_extractor.py` 内部实现 —— 接口保留，仅调用时机改变（合并进 planner）
- ❌ 视觉回归（pixel diff）—— 用结构等价测试即可

---

## 2. 执行原则（Guard Rails — 不可违反）

1. **Baseline 先行**：Step 0 必须先建立 4 端输出基线测试，否则后续"等价迁移"无验证手段
2. **每步可回滚**：每个 Step 独立可回滚，feature flag 默认关闭直到 Step 9
3. **Skill 模式必须同步迁移**：当前 Skill mode (LLM agent) 是默认主路径（`docx_gen.py:91` 检查 `REPORT_AGENT_ENABLED`），不能只迁 deterministic fallback
4. **现有元数据保留**：`degradations`、`endpoint_name`、task_order 迭代顺序，新模型必须继承
5. **从最简单的端起步**：Markdown 渲染器先行（纯字符串），暴露协议设计缺陷成本最低
6. **不引入新视觉效果**：Step 0-8 输出文件结构性等价，不允许借机加新元素
7. **每步必须跑 baseline 测试通过**才进入下一步

---

## 3. 当前架构快照（Claude Code 必读）

### 3.1 关键文件清单

| 文件 | 行号关键点 | 角色 |
|---|---|---|
| `backend/tools/report/_content_collector.py` | `:84-99` 数据模型；`:390` `collect_and_associate` 入口 | 当前数据采集（要替换） |
| `backend/tools/report/_kpi_extractor.py` | `:79` `extract_kpis_llm` 入口 | LLM KPI 抽取（要合并进 planner） |
| `backend/tools/report/docx_gen.py` | `:32` deterministic builder；`:81` skill mode；`:91` flag | DOCX 入口 |
| `backend/tools/report/pptx_gen.py` | `:144-230` execute | PPTX 入口 |
| `backend/tools/report/html_gen.py` | `:27` HTML_TEMPLATE 字符串模板 | HTML 入口（特殊：字符串拼接） |
| `backend/tools/report/markdown_gen.py` | `:25` MD_TEMPLATE | MD 入口（最简单） |
| `backend/tools/report/_docx_elements.py` | 全文 | DOCX 元素低层函数（不动，仅包装） |
| `backend/tools/report/_pptx_slides.py` | 全文 | PPTX 幻灯片低层函数（不动，仅包装） |
| `backend/tools/report/_pptxgen_builder.py` | 全文 | PptxGenJS Node.js 桥接（不动，仅包装） |
| `backend/tools/report/_html_tools.py` | — | HTML agent 工具集 |
| `backend/tools/report/_docx_tools.py` | `:30` `DOCX_SYSTEM_PROMPT`；`:55` `make_docx_tools` | DOCX agent 工具（要重写为 Block 工具） |
| `backend/tools/report/_pptx_tools.py` | — | PPTX agent 工具（要重写） |
| `backend/tools/report/_agent_loop.py` | `:30` `FINALIZE_SENTINEL`；`:77` `serialize_report_content`；`:119` `run_report_agent` | 共享 agent loop（保留 + 新增 outline 序列化） |
| `backend/tools/report/_theme.py` | — | 颜色/字体配置（不动） |
| `backend/tools/report/summary_gen.py` | — | **不动** — 独立工具 |

### 3.2 当前数据流

```
[执行链 ToolOutput] → collect_and_associate()  → ReportContent {sections[items]}
                                                        │
                            ┌───────────────────────────┼─────────────────────────────┐
                            ▼                           ▼                             ▼
                    extract_kpis_llm()         _build_*_deterministic()      run_report_agent()
                    (独立 LLM call)            (按 isinstance switch)        (LLM 编排 + 工具调用)
                                                        │                             │
                                                        ▼                             ▼
                                                 docx/pptx/html/md           docx/pptx/html/md
```

### 3.3 已知约束（来自现有代码注释和 Batch 4 改进）

- 任务迭代顺序：用 `task_order`，不是 `sorted(dict.keys())`（解决 T001→T010→T011→T002 错乱问题）
- 失败 task：`status == 'failed'` 或 `'skipped'` 必须跳过
- 内容失配：未匹配 item 丢弃 + log warning，不要塞进"最空章节"
- ChartDataItem/DataFrameItem 带 `endpoint_name` 用于 label_zh 解析
- PptxGenJS 桥接已踩过的坑（来自 Claude SOP）：颜色 6 位 hex 不带 `#`、`title` 不是 `chartTitle`、shadow 用 `opacity` 字段、option 对象禁止复用（库会原地修改）

### 3.4 Skill mode（必须同步迁移的部分）

`_agent_loop.run_report_agent` 是四端共享的 LLM agent loop：
- 入参：`llm`、`tools`、`system_prompt`、`user_message`
- LLM 通过 `tool_calls` 调用工具，调用 `finalize_*` 后返回 `FINALIZE_SENTINEL` 结束
- 当前 user_message 由 `serialize_report_content(ReportContent)` 生成
- 当前 LLM 通过 `(section_index, item_index)` 寻址内容（`_docx_tools.py:58 _lookup`）

新管道下：
- user_message 改为 `serialize_outline(ReportOutline)`
- LLM 通过 `block_id` 寻址，工具按 Block kind 暴露：`add_kpi_row(block_id)` / `add_chart(block_id)` / `add_table(block_id)` / 等
- agent 职责从「编排+渲染」收窄为「按 outline 渲染」

---

## 4. 目标架构

### 4.1 三层流水线

```
Stage 1: Collection      _content_collector.collect_raw()
   │ 输入: ToolInput.params + execution context
   │ 输出: RawCollection {raw_items: [...], assets: {...}, metadata, task_order}
   │ 不再做章节归属，只做"取数 + 类型识别 + endpoint 元数据保留"
   ▼
Stage 2: Planning        _outline_planner.plan_outline()
   │ 输入: RawCollection + section_definitions(含 role) + intent
   │ 输出: ReportOutline
   │
   │ 主路径 (LLM): 一次 LLM call 同时产出 kpi_summary + sections.blocks + 合成块
   │ Fallback (Rule): 按 section.role 走规则模板 (与当前 deterministic 等价)
   ▼
Stage 3: Rendering       render_outline(outline, renderer)
   │ 4 个 BlockRenderer 实现：Docx/Pptx/Html/Markdown
   │ 每个 renderer 持有自己的内部状态(doc/prs/buffer)，实现统一协议
   │ Skill mode：agent 工具集映射到 Block kind，LLM "执行渲染" 而非 "编排"
```

### 4.2 数据模型（精确 schema 在第 7 节）

```
ReportOutline
  ├ schema_version: "1.0"
  ├ metadata: {title, author, date, intent}
  ├ kpi_summary: [KPIItem]                # 顶部全局 KPI
  ├ sections: [OutlineSection]
  ├ assets: {asset_id → ChartAsset | TableAsset | ...}
  ├ degradations: [{...}]                  # 沿用现有语义
  └ planner_mode: "llm" | "rule_fallback"

OutlineSection
  ├ name: str
  ├ role: "summary" | "status" | "analysis" | "attribution" | "recommendation" | "appendix"
  ├ blocks: [Block]
  └ source_tasks: [task_id]                # 溯源

Block (sealed union, 用 kind 字段区分)
  ├ kpi_row             {block_id, items: [KPIItem]}
  ├ paragraph           {block_id, text, style: "body"|"lead"|"callout-warn"|"callout-info"}
  ├ table               {block_id, asset_id, caption?, highlight_rules?}
  ├ chart               {block_id, asset_id, caption?}
  ├ chart_table_pair    {block_id, chart_asset_id, table_asset_id, layout: "h"|"v"}
  ├ comparison_grid     {block_id, columns: [{title, items: [str]}]}   # 三栏建议等
  ├ growth_indicators   {block_id, growth_rates: {...}}                 # 沿用 GrowthItem
  └ section_cover       {block_id, index, title, subtitle?}             # 留接口，本次不实现渲染

ChartAsset:  {asset_id, kind: "chart", source_task, endpoint?, option: {...}}
TableAsset:  {asset_id, kind: "table", source_task, endpoint?, df_records: [{...}], columns_meta: [...]}
StatsAsset:  {asset_id, kind: "stats", source_task, summary_stats: {...}}  # 当前 StatsTableItem
```

---

## 5. 实施 Step 详解

### Sprint 1：Baseline + 数据模型 + Markdown 试点（4 天）

#### Step 0 — 建立 4 端输出基线测试 [1d]

**目的**：所有后续等价迁移都靠这套基线守卫，没有它一切重构都是盲飞。

**新增文件**：
- `tests/contract/test_report_outputs_baseline.py`
- `tests/fixtures/report_baseline/` 目录（落盘 baseline 输出）
- `tests/fixtures/report_baseline/inputs/` 目录（fixture 输入数据）

**实施动作**：
1. 准备 1-2 套典型 fixture：
   - 「正常路径」: 4 章节 / 含 narrative / stats / growth / chart / dataframe / summary 各类 item，覆盖所有当前 isinstance 分支
   - 「降级路径」: 含失败 task、缺失数据，触发 `degradations` 字段
   - 数据可从 `tests/fixtures/` 现有 fixture 抄改，或调真实 execution context dump
2. 编写 fixture 加载工具：构造 `ToolInput.params + context` 直接调用四端 `execute()`
3. 第一次跑：把当前主分支输出落盘到 `tests/fixtures/report_baseline/golden/`：
   - `report_normal.docx` / `.pptx` / `.html` / `.md`
   - `report_degraded.docx` / 等
4. 编写比较器：
   - **DOCX**：解压 OOXML（zip）→ 提取 `word/document.xml` 中段落文本、表格结构、heading 层级 → 渲染为标准化文本树 → diff
   - **PPTX**：同样解压，提取每页 shape 文本 + 表格 + 占位符 → 文本树 → diff
   - **HTML**：BeautifulSoup 解析 → 标准化（去空格、属性排序）→ diff
   - **Markdown**：直接字符串规范化（去尾空格、统一换行）→ diff
   - 不比较 docProps/core.xml 等含日期的元数据
5. 测试断言："新输出的结构化文本树 == golden"

**验收**：
- 在主分支跑 `pytest tests/contract/test_report_outputs_baseline.py` 全绿
- 故意在 `_docx_elements.build_narrative` 加一个空格 → 测试必须失败（验证测试有效性）

**完成定义**：基线测试 + 比较器 + golden fixture 三件齐全，可重复运行。

---

#### Step 1 — 引入 `_outline.py` 数据模型 [1d]

**新增文件**：
- `backend/tools/report/_outline.py`

**实施动作**：

1. 实现第 4.2 节的 dataclass，使用 Python 3.10+ 的 `Literal` / `match` / `Union`：

```python
from dataclasses import dataclass, field
from typing import Literal, Any
import pandas as pd

BlockKind = Literal[
    "kpi_row", "paragraph", "table", "chart",
    "chart_table_pair", "comparison_grid",
    "growth_indicators", "section_cover",
]

SectionRole = Literal[
    "summary", "status", "analysis",
    "attribution", "recommendation", "appendix",
]

ParagraphStyle = Literal["body", "lead", "callout-warn", "callout-info"]

@dataclass
class KpiRowBlock:
    block_id: str
    kind: Literal["kpi_row"] = "kpi_row"
    items: list[KPIItem] = field(default_factory=list)

# ... 其余 Block dataclass

Block = Union[KpiRowBlock, ParagraphBlock, TableBlock, ...]

@dataclass
class ChartAsset:
    asset_id: str
    source_task: str
    option: dict[str, Any]
    endpoint: str | None = None
    kind: Literal["chart"] = "chart"

# ... TableAsset / StatsAsset

@dataclass
class OutlineSection:
    name: str
    role: SectionRole
    blocks: list[Block] = field(default_factory=list)
    source_tasks: list[str] = field(default_factory=list)

@dataclass
class ReportOutline:
    schema_version: str = "1.0"
    metadata: dict[str, Any] = field(default_factory=dict)
    kpi_summary: list[KPIItem] = field(default_factory=list)
    sections: list[OutlineSection] = field(default_factory=list)
    assets: dict[str, Any] = field(default_factory=dict)
    degradations: list[dict[str, Any]] = field(default_factory=list)
    planner_mode: Literal["llm", "rule_fallback"] = "rule_fallback"

    def to_json(self) -> dict: ...      # for LLM planner output / debug dump
    @classmethod
    def from_json(cls, data: dict) -> "ReportOutline": ...
```

2. 提供 helper：`new_block_id() -> str`（纯递增 `B0001`-`B9999`，便于 LLM 引用）
3. 提供 helper：`new_asset_id(kind: str) -> str`（`C0001` chart / `T0001` table / `S0001` stats）
4. 写单测 `tests/contract/test_outline_model.py`：构造 outline → to_json → from_json → 等价

**验收**：单测全绿；mypy / pyright 通过。

---

#### Step 2 — `_block_renderer.py` 协议 + 4 个空 Renderer 骨架 [1d]

**新增文件**：
- `backend/tools/report/_block_renderer.py`
- `backend/tools/report/_renderers/__init__.py`
- `backend/tools/report/_renderers/markdown.py`
- `backend/tools/report/_renderers/docx.py`
- `backend/tools/report/_renderers/pptx.py`
- `backend/tools/report/_renderers/html.py`

**实施动作**：

1. `_block_renderer.py` 定义协议：

```python
from typing import Protocol, runtime_checkable
from backend.tools.report._outline import (
    ReportOutline, OutlineSection, Block,
    KpiRowBlock, ParagraphBlock, TableBlock, ChartBlock,
    ChartTablePairBlock, ComparisonGridBlock,
    GrowthIndicatorsBlock, SectionCoverBlock,
)

@runtime_checkable
class BlockRenderer(Protocol):
    """Each backend implements its own state (doc/prs/buffer)."""

    def begin_document(self, outline: ReportOutline) -> None: ...
    def end_document(self) -> bytes | str: ...

    def begin_section(self, section: OutlineSection, index: int) -> None: ...
    def end_section(self, section: OutlineSection, index: int) -> None: ...

    def emit_kpi_row(self, block: KpiRowBlock) -> None: ...
    def emit_paragraph(self, block: ParagraphBlock) -> None: ...
    def emit_table(self, block: TableBlock, asset) -> None: ...
    def emit_chart(self, block: ChartBlock, asset) -> None: ...
    def emit_chart_table_pair(
        self, block: ChartTablePairBlock,
        chart_asset, table_asset,
    ) -> None: ...
    def emit_comparison_grid(self, block: ComparisonGridBlock) -> None: ...
    def emit_growth_indicators(self, block: GrowthIndicatorsBlock) -> None: ...
    def emit_section_cover(self, block: SectionCoverBlock) -> None: ...


def render_outline(outline: ReportOutline, renderer: BlockRenderer) -> bytes | str:
    renderer.begin_document(outline)
    for idx, section in enumerate(outline.sections):
        renderer.begin_section(section, idx)
        for block in section.blocks:
            _dispatch(block, outline, renderer)
        renderer.end_section(section, idx)
    return renderer.end_document()


def _dispatch(block: Block, outline: ReportOutline, renderer: BlockRenderer) -> None:
    match block:
        case KpiRowBlock():            renderer.emit_kpi_row(block)
        case ParagraphBlock():         renderer.emit_paragraph(block)
        case TableBlock():             renderer.emit_table(block, outline.assets[block.asset_id])
        case ChartBlock():             renderer.emit_chart(block, outline.assets[block.asset_id])
        case ChartTablePairBlock():    renderer.emit_chart_table_pair(
                                            block,
                                            outline.assets[block.chart_asset_id],
                                            outline.assets[block.table_asset_id])
        case ComparisonGridBlock():    renderer.emit_comparison_grid(block)
        case GrowthIndicatorsBlock():  renderer.emit_growth_indicators(block)
        case SectionCoverBlock():      renderer.emit_section_cover(block)
        case _: raise ValueError(f"Unknown block kind: {type(block).__name__}")
```

2. 4 个 renderer 文件先写空骨架：每个 emit_* 方法 `raise NotImplementedError`，仅保留构造函数。
3. 单测 `tests/contract/test_block_renderer_protocol.py`：构造一个 mock renderer 验证 dispatch 全覆盖。

**验收**：协议定义齐全；空 renderer 可实例化但调用方法抛 NotImplementedError。

---

#### Step 3 — Markdown Renderer + collect_to_outline_legacy [1d]

**为什么先 Markdown**：纯字符串拼接，最快验证协议设计。如有缺陷立即调整 Step 2 协议，成本最低。

**修改文件**：
- `backend/tools/report/_renderers/markdown.py`（实现）
- `backend/tools/report/_outline_legacy.py`（**新增**，转换器）
- `backend/tools/report/markdown_gen.py`（切换管道）

**实施动作**：

1. 新增 `_outline_legacy.py`：
```python
def collect_and_build_outline(params, context, task_order=None) -> ReportOutline:
    """Step 3-6 期间用：调用旧 collect_and_associate，再把
    ReportContent 1:1 转成 ReportOutline。Step 7 后会被
    _outline_planner.plan_outline 替代。"""
```
   - 把每个 `NarrativeItem` 转为 `ParagraphBlock(style="body")`
   - `StatsTableItem` 转为 `TableBlock` + 注册一个 `StatsAsset`
   - `GrowthItem` 转为 `GrowthIndicatorsBlock`
   - `ChartDataItem` 转为 `ChartBlock` + 注册 `ChartAsset`（保留 endpoint）
   - `DataFrameItem` 转为 `TableBlock` + 注册 `TableAsset`
   - `SummaryTextItem` 转为附加 section role="appendix" 下的 `ParagraphBlock(style="lead")`
   - `kpi_cards` 直接搬到 `outline.kpi_summary`
   - section 的 `role` 用启发式推断（章节名含"摘要" → summary；含"建议" → recommendation；其它 → status）

2. 实现 `MarkdownBlockRenderer`：
   - 内部维护 `self._buf: list[str]` 和当前 section heading level
   - 各 emit_* 方法对应当前 `markdown_gen.py` 的渲染逻辑（参考 `MD_TEMPLATE`）
   - `end_document()` 拼接成完整 markdown 字符串

3. 改 `markdown_gen.py`：
```python
async def execute(self, inp, context):
    outline = await collect_and_build_outline(inp.params, context, task_order=...)
    outline.kpi_summary = await extract_kpis_llm(...)  # 暂保留此调用
    renderer = MarkdownBlockRenderer()
    output = render_outline(outline, renderer)
    return ToolOutput(...)
```

4. **跑 Step 0 baseline 测试**：MD 输出必须 byte-for-byte 等价（或字符串规范化后等价）。
   - 若不等价，调整 renderer 实现而非 baseline。
   - 若调整后仍不等价，说明协议设计有遗漏，回 Step 2 补 emit_* 方法。

**验收**：`pytest tests/contract/test_report_outputs_baseline.py::test_markdown` 全绿。

**风险**：可能发现协议缺方法（如 footnote、code block）—— 这是 Markdown 特有，加到协议但其他端默认 no-op。

---

### Sprint 2：DOCX/PPTX/HTML 迁移（5 天）

#### Step 4 — DOCX Renderer（Skill mode + Deterministic 双路径）[2d]

**修改文件**：
- `backend/tools/report/_renderers/docx.py`（实现）
- `backend/tools/report/_docx_tools.py`（重写工具集，按 Block kind）
- `backend/tools/report/_agent_loop.py`（新增 `serialize_outline`）
- `backend/tools/report/docx_gen.py`（切换管道）

**实施动作**：

1. 实现 `DocxBlockRenderer(BlockRenderer)`：
   - 构造函数接 `Document` 实例（或内部新建 + 调用 `E.build_styles` / `E.build_page_header_footer`）
   - 各 `emit_*` 方法包装 `_docx_elements` 现有函数：
     - `emit_paragraph(block)` → `E.build_narrative(doc, block.text)` 或 `E.build_callout(...)`（callout 暂用 narrative + 斜体替代，效果留 Sprint 3）
     - `emit_table(block, asset)` → 区分 `TableAsset` 走 `E.build_dataframe_table`，`StatsAsset` 走 `E.build_stats_table`
     - `emit_chart(block, asset)` → 当前 `E.build_chart_data_table`（无图嵌入，视觉留 Sprint 3）
     - `emit_kpi_row(block)` → `E.build_kpi_row`
     - `emit_growth_indicators(block)` → `E.build_growth_indicators`
     - `emit_chart_table_pair` → 临时实现：连续调用 chart + table，无并排（视觉留 Sprint 3）
     - `emit_comparison_grid(block)` → 临时实现：N 列表格
     - `emit_section_cover(block)` → 临时实现：`E.build_section_heading` + PageBreak
   - `begin_section` → `E.build_section_heading`；`end_section` no-op
   - `end_document` 返回 docx bytes

2. **重写** `_docx_tools.py`：
```python
DOCX_OUTLINE_SYSTEM_PROMPT = """\
你是一位 Word 文档排版执行者。用户已将文档大纲(outline)规划完毕，
你的任务是按 outline 的 sections 顺序，逐个调用对应的 emit 工具来渲染每个 block。

## 工作流程
1. 调用 begin_document
2. 对每个 section: 调用 begin_section, 然后按顺序对每个 block 调用对应 emit 工具，最后 end_section
3. 完成后调用 finalize_document

## 工具与 Block 对应
- emit_kpi_row(block_id): 渲染 KPI 行
- emit_paragraph(block_id): 渲染段落
- emit_table(block_id): 渲染表格
- emit_chart(block_id): 渲染图表（当前为数据表）
- emit_chart_table_pair(block_id): 图+表组合
- emit_comparison_grid(block_id): 多栏对比
- emit_growth_indicators(block_id): 增长率指标
- emit_section_cover(block_id): 章节封面
- begin_section(section_index), end_section(section_index)

## 重要
- block_id 严格按 user message 中提供的 ID 调用，不要编造
- 不要跳过 block，不要重复
- 完成后必须调用 finalize_document
"""

def make_docx_outline_tools(renderer: DocxBlockRenderer, outline: ReportOutline) -> list:
    """工具按 block_id 寻址，工具内部调 renderer.emit_*"""
```
   - 工具实现：通过 `block_id` 在 outline 里查到 block + asset，调对应 renderer 方法
   - 错误处理：block_id 不存在 → 返回错误字符串给 LLM
   - finalize 工具返回 `FINALIZE_SENTINEL`

3. 在 `_agent_loop.py` 新增：
```python
def serialize_outline(outline: ReportOutline) -> str:
    """Outline → 喂给 LLM 的紧凑文本表示。
    每个 block 一行: [block_id] kind: 摘要描述
    section 用 ### 分隔"""
```
   - 旧的 `serialize_report_content` 保留（迁移期可能并存）

4. 改 `docx_gen.py`：
```python
async def execute(self, inp, context):
    outline = await collect_and_build_outline(inp.params, context, task_order=...)
    outline.kpi_summary = await extract_kpis_llm(...)

    renderer = DocxBlockRenderer()  # 内部初始化 doc + styles + header

    # Skill mode
    mode = "deterministic_fallback"
    try:
        if settings.REPORT_AGENT_ENABLED:
            tools = make_docx_outline_tools(renderer, outline)
            user_msg = serialize_outline(outline)
            success = await run_report_agent(llm, tools, DOCX_OUTLINE_SYSTEM_PROMPT, user_msg)
            if success:
                mode = "llm_agent"
            else:
                renderer = DocxBlockRenderer()  # reset
                render_outline(outline, renderer)
                mode = "deterministic_fallback"
    except Exception:
        renderer = DocxBlockRenderer()
        render_outline(outline, renderer)
        mode = "deterministic_fallback_error"

    docx_bytes = renderer.end_document()
    return ToolOutput(..., metadata={"mode": mode, ...})
```

5. **跑 Step 0 baseline**（DOCX 部分）。
6. 旧的 `_build_docx_deterministic` 保留但加 `# DEPRECATED — to remove in Step 8`。

**验收**：
- DOCX baseline 测试全绿
- Skill mode 路径手动跑通（用 `REPORT_AGENT_ENABLED=true` 跑一次端到端）
- Deterministic fallback 路径自动测试（baseline 测试默认走 fallback）

**风险**：
- agent loop 的 LLM 工具数量从 ~7 个变为 ~10 个（含 begin/end_section），prompt token 增加。要控制：每个工具描述限制在 1 行
- 旧 agent 通过 `(section_idx, item_idx)` 寻址，新 agent 通过 `block_id`。系统 prompt 必须明确这一点

---

#### Step 5 — PPTX Renderer（含 PptxGenJS 桥接）[1.5d]

**修改文件**：
- `backend/tools/report/_renderers/pptx.py`（实现）
- `backend/tools/report/_pptx_tools.py`（重写）
- `backend/tools/report/pptx_gen.py`（切换管道）

**实施动作**：

1. `PptxBlockRenderer` 内部维护 `Presentation` 实例 + 当前 slide 引用 + PptxGenJS 桥接条件
2. 包装 `_pptx_slides.py` 函数，加 PptxGenJS 路径：
   - `emit_chart` 优先调 `_pptxgen_builder` 生成原生图表，失败降级 `_pptx_slides` 表格
   - `emit_chart_table_pair` 在同一 slide 上左右布局（已有 helper 复用）
3. **PptxGenJS 隐性约束固化进单测** `tests/contract/test_pptxgen_constraints.py`：
   - 颜色字段必须 6 位 hex 且不带 `#`
   - chart options 不得含 `chartTitle` 字段
   - shadow 配置不得含 8 位 hex
   - 同一 PptxGenJS 进程内不复用 option 对象（factory 模式）
4. 重写 `_pptx_tools.py`：与 Step 4 同构（block_id 寻址 + emit 工具）
5. 切换 `pptx_gen.py`
6. **跑 Step 0 baseline**（PPTX 部分）

**验收**：PPTX baseline + PptxGenJS 约束测试全绿。

---

#### Step 6 — HTML Renderer [1d]

**特殊性**：当前 HTML 端是字符串模板拼接（`HTML_TEMPLATE` + 内联 `{content}`），与 docx/pptx 对象 API 风格不同。

**修改文件**：
- `backend/tools/report/_renderers/html.py`（实现）
- `backend/tools/report/_html_tools.py`（重写）
- `backend/tools/report/html_gen.py`（切换管道）

**实施动作**：

1. `HtmlBlockRenderer` 内部维护：
   - `self._sections_html: list[str]`（每段 `<div class="section">...</div>`）
   - `self._charts_init_js: list[str]`（ECharts 初始化脚本）
   - `end_document()` 套用 `HTML_TEMPLATE` 拼最终 HTML
2. 各 emit_* 方法生成对应 HTML 片段，沿用现有 CSS 类名（`.kpi-row` / `.kpi-card` / `table.stats` 等）
3. ECharts 图表通过 `<div id="chart_{block_id}">` + 末尾 `<script>` 初始化（参考现有实现）
4. 重写 `_html_tools.py`，跑 baseline

**验收**：HTML baseline 全绿（注意标准化 — `<div>` 属性顺序、空白）。

---

#### Step 7 — 收尾迁移：废弃旧 ReportContent 路径 [0.5d]

**修改文件**：
- `backend/tools/report/_content_collector.py`（标记 deprecated）
- `backend/tools/report/_agent_loop.py`（移除 `serialize_report_content`）
- 4 端 `*_gen.py`（清理 fallback 中残留的旧路径调用）

**实施动作**：
1. 确认 4 端都已切到 `collect_and_build_outline`
2. `_content_collector.py` 顶部加：`# DEPRECATED: replaced by _outline_legacy + _outline_planner. Will be removed in next major version.`
3. **不要删** `collect_and_associate` 函数本身 —— `_outline_legacy.collect_and_build_outline` 内部还在调用它。它现在的角色是"把 raw context 转成 ReportContent"，是 legacy 转换器的输入。
4. 删除 `serialize_report_content`（已经没人用）
5. 删除 `_build_docx_deterministic` 等旧函数（已被 renderer 替代）
6. 全套 baseline 测试再跑一遍确认无回归

**验收**：所有 baseline 测试 + 既有契约测试全绿；废弃代码已清理。

---

### Sprint 3：LLM Planner

#### Step 8-9 — `_outline_planner.py` + 灰度

> **历史步骤，详细规格已废弃**。Step 8 原计划"LLM 主路径 + 规则 fallback 双路径"，Step 9 设计了 `REPORT_OUTLINE_PLANNER_ENABLED` 灰度开关 + 三周渐进策略。Step 12 收尾时彻底简化为"仅 LLM 路径"——开关、规则 fallback、`_outline_legacy.py` / `_kpi_extractor.py` 一并删除。
>
> **当前实现位置**：
> - 规划逻辑：[`backend/tools/report/_outline_planner.py`](../backend/tools/report/_outline_planner.py)（`plan_outline` 入口、`_validate_outline_response` 校验、`_consume_synthesised_assets` 处理 LLM 合成 asset）
> - Prompt 模板：[`backend/tools/report/_planner_prompts.py`](../backend/tools/report/_planner_prompts.py)（`OUTLINE_PLANNER_SYSTEM` + `build_planner_user_prompt` + 完整 JSON Schema 输出说明）
> - Debug dump：`REPORT_DEBUG_DUMP_OUTLINE` flag 仍保留（dump 到 `data/reports/outline_<task_id>.json`）
> - 失败处理：LLM 错误 / JSON 解析失败 / asset_id 编造 → 直接抛 `_LLMPlannerFailure`，无内置兜底，由调用方处理
>
> 不要按本节原始伪代码（已删）去找当前函数签名——以源码为准。

---

## 6. 测试策略汇总

| 测试 | 路径 | 守卫什么 |
|---|---|---|
| `test_report_outputs_baseline.py` | `tests/contract/` | 4 端输出结构等价（核心回归网） |
| `test_outline_model.py` | `tests/contract/` | Outline dataclass + JSON 序列化 |
| `test_block_renderer_protocol.py` | `tests/contract/` | dispatch 全覆盖 |
| `test_pptxgen_constraints.py` | `tests/contract/` | PptxGenJS 隐性坑 |
| `test_outline_planner_llm.py` | `tests/contract/` | LLM planner JSON schema + asset_id 校验 |
| `test_outline_planner_fallback.py` | `tests/contract/` | LLM 失败时 fallback 触发 |

baseline 测试在 Step 0 落地后必须**每个 Step 结束都跑一遍**。

---

## 7. 数据契约速查

### 7.1 Block 完整字段表

| Block kind | 字段 | 必填 | 说明 |
|---|---|---|---|
| `kpi_row` | `block_id, items` | 是 | items: `[KPIItem]`，最多 4 |
| `paragraph` | `block_id, text, style` | 是 | style ∈ body/lead/callout-warn/callout-info |
| `table` | `block_id, asset_id` | 是 | asset_id 指向 TableAsset 或 StatsAsset |
| `table` | `caption, highlight_rules` | 否 | |
| `chart` | `block_id, asset_id` | 是 | asset_id 指向 ChartAsset |
| `chart` | `caption` | 否 | |
| `chart_table_pair` | `block_id, chart_asset_id, table_asset_id, layout` | 是 | layout ∈ h/v |
| `comparison_grid` | `block_id, columns` | 是 | columns: `[{title, items: [str]}]`，N=2-4 |
| `growth_indicators` | `block_id, growth_rates` | 是 | 同当前 GrowthItem |
| `section_cover` | `block_id, index, title` | 是 | 渲染留 Sprint 3+ |

### 7.2 Asset 完整字段表

| Asset kind | 字段 |
|---|---|
| `chart` | `asset_id, source_task, option, endpoint?` |
| `table` | `asset_id, source_task, df_records, columns_meta, endpoint?` |
| `stats` | `asset_id, source_task, summary_stats, endpoint?` |

`endpoint` 用于 label_zh 解析，沿用当前 `_field_labels.resolve_col_label` 的 endpoint 优先级。

### 7.3 BlockRenderer 协议方法签名

参见 Step 2 代码块，所有方法返回 `None`，状态在 renderer 内部维护，最终通过 `end_document()` 取出 bytes/str。

---

## 8. 风险登记 + 回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| baseline 测试覆盖不足，迁移引入隐性回归 | 中 | 高 | Step 0 必须故意改坏代码验证测试敏感度 |
| LLM planner 输出不规范 | 高 | 中 | JSON schema 校验 + 1 次 retry + rule fallback |
| LLM 编造 asset_id | 中 | 中 | 严格校验 + fallback |
| Skill mode 工具集变化导致旧 LLM 失败率上升 | 中 | 中 | Step 4 上线前用真实 fixture 跑 ≥5 次 agent 路径，统计成功率 |
| PptxGenJS 桥接在新 renderer 下行为不一致 | 低 | 中 | Step 5 单测固化约束 |
| HTML 字符串模板规范化困难导致 baseline 误判 | 中 | 低 | Step 0 用 BeautifulSoup AST 比较，不比较字符串 |
| 重构期间产品需求插入新内容类型 | 中 | 高 | Sprint 锁定期间冻结 report 模块，新需求等 Sprint 结束 |

**回滚策略**：每个 Step 都是独立 commit。若 Step N 出问题：
- Step 0-3：直接 revert，主分支无影响
- Step 4-7：revert 对应端，其他端不受影响
- Step 8-9：关 flag 即回 rule 路径

---

## 9. 附录 A — 不在本次重构范围（明确的 Sprint 3+ 工作）

以下视觉效果留待新架构稳定后做，每项都是「新架构上加方法」级改动：

| 项目 | 实现位置 | 预计工时 |
|---|---|---|
| 章节分节封面页（深色背景大标题） | 各 renderer 的 `emit_section_cover` | 0.5d × 4 端 |
| Callout 强调框（左边框/底色） | 各 renderer 的 `emit_paragraph` callout 分支 | 0.5d × 4 端 |
| DOCX 嵌入原生图表（matplotlib） | `DocxBlockRenderer.emit_chart` 接 matplotlib → PNG → `add_picture` | 2d |
| PPT 环形图/饼图/横向条形/组合图 | `_pptxgen_builder` 扩展 chart_type switch | 1d |
| 主题切换（深蓝/科技灰/暖色） | `_theme.py` → `Theme` 类 + renderer 注入 | 1d |
| 视觉回归（pixel diff） | `tests/visual/` + LibreOffice + pdftoppm + perceptual hash | 2d |

---

## 10. 附录 B — Claude Code 执行 Tips

- 每个 Step 开始前重读本文档第 3 节（架构快照）和当前 Step 章节
- 每个 Step 结束跑一次 `pytest tests/contract/test_report_outputs_baseline.py`
- 任何"baseline 不通过"都不要修 baseline，要修代码 — baseline 是单一真实来源
- LLM prompt 修改要在 `_planner_prompts.py` 集中维护，不要散落
- 新增 Block kind 时按顺序：(1) `_outline.py` dataclass → (2) `_block_renderer.py` 协议方法 → (3) 4 个 renderer 实现 → (4) `_planner_prompts.py` schema → (5) 单测
- 跨 Step 的 deprecated 代码用注释 `# DEPRECATED — Step N 移除` 明确标注，Step 7 统一清理

---

**EOF**
