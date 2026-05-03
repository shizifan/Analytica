# 辽港数据期刊 · 设计实施方案

> **状态**：待实施 · 不在此 PR 中落地代码
> **最后更新**：2026-05-02
> **目标分支**：`claude/confirm-llm-generation-status-rUDwH`
> **作者**：Claude（基于多轮设计评审）

---

## 0. 文档说明

本文档定义"辽港数据期刊"（Liangang Data Journal）视觉系统在三种报告输出格式（HTML、DOCX、PPTX）上的统一实施规范。

### 0.1 决策已锁定（不再讨论）

| # | 决策项 | 取值 | 来源 |
|---|---|---|---|
| 1 | 强调色体系 | 辽港集团 VI 标准色（PANTONE 293 C 深蓝 + PANTONE 872 U 古铜） | 用户上传 VI 手册截图 |
| 2 | 整体方向 | 编辑型 / 数据期刊（Editorial Data Journal） | 用户确认 |
| 3 | 主轴布局 | 纵向（chart 在上、KPI 在下、明细折叠至附录） | 用户确认 |
| 4 | 表格策略 | 减量呈现，主流默认不展开全表 | 用户确认 |
| 5 | PPTX 比例 | 16:9（13.333" × 7.5"） | 本轮确认 |
| 6 | DOCX 折叠层 | 章末附录（每章末尾追加"完整数据"小节） | 本轮确认 |
| 7 | PPTX 附录 deck | 默认开启，无前端开关 | 本轮确认 |
| 8 | PR 拆分 | 四段（基础 → HTML → DOCX → PPTX） | 本轮确认 |
| 9 | PPTX 矢量图 | 质量红线，pptxgenjs 不可用时阻断生成，不降级 | 本轮确认 |
| 10 | 质量保障 | 三层防线：预生成测试 → 生成期重试 → 生成后 LLM Review | 本轮确认 |

### 0.2 默认值（未显式确认，沿用上轮提案）

| # | 项目 | 默认值 | 备注 |
|---|---|---|---|
| D1 | 纸张背景色 | `#FBF6EE`（古铜 8% tint 调暖） | 见 §1.1 |
| D2 | KPI strip 格数 | 固定 4 格（起点/高点/当前/变化） | 见 §6 |
| D3 | 表格折叠阈值 | ≥6 行折叠，≤5 行内联 | 见 §6.4 |
| D4 | 图表 Y 轴位置 | 右置（编辑型签名特征） | 见 §5.2 |
| D5 | H1 端饰条颜色 | 古铜（与 navy 主结构互补） | 见 §3 |

如需调整，在实施前通过 PR 评论变更本表，相应章节同步更新。

---

## 1. 共享设计 Token

### 1.1 颜色 Token

#### 品牌基色（VI 手册定义）

| Token | Hex | RGB | PANTONE | 角色 |
|---|---|---|---|---|
| `primary` | `#004889` | (0, 72, 137) | 293 C | 主结构色 |
| `accent` | `#AC916B` | (172, 145, 107) | 872 U | 强调色 |

#### 完整 token 表

| Token 名 | Hex | RGB | 用途 |
|---|---|---|---|
| `paper` | `#FBF6EE` | (251, 246, 238) | 页面/Slide 背景 |
| `paper_2` | `#F4ECDF` | (244, 236, 223) | 卡片底色、agate 表斑马偶数行 |
| `ink_1` | `#1F1A12` | (31, 26, 18) | 正文主墨色（暖黑） |
| `ink_2` | `#5E5648` | (94, 86, 72) | 次级文字、副标题 |
| `ink_3` | `#9A8E78` | (154, 142, 120) | metadata、注脚、表头小字 |
| `rule_soft` | `rgba(31,26,18,.20)` | — | hairline（约 #1F1A1233） |
| `rule_strong` | `#004889` | (0, 72, 137) | section 重要分隔 |
| `primary` | `#004889` | (0, 72, 137) | 辽港深蓝主品牌 |
| `primary_70` | `#336EA4` | (51, 110, 164) | navy 70% tint，次级数据 |
| `primary_50` | `#80A4C2` | (128, 164, 194) | navy 50%，对照系列 |
| `primary_30` | `#B3C8DB` | (179, 200, 219) | navy 30%，sequential 浅阶 |
| `accent` | `#AC916B` | (172, 145, 107) | 辽港古铜主强调 |
| `accent_60` | `#CFAB79` | (207, 171, 121) | 古铜 60% |
| `accent_30` | `#E7D4BC` | (231, 212, 188) | 古铜 30%，背景高亮 |
| `accent_dark` | `#8B4A2B` | (139, 74, 43) | 古铜加深，下跌/警示 |
| `gain` | `#004889` | — | 上涨语义（即 navy） |
| `loss` | `#8B4A2B` | — | 下跌语义（即 accent_dark） |
| `alert` | `#A8341E` | (168, 52, 30) | 仅 callout-warn 用 |

> **规则**：图表内的"涨跌"用主色 vs 次色的明度对比表达；语义层（好/坏）由文字注释承担。

### 1.2 字体 Token

| Token | 用途 | Web 字体 | 桌面/服务端兜底 |
|---|---|---|---|
| `font_display` | H1/H2/lede/pull-quote | Noto Serif SC | 思源宋体 → SimSun → STSong |
| `font_body` | 正文 | Noto Serif SC | 同 display |
| `font_ui` | 表头/标签/UI/副文/源注 | Noto Sans SC | PingFang SC → Microsoft YaHei → SimHei |
| `font_mono` | 所有数字、表格数字、KPI 大数 | JetBrains Mono | Consolas → Menlo → Courier New |

> **唯一来源**：`Theme` dataclass 增加 `font_display` / `font_ui` / `font_cn_fallbacks`（多级降级 hint），三个 renderer 一致使用。

### 1.3 字号 Token（点 / px 二分）

| Token | 用途 | HTML px | DOCX/PPTX pt |
|---|---|---|---|
| `size_h1` | 报告标题 | 42 | 32 |
| `size_h2` | 章节标题 | 28 | 22 |
| `size_h3` | 子节标题 | 20 | 16 |
| `size_lede` | 引语段 | 18 | 14 |
| `size_body` | 正文 | 16 | 11 |
| `size_pullquote` | 推荐段大字 | 22 | 18 |
| `size_kpi_value` | KPI 大数字 | 36 | 28 |
| `size_kpi_label` | KPI 标签 | 11 | 8 |
| `size_chart_title` | 图表题图 | 16 | 14 |
| `size_chart_sub` | 图表副标题 | 12 | 10 |
| `size_table_header` | 表头 | 11 | 9 |
| `size_table_body` | 表体 | 13 | 10 |
| `size_source` | 注脚/来源 | 11 | 9 |
| `size_kicker` | 小标签 | 11 | 9 |

### 1.4 图表色板（四类）

| 类型 | 色板（按顺序） |
|---|---|
| Categorical（≤4） | `#004889`, `#AC916B`, `#80A4C2`, `#CFAB79` |
| Categorical（5-6） | 上面 4 + `#336EA4`, `#8B4A2B` |
| Sequential（单一渐变） | `#B3C8DB → #80A4C2 → #4D80B0 → #336EA4 → #004889` |
| Diverging（双向） | `#AC916B → #FBF6EE → #004889` |
| Highlight 模式 | 默认所有系列 `#80A4C2`，焦点系列 `#004889` |

---

## 2. 字体落地策略

### 2.1 服务端字体安装（Dockerfile）

需要在镜像中预装：

```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-noto-cjk \
        fonts-noto-cjk-extra \
        fonts-jetbrains-mono \
    && fc-cache -fv \
    && rm -rf /var/lib/apt/lists/*

# Node.js + pptxgenjs bridge 环境（PPTX 矢量图为品质红线，不可省略）
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && node -v && npm -v
COPY backend/tools/report/_pptxgen_bridge/package.json /app/bridge/
RUN cd /app/bridge && npm ci --production
```

> Debian/Ubuntu 包名以上为准；其它发行版需对应映射。

### 2.2 启动期自检

`backend/main.py` 启动钩子里加：

