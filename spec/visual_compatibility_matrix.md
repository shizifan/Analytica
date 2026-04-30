# 跨平台视觉兼容性矩阵

**对应阶段**：[visual_polish_plan.md 阶段 6 / 子项 6.3](./visual_polish_plan.md#103-子项-63--跨平台-spot-check-矩阵-05d)
**配套**：`tests/contract/test_enhanced_baseline.py`（结构等价）+ `tests/visual/test_report_visual.py`（perceptual hash）

每次重大视觉改动后，跑 enhanced fixture（`tests/fixtures/report_baseline/enhanced/golden.{docx,pptx,html}`）逐项校对并更新本表。

---

## Spot check 流程

1. 重新生成 enhanced fixture：
   ```bash
   ANALYTICA_REGEN_BASELINE=1 uv run pytest tests/contract/test_enhanced_baseline.py
   ```
2. 在每个目标客户端打开对应 golden 文件，对照下表逐项核查。
3. 若发现新差异，在"已知差异"列追加（**仅当**差异属于客户端渲染特性，不会回退用户体验）；否则记为缺陷并修复。

---

## 兼容性矩阵

| 客户端                  | normal fixture | enhanced fixture | 已知差异 |
|-------------------------|:-:|:-:|---|
| **Word macOS 16.x**     | ✅ | ✅ | — |
| **Word Windows 16.x**   | ✅ | ✅ | 表格列宽 1px 偏差（Word 自动重算） |
| **PowerPoint macOS 16.x** | ✅ | ✅ | — |
| **PowerPoint Windows 16.x** | ✅ | ✅ | — |
| **Chrome (latest)**     | ✅ | ✅ | — |
| **Safari (latest)**     | ✅ | ✅ | callout 阴影渲染稍弱（Safari box-shadow blur 实现差异） |
| **Firefox (latest)**    | ✅ | ✅ | — |
| **LibreOffice 24.x**（CI 用） | ✅ | ✅ | 中文字体 fallback 到 Noto CJK，行距比 macOS Word 略松 |

图例：
- ✅ — 完整渲染，结构与排版与设计意图一致
- ⚠️ — 部分降级，但功能可用（备注差异）
- ❌ — 渲染破损，必须修复

---

## 重点检查项（enhanced fixture 专属）

| 视觉项 | 来源 block | DOCX 检查 | PPTX 检查 | HTML 检查 |
|---|---|---|---|---|
| Section cover (深色) | `SectionCoverBlock` | 章节首页深色背景大标题 + 副标题 | 单独深色封面 slide | 深色 banner div |
| KPI 行 | `KpiRowBlock` | 顶部 4 列卡片，箭头方向正确 | KPI 概览页存在 | `<section class="kpi-row">` 4 卡片 |
| Chart-table pair | `ChartTablePairBlock` | 嵌入图片 + 紧邻数据表 | 单页内左图右表 | grid 双栏 |
| Table highlight | `TableBlock.highlight_rules` | max 单元格背景色 / negative 红色 / 前 3 列描边 | 同 DOCX | 通过 `data-rule` class 着色 |
| Callout warn / info | `ParagraphBlock(style="callout-*")` | 灰底框 + 图标段落 | 文本框背景色区分 | `.callout.warn` / `.callout.info` 边框色取自 theme |
| Comparison grid (3 栏) | `ComparisonGridBlock` | 三列等宽表格 | 三栏 slide | `display:grid` 三列 |
| Growth indicators | `GrowthIndicatorsBlock` | 箭头 + 颜色 | 数字 + 趋势指示 | trend pill |
| 多图表混合 | bar + pie | 两张 PNG | 两个 native chart | 两个 `<div class="chart">` |
| 字体 | — | 中文走 SimSun / PingFang，英文走 Inter | 同左 | CSS font-stack 含 fallback |

---

## CI 自动化

- 主 PR 流水线跑结构等价（`test_enhanced_baseline.py`），不阻塞合入。
- `visual` label PR 跑 perceptual hash（`tests/visual/`）+ LibreOffice 渲染。
- Nightly 跑完整矩阵（含 Pillow + imagehash 安装）并把渲染样张归档至 artifacts。

---

## 历史更新

| 日期 | 改动 | 触发回归 |
|---|---|---|
| 2026-04-30 | 阶段 6 落地 — 矩阵首次记录 | — |
