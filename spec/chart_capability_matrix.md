# 4 端 Chart Type 能力矩阵

**关联**：[spec/visual_polish_plan.md](./visual_polish_plan.md) 阶段 2 · 数据表达核心
**状态**：Phase 2.3 交付（2026-04-29）
**单一真相**：[backend/tools/report/_chart_renderer.py](../backend/tools/report/_chart_renderer.py) + [_pptxgen_builder.py](../backend/tools/report/_pptxgen_builder.py)

---

## 矩阵

| chart_type | DOCX (matplotlib PNG) | PPT (PptxGenJS, 原生可编辑) | PPT (python-pptx, 兜底) | HTML (ECharts) | Markdown |
|---|---|---|---|---|---|
| `bar` | ✅ 嵌图 | ✅ 原生 | 数据表 | ✅ 交互 | 数据表 |
| `line` | ✅ 嵌图 | ✅ 原生 | 数据表 | ✅ 交互 | 数据表 |
| `pie` | ✅ 嵌图 | ✅ 原生 | 数据表 | ✅ 交互 | 数据表 |
| `doughnut` | ✅ 嵌图（pie 视觉等价） | ✅ 原生（hole=50）| 数据表 | ✅ 交互 | 数据表 |
| `horizontal_bar` (yAxis.type="category") | ✅ 嵌图 | ✅ 原生（barDir=bar）| 数据表 | ✅ 交互 | 数据表 |
| `combo` (BAR + LINE 共享类别) | ✅ 嵌图（双 y 轴）| ✅ 原生（multi-type chart） | 数据表 | ✅ 交互 | 数据表 |
| `waterfall` | 数据表 | 数据表 | 数据表 | ✅ 交互 | 数据表 |
| `scatter` | 数据表 | 数据表 | 数据表 | ✅ 交互 | 数据表 |
| `radar` | 数据表 | 数据表 | 数据表 | ✅ 交互 | 数据表 |
| `gauge` / `funnel` / `treemap` 等 | 数据表 | 数据表 | 数据表 | ✅ 交互 | 数据表 |

**符号说明**：
- ✅ **嵌图 / 原生 / 交互**：该 chart 类型走"高质量路径"
- **数据表**：自动降级到表格 ([_chart_renderer.echarts_to_data_table](../backend/tools/report/_chart_renderer.py))，**永不渲染失败**

---

## 路径详解

### DOCX

入口：[`DocxBlockRenderer.emit_chart`](../backend/tools/report/_renderers/docx.py)
1. 试 [`render_chart_to_png(option, theme)`](../backend/tools/report/_chart_renderer.py)（matplotlib + Agg 后端）
2. 成功 → `doc.add_heading(title, level=2)` + `doc.add_picture(png, width=6")`
3. 失败 / chart 类型不支持 → fallback `_docx_elements.build_chart_data_table`（OOXML 表格）

**字体**：`_chart_renderer.py` 启动时探测 CJK 字体（`Noto Sans CJK SC` / `PingFang SC` / `Hiragino Sans GB` / `STHeiti` / `Microsoft YaHei` 等），配置 `matplotlib.rcParams['font.sans-serif']`。CI 镜像应安装 `fonts-noto-cjk`，否则中文标签渲染为方块（不会崩溃）。

### PPT (PptxGenJS Node 桥接)

入口：[`PptxGenJSBlockRenderer.emit_chart`](../backend/tools/report/_renderers/pptxgen.py) → `_add_chart_table_slide`
1. [`echarts_to_pptxgen(option)`](../backend/tools/report/_pptxgen_builder.py) 返回 spec
2. spec 序列化为 [`AddChart`](../backend/tools/report/_pptxgen_commands.py) SlideCommand → JSON → stdin
3. Node executor [`pptxgen_executor.js`](../backend/tools/report/pptxgen_executor.js) 调 `slide.addChart(type, data, options)` 生成原生 PowerPoint chart（**用户可在 PowerPoint 内编辑数据**）
4. spec 为 `None`（waterfall / scatter / 其他不支持）→ Node 端跳过，整张 slide 退化（python-pptx fallback 路径会接管）

