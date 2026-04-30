# Sprint 2 闭环 + 视觉改造 完整实施方案

**前置依赖**：[spec/refactor_report_outline.md](./refactor_report_outline.md) Sprint 1-2 已交付（2026-04-29）
**目标读者**：Claude Code 执行实例（无本会话上下文）
**状态**：阶段 0 ✅ 已交付（2026-04-29）；阶段 1-6 待实施
**预计工时**：~20 人日（按单人）/ 2 人并行 ~10 周
**关键产品决策**：选项 C — 保留 PptxGenJS 原生可编辑图表能力（用户强需求）

---

## 交付状态

| 阶段 | 内容 | 完成日期 | 状态 |
|---|---|---|---|
| 0 | Sprint 2 收尾（PptxGenJS outline 化）— 4 端真正闭环 | 2026-04-29 | ✅ |
| 1 | Theme 系统化 | 2026-04-29 | ✅ |
| 2 | 数据表达核心（chart 渲染能力） | 2026-04-29 | ✅ |
| 3 | 版式与编排 | 2026-04-29 | ✅ |
| 4 | 信息层次与强调 | 2026-04-29 | ✅ |
| 5 | 视觉风格一致性 | 2026-04-29 | ✅ |
| 6 | 质量保障 | 2026-04-30 | ✅ |

**阶段 0 摘要（已交付）**：
- 新增 `_pptxgen_commands.py`（SlideCommand DSL，6 种 command type）
- 新增 `_renderers/pptxgen.py`（PptxGenJSBlockRenderer，第 5 个 BlockRenderer 实现）
- 新增 `_pptxgen_runtime.py`（Python ↔ Node subprocess helper）
- 新增 `pptxgen_executor.js`（长期常驻 Node 脚本，替代旧 `generate_pptxgen_script` 临时 JS 字符串生成）
- `_pptxgen_builder.py` 从 936 → 217 行（删除 `_ScriptBuilder` / `generate_pptxgen_script` / `render_to_pptx`）
- `pptx_gen.py` 双路径消除：单一 `outline → renderer 选择 → render_outline` 流，回退能力下沉到 renderer 选择层
- 新增测试 45 项（25 SlideCommand + 13 PptxGenJSBlockRenderer + 7 Node 桥接集成）
- 全套 contract 测试 276 PASSED 零回归

---

## 0. Mission

本方案合并两件事：

1. **完成 Sprint 1-2 的最后 0.5 端**：PPT 的 PptxGenJS 桥接当前仍走 ReportContent 旧管道（Sprint 1-2 为控制 scope 的妥协）。让它也吃 outline，4 端真正 100% outline 化。
2. **在统一架构上做视觉改造**：对标 SOP 沙箱产出（Claude 在沙箱里基于同一份 JSON 生成的 12 页 PPT + 4 节 DOCX），把"结构正确但视觉够用"提升到"专业级数据分析报告"。

**关键差距**（来自 SOP 对比）：

| 差距项 | 当前 | 目标 |
|---|---|---|
| PPT 架构 | 双路径（PptxGenJS 走 ReportContent / fallback 走 outline）| 单一管道（统一吃 outline，回退在 renderer 层）|
| DOCX 图表 | 仅渲染数据表 | 嵌入原生图片（matplotlib 渲染）|
| PPT 图表 | 仅 BAR / LINE | + DOUGHNUT / PIE / 横向条形 / BAR+LINE 组合 |
| 章节切换 | 仅 H1 + page break | 深色背景大标题封面页 |
| 强调样式 | 普通段落 | Callout 框（warn / info）+ 表格高亮 |
| 建议章节 | 段落堆叠 | 短期/中期/长期三栏 grid |
| 主题系统 | module 全局常量 | Theme dataclass（基础设施，未来易扩展）|
| 视觉质量保障 | 仅结构等价测试 | + perceptual hash 视觉回归 |

---

## 1. 全景图（7 个阶段）

```
[阶段 0]  Sprint 2 收尾 — PptxGenJS outline 化       ← 必须先做完
   │     (产品决策保留原生图表;此为 Sprint 1-2 收尾)
   ▼
[阶段 1]  Theme 系统化                               ← 视觉前置基建
   │
   ▼
[阶段 2]  数据表达核心 (chart 渲染能力)
   │
   ▼
[阶段 3]  版式与编排 (结构感)
   │
   ▼
[阶段 4]  信息层次与强调 (重点突出)
   │
   ▼
[阶段 5]  视觉风格一致性 (整体打磨)
   │
   ▼
[阶段 6]  质量保障 (守护成果)
```

每个阶段是「**前一阶段完成才能闭环**」的逻辑单元；阶段内子项按依赖关系排，不按工时排。

---

## 2. Non-goals（明确不做）

- ❌ **不再考虑选项 D（放弃 PptxGenJS）** —— 已决策选 C（保留原生可编辑图表）
- ❌ **不改 BlockRenderer 协议** —— 仅扩展实现，新增 1 个 PptxGenJSBlockRenderer
- ❌ **不做主题切换功能** —— 阶段 1 抽象 Theme dataclass，但只交付 1 套精致 corporate-blue preset；多主题留待产品需求驱动
- ❌ **不做暗色模式（除 HTML 外）** —— DOCX/PPT 客户端不支持
- ❌ **不追求跨平台像素一致** —— 接受不同客户端合理差异，靠 spot check 矩阵记录
- ❌ **不为 Markdown 端做"专业视觉"** —— 它是机器可读中间格式，所有视觉项做"降级一致"即可

---

## 3. 与 Sprint 1-2 的关系

### 3.1 Sprint 1-2 是 3.5 端架构升级，不是 4 端

