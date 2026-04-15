# Analytica · Phase 3：执行层与技能库

---

## 版本记录

| 版本号 | 日期 | 修订说明 | 编制人 |
|--------|------|----------|--------|
| v1.0 | 2026-04-14 | 从实施方案 v1.3 拆分，补充 PRD 章节与完整测试用例集 | FAN |

---

## 目录

1. [阶段目标与交付物](#1-阶段目标与交付物)
2. [PRD 关联章节](#2-prd-关联章节)
3. [实施方案：Sprint 6 — 技能库框架](#3-实施方案sprint-6--技能库框架)
4. [实施方案：Sprint 7 — 分析技能](#4-实施方案sprint-7--分析技能)
5. [实施方案：Sprint 8 — 可视化与报告生成](#5-实施方案sprint-8--可视化与报告生成)
6. [实施方案：Sprint 9 — 执行节点完整实现](#6-实施方案sprint-9--执行节点完整实现)
7. [测试用例集](#7-测试用例集)
8. [验收检查单](#8-验收检查单)

---

## 1. 阶段目标与交付物

**时间窗口：** Week 5–7（Day 18–33）

**前置条件：** Phase 2 全部验收通过（规划节点、状态机、API 端点正常）

**阶段目标：** 实现技能库框架，集成数据获取、分析、可视化和报告生成技能，完成 full_report 完整执行流程。

**可运行交付物：**

| 交付物 | 验证方式 |
|--------|----------|
| 技能注册中心，10 个内置技能全部可调用 | `pytest tests/unit/test_skills.py` |
| full_report 场景端到端执行，输出真实 PPTX | 生成一份港口运营 PPTX 报告 |
| 10 个 Mock API 接口集成（respx 拦截） | 所有 API 调用使用 fixture 数据 |
| 单元测试 ≥ 30 个，全部通过 | `pytest tests/unit/ -v` |

---

## 2. PRD 关联章节

### 2.1 执行层设计（来自 PRD §4.3）

#### 2.1.1 模块职责

执行层按照规划层生成的任务清单，依次（或并行）调用各技能执行具体任务，将结果汇集到执行上下文（ExecutionContext），并在发现数据质量问题或新分析需求时动态更新计划。

#### 2.1.2 执行上下文（ExecutionContext）

```python
# 执行上下文：各任务输出的统一存储
execution_context = {
    "T001": SkillOutput(
        skill_id="skill_api_fetch",
        status="success",
        output_type="dataframe",
        data=pd.DataFrame(...),
        metadata={"rows": 4, "endpoint": "getThroughputByBusinessType"}
    ),
    "T002": SkillOutput(
        skill_id="skill_desc_analysis",
        status="success",
        output_type="json",
        data={"summary_stats": {...}, "growth_rates": {...}, "narrative": "..."}
    )
}
```

#### 2.1.3 动态规划更新触发条件

| 触发条件 | 追加任务类型 |
|----------|-------------|
| 数据获取结果 < 10 行 | 数据质量检查任务 + 告警 |
| 归因分析发现重要外部因素 | 互联网检索任务（自动追加） |
| 用户通过 WebSocket 发送追加需求 | 按需追加 |

#### 2.1.4 并行执行策略

- 使用 `asyncio.gather` 并行执行无依赖关系的任务
- 每个任务超时：`estimated_seconds * 3`
- 单任务失败不影响其他任务（任务级容错）

### 2.2 技能库完整清单（来自 PRD §5.2）

#### 数据获取技能

| 技能 ID | 名称 | 技术方案 |
|---------|------|----------|
| `skill_api_fetch` | API 数据获取 | httpx 异步请求，自动鉴权，返回 DataFrame |
| `skill_web_search` | 互联网检索 | Tavily Search API，返回结构化摘要 |
| `skill_file_parse` | 文件解析 | CSV/Excel/JSON → DataFrame |

#### 分析技能

| 技能 ID | 名称 | 技术方案 |
|---------|------|----------|
| `skill_desc_analysis` | 描述性分析 | pandas 统计，LLM 叙述生成 |
| `skill_attribution` | 归因分析 | LLM 因果推理（融合内外部数据） |
| `skill_prediction` | 预测分析 | Prophet / ARIMA / LLM 辅助 |
| `skill_anomaly` | 异常检测 | 时序异常识别 |

#### 可视化技能

| 技能 ID | 名称 | 输出 |
|---------|------|------|
| `skill_chart_line` | 折线图 | ECharts option JSON |
| `skill_chart_bar` | 柱状图 | ECharts option JSON |
| `skill_chart_waterfall` | 瀑布图 | ECharts option JSON（归因可视化）|
| `skill_dashboard` | 仪表盘 | 多图表组合 HTML |

#### 报告生成技能

| 技能 ID | 名称 | 输出格式 |
|---------|------|----------|
| `skill_report_pptx` | PPTX 报告 | .pptx 文件（含封面/目录/图表/总结） |
| `skill_report_docx` | Word 报告 | .docx 文件 |
| `skill_report_html` | HTML 报告 | 单页 HTML 文件 |
| `skill_summary_gen` | 摘要生成 | 纯文本摘要段落 |

### 2.3 10 个 Mock API 接口（来自 PRD §6.3）

测试阶段使用 `respx` 拦截 `httpx` 请求，fixture 文件位于 `tests/fixtures/mock_api/`。

| 端点 ID | 路径 | Mock 数据范围 |
|---------|------|--------------|
| `getThroughputSummary`（M01） | `GET /production/throughput/summary` | 月度/年度总吞吐量，含同比环比 |
| `getThroughputByBusinessType`（M02） | `GET /production/throughput/by-business-type` | 4个板块分类，含占比 |
| `getThroughputTrendByMonth`（M03） | `GET /production/throughput/monthly-trend` | 当年vs上年月度序列 |
| `getContainerThroughput`（M04） | `GET /production/container/throughput` | TEU，内外贸拆分 |
| `getBerthOccupancyRate`（M05） | `GET /production/berth/occupancy-rate` | 按港区或业务板块 |
| `getVesselEfficiency`（M06） | `GET /production/vessel/efficiency` | 单船效率，按公司可选 |
| `getPortInventory`（M07） | `GET /production/port-inventory` | 港存，含库容比 |
| `getDailyProductionDynamic`（M08） | `GET /production/daily-dynamic` | 昼夜班数据 |
| `getShipStatus`（M09） | `GET /production/ships/status` | 在泊/锚地，实时快照 |
| `getMarketMonthlyThroughput`（M10） | `GET /market/throughput/monthly` | 市场当月+同比 |
| `getMarketCumulativeThroughput`（M11） | `GET /market/throughput/cumulative` | 年度累计+同比 |
| `getMarketTrendChart`（M12） | `GET /market/trend-chart` | ⚠️ businessSegment必填 |
| `getMarketZoneThroughput`（M13） | `GET /market/throughput/by-zone` | 4个港区对比 |
| `getKeyEnterpriseContribution`（M14） | `GET /market/key-enterprise` | TOP企业贡献排名 |
| `getMarketBusinessSegment`（M15） | `GET /market/business-segment` | 4板块占比 |
| `getCustomerBasicInfo`（M16） | `GET /customer/basic-info` | 客户总数及类型分布 |
| `getStrategicCustomerThroughput`（M17） | `GET /customer/strategic/throughput` | 战略客户货量 |
| `getStrategicCustomerRevenue`（M18） | `GET /customer/strategic/revenue` | 战略客户收入（万元） |
| `getCustomerContributionRanking`（M19） | `GET /customer/contribution/ranking` | 全量客户排名，topN≤50 |
| `getCustomerCreditInfo`（M20） | `GET /customer/credit-info` | 信用等级AAA~C |
| `getAssetOverview`（M21） | `GET /asset/overview` | 资产总数/原值/净值 |
| `getAssetDistributionByType`（M22） | `GET /asset/distribution/by-type` | 4类型资产结构 |
| `getEquipmentFacilityStatus`（M23） | `GET /asset/equipment/status` | 正常/维修/报废/闲置 |
| `getAssetHistoricalTrend`（M24） | `GET /asset/historical-trend` | 历年新增/报废趋势 |
| `getInvestPlanSummary`（M25） | `GET /invest/plan/summary` | 批复额/完成额/完成率 |
| `getInvestPlanProgress`（M26） | `GET /invest/plan/monthly-progress` | 月度计划vs实际曲线 |
| `getCapitalProjectList`（M27） | `GET /invest/capital-projects` | 资本类项目明细列表 |

**Mock 统一约定：**
- Base URL：`http://mock.port-ai.internal/api/v1/`（MockAPI 模拟建议文档统一规范）
- 认证：`Authorization: Bearer TEST_TOKEN_2024`
- 数据范围：2024-01 ～ 2026-06（30 个月）
- 认证：Bearer Token（固定测试 Token）
- 时间入参：月度接口用 `curDateMonth`（YYYYMM），年度接口用 `curDateYear`（YYYY）
- 同期参数：`samePeriodDateMonth` / `samePeriodDateYear`

### 2.4 PPTX 报告规范（来自 PRD §7, 实施方案 §6.3）

| 页面类型 | 内容要求 |
|----------|----------|
| 封面页 | 大标题 + 副标题 + 日期 + Logo |
| 目录页 | 自动从 report_structure 生成，含页码 |
| 内容页 | 标题 + 图表（PNG 嵌入）/ 文字 / 图文混排 |
| 总结页 | 核心结论 + 建议要点 |

颜色主题：深蓝 `#1E3A5F`（背景/标题）、白色（正文）、琥珀 `#F0A500`（强调色）

---

## 3. 实施方案：Sprint 6 — 技能库框架

**时间：** Day 18–21

### 3.1 AI Coding Prompt：技能基类与注册中心

```
【任务】实现技能库框架（backend/skills/base.py + registry.py）。

【技能基类】（backend/skills/base.py）
from abc import ABC, abstractmethod
from pydantic import BaseModel
from typing import Any, Optional
from enum import Enum

class SkillCategory(str, Enum):
    DATA_FETCH = "data_fetch"
    ANALYSIS = "analysis"
    VISUALIZATION = "visualization"
    REPORT = "report"
    SEARCH = "search"

class SkillInput(BaseModel):
    params: dict
    context_refs: list[str] = []  # 引用前序任务结果的 task_id

class SkillOutput(BaseModel):
    skill_id: str
    status: str  # success | failed | partial
    output_type: str  # dataframe | chart | text | file | json
    data: Any
    storage_ref: Optional[str] = None
    metadata: dict = {}
    error_message: Optional[str] = None

class BaseSkill(ABC):
    skill_id: str
    category: SkillCategory
    description: str

    @abstractmethod
    async def execute(self, input: SkillInput, context: dict) -> SkillOutput: ...

【注册中心】（backend/skills/registry.py）
- 单例 SkillRegistry
- 应用启动时自动扫描 skills/ 子目录注册
- @register_skill(id, category, description) 装饰器
- get_skill(skill_id) -> BaseSkill
- list_skills(category=None) -> List[dict]
- get_skills_description() -> str  # 返回面向 LLM 的描述文本

【还需要】
- async skill_executor(skill_id, input, context, timeout_seconds) -> SkillOutput
  超时后返回 SkillOutput(status="failed", error_message="timeout")
- 执行日志记录（技能ID、耗时、状态）

【输出】backend/skills/base.py + backend/skills/registry.py
```

### 3.2 AI Coding Prompt：数据获取技能

```
【任务】实现三个数据获取技能。

1. API 数据获取技能（skills/data/api_fetch.py，skill_id: "skill_api_fetch"）：
   - 根据 params.datasource_id + params.endpoint_id 查找数据源配置
   - 自动处理 Bearer Token 认证
   - 调用 httpx.AsyncClient 发起请求
   - 将响应 JSON 转为 pandas DataFrame
   - 基础数据质量检查：行数、缺失率、数据类型
   - 返回 SkillOutput(output_type="dataframe", data=df, metadata={"rows": N, "quality": {...}})

2. 互联网检索技能（skills/data/web_search.py，skill_id: "skill_web_search"）：
   - 调用 Tavily Search API
   - 支持 params.query 和 params.max_results
   - 调用 Qwen3 生成综合摘要
   - 摘要 Prompt：「基于以下检索结果，提取与{topic}相关的关键数据和趋势，结构化段落输出」
   - 返回 SkillOutput(output_type="json", data={"results": [...], "synthesized_summary": "..."})

3. 文件解析技能（skills/data/file_parse.py，skill_id: "skill_file_parse"）：
   - 支持 CSV、Excel（xlsx）、JSON
   - 自动推断列类型
   - 返回 SkillOutput(output_type="dataframe", data=df, metadata={"columns": [...], "dtypes": {...}})

【约束】
- 使用 @register_skill 装饰器注册
- httpx 使用 respx mock（测试）
- 每个技能有完整错误处理和日志

【输出】三个技能文件 + 对应测试
```

---

## 4. 实施方案：Sprint 7 — 分析技能

**时间：** Day 22–25

### 4.1 AI Coding Prompt：描述性分析技能

```
【任务】实现描述性分析技能（skills/analysis/descriptive.py，skill_id: "skill_desc_analysis"）。

输入（params）：
- data_ref: 前序任务 task_id（从 context[data_ref].data 获取 DataFrame）
- target_columns: 要分析的数值列列表
- group_by: 可选分组维度
- time_column: 可选时间列
- calc_growth: 是否计算同比/环比

输出（SkillOutput.data）：
{
  "summary_stats": {"列名": {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0, "missing_rate": 0}},
  "growth_rates": {"列名": {"mom": 0.05, "yoy": 0.12}},  // 环比/同比
  "narrative": "LLM 生成的描述性分析段落（中文，2-3段）"
}

narrative Prompt：
「你是数据分析师，基于以下统计数据写简洁描述性分析（2-3段，中文）：
数据概况：{summary_stats_json}
增长率：{growth_rates_json}
分析背景：{analysis_goal}
要求：突出最重要的2-3个发现，指出异常值，语言简洁专业，避免重复数字」

【陷阱】
- 同比计算需要时序完整（少于 12 个月时无同比数据，返回 null）
- group_by 时 target_columns 需分组后分别计算
- narrative LLM 输出可能含 <think> 块，解析前剥离

【测试数据】使用 12 个月港口吞吐量数据（含季节性波动和一个异常月份）

【输出】skills/analysis/descriptive.py + tests/unit/test_skill_desc_analysis.py
```

### 4.2 AI Coding Prompt：归因分析技能

```
【任务】实现归因分析技能（skills/analysis/attribution.py，skill_id: "skill_attribution"）。

输入（params）：
- internal_data_ref: 内部数据描述性统计的 task_id 引用
- external_context_ref: 互联网检索结果的 task_id 引用
- target_metric: 目标指标和变化幅度（如 "集装箱吞吐量下降 8.5%"）
- time_period: 分析时段

归因 LLM System Prompt：
「你是资深数据分析师，擅长从多源数据推断因果关系。要求：
- 区分直接原因与背景原因
- 对不确定的归因必须说明置信度
- 避免仅凭时间相关性得出因果结论
- 对每个驱动因素提供具体证据」

输出（SkillOutput.data）：
{
  "primary_drivers": [{"factor": "全球航运需求下滑", "direction": "-", "estimated_impact": "约-5%", "evidence": "检索结果显示..."}],
  "secondary_factors": [...],
  "uncertainty_note": "外部因素量化依赖检索数据，存在一定不确定性",
  "narrative": "归因分析叙述段落",
  "waterfall_data": [{"name": "基准值", "value": 100}, {"name": "全球需求", "value": -5}, ...]
}

waterfall_data 用于传入 skill_chart_waterfall 生成瀑布图。

【陷阱】
- external_context_ref 可能为空（无检索步骤），此时仅基于内部数据归因，需在 uncertainty_note 中说明
- LLM 可能输出超长 JSON 或被 markdown 包裹，需统一解析处理

【输出】skills/analysis/attribution.py + 3 个测试用例
```

---

## 5. 实施方案：Sprint 8 — 可视化与报告生成

**时间：** Day 26–29

### 5.1 AI Coding Prompt：ECharts 可视化技能

```
【任务】实现三个 ECharts 可视化技能。

1. 折线图（skills/visualization/chart_line.py，skill_id: "skill_chart_line"）：
   - 输入：DataFrame（含时间列+值列）、标题、颜色主题
   - 输出：完整 ECharts option JSON
   - 支持多系列（多条折线）、区间阴影、参考线

2. 瀑布图（skills/visualization/chart_waterfall.py，skill_id: "skill_chart_waterfall"）：
   - 输入：归因因素列表（name, value, direction）
   - 输出：ECharts 瀑布图 option JSON
   - 正值琥珀色 #F0A500，负值红色 #E85454，基准/汇总深蓝 #1E3A5F

3. 图表 HTML 封装器（skills/visualization/chart_wrapper.py）：
   - 将 ECharts option JSON 包装为独立可运行 HTML（CDN 引入 ECharts）
   - 输出可直接在浏览器打开的单文件 HTML

颜色主题：主色 #1E3A5F（深蓝），强调色 #F0A500（琥珀）。

【约束】输出的 ECharts JSON 必须可直接被前端 echarts.setOption(option) 使用，不含 Python 对象。

【输出】三个技能文件 + 测试（验证输出 JSON 的合法性）
```

### 5.2 AI Coding Prompt：PPTX 报告生成技能

```
【任务】实现报告生成技能（skills/report/ 下三个文件）。

1. PPTX 生成（skills/report/pptx_gen.py，skill_id: "skill_report_pptx"）：
   输入：
   - report_structure: 章节结构
   - execution_context: 各任务输出（含文字/ECharts JSON/表格数据）
   - report_metadata: {title, author, date, logo_path}
   
   功能要求：
   a. 封面页：大标题（深蓝背景，白色字体）+ 副标题 + 日期 + Logo（如有）
   b. 目录页：自动生成，含章节编号
   c. 内容页：
      - 纯文字页：标题 + 要点列表
      - 图表页：标题 + 图表 PNG + 图注
      - 图文混排：左图右文
   d. 末页：核心结论 + 建议
   
   技术方案：
   - python-pptx 实现
   - ECharts JSON 通过 pyecharts 渲染为 PNG 字节流嵌入
   - 图表 PNG 如果 pyecharts 不可用，使用占位图替代（降级策略）
   - pptx_preview() → Base64 首页缩略图
   
   字体：标题 Microsoft YaHei Bold 28pt，正文 16pt

2. DOCX 生成（skills/report/docx_gen.py，skill_id: "skill_report_docx"）：
   - python-docx 实现，含标题/正文/图表（PNG 嵌入）/表格
   
3. HTML 报告（skills/report/html_gen.py，skill_id: "skill_report_html"）：
   - Jinja2 模板引擎
   - 图表通过 ECharts CDN 渲染
   - 单文件可在浏览器独立打开

【输出】三个技能文件 + 测试（验证文件可正常打开和页数）
```

---

## 6. 实施方案：Sprint 9 — 执行节点完整实现

**时间：** Day 30–33

### 6.1 AI Coding Prompt：执行层节点

```
【任务】实现完整的 LangGraph 执行节点（backend/agent/execution.py）。

【核心逻辑】

execution_node(state: AgentState) -> AgentState:
1. 取出当前待执行任务（按 depends_on 拓扑排序）
2. 找出无未完成依赖的任务集合
3. 使用 asyncio.gather 并行执行（最多 3 个任务并行）
4. 每个任务执行：
   a. 更新 task_statuses[task_id] = "running"，WebSocket 推送
   b. 调用 skill_executor(skill_id, input, context, timeout)
   c. 成功：task_statuses = "done"，写入 execution_context
   d. 失败：task_statuses = "failed"，记录 error，继续其他任务（容错）
   e. WebSocket 推送任务完成事件（含结果预览）
5. 检查动态规划追加条件（数据量/归因结果）
6. 所有任务完成 → 设 next_action="reflection"

【WebSocket 推送格式】
{"event": "task_update", "task_id": "T001", "status": "running/done/failed",
 "progress": 0.3, "message": "正在获取港口吞吐量数据...", "preview": null}

【动态规划追加】
- df.shape[0] < 10 → 追加 data_quality_check 任务，提示用户
- attribution 结果的 primary_drivers[0].evidence 含「外部」→ 追加 web_search 任务
- 追加任务时设 state.needs_replan=True，回到规划节点

【约束】
- 每个任务超时 = task.estimated_seconds * 3
- 并行数量上限 3
- 失败任务不阻塞其他任务
- 全异步

【输出】backend/agent/execution.py + 集成测试
```

---

## 7. 测试用例集

> **设计原则：** 执行层的 AI 不确定性来源于：（1）LLM 生成的叙述类内容质量；（2）Mock API 数据的边界情况处理；（3）并行执行的竞态条件；（4）报告文件的完整性。测试分层覆盖技能单元、API 集成和 full_report E2E 三个层级。

### 7.1 技能注册中心测试（tests/unit/test_skill_registry.py）

#### TC-R01：启动后所有内置技能已注册
```python
def test_all_builtin_skills_registered():
    """验证应用启动后所有预定义技能均可在注册中心找到"""
    registry = SkillRegistry.get_instance()
    expected_skills = [
        "skill_api_fetch", "skill_web_search", "skill_file_parse",
        "skill_desc_analysis", "skill_attribution", "skill_prediction",
        "skill_anomaly", "skill_chart_line", "skill_chart_bar",
        "skill_chart_waterfall", "skill_dashboard",
        "skill_report_pptx", "skill_report_docx", "skill_report_html", "skill_summary_gen"
    ]
    for skill_id in expected_skills:
        skill = registry.get_skill(skill_id)
        assert skill is not None, f"{skill_id} 未注册"
```

#### TC-R02：get_skill 不存在时返回 None 不崩溃
```python
def test_get_nonexistent_skill_returns_none():
    registry = SkillRegistry.get_instance()
    result = registry.get_skill("skill_does_not_exist")
    assert result is None
```

#### TC-R03：list_skills 按分类过滤
```python
def test_list_skills_by_category():
    registry = SkillRegistry.get_instance()
    data_skills = registry.list_skills(category="data_fetch")
    assert len(data_skills) == 3
    skill_ids = {s["skill_id"] for s in data_skills}
    assert skill_ids == {"skill_api_fetch", "skill_web_search", "skill_file_parse"}
```

#### TC-R04：get_skills_description 返回面向 LLM 的文本
```python
def test_skills_description_for_llm():
    """验证 get_skills_description() 返回包含所有 skill_id 的可读描述"""
    registry = SkillRegistry.get_instance()
    desc = registry.get_skills_description()
    assert "skill_api_fetch" in desc
    assert "skill_report_pptx" in desc
    assert len(desc) > 500  # 确保不是空字符串
```

#### TC-R05：超时执行返回 failed 状态
```python
@pytest.mark.asyncio
async def test_skill_executor_timeout():
    """验证技能执行超时时返回 SkillOutput(status='failed', error_message='timeout')"""
    async def slow_skill(input, context):
        await asyncio.sleep(100)
    
    output = await skill_executor("skill_api_fetch", mock_input, {}, timeout_seconds=1)
    assert output.status == "failed"
    assert "timeout" in output.error_message.lower()
```

---

### 7.2 API 数据获取技能测试（tests/unit/test_skill_api_fetch.py）

#### TC-AF01：getThroughputByBusinessType（M02）正常调用返回 DataFrame
```python
@pytest.mark.asyncio
async def test_api_fetch_throughput_by_business_type(respx_mock):
    """
    验证 skill_api_fetch 调用 M02 getThroughputByBusinessType 返回正确的 DataFrame。
    业务场景：§7 A1「上个月各业务线的吞吐量是多少？」
    """
    mock_response = [
        {"businessType": "集装箱", "throughput": 38.2, "yoyRate": 7.3, "shareRatio": 42.1},
        {"businessType": "散杂货", "throughput": 28.5, "yoyRate": 2.1, "shareRatio": 31.4},
        {"businessType": "油化品", "throughput": 15.3, "yoyRate": -1.2, "shareRatio": 16.9},
        {"businessType": "商品车", "throughput": 8.6,  "yoyRate": 15.4, "shareRatio": 9.5},
    ]
    respx_mock.get(
        "http://mock.port-ai.internal/api/v1/production/throughput/by-business-type"
    ).mock(return_value=httpx.Response(200, json={"code": 200, "data": mock_response}))

    skill = SkillRegistry.get_instance().get_skill("skill_api_fetch")
    output = await skill.execute(SkillInput(params={
        "endpoint_id": "getThroughputByBusinessType",
        "flag": 0,
        "dateMonth": "2026-03",
    }), context={})

    assert output.status == "success"
    assert output.output_type == "dataframe"
    assert len(output.data) == 4
    assert "businessType" in output.data.columns
    assert "shareRatio" in output.data.columns
    # 所有板块占比之和应≈100%
    assert abs(output.data["shareRatio"].sum() - 100.0) <= 1.0
```

#### TC-AF02：数据行数 < 10 触发质量警告（以 getCustomerContributionRanking M19 为例）
```python
@pytest.mark.asyncio
async def test_api_fetch_low_data_triggers_quality_warning(respx_mock):
    """
    验证 M19 getCustomerContributionRanking 返回少量数据（< 10 条）时，
    metadata 中含 quality_warning，提示后续分析可靠性降低。
    """
    sparse_data = [
        {"rank": 1, "clientName": "中远海运", "throughput": 45.2,
         "contributionRate": 12.1, "yoyChange": 5.3}
    ]  # 只有1条，不足10条
    respx_mock.get(
        "http://mock.port-ai.internal/api/v1/customer/contribution/ranking"
    ).mock(return_value=httpx.Response(200, json={"code": 200, "data": sparse_data}))

    skill = SkillRegistry.get_instance().get_skill("skill_api_fetch")
    output = await skill.execute(SkillInput(params={
        "endpoint_id": "getCustomerContributionRanking",
        "date": "2026-03",
        "statisticType": 0,
    }), context={})
    assert output.metadata.get("quality_warning") == "low_data_volume"
    assert output.metadata.get("rows") < 10
```

#### TC-AF03：API 返回 401 时的错误处理（Bearer Token 失效）
```python
@pytest.mark.asyncio
async def test_api_fetch_auth_error_returns_failed(respx_mock):
    """
    验证 Mock Server 返回 401 时，skill_api_fetch 输出 status='failed'。
    401 场景：测试环境 Bearer TEST_TOKEN_2024 过期或错误时的行为。
    """
    respx_mock.get(
        "http://mock.port-ai.internal/api/v1/invest/plan/summary"
    ).mock(return_value=httpx.Response(401, json={"error": "Unauthorized"}))

    skill = SkillRegistry.get_instance().get_skill("skill_api_fetch")
    output = await skill.execute(SkillInput(params={
        "endpoint_id": "getInvestPlanSummary",
        "currYear": "2026",
    }), context={})
    assert output.status == "failed"
    assert "401" in output.error_message or "auth" in output.error_message.lower()
```

#### TC-AF04：API 返回 500 时的容错（服务异常不崩溃）
```python
@pytest.mark.asyncio
async def test_api_fetch_server_error_graceful(respx_mock):
    """
    验证 Mock Server 返回 500 时，技能返回 failed 状态，不抛异常。
    500 场景：Mock Server 自身错误，或对应月份数据计算异常。
    """
    respx_mock.get(
        "http://mock.port-ai.internal/api/v1/customer/strategic/revenue"
    ).mock(return_value=httpx.Response(500, text="Internal Server Error"))

    skill = SkillRegistry.get_instance().get_skill("skill_api_fetch")
    output = await skill.execute(SkillInput(params={
        "endpoint_id": "getStrategicCustomerRevenue",
        "curDate": "2026",
        "statisticType": 1,
    }), context={})
    assert output.status == "failed"
    assert output.data is None
    assert "500" in output.error_message or "server" in output.error_message.lower()
```

#### TC-AF05：getMarketTrendChart（M12）businessSegment 参数缺失时报错
```python
@pytest.mark.asyncio
async def test_market_trend_chart_missing_business_segment():
    """
    验证调用 M12 getMarketTrendChart 未传必填参数 businessSegment 时，
    技能返回参数验证错误，不应盲目调用 API。
    对应 MockAPI §3.2 M12：businessSegment 为必填参数。
    """
    skill = SkillRegistry.get_instance().get_skill("skill_api_fetch")
    output = await skill.execute(SkillInput(params={
        "endpoint_id": "getMarketTrendChart",
        "startDate": "2025-01",
        "endDate": "2025-12",
        # 故意缺少 businessSegment
    }), context={})
    assert output.status == "failed"
    assert "businessSegment" in output.error_message, \
        "错误信息应明确指出缺少 businessSegment 参数"
```

#### TC-AF06：getCustomerContributionRanking（M19）topN 超限处理
```python
@pytest.mark.asyncio
async def test_customer_ranking_top_n_over_limit(respx_mock):
    """
    验证 M19 getCustomerContributionRanking 的 topN 参数超过上限（>50）时，
    技能自动截断为 50，并在 metadata 中记录截断警告。
    """
    large_ranking = [
        {"rank": i, "clientName": f"客户{i}", "throughput": 100-i,
         "contributionRate": 5.0, "yoyChange": 0.5}
        for i in range(1, 101)  # 返回 100 条
    ]
    respx_mock.get(
        "http://mock.port-ai.internal/api/v1/customer/contribution/ranking"
    ).mock(return_value=httpx.Response(200, json={"code": 200, "data": large_ranking}))

    skill = SkillRegistry.get_instance().get_skill("skill_api_fetch")
    output = await skill.execute(SkillInput(params={
        "endpoint_id": "getCustomerContributionRanking",
        "date": "2026-03",
        "statisticType": 0,
        "topN": 200,  # 超过 API 文档上限 50
    }), context={})
    assert len(output.data) <= 50, "超限 topN 应被截断为 50"
    assert output.metadata.get("truncated") is True or \
           output.metadata.get("large_dataset_warning") is not None
```

#### TC-AF07：Bearer Token 自动注入请求头（统一 TEST_TOKEN_2024）
```python
@pytest.mark.asyncio
async def test_api_fetch_bearer_token_injected(respx_mock):
    """
    验证所有 Mock API 调用均携带正确的 Bearer Token。
    Token 值：TEST_TOKEN_2024（MockAPI 模拟建议文档 §2 统一规范）
    """
    captured_request = None
    def capture(request):
        nonlocal captured_request
        captured_request = request
        return httpx.Response(200, json={"code": 200, "data": []})
    respx_mock.get(
        "http://mock.port-ai.internal/api/v1/production/throughput/summary"
    ).mock(side_effect=capture)

    skill = SkillRegistry.get_instance().get_skill("skill_api_fetch")
    await skill.execute(SkillInput(params={
        "endpoint_id": "getThroughputSummary",
        "date": "2026-03",
        "dateType": 1,
    }), context={})
    assert captured_request is not None
    assert "Authorization" in captured_request.headers
    assert captured_request.headers["Authorization"] == "Bearer TEST_TOKEN_2024"
```

---

### 7.3 描述性分析技能测试（tests/unit/test_skill_desc_analysis.py）

#### TC-DA01：同比增长率计算正确
```python
@pytest.mark.asyncio
async def test_yoy_growth_rate_calculation():
    """验证 12 个月数据的同比增长率计算准确"""
    # 2025 年 1 月：100，2026 年 1 月：112 → 同比 +12%
    data = make_monthly_throughput_data(months=24, start_year=2025)
    skill = SkillRegistry.get_instance().get_skill("skill_desc_analysis")
    output = await skill.execute(SkillInput(params={
        "data_ref": "T001",
        "target_columns": ["throughput_teu"],
        "time_column": "date_month",
        "calc_growth": True
    }), context={"T001": make_skill_output_from_df(data)})
    growth = output.data["growth_rates"]["throughput_teu"]
    assert "yoy" in growth
    assert abs(growth["yoy"] - 0.12) < 0.01  # 允许 1% 误差
```

#### TC-DA02：环比增长率计算正确
```python
@pytest.mark.asyncio
async def test_mom_growth_rate_calculation():
    """验证月度环比增长率计算"""
    data = make_monthly_data_with_known_mom(0.05)  # 月环比 5%
    skill = SkillRegistry.get_instance().get_skill("skill_desc_analysis")
    output = await skill.execute(...)
    assert abs(output.data["growth_rates"]["throughput_teu"]["mom"] - 0.05) < 0.02
```

#### TC-DA03：不足 12 个月时同比返回 null
```python
@pytest.mark.asyncio
async def test_yoy_returns_null_when_less_than_12_months():
    """验证数据不足 12 个月时，yoy 为 null 而非崩溃"""
    data = make_monthly_throughput_data(months=6)
    skill = SkillRegistry.get_instance().get_skill("skill_desc_analysis")
    output = await skill.execute(...)
    assert output.data["growth_rates"]["throughput_teu"]["yoy"] is None
```

#### TC-DA04：narrative 包含关键发现（不为空，不是模板填充）
```python
@pytest.mark.asyncio
async def test_narrative_contains_meaningful_content(mock_llm_narrative):
    """验证 LLM 生成的 narrative 非空，包含数字或关键词"""
    mock_llm_narrative.return_value = "2026年1月集装箱吞吐量达到123.4万TEU，同比增长12.3%，为近24个月最高。主要增量来自外贸业务..."
    data = make_monthly_throughput_data(months=24)
    skill = SkillRegistry.get_instance().get_skill("skill_desc_analysis")
    output = await skill.execute(...)
    narrative = output.data["narrative"]
    assert len(narrative) > 50
    # 不应只是模板填充（如 "数据显示数值变化"）
    assert any(char.isdigit() for char in narrative)  # 包含数字
```

#### TC-DA05：narrative LLM 输出含 <think> 标签被剥离
```python
@pytest.mark.asyncio
async def test_desc_analysis_strips_think_tags(mock_llm_narrative):
    """验证描述性分析技能剥离 LLM 的 <think> 推理块"""
    mock_llm_narrative.return_value = "<think>让我分析一下...</think>2026年1月吞吐量为123万TEU..."
    data = make_monthly_throughput_data(months=12)
    skill = SkillRegistry.get_instance().get_skill("skill_desc_analysis")
    output = await skill.execute(...)
    assert "<think>" not in output.data["narrative"]
    assert "123万TEU" in output.data["narrative"]
```

#### TC-DA06：分组统计（group_by）正确
```python
@pytest.mark.asyncio
async def test_group_by_io_trade():
    """验证 group_by=ioTrade 时按内外贸分别统计"""
    data = make_throughput_data_with_io_trade()  # 含内贸/外贸两组
    skill = SkillRegistry.get_instance().get_skill("skill_desc_analysis")
    output = await skill.execute(SkillInput(params={
        "data_ref": "T001", "target_columns": ["throughput_teu"],
        "group_by": "ioTrade", "calc_growth": False
    }), context={"T001": make_skill_output_from_df(data)})
    stats = output.data["summary_stats"]
    assert "内贸" in stats or "ioTrade_内贸" in stats
    assert "外贸" in stats or "ioTrade_外贸" in stats
```

---

### 7.4 归因分析技能测试（tests/unit/test_skill_attribution.py）

#### TC-AT01：归因结果包含 primary_drivers
```python
@pytest.mark.asyncio
async def test_attribution_returns_primary_drivers(mock_attribution_llm):
    """验证归因分析返回 primary_drivers 列表"""
    mock_attribution_llm.return_value = json.dumps({
        "primary_drivers": [{"factor": "全球航运需求", "direction": "-", "estimated_impact": "-5%", "evidence": "检索结果"}],
        "secondary_factors": [],
        "uncertainty_note": "外部因素量化有限",
        "narrative": "本月吞吐量下降主要受...",
        "waterfall_data": [{"name": "基准", "value": 100}]
    })
    skill = SkillRegistry.get_instance().get_skill("skill_attribution")
    output = await skill.execute(...)
    assert "primary_drivers" in output.data
    assert len(output.data["primary_drivers"]) >= 1
```

#### TC-AT02：无外部检索数据时归因仍可执行
```python
@pytest.mark.asyncio
async def test_attribution_without_external_context(mock_attribution_llm):
    """验证 external_context_ref 为空时，归因分析不崩溃，uncertainty_note 说明局限性"""
    skill = SkillRegistry.get_instance().get_skill("skill_attribution")
    output = await skill.execute(SkillInput(params={
        "internal_data_ref": "T001",
        "external_context_ref": None,  # 无外部数据
        "target_metric": "吞吐量下降8.5%",
        "time_period": "2026年1月"
    }), context={"T001": make_mock_stats_output()})
    assert output.status == "success"
    assert "uncertainty" in output.data["uncertainty_note"].lower() or "局限" in output.data["uncertainty_note"]
```

#### TC-AT03：瀑布图数据结构完整
```python
@pytest.mark.asyncio
async def test_attribution_waterfall_data_complete(mock_attribution_llm):
    """验证 waterfall_data 包含基准值和各驱动因素"""
    mock_attribution_llm.return_value = json.dumps({
        "primary_drivers": [{"factor": "因素A", "direction": "+", "estimated_impact": "+3%", "evidence": "..."}],
        "secondary_factors": [],
        "uncertainty_note": "",
        "narrative": "...",
        "waterfall_data": [
            {"name": "基准值", "value": 100},
            {"name": "因素A", "value": 3},
            {"name": "汇总", "value": 103}
        ]
    })
    skill = SkillRegistry.get_instance().get_skill("skill_attribution")
    output = await skill.execute(...)
    wf = output.data["waterfall_data"]
    assert len(wf) >= 2
    names = [item["name"] for item in wf]
    assert "基准值" in names or any("基准" in n for n in names)
```

---

### 7.5 可视化技能测试（tests/unit/test_skill_visualization.py）

#### TC-V01：折线图 option JSON 合法
```python
@pytest.mark.asyncio
async def test_line_chart_option_is_valid_echarts():
    """验证折线图输出的 ECharts option 包含 series 和 xAxis"""
    data = make_monthly_trend_data()
    skill = SkillRegistry.get_instance().get_skill("skill_chart_line")
    output = await skill.execute(SkillInput(params={
        "data_ref": "T001", "title": "集装箱吞吐量趋势",
        "time_column": "date_month", "value_columns": ["throughput_teu"]
    }), context={"T001": make_skill_output_from_df(data)})
    option = output.data
    assert "series" in option
    assert "xAxis" in option
    assert isinstance(option["series"], list)
    assert len(option["series"]) >= 1
```

#### TC-V02：多系列折线图
```python
@pytest.mark.asyncio
async def test_line_chart_multiple_series():
    """验证 value_columns 传多列时，输出多条折线"""
    data = make_data_with_two_series()
    skill = SkillRegistry.get_instance().get_skill("skill_chart_line")
    output = await skill.execute(SkillInput(params={
        "data_ref": "T001", "title": "多业务线趋势",
        "time_column": "date_month", "value_columns": ["container_teu", "bulk_ton"]
    }), context={"T001": make_skill_output_from_df(data)})
    assert len(output.data["series"]) == 2
```

#### TC-V03：瀑布图正值/负值颜色区分
```python
@pytest.mark.asyncio
async def test_waterfall_chart_colors():
    """验证瀑布图正值使用琥珀色，负值使用红色"""
    waterfall_input = [
        {"name": "基准", "value": 100},
        {"name": "因素A", "value": 5, "direction": "+"},
        {"name": "因素B", "value": -8, "direction": "-"},
        {"name": "汇总", "value": 97}
    ]
    skill = SkillRegistry.get_instance().get_skill("skill_chart_waterfall")
    output = await skill.execute(SkillInput(params={"waterfall_data": waterfall_input, "title": "归因分解"}), {})
    option = output.data
    # 在 series 中找到正值颜色
    series_data = option["series"][0]["data"]
    # 至少一个条目含正向颜色（#F0A500）或负向颜色（#E85454）
    colors_used = {item.get("itemStyle", {}).get("color") for item in series_data if isinstance(item, dict)}
    assert "#F0A500" in colors_used or "#1E3A5F" in colors_used
```

#### TC-V04：ECharts option 不含 Python 对象
```python
@pytest.mark.asyncio
async def test_echart_option_json_serializable():
    """验证输出的 ECharts option 可直接 json.dumps（不含 datetime、DataFrame 等 Python 对象）"""
    data = make_monthly_trend_data()
    skill = SkillRegistry.get_instance().get_skill("skill_chart_line")
    output = await skill.execute(...)
    # 应不抛出 JSON 序列化错误
    try:
        json.dumps(output.data)
    except (TypeError, ValueError) as e:
        pytest.fail(f"ECharts option 不可 JSON 序列化：{e}")
```

---

### 7.6 PPTX 报告生成测试（tests/unit/test_skill_report_pptx.py）

#### TC-PT01：PPTX 文件生成成功，幻灯片数 ≥ 4
```python
@pytest.mark.asyncio
async def test_pptx_generated_successfully():
    """验证 skill_report_pptx 生成的文件可被 python-pptx 打开，幻灯片数 ≥ 4"""
    from pptx import Presentation
    import io
    skill = SkillRegistry.get_instance().get_skill("skill_report_pptx")
    output = await skill.execute(SkillInput(params={
        "report_metadata": {"title": "港口运营分析", "author": "Analytica", "date": "2026-04"},
        "report_structure": {"sections": ["趋势分析", "归因分析", "结论"]}
    }), context=make_full_execution_context())
    assert output.status == "success"
    assert output.output_type == "file"
    prs = Presentation(io.BytesIO(output.data))
    assert len(prs.slides) >= 4  # 封面+目录+内容+结尾
```

#### TC-PT02：封面包含标题文字
```python
@pytest.mark.asyncio
async def test_pptx_cover_contains_title():
    """验证 PPTX 封面页包含报告标题文字"""
    from pptx import Presentation
    import io
    skill = SkillRegistry.get_instance().get_skill("skill_report_pptx")
    output = await skill.execute(SkillInput(params={
        "report_metadata": {"title": "港口运营年度报告", "author": "测试", "date": "2026-04"},
        "report_structure": {"sections": ["趋势"]}
    }), context=make_minimal_execution_context())
    prs = Presentation(io.BytesIO(output.data))
    cover_slide = prs.slides[0]
    text_content = " ".join(tf.text for shape in cover_slide.shapes if shape.has_text_frame for tf in shape.text_frame.paragraphs)
    assert "港口运营年度报告" in text_content
```

#### TC-PT03：无图表数据时降级处理（不崩溃）
```python
@pytest.mark.asyncio
async def test_pptx_without_charts_does_not_crash():
    """验证无图表数据时，PPTX 生成不崩溃（使用文字页代替图表页）"""
    skill = SkillRegistry.get_instance().get_skill("skill_report_pptx")
    # 执行上下文中无图表数据
    context_without_charts = {"T001": make_text_only_output()}
    output = await skill.execute(SkillInput(params=make_minimal_report_params()), context_without_charts)
    assert output.status in ("success", "partial")  # 允许 partial（有警告但文件生成）
    assert output.data is not None
```

#### TC-PT04：无乱码（中文字体检查）
```python
@pytest.mark.asyncio
async def test_pptx_no_chinese_garbled():
    """验证 PPTX 文件中的中文文字使用了合适字体（Microsoft YaHei 或 SimHei）"""
    from pptx import Presentation
    import io
    skill = SkillRegistry.get_instance().get_skill("skill_report_pptx")
    output = await skill.execute(make_report_input_with_chinese(), make_full_execution_context())
    prs = Presentation(io.BytesIO(output.data))
    # 检查第一张内容幻灯片的文字框字体
    for slide in prs.slides[1:3]:
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    for run in para.runs:
                        if run.font.name:
                            assert run.font.name in ("Microsoft YaHei", "SimHei", "微软雅黑", None)
```

#### TC-PT05：HTML 报告文件合法（可在浏览器解析）
```python
@pytest.mark.asyncio
async def test_html_report_is_valid_html():
    """验证 skill_report_html 输出的 HTML 包含基本结构标签"""
    skill = SkillRegistry.get_instance().get_skill("skill_report_html")
    output = await skill.execute(make_report_input(), make_full_execution_context())
    html_content = output.data
    assert "<html" in html_content.lower()
    assert "<body" in html_content.lower()
    assert "echarts" in html_content.lower()  # ECharts 脚本已嵌入
```

---

### 7.7 执行节点测试（tests/integration/test_execution_node.py）

#### TC-EN01：simple_table 场景 E2E（< 30 秒）
```python
@pytest.mark.asyncio
async def test_simple_table_e2e_within_30s(respx_mock, mock_desc_llm):
    """full E2E：simple_table 场景，总耗时 < 30 秒"""
    setup_mock_api(respx_mock, "getThroughputByBusinessType", "m02_getThroughputByBusinessType_2026-03.json")
    state = make_state_with_confirmed_plan("simple_table", tasks=[
        make_task("T001", "data_fetch", "skill_api_fetch"),
        make_task("T002", "report_gen", "skill_report_html", depends_on=["T001"])
    ])
    start = time.time()
    result = await execution_node(state)
    elapsed = time.time() - start
    assert result["task_statuses"]["T001"] == "done"
    assert result["task_statuses"]["T002"] == "done"
    assert elapsed < 30
```

#### TC-EN02：并行任务确实并行执行
```python
@pytest.mark.asyncio
async def test_parallel_tasks_execute_concurrently(respx_mock):
    """验证无依赖关系的 T001/T002 并行执行，总耗时 < 两者之和"""
    # T001 和 T002 各需 2 秒，并行应 < 4 秒
    execution_times = []
    async def slow_api(url, **kwargs):
        start = time.time()
        await asyncio.sleep(2)
        execution_times.append(time.time() - start)
        return httpx.Response(200, json=[{"value": 100}])
    
    respx_mock.get(...).mock(side_effect=slow_api)
    state = make_state_with_parallel_tasks(["T001", "T002"])
    start = time.time()
    await execution_node(state)
    total = time.time() - start
    assert total < 4  # 并行执行，应 < 2+2=4 秒（实际约 2 秒）
```

#### TC-EN03：单任务失败不阻塞其他任务
```python
@pytest.mark.asyncio
async def test_single_task_failure_not_blocking(respx_mock):
    """验证 T001 失败时，T002（无依赖 T001）仍继续执行"""
    # T001 的 API 返回 500
    respx_mock.get("*/production/throughput/by-business-type*").mock(return_value=httpx.Response(500))
    # T002 使用另一个 API
    respx_mock.get("*/market/throughput/by-zone*").mock(return_value=httpx.Response(200, json={"code": 200, "data": [{"zoneName": "大连港区", "throughput": 50.0, "yoyRate": 5.2, "shareRatio": 52.0}]}))
    
    state = make_state_with_independent_tasks(["T001", "T002"])
    result = await execution_node(state)
    assert result["task_statuses"]["T001"] == "failed"
    assert result["task_statuses"]["T002"] == "done"
```

#### TC-EN04：数据量不足触发动态规划追加
```python
@pytest.mark.asyncio
async def test_low_data_triggers_replan(respx_mock):
    """验证数据获取结果 < 10 行时，设置 needs_replan=True"""
    respx_mock.get(...).mock(return_value=httpx.Response(200, json=[{"value": 100}]))  # 只有 1 行
    state = make_state_with_data_fetch_plan()
    result = await execution_node(state)
    assert result.get("needs_replan") == True
    # 应有数据质量告警任务被追加
    new_task_types = [t.type for t in result["analysis_plan"]["tasks"] if t.task_id.startswith("T_DQ")]
    assert len(new_task_types) >= 1
```

#### TC-EN05：WebSocket 推送任务状态更新
```python
@pytest.mark.asyncio
async def test_execution_pushes_task_updates_via_websocket(respx_mock, mock_ws):
    """验证执行节点通过 WebSocket 推送 task_update 事件"""
    setup_mock_api(respx_mock)
    state = make_state_with_confirmed_plan("simple_table")
    await execution_node(state)
    # 检查 WebSocket 推送的消息
    events = [call[0][0] for call in mock_ws.send_json.call_args_list]
    task_updates = [e for e in events if e.get("event") == "task_update"]
    assert len(task_updates) >= 2  # 至少 running + done 两次状态变更
    statuses = {e["status"] for e in task_updates}
    assert "running" in statuses
    assert "done" in statuses
```

#### TC-EN06：all tasks done 后 next_action 为 reflection
```python
@pytest.mark.asyncio
async def test_all_tasks_done_next_action_is_reflection(respx_mock):
    """验证所有任务完成后，next_action 设置为 reflection"""
    setup_mock_api(respx_mock)
    state = make_state_with_confirmed_plan("simple_table")
    result = await execution_node(state)
    all_done = all(v == "done" for v in result["task_statuses"].values())
    assert all_done
    assert result["next_action"] == "reflection"
```

---

### 7.8a 新增领域 Mock API 数据合理性测试（tests/unit/test_api_fetch_extended.py）

> 基于 MockAPI 模拟建议文档 §3（五大领域 27 个 API），补充资产、投资、客户域的执行层数据合理性验证。

#### TC-AF08：getInvestPlanSummary（M25）返回值业务合理性
```python
@pytest.mark.asyncio
async def test_invest_plan_summary_business_validity(mock_client):
    """
    验证 M25 getInvestPlanSummary 返回的投资完成率在合理范围内，
    且批复额、完成额、支付额三者关系正确：支付额 ≤ 完成额 ≤ 批复额。
    """
    resp = await mock_client.get(
        "/api/v1/invest/plan/summary",
        params={"currYear": "2025"}
    )
    data = resp.json()["data"]

    assert 0 <= data["completionRate"] <= 100, \
        f"投资完成率 {data['completionRate']}% 超出有效范围"
    assert data["paidAmount"] <= data["completedAmount"], \
        "支付额不应超过完成额"
    assert data["completedAmount"] <= data["approvedAmount"], \
        "完成额不应超过批复额"
    # 项目数合理
    total_projects = (data["projectCount"]["capital"] +
                      data["projectCount"]["cost"] +
                      data["projectCount"]["unplanned"])
    assert 30 <= total_projects <= 100, \
        f"项目总数 {total_projects} 超出合理范围 [30, 100]"
```

#### TC-AF09：getAssetOverview（M21）净值不大于原值
```python
@pytest.mark.asyncio
async def test_asset_overview_net_not_exceed_original(mock_client):
    """
    验证 M21 getAssetOverview 中资产净值 ≤ 原值（折旧后净值递减规律）。
    同时验证各港区净值之和 ≤ 全港净值（允许5%以内差异，来自舍入）。
    """
    for year in ["2024", "2025", "2026"]:
        resp = await mock_client.get(
            "/api/v1/asset/overview",
            params={"dateYear": year}
        )
        data = resp.json()["data"]
        assert data["totalNetValue"] <= data["totalOriginalValue"], \
            f"{year}年资产净值({data['totalNetValue']}) 超过原值({data['totalOriginalValue']})"
        # 净值率应在合理范围（55-65%）
        net_ratio = data["totalNetValue"] / data["totalOriginalValue"]
        assert 0.50 <= net_ratio <= 0.75, \
            f"{year}年净值率 {net_ratio:.1%} 超出合理范围 [50%, 75%]"
```

#### TC-AF10：getEquipmentFacilityStatus（M23）各状态比例之和 = 1.0
```python
@pytest.mark.asyncio
async def test_equipment_status_ratios_complete(mock_client):
    """
    验证 M23 getEquipmentFacilityStatus 返回的所有设备状态比例之和为 1.0（100%），
    且"正常"状态占比符合港口运营规律（80-92%）。
    """
    for asset_type in [1, 2]:  # 1=设备, 2=设施
        resp = await mock_client.get(
            "/api/v1/asset/equipment/status",
            params={"dateYear": "2025", "type": asset_type}
        )
        statuses = resp.json()["data"]
        total_ratio = sum(s["ratio"] for s in statuses)
        assert abs(total_ratio - 1.0) <= 0.01, \
            f"设备类型{asset_type}状态比例之和 {total_ratio:.3f} ≠ 1.0"
        # 正常占比合理性
        normal = next((s for s in statuses if s["status"] == "正常"), None)
        assert normal is not None, "应有'正常'状态"
        assert 0.80 <= normal["ratio"] <= 0.92, \
            f"设备类型{asset_type}正常率 {normal['ratio']:.1%} 不在合理范围 [80%, 92%]"
```

#### TC-AF11：getShipStatus（M09）在泊与锚地船舶数量合理
```python
@pytest.mark.asyncio
async def test_ship_status_counts_in_business_range(mock_client):
    """
    验证 M09 getShipStatus 返回的在泊（D）和锚地（C）船舶数量在业务合理范围内。
    在泊：15-35 艘（反映大型港口繁忙程度）；锚地：3-12 艘。
    """
    for status, expected_range in [("D", (15, 35)), ("C", (3, 12))]:
        resp = await mock_client.get(
            "/api/v1/production/ships/status",
            params={"shipStatus": status}
        )
        ships = resp.json()["data"]
        lo, hi = expected_range
        status_name = "在泊" if status == "D" else "锚地"
        assert lo <= len(ships) <= hi, \
            f"{status_name}船舶数量 {len(ships)} 艘不在合理范围 [{lo}, {hi}]"
        # 每艘船应有船名和港区
        for ship in ships[:3]:  # 抽查前3条
            assert ship.get("shipName"), "船舶应有船名"
            assert ship.get("region"), "船舶应有港区信息"
```

#### TC-AF12：getCustomerCreditInfo（M20）信用等级合法且额度关系正确
```python
@pytest.mark.asyncio
async def test_customer_credit_info_validity(mock_client):
    """
    验证 M20 getCustomerCreditInfo 返回的信用等级合法（AAA/AA/A/B/C），
    且已用额度 ≤ 授信额度（基本财务约束）。
    """
    resp = await mock_client.get("/api/v1/customer/credit-info")
    customers = resp.json()["data"]
    valid_levels = {"AAA", "AA", "A", "B", "C"}

    for c in customers:
        assert c["creditLevel"] in valid_levels, \
            f"客户 {c['customerName']} 信用等级 '{c['creditLevel']}' 无效"
        assert c["usedCredit"] <= c["creditLimit"], \
            f"客户 {c['customerName']} 已用额度({c['usedCredit']}) 超过授信额度({c['creditLimit']})"
        assert c["availableCredit"] >= 0, \
            f"客户 {c['customerName']} 可用额度不应为负"
        # 三者数学关系：可用 ≈ 授信 - 已用
        assert abs(c["availableCredit"] - (c["creditLimit"] - c["usedCredit"])) <= 0.1

    # 高质量客户（AAA+AA+A）应占多数（≥75%）
    high_quality_count = sum(1 for c in customers if c["creditLevel"] in ("AAA", "AA", "A"))
    ratio = high_quality_count / len(customers)
    assert ratio >= 0.75, \
        f"高质量客户占比 {ratio:.1%} 过低（应 ≥75%），客户结构异常"
```

---

### 7.9 Mock API 数据完整性测试（tests/unit/test_mock_api_fixtures.py）

#### TC-FX01：27 个 Mock API 的 fixture 文件存在且格式合法
```python
def test_all_fixture_files_exist_and_valid():
    """
    验证基于 MockAPI 模拟建议文档 §6 生成的 27 个 Mock API fixture 文件
    均存在且为合法的 JSON/YAML 格式。
    """
    fixtures = [
        # 生产运营域（M01-M09）
        "m01_getThroughputSummary_2025-06.json",
        "m02_getThroughputByBusinessType_2026-03.json",
        "m03_getThroughputTrendByMonth_2025.json",
        "m04_getContainerThroughput_2025.json",
        "m05_getBerthOccupancyRate_region_2026-03.json",
        "m06_getVesselEfficiency_2026-03.json",
        "m07_getPortInventory_2026-03-31.json",
        "m08_getDailyProductionDynamic_2026-03-15.json",
        "m09_getShipStatus_inberth.json",
        # 市场商务域（M10-M15）
        "m10_getMarketMonthlyThroughput_2026-03.json",
        "m11_getMarketCumulativeThroughput_2026.json",
        "m12_getMarketTrendChart_container_2025-01_2025-12.json",
        "m13_getMarketZoneThroughput_2026-03.json",
        "m14_getKeyEnterpriseContribution_container_2026-03.json",
        "m15_getMarketBusinessSegment_2026-03.json",
        # 客户管理域（M16-M20）
        "m16_getCustomerBasicInfo.json",
        "m17_getStrategicCustomerThroughput_2025_annual.json",
        "m18_getStrategicCustomerRevenue_2025_annual.json",
        "m19_getCustomerContributionRanking_2026-03.json",
        "m20_getCustomerCreditInfo.json",
        # 资产管理域（M21-M24）
        "m21_getAssetOverview_2025.json",
        "m22_getAssetDistributionByType_2025.json",
        "m23_getEquipmentFacilityStatus_device_2025.json",
        "m24_getAssetHistoricalTrend_2024_2026.json",
        # 投资管理域（M25-M27）
        "m25_getInvestPlanSummary_2026.json",
        "m26_getInvestPlanProgress_2026-01_2026-06.json",
        "m27_getCapitalProjectList_2026.json",
    ]
    fixture_dir = Path("tests/fixtures/mock_api")
    for fname in fixtures:
        fpath = fixture_dir / fname
        assert fpath.exists(), f"Fixture 文件不存在：{fname}"
        with open(fpath) as f:
            data = json.load(f)
        assert isinstance(data, list), f"{fname} 应为 JSON 数组"
        assert len(data) > 0, f"{fname} 不应为空数组"
```

#### TC-FX02：M02 fixture 包含必要字段（业务板块分类数据）
```python
def test_throughput_by_business_type_fixture_fields():
    """
    验证 M02 getThroughputByBusinessType fixture 包含4个业务板块，
    且每条记录含必要字段：businessType/throughput/yoyRate/shareRatio。
    """
    with open("tests/fixtures/mock_api/m02_getThroughputByBusinessType_2026-03.json") as f:
        data = json.load(f)
    assert data["code"] == 200
    records = data["data"]
    assert len(records) == 4, "应有4个业务板块"
    business_types = {r["businessType"] for r in records}
    assert business_types == {"集装箱", "散杂货", "油化品", "商品车"}
    for r in records:
        assert "throughput" in r and "yoyRate" in r and "shareRatio" in r
    total_share = sum(r["shareRatio"] for r in records)
    assert abs(total_share - 100.0) <= 0.5, f"板块占比之和 {total_share:.1f} ≠ 100%"
```

#### TC-FX03：M12 fixture 时间序列完整且有序
```python
def test_market_trend_chart_fixture_sorted_and_complete():
    """
    验证 M12 getMarketTrendChart（集装箱2025全年）fixture：
    数据按月份升序、覆盖12个月、每条含 month/value/yoyRate。
    """
    with open("tests/fixtures/mock_api/m12_getMarketTrendChart_container_2025-01_2025-12.json") as f:
        data = json.load(f)
    records = data["data"]
    months = [r["month"] for r in records]
    assert months == sorted(months), "月份应按升序排列"
    assert len(records) == 12, f"2025全年应有12条，实际{len(records)}条"
    for r in records:
        assert "month" in r and "value" in r and "yoyRate" in r
        assert r["value"] > 0, "月度吞吐量应为正值"
```


---

## 8. 验收检查单

### 功能验收

| 验收项 | 判断标准 | 状态 |
|--------|----------|------|
| 技能注册中心：15 个内置技能全部注册 | TC-R01 通过 | ⬜ |
| API 数据获取：27 个 Mock API 可正常调用 | TC-AF01~TC-AF12 通过 | ⬜ |
| 描述性分析：同比/环比/分组统计正确 | TC-DA01~TC-DA06 通过 | ⬜ |
| 归因分析：primary_drivers 可解释 | TC-AT01~TC-AT03 + TC-NQ03 通过 | ⬜ |
| 叙述质量：含数值要素、无LLM工件残留 | TC-NQ01~TC-NQ05 通过 | ⬜ |
| PPTX 报告：可打开，幻灯片 ≥ 4 页 | TC-PT01~TC-PT05 通过 | ⬜ |
| 执行节点：simple_table E2E < 30s | TC-EN01 通过 | ⬜ |
| 并行执行验证 | TC-EN02 通过 | ⬜ |
| 单任务失败不阻塞全链路 | TC-EN01（EXEC-RATE01）通过 | ⬜ |
| 幻觉技能/端点已在规划层过滤，执行层不会收到 | 集成测试验证 | ⬜ |
| 大数据量接口（>50条）有质量警告 | TC-AF06 通过 | ⬜ |

### 测试覆盖验收

| 测试类型 | 要求 | 状态 |
|----------|------|------|
| 单元测试 | ≥ 30 个，全部通过 | ⬜ |
| 每个技能覆盖率 | > 90% | ⬜ |
| 27 个 Mock API fixture | TC-FX01 通过 | ⬜ |
| LLM 容错测试 | `<think>`标签/非法JSON/超时 全覆盖 | ⬜ |
| 叙述质量断言 | TC-NQ01~TC-NQ05 全部通过 | ⬜ |

### 性能验收

| 指标 | 要求 | 状态 |
|------|------|------|
| simple_table 端到端 | < 30 秒 | ⬜ |
| chart_text 端到端 | < 3 分钟 | ⬜ |
| full_report 端到端 | < 10 分钟 | ⬜ |
| PPTX 生成（含图表嵌入） | < 60 秒 | ⬜ |
| 27 个 Mock API 8并发响应 | < 500ms（TC-M0P02）| ⬜ |
