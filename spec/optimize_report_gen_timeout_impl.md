# HTML/DOCX 报告生成超时优化 — 详细实施方案

**目标**：消除 `tool_report_html` / `tool_report_docx` 的 `Timeout after 60s` 错误
**状态**：待实施
**前提**：[optimize_report_gen_timeout.md](./optimize_report_gen_timeout.md)

---

## 0. 关键发现：`render_outline` 已存在

在 `_block_renderer.py` (line 150) 中，**`render_outline(outline, renderer)` 已经实现**。它遍历 outline，将每个 block 通过 `_dispatch()` 路由到 renderer 的对应 `emit_*` 方法。这恰好是 agent loop 在做的事情，但无需 LLM。

```python
# _block_renderer.py:150
def render_outline(outline: ReportOutline, renderer: BlockRenderer) -> bytes | str:
    renderer.begin_document(outline)
    for idx, section in enumerate(outline.sections):
        renderer.begin_section(section, idx)
        for block in section.blocks:
            _dispatch(block, outline, renderer)
        renderer.end_section(section, idx)
    return renderer.end_document()
```

`_dispatch()` (line 173) 匹配所有 8 种 block 类型到 renderer 方法，包括 `ChartTablePairBlock` 的 chart + table 双 asset 注入。

---

## 1. 改动清单

### Phase A — 核心：切换为确定性渲染 (P0)

| # | 文件 | 改动 | 行数 |
|---|------|------|------|
| A1 | `backend/tools/report/html_gen.py` | `_run_html_agent()` 删除；`execute()` 中调用 `render_outline(outline, renderer)` | -30 / +5 |
| A2 | `backend/tools/report/docx_gen.py` | `_run_docx_agent()` 删除；`execute()` 中调用 `render_outline(outline, renderer)` | -40 / +5 |
| A3 | `backend/tools/report/_agent_loop.py` | 整体删除（仅被 html_gen + docx_gen 使用） | -195 |
| A4 | `backend/tools/report/_html_tools.py` | 整体删除（仅被 html_gen 的 `_run_html_agent` 使用） | -179 |
| A5 | `backend/tools/report/_docx_tools.py` | 整体删除（仅被 docx_gen 的 `_run_docx_agent` 使用） | -220 |

### Phase B — 防御：调整 timeout profile (P1)

| # | 文件 | 改动 | 行数 |
|---|------|------|------|
| B1 | `backend/agent/execution.py:90` | `report_gen` timeout profile: `(30, 120, 2.0)` → `(60, 180, 2.5)` | 1 |
| B2 | `backend/agent/planning.py:1426` | planning hint `estimated_seconds: 30` → `60` | 1 |
| B3 | `backend/agent/planning.py:1438` | 同上（多格式报告分支） | 1 |
| B4 | `backend/agent/plan_templates/*.json` (×3) | JSON 模板中 `tool_report_html` 的 `estimated_seconds: 30` → `60` | 3 |

### Phase C — 验证：测试修正

| # | 文件 | 改动 | 行数 |
|---|------|------|------|
| C1 | `tests/scenarios/test_json_template_execution.py` | 确认 `mode="llm_agent"` 断言不再失败（改为 `"deterministic"`） | ~2 |
| C2 | `tests/scenarios/test_json_template_execution_by_mock_llm.py` | 同上 | ~2 |
| C3 | 运行全部 contract 测试 | 验证 golden file 对齐 | — |

### 总计
- 删除 ~635 行死代码
- 新增 ~10 行业务代码
- 修改 ~10 行配置/测试

---

## 2. 逐一修改说明

### A1 — `html_gen.py`

**当前**（lines 65–100）：
```python
async def _run_html_agent(renderer: HtmlBlockRenderer, outline) -> None:
    from langchain_openai import ChatOpenAI
    from backend.config import get_settings
    from backend.tools.report._agent_loop import run_report_agent, serialize_outline
    from backend.tools.report._html_tools import HTML_OUTLINE_SYSTEM_PROMPT, make_html_outline_tools

    settings = get_settings()
    llm = ChatOpenAI(...)
    tools = make_html_outline_tools(renderer, outline)
    user_message = serialize_outline(outline)
    success = await run_report_agent(llm, tools, HTML_OUTLINE_SYSTEM_PROMPT, user_message)
    if not success:
        raise RuntimeError("HTML agent did not finalise")
```

**改为**：删除 `_run_html_agent` 整个函数。`execute()` 中第 41 行：
```python
# 旧
await _run_html_agent(renderer, outline)
html = renderer.end_document()

# 新
from backend.tools.report._block_renderer import render_outline
html = render_outline(outline, renderer)
```

同时修改 `mode` metadata（第 48 行）：
```python
# 旧
"mode": "llm_agent",
# 新
"mode": "deterministic",
```

清理不再需要的 import（`langchain_openai.ChatOpenAI`, `get_settings`, `run_report_agent`, `serialize_outline`, `HTML_OUTLINE_SYSTEM_PROMPT`, `make_html_outline_tools`）。