**COMBO 特殊路径**：spec.type == "COMBO" 时，data 是 `[{type, data, options}, ...]` 多类型数组；Node executor 检测到后调 `slide.addChart(arrayOfTypes, outerOpts)` —— 这是 pptxgenjs 的 multi-type chart API。

### PPT (python-pptx fallback)

入口：[`PptxBlockRenderer.emit_chart`](../backend/tools/report/_renderers/pptx.py)
- 触发条件：`check_pptxgen_available() == False`（Node / pptxgenjs 缺失）或 PptxGenJS 渲染异常
- 行为：写一张 `_pptx_slides.build_chart_table_slide`（OOXML 表格 + 标题），不嵌图
- 视觉降级，但**用户仍能拿到完整数据**

### HTML (ECharts)

入口：[`HtmlBlockRenderer.emit_chart`](../backend/tools/report/_renderers/html.py) → 调 [`echarts_to_html(option, container_id)`](../backend/tools/report/_chart_renderer.py)
- ECharts 5 是浏览器端 SDK，**支持所有 ECharts 原生类型**（含 waterfall / scatter / radar / gauge / funnel / treemap / heatmap 等）
- HTML 包内 `<script src="https://cdn.jsdelivr.net/npm/echarts@5/...">` 加载 SDK
- 原始 ECharts option 直接 `setOption` —— Phase 2.5 增加 tooltip / resize 自动配置

### Markdown

入口：[`MarkdownBlockRenderer.emit_chart`](../backend/tools/report/_renderers/markdown.py)
- 设计上 Markdown 是"机器可读中间格式"，不追求图表能力
- 所有 chart_type 一律降级为 `### {title}` + `*（图表数据，可视化时需配合 ECharts 等工具渲染）*`
- 完整数据可走 `echarts_to_data_table` 输出 markdown 表格（Phase 4-5 视觉打磨可启用）

---

## 降级一致性原则

无论上游 LLM planner / 数据源给出何种 chart_type，**4 端永远不会渲染失败**：

```
chart_type 在矩阵的 ✅ 列?
  yes → 高质量渲染（嵌图 / 原生 / ECharts）
  no  → echarts_to_data_table → 各端绘制数据表
```

测试守护：
- [`test_pptxgen_constraints.py`](../tests/contract/test_pptxgen_constraints.py) 覆盖 7 个 chart 类型 × 3 个不变量 = 21 个参数化用例 + 6 个 type-specific
- [`test_pptxgen_block_renderer.py`](../tests/contract/test_pptxgen_block_renderer.py) 验证 chart 命令通过 Node 桥接产生 OOXML chart part
- [`test_pptxgen_node_bridge.py`](../tests/integration/test_pptxgen_node_bridge.py) (slow) 端到端验证

---

## 扩展指引（加新 chart 类型）

按以下顺序：

1. **DOCX (matplotlib)** —— 在 [`_chart_renderer.py`](../backend/tools/report/_chart_renderer.py) 新增 `_render_<kind>` + 在 `_detect_chart_kind` / `_PNG_SUPPORTED` 注册
2. **PPT 原生** —— 在 [`echarts_to_pptxgen`](../backend/tools/report/_pptxgen_builder.py) 加分支 + 新增 `_convert_<kind>` helper
3. **JS 端** —— 若 chart_type 是新值（不属于 BAR/LINE/PIE/DOUGHNUT），在 [`pptxgen_executor.js`](../backend/tools/report/pptxgen_executor.js) `CHART_TYPE_MAP` 加映射
4. **SlideCommand schema** —— 在 [`_pptxgen_commands.py`](../backend/tools/report/_pptxgen_commands.py) `ChartType` Literal 加新值
5. **测试** —— `test_pptxgen_constraints.py` 加 fixture + 参数化 + type-specific 断言；3 大不变量参数化自动覆盖

**禁止**：
- 在某一端实现新 chart 类型而不更新矩阵 → 跨端漂移
- 跳过 fallback 路径 → 用户拿到的报告可能空缺
- 直接修改 ECharts option（在 renderer 内）→ option 是上游数据，应只读

---

**EOF**
