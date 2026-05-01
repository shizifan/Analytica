# Complexity 边界重新划分 — 实施方案

**目标读者**：Claude Code 执行实例（无本会话上下文）
**作者**：边界讨论沉淀（2026-05-01）
**状态**：📋 待启动
**前置讨论**：会话中关于 simple_table / chart_text / full_report 边界 10 点诊断

---

## 0. Mission

把 `simple_table` / `chart_text` / `full_report` 的边界从**当前两套互不同步的规则**（`schemas.py` 槽位 condition + `planning.py` prompt 工具白名单）收敛到**单一事实源**，并按业务直觉重划：

```
 simple_table  =  表格类查询（fetch + 可选 chart，单组件切换）
 chart_text    =  图文分析（含归因/预测/总结，无报告文件）
 full_report   =  图文分析 + 可下载文档（在 chart_text 基础上加 report_*）
```

**核心改造**：把"工具白名单 / 必须工具 / 槽位关联 / 任务数建议"统一为一份 `COMPLEXITY_RULES` 表，让 schemas / planning / perception / validation 全部读它，杜绝两套规则漂移。

---

## 1. 当前状态实测

### 1.1 边界定义实际分布

| 规则 | 定义位置 | 内容 |
|------|----------|------|
| 槽位与复杂度关联 | `backend/models/schemas.py:24-26` | `attribution_needed` condition: `chart_text + full_report` <br>`predictive_needed` condition: `full_report` only<br>`output_format` condition: `full_report` only |
| 任务数硬上限 | `backend/agent/planning.py:34-38` | `TASK_COUNT_LIMITS = {simple:(1,3), chart_text:(2,5), full_report:(5,25)}` |
| 工具白名单（prompt）| `backend/agent/planning.py:144-159` | "chart_text 禁止 tool_attribution"、"simple_table 只允许 fetch + summary"、"full_report 必须 ≥4 fetch + ≥3 chart + ≥2 desc + ≥1 attribution + ≥1 summary + ≥1 report" |
| 工具白名单（验证）| `backend/agent/planning.py:_enforce_complexity_constraints (1606-1629)` | chart_text: 必须 fetch + chart；full_report: 必须 fetch + chart + report_gen |
| 任务数上限强制 | `backend/agent/planning.py:_validate_tasks Phase 4 (1538-1554)` | 用 `TASK_COUNT_LIMITS` 截断超额任务 |
| 澄清触发条件 | `backend/agent/perception.py:CONDITION_RULES (161-163)` | 仅 `output_format` 在 full_report 时触发追问 |

### 1.2 已识别的内部矛盾

```
schemas.py:25:    attribution_needed condition = chart_text + full_report
                           ↓ (perception 据此填槽)
planning.py:151:  chart_text 禁止 tool_attribution
                           ↓ (planning 拒绝生成)
结果:             用户在 chart_text 场景说"为什么 X" → attribution_needed=true
                  → planning 静默忽略 → 用户的归因诉求蒸发
```

### 1.3 现有测试覆盖

`tests/contract/test_no_silent_loss.py:52-66`:
```python
def test_complexity_constraint_raises_not_silent():
    """chart_text 没图表工具时必须 raise"""
    with pytest.raises(PlanningError, match="图表工具"):
        engine._validate_tasks(..., complexity="chart_text")
```

→ **本测试在新方案下需要重写**（chart 不再是 chart_text 的硬约束）。

`tests/contract/test_plan_templates.py:101-105`:
```python
complexity = get_template_meta(employee_id).get("complexity", "full_report")
engine._validate_tasks(plan, valid_tools, valid_endpoints, complexity)
```
→ 调用接口签名不变，无需改。

---

## 2. 新边界规则（基于讨论的 10 点）

### 2.1 三层职责重定义

| 复杂度 | 业务定位 | 工具准入 | 必备 | 禁用 |
|--------|---------|---------|------|------|
| **simple_table** | 表格类查询，可选切换图表视图 | `tool_api_fetch` / `tool_file_parse` / `tool_chart_*` (含 `tool_dashboard`) / `tool_web_search` | (`tool_api_fetch` \| `tool_file_parse`) ≥ 1 | `tool_desc_analysis` / `tool_attribution` / `tool_prediction` / `tool_anomaly` / `tool_summary_gen` / `tool_report_*` (4 个) |
| **chart_text** | 图文分析（含归因/预测/总结，**不出报告文件**） | 除 `tool_report_*` 外全部 | (`tool_api_fetch` \| `tool_file_parse`) ≥ 1 | `tool_report_html` / `tool_report_docx` / `tool_report_pptx` / `tool_report_markdown` |
| **full_report** | chart_text + 可下载文档 | 全部工具 | (`tool_api_fetch` \| `tool_file_parse`) ≥ 1 + `tool_report_*` ≥ 1（任一报告工具，最后一个） | 无 |

### 2.2 任务数：从硬限制改为软提示

| 复杂度 | 旧硬上限 | 新软建议 (min / typical / max_soft) |
|--------|---------|--------|
| simple_table | 1-3 | 1 / 1 / 2 |
| chart_text | 2-5 | 1 / 4 / 8 |
| full_report | 5-25 | 3 / 8 / 20 |

**实现**：
- **删除** `TASK_COUNT_LIMITS` 整个常量
- 在 `_complexity_rules.py` 的 `ComplexityRule` 内用 `task_count_hint_min/typical/max_soft` 三个字段表达
- 移除 `_validate_tasks` Phase 4 的截断逻辑（删除 1538-1554 整段），改为软警告（超出 `max_soft` 仅记 revision_log，不截断）

### 2.3 chart 不再是 chart_text 的硬约束

旧：`_enforce_complexity_constraints` 在 chart_text 缺图表时 raise。
新：仅当 `complexity == full_report` 时检查图表存在（且这条也只是建议级，不 raise，记 revision_log warning）。

理由：用户问"X 趋势如何"——LLM 觉得文字+表格已说清，不出图也合理。强制出图反而劣化输出。

### 2.4 Schema-Planning 边界对齐

| Schema slot condition | 旧 | 新 |
|----------------------|---|----|
| `output_format` | `full_report` only | `full_report` only（不变）|
| `attribution_needed` | `chart_text + full_report` | `chart_text + full_report`（不变；但 planning 不再静默忽略） |
| `predictive_needed` | `full_report` only | **改为 `chart_text + full_report`**（与 attribution 对齐） |

---

## 3. 单一事实源：`_complexity_rules.py`

### 3.1 数据结构