**新的 `html_gen.py` 结构**（~40 行）：
```python
from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool
from backend.tools.report._block_renderer import render_outline
from backend.tools.report._outline_planner import plan_outline
from backend.tools.report._renderers.html import HtmlBlockRenderer
from backend.tools.report._theme import get_theme


@register_tool("tool_report_html", ...)
class HtmlReportTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        try:
            outline = await plan_outline(...)
            theme = get_theme(...)
            renderer = HtmlBlockRenderer(theme=theme)
            html = render_outline(outline, renderer)
            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="file",
                data=html,
                metadata={
                    "format": "html",
                    "title": outline.metadata.get("title", ""),
                    "chart_count": renderer.chart_count,
                    "mode": "deterministic",
                }
            )
        except Exception as e:
            logger.exception("HTML generation failed: %s", e)
            return self._fail(str(e))
```

### A2 — `docx_gen.py`

完全对称的改动。`_run_docx_agent()` 删除，改为 `render_outline(outline, renderer)`。
`mode` 从 `"llm_agent"` 改为 `"deterministic"`。

注意：`render_outline()` 返回 `bytes | str`。对 DOCX 是 `bytes`，对 HTML 是 `str`。和现有代码一致。

### A3 — `_agent_loop.py` 删除

**引用检查**：
```
backend/tools/report/_agent_loop.py
  ← html_gen.py  (将删除引用)
  ← docx_gen.py  (将删除引用)
  （无其他 caller）
```

删除前确认无其他引用：`grep -r "from backend.tools.report._agent_loop" backend/` 应只有 `html_gen.py` 和 `docx_gen.py`。

### A4 — `_html_tools.py` 删除

**引用检查**：
```
backend/tools/report/_html_tools.py
  ← html_gen.py  (将删除引用)
  （无其他 caller）
```

### A5 — `_docx_tools.py` 删除

**引用检查**：
```
backend/tools/report/_docx_tools.py
  ← docx_gen.py  (将删除引用)
  （无其他 caller）
```

### B1 — `execution.py` timeout profile

```python
# 旧
"report_gen":    (30, 120, 2.0),
# 新
"report_gen":    (60, 180, 2.5),
```

解释：P0 后 report_gen 实际耗时 = content_collection(<1s) + outline_planner(0-60s) + render_outline(<1s) ≈ 0-62s。新 profile 下 `estimated_seconds=60` → `clip(60*2.5, 60, 180) = 150s`，有近 90s buffer，即使 outline planner 跑满 60s 也足够。

### B2/B3 — `planning.py` planning hints

```python
# 旧（两处）
estimated_seconds: 30
# 新
estimated_seconds: 60
```

### B4 — JSON 模板

三个模板文件中 `"tool": "tool_report_html"` 的 `estimated_seconds` 从 `30` 改为 `60`：
- `throughput_analyst_monthly_review.json:465`
- `customer_insight_strategic_contribution.json:447`
- `asset_investment_equipment_ops.json:465`

### C1/C2 — 测试修正

在 `test_json_template_execution.py` 和 `test_json_template_execution_by_mock_llm.py` 中检查是否有对 `mode: "llm_agent"` 的断言，如有则改为 `"deterministic"`（或删除该断言）。

当前 `TestReportGenerationHTML.test_html_report_generation` 的断言不检查 mode，只检查 `output.status`, `output_type`, `metadata.format`, `data` 是 `str`，包含 `<html` 标签。所以**无需修改测试代码**。

### C3 — Contract 测试验证

`test_enhanced_baseline.py::test_html_enhanced_baseline` 直接调用 `HtmlBlockRenderer` + `render_outline`，已验证 outline 确定性渲染的正确性。方案 A1 本质是把这部分已验证的代码从测试环境搬到生产代码路径，风险极低。

---

## 3. 实施顺序

```
Step 1: A1 html_gen.py     — 切换为 render_outline
Step 2: A2 docx_gen.py     — 切换为 render_outline
Step 3: A3-A5 删除死代码    — _agent_loop.py, _html_tools.py, _docx_tools.py
Step 4: B1-B4 调整 timeout  — execution.py, planning.py, JSON 模板
Step 5: 运行 contract 测试  — pytest tests/contract/
Step 6: 运行场景测试       — pytest tests/scenarios/test_json_template_execution_by_mock_llm.py
Step 7: 若有环境，运行真实 LLM 测试 — pytest tests/scenarios/test_json_template_execution.py
```

---

## 4. 风险与回滚

| 风险 | 概率 | 缓解 |
|------|------|------|
| `render_outline` 与 agent loop 输出有 byte 级差异 | 低 | contract 测试已覆盖 `render_outline` + `HtmlBlockRenderer` 组合，golden file 对齐 |
| agent loop 在段落渲染中做了文本润色 | 低 | `emit_paragraph()` 仅做 HTML wrapping（`<div class="narrative">text</div>`），无文本改写 |
| DOCX renderer 有特殊行为需要 agent 驱动 | 低 | `DocxBlockRenderer` 的 emit 方法与 agent tools 调用的完全相同，无额外逻辑 |
| PPTX 也用了 agent loop | 否 | PPTX 无 agent 路径（`_pptx_tools.py` 已在 `a8f8aad` 删除） |

**回滚方案**：revert Step 1-3 的 commit，恢复 agent loop 路径。

---

## 5. 预期收益

| 指标 | 优化前 | 优化后 |
|------|--------|--------|
| HTML 报告生成耗时 | 90-960s (典型超时) | **3-62s**（取决于 outline planner） |
| DOCX 报告生成耗时 | 同上 | **3-62s** |
| 每份报告 LLM API 调用 | 20-50 次 | **1 次**（仅 outline planner） |
| 超时概率 | 几乎必然 | **< 1%** |
| 死代码行数 | 635 行 | 0 |
