# 批次 C — PPTX 渲染层 Patch 实施方案

> **状态**：待实施 | **父文档**：`spec/optimize_report_quality_V1.md` | **预计工时**：1 天
>
> **依存关系**：可与批次 A 并行。需等待批次 A.1 的渲染层标注模式就位后对接质量标志位。

---

## 0. 背景与目标

### 0.1 本批次要解决的问题

PPTX 格式当前存在两个严重问题：

| 症状 | 根因编号 | 本批次覆盖 |
|---|---|---|
| 一项分析散落到 4 张 slide | R7：硬编码每 section 强制生成 chart + narrative + growth KPI + stats 共 3-4 张 slide | C.1 章节内容合页 |
| 附录整段重复出现 | R8：`_flush_appendix_deck()` 被触发 2 次，无幂等标记 | C.2 Appendix 幂等 |

### 0.2 目标

- 设备运营报告 PPTX 从当前 24 张降到 12-14 张
- 任意章节占 1-2 张 slide
- 附录与结语各只出现 1 次

---

## 1. C.1 — 章节内容合页 Layout-Aware（0.5 天）

### 1.1 问题

**代码位置**：`backend/tools/report/_renderers/pptxgen.py:968-992` `_render_section_combo()`

当前逻辑硬编码每章 3-4 张 slide：图表页 + 文字叙述页 + 增长率 KPI 页 + 统计页。内容少的章节（如故障特征只有 1 个 chart + 2 行 narrative）也被撑成 4 页。

### 1.2 改动

**1. 新增 `_estimate_section_complexity()` 函数**：

```python
def _estimate_section_complexity(section: Section) -> str:
    """
    统计该 section 的 chart 数、narrative 字数、KPI 数，
    返回 layout 决策：single_page / chart_text_split / multi_page
    """
    chart_count = sum(1 for b in section.blocks if isinstance(b, ChartBlock))
    narrative_len = sum(len(b.text) for b in section.blocks if isinstance(b, NarrativeBlock))
    kpi_count = sum(len(b.items) for b in section.blocks if isinstance(b, KpiRowBlock))

    if chart_count <= 1 and narrative_len <= 200 and kpi_count <= 3:
        return "single_page"
    elif chart_count == 1 and (narrative_len > 200 or kpi_count > 3):
        return "chart_text_split"
    else:
        return "multi_page"
```

**注**：`multi_page` 阈值的 "chart > 2 或 narrative > 200 字"参数为初始值，实施 C.1 时按真实测试用例调优。

**2. `_render_section_combo()` 按决策走不同分支**：

- `single_page`（默认）：1 张 slide 容纳 chart + narrative + ≤3 KPI
- `chart_text_split`：chart 占满一页，narrative + KPI 合到下一页
- `multi_page`：仅当 chart > 2 或 narrative > 200 字时启用，逐一展开

**3. 删除"每章节专用增长率页"** — 增长率合并进章节内的 KPI 行。

### 1.3 与 quality_flags 的对接

渲染层根据 A.0 写入的 `quality_flags` 调整渲染策略（与批次 A.1 共用同一渲染器改动）：

| Flag | 渲染行为 |
|---|---|
| `P0_NO_VARIANCE` | 不画无方差趋势线，改为单一数值卡片 |
| `P0_RANGE_RATE` / `P1_QUANTITY_LOW` | 数字后加 ⚠️ + tooltip |
| `P1_NAME_VS_INTENT` | 字段标签使用映射后的业务名 |

---

## 2. C.2 — Appendix 幂等（0.5 天）

### 2.1 问题

**代码位置**：`backend/tools/report/_renderers/pptxgen.py:878-891`

`_flush_appendix_deck()` 被触发 2 次（结语前后各一次），因为调用方没有幂等保护。

### 2.2 改动

**在 pptxgen.py 的 builder state 加幂等标记**：

```python
class PptxBuilder:
    def __init__(self, ...):
        ...
        self._appendix_flushed: bool = False

    def _flush_appendix_deck(self) -> None:
        if self._appendix_flushed:
            return
        # ... 原有逻辑 ...
        self._appendix_flushed = True
```

**单元测试**：

```python
def test_flush_appendix_idempotent():
    builder = PptxBuilder(...)
    builder._flush_appendix_deck()
    first_slide_count = len(builder.slides)
    builder._flush_appendix_deck()  # 第二次调用
    assert len(builder.slides) == first_slide_count  # 不变
```

---

## 3. 验收标准

- [ ] 设备运营报告 PPTX slide 数从当前 24 张降到 12-16 张
- [ ] 任意章节占 1-2 张 slide，不再出现章节封面 + 图表页 + 文字页 + KPI 页四联
- [ ] 附录与结语只出现 1 次（不重复）
- [ ] 增长率合并进章节内 KPI 行，无独立的"增长率专用页"

---

## 4. 文件清单

| 文件 | 改动概要 |
|---|---|
| `backend/tools/report/_renderers/pptxgen.py` | C.1: `_render_section_combo` 改造（`_estimate_section_complexity` + 三分支 layout + 删除增长率专用页）+ 对接 quality_flags；C.2: `_flush_appendix_deck` 加 `_appendix_flushed` 幂等标记 |

---

> **下一步**：本批次完成后，PPTX 排版问题清零。与批次 A 的数据标注对接后，PPTX 格式即可具备"可信 + 排版工整"两个核心特性。