```
Sprint 1-2 (已交付):
  ✅ Markdown / DOCX / HTML / PPT-fallback   → 3.5 端 outline 化
  ⚠️ PPT-PptxGenJS                          → 留作债务

阶段 0 (本方案):
  📌 PPT-PptxGenJS                          → 让最后 0.5 端也吃 outline
```

阶段 0 不是"视觉改造前置"，是 **Sprint 1-2 的真正最后一步**。

### 3.2 已埋的扩展点（启用，不重写）

| Sprint 1-2 资产 | 阶段启用 |
|---|---|
| `SectionCoverBlock` dataclass | 3.1 |
| `ParagraphBlock.style: callout-warn / callout-info` | 4.1 |
| `ComparisonGridBlock` 4 端基本实现 | 3.2 |
| `ChartTablePairBlock` dataclass | 3.3 |
| `BlockRenderer` 协议 + `BlockRendererBase` | 全程 |
| `_planner_prompts.py` LLM 决策规则 | 全程（每阶段子项内调优）|
| `_outline.py` 数据模型 | 阶段 0 序列化为 JSON 喂 Node |

### 3.3 新增的扩展点

| 新模块 | 阶段引入 |
|---|---|
| `_pptgen_commands.py`（SlideCommand DSL）| 0 |
| `_renderers/pptxgen.py`（PptxGenJSBlockRenderer）| 0 |
| `pptxgen_executor.js`（Node 长期常驻脚本）| 0 |
| `Theme` dataclass（`_theme.py` 重构）| 1 |
| `_chart_renderer.py`（4 端共享渲染策略）| 2.1 |
| `TableBlock.highlight_rules` 字段扩展 | 4.2 |
| `_components.py`（跨端视觉契约）| 5.1 |

---

## 4. 阶段 0 · Sprint 2 收尾（PptxGenJS outline 化）

> 这是 Sprint 1-2 的真正最后一步。完成后，4 端架构升级才**真正闭环**。

### 4.1 设计原则

1. **BlockRenderer 协议保持不变** —— 新增 `PptxGenJSBlockRenderer` 作为第 5 个实现
2. **Python 端拥有所有版式决策权** —— 与其他 3 端对称
3. **Node 端只做渲染执行** —— 简化 JS 代码，提升扩展性
4. **数据通信用 JSON** —— Python `outline → SlideCommand[] → stdin → Node`

### 4.2 三层架构

```
[Python]
  plan_outline(...)  →  ReportOutline
        ↓
  PptxGenJSBlockRenderer (新增,实现 BlockRenderer 协议)
        ↓ emit_* 12 个方法,每个产出 SlideCommand
  [SlideCommand, SlideCommand, ...]
        ↓ JSON 序列化
        ↓ stdin

[Node executor (重写)]
  读 stdin JSON
        ↓ 遍历 SlideCommand
  pptxgenjs API 调用 (slide.addChart / addText / addTable / addShape)
        ↓
  pres.write() → .pptx bytes
        ↓ stdout

[Python]
  接收 bytes → ToolOutput
```

### 4.3 SlideCommand DSL

新增 `backend/tools/report/_pptxgen_commands.py`：

```python
@dataclass
class NewSlide:
    type: Literal["new_slide"] = "new_slide"
    background: str | None = None  # 6 位 hex,无 #

@dataclass
class AddText:
    type: Literal["add_text"] = "add_text"
    x: float; y: float; w: float; h: float
    text: str
    font_size: int = 12
    bold: bool = False
    color: str = "000000"
    font_name: str | None = None
    alignment: Literal["left", "center", "right"] = "left"

@dataclass
class AddChart:
    type: Literal["add_chart"] = "add_chart"
    x: float; y: float; w: float; h: float
    chart_type: Literal["BAR", "LINE", "PIE", "DOUGHNUT"]
    data: list[dict]
    options: dict

@dataclass
class AddTable:
    type: Literal["add_table"] = "add_table"
    x: float; y: float; w: float; h: float
    rows: list[list[dict]]  # 每个 cell {text, fill?, color?, bold?}
    options: dict

@dataclass
class AddShape:
    type: Literal["add_shape"] = "add_shape"
    x: float; y: float; w: float; h: float
    shape: Literal["rect", "rounded_rect", "ellipse"]
    fill: str
    line_color: str | None = None

@dataclass
class AddImage:
    type: Literal["add_image"] = "add_image"
    x: float; y: float; w: float; h: float
    data_uri: str  # base64 PNG / SVG

SlideCommand = Union[NewSlide, AddText, AddChart, AddTable, AddShape, AddImage]
```

每个 type 对应 pptxgenjs 一个 API 调用，扩展新能力只需加新 type。

### 4.4 实施 Step 详解

#### Step 0.1 · SlideCommand schema [1d]

- 新增 `_pptxgen_commands.py`
- 6 种 command type dataclass + JSON schema
- 提供 `serialize_commands(cmds: list) -> str` helper

#### Step 0.2 · PptxGenJSBlockRenderer [3d]

- 新增 `backend/tools/report/_renderers/pptxgen.py`
- 实现 BlockRenderer 协议 12 个方法
- 每个 emit_* 转为 SlideCommand 序列：
  - `begin_document`：append `NewSlide`(cover) + `AddText`×3 (title/author/date)
  - `emit_chart`：调 `echarts_to_pptxgen()` → `AddChart`
  - `emit_table`：`AddTable`（pptxgenjs 原生表格）
  - `emit_kpi_row`：N 个 `AddShape`(rounded_rect) + `AddText`×3
  - `emit_paragraph`：`AddText`
  - `emit_section_cover`：`NewSlide`(深色) + `AddText`(章节号) + `AddText`(标题)
  - `emit_comparison_grid`：`NewSlide` + N 个 `AddShape` + `AddText`
  - 其他类似
- `end_document`：JSON 序列化 commands → 调用 Node executor → 接 stdout bytes
- 复用：`_pptxgen_builder.echarts_to_pptxgen` 已支持 BAR/LINE 转换，保留