```python
# backend/agent/_complexity_rules.py（NEW）

from dataclasses import dataclass
from typing import Literal

ComplexityLevel = Literal["simple_table", "chart_text", "full_report"]


# ── 验证常量 (横切, 不依赖 ComplexityRule) ──────
# 数据源工具: 所有复杂度都至少需要 1 个 (api_fetch 或 file_parse)
DATA_SOURCE_TOOLS: frozenset[str] = frozenset({
    "tool_api_fetch",
    "tool_file_parse",  # 文件上传, 暂未支持的预留
})

# 报告文件工具: 仅 full_report 必须有, simple_table/chart_text 禁
REPORT_FILE_TOOLS: frozenset[str] = frozenset({
    "tool_report_html",
    "tool_report_docx",
    "tool_report_pptx",
    "tool_report_markdown",
})

# 图表工具: 软建议用 (full_report 缺图表时记 revision_log warning)
CHART_TOOLS: frozenset[str] = frozenset({
    "tool_chart_bar",
    "tool_chart_line",
    "tool_chart_waterfall",
    "tool_dashboard",
})


@dataclass(frozen=True)
class ComplexityRule:
    """三层复杂度的统一定义。schemas / planning / perception 全部从此派生。"""

    name: ComplexityLevel
    description: str

    # 显式禁用工具列表 (按 tool_id, 不依赖 category)
    forbidden_tools: frozenset[str]

    # 槽位关联 (perception/schemas 用)
    relevant_slots: frozenset[str]

    # 任务数提示 (planning prompt 用, 不强制)
    task_count_hint_min: int
    task_count_hint_typical: int
    task_count_hint_max_soft: int


# ── 三层规则定义 ─────────────────────────────────
COMPLEXITY_RULES: dict[str, ComplexityRule] = {
    "simple_table": ComplexityRule(
        name="simple_table",
        description="表格类查询，可选切换图表视图",
        forbidden_tools=frozenset({
            # 分析类全禁
            "tool_desc_analysis",
            "tool_attribution",
            "tool_prediction",
            "tool_anomaly",
            "tool_summary_gen",
            # 报告文件类全禁 (复用 REPORT_FILE_TOOLS 单一事实源, 未来加新报告工具不需要再改这里)
            *REPORT_FILE_TOOLS,
            # 允许: tool_api_fetch / tool_file_parse / tool_chart_* / tool_web_search
        }),
        relevant_slots=frozenset({
            "analysis_subject", "time_range", "domain",
            "region", "comparison_type",
            "data_granularity", "time_granularity",
        }),
        task_count_hint_min=1,
        task_count_hint_typical=1,
        task_count_hint_max_soft=2,
    ),
    "chart_text": ComplexityRule(
        name="chart_text",
        description="图文分析，含归因/预测/总结，不出报告文件",
        forbidden_tools=frozenset({
            # 仅禁报告文件 (复用 REPORT_FILE_TOOLS 单一事实源)
            *REPORT_FILE_TOOLS,
            # 关键: tool_summary_gen 允许 (chart_text 需要它做最终总结)
            # 关键: tool_attribution / tool_prediction / tool_anomaly / tool_desc_analysis 全允许
            # 允许: tool_api_fetch / tool_file_parse / tool_chart_* / tool_web_search
        }),
        relevant_slots=frozenset({
            "analysis_subject", "time_range", "domain",
            "region", "comparison_type",
            "data_granularity", "time_granularity",
            "attribution_needed", "predictive_needed",
        }),
        task_count_hint_min=1,
        task_count_hint_typical=4,
        task_count_hint_max_soft=8,
    ),
    "full_report": ComplexityRule(
        name="full_report",
        description="图文分析 + 可下载文档",
        forbidden_tools=frozenset(),  # 无禁用
        relevant_slots=frozenset({
            "analysis_subject", "time_range", "domain",
            "region", "comparison_type",
            "data_granularity", "time_granularity",
            "attribution_needed", "predictive_needed",
            "output_format",
        }),
        task_count_hint_min=3,
        task_count_hint_typical=8,
        task_count_hint_max_soft=20,
    ),
}


# ── 派生函数 ─────────────────────────────────────
def get_rule(complexity: str) -> ComplexityRule:
    """获取规则；未知 complexity 退化为 simple_table。"""
    return COMPLEXITY_RULES.get(complexity, COMPLEXITY_RULES["simple_table"])


def is_tool_allowed(complexity: str, tool_id: str) -> bool:
    """判断工具在指定复杂度下是否允许使用。

    注意: 此函数只检查 forbidden_tools 黑名单。
    数据源 (≥1) 和 report 文件 (full_report 必须 ≥1) 是验证层的
    "整 plan 级"约束, 不在单工具粒度判断。
    """
    return tool_id not in get_rule(complexity).forbidden_tools


def get_relevant_slots(complexity: str) -> frozenset[str]:
    """获取此复杂度下相关的可填槽位 (供 schemas/perception 派生 condition)。"""
    return get_rule(complexity).relevant_slots


def get_task_count_hint(complexity: str) -> tuple[int, int, int]:
    """返回 (min, typical, max_soft) 给 planning prompt 用。"""
    rule = get_rule(complexity)
    return (rule.task_count_hint_min, rule.task_count_hint_typical, rule.task_count_hint_max_soft)
```

### 3.1.1 工具到三层复杂度的完整映射（实测 16 个工具）

| 工具 ID | 类别 | simple_table | chart_text | full_report | 备注 |
|---------|------|:---:|:---:|:---:|------|
| `tool_api_fetch` | data_fetch | ✅ 必须≥1 | ✅ 必须≥1 | ✅ 必须≥1 | 与 file_parse OR |
| `tool_file_parse` | data_fetch | ✅ 备用 | ✅ 备用 | ✅ 备用 | 文件上传暂未支持，预留 |
| `tool_chart_bar` | visualization | ✅ | ✅ | ✅ | simple_table 也可出图（与表切换） |
| `tool_chart_line` | visualization | ✅ | ✅ | ✅ | 同上 |
| `tool_chart_waterfall` | visualization | ✅ | ✅ | ✅ | 同上 |
| `tool_dashboard` | visualization | ✅ | ✅ | ✅ | 同上 |
| `tool_desc_analysis` | analysis | ❌ | ✅ | ✅ | chart_text 数量按需 |
| `tool_attribution` | analysis | ❌ | ✅ | ✅ | **chart_text 关键修复** |
| `tool_prediction` | analysis | ❌ | ✅ | ✅ | **chart_text 关键修复** |
| `tool_anomaly` | analysis | ❌ | ✅ | ✅ | **盲点 1 修复** |
| `tool_summary_gen` | report* | ❌ | ✅ | ✅ | **盲点 4 修复**（用户特别强调）|
| `tool_web_search` | search | ✅ | ✅ | ✅ | **盲点 2 修复**：所有复杂度允许 |
| `tool_report_html` | report | ❌ | ❌ | ✅ | full_report 必须 ≥1（任一报告文件工具）|
| `tool_report_docx` | report | ❌ | ❌ | ✅ | 同上 |
| `tool_report_pptx` | report | ❌ | ❌ | ✅ | 同上 |
| `tool_report_markdown` | report | ❌ | ❌ | ✅ | 同上 |

