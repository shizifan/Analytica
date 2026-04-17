# Analytica 三阶段综合测试报告

## 测试概况

| 项目 | 数据 |
|------|------|
| 测试日期 | 2026-04-15 11:26 |
| 测试总数 | 36 |
| 通过数 | 36 |
| 失败数 | 0 |
| 通过率 | 100.0% |
| 总耗时 | 1.1s |

## 阶段汇总

| 阶段 | 测试数 | 通过 | 失败 | 状态 |
|------|--------|------|------|------|
| Phase 1: 感知层 | 10 | 10 | 0 | PASS |
| Phase 2: 规划层 | 9 | 9 | 0 | PASS |
| Phase 3: 执行层 | 14 | 14 | 0 | PASS |
| E2E: 全链路 | 3 | 3 | 0 | PASS |

---

## Phase 1: 感知层测试详情

感知层负责从自然语言中提取分析意图（槽位填充），支持多轮追问和旁路跳过。

| TC | 测试名称 | 验证内容 | 结果 |
|----|----------|----------|------|
| P1-01 | Single Turn Full Extraction | 单轮输入完整提取 analysis_subject, time_range, output_complexity | PASS |
| P1-02 | Partial Extraction Triggers Clarification | 缺少必需槽位时触发追问 | PASS |
| P1-03 | Multi Turn Slot Filling | 多轮对话逐步填充所有必需槽位 | PASS |
| P1-04 | Bypass Fills Defaults | '按你理解执行' 旁路跳过填充默认值 | PASS |
| P1-05 | Max Rounds Fills Defaults | 达到最大追问轮数自动填充默认值 | PASS |
| P1-06 | Build Structured Intent | 从完整槽位构建 StructuredIntent 对象 | PASS |
| P1-07 | Memory Prefill Inferable Only | 记忆只预填充 inferable=True 的槽位 | PASS |
| P1-08 | Llm Output Cleaning | <think> 标签和 markdown 代码块正确剥离 | PASS |
| P1-09 | Source Priority Protection | 低优先级源不能覆盖高优先级源的值 | PASS |
| P1-10 | Multi Slot Clarification | 多个空槽位合并为一条追问 | PASS |

### 感知层数据查询结果

以下为感知层测试中的槽位提取结果示例：

**P1-01 单轮完整提取场景：**
```
输入: "帮我查一下2026年第一季度集装箱吞吐量"
提取结果:
  analysis_subject: ["集装箱吞吐量"] (source=user_input, confirmed=True)
  time_range: {start: "2026-01-01", end: "2026-03-31", description: "2026年第一季度"}
  output_complexity: "simple_table" (source=user_input)
```

**P1-03 多轮追问场景：**
```
Round 0: "看下月度吞吐量趋势" -> 提取 analysis_subject=["月度吞吐量趋势"]
  -> 追问: 请问您需要分析哪个时间段？
Round 1: "最近一年的，看趋势图" -> 提取 time_range=最近一年, output_complexity=chart_text
  -> 所有必需槽位已填充，构建 StructuredIntent
```

## Phase 2: 规划层测试详情

规划层基于 StructuredIntent 调用 LLM 生成 AnalysisPlan，验证技能/端点合法性。

| TC | 测试名称 | 验证内容 | 结果 |
|----|----------|----------|------|
| P2-01 | Simple Table Plan Generation | simple_table 生成 2-3 个任务 (data_fetch + analysis) | PASS |
| P2-02 | Chart Text Plan Has Visualization | chart_text 包含可视化任务 (折线图/柱状图) | PASS |
| P2-03 | Hallucinated Skills Filtered | LLM 幻觉出的虚假技能被自动过滤 | PASS |
| P2-04 | Mcode Resolution | M-code (如 M04) 自动解析为端点函数名 | PASS |
| P2-05 | Circular Dependency Broken | 循环依赖 (T001->T002->T001) 被自动破除 | PASS |
| P2-06 | Plan Versioning | 修改计划后版本号递增，revision_log 记录变更 | PASS |
| P2-07 | Plan Markdown Output | 计划正确格式化为 Markdown 展示 | PASS |
| P2-08 | Planning Llm Output Parsing | 各种 LLM 输出格式 (JSON/think/markdown) 正确解析 | PASS |
| P2-09 | Full Report Has Report Structure | full_report 方案包含 report_structure 章节结构 | PASS |

### 规划层计划生成结果