#### Step 0.3 · Node executor 重写 [2d]

- 重写 `backend/tools/report/pptxgen_executor.js`（替代当前 `generate_pptxgen_script` 的临时 JS 字符串生成）
- 长期常驻脚本：
  ```javascript
  const pptxgen = require("pptxgenjs");
  const fs = require("fs");
  const commands = JSON.parse(fs.readFileSync(0, "utf8"));
  const pres = new pptxgen();
  pres.layout = "LAYOUT_WIDE";
  let currentSlide = null;
  for (const cmd of commands) {
      switch (cmd.type) {
          case "new_slide":
              currentSlide = pres.addSlide();
              if (cmd.background) {
                  currentSlide.background = { fill: cmd.background };
              }
              break;
          case "add_text":
              currentSlide.addText(cmd.text, {
                  x: cmd.x, y: cmd.y, w: cmd.w, h: cmd.h,
                  fontSize: cmd.font_size, bold: cmd.bold,
                  color: cmd.color, fontFace: cmd.font_name,
                  align: cmd.alignment,
              });
              break;
          case "add_chart":
              currentSlide.addChart(cmd.chart_type, cmd.data, cmd.options);
              break;
          // ... 其他 case
      }
  }
  pres.write({ outputType: "nodebuffer" }).then(buf => process.stdout.write(buf));
  ```

- 简单稳定，能力扩展只需加 case
- Python 端用 `subprocess.run(["node", "pptxgen_executor.js"], input=cmds_json, capture_output=True)`

#### Step 0.4 · pptx_gen.py 双路径消除 [0.5d]

```python
# Before (Sprint 1-2 残留):
if check_pptxgen_available():
    rc = collect_and_associate(...)        # 旧管道
    rc.kpi_cards = await extract_kpis_llm(...)
    pptx_bytes = render_to_pptx(rc)
else:
    outline = await plan_outline(...)
    renderer = PptxBlockRenderer()
    render_outline(outline, renderer)
    pptx_bytes = renderer.end_document()

# After (阶段 0 完成):
outline = await plan_outline(...)
if check_pptxgen_available():
    renderer = PptxGenJSBlockRenderer()    # 走 Node 桥接 → 原生图表
else:
    renderer = PptxBlockRenderer()         # 走 python-pptx 兜底
render_outline(outline, renderer)
pptx_bytes = renderer.end_document()
```

回退能力下沉到 renderer 选择层；管道层不再分裂。

#### Step 0.5 · 删除旧代码 [0.5d]

- `_pptxgen_builder.py`：
  - 删 `generate_pptxgen_script(report: ReportContent, ...)`
  - 删 `render_to_pptx(report: ReportContent)`
  - 保留 `echarts_to_pptxgen()`（被 PptxGenJSBlockRenderer 复用）
  - 保留 `check_pptxgen_available()`
- `pptx_gen.py`：删 `from backend.tools.report._content_collector import collect_and_associate` 等旧 import

#### Step 0.6 · 测试 [1.5d]

新增：
- `tests/contract/test_pptxgen_block_renderer.py`：PptxGenJSBlockRenderer 单元测试
  - 输入 fixture outline → 验证 SlideCommand JSON 结构
  - 不依赖真实 Node（mock 桥接调用）
- `tests/integration/test_pptxgen_node_bridge.py`：Node 桥接集成测试
  - mark `slow`（仅 Node 环境跑）
  - 真实 Node + npm 跑通完整流程，验证 .pptx 字节合法

更新：
- 现有 `test_pptx_baseline` 保持走 python-pptx fallback（CI 不依赖 Node）
- 新增 `test_pptx_pptxgen_baseline`（mark `slow`），守护 PptxGenJS 路径输出

#### Step 0.7 · 文档更新 [0.5d]

- [spec/refactor_report_outline.md](./refactor_report_outline.md) 第 0 节"交付状态"加 ✅ Step 11（Sprint 2 收尾）
- 修订原 Step 5 注释："PptxGenJS 桥接已迁移至 outline 管道"
- PPT 端架构表更新：100% outline 化

### 4.5 阶段 0 完成标志

- [ ] 4 端 100% outline 化（PPT 双路径消除）
- [ ] PptxGenJSBlockRenderer 实现 BlockRenderer 协议 12 个方法
- [ ] Node executor 长期常驻脚本就位
- [ ] PPT baseline（fallback 路径）保持等价
- [ ] PPT PptxGenJS 路径有独立 baseline（`slow` 标签）

---

## 5. 阶段 1 · Theme 系统化（视觉前置基建）

唯一一项基建：`_theme.py` 重构为 `Theme` dataclass，4 端 renderer 注入 theme 参数。**不做主题切换功能**，但抽象层让未来增主题是低成本工作。

### 5.1 实施动作

```python
# backend/tools/report/_theme.py (重构)

@dataclass(frozen=True)
class Theme:
    name: str
    # 颜色 (RGB tuple)
    PRIMARY: tuple[int, int, int]
    SECONDARY: tuple[int, int, int]
    ACCENT: tuple[int, int, int]
    POSITIVE: tuple[int, int, int]
    NEGATIVE: tuple[int, int, int]
    NEUTRAL: tuple[int, int, int]
    BG_LIGHT: tuple[int, int, int]
    TEXT_DARK: tuple[int, int, int]
    # 字体
    FONT_CN: str
    FONT_NUM: str
    # 尺寸
    SIZE_TITLE: int
    SIZE_H1: int
    SIZE_BODY: int
    SIZE_TABLE_HEADER: int
    SIZE_TABLE_BODY: int
    SIZE_SMALL: int
    # 视觉项扩展(阶段 4-5 会用到)
    chart_colors: tuple[str, ...]
    callout_warn_bg: tuple[int, int, int]
    callout_warn_border: tuple[int, int, int]
    callout_info_bg: tuple[int, int, int]
    callout_info_border: tuple[int, int, int]
    cover_bg: tuple[int, int, int]
    cover_text: tuple[int, int, int]
    radius_card: int
    radius_callout: int
    shadow_strength: float
    # 派生(常用)
    PRIMARY_HEX: str  # 6 位 hex,无 #
    # ...

THEMES: dict[str, Theme] = {
    "corporate-blue": Theme(
        name="corporate-blue",
        PRIMARY=(0x1E, 0x3A, 0x5F),
        # ... 与当前默认完全一致
    ),
}

def get_theme(name: str = "corporate-blue") -> Theme:
    return THEMES.get(name, THEMES["corporate-blue"])

# 向后兼容: 模块级常量重新导出 corporate-blue 字段
_default = THEMES["corporate-blue"]
PRIMARY = _default.PRIMARY
SECONDARY = _default.SECONDARY
# ... 所有现有 from _theme import T; T.PRIMARY 用法零改动
```