`*` `tool_summary_gen` 现有 category="report"，但语义是"分析/总结"，本方案**不依赖**它的 category 做判断（用 tool_id 显式列入 forbidden 或不列入），从而避免 category 错位带来的副作用。category 字段保持现状不动。

### 3.2 测试

`tests/contract/test_complexity_rules.py`（NEW）：

```python
import pytest
from backend.agent._complexity_rules import (
    COMPLEXITY_RULES, get_rule, is_tool_allowed, get_relevant_slots,
    get_task_count_hint, DATA_SOURCE_TOOLS, REPORT_FILE_TOOLS,
)

pytestmark = pytest.mark.contract


class TestRuleStructure:
    def test_three_levels_present(self):
        assert set(COMPLEXITY_RULES.keys()) == {"simple_table", "chart_text", "full_report"}

    def test_data_source_constants(self):
        """DATA_SOURCE_TOOLS 与 REPORT_FILE_TOOLS 为不可变集合"""
        assert "tool_api_fetch" in DATA_SOURCE_TOOLS
        assert "tool_file_parse" in DATA_SOURCE_TOOLS
        assert "tool_report_html" in REPORT_FILE_TOOLS
        assert "tool_report_markdown" in REPORT_FILE_TOOLS

    def test_data_source_disjoint_from_report(self):
        assert DATA_SOURCE_TOOLS & REPORT_FILE_TOOLS == frozenset()

    def test_chart_tools_membership(self):
        from backend.agent._complexity_rules import CHART_TOOLS
        for tool in ("tool_chart_bar", "tool_chart_line",
                     "tool_chart_waterfall", "tool_dashboard"):
            assert tool in CHART_TOOLS

    def test_chart_tools_disjoint_from_others(self):
        """CHART_TOOLS 与 DATA_SOURCE_TOOLS / REPORT_FILE_TOOLS 互斥, 防止集合漂移。"""
        from backend.agent._complexity_rules import CHART_TOOLS
        assert CHART_TOOLS & DATA_SOURCE_TOOLS == frozenset()
        assert CHART_TOOLS & REPORT_FILE_TOOLS == frozenset()


class TestSimpleTableForbidden:
    def test_forbids_all_analysis(self):
        rule = COMPLEXITY_RULES["simple_table"]
        for tool in ("tool_desc_analysis", "tool_attribution",
                     "tool_prediction", "tool_anomaly", "tool_summary_gen"):
            assert tool in rule.forbidden_tools

    def test_forbids_all_report_files(self):
        rule = COMPLEXITY_RULES["simple_table"]
        assert REPORT_FILE_TOOLS <= rule.forbidden_tools

    def test_allows_charts(self):
        """讨论 #2 修复: simple_table 允许出图(与表格切换显示)"""
        assert is_tool_allowed("simple_table", "tool_chart_bar")
        assert is_tool_allowed("simple_table", "tool_chart_line")

    def test_allows_web_search(self):
        """盲点 2 修复: tool_web_search 三层都允许"""
        assert is_tool_allowed("simple_table", "tool_web_search")

    def test_allows_data_sources(self):
        assert is_tool_allowed("simple_table", "tool_api_fetch")
        assert is_tool_allowed("simple_table", "tool_file_parse")


class TestChartTextForbidden:
    def test_forbids_only_report_files(self):
        rule = COMPLEXITY_RULES["chart_text"]
        assert rule.forbidden_tools == REPORT_FILE_TOOLS

    def test_allows_summary_gen(self):
        """盲点 4 关键修复: chart_text 必须能用 summary_gen 做最终总结"""
        assert is_tool_allowed("chart_text", "tool_summary_gen")

    def test_allows_attribution(self):
        """边界 #4 修复: chart_text 不再禁止归因"""
        assert is_tool_allowed("chart_text", "tool_attribution")

    def test_allows_prediction(self):
        """边界 #8 修复: chart_text 不再禁止预测"""
        assert is_tool_allowed("chart_text", "tool_prediction")

    def test_allows_anomaly(self):
        """盲点 1 修复: chart_text 允许异常检测"""
        assert is_tool_allowed("chart_text", "tool_anomaly")

    def test_allows_charts_and_search(self):
        assert is_tool_allowed("chart_text", "tool_chart_bar")
        assert is_tool_allowed("chart_text", "tool_web_search")

    def test_forbids_report_files(self):
        for tool in REPORT_FILE_TOOLS:
            assert not is_tool_allowed("chart_text", tool)


class TestFullReportForbidden:
    def test_forbids_nothing(self):
        rule = COMPLEXITY_RULES["full_report"]
        assert rule.forbidden_tools == frozenset()

    def test_allows_everything(self):
        for tool in ("tool_api_fetch", "tool_file_parse",
                     "tool_chart_bar", "tool_desc_analysis",
                     "tool_attribution", "tool_prediction", "tool_anomaly",
                     "tool_summary_gen", "tool_web_search",
                     "tool_report_html", "tool_report_docx",
                     "tool_report_pptx", "tool_report_markdown"):
            assert is_tool_allowed("full_report", tool), f"{tool} 应允许"


class TestSlotRelevance:
    def test_simple_table_no_attribution_or_prediction(self):
        slots = get_relevant_slots("simple_table")
        assert "attribution_needed" not in slots
        assert "predictive_needed" not in slots

    def test_chart_text_includes_attribution_and_prediction(self):
        slots = get_relevant_slots("chart_text")
        assert "attribution_needed" in slots
        assert "predictive_needed" in slots
        assert "output_format" not in slots  # 仅 full_report 才有

    def test_full_report_includes_output_format(self):
        slots = get_relevant_slots("full_report")
        assert "output_format" in slots
        assert "attribution_needed" in slots
        assert "predictive_needed" in slots

    def test_time_and_data_granularity_in_all_three(self):
        """time_granularity / data_granularity 在三层都相关 (修复盲点: 之前漏配)"""
        for complexity in ("simple_table", "chart_text", "full_report"):
            slots = get_relevant_slots(complexity)
            assert "time_granularity" in slots, f"{complexity} 缺 time_granularity"
            assert "data_granularity" in slots, f"{complexity} 缺 data_granularity"


class TestTaskCountHint:
    def test_hint_ordered(self):
        """min ≤ typical ≤ max_soft"""
        for complexity in ("simple_table", "chart_text", "full_report"):
            min_n, typical, max_soft = get_task_count_hint(complexity)
            assert min_n <= typical <= max_soft

    def test_simple_table_hint_smaller_than_chart_text(self):
        s_max = get_task_count_hint("simple_table")[2]
        c_max = get_task_count_hint("chart_text")[2]
        assert s_max < c_max
```