**P2-01 simple_table 计划示例：**
```
方案: Q1集装箱吞吐量查询 (v1, 预计 20s)
任务链:
  T001 [数据获取] skill_api_fetch -> getContainerThroughput (M04)
  T002 [分析处理] skill_desc_analysis (depends: T001)
```

**P2-02 chart_text 计划示例：**
```
方案: 吞吐量趋势分析 (v1, 预计 40s)
任务链:
  T001 [数据获取] skill_api_fetch -> getThroughputTrendByMonth (M03)
  T002 [分析处理] skill_desc_analysis (depends: T001)
  T003 [可视化]   skill_chart_line (depends: T001)
  T004 [分析处理] skill_attribution (depends: T001)
```

## Phase 3: 执行层测试详情

执行层根据 AnalysisPlan 调度技能执行，支持拓扑排序并行、数据查询、图表生成和报告产出。

| TC | 测试名称 | 验证内容 | 结果 |
|----|----------|----------|------|
| P3-01 | Topological Layering | 任务按依赖关系正确分层 (Layer0: T001, Layer1: T002+T003, Layer2: T004) | PASS |
| P3-02 | Descriptive Analysis Skill | 描述性统计: mean/median/std/min/max/missing_rate + 同比/环比 | PASS |
| P3-03 | Line Chart Generation | 折线图生成: ECharts option JSON 含 series + xAxis (12个月数据) | PASS |
| P3-04 | Bar Chart Generation | 柱状图生成: 4 个业务板块对比 (集装箱/散杂货/油化品/商品车) | PASS |
| P3-05 | Waterfall Chart Generation | 瀑布图生成: 正值(#F0A500)、负值(#E85454)、基准(#1E3A5F) 颜色区分 | PASS |
| P3-06 | Html Report Generation | HTML报告: 含 <html>、echarts CDN、标题、叙述段落 | PASS |
| P3-07 | Skill Executor Timeout | 技能超时返回 failed 状态 (timeout=0.1s) | PASS |
| P3-08 | Skill Executor Exception | 技能抛出异常返回 failed + 错误信息 | PASS |
| P3-09 | Parallel Execution | 同层任务并行执行 (2个0.5s任务耗时<3s) | PASS |
| P3-10 | Single Task Failure Isolation | 单任务失败不阻塞同层其他任务 | PASS |
| P3-11 | Low Data Triggers Replan | 返回 < 10 行数据时 needs_replan=True | PASS |
| P3-12 | Dependency Chain Ordering | 依赖链 T001->T002->T003 按序执行 | PASS |
| P3-13 | All 15 Skills Registered | 15 个内置技能全部注册 | PASS |
| P3-14 | Ws Callback Push | WebSocket 回调推送 running + done 状态 | PASS |

### 数据查询结果

**P3-02 描述性统计分析结果：**
```json
{
  "summary_stats": {
    "throughput_wan_ton": {
      "mean": 3066.67,
      "median": 3075.0,
      "std": 203.84,
      "min": 2700.0,
      "max": 3400.0,
      "missing_rate": 0.0
    }
  },
  "growth_rates": {
    "throughput_wan_ton": {
      "yoy": "null (需>=13个月数据)",
      "mom": 0.0833
    }
  },
  "narrative": "Q1集装箱吞吐量均值3133万吨，环比增长8.3%..."
}
```

### 图文分析结果

**P3-03 折线图 ECharts Option (关键字段)：**
```json
{
  "title": {
    "text": "月度吞吐量趋势"
  },
  "xAxis": {
    "type": "category",
    "data": [
      "2025-04",
      "2025-05",
      "...",
      "2026-03"
    ]
  },
  "series": [
    {
      "name": "throughput_wan_ton",
      "type": "line",
      "smooth": true,
      "data": [
        2800,
        2950,
        "...",
        3250
      ]
    }
  ]
}
```

**P3-05 瀑布图 ECharts Option (颜色编码)：**
```
  上月基数: 3000 (深蓝 #1E3A5F)
  集装箱增长: +150 (琥珀 #F0A500)
  散杂货下降: -80 (红色 #E85454)
  油化品增长: +30 (琥珀 #F0A500)
  本月合计: 3100 (深蓝 #1E3A5F)
```

### 数据分析报告结果

**P3-06 HTML 报告结构：**
```html
<!DOCTYPE html>
<html lang="zh-CN">
  <head>
    <title>2026年Q1集装箱吞吐量分析报告</title>
    <script src="echarts@5/dist/echarts.min.js"></script>
  </head>
  <body>
    <h1>2026年Q1集装箱吞吐量分析报告</h1>
    <h2>1. 数据概览</h2>
    <div class="narrative">Q1吞吐量总体呈上升趋势...</div>
    <h2>2. 趋势分析</h2>
    <div id="chart_0" class="chart-container"></div>
    <h2>3. 总结</h2>
    <p>以上分析基于港口运营数据，仅供参考。</p>
  </body>
</html>
```

## E2E: 全链路集成测试详情

端到端测试验证 感知->规划->执行 完整链路的正确性。

| TC | 测试名称 | 验证内容 | 结果 |
|----|----------|----------|------|
| E2E-01 | Full Pipeline Simple Table | simple_table: 感知提取->规划2任务->执行数据获取+统计分析 | PASS |
| E2E-02 | Full Pipeline Chart Text | chart_text: 感知->规划3任务->执行数据获取+统计+折线图 | PASS |
| E2E-03 | Full Pipeline Full Report | full_report: 感知->规划5任务->执行数据+分析+图表+HTML报告 | PASS |

### E2E-03 full_report 全链路执行详情

```
Phase 1 感知:
  输入: "出一份Q1港口运营HTML分析报告"
  -> analysis_subject: ["港口运营"]
  -> time_range: 2026-01-01 ~ 2026-03-31 (Q1)
  -> output_complexity: full_report
  -> output_format: html

Phase 2 规划:
  方案: "Q1港口运营分析报告" (5个任务)
  T001 [数据获取] skill_api_fetch -> getThroughputTrendByMonth
  T002 [分析处理] skill_desc_analysis (depends: T001)
  T003 [可视化]   skill_chart_line (depends: T001)
  T004 [可视化]   skill_chart_waterfall (独立)
  T005 [报告生成] skill_report_html (depends: T002,T003,T004)
  report_structure: [数据概览, 趋势分析, 归因分析]

Phase 3 执行:
  Layer 0: T001(数据获取) + T004(瀑布图) 并行执行
  Layer 1: T002(统计分析) + T003(折线图) 并行执行
  Layer 2: T005(HTML报告) 等待依赖完成后执行
  结果: 5/5 任务完成, HTML报告含echarts图表
```

---

## 验收检查单

| 验收项 | 判断标准 | 状态 |
|--------|----------|------|
| 感知层: 槽位提取准确 | P1-01~P1-03 | PASS |
| 感知层: 旁路和默认值填充 | P1-04~P1-05 | PASS |
| 感知层: 结构化意图构建 | P1-06 | PASS |
| 感知层: 记忆/优先级/多槽位追问 | P1-07~P1-10 | PASS |
| 规划层: 三种复杂度计划生成 | P2-01, P2-02, P2-09 | PASS |
| 规划层: 幻觉过滤+M-code解析 | P2-03~P2-04 | PASS |
| 规划层: 循环依赖+版本管理 | P2-05~P2-06 | PASS |
| 执行层: 数据查询结果正确 | P3-02 描述性统计 | PASS |
| 执行层: 图表生成 (折线/柱状/瀑布) | P3-03~P3-05 | PASS |
| 执行层: HTML分析报告产出 | P3-06 | PASS |
| 执行层: 并行执行+故障隔离 | P3-09~P3-10 | PASS |
| 执行层: 数据质量检查+重规划触发 | P3-11 | PASS |
| 执行层: 15个内置技能注册 | P3-13 | PASS |
| 全链路: simple_table E2E | E2E-01 | PASS |
| 全链路: chart_text E2E (含图表) | E2E-02 | PASS |
| 全链路: full_report E2E (含报告) | E2E-03 | PASS |

---

## 附录: 三阶段架构

```
用户输入 --> [Phase 1: 感知层]
              SlotFillingEngine
              - LLM 槽位提取
              - 多轮追问 (max 3 轮)
              - 旁路跳过
              -> StructuredIntent

          --> [Phase 2: 规划层]
              PlanningEngine
              - LLM 方案生成
              - 技能/端点验证
              - 循环依赖检测
              -> AnalysisPlan (v1)

          --> [Phase 3: 执行层]
              execute_plan()
              - Kahn 拓扑排序
              - asyncio.gather 并行
              - 15 个技能调度:
                [数据获取] skill_api_fetch/web_search/file_parse
                [分析处理] skill_desc_analysis/attribution/prediction/anomaly
                [可视化]   skill_chart_line/bar/waterfall/dashboard
                [报告生成] skill_report_html/docx/pptx/summary_gen
              -> 数据结果 + 图表 + 分析报告
```