### 5.2 4 端 renderer 接 theme

```python
class BlockRendererBase:
    def __init__(self, theme: Theme | None = None):
        self._theme = theme or get_theme("corporate-blue")
```

4 端 renderer 内部用 `self._theme.PRIMARY` 替代 `T.PRIMARY`（逐步替换，新视觉项强制用 theme，旧 builder 暂保留模块常量）。

### 5.3 *_gen.py 接 theme

```python
theme_name = inp.params.get("report_metadata", {}).get("theme", "corporate-blue")
theme = get_theme(theme_name)
renderer = DocxBlockRenderer(theme=theme)
```

### 5.4 测试

- 单测：`get_theme("corporate-blue")` 返回对象，所有字段非 None
- 单测：`get_theme("unknown")` 降级到 corporate-blue
- baseline 测试：4 端 normal fixture 仍 byte-equivalent（向后兼容验证）

### 5.5 阶段 1 完成标志

- [ ] `_theme.py` 重构为 dataclass + 1 套 corporate-blue preset
- [ ] 4 端 renderer 接 theme 参数（默认 corporate-blue）
- [ ] 模块级常量保留向后兼容
- [ ] `report_metadata.theme` 通道打通
- [ ] 所有现有 baseline 测试通过

---

## 6. 阶段 2 · 数据表达核心

### 6.1 子项 2.1 · Chart renderer 抽象层 [2d]

新增 `backend/tools/report/_chart_renderer.py`：

```python
def render_chart_to_png(option: dict, theme: Theme,
                       width_inch: float = 6.0,
                       height_inch: float = 3.5,
                       dpi: int = 150) -> bytes | None:
    """matplotlib 路径 — DOCX 嵌图。返回 None 表示不支持。"""

def echarts_to_pptxgen_v2(option: dict, theme: Theme) -> dict | None:
    """已存在(_pptxgen_builder),迁移到此模块统一管理"""

def echarts_to_html(option: dict, container_id: str) -> str:
    """ECharts 初始化 JS — for HTML(已存在,迁移)"""

def echarts_to_data_table(option: dict) -> dict | None:
    """提取 chart 数据为表格行(降级 fallback,4 端复用)"""
```

4 端 renderer 的 emit_chart 都从这个模块取渲染策略。

### 6.2 子项 2.2 · DOCX 嵌入原生图表 [3d]

```python
# _renderers/docx.py
def emit_chart(self, block, asset):
    option = getattr(asset, "option", None)
    if not isinstance(option, dict):
        return
    png_bytes = render_chart_to_png(option, self._theme)
    if png_bytes:
        self._doc.add_picture(io.BytesIO(png_bytes), width=Inches(6.0))
        if block.caption:
            p = self._doc.add_paragraph(block.caption)
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    else:
        # 降级数据表
        E.build_chart_data_table(self._doc, option)
```

支持 chart_type：BAR / LINE / PIE / HORIZONTAL_BAR / COMBO（BAR+LINE）。

**依赖**：
- pip 加 `matplotlib >= 3.7`
- Dockerfile 加 `apt-get install fonts-noto-cjk`
- matplotlib 顶部 `rcParams['font.sans-serif'] = ['SimHei', 'Noto Sans CJK SC']`

### 6.3 子项 2.3 · PPT 多图表类型 [1.5d]

`echarts_to_pptxgen_v2` 扩展（在阶段 0 已迁移到 `_chart_renderer.py`）：

```python
_TYPE_MAP = {
    "bar": "BAR",
    "line": "LINE",
    "pie": "PIE",            # 新增
    "doughnut": "DOUGHNUT",  # 新增
}
```

PIE / DOUGHNUT：`series[0].data` 是 `[{name, value}]` 形态。
横向条形：已支持（`yAxis.type == "category"`），加测试覆盖。
组合图：series 含多种 type 时返回多 chart spec。

PptxGenJSBlockRenderer.emit_chart 直接复用，输出 `AddChart` SlideCommand。

### 6.4 子项 2.4 · 4 端 chart_type 能力矩阵 [0.5d]

落盘 `spec/chart_capability_matrix.md`：

| chart_type | DOCX | PPT (PptxGenJS) | PPT (python-pptx) | HTML | Markdown |
|---|---|---|---|---|---|
| BAR | ✅ matplotlib | ✅ 原生 | 数据表 | ✅ ECharts | 数据表 |
| LINE | ✅ matplotlib | ✅ 原生 | 数据表 | ✅ ECharts | 数据表 |
| PIE | ✅ matplotlib | ✅ 原生（2.3 新增）| 数据表 | ✅ ECharts | 数据表 |
| DOUGHNUT | ✅ matplotlib | ✅ 原生（2.3 新增）| 数据表 | ✅ ECharts | 数据表 |
| H_BAR | ✅ matplotlib | ✅ 原生 | 数据表 | ✅ ECharts | 数据表 |
| COMBO | ✅ matplotlib | ✅ 原生 | 数据表 | ✅ ECharts | 数据表 |
| WATERFALL | 数据表 | 数据表 | 数据表 | ✅ ECharts | 数据表 |
| RADAR / SCATTER | TBD | TBD | 数据表 | ✅ ECharts | 数据表 |