---

## 4. 各文件改动清单

### 4.1 `backend/agent/_complexity_rules.py`（**新增**）

完整内容见 §3.1。约 **130 行**。

### 4.2 `backend/models/schemas.py`（**改造**）

**改动**：把 `SLOT_SCHEMA` 中的 `condition` 从字符串字面量改为从 `_complexity_rules` 派生。

```python
# OLD (24-26 行)
SlotDefinition(name="output_format", required=False, priority=4, condition="output_complexity=full_report"),
SlotDefinition(name="attribution_needed", required=False, priority=5, inferable=True, condition="output_complexity in [chart_text,full_report]"),
SlotDefinition(name="predictive_needed", required=False, priority=6, inferable=True, condition="output_complexity=full_report"),

# NEW
def _build_slot_condition(slot_name: str) -> str | None:
    """从 _complexity_rules 派生槽位的 condition 字符串。"""
    from backend.agent._complexity_rules import COMPLEXITY_RULES

    relevant_complexities = [
        complexity for complexity, rule in COMPLEXITY_RULES.items()
        if slot_name in rule.relevant_slots
    ]
    # 全部复杂度都关联 → 不需要 condition
    if len(relevant_complexities) == len(COMPLEXITY_RULES):
        return None
    if len(relevant_complexities) == 1:
        return f"output_complexity={relevant_complexities[0]}"
    return f"output_complexity in [{','.join(sorted(relevant_complexities))}]"


SLOT_SCHEMA: list[SlotDefinition] = [
    SlotDefinition(name="analysis_subject", required=True, priority=2, inferable=False),
    SlotDefinition(name="time_range", required=True, priority=1, inferable=False),
    SlotDefinition(name="output_complexity", required=False, priority=3, inferable=True),
    SlotDefinition(name="output_format", required=False, priority=4,
                   condition=_build_slot_condition("output_format")),
    SlotDefinition(name="attribution_needed", required=False, priority=5, inferable=True,
                   condition=_build_slot_condition("attribution_needed")),
    SlotDefinition(name="predictive_needed", required=False, priority=6, inferable=True,
                   condition=_build_slot_condition("predictive_needed")),
    # ... 其他 slot 不变
]
```

**等价性验证**：派生后的 condition 应与旧字面量一致（除了 `predictive_needed` 现在包含 chart_text）。

### 4.3 `backend/agent/planning.py`（**重点改造**）

#### 4.3.1 删除 `TASK_COUNT_LIMITS`（34-38 行）

**直接删除整个常量**。所有原引用点改为读 `_complexity_rules`：

```python
# 删除整段:
TASK_COUNT_LIMITS = {
    "simple_table": (1, 3),
    "chart_text":   (2, 5),
    "full_report":  (5, 25),
}
```

**全工程引用点 grep**：
```
backend/agent/planning.py:1105   if "output_format" in intent and intent["output_format"] in TASK_COUNT_LIMITS:
backend/agent/planning.py:1115   if val and val in TASK_COUNT_LIMITS:
backend/agent/planning.py:1539   _, max_count = TASK_COUNT_LIMITS.get(complexity, (1, 8))
```

**逐处改造**：

**1105-1106 行（`_get_complexity` 内 dead code）— 删除整段**：
```python
# 这两行是无害 dead code: output_format 的值是 "html"/"docx"/"pptx",
# 永远匹配不到 TASK_COUNT_LIMITS 的键 "simple_table"/"chart_text"/"full_report"。
# 顺便清理, 不再保留。
if "output_format" in intent and intent["output_format"] in TASK_COUNT_LIMITS:
    return intent["output_format"]
```

**1115 行（`_get_complexity` 内合法引用）— 替换常量名**：
```python
# 旧:
if val and val in TASK_COUNT_LIMITS:
    return val

# 新:
if val and val in COMPLEXITY_RULES:
    return val
```
（需要在文件顶部加 `from backend.agent._complexity_rules import COMPLEXITY_RULES`。）

**1539 行（任务数硬截断）— 删除整个截断逻辑（详见 §4.3.5）**，不需要替代。

**注**：1105-1106 dead code 是历史遗留 bug，本方案顺手清理（删除而非保留），属"重构窗口期一并治理"，不在 §7「不在本方案范围」之外引入新问题。

#### 4.3.2 重写 prompt 的"任务数量要求"段（121-125 行）

```python
# 旧
【任务数量要求】
- simple_table: 1-3 个任务
- chart_text: 2-5 个任务
- full_report: 5-25 个任务

# 新
【任务数量建议】（仅供参考, 实际由数据复杂度决定）
- simple_table: 1-2 个任务（典型 1 个）
- chart_text:   1-8 个任务（典型 4 个；按数据需要灵活调整）
- full_report:  3-20 个任务（典型 8 个；包含完整数据→分析→可视化→报告链路）
```

#### 4.3.3 重写"工具激活规则"段（143-159 行）

```python
# 新
【工具激活规则】（按复杂度区分; 验证层会强制 must / forbidden）
■ simple_table - 表格类查询:
  - 必须: tool_api_fetch 或 tool_file_parse (≥1, 选最合适的数据源)
  - 可选: tool_chart_* (如数据适合可视化, 与表格在同一卡片切换显示)
  - 可选: tool_web_search (需补充外部信息时)
  - 禁止: tool_desc_analysis / tool_attribution / tool_prediction / tool_anomaly / tool_summary_gen / tool_report_*

■ chart_text - 图文分析:
  - 必须: tool_api_fetch 或 tool_file_parse (≥1, 按数据需要)
  - 可选 (按数据需要灵活组合):
    - tool_chart_* - 当图表能更好展现分析结论时使用; 文字能说清就不必出图
    - tool_desc_analysis - 针对单个或多个 API 数据做描述性分析, 数量按需 (一份数据一段叙述, 或多份数据综合一段叙述)
    - tool_attribution - 当用户问"为什么/原因/归因"时使用
    - tool_prediction - 当用户问"未来/趋势预测"时使用
    - tool_anomaly - 当用户问"异常/反常/突变"时使用
    - tool_summary_gen - 多任务综合总结 (推荐作为最后一个任务)
    - tool_web_search - 需补充外部信息时
  - 禁止: tool_report_* (HTML / DOCX / PPTX / Markdown 文件输出, 共 4 个)

■ full_report - 图文分析 + 可下载文档:
  - 必须: tool_api_fetch 或 tool_file_parse (≥1) + tool_report_* (≥1, 任一报告工具, 必须是最后一个任务)
  - 可选: 同 chart_text 的全部可选工具 (鼓励完整链路: 数据 → 分析 → 可视化 → 总结 → 报告)
  - 禁止: 无

【重要】
- 任务工具应基于"数据是否需要"决定, 不要为了凑层级而生成冗余任务
- chart_text 与 full_report 的唯一区别是是否需要可下载文档 (HTML/DOCX/PPTX/Markdown)
- simple_table 始终不生成分析类工具 (desc / attribution / prediction / anomaly / summary)
- chart_text / full_report 内部, 是否生成 attribution/prediction/anomaly 任务由 attribution_needed/predictive_needed 等槽位决定
```