```python
def check_fonts() -> list[str]:
    """返回缺失的关键字体名，写入启动日志；缺失不阻断启动。"""
    required = ["Noto Serif SC", "Noto Sans SC", "JetBrains Mono"]
    # subprocess fc-list 检测；缺失 -> WARNING

async def probe_pptxgenjs_bridge() -> bool:
    """检测 pptxgenjs Node bridge 是否可用。不可用 -> CRITICAL（PPTX 生成将阻断）。"""
    # ping Node process / health endpoint
```

### 2.3 多级降级（Theme 层）

```python
font_cn_fallbacks: tuple[str, ...] = (
    "Noto Serif SC",
    "Source Han Serif SC",  # 思源宋体
    "Songti SC",            # macOS
    "STSong",               # 简版
    "SimSun",               # Windows
)
font_ui_fallbacks: tuple[str, ...] = (
    "Noto Sans SC",
    "PingFang SC",          # macOS
    "Microsoft YaHei",      # Windows
    "SimHei",
)
font_mono_fallbacks: tuple[str, ...] = (
    "JetBrains Mono", "IBM Plex Mono", "Consolas", "Menlo", "Courier New",
)
```

DOCX 通过 `<w:rFonts w:ascii w:eastAsia w:hAnsi>` 写多个 hint。
PPTX 在 `paragraph.font.name` 上设主字体；缺失时由 PowerPoint 自动按系统字体替换。
HTML 通过 CSS `font-family` 多级 fallback。

### 2.4 字体许可

所有指定字体均为开源许可（OFL/SIL/Apache），可商用，无需付费授权。

---

## 3. 跨格式元素映射表

完整映射详见各格式专章。下表只列高层对应。

| 设计元素 | HTML | DOCX | PPTX |
|---|---|---|---|
| 纸色背景 | `body { background: #FBF6EE }` | 封面与 section divider 用大块 shape；正文页通过 page color | master slide 背景实色 |
| H1 标题 | display serif 42px | Title style 32pt navy | Cover slide 32pt navy |
| Kicker 小标签 | small caps + 字距 | character style "Kicker" | textbox 9pt smcp navy |
| 章首罗马数字 | `<span.section-num>` italic | 大号 italic 段 | divider slide 左侧 120pt 古铜 |
| Lede 引语 | italic + drop cap | "Lede" 段落样式 + dropCap OOXML | chart slide 顶部 textbox |
| 正文段落 | serif 1.85x 行高 + 2em 缩进 | "Narrative" style 11pt 1.5x | textbox 13pt 1.4x |
| Hairline | `border-top: 1px solid rule_soft` | 段落上边框 1pt | line shape 0.75pt |
| Pull-quote | 左 4px 古铜竖条 + 大斜体 | 段落左缩 + 左 4pt 古铜边框 + italic | 独立 slide |
| Chart | ECharts + theme | matplotlib PNG + mpl theme | pptxgenjs native + theme（矢量图为品质红线，不可降级） |
| KPI strip | 4 列 grid + tabular mono | 1×4 无边框 table + 上下 hairline | 一张专用 KPI slide 或 chart slide 底部 |
| Agate 表（≤5 行） | `table.agate` | "Hairline Table" style | pptxgenjs `addTable` + 仅 3 hairline |
| 完整数据折叠 | `<details>` 默认收起 | 章末"完整数据"小节 + 书签锚点 | 末尾"附录 · 完整数据" slide pack |
| Endmark ■ | 古铜 inline 方块 | character style + W:sym 方块 | slide 右下 shape |
| Source/footnote | italic 11px ink_3 | "Source" 段 9pt italic | 底部 textbox 8pt italic |
| 页眉/页脚 | — | header + footer 区域 | master slide 区 |

---

## 4. HTML 实施细节

### 4.1 模板骨架

`backend/tools/report/_renderers/html.py:39-116` 的 `HTML_TEMPLATE` 全量重写。新增 `<head>` 内容：

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=Noto+Sans+SC:wght@400;500;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
```

CSS 用变量管理，在 `<style>` 顶部生成：

```css
:root {
  --paper: #FBF6EE;
  --paper-2: #F4ECDF;
  --ink-1: #1F1A12;
  --ink-2: #5E5648;
  --ink-3: #9A8E78;
  --rule: rgba(31,26,18,0.20);
  --primary: #004889;
  --primary-70: #336EA4;
  --primary-50: #80A4C2;
  --accent: #AC916B;
  --accent-60: #CFAB79;
  --accent-dark: #8B4A2B;
  --font-display: "Noto Serif SC", "Source Han Serif SC", "Songti SC", "SimSun", serif;
  --font-body: var(--font-display);
  --font-ui: "Noto Sans SC", "PingFang SC", "Microsoft YaHei", system-ui, sans-serif;
  --font-mono: "JetBrains Mono", "IBM Plex Mono", "Consolas", "Menlo", monospace;
}
```

### 4.2 关键 selector（节选，完整版见上轮 §6 设计稿）

```css
body {
  background: var(--paper);
  color: var(--ink-1);
  font-family: var(--font-body);
  font-size: 16px; line-height: 1.85;
  font-variant-numeric: tabular-nums lining-nums;
  max-width: 840px; margin: 0 auto;
  padding: 64px 56px 96px;
  hanging-punctuation: allow-end last;
}
.kicker { font-family: var(--font-ui); font-size: 11px; letter-spacing: .12em;
          text-transform: uppercase; color: var(--primary); font-feature-settings: "smcp"; }
.section { padding-top: 32px; border-top: 1px solid var(--primary); margin-top: 32px; }
.lede { font-family: var(--font-display); font-style: italic; font-size: 18px;
        color: var(--ink-2); margin: 16px 0 24px; }
.lede:first-letter { font-size: 4em; line-height: .85; float: left;
                     padding: 4px 8px 0 0; color: var(--primary); }
.narrative { text-indent: 2em; margin: 14px 0; }
.chart-fig { margin: 32px 0; }
.chart-fig header { border-top: 1px solid var(--rule); padding-top: 12px; margin-bottom: 16px; }
.fig-title { font-family: var(--font-display); font-size: 16px; font-weight: 600; }
.fig-sub { font-family: var(--font-ui); font-size: 12px; color: var(--ink-2); }
.chart-container { width: 100%; height: 360px; }
.fig-note { font-family: var(--font-ui); font-style: italic; font-size: 11px;
            color: var(--ink-3); border-top: 1px solid var(--rule);
            padding-top: 8px; margin-top: 12px; }
.kpi-strip { display: grid; grid-template-columns: repeat(4, 1fr);
             border-top: 1px solid var(--primary); border-bottom: 1px solid var(--primary); }
.kpi-cell { padding: 16px 20px; border-right: 1px solid var(--rule); }
.kpi-cell:last-child { border-right: 0; }
.kpi-cell .label { font-family: var(--font-ui); font-size: 11px; letter-spacing: .08em;
                   text-transform: uppercase; color: var(--ink-3); }
.kpi-cell .value { font-family: var(--font-mono); font-size: 36px; font-weight: 500;
                   color: var(--primary); letter-spacing: -0.02em; line-height: 1; margin-top: 4px; }
.kpi-cell .value.loss { color: var(--accent-dark); }
table.agate { width: 100%; border-collapse: collapse; font-size: 13px; }
table.agate thead th { font-family: var(--font-ui); font-size: 11px; font-weight: 500;
                       letter-spacing: .1em; text-transform: uppercase; color: var(--ink-3);
                       padding: 10px 12px; border-top: 1px solid var(--ink-1);
                       border-bottom: 1px solid var(--rule); text-align: left; }
table.agate tbody td { font-family: var(--font-mono); font-size: 13px; padding: 8px 12px; }
table.agate tbody td.cat { font-family: var(--font-body); }
table.agate td.num { text-align: right; font-variant-numeric: tabular-nums; }
table.agate tbody tr:last-child td { border-bottom: 1px solid var(--ink-1); }
details.full-data > summary { font-family: var(--font-ui); font-style: italic;
                              font-size: 13px; color: var(--ink-2); cursor: pointer; }