降级一致性：所有"不支持"位置都有数据表 fallback，不会失败。

### 6.5 子项 2.5 · HTML ECharts 交互优化 [0.5d]

- `<div class="chart-container">` 加 `data-chart-type` 属性，CSS 按 chart type 调高度
- ECharts init 加 `tooltip.trigger: "axis"` 默认开启
- 加 `window.addEventListener("resize", ...)` 让图表响应 viewport
- 不破坏现有 baseline（只增不删）

### 6.6 阶段 2 完成标志

- [ ] `_chart_renderer.py` 抽象层就位，4 端共用
- [ ] DOCX 嵌入 BAR/LINE/PIE/H_BAR/COMBO 5 种 PNG 图表
- [ ] PPT PptxGenJS 路径支持 BAR/LINE/PIE/DOUGHNUT/H_BAR/COMBO 6 种原生图表
- [ ] HTML 图表加 tooltip + resize
- [ ] 4 端 chart_type 能力矩阵文档化

---

## 7. 阶段 3 · 版式与编排（结构感）

### 7.1 子项 3.1 · 章节分节封面页 [2d]

启用 `SectionCoverBlock`：

1. **legacy 转换器**：每个非 appendix section 头部插入 `SectionCoverBlock(index, title, subtitle="")`
2. **LLM planner prompt 增强**：建议在 section.role ∈ {status, analysis} 时插 cover；摘要 / appendix 不插
3. **4 端 emit_section_cover**：
   - DOCX：单页深色填充段落 + 大字 + 分页符
   - PPT (PptxGenJS)：`NewSlide(background=theme.cover_bg)` + `AddText(title)` 命令
   - PPT (python-pptx)：替换现有 `build_section_divider_slide` 内联实现
   - HTML：`<div class="section-cover">` + CSS 深色背景
   - Markdown：no-op

**关键风险**：当前 `PptxBlockRenderer.begin_section` 已调 `S.build_section_divider_slide`。改造时把 divider 调用挪到 emit_section_cover；legacy 转换器**始终**插入 SectionCoverBlock 保证向后兼容。

### 7.2 子项 3.2 · 三栏建议 grid [1d]

升级现有 ComparisonGridBlock 4 端实现到"专业版"：
- DOCX：N 列卡片表格（每列底色 + 标题色块 + bullet）
- PPT (PptxGenJS)：独立 slide，N 个 `AddShape(rounded_rect)` + `AddText`
- PPT (python-pptx)：新增 `_pptx_slides.build_comparison_grid_slide`
- HTML：CSS Grid，每列等宽，hover 阴影
- Markdown：保持当前 `**列名**\n- item` 列表

### 7.3 子项 3.3 · chart_table_pair 并排版式 [1.5d]

启用 `ChartTablePairBlock` 真正的并排：
- DOCX：双列表格（左 chart 占位 + 右 stats table）
- PPT：单 slide 左右 6:4 布局
- HTML：CSS flex 双列
- Markdown：保持顺序输出（无并排能力）

### 7.4 子项 3.4 · 归因汇总表 [1d]

LLM planner prompt 加规则：`role=attribution` 时合成「问题 / 数据 / 原因 / 影响 / 责任」5 列表格 → `TableBlock` + 特殊 StatsAsset。

renderer 端：表格按列宽自适应，关键列（"原因"）加底色，配 4.2 高亮规则。

### 7.5 子项 3.5 · KPI overview 现代化 [1d]

提取 `_pptx_slides.build_kpi_overview_slide` 函数（替代当前 PptxBlockRenderer 内联实现），改进：
- 圆角卡片（`MSO_SHAPE.ROUNDED_RECTANGLE`）
- 阴影（pptxgenjs 路径用 `shadow: {opacity: 0.3}`）
- theme 配色对齐
- 4 端 KPI overview 视觉契约统一

### 7.6 子项 3.6 · TOP-N 排名版式 [1d]

新增视觉项：
- 横向条形图（chart_type=H_BAR + showValue=true）
- 表格第一行加金/银/铜色标记（`highlight_rules: [{"rank": 1, "color": "gold"}]`）
- LLM planner 在数据有"排名"语义时（任务名含 top/排名/前 N）触发该版式

### 7.7 阶段 3 完成标志

- [ ] 4 端 SectionCoverBlock 真正实现（替代当前 fallback）
- [ ] 4 端 ComparisonGridBlock 升级到专业版
- [ ] 4 端 chart_table_pair 真并排版式
- [ ] attribution role 自动合成 5 列归因表
- [ ] KPI overview 4 端视觉契约统一
- [ ] TOP-N 排名版式可用

---

## 8. 阶段 4 · 信息层次与强调

### 8.1 子项 4.1 · Callout 强调框 [2d]

启用 `ParagraphBlock.style: callout-warn / callout-info`：

1. **转换器关键词检测**（fallback）：`text` 含「风险/预警/未达成」→ callout-warn；含「提示/注意」→ callout-info
2. **LLM planner prompt 增强**：明确 callout style 决策规则
3. **4 端 emit_paragraph 检测 style 分支**：
   - DOCX：新增 `build_callout(doc, text, level)`（左边框 + 浅色填充）
   - PPT：`AddShape(rounded_rect, fill=theme.callout_*_bg)` + `AddText` 命令
   - HTML：`<div class="callout warn">` + CSS
   - Markdown：`> ⚠️ **注意**：{text}` blockquote