#### 4.3.4 简化 `_enforce_complexity_constraints`（1585-1629 行）

**改动方式**：完全替换原函数体（1585-1629 共 45 行），保留方法签名 `def _enforce_complexity_constraints(self, plan, complexity) -> None`。

```python
def _enforce_complexity_constraints(
    self, plan: AnalysisPlan, complexity: str,
) -> None:
    """从 _complexity_rules 派生的硬约束验证。

    三类硬检查 (违反则 PlanningError, 触发重试):
      1. 数据源: 所有复杂度都至少需要 1 个 fetch 类工具 (api_fetch 或 file_parse)
      2. forbidden_tools: 显式黑名单不可有
      3. full_report: 至少 1 个报告文件工具 (report_html/docx/pptx/markdown)

    软警告 (记 revision_log 不抛错):
      - full_report 缺图表
      - 任务数超 max_soft (在 _validate_tasks Phase 4 处理)
    """
    from backend.agent._complexity_rules import (
        CHART_TOOLS,
        DATA_SOURCE_TOOLS,
        REPORT_FILE_TOOLS,
        get_rule,
    )

    rule = get_rule(complexity)
    tasks = plan.tasks
    if not tasks:
        raise PlanningError(
            f"规划失败：过滤后没有剩余任务（complexity={complexity}）"
        )

    tools_used = {t.tool for t in tasks if t.tool}

    # 1. 数据源检查 (所有复杂度通用 — simple_table 也走这条, 不需要单独 case)
    if not (tools_used & DATA_SOURCE_TOOLS):
        raise PlanningError(
            f"{complexity} 复杂度要求至少 1 个数据获取任务 "
            f"(tool_api_fetch 或 tool_file_parse), 过滤后剩 0 个"
        )

    # 2. forbidden_tools 检查 (单一事实源黑名单)
    forbidden_present = tools_used & rule.forbidden_tools
    if forbidden_present:
        raise PlanningError(
            f"{complexity} 复杂度禁止使用: {sorted(forbidden_present)}"
        )

    # 3. full_report 必须有 ≥1 报告文件工具
    if complexity == "full_report":
        if not (tools_used & REPORT_FILE_TOOLS):
            raise PlanningError(
                f"full_report 复杂度要求至少 1 个报告文件工具 "
                f"({sorted(REPORT_FILE_TOOLS)})"
            )

    # 软警告: full_report 缺图表 (用 _complexity_rules 的 CHART_TOOLS 常量, 避免硬编码漂移)
    # 注: int(time.time()) 依赖 planning.py 文件顶部的 import time (现有, 多处使用)
    if complexity == "full_report" and not (tools_used & CHART_TOOLS):
        plan.revision_log.append({
            "phase": "validation_warning",
            "ts": int(time.time()),
            "message": "full_report 未生成图表任务, 报告可能仅含文字",
        })

    # 注:
    # - chart_text 不再硬要求图表 (用户讨论 #7)
    # - 不再有 forbidden_categories 检查 (避免 tool_summary_gen 因 category=report 被误禁)
    # - chart_text 的 summary_gen 现在能正常工作
```

**与原有 1606-1629 行实现的核心区别**：

| 维度 | 旧 | 新 |
|------|---|---|
| 数据源检查 | 仅 chart_text 检查 | 三层都检查 |
| chart_text 必须图表 | ✅ 是 (硬约束) | ❌ 否 (软建议) |
| full_report 必须图表 | ✅ 是 (硬约束) | ❌ 否 (软警告) |
| full_report 必须报告 | 用 `t.type == "report_gen"` 判 | 用 tool_id 显式列表判 (REPORT_FILE_TOOLS) |
| forbidden 检查粒度 | 无（仅 prompt 软约束） | tool_id 黑名单（硬约束） |
| category 检查 | 无 | 无（不依赖 category 字段） |

#### 4.3.5 删除任务数硬截断（`_validate_tasks` Phase 4，1538-1554 行）

**改动方式**：删除原 1538-1554 整段（`# Phase 4 — cap task count` 注释开始到截断逻辑结束），在原位置插入下方新代码。

```python
# Phase 4 — task count soft warning (was: hard cap, now: warning only)
from backend.agent._complexity_rules import get_task_count_hint
_, _, max_soft = get_task_count_hint(complexity)
if len(kept) > max_soft:
    plan.revision_log.append({
        "phase": "validation_warning",
        "ts": int(time.time()),
        "message": (
            f"{complexity} 任务数 {len(kept)} 超过软建议上限 {max_soft}, "
            f"未截断, 仅记录"
        ),
    })
    logger.info(
        "Task count %d exceeds soft hint %d for %s (not truncated)",
        len(kept), max_soft, complexity,
    )
```

**原 1538-1554 行的逻辑（需删除）**：
```python
# Phase 4 — cap task count (preserve report_gen)
_, max_count = TASK_COUNT_LIMITS.get(complexity, (1, 8))
cap_dropped: list[str] = []
if len(kept) > max_count:
    report_tasks = [t for t in kept if t.type == "report_gen"]
    non_report_tasks = [t for t in kept if t.type != "report_gen"]
    non_report_cap = max(max_count - len(report_tasks), 1)
    if len(non_report_tasks) > non_report_cap:
        cap_dropped = [t.task_id for t in non_report_tasks[non_report_cap:]]
        non_report_tasks = non_report_tasks[:non_report_cap]
    kept = non_report_tasks + report_tasks
    for tid in cap_dropped:
        drop_reasons[tid] = f"truncated by complexity cap ({complexity}: max {max_count})"
    logger.warning(...)
```

**关键差异**：
- 删除"按 type 分桶截断"的逻辑（不再 split report_tasks / non_report_tasks）
- 删除 `cap_dropped` 局部变量与 `drop_reasons` 截断标记写入
- `kept` 列表不再被修改（保持 §_validate_tasks Phase 3 后的全集）