.endmark { display: inline-block; width: 8px; height: 8px;
           background: var(--accent); margin-left: 6px; vertical-align: middle; }
blockquote.pull { border-left: 4px solid var(--accent); margin: 24px 0; padding-left: 24px;
                  font-family: var(--font-display); font-style: italic; font-size: 22px;
                  line-height: 1.4; color: var(--ink-1); }
.callout { border-left: 3px solid var(--accent); background: rgba(0,0,0,0.02);
           padding: 12px 16px; margin: 16px 0; }
.callout.warn { border-left-color: #A8341E; }
```

### 4.3 emit_chart 改造（修复重叠 bug + 应用主题）

```python
def emit_chart(self, block, asset):
    option = getattr(asset, "option", None)
    if not isinstance(option, dict):
        return
    chart_id = f"chart_{self._chart_idx}"
    self._chart_idx += 1
    enriched = self._enrich_option_for_html(option)
    chart_json = json.dumps(enriched, ensure_ascii=False)

    # figure 包装：title/sub/source 由 wrapper 承担，chart option 内不再渲染
    title = block.title or ""
    subtitle = block.subtitle or ""
    source = block.source or ""
    self._parts.append(
        f'<figure class="chart-fig">'
        f'<header>'
        f'  <h3 class="fig-title">{title}</h3>'
        f'  <p class="fig-sub">{subtitle}</p>'
        f'</header>'
        f'<div id="{chart_id}" class="chart-container" '
        f'data-chart-type="{self._detect_html_chart_type(option)}"></div>'
        f'<footer><p class="fig-note">{source}</p></footer>'
        f'</figure>'
        f'<script>(function(){{var run=function(){{'
        f'var c=echarts.init(document.getElementById("{chart_id}"),"liangang-journal");'
        f'c.setOption({chart_json});'
        f'window.addEventListener("resize",function(){{c.resize();}});'
        f'}};if(document.readyState!=="loading")requestAnimationFrame(run);'
        f'else document.addEventListener("DOMContentLoaded",run);}})();</script>'
    )
```

> 关键修复：`requestAnimationFrame` 包裹 `echarts.init`，等 flex/grid layout 稳定后再读容器尺寸 — 解决 chart-table 横向重叠的 bug。

### 4.4 emit_chart_table_pair 改造（纵向）

```python
def emit_chart_table_pair(self, block, chart_asset, table_asset):
    # 默认纵向：图在上，KPI strip 在下；明细折叠至 details
    self.emit_chart(synth_chart, chart_asset)
    if block.kpi_strip:                    # planner 已生成
        self.emit_kpi_strip(block.kpi_strip)
    if block.show_full_table:              # 默认 False
        self._emit_table_inline(synth_table, table_asset)
    else:
        self._emit_table_collapsed(synth_table, table_asset)
```

`_emit_table_collapsed` 输出：

```html
<details class="full-data">
  <summary>展开完整数据 (12 行)</summary>
  <table class="agate">…</table>
</details>
```

### 4.5 emit_table 改造

- 套用 `table.agate` 样式
- 行数 ≥6 自动折叠至 `<details>`
- 数字列检测：`pd.api.types.is_numeric_dtype` 加 `td.num` class

### 4.6 中英自动加空格

新增 `backend/tools/report/_typography.py`：

```python
import re
_CJK_LATIN = re.compile(r'([一-龥])([A-Za-z0-9])')
_LATIN_CJK = re.compile(r'([A-Za-z0-9])([一-龥])')
_NO_SKIP = re.compile(r'<(?:code|pre|script|style)[^>]*>.*?</(?:code|pre|script|style)>',
                      re.DOTALL | re.IGNORECASE)

def cn_latin_spacing(html: str) -> str:
    """中英之间自动加空格，跳过 code/pre/script/style 块。"""
    placeholders = []
    def stash(m):
        placeholders.append(m.group(0))
        return f"\x00{len(placeholders)-1}\x00"
    masked = _NO_SKIP.sub(stash, html)
    masked = _CJK_LATIN.sub(r'\1 \2', masked)
    masked = _LATIN_CJK.sub(r'\1 \2', masked)
    return re.sub(r'\x00(\d+)\x00', lambda m: placeholders[int(m.group(1))], masked)
```

在 `HtmlBlockRenderer.end_document` 出包前调用。

### 4.7 ECharts 主题注册

新增 `backend/tools/visualization/_echarts_theme.py`：

```python
LIANGANG_JOURNAL_THEME = {
    "color": ["#004889", "#AC916B", "#80A4C2", "#CFAB79", "#336EA4", "#8B4A2B"],
    "backgroundColor": "transparent",
    "textStyle": {
        "fontFamily": "'Noto Sans SC', 'PingFang SC', sans-serif",
        "color": "#1F1A12"
    },
    "title": {"show": False},  # 由 HTML wrapper 渲染
    "grid": {"top": 24, "right": 24, "bottom": 32, "left": 8, "containLabel": True},
    "xAxis": {
        "axisLine": {"show": False},
        "axisTick": {"show": False},
        "splitLine": {"show": False},
        "axisLabel": {"color": "#5E5648", "fontSize": 11},
    },
    "yAxis": {
        "position": "right",
        "axisLine": {"show": False},
        "axisTick": {"show": False},
        "splitLine": {"show": True, "lineStyle": {"color": "rgba(31,26,18,0.10)"}},
        "axisLabel": {"color": "#5E5648", "fontSize": 11, "align": "left", "margin": 8},
    },
    "legend": {"show": False},
    "tooltip": {
        "trigger": "axis",
        "backgroundColor": "#FBF6EE",
        "borderColor": "#004889",
        "borderWidth": 1,
        "textStyle": {"color": "#1F1A12"}
    },
    "graphic": [{
        "type": "rect", "left": 0, "top": 6,
        "shape": {"width": 4, "height": 16},
        "style": {"fill": "#AC916B"}
    }],
}
```

通过 `<script>echarts.registerTheme("liangang-journal", THEME)</script>` 在 HTML head 注入。

---

## 5. DOCX 实施细节

### 5.1 styles.xml 自定义样式表

`build_styles(doc)` 重写为下表：

| Style 名 | 类型 | 字体 | 字号 | 颜色 | 段落属性 |
|---|---|---|---|---|---|
| Normal | Paragraph | font_body | 11pt | #1F1A12 | 行距 1.5x，2 字符首缩 |
| Title | Paragraph | font_display | 32pt bold | #004889 | 居左，下方 1pt navy 边框 |
| Subtitle | Paragraph | font_display italic | 18pt | #5E5648 | 下间距 24pt |
| Heading 1 | Paragraph | font_display | 22pt bold | #1F1A12 | 上间距 24pt + 顶部 1pt navy 边框 + dropCap eligible |
| Heading 2 | Paragraph | font_display | 16pt bold | #1F1A12 | 上间距 16pt |
| Heading 3 | Paragraph | font_display | 14pt bold | #1F1A12 | 上间距 12pt |
| Kicker | Character | font_ui | 9pt | #004889 | smcp + 字距 0.12em |
| Lede | Paragraph | font_display italic | 14pt | #1F1A12 | 不缩进，下间距 12pt，dropCap |
| Narrative | Paragraph | font_body | 11pt | #1F1A12 | 行距 1.5x，2 字符首缩 |
| Callout | Paragraph | font_body | 11pt | #1F1A12 | 左 3pt 古铜边框 + #FBF6EE 底 |
| Pullquote | Paragraph | font_display italic | 14pt | #1F1A12 | 左 4pt 古铜边框 + 左缩 |
| KPIValue | Character | font_mono | 28pt | #004889 | tabular figures |
| KPILabel | Character | font_ui | 8pt | #9A8E78 | smcp |
| Source | Paragraph | font_ui italic | 9pt | #9A8E78 | 上间距 6pt |
| TableHeader | Character | font_ui | 9pt | #9A8E78 | smcp + 字距 0.1em |
| TableNum | Character | font_mono | 10pt | #1F1A12 | tabular figures，右对齐 |

### 5.2 Hairline Table 实现

`build_hairline_table(doc, df, theme)`：

1. 创建 `1+rows × cols` table，无 `Table Grid` style
2. 遍历所有 cell：清除 top/right/bottom/left 边框
3. 表头行：top 1pt #1F1A12，bottom 0.5pt rule_soft；字符样式 TableHeader
4. 末行：bottom 1pt #1F1A12
5. 数字列：右对齐 + TableNum 字符样式
6. 偶数行 cell shading #F4ECDF（可选，默认关）

### 5.3 KPI strip 实现

`build_kpi_strip(doc, kpis: list[KPIItem4])`：

```python
# kpis 固定 4 项：first / max / last / delta
table = doc.add_table(rows=1, cols=4)
# 全 cell 无边框
# table 顶/底加 1pt navy 段落边框（不是 cell border）
for i, kpi in enumerate(kpis):
    cell = table.rows[0].cells[i]
    # 第一段 KPILabel：smcp 古铜 9pt
    # 第二段 KPIValue：mono 28pt navy（loss → accent_dark）
    # 第三段 KPISub：ui 9pt ink_3 metadata
    if i < 3:
        # 右边框 0.5pt rule_soft
```

### 5.4 Drop cap 实现

```python
def _apply_dropcap(para, theme, lines: int = 3):
    pPr = para._p.get_or_add_pPr()
    framePr = OxmlElement("w:framePr")
    framePr.set(qn("w:dropCap"), "drop")
    framePr.set(qn("w:lines"), str(lines))
    framePr.set(qn("w:wrap"), "around")
    framePr.set(qn("w:vAnchor"), "text")
    framePr.set(qn("w:hAnchor"), "text")
    pPr.append(framePr)
    if para.runs:
        para.runs[0].font.size = Pt(36)
        para.runs[0].font.color.rgb = RGBColor(*theme.primary)
```

仅应用于 lede 段。LibreOffice 渲染异常时退化为普通 italic（不影响内容）。

### 5.5 章末附录实现

DOCX 不支持原生折叠。新方案：

#### 5.5.1 buffering 模型

`DocxBlockRenderer` 增加：
```python
self._section_appendix_buffer: dict[str, list[tuple[TableBlock, Asset]]] = {}
self._current_section_id: str = ""
```

每当 `emit_chart_table_pair` 触发时：
- 渲染图表 + KPI strip（正文）
- 把 table_asset 推入 `_section_appendix_buffer[current_section_id]`

#### 5.5.2 章末刷出

`end_section`：
```python
def end_section(self, section, index):
    buffered = self._section_appendix_buffer.get(section.id, [])
    if buffered:
        # 加 hairline 分隔
        E.build_hairline_paragraph(self._doc, theme=self._theme)
        # 小标题
        E.build_appendix_subheading(self._doc, "完整数据")
        for table_block, asset in buffered:
            E.build_hairline_table(self._doc, asset.to_df(), self._theme)
            E.build_source_paragraph(self._doc, table_block.source or "")
    # 原有 appendix 逻辑（针对 role=="appendix" 的整章）保留
```

#### 5.5.3 锚点 / 跳转

正文 KPI strip 之后插入 italic 段：
> "本节完整数据见下方附录"

锚点设置在"完整数据"小标题处（OOXML bookmark），段内文字加超链接，Word 中 ctrl+click 可跳转。

### 5.6 Cover / Section divider 视觉重做

- **Cover page**：纸色背景 shape（占整页）+ 上方古铜 4×120pt brand bar + 下方 H1 + deck + 古铜 endmark + metadata 小字
- **Section heading**：罗马数字 italic（"II"）+ 章节陈述句标题（22pt navy）+ 顶部 1pt navy hairline；不再分页符强制（编辑型推崇连贯阅读）

### 5.7 emit_chart 调整

保持 matplotlib PNG 嵌入策略，新增主题应用：

```python
from backend.tools.report._chart_renderer import render_chart_to_png
png = render_chart_to_png(option, theme=self._theme)  # theme 传入 mpl_theme
# 标题/副标题/source 用 Heading 3 + Source style，不再让 chart 自渲染
self._doc.add_paragraph(title, style="Heading 3")
self._doc.add_picture(BytesIO(png), width=Inches(6.0))
self._doc.add_paragraph(source, style="Source")
```

---

## 6. PPTX 实施细节

### 6.1 Slide 母版与全局规格

| 属性 | 值 |
|---|---|
| 比例 | 16:9 |
| 尺寸 | 13.333" × 7.5"（`Inches(13.333) × Inches(7.5)`） |
| 母版背景 | 实色填充 #FBF6EE |
| 页边 | 上 0.5"、下 0.5"、左 0.6"、右 0.6"（内容区 12.133" × 6.5"） |
| 母版页眉 | 左：kicker（"辽港集团 · 设备运营月报 · 2026-04"，font_ui 8pt smcp #AC916B 字距加宽） |
| 母版页脚 | 左：页码（font_ui 9pt #004889）；右：endmark 古铜 6×6pt + metadata 小字 |

### 6.2 Slide 类型清单

| Slide | 触发 | 布局要点 |
|---|---|---|
| Cover | 文档开头 | H1（font_display 32pt navy）+ deck（italic 18pt #5E5648）+ 顶部古铜 brand bar 4×40pt + 元信息小字（作者/日期 9pt smcp #AC916B） |
| TOC | Cover 后 | "目  录" 大字（display 24pt navy）+ section list（font_display 14pt + 罗马数字 italic 古铜） |
| Section Divider | 每章首 | 左侧大罗马数字（font_display italic 120pt #AC916B）+ 右侧章节陈述标题（28pt #004889）+ 顶部 1pt navy hairline |
| Lede / Narrative | 段落叙述 | 顶 kicker + 大 lede（italic 18pt）+ 正文（11pt 1.5x）+ 左侧 4×80pt 古铜 brand bar |
| Chart | 图表 | 顶 figure title（serif 14pt）+ 副标题（sans 10pt）+ chart 占内容区 70% 高度 + 底 source（italic 9pt）+ 右下 endmark |
| Chart + KPI Strip | 趋势图 | chart 占上 60%，下方 4 列 KPI（mono 28pt navy）+ 上下 hairline；不再独占两张 slide |
| Pull-quote | 推荐每章 1 张 | 全屏 1/3 区大斜体引语（display italic 28pt）+ 左侧 8×120pt 古铜竖条 + attribution 小字 |
| Appendix Cover | 附录前 | 同 Section Divider 但反转：古铜底 + paper 字 |
| Appendix Detail | 完整数据 | 满版 agate 大表，最多 15 行；超出再分页 |
| Closing | 文档末 | "结语" + metadata + 大 endmark 古铜方块居中 |

### 6.3 build_section_divider_slide 重写

```python
def build_section_divider_slide(prs, number, title, theme):
    slide = _blank(prs)
    _set_bg(slide, theme.bg_light)  # 纸色，不再 navy 实色
    # 左侧大罗马数字
    roman = _to_roman(number)  # 1 -> I, 2 -> II ...
    _add_textbox(slide,
        Inches(0.6), Inches(2.0), Inches(4.0), Inches(3.5),
        roman, font_size=120, italic=True, bold=False,
        color=theme.accent, font_name=theme.font_display)
    # 顶部 hairline
    _add_rect(slide, Inches(0.6), Inches(0.6), Inches(12.13), Inches(0.012),
              theme.primary)
    # 右侧标题
    _add_textbox(slide,
        Inches(5.5), Inches(3.0), Inches(7.0), Inches(2.0),
        title, font_size=28, bold=True,
        color=theme.primary, font_name=theme.font_display)
    # 右下 endmark
    _add_rect(slide, Inches(12.7), Inches(7.0), Inches(0.13), Inches(0.13),
              theme.accent)
```

### 6.4 build_kpi_strip_slide 与 build_chart_with_kpi_slide

`build_kpi_strip_slide(prs, title, kpis: list[KPIItem4], theme)`：
- 顶 figure title
- 4 个 textbox 横向均分（每个 ~3" 宽）
- 每个 box 三段：label（smcp 9pt ink_3）+ value（mono 28pt navy/accent_dark）+ sub（ui 9pt ink_3）
- 上下两条 1pt navy line shape

`build_chart_with_kpi_slide(prs, title, sub, source, chart_image_or_native, kpis, theme)`：
- 顶 6.5" 高 chart 区
- 下 4 列 KPI（无 box 高度 1"）
- 底 source（italic 9pt）

### 6.5 pptxgenjs 主题注入

`_pptxgen_builder.py:_base_options` 改为：

```python
def _base_options(n_series: int, theme) -> dict[str, Any]:
    return {
        "chartArea": {"fill": {"color": theme.hex_bg_light}, "roundedCorners": False},
        "plotArea": {"fill": {"color": theme.hex_bg_light}},
        "valGridLine": {"color": "1F1A1219", "size": 0.5},
        "catGridLine": {"color": "transparent"},
        "showLegend": False,
        "showTitle": False,                  # 标题交给外层 textbox
        "catAxisLineShow": False,
        "valAxisLineShow": False,
        "valAxisOrientation": "right",       # Y 轴右置
        "chartColors": list(theme.chart_colors),
        "fontFace": theme.font_ui,
        "fontSize": 9,
        "color": theme.hex_text_dark,
    }
```

`_pptxgen_commands.py` 在 `AddText` / `AddShape` 默认 fill / color 字段加 theme-aware 默认。

### 6.6 emit_chart_table_pair 改造

```python
def emit_chart_table_pair(self, block, chart_asset, table_asset):
    # 主流程：chart slide（含 KPI strip）+ 推送 table 到 appendix buffer
    self._chart_with_kpi_slide(block, chart_asset)
    self._appendix_buffer.append((block, table_asset))
```

### 6.7 附录 deck 实现

`PptxBlockRenderer` 增加：
```python
self._appendix_buffer: list[tuple[Any, Asset]] = []
```

`end_document` 在 `prs.save` 前：
```python
if self._appendix_buffer:
    S.build_appendix_cover_slide(self._prs, self._theme)
    for block, asset in self._appendix_buffer:
        S.build_appendix_detail_slide(self._prs, block, asset, self._theme)
```

`build_appendix_detail_slide` 用 agate 大表布局，行数超过 15 行时按 15 行切分多张 slide。

---

## 7. 共享层改动

### 7.1 `_theme.py`

#### 7.1.1 Theme dataclass 扩展

```python
@dataclass(frozen=True)
class Theme:
    # ... 现有字段
    # === 新增 ===
    font_display: str = ""               # 默认空表示沿用 font_cn
    font_ui: str = ""                    # 默认空表示沿用 font_cn
    font_cn_fallbacks: tuple[str, ...] = ()
    font_ui_fallbacks: tuple[str, ...] = ()
    font_mono_fallbacks: tuple[str, ...] = ()

    def __post_init__(self):
        # display/ui 默认 fallback 到 cn
        object.__setattr__(self, "font_display", self.font_display or self.font_cn)
        object.__setattr__(self, "font_ui", self.font_ui or self.font_cn)
```

#### 7.1.2 LIANGANG_JOURNAL preset 完整定义

详见 §1。注册到 `THEMES` dict：
```python
THEMES = {
    "corporate-blue": CORPORATE_BLUE,
    "liangang-journal": LIANGANG_JOURNAL,
}
```

#### 7.1.3 默认 theme 切换时机

- PR-1：注册 `LIANGANG_JOURNAL` 但**默认仍是 corporate-blue**
- PR-2：`get_theme(None)` 默认值改为 `LIANGANG_JOURNAL`
- 或通过环境变量 `ANALYTICA_THEME=liangang-journal` 控制

### 7.2 `_outline.py`

新增 `KpiStripBlock`：
```python
@dataclass
class KpiStripItem:
    label: str          # "起点"/"高点"/"当前"/"变化"
    value: str          # 已格式化数值字符串（"7.9%"、"-2.3pp"）
    sub: str = ""       # metadata（"2026-02"、"环比"）
    trend: str = ""     # "gain" | "loss" | ""

@dataclass
class KpiStripBlock(Block):
    block_id: str
    items: tuple[KpiStripItem, ...]   # 固定 4 项
```

### 7.3 `_block_renderer.py`

抽象方法：
```python
class BlockRendererBase:
    def emit_kpi_strip(self, block: KpiStripBlock) -> None:
        raise NotImplementedError
```

### 7.4 `_outline_planner.py`

#### 7.4.1 趋势数据自动生成 KpiStripBlock

```python
def _trend_to_kpi_strip(df, time_col, value_col, label_template) -> KpiStripBlock:
    first = df.iloc[0]
    last = df.iloc[-1]
    max_row = df.loc[df[value_col].idxmax()]
    delta = last[value_col] - first[value_col]
    return KpiStripBlock(items=(
        KpiStripItem("起点", fmt(first[value_col]), str(first[time_col])),
        KpiStripItem("高点", fmt(max_row[value_col]), str(max_row[time_col])),
        KpiStripItem("当前", fmt(last[value_col]), str(last[time_col]),
                     trend="gain" if delta > 0 else "loss"),
        KpiStripItem("变化", fmt_delta(delta), "环比",
                     trend="gain" if delta > 0 else "loss"),
    ))
```

#### 7.4.2 表格行数裁剪

```python
def _trim_table_for_inline(df, max_rows=5):
    """超过 max_rows 时返回 top-N + 合计行；否则返回原 df。"""
    if len(df) <= max_rows:
        return df, False  # 不需要折叠
    top = df.nlargest(max_rows, key_col)
    rest_sum = df.drop(top.index).sum(numeric_only=True)
    rest_row = pd.DataFrame([{key_col: f"其余 {len(df) - max_rows} 类合计", **rest_sum}])
    return pd.concat([top, rest_row]), True  # 截断标志
```

### 7.5 `_planner_prompts.py`

新增写作约束：

1. **图表标题必须是陈述句**：禁用"数据对比""趋势图""分布图"等通用词；要求形如"二月设备利用率跌至五月最低"
2. **每个 chart 必须配 source 行**：planner 在 ChartBlock 上新增 `source: str` 字段
3. **KPI strip 是默认配置**：trend 类数据 planner 必须输出 KpiStripBlock；分类比较类输出 ≤5 行 TableBlock
4. **few-shot 样例**：在 prompt 加 2-3 个编辑式标题样例

### 7.6 `_chart_renderer.py` (matplotlib)

新增 `_chart_renderer_mpl_theme.py`，配置 rcParams：

```python
def apply_mpl_theme(theme):
    plt.rcParams.update({
        "figure.facecolor": theme.css_bg_light,
        "axes.facecolor": theme.css_bg_light,
        "axes.edgecolor": theme.css_neutral,
        "axes.labelcolor": theme.css_text_dark,
        "axes.titlecolor": theme.css_text_dark,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.spines.left": False,
        "axes.spines.bottom": False,
        "axes.grid": True,
        "axes.grid.axis": "y",
        "grid.color": "#1F1A1219",
        "grid.linewidth": 0.5,
        "ytick.color": theme.css_text_dark,
        "xtick.color": theme.css_text_dark,
        "ytick.major.size": 0,
        "xtick.major.size": 0,
        "font.family": [theme.font_ui] + list(theme.font_ui_fallbacks),
        "font.size": 9,
        "axes.prop_cycle": cycler("color", ["#" + c for c in theme.chart_colors]),
    })
```

### 7.7 Dockerfile / 部署

详见 §2.1。

### 7.8 字体启动自检

`backend/main.py` 启动钩子：

```python
@app.on_event("startup")
async def check_fonts_on_startup():
    missing = check_fonts()
    if missing:
        logger.warning("Missing fonts: %s. Reports will fall back to system defaults.",
                       ", ".join(missing))

@app.on_event("startup")
async def check_pptxgenjs_bridge():
    healthy = await probe_pptxgenjs_bridge()
    if not healthy:
        logger.critical("pptxgenjs bridge unavailable - PPTX generation will be blocked")
```

---

## 8. 表格简化规则

### 8.1 三层数据呈现策略

| 层 | 内容 | 形式 |
|---|---|---|
| L1 视觉首阅 | 一句话结论 + 关键值 | H2 编辑标题 + lede 段 |
| L2 主体 | 趋势图 + 4 个 KPI 大数 | chart + KPI strip |
| L3 完整数据 | 全部明细 | 折叠（HTML）/ 章末（DOCX）/ 附录 deck（PPTX） |

### 8.2 数据形态分流

| 数据形态 | HTML L2 | HTML L3 | DOCX L2 | DOCX L3 | PPTX L2 | PPTX L3 |
|---|---|---|---|---|---|---|
| 趋势（≥6 时间点） | KPI strip | `<details>` 全表 | KPI strip | 章末小节 | KPI strip slide | 附录 slide |
| 类别（>5 类） | top5+合计 agate 表 | `<details>` 全表 | top5+合计 hairline 表 | 章末小节 | top5 agate slide | 附录 slide |
| 类别（≤5 类） | 完整 agate | — | 完整 hairline | — | 完整 agate | — |
| stats（多维统计） | agate（≤5 列） | — | hairline | — | KPI cards 拆 + agate | 完整 |
| 饼图/环形 | 仅图（标 label） | `<details>` 全表 | 仅图 + 章末 | 章末 | 仅图 slide | 附录 slide |
| 散点 | 仅图（标异常点） | `<details>` 全表 | 仅图 + 章末 | 章末 | 仅图 | 附录 |

### 8.3 KPI strip 固定结构

```
┌─────────┬─────────┬─────────┬─────────┐
│  起点   │   高点   │   当前   │   变化   │
│  0.998  │  7.9%   │  5.6%   │ -2.3pp  │
│ 2026-01 │ 2026-02 │ 2026-04 │  环比    │
└─────────┴─────────┴─────────┴─────────┘
```

由 planner 在 `_outline_planner.py` 自动从 trend 数据生成；不需要 LLM 写作。

### 8.4 折叠阈值

- **HTML**：行数 ≥6 自动 `<details>` 折叠
- **DOCX**：所有 chart_table_pair 的 table 一律推到章末（不区分行数，节奏更整齐）
- **PPTX**：所有 chart_table_pair 的 table 一律推到附录 deck

---

## 9. PR 拆分计划（四段）

### PR-1 共享基础设施（无视觉变化）

**目标**：landing 不影响现有视觉的所有共享层改动；保持 `corporate-blue` 为默认 theme。

**包含**：
- §7.1 `_theme.py`：扩展 Theme dataclass + 注册 `LIANGANG_JOURNAL`（不切默认）
- §7.2 `_outline.py`：新增 `KpiStripBlock` / `KpiStripItem`
- §7.3 `_block_renderer.py`：抽象方法签名（base class 实现成 no-op，向后兼容）
- §7.4 `_outline_planner.py`：新增 `_trend_to_kpi_strip` / `_trim_table_for_inline`，但门控在新 flag 后（`USE_KPI_STRIP=False` 默认）
- §7.5 `_planner_prompts.py`：新增 prompt 片段（不切默认 prompt）
- §7.6 `_chart_renderer_mpl_theme.py`：新文件
- §7.7 Dockerfile：装字体 + Node.js + pptxgenjs bridge 环境
- §7.8 字体自检 + pptxgenjs bridge 启动期检测
- §7.9 `_retry_config.py`：重试策略配置（共享层骨架，renderer 尚未接入）
- §7.10 `_quality_reviewer.py`：LLM 后置审查模块骨架 + `ReviewResult` 数据结构
- 测试：theme 注册测试、KpiStripBlock dataclass 测试、降级测试、bridge 可用性测试

**验收标准**：
- 现有 baseline 测试全绿
- 新 theme 可被 `get_theme("liangang-journal")` 取出但未被任何 renderer 默认使用
- Dockerfile 构建后 `fc-list | grep -i noto` 有输出，`node -v` 和 pptxgenjs bridge health check 通过
- PR 大小：~800 行新增 + ~60 行修改

### PR-2 HTML 重设计（用户首先看到的视觉变化）

**目标**：HTML 报告完全切到辽港数据期刊视觉；DOCX/PPTX 仍用旧版 layout 但应用新色板（轻量适配）。

**包含**：
- §7 中 `get_theme` 默认改为 `liangang-journal`
- §4.1-4.7 全部 HTML 重写
- §7.4 `_outline_planner.py`：把 `USE_KPI_STRIP` flag 切到 `True`（影响所有 renderer，但 DOCX/PPTX 暂时把 KpiStripBlock fallback 成简易 KPI row 显示）
- DOCX/PPTX 的 `emit_kpi_strip` 暂时实现为 minimal（沿用现有 KPI row 渲染样式但用新色板）
- 修复 chart-table 重叠 bug（§4.3 RAF 包裹）
- HTML renderer 接入重试装饰器（规划层 JSON/标题重试）
- HTML renderer 接入 LLM 后置审查（数据准确性 + 标题质量 + 结构完整性）
- 测试：HTML baseline 全量回写 + sample 渲染人工 review

**验收标准**：
- HTML 渲染样例完全切新视觉
- DOCX/PPTX 不崩，色板更新
- chart-table 重叠 bug 消失
- PR 大小：~1200 行 HTML/CSS + ~200 行 Python

### PR-3 DOCX 重设计

**目标**：DOCX 报告完全切到辽港数据期刊视觉。

**包含**：
- §5.1 styles.xml 自定义样式表
- §5.2 Hairline Table
- §5.3 KPI strip（DOCX 版）
- §5.4 Drop cap
- §5.5 章末附录实现（含 buffering 模型 + 跳转锚点）
- §5.6 Cover / Section divider 重做
- §5.7 emit_chart 调整 + mpl theme 接入
- DOCX renderer 接入重试装饰器（matplotlib OOM 重试）
- DOCX renderer 接入 LLM 后置审查
- 测试：DOCX baseline 全量回写

**验收标准**：
- Word / WPS 打开样例无格式错乱
- LibreOffice 打开降级渲染（dropCap 退化为 italic 即可）
- 章末附录跳转链接生效
- PR 大小：~800 行 Python

### PR-4 PPTX 重设计

**目标**：PPTX 报告完全切到辽港数据期刊视觉，含附录 deck。

**包含**：
- §6.1 母版 + 16:9 切换
- §6.2 全部 slide 类型实现
- §6.3 build_section_divider_slide 重写
- §6.4 KPI strip slide / chart with KPI slide
- §6.5 pptxgenjs 主题注入
- §6.6 emit_chart_table_pair 改造
- §6.7 附录 deck 自动生成
- `emit_chart` 移除 PNG fallback 分支：pptxgenjs 不可用时直接 raise，不降级
- PPTX renderer 接入重试装饰器（bridge timeout 指数退避重试）
- PPTX renderer 接入 LLM 后置审查（全维度覆盖）
- 测试：PPTX baseline 全量回写 + 投影/PPT/WPS 三处人工 review
- 环境验收：pptxgenjs bridge health check 通过（阻断性）

**验收标准**：
- PowerPoint / Keynote / WPS 打开样例无错乱
- 16:9 投影显示正确
- 附录 slide pack 按预期附在末尾
- pptxgenjs bridge health check 通过，bridge 不可用时 PPTX 生成直接报错而非降级
- PR 大小：~1000 行 Python + ~100 行 JS（pptxgenjs 路径）

### PR 之间的依赖

```
PR-1 (基础) ──→ PR-2 (HTML) ──→ PR-3 (DOCX) ──→ PR-4 (PPTX)
                  │                  │                │
                  └─ 切默认 theme ────┴─ DOCX/PPTX 仍兼容
```

任一 PR 必须基于前一 PR merge 后的 main 分支。

---

## 10. 测试策略

### 10.1 Baseline 测试

`tests/contract/test_report_outputs_baseline.py` 现有 byte-level 比对会全部破坏。计划：

1. PR-1：保持 baseline 不变（无视觉改动）
2. PR-2：在 PR 中加 `update_baseline=True` flag 一次性回写 HTML baseline；human review 后锁定
3. PR-3：同上，回写 DOCX baseline
4. PR-4：同上，回写 PPTX baseline

每次回写需 PR 描述附 sample 渲染截图，2 人 review 通过后 merge。

### 10.2 字体降级测试

新增 `tests/test_font_fallback.py`：在 fontconfig 强制移除 Noto CJK 后调用 renderer，验证：
- 不抛异常
- 输出文件可被对应应用打开
- WARN log 包含字体缺失提示

### 10.3 跨格式视觉对照

新增 `tests/visual/test_cross_format_consistency.py`（半人工）：
- 用同一份 outline 生成三个格式
- 输出到 `tests/visual/__output__/` 供 review
- CI 跳过；本地 `pytest -m visual` 执行

### 10.4 KpiStripBlock 单测

每个 renderer 的 `emit_kpi_strip` 都有单元测试，覆盖：
- 4 项完整渲染
- trend=gain/loss 颜色切换
- 空 sub 字段降级
- 数字溢出（"-1234.56pp"）布局

### 10.5 LLM 标题质量门控

`_planner_prompts.py` 加 validator：

```python
GENERIC_CHART_TITLES = {"数据对比", "趋势图", "分布图", "对比图", "图表"}
def validate_chart_title(title: str) -> bool:
    """returns False if title is generic; planner will retry."""
    return title and title not in GENERIC_CHART_TITLES and len(title) >= 6
```

planner 检测到通用标题最多重试 1 次；仍失败则降级到外层 H 标题承担语义。

---

## 11. 风险登记册

| ID | 风险 | 级别 | 缓解 | 责任 PR |
|---|---|---|---|---|
| R1 | 服务端缺字体 → 中文乱码 | 高 | Dockerfile 装字体 + 启动期自检 + Theme fallback | PR-1 |
| R2 | DOCX dropCap 在 LibreOffice 异常 | 中 | 提供 `enable_dropcap` 配置；默认开 | PR-3 |
| R3 | pptxgenjs Node bridge 不可用 → PPTX 无法生成矢量图表 | 高 | Dockerfile 预装 Node.js 环境 + 启动期强制检测 + 不可用时直接阻断（不降级） | PR-1, PR-4 |
| R4 | LLM 写不出陈述式图表标题 | 中 | prompt few-shot + validator 重试 | PR-1 |
| R5 | 附录 slide 过长（>30 张） | 低 | 配置项 `appendix_max_slides=20`，超出折叠为指引 slide | PR-4 |
| R6 | 三格式 baseline 全量回写 | 中 | 一次性回写 + 强制人工 review + 截图存档 | 各 PR |
| R7 | Office 旧版本古铜色偏差 | 低 | 接受；目标平台 Office 365 / WPS 最新 | — |
| R8 | 字体许可争议 | 低 | 已选均为 OFL/SIL/Apache 开源许可 | PR-1 |
| R9 | 中英自动加空格 regex 误伤 | 低 | 跳过 `<code>/<pre>/<script>/<style>` | PR-2 |
| R10 | 思源/Noto 字体加载导致 HTML 首屏慢 | 低 | `font-display: swap` + preconnect | PR-2 |
| R11 | DOCX 章末附录链接在 WPS 跳转异常 | 低 | 接受降级为锚点滚动；不阻断阅读 | PR-3 |
| R12 | 16:9 切换破坏现有用户的 4:3 模板预期 | 低 | 在 release notes 公示；PPTX 不向后兼容 | PR-4 |
| R13 | Review LLM 自身误判（将正确内容标为 FAIL） | 中 | BLOCKING 维度尽量用规则检查而非 LLM；叙述连贯性仅 WARNING | PR-1 |
| R14 | 重试导致单次生成耗时过长 | 中 | 单 block 累计 ≤3 次 + 整文档累计 ≤12 次 + 全流程硬超时 5min（含 Review） | PR-1 |

---

## 12. 生成质量保障

### 12.1 问题背景

当前方案仅在 §10.5 存在单一重试点（LLM 图表标题检测到通用词后重试 1 次），报告生成流水线整体缺乏系统化的运行时质量控制。具体缺失：

- **规划阶段**：JSON 格式畸形、缺少必要 block、数据引用列名错误——均无重试，直接失败
- **渲染阶段**：pptxgenjs bridge 超时、图表渲染 OOM——无重试，直接降级或失败
- **生成后**：报告输出无独立的自动化质量审查，质量完全依赖生成阶段的一次性正确

参考业界深度分析产品（如 Perplexity、ChatGPT Deep Research），重试 + 后置审查是确保报告质量的标准手段。

### 12.2 生成重试策略

#### 12.2.1 重试粒度

以 **block 为最小重试单元，以 chapter 为兜底**：

| 粒度 | 适用场景 | 不适用场景 |
|------|----------|------------|
| 单 block 重试 | 图表标题写砸、JSON 字段缺失 | narrative 整体跑偏 |
| 单 chapter 重试 | 数据引用列名全章错误、narrative 语义断裂 | — |
| 整文档重试 | — | 代价过高，不在自动流程中触发 |

#### 12.2.2 可重试错误分类

| 阶段 | 错误类型 | 重试次数 | 重试策略 |
|------|----------|----------|----------|
| 规划 | JSON 格式畸形 | 2 | prompt 追加 JSON 格式纠正提示 |
| 规划 | 缺失必要 block（如 trend 数据无 chart） | 1 | prompt 明确要求 block 类型列表 |
| 规划 | 数据引用列名错误（LLM 编造了不存在的字段名） | 1 | prompt 回注实际可用数据列名 |
| 规划 | 图表标题为通用词（"数据对比""趋势图"等） | 1 | prompt 追加陈述式标题样例（已有，§10.5） |
| 渲染 | pptxgenjs bridge timeout | 2 | 指数退避（1s → 4s） |
| 渲染 | matplotlib 图表渲染 OOM | 1 | 降分辨率重试 |
| 渲染 | 中文字体乱码 | 0 | 走字体 fallback 链，不重试 |

#### 12.2.3 约束

以下约束覆盖整个生成周期（含 Review 重试），所有重试共享同一计数器，避免绕过。

| 约束项 | 值 | 说明 |
|--------|----|------|
| 单 block 累计重试上限 | 3 次 | 覆盖生成期 + Review 触发的全部重试；达到后该 block 永久放弃，返回部分成功 |
| 整文档累计重试上限 | 12 次 | 覆盖所有 block 的全部重试次数之和；达到后剩余重试请求全部拒绝 |
| Review 最大轮次 | 2 轮 | Review → 重试 → 再 Review 为一轮；2 轮后仍有 BLOCKING 失败则返回部分成功 |
| 全流程超时 | 5 分钟 | 从生成开始到最终 Review 完成（含 Review 和 Review 触发的重试）；超时返回部分成功 |
| 部分成功保留 | 是 | 已成功渲染的 block 不因其他 block 的重试而丢弃 |
| prompt 渐进增强 | 是 | 每次重试在 prompt 中注入更详细的错误上下文；Review 后的重试额外注入上一轮 Review 的具体问题描述 |

#### 12.2.4 实现位置

| 模块 | 职责 |
|------|------|
| `backend/tools/report/_retry_config.py` | 重试策略配置（次数、超时、退避策略） |
| `backend/tools/report/_outline_planner.py` | 规划层重试循环（JSON 校验 → 重试 → 失败则抛错） |
| `backend/tools/report/_block_renderer.py` | 渲染层重试装饰器（各 renderer 共用） |

### 12.3 LLM 后置审查

#### 12.3.1 审查时机与流程

```
报告生成完成 → LLM Review → PASS → 交付用户
                    │
                    │ FAIL
                    ▼
           标记问题 block
                    │
                    ▼
           单 block 重试 → 再次 Review
                              │
                        PASS  │ FAIL（最多 2 轮 total review）
                        交付   └→ 返回部分成功 + 错误标注
```

审查在所有 renderer 输出完成后、交付用户前触发。若 FAIL，重试后再次审查，最多 2 轮 total review。

#### 12.3.2 审查模型

使用**独立的 review prompt** 以避免 self-review 效应。若部署环境支持多个 LLM 后端，推荐用与生成阶段不同的模型做交叉检查。

#### 12.3.3 审查维度

| 维度 | 检查方式 | 级别 | 不通过时的动作 |
|------|----------|------|---------------|
| 数据准确性 | 从报告随机抽样 3-5 个数值断言，与原始 DataFrame 交叉验证 | **BLOCKING** | 标记对应 block，触发重试 |
| 标题质量 | §10.5 validator 词表 + LLM 语义判断是否为陈述句 | **BLOCKING** | 标记对应 chart block，触发重试 |
| 结构完整性 | 规则检查：每个 chapter 是否含 chart → KPI strip → 完整数据折叠 | **BLOCKING** | 标记缺失 block 的 chapter，触发重试 |
| 叙述连贯性 | LLM 通读全章后打分 (1-5) | **WARNING** | <3 分打 warn log + 标注在交付物 metadata |
| 视觉一致性 | 检测 CSS 变量/字体/字号是否偏离 Token 规范 | **WARNING** | 打 warn log + 标注在交付物 metadata |

- **BLOCKING**：不通过则必须重试对应 block/chapter
- **WARNING**：低于阈值记录日志并标注在交付物 metadata 中，不阻断交付

#### 12.3.4 实现位置

新增 `backend/tools/report/_quality_reviewer.py`：

```python
from dataclasses import dataclass, field

@dataclass
class ReviewFinding:
    dimension: str        # "data_accuracy" | "title_quality" | ...
    passed: bool
    severity: str         # "BLOCKING" | "WARNING"
    detail: str           # 人类可读的问题描述
    block_ids: list[str]  # 涉及的问题 block ID

@dataclass
class ReviewResult:
    passed: bool                             # 所有 BLOCKING 均通过
    findings: list[ReviewFinding]
    retry_targets: list[str]                 # 需要重试的 block/chapter ID

class ReportQualityReviewer:
    def review(self, report: Report, source_data: dict) -> ReviewResult:
        findings = [
            self._check_data_accuracy(report, source_data),
            self._check_title_quality(report),
            self._check_structure_completeness(report),
            self._check_narrative_coherence(report),
            self._check_visual_consistency(report),
        ]
        blocking = [f for f in findings if f.severity == "BLOCKING" and not f.passed]
        retry_targets = list(set(bid for f in blocking for bid in f.block_ids))
        return ReviewResult(
            passed=len(blocking) == 0,
            findings=findings,
            retry_targets=retry_targets,
        )
```

### 12.4 三层质量防线总览

```
┌──────────────────────────────────────────────────────┐
│                    第 1 层：预生成测试                  │
│  §10 测试策略：baseline 回写、单测、跨格式对照          │
│  时机：开发期 / CI                                     │
│  目的：确保代码变更不破坏已有渲染结果                    │
└──────────────────────────┬───────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────┐
│                    第 2 层：生成期重试                  │
│  §12.2：规划层 JSON/标题重试 + 渲染层 bridge/OOM 重试   │
│  时机：每次用户请求报告生成时                            │
│  目的：自动修复生成过程中可恢复的瞬时错误                │
└──────────────────────────┬───────────────────────────┘
                           ▼
┌──────────────────────────────────────────────────────┐
│                    第 3 层：生成后审查                  │
│  §12.3：LLM Review 五维度交叉检查 + 必要时触发重试       │
│  时机：所有 renderer 输出完成后、交付用户前              │
│  目的：确保交付物达到数据期刊品质标准                    │
└──────────────────────┬───────────────────────────────┘
                       ▼
                   交付用户
```

### 12.5 对 PR 拆分的影响

| PR | 质量保障相关改动 |
|----|-----------------|
| **PR-1** | 新增 `_retry_config.py`（共享层骨架）+ `_quality_reviewer.py`（`ReviewResult` 数据结构 + 规则检查维度）+ `_outline_planner.py` 规划层重试循环 |
| **PR-2** | HTML renderer 接入重试装饰器 + 接入 LLM 后置审查（数据准确性 + 标题质量 + 结构完整性） |
| **PR-3** | DOCX renderer 接入重试装饰器 + 接入 LLM 后置审查 |
| **PR-4** | PPTX renderer 接入重试装饰器（bridge timeout 指数退避）+ 接入 LLM 后置审查（全维度覆盖） |

---

## 13. 实施前置任务

按此顺序执行：

### 13.1 决策签字

- [ ] 上轮 5 个默认值（D1-D5）由 PM/Tech Lead 签字确认 / 调整
- [ ] PR 评审委员（至少 2 人，含 1 名熟悉 OOXML 的）

### 12.2 设计资产

- [ ] 准备 3 份样本 outline（短/中/长，覆盖各类 block 类型）
- [ ] 准备 sample 数据（趋势、类别、stats）
- [ ] 准备 PPTX 模板预览（投影实测）

### 12.3 环境准备

- [ ] CI 镜像加字体
- [ ] 本地开发文档说明字体安装方式
- [ ] PowerPoint / Keynote / WPS 测试环境就绪

### 13.4 Baseline 回写流程

- [ ] 定义 baseline 回写 review checklist（截图、字体、色板、layout 四项）
- [ ] 设置 `update_baseline=True` 的 PR 标记规则

---

## 14. 附录 A：完整设计 token 清单

详见 §1。本节为 Theme dataclass 完整赋值，可直接 copy 到 `_theme.py`：

```python
LIANGANG_JOURNAL = Theme(
    name="liangang-journal",
    primary=(0x00, 0x48, 0x89),
    secondary=(0x33, 0x6E, 0xA4),
    accent=(0xAC, 0x91, 0x6B),
    positive=(0x00, 0x48, 0x89),
    negative=(0x8B, 0x4A, 0x2B),
    neutral=(0x9A, 0x8E, 0x78),
    bg_light=(0xFB, 0xF6, 0xEE),
    white=(0xFF, 0xFE, 0xFB),
    text_dark=(0x1F, 0x1A, 0x12),
    font_cn="Noto Serif SC",
    font_num="JetBrains Mono",
    font_display="Noto Serif SC",
    font_ui="Noto Sans SC",
    font_cn_fallbacks=("Source Han Serif SC", "Songti SC", "STSong", "SimSun"),
    font_ui_fallbacks=("PingFang SC", "Microsoft YaHei", "SimHei"),
    font_mono_fallbacks=("IBM Plex Mono", "Consolas", "Menlo", "Courier New"),
    size_title=32,
    size_h1=22,
    size_h2=16,
    size_h3=14,
    size_body=11,
    size_small=9,
    size_kpi_large=28,
    size_kpi_label=8,
    size_table_header=9,
    size_table_body=10,
    slide_width=13.333,
    slide_height=7.5,
    chart_colors=(
        "004889", "AC916B", "80A4C2", "CFAB79", "336EA4", "8B4A2B",
    ),
    cover_bg=(0xFB, 0xF6, 0xEE),
)
```

---

## 15. 附录 B：参考文献

- [The Economist visual style guide - Fountn](https://fountn.design/resource/the-economist-visual-style-guide/)
- [What Makes The Economist's Charts So Good? - Tim van Schaick](https://medium.com/@timvanschaick/what-makes-the-economists-charts-so-good-0234e4271da3)
- [What We Can Learn From The Economist About Data Visualization - Prezlab](https://prezlab.com/what-we-can-learn-from-the-economist-about-data-visualization/)
- [From Data to Storytelling: John Burn-Murdoch (FT) - GIJN](https://gijn.org/stories/data-visualization-storytelling-tips-john-burn-murdoch/)
- [W3C Requirements for Chinese Text Layout 中文排版需求](https://www.w3.org/TR/2015/WD-clreq-20150723/)
- [Source Han Serif (思源宋体) - Adobe Fonts](https://fonts.adobe.com/fonts/source-han-serif-simplified-chinese)
- [Chinese Copywriting Guidelines (sparanoid)](https://github.com/sparanoid/chinese-copywriting-guidelines)
- 辽港集团 VI 手册 A10 标准色（用户提供）

---

**文档结束。**