**注意**：PptxBlockRenderer 是 buffer 模式，`emit_paragraph` 需保留 style 信息（buffer 项从 `text: str` 改为 `(text, style)` tuple）。

### 8.2 子项 4.2 · 表格行/列高亮 [1.5d]

数据模型扩展（**新增字段，不新增 Block kind**）：

```python
@dataclass
class TableBlock:
    block_id: str
    asset_id: str
    caption: str = ""
    highlight_rules: list[dict] = field(default_factory=list)
    # 示例: [{"col": "rate", "predicate": "< 0.5", "color": "negative"}]
    #       [{"row": 0, "color": "gold"}]   # 排名第一
```

renderer 应用规则给单元格 / 行上色。LLM planner 在 attribution / status 章节有阈值数据时输出。

### 8.3 子项 4.3 · 趋势箭头与色彩 [1d]

统一 4 端规则到 theme：

```python
TREND_TOKENS = {
    "positive": {"arrow": "↑", "color_attr": "POSITIVE"},
    "negative": {"arrow": "↓", "color_attr": "NEGATIVE"},
    "flat":     {"arrow": "→", "color_attr": "NEUTRAL"},
}
```

应用点：
- KPI 卡 trend 字段
- 增长率 yoy/mom 数字
- 表格内 highlight_rules 触发时

### 8.4 子项 4.4 · 数据标签 [0.5d]

ChartAsset.option 内的 `series[].label.show` 自动设为 true（条件：单系列 + 类型为 BAR/H_BAR）；在 `_chart_renderer.py` 转换时映射为对应参数。

### 8.5 子项 4.5 · 风险预警框 [0.5d]

`ParagraphBlock(style="callout-warn")` 视觉强化：
- DOCX/HTML/PPT 加图标占位（`⚠️` emoji 或 SVG）
- 文字加粗
- 触发条件：LLM planner 检测到「未达成 / 下降 N% / 风险」类内容

### 8.6 阶段 4 完成标志

- [ ] 4 端 callout-warn / callout-info 视觉差异化
- [ ] 表格 highlight_rules 字段就位 + 4 端实现
- [ ] 趋势 token 统一，4 端规则一致
- [ ] 单系列 BAR/H_BAR 自动加数据标签

---

## 9. 阶段 5 · 视觉风格一致性

### 9.1 子项 5.1 · 组件库化 [2d]

新增 `backend/tools/report/_components.py`：

```python
@dataclass
class KpiCardSpec:
    """跨端 KPI 卡视觉契约"""
    width_ratio: float = 0.25  # 4 列时各占 25%
    label_size_ratio: float = 0.4  # 相对 value 字号
    accent_position: Literal["top", "left"] = "left"
    has_shadow: bool = True
    radius: int = 8  # 圆角
    padding: int = 16
```

定义 4 个组件：KpiCard / Callout / SectionCover / GridColumn。

4 端 emit_* 都按同一份 spec 实现，未来调整一处而非 4 处。

### 9.2 子项 5.2 · 字体分离与排版 [1d]

明确规则：
- 中文：theme.FONT_CN（默认"微软雅黑" / "苹方"）
- 数字：theme.FONT_NUM（等宽，"Source Code Pro" / "JetBrains Mono"）
- 标题：theme.FONT_CN bold

4 端在表格数字 / KPI 数字 / 增长率数字处统一用 FONT_NUM。

### 9.3 子项 5.3 · Theme preset 完整化 [1d]

Theme 不只颜色，含：
- `radius_card` / `radius_callout` / `radius_button`
- `shadow_strength`（0-1）
- `border_weight`
- `padding_card`

但**不做多 preset**：仍只有 corporate-blue 一套，但所有视觉项都从 theme 读这些字段。

### 9.4 子项 5.4 · 暗色模式探索（HTML）[1d]

- HTML 加 `prefers-color-scheme: dark` 媒体查询
- theme 字段加 `dark_mode: bool = False`，dark 时反转 PRIMARY / TEXT_DARK / BG_LIGHT
- 不阻塞，仅 HTML 端做（DOCX/PPT 用户的客户端不支持）

### 9.5 子项 5.5 · 跨主题视觉断言 [0.5d]

新增测试：
- 同一份 outline + 同一 theme → 输出 byte-equivalent
- 同一份 outline + 不同 theme（未来加 preset 时）→ 颜色字符串差异，骨架一致

### 9.6 阶段 5 完成标志

- [ ] 4 端 4 个组件视觉契约一致
- [ ] 字体分离规则全局应用
- [ ] Theme dataclass 含完整字段（不只颜色）
- [ ] HTML 暗色模式可切换

---

## 10. 阶段 6 · 质量保障

### 10.1 子项 6.1 · Enhanced visual fixture [1d]

新建 `tests/fixtures/report_baseline/enhanced/`：
- 输入数据触发所有新视觉项（含 callout 关键词、recommendation section、多 chart type、attribution 表、TOP-N）
- 4 端 golden（含 PptxGenJS 路径的 .pptx）

### 10.2 子项 6.2 · Perceptual hash 视觉回归 [1.5d]

新增 `tests/visual/test_report_visual.py`：
- 工具链：LibreOffice → PDF → pdftoppm → imagehash phash
- 阈值 ≤ 5 hash distance（imagehash 标准）
- mark `slow`，仅 visual: label PR 触发

### 10.3 子项 6.3 · 跨平台 spot check 矩阵 [0.5d]

落盘 `spec/visual_compatibility_matrix.md`：

| 客户端 | normal fixture | enhanced fixture | 已知差异 |
|---|---|---|---|
| Word macOS 16.x | ✅ | ✅ | — |
| Word Windows 16.x | ✅ | ✅ | 表格列宽 1px 偏差 |
| PowerPoint macOS 16.x | ✅ | ✅ | — |
| PowerPoint Windows 16.x | ✅ | ✅ | — |
| Chrome | ✅ | ✅ | — |
| Safari | ✅ | ✅ | callout 阴影渲染稍弱 |
| Firefox | ✅ | ✅ | — |