**重试语义说明**（与 §4.3.5 Phase 4 写入 revision_log 相关）：

`generate_plan` 的重试循环（`planning.py:691` 起）每次重试都会重新调用 `_build_plan(plan_dict, ...)` 创建**全新**的 `AnalysisPlan` 对象。这意味着：

- Phase 4 写入 `plan.revision_log` 的"任务数超软上限"软警告，**仅在该次 LLM 调用产出的 plan 上**
- 若同一次调用后续 Phase 7 (`_enforce_complexity_constraints`) raise PlanningError 触发重试，该 plan 对象被丢弃，软警告随之消失
- 这是**预期行为**：软警告反映的是"那一次 LLM 输出的特征"，下一次重试若产出合规 plan 就不应该携带上次的警告

工程师无需特别处理；只需理解 revision_log 的语义是"本次最终成功 plan 上记录的所有非致命问题"，不是"所有重试历史的累积"。

#### 4.3.6 更新 `PLANNING_RULE_HINTS` 中的"minimization"（55-61 行）

```python
# 旧
"minimization": (
    "- 优先使用最少的 data_fetch 任务...\n"
    "- chart_text 典型结构：1 个 data_fetch + 1 个 visualization = 2 个任务\n"
    "..."
),

# 新
"minimization": (
    "- 优先使用最少的 data_fetch 任务。能用一个 API 满足的需求, 不要用多个\n"
    "- chart_text 任务由数据复杂度决定: 简单查询 1-2 个任务即可, 复杂分析可以更多\n"
    "- 不要为了凑任务数添加冗余数据获取\n"
    "- attribution_needed=false 或用户说\"不需要归因\"时, 不生成归因分析任务\n"
    "- predictive_needed=false 或用户没问\"预测/未来\"时, 不生成预测任务"
),
```

### 4.4 `backend/agent/perception.py`（**轻改**）

`CONDITION_RULES` (161-163 行) 当前只有 `output_format`，对齐新规则：

```python
# 旧
CONDITION_RULES = {
    "output_format": lambda complexity: complexity == "full_report",
}

# 新 (从 _complexity_rules 派生 — 单函数, 无闭包, 显式直读)
def _output_format_relevant(complexity: str) -> bool:
    """output_format 仅在 full_report 复杂度下需要追问。

    实现方式: 直读 _complexity_rules.COMPLEXITY_RULES, 与单一事实源对齐。
    避免老 lambda 写法的硬编码漂移。
    """
    from backend.agent._complexity_rules import COMPLEXITY_RULES
    rule = COMPLEXITY_RULES.get(complexity)
    return rule is not None and "output_format" in rule.relevant_slots


CONDITION_RULES = {
    "output_format": _output_format_relevant,
}
```

注：
- `attribution_needed` / `predictive_needed` 维持 perception 现有策略：**仅在用户明确说才填，不主动追问**。本方案不加入 CONDITION_RULES。
- 不用 lambda + 默认参数闭包的原因：那种写法对后续修改脆弱（一旦循环/分支变化容易破坏闭包捕获），用具名函数 + 显式 dict 更清晰。

### 4.5 测试改动

#### 4.5.1 改 `tests/contract/test_no_silent_loss.py:52-66`

```python
# 旧 - chart_text 没图表必须 raise
def test_complexity_constraint_raises_not_silent():
    ...
    with pytest.raises(PlanningError, match="图表工具"):
        engine._validate_tasks(..., complexity="chart_text")

# 新 - chart_text 没图表不再 raise (改为 simple_table 禁用 desc_analysis 验证)
def test_complexity_constraint_raises_not_silent():
    """When complexity invariant is violated, validator must raise."""
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import AnalysisPlan, TaskItem
    from backend.exceptions import PlanningError

    engine = PlanningEngine(llm=None, llm_timeout=10, max_retries=1)
    # simple_table 禁止 tool_desc_analysis, 违反时必须 raise
    plan = AnalysisPlan(title="t", analysis_goal="", estimated_duration=10, tasks=[
        TaskItem(task_id="T001", type="data_fetch", tool="tool_api_fetch",
                 params={"endpoint_id": "E"}, depends_on=[]),
        TaskItem(task_id="T002", type="analysis", tool="tool_desc_analysis",
                 params={}, depends_on=["T001"]),
    ])
    with pytest.raises(PlanningError, match="禁止"):
        engine._validate_tasks(
            plan,
            valid_tools={"tool_api_fetch", "tool_desc_analysis"},
            valid_endpoints={"E"},
            complexity="simple_table",
        )


# 新增测试: chart_text 没图表不再 raise
def test_chart_text_without_chart_does_not_raise():
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import AnalysisPlan, TaskItem

    engine = PlanningEngine(llm=None, llm_timeout=10, max_retries=1)
    plan = AnalysisPlan(title="t", analysis_goal="", estimated_duration=10, tasks=[
        TaskItem(task_id="T001", type="data_fetch", tool="tool_api_fetch",
                 params={"endpoint_id": "E"}, depends_on=[]),
        TaskItem(task_id="T002", type="analysis", tool="tool_desc_analysis",
                 params={"data_ref": "T001"}, depends_on=["T001"]),
    ])
    # 不抛错: chart_text 现在允许只用 fetch + desc_analysis
    engine._validate_tasks(
        plan,
        valid_tools={"tool_api_fetch", "tool_desc_analysis"},
        valid_endpoints={"E"},
        complexity="chart_text",
    )
    assert len(plan.tasks) == 2


# 新增测试: chart_text 允许 attribution
def test_chart_text_allows_attribution():
    from backend.agent.planning import PlanningEngine
    from backend.models.schemas import AnalysisPlan, TaskItem

    engine = PlanningEngine(llm=None, llm_timeout=10, max_retries=1)
    plan = AnalysisPlan(title="t", analysis_goal="", estimated_duration=10, tasks=[
        TaskItem(task_id="T001", type="data_fetch", tool="tool_api_fetch",
                 params={"endpoint_id": "E"}, depends_on=[]),
        TaskItem(task_id="T002", type="analysis", tool="tool_attribution",
                 params={}, depends_on=["T001"]),
    ])
    engine._validate_tasks(
        plan,
        valid_tools={"tool_api_fetch", "tool_attribution"},
        valid_endpoints={"E"},
        complexity="chart_text",
    )
    assert len(plan.tasks) == 2
```

#### 4.5.2 新增 `tests/contract/test_complexity_rules.py`

完整内容见 §3.2。约 **80 行**，覆盖单一事实源的全部分支。

#### 4.5.3 现有测试影响评估

| 测试文件 | 影响 | 处理 |
|----------|------|------|
| `test_no_silent_loss.py` | 1 个测试需重写 + 2 个新增 | 见 §4.5.1 |
| `test_planning_rule_hints.py` | minimization rule 文本变了 | 检查断言是否依赖具体字符串，按需更新 |
| `test_planning_node_degradation.py` | 不依赖任务数限制 | 无影响 |
| `test_plan_templates.py` | 调用 `_validate_tasks` 接口签名 | 无影响 |
| `test_employee_dryrun.py` | 不依赖边界规则 | 无影响 |

---

## 5. 落地步骤

**一次性切换，无灰度，无中间过渡，无新旧并存。** 6 步顺序合并到同一个 PR。

### Step 1: 单一事实源
1. 新建 `backend/agent/_complexity_rules.py` (§3.1)
2. 新建 `tests/contract/test_complexity_rules.py` (§3.2)

### Step 2: schemas.py 改造
1. 改 `backend/models/schemas.py` (§4.2): condition 改为从 `_complexity_rules` 派生
2. **不保留旧字面量**

### Step 3: planning.py 改造
1. 删除 `TASK_COUNT_LIMITS` 整个常量 (§4.3.1)
2. `_get_complexity` 内的 `TASK_COUNT_LIMITS` 引用全部替换为 `COMPLEXITY_RULES` (§4.3.1)
3. 重写 `_enforce_complexity_constraints` (§4.3.4)
4. 重写 prompt 工具激活规则段 (§4.3.3)
5. 重写 prompt 任务数量段 (§4.3.2)
6. 删除 `_validate_tasks` Phase 4 任务数硬截断 (§4.3.5)
7. 重写 `minimization` rule (§4.3.6)

### Step 4: perception.py 改造
1. `CONDITION_RULES` 改为从 `_complexity_rules` 派生 (§4.4)

### Step 5: 测试更新
1. 重写 `test_no_silent_loss.py:test_complexity_constraint_raises_not_silent`
2. 新增 `test_chart_text_without_chart_does_not_raise`
3. 新增 `test_chart_text_allows_attribution`
4. 检查 `test_planning_rule_hints.py` 是否依赖具体 minimization 字符串，按需更新

### Step 6: 验证
1. 跑全量 contract 测试 (≥387 全过)
2. 按 §8 验收标准 4 项行为人工跑

### 一刀切原则
- ❌ 不引入 `COMPLEXITY_BOUNDARY_V2_ENABLED` 等任何 feature flag
- ❌ 不保留旧 `TASK_COUNT_LIMITS` 作为兼容层
- ❌ 不在 `_enforce_complexity_constraints` 里放 if/else 分支保留旧行为
- ❌ 不允许新旧 prompt 段并存
- ✅ 所有改动一个 commit 落地，回退就 git revert，不靠 flag 切换

---

## 6. 风险与缓解

由于一刀切上线，所有风险都靠**前置工程严谨度**消除，不靠 flag 兜底。

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| chart_text 行为综合变化大（任务数变多 / 多了 attribution+prediction+summary_gen 等工具 / 不再硬要求 chart） | 高 | 中 | (1) prompt 给"典型 4 个任务"建议值约束 LLM; (2) minimization rule 强调"按数据需要"; (3) attribution/prediction 仍受槽位控制（"仅当用户明确问为什么/未来时使用"）; (4) §8 验收标准 4 项人工跑通; (5) commit 信息 + spec 链接清晰, 便于必要时 git revert |
| LLM 在 chart_text 滥用 attribution / prediction | 中 | 中 | prompt 强调"仅当用户明确问为什么/未来时使用" + perception 已严格控 `attribution_needed` slot 填充策略不变 |
| simple_table 用户期望出图但被禁 | 低 | 低 | simple_table 现允许 chart_*, 前端 TaskResultCard 已支持表/图切换 |
| 历史 template (full_report) 任务数超 soft cap | 低 | 低 | 软警告不截断, 现有 template 行为零变化 |
| schemas condition 派生与旧字面量不一致 | 中 | 中 | **预合并自动检查**：`_complexity_rules` 派生结果 vs 旧字面量做单元测试断言（除 `predictive_needed` 故意扩大外其他必须等价） |
| 删除 `TASK_COUNT_LIMITS` 影响其他模块 | 低 | 中 | 全工程仅 planning.py 内 3 处引用，全部在本方案改造范围内 |

---

## 7. 不在本方案范围

为避免重蹈"边界改动 + 执行模型重构"双重风险：

- ❌ 不动 execution.py 的 DAG 跑法
- ❌ 不动 graph.py 的节点编排
- ❌ 不动 tool 实现 (descriptive / attribution / summary_gen 等)
- ❌ 不引入 cell / re-plan / phase loop 概念
- ❌ 不动前端

本方案**只改边界规则的定义与强制点**, 不改任何 runtime 行为或工具实现。

---

## 8. 验收标准

### 功能验收（API 级）
- [ ] `is_tool_allowed("chart_text", "tool_attribution")` → `True`（边界 #4 修复）
- [ ] `is_tool_allowed("chart_text", "tool_prediction")` → `True`（边界 #8 修复）
- [ ] `is_tool_allowed("chart_text", "tool_anomaly")` → `True`（盲点 1 修复）
- [ ] **`is_tool_allowed("chart_text", "tool_summary_gen")` → `True`（盲点 4 关键修复）**
- [ ] `is_tool_allowed("chart_text", "tool_report_html")` → `False`
- [ ] `is_tool_allowed("simple_table", "tool_chart_bar")` → `True`（边界 #2 修复）
- [ ] `is_tool_allowed("simple_table", "tool_summary_gen")` → `False`
- [ ] `is_tool_allowed("simple_table", "tool_anomaly")` → `False`（盲点 1 一致性）
- [ ] `is_tool_allowed("simple_table", "tool_web_search")` → `True`（盲点 2 修复）
- [ ] `is_tool_allowed("chart_text", "tool_web_search")` → `True`
- [ ] `is_tool_allowed("full_report", *)` → `True` 对所有 16 个工具

### 验证层验收（_enforce_complexity_constraints）
- [ ] simple_table 缺 fetch → PlanningError
- [ ] chart_text 缺 fetch → PlanningError（与旧版一致）
- [ ] full_report 缺 fetch → PlanningError（新增检查）
- [ ] **chart_text 缺图表时不再 raise（旧版会 raise）**
- [ ] **full_report 缺图表时不再 raise，仅记 revision_log（旧版会 raise）**
- [ ] simple_table 含 `tool_desc_analysis` → PlanningError
- [ ] chart_text 含 `tool_summary_gen` → 不 raise（关键修复）
- [ ] chart_text 含 `tool_attribution` → 不 raise
- [ ] chart_text 含 `tool_report_html` → PlanningError
- [ ] full_report 缺 `tool_report_*` → PlanningError