每次重大视觉改动跑一遍，更新此矩阵。

### 10.4 子项 6.4 · LLM planner 视觉验收 [1d]

`test_outline_planner_visual.py`：mock LLM 输出含新视觉项（callout / grid / cover / highlight），验证 4 端正确渲染。

### 10.5 子项 6.5 · 视觉回归 CI 集成 [0.5d]

- 主 PR：跑结构 baseline（不阻塞）
- visual: label PR：跑 perceptual hash + spot check 报告
- nightly：跑完整 visual matrix，发 Slack 报告

### 10.6 子项 6.6 · 性能预算 [0.5d]

`test_perf_budget.py`：
- 报告生成总耗时 ≤ baseline 的 1.5 倍（含嵌图 + LLM）
- DOCX size ≤ 200KB（normal fixture）
- PPT size ≤ 1MB（含原生图表）
- 超出报警，不直接 fail

### 10.7 阶段 6 完成标志（2026-04-30 ✅）

- [x] enhanced visual fixture 4 端 golden 就位 — `tests/fixtures/report_baseline/enhanced/` + `tests/contract/test_enhanced_baseline.py`
- [x] perceptual hash 视觉回归落地 — `tests/visual/test_report_visual.py`（slow，依赖 LibreOffice + poppler-utils + Pillow + imagehash；deps 缺失时 graceful skip）
- [x] 跨平台 spot check 矩阵文档化 — [`spec/visual_compatibility_matrix.md`](./visual_compatibility_matrix.md)
- [x] LLM planner 视觉验收测试通过 — `tests/contract/test_outline_planner_visual.py`（10 PASSED，含 section_cover 拒绝 / highlight_rules 静默丢弃 gap 守卫）
- [x] CI 集成 + 性能预算就位 — `.github/workflows/visual_regression.yml` + `tests/contract/test_perf_budget.py`

---

## 11. 实施时序与依赖

```
Week 1-2:  阶段 0 (Sprint 2 收尾)             ←  PPT outline 化,4 端真正闭环
Week 3:    阶段 1 (Theme)                     ←  视觉前置基建
Week 3-5:  阶段 2 (数据表达核心)              ←  Chart 能力 + 嵌图
Week 5-7:  阶段 3 (版式与编排)                ←  专业版式
Week 7-8:  阶段 4 (信息层次与强调)            ←  视觉标记
Week 8-9:  阶段 5 (视觉风格一致性)            ←  整体打磨
Week 9-10: 阶段 6 (质量保障)                  ←  回归网

并行可能性:
  - 阶段 2.5 (HTML ECharts 优化) 可与 2.2/2.3 并行
  - 阶段 3.6 (TOP-N) 依赖 4.2 (highlight_rules),可顺延
  - 阶段 5.4 (暗色模式) 可延后到所有完成后再做
  - 阶段 6 各子项与阶段 3-5 可重叠（边做视觉边补回归）

总工时:
  - 单人净工作量 ~20 人日
  - 2 人协作约 10 周(含评审/spot check 缓冲)
```

---

## 12. 测试策略汇总

| 测试类型 | 文件 / 位置 | 守卫什么 |
|---|---|---|
| 现有结构 baseline | `test_report_outputs_baseline.py` (4 项) | 4 端 normal fixture byte-equivalent |
| Outline 模型 | `test_outline_model.py` (18 项) | dataclass + JSON + ID minting |
| Renderer 协议 | `test_block_renderer_protocol.py` (20 项) | dispatch 全覆盖 |
| PptxGenJS 约束 | `test_pptxgen_constraints.py` (13 项) | 颜色无 # / 无 chartTitle / 无 8 位 hex |
| Outline planner | `test_outline_planner_*.py` (15 项) | LLM 路径 + fallback |
| **新增**: PptxGenJSBlockRenderer | `test_pptxgen_block_renderer.py` | 阶段 0 — outline → SlideCommand 正确性 |
| **新增**: Node 桥接集成 | `test_pptxgen_node_bridge.py` (slow) | 阶段 0 — 真实 Node 跑通 |
| **新增**: Chart renderer | `test_chart_renderer.py` | 阶段 2 — 4 端 chart 渲染正确 |
| **新增**: Enhanced baseline | `test_enhanced_baseline.py` | 阶段 6 — 4 端 + 新视觉项 |
| **新增**: 视觉回归 | `tests/visual/test_report_visual.py` (slow) | 阶段 6 — perceptual hash |
| **新增**: LLM 视觉验收 | `test_outline_planner_visual.py` | 阶段 6 — LLM 输出驱动新视觉 |
| **新增**: 性能预算 | `test_perf_budget.py` | 阶段 6 — 耗时 + 文件大小阈值 |

---

## 13. 风险登记 + 回滚

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| 阶段 0 Node 脚本重写工作量大 | 高 | 中 | 拆解为最小可用版本（仅 cover + chart）+ 逐步加 cmd type |
| matplotlib 中文字体在 CI 不可用 | 高 | 中 | Dockerfile 加 fonts-noto-cjk + spot check 字体可用性 |
| LibreOffice 渲染与原生客户端不一致 | 高 | 低 | 视觉回归阈值放宽 + 主回归用结构等价 |
| Theme 重构破坏底层 builder 现有引用 | 中 | 高 | 模块级常量保留为 corporate-blue 默认值（向后兼容）|
| LLM planner prompt 累积过长导致超 token | 中 | 中 | 阶段 1-6 完成后做一次 prompt 压缩 + few-shot 提取 |
| PPT enhanced fixture 跨平台差异 | 高 | 低 | spot check 矩阵做记录而非 CI 阻塞 |
| 性能预算超出 | 中 | 中 | 矩阵化测各阶段耗时；嵌图可选关闭（degradation flag）|
| matplotlib PNG 二进制差异让 baseline 失败 | 高 | 低 | DOCX baseline 不比较图片二进制，仅检查骨架 |
| Sprint 1-2 baseline 在阶段 1 Theme 重构后失效 | 中 | 高 | Step 1 完成后立即跑 4 端 baseline，发现差异即调整 |