### 回归验收
- [ ] 所有 contract tests 通过 (≥387 + 新增 ≥10)
- [ ] `test_no_silent_loss.py` 改动后通过
- [ ] `test_planning_rule_hints.py` 通过（minimization 文本若改，按需更新）

### 行为验收（人工真跑）
- [ ] 输入"用图表分析 2026Q1 各港吞吐量" → chart_text plan, 含 fetch + chart + desc_analysis + **summary_gen**
- [ ] 输入"分析 2026Q1 吞吐量为什么下降" → chart_text plan, 含 attribution + summary_gen
- [ ] 输入"查 2026Q1 吞吐量" → simple_table plan, 仅 fetch（可选 chart, 不含分析/总结）
- [ ] 输入"出一份吞吐量分析报告" → full_report plan, 最后任务是 `tool_report_*`

---

## 9. 工时估算

| Step | 工时 |
|------|------|
| Step 1 (rules.py + tests) | 0.5d |
| Step 2 (schemas 派生) | 0.5d |
| Step 3 (planning 改造) | 1d |
| Step 4 (perception 对齐) | 0.25d |
| Step 5 (测试更新) | 0.5d |
| Step 6 (验证 + commit) | 0.25d |
| **总计** | **3d，单 PR** |

---

## 10. 与之前 cell 方案的关系

| 方面 | cell 方案（已回退） | 本方案 |
|------|-------------------|--------|
| 改动层 | 引入新执行模型 (4 phase) | 只改边界规则定义 |
| 改动量 | ~3700 行 (含测试) | ~400 行 (含测试) |
| 影响 runtime | 重大 | 零 |
| 上线方式 | 需灰度（已废） | 一刀切，无 flag |
| 解决问题 | "看数据后决策"能力 | 边界规则不一致 + chart_text 缺归因/预测 |

---

## 附录 A: 原始 10 点诊断 + 4 个盲点逐项映射

### 用户讨论的 10 点
| # | 诊断 | 落实位置 |
|---|------|---------|
| 1 | api_fetch 都必须，simple_table=1，其他按需 | §3.1 DATA_SOURCE_TOOLS 三层通用；§4.3.4 验证逻辑 |
| 2 | simple_table 也可选 chart，与表同卡片切换 | §3.1 simple_table forbidden_tools 不含 chart_*；prompt §4.3.3 |
| 3 | desc_analysis 数量按需，可单 ref 或多 ref | §4.3.3 prompt 明确"数量按需" |
| 4 | attribution / prediction / summary_gen 应可用于 chart_text | §3.1 chart_text forbidden_tools 仅含 REPORT_FILE_TOOLS |
| 5 | simple_table 不需要 summary_gen | §3.1 simple_table forbidden_tools 含 tool_summary_gen |
| 6 | 任务数不要写死 | §4.3.2 prompt 改建议；§4.3.5 删硬截断 |
| 7 | chart_text 不一定要有 chart | §4.3.4 不再硬要求图表 |
| 8 | chart_text 不能禁止 attribution / prediction | 同 #4 |
| 9 | chart_text 只允许 1 desc_analysis 限制 LLM | §4.3.3 prompt 不再约束数量 |
| 10 | schema vs planning 边界 | §4.2 schemas 从 _complexity_rules 派生；§3.1 单一事实源 |

### 后续发现的 4 个盲点（基于代码清理后实测工具清单）
| # | 盲点 | 落实位置 |
|---|------|---------|
| 1 | `tool_anomaly` 工具未归属 | §3.1 simple_table forbidden_tools 含；其他允许 |
| 2 | `tool_web_search` 三层都允许 | §3.1 任何 forbidden_tools 都不含；§3.1.1 映射表确认 |
| 3 | `tool_file_parse` 与 `tool_api_fetch` OR 关系 | §3.1 DATA_SOURCE_TOOLS 含两者；§4.3.4 验证逻辑用集合交 |
| 4 | `tool_summary_gen` category=report 错位 | §3.0 决策放弃 category 机制；§3.1 用显式 tool_id 黑名单；chart_text 显式允许 |

---

## 附录 B: 现行代码"边界规则"全分布索引

便于工程师快速定位所有需要改的位置：

| 位置 | 行号 | 内容 |
|------|------|------|
| `backend/models/schemas.py` | 24-26 | `attribution_needed` / `predictive_needed` / `output_format` 的 condition 字面量 |
| `backend/agent/planning.py` | 34-38 | `TASK_COUNT_LIMITS` 字典 |
| `backend/agent/planning.py` | 55-61 | `PLANNING_RULE_HINTS["minimization"]` |
| `backend/agent/planning.py` | 121-125 | prompt"任务数量要求"段 |
| `backend/agent/planning.py` | 143-159 | prompt"工具激活规则"段 |
| `backend/agent/planning.py` | 1538-1554 | `_validate_tasks` Phase 4 任务数硬截断 |
| `backend/agent/planning.py` | 1585-1629 | `_enforce_complexity_constraints` 工具白名单验证 |
| `backend/agent/perception.py` | 161-163 | `CONDITION_RULES` 字面量 |
| `tests/contract/test_no_silent_loss.py` | 52-66 | `test_complexity_constraint_raises_not_silent` 现依赖 chart_text 必须 chart |

---

## 附录 C: 设计抉择档案 — 为什么放弃 `forbidden_categories`

设计过程中曾考虑用 `forbidden_categories: frozenset[str]` 做"整类禁工具"（例如 `chart_text` 把 `category="report"` 整类全禁）。最终放弃，原因如下：

**触发问题**：工具 category 字段与语义不完全对齐。`tool_summary_gen.category = "report"`，但语义上它是"分析/总结"，不是"报告文件"。如果 chart_text 用 `forbidden_categories={"report"}`，会**意外禁掉 chart_text 的 summary_gen**——而 chart_text 明确需要 summary_gen 做最终总结。

**最终方案**：用**显式 tool_id 黑名单**（`forbidden_tools: frozenset[str]`）+ **两组横切常量**（`DATA_SOURCE_TOOLS` / `REPORT_FILE_TOOLS` / `CHART_TOOLS`）单独检查。语义清晰、不依赖 category 字段。

**保留这段记录的原因**：避免后续 review 者看到当前的 tool_id 黑名单设计后，提出"用 category 更优雅"的反向建议。category 与语义错位是实际存在的，且修 category 不在本方案范围。

---

*版本 v1.0 — 2026-05-01*