**全局回滚策略**：
- 每个阶段独立 PR，可独立 revert
- 阶段 0 完成前可全部回退到 Sprint 1-2 状态
- 阶段 1+ 启动后，每阶段都有 baseline + 视觉守护，单阶段 revert 不影响其他阶段
- 用户层面：`theme="legacy"` 或不传 theme → 输出与 Sprint 1-2 后完全等价

---

## 14. 验收标准

完成后应同时满足：

- [ ] **架构闭环**：4 端 100% outline 化，PPT 双路径消除
- [ ] **视觉对标**：客户拿到的 .docx/.pptx 与 SOP 沙箱产出在 90% 视觉特征上对齐（人眼对照）
- [ ] **跨平台兼容**：visual_compatibility_matrix.md 全绿（已知差异已记录）
- [ ] **回归网完整**：60+ 视觉测试 + perceptual hash + 性能预算 + LLM planner 视觉验收
- [ ] **theme 抽象就位**：未来加新主题是"加一个 dict entry"成本
- [ ] **零向后破坏**：未传 theme 的旧调用与重构前完全等价

---

## 15. Claude Code 执行 Tips

- 每个阶段开始前重读本文档第 3 节（与 Sprint 1-2 关系）和当前阶段章节
- 每个阶段结束跑：`pytest tests/contract/`（含新增测试）+ baseline spot check
- 任何"baseline 不通过"都不要修 baseline，要修代码 — baseline 是单一真实来源
- 新增视觉项时按顺序：(1) 数据模型字段（如有）→ (2) `_chart_renderer.py` / `_components.py` 共享层 → (3) 4 端 renderer 实现 → (4) `_planner_prompts.py` 增强 → (5) 单测
- 跨阶段 deprecated 代码用注释 `# DEPRECATED — 阶段 N 移除` 明确标注
- 阶段 0 是 Sprint 1-2 收尾，不是视觉改造 — 完成前不要碰阶段 1+ 的工作

---

## 附录 A · Claude SOP 对照清单

| SOP 第 N 页 | 视觉特征 | 本方案对应 |
|---|---|---|
| 1 (PPT 封面) | 深色全屏 + 大字 | Cover slide（已有，3.5 KPI overview 增强）|
| 3 / 6 / 9 (PPT 章节过渡) | 深色背景 + 章节号大字 | 3.1 SectionCoverBlock |
| 7 (设备状态环形图) | 环形图（DOUGHNUT）| 2.3 |
| 5 (类别饼图) | 饼图（PIE）| 2.3 |
| 8 (TOP10 横向排名) | 横向条形 + 高亮 | 2.3 + 4.2 + 3.6 |
| 10 (KPI 看板 + 子公司对比) | KPI 卡 + 组合图 | 3.5 + 2.3 |
| 12 (短/中/长期建议) | 三栏 grid | 3.2 |
| DOCX § 4.1 (问题归因汇总表) | 标准表格 + 高亮 | 3.4 + 4.2 |
| DOCX § 4.2 (行动建议) | 三栏分时段 | 3.2（DOCX 端实现）|

---

## 附录 B · 文件改动清单

### 新增

```
backend/tools/report/
├── _pptxgen_commands.py          # 阶段 0 — SlideCommand DSL
├── _renderers/pptxgen.py         # 阶段 0 — PptxGenJSBlockRenderer
├── pptxgen_executor.js           # 阶段 0 — Node 长期常驻
├── _chart_renderer.py            # 阶段 2.1 — 4 端共享 chart 渲染
├── _components.py                # 阶段 5.1 — 跨端组件视觉契约
└── _docx_callout.py              # 阶段 4.1 — DOCX callout builder

tests/
├── contract/test_pptxgen_block_renderer.py
├── contract/test_chart_renderer.py
├── contract/test_outline_planner_visual.py
├── contract/test_enhanced_baseline.py
├── integration/test_pptxgen_node_bridge.py
├── visual/test_report_visual.py
└── perf/test_perf_budget.py

spec/
├── chart_capability_matrix.md
└── visual_compatibility_matrix.md

tests/fixtures/report_baseline/
└── enhanced/
    ├── golden.docx
    ├── golden.pptx
    ├── golden.html
    └── golden.md
```

### 修改

```
backend/tools/report/
├── _theme.py                     # 阶段 1 — 重构为 Theme dataclass
├── _outline.py                   # 阶段 4.2 — TableBlock.highlight_rules
├── _outline_legacy.py            # 阶段 3.1/4.1 — 自动插入 SectionCoverBlock + callout 关键词检测
├── _planner_prompts.py           # 全程 — LLM 视觉决策规则增强
├── _pptxgen_builder.py           # 阶段 0 — 删 generate_pptxgen_script + render_to_pptx
├── pptx_gen.py                   # 阶段 0 — 双路径消除
├── _renderers/{markdown,docx,pptx,html}.py  # 全程 — emit_* 视觉项实现
├── _docx_elements.py             # 阶段 4.1 — build_callout 新增
└── _pptx_slides.py               # 阶段 3.5 — build_kpi_overview_slide 提取

backend/config.py
└── 阶段 1 — 加 REPORT_THEME flag (可选)
```

### 删除

```
backend/tools/report/
├── _pptx_tools.py                # 已在 Sprint 1-2 Step 7 删除
└── _content_collector.py 中的旧引用 # 阶段 0 完成后清理
```

---

**EOF**
