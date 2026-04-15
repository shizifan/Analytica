# Analytica · Phase 2：规划层与状态机

---

## 版本记录

| 版本号 | 日期 | 修订说明 | 编制人 |
|--------|------|----------|--------|
| v1.0 | 2026-04-14 | 从实施方案 v1.3 拆分，补充 PRD 章节与完整测试用例集 | FAN |

---

## 目录

1. [阶段目标与交付物](#1-阶段目标与交付物)
2. [PRD 关联章节](#2-prd-关联章节)
3. [实施方案：Sprint 4 — 规划层核心](#3-实施方案sprint-4--规划层核心)
4. [实施方案：Sprint 5 — 规划展示 API](#4-实施方案sprint-5--规划展示-api)
5. [测试用例集](#5-测试用例集)
6. [验收检查单](#6-验收检查单)

---

## 1. 阶段目标与交付物

**时间窗口：** Week 3–4（Day 11–17）

**前置条件：** Phase 1 全部验收通过（感知层 CLI Demo 运行正常，MySQL 表结构完整）

**阶段目标：** 实现分析方案生成、展示与用户确认流程，搭建完整 LangGraph 四节点状态机骨架（execution/reflection 为 stub）。

**可运行交付物：**

| 交付物 | 验证方式 |
|--------|----------|
| 规划节点：输入 StructuredIntent → 输出 AnalysisPlan | Postman 端到端测试 |
| LangGraph 完整状态机（含 Human-in-the-Loop 暂停） | 会话持久化验证 |
| 规划确认 REST API（GET/POST/PATCH） | Postman 测试 3 个端点 |
| 单元测试 ≥ 15 个，全部通过 | `pytest tests/unit/ -v` |

---

## 2. PRD 关联章节

### 2.1 规划层完整设计（来自 PRD §4.2）

#### 2.1.1 模块职责

规划层接收感知层输出的结构化意图，调用 LLM 生成一份 **Analysis Plan**（分析方案），将整个分析任务拆解为有序的任务清单（Task List），展示给用户确认后触发执行层。

规划层的核心能力：
- 根据分析目标的复杂度，动态生成合适数量的任务（simple_table 2–3 个，full_report 5–8 个）
- 将可用数据源端点（10 个 Mock API）和技能清单注入规划 Prompt
- 支持用户修改方案（删除任务、修改格式、追加步骤）
- 版本管理：每次修改自动递增 plan_version，保留修改记录

#### 2.1.2 任务（Task）数据结构

```json
{
  "task_id": "T001",
  "type": "data_fetch | search | analysis | visualization | report_gen",
  "name": "任务名称",
  "description": "对用户友好的描述（中文，简洁）",
  "depends_on": ["T000"],
  "skill": "skill_api_fetch",
  "params": {
    "datasource_id": "ds_port_ops",
    "endpoint_id": "getThroughputByBusinessType",  // M02
    "curDateMonth": "202601"
  },
  "estimated_seconds": 30
}
```

#### 2.1.3 规划展示格式（Markdown，展示给用户确认）

```
📋 **分析方案 · v1**（预计完成时间：约 2 分钟）

**分析目标：** 2026年1月集装箱吞吐量查询

任务清单：
✅ T001 · 获取月度吞吐量数据 _(数据获取 · 预计 30 秒)_
   → 来源：getThroughputByBusinessType（M02），按业务板块分类
✅ T002 · 生成数据表格 _(报告生成 · 预计 10 秒)_
   → 格式：Markdown 内联表格

---
[确认执行] [修改方案] [重新规划]
```

#### 2.1.4 规划 LLM Prompt 关键要素

规划 Prompt 必须注入以下上下文，否则 LLM 会生成无法执行的幻觉任务：

| 注入内容 | 来源 | 注入方式 |
|----------|------|----------|
| 可用 API 端点列表（含 when_to_use + known_caveats） | 数据源配置 | 动态注入 |
| 可用技能清单（skill_id + description） | 技能注册中心 `get_skills_description()` | 动态注入 |
| StructuredIntent（含槽值和 source） | 感知层输出 | 直接传入 |
| 历史分析模板骨架（若有） | MySQL analysis_templates 表 | `find_templates()` |
| 来自记忆的槽值标注 | 感知层 slots[x].source == "memory" | 在描述中标注 |

#### 2.1.5 规划层与 10 个 Mock API 端点的选取规则

规划 Prompt 需根据 StructuredIntent 中的分析意图，注入 `when_to_use` 语义让 LLM 自主选择合适接口：

| 分析意图关键词 | 优先选取接口 |
|---------------|-------------|
| 全港总吞吐量（生产视角） | `getThroughputSummary`（M01） |
| 按业务板块分类吞吐量 | `getThroughputByBusinessType`（M02） |
| 月度趋势折线图数据 | `getThroughputTrendByMonth`（M03） |
| 集装箱 TEU 专项查询 | `getContainerThroughput`（M04） |
| 泊位占用率分析 | `getBerthOccupancyRate`（M05） |
| 船舶作业效率 | `getVesselEfficiency`（M06） |
| 港存货物量 | `getPortInventory`（M07） |
| 市场当月总量（市场视角） | `getMarketMonthlyThroughput`（M10） |
| 市场年度累计 | `getMarketCumulativeThroughput`（M11） |
| 市场趋势图（板块） | `getMarketTrendChart`（M12）⚠️ businessSegment必填 |
| 各港区对比 | `getMarketZoneThroughput`（M13） |
| 重点企业贡献排名 | `getKeyEnterpriseContribution`（M14） |
| 业务板块占比 | `getMarketBusinessSegment`（M15） |
| 战略客户货量 | `getStrategicCustomerThroughput`（M17） |
| 客户贡献排名 | `getCustomerContributionRanking`（M19） |
| 资产总览 | `getAssetOverview`（M21） |
| 投资计划汇总 | `getInvestPlanSummary`（M25） |
| 投资月度进度 | `getInvestPlanProgress`（M26） |

**关键约束（known_caveats 注入规划 Prompt）：**
- `getMarketTrendChart`（M12）的 `businessSegment` 为必填参数，枚举值：集装箱/散杂货/油化品/商品车/全货类
- `getCustomerContributionRanking`（M19）的 `topN` 上限为 50，超限自动截断
- `getStrategicCustomerThroughput`（M17）vs `getCustomerContributionRanking`（M19）：战略客户专项 vs 全量排名，不可混用
- 集装箱有双单位（TEU 和吨），不可直接加总

### 2.2 典型使用场景（来自 PRD §2.2）

规划层需为以下三种场景生成合理的任务数量：

| 场景 | 输出复杂度 | 典型任务数 | 规划时间上限 |
|------|-----------|-----------|-------------|
| A：简单数据查询 | simple_table | 2–3 | < 5 秒 |
| B：图文分析 | chart_text | 3–5 | < 10 秒 |
| C：完整报告 | full_report | 5–8 | < 20 秒 |

### 2.3 LangGraph 状态机设计（来自实施方案 §2.3, §5.1）

```
START → perception
perception → perception     (empty_required_slots 非空，自循环等待)
perception → planning       (structured_intent 已设置)
planning → planning         (plan_confirmed == False，Human-in-the-Loop 暂停)
planning → execution        (plan_confirmed == True)
execution → execution       (按任务队列执行，直至完成)
execution → planning        (发现需追加任务)
execution → reflection      (所有任务完成)
reflection → END
```

**MySQLCheckpointSaver：** 继承 LangGraph `BaseCheckpointSaver`，实现 `put/get/list` 三个异步方法，底层使用 `sessions` 表中的 `state_json` 列存储序列化的 Checkpoint JSON。

### 2.4 规划层 UX 设计（来自 PRD §7.3）

| 状态 | 视觉反馈 | 用户可操作 |
|------|----------|-----------|
| 规划生成中 | 任务清单逐行展开（流式） | 等待 |
| 等待确认 | 完整任务清单 + 三个按钮 | 确认执行 / 修改方案 / 重新规划 |
| 用户修改中 | 任务可删除/重排 | 编辑后点「确认修改」 |
| 方案已确认 | 进度条出现 | 查看详情、暂停 |

---

## 3. 实施方案：Sprint 4 — 规划层核心

**时间：** Day 11–14

### 3.1 AI Coding Prompt：规划节点

```
【任务】实现 LangGraph 规划节点（backend/agent/planning.py）。

【上下文】
- 已有：AgentState，StructuredIntent，SlotFillingEngine，MySQL 数据库
- LLM：Qwen3-235B（OpenAI 兼容），注意 <think> 标签剥离和严格 JSON 输出
- 陷阱：LLM 可能生成不存在的 endpoint_id 或 skill_id，需验证后过滤

【任务结构定义】（backend/models/schemas.py 新增）

Task:
  task_id: str              # T001, T002, ...
  type: Literal["data_fetch", "search", "analysis", "visualization", "report_gen"]
  name: str
  description: str
  depends_on: List[str]     # task_id 列表
  skill: str                # 技能注册中心中的 skill_id
  params: dict              # 技能调用参数
  estimated_seconds: int

AnalysisPlan:
  plan_id: str
  version: int              # 从 1 开始
  title: str
  analysis_goal: str
  estimated_duration: int   # 秒
  tasks: List[Task]
  report_structure: Optional[dict]  # 仅 full_report 时填充
  revision_log: List[dict]  # [{version, changed_at, change_summary}]

【核心逻辑】

planning_node(state: AgentState) -> AgentState:
  1. 如果 plan_confirmed == True，直接 next_action="execution"，返回
  2. 从 structured_intent 提取 complexity、slots
  3. 从技能注册中心获取技能描述（get_skills_description()）
  4. 从数据源配置获取端点列表（含 when_to_use + known_caveats）
  5. 调用 find_templates() 查询历史模板骨架（无结果时忽略）
  6. 调用 Qwen3 生成 Analysis Plan JSON
  7. 验证：所有 task.skill 必须在注册中心存在；所有 task.params.endpoint_id 必须在配置中存在
     对不合法的任务：记录警告日志，从 tasks 中移除
  8. 生成 Markdown 展示文本，写入 messages
  9. 设置 plan_confirmed=False，Human-in-the-Loop 暂停
  10. WebSocket 推送 { "event": "plan_generated", "plan": plan_json }

【规划 LLM Prompt 关键要素】
- 注入可用端点清单（含 when_to_use）
- 注入可用技能清单
- 注入 StructuredIntent
- 若有模板骨架，附加「参考模板」提示
- simple_table 任务数 2-3，chart_text 3-5，full_report 5-8
- 对 getMarketTrendChart（M12），要求 params 中包含必填的 businessSegment 过滤
- 输出严格 JSON，无 <think> 块，无 markdown 包裹

【还需要】
- format_plan_as_markdown(plan: AnalysisPlan) -> str 格式化方法
- update_plan(plan, modifications) -> AnalysisPlan 更新方法（追加版本记录）

【约束】
- LLM 调用超时 60s（规划比感知慢）
- plan_id 用 uuid4 生成
- 全异步，类型注解

【输出】backend/agent/planning.py + schemas.py 更新
```

### 3.2 AI Coding Prompt：LangGraph 完整状态机

```
【任务】组装完整的 LangGraph 状态机，连接四个阶段节点（backend/agent/graph.py）。

【边逻辑（严格按照条件实现）】

def route_after_perception(state) -> str:
    if state["empty_required_slots"]:
        return "perception"   # 自循环，等待用户回复
    return "planning"

def route_after_planning(state) -> str:
    if not state["plan_confirmed"]:
        return "__end__"      # Human-in-the-Loop 暂停，等待 /plan/confirm 触发恢复
    return "execution"

def route_after_execution(state) -> str:
    if state.get("needs_replan"):
        return "planning"
    all_done = all(v == "done" for v in state["task_statuses"].values())
    if all_done:
        return "reflection"
    return "execution"

【MySQLCheckpointSaver】
继承 BaseCheckpointSaver：
- put(config, checkpoint, metadata, new_versions) -> RunnableConfig
  序列化 checkpoint 为 JSON，upsert 到 sessions.state_json（ON DUPLICATE KEY UPDATE）
- get(config) -> Optional[Checkpoint]
  从 sessions 表按 session_id 反序列化
- list(config, ...) -> Iterator[CheckpointTuple]
  按 session_id 返回历史快照（MVP 阶段只保存最新一个）

【流式执行方法】
async def run_stream(session_id: str, user_message: str) -> AsyncGenerator[dict, None]:
    推送 {"event": "phase_enter", "phase": "perception"/"planning"/...}
    通过 LangGraph .astream() 执行图，每个节点完成后 yield 状态更新

【输出】backend/agent/graph.py 完整代码
```

---

## 4. 实施方案：Sprint 5 — 规划展示 API

**时间：** Day 15–17

### 4.1 AI Coding Prompt：规划确认 API 端点

```
【任务】实现规划确认相关的 REST API 端点（backend/main.py 扩展）。

1. GET /api/sessions/{session_id}/plan
   - 返回 AnalysisPlan JSON + markdown_display 字段
   - 包含版本号和修改历史

2. POST /api/sessions/{session_id}/plan/confirm
   Body: {"confirmed": true, "modifications": [{"type": "remove_task", "task_id": "T003"}]}
   - 应用修改，递增 plan_version，写入 revision_log
   - 设置 plan_confirmed=True，触发 LangGraph 从 planning 继续执行
   - 返回更新后的 plan

3. POST /api/sessions/{session_id}/plan/regenerate
   Body: {"feedback": "请增加同比分析步骤"}
   - 将用户反馈注入重规划 Prompt
   - 重新调用 planning_node
   - plan_version 递增，保留 revision_log

【要求】
- 操作幂等：已确认的 plan 再次 confirm 应返回 200 而非报错
- Pydantic v2 验证请求/响应
- 写操作前验证 session_id 存在
- 异步实现

【输出】backend/main.py 添加三个路由
```

---

## 5. 测试用例集

> **设计原则：** 规划层的 LLM 不确定性主要体现在：（1）生成的任务合法性（是否引用了不存在的技能/端点）；（2）任务数量和结构的合理性；（3）依赖关系图的有向无环性；（4）全报告场景的覆盖完整性。测试设计重点覆盖这四类风险，并大量使用固定 Mock LLM 输出。

### 5.1 规划节点基础测试（tests/unit/test_planning.py）

#### TC-P01：simple_table 场景生成 2–3 个任务
```python
@pytest.mark.asyncio
async def test_simple_table_generates_2_to_3_tasks(mock_planning_llm):
    """验证 simple_table 场景下 LLM 生成 2-3 个任务"""
    mock_planning_llm.return_value = json.dumps({
        "title": "集装箱月度吞吐量查询",
        "estimated_duration": 45,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch", "name": "获取月度板块数据", "depends_on": [], "skill": "skill_api_fetch", "params": {"endpoint_id": "getThroughputByBusinessType"}, "estimated_seconds": 10},
            {"task_id": "T002", "type": "report_gen", "name": "生成表格", "depends_on": ["T001"], "skill": "skill_report_html", "params": {}, "estimated_seconds": 10}
        ]
    })
    intent = make_structured_intent("simple_table")
    plan = await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert 2 <= len(plan.tasks) <= 3
```

#### TC-P02：full_report 场景生成 5–8 个任务
```python
@pytest.mark.asyncio
async def test_full_report_generates_5_to_8_tasks(mock_planning_llm):
    """验证 full_report 场景生成的任务数量在 5-8 个范围内"""
    mock_planning_llm.return_value = make_full_report_plan_json(task_count=6)
    intent = make_structured_intent("full_report")
    plan = await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert 5 <= len(plan.tasks) <= 8
```

#### TC-P03：任务依赖关系无环
```python
@pytest.mark.asyncio
async def test_task_dependencies_are_acyclic(mock_planning_llm):
    """验证生成的任务依赖图是有向无环图（DAG）"""
    mock_planning_llm.return_value = make_full_report_plan_json(task_count=6)
    intent = make_structured_intent("full_report")
    plan = await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    # 检测环：对 depends_on 构建图，运行 DFS 拓扑排序
    graph = {t.task_id: t.depends_on for t in plan.tasks}
    assert not has_cycle(graph), "任务依赖图中存在环"
```

#### TC-P04：任务依赖引用的 task_id 必须存在
```python
@pytest.mark.asyncio
async def test_task_dependency_references_exist(mock_planning_llm):
    """验证所有 depends_on 中引用的 task_id 均在 tasks 列表中存在"""
    mock_planning_llm.return_value = make_full_report_plan_json(task_count=5)
    intent = make_structured_intent("full_report")
    plan = await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    all_task_ids = {t.task_id for t in plan.tasks}
    for task in plan.tasks:
        for dep in task.depends_on:
            assert dep in all_task_ids, f"任务 {task.task_id} 依赖不存在的 {dep}"
```

#### TC-P05：幻觉技能被过滤
```python
@pytest.mark.asyncio
async def test_hallucinated_skill_filtered_out(mock_planning_llm):
    """
    验证 LLM 生成了不在 VALID_SKILL_IDS 中的技能 ID 时，该任务被过滤而非引发崩溃。
    使用真实业务场景下 LLM 可能幻觉的技能名称（非明显乱码）。
    """
    plan_with_fake_skill = {
        "title": "测试",
        "estimated_duration": 30,
        "tasks": [
            {"task_id": "T001", "type": "data_fetch", "name": "真实任务", "depends_on": [],
             "skill": "skill_api_fetch", "params": {}, "estimated_seconds": 10},
            # LLM 幻觉：真实业务中不存在的技能（港口特有幻觉）
            {"task_id": "T002", "type": "analysis", "name": "港口排名分析", "depends_on": [],
             "skill": "skill_port_national_ranking", "params": {}, "estimated_seconds": 10},
            {"task_id": "T003", "type": "analysis", "name": "收入预测", "depends_on": [],
             "skill": "skill_revenue_forecast_external", "params": {}, "estimated_seconds": 10},
        ]
    }
    mock_planning_llm.return_value = json.dumps(plan_with_fake_skill)
    intent = make_structured_intent("simple_table")
    plan = await generate_plan(
        intent,
        available_skills={"skill_api_fetch": {}},
        available_endpoints=MOCK_ENDPOINTS
    )
    task_ids = {t.task_id for t in plan.tasks}
    assert "T001" in task_ids
    assert "T002" not in task_ids, "幻觉技能 skill_port_national_ranking 应被过滤"
    assert "T003" not in task_ids, "幻觉技能 skill_revenue_forecast_external 应被过滤"
```

#### TC-P06：幻觉端点被过滤（基于 27 个合法 Mock API）
```python
@pytest.mark.asyncio
async def test_hallucinated_endpoint_filtered_out(mock_planning_llm):
    """
    验证 LLM 生成了不在 M01-M27 中的端点名称时，该任务被过滤。
    使用真实业务场景下可能产生的幻觉端点（非明显随机字符串）。
    """
    plan_with_fake_endpoint = {
        "title": "测试",
        "tasks": [
            # 合法端点（M01）
            {"task_id": "T001", "type": "data_fetch", "name": "获取吞吐量",
             "depends_on": [], "skill": "skill_api_fetch",
             "params": {"endpoint_id": "getThroughputSummary"}, "estimated_seconds": 10},
            # 幻觉端点：听起来合理但不在 M01-M27 中
            {"task_id": "T002", "type": "data_fetch", "name": "全国排名",
             "depends_on": [], "skill": "skill_api_fetch",
             "params": {"endpoint_id": "getPortNationalRanking"}, "estimated_seconds": 10},
            # 幻觉端点：收入类（Mock API 仅战略客户有收入，无通用收入端点）
            {"task_id": "T003", "type": "data_fetch", "name": "业务线收入",
             "depends_on": [], "skill": "skill_api_fetch",
             "params": {"endpoint_id": "getRevenueByBusinessType"}, "estimated_seconds": 10},
            # 幻觉端点：预测类（Mock API 不含预测端点）
            {"task_id": "T004", "type": "data_fetch", "name": "2027预测",
             "depends_on": [], "skill": "skill_api_fetch",
             "params": {"endpoint_id": "getForecast2027"}, "estimated_seconds": 10},
        ]
    }
    mock_planning_llm.return_value = json.dumps(plan_with_fake_endpoint)
    intent = make_structured_intent("simple_table")
    valid_endpoints = {"getThroughputSummary": {}}  # 只有 M01 合法
    plan = await generate_plan(
        intent,
        available_skills=MOCK_SKILLS,
        available_endpoints=valid_endpoints
    )
    endpoint_ids = {t.params.get("endpoint_id") for t in plan.tasks}
    assert "getThroughputSummary" in endpoint_ids
    assert "getPortNationalRanking" not in endpoint_ids
    assert "getRevenueByBusinessType" not in endpoint_ids
    assert "getForecast2027" not in endpoint_ids
```

#### TC-P07：LLM 输出含 <think> 标签被正确剥离
```python
@pytest.mark.asyncio
async def test_planning_strips_think_tags():
    """验证规划节点处理 Qwen3 <think> 推理块后能正常解析 JSON"""
    raw = "<think>规划思考过程...</think>\n" + json.dumps({
        "title": "测试", "estimated_duration": 30,
        "tasks": [{"task_id": "T001", "type": "data_fetch", "name": "获取数据",
                   "depends_on": [], "skill": "skill_api_fetch", "params": {}, "estimated_seconds": 10}]
    })
    plan = parse_planning_llm_output(raw)
    assert plan["title"] == "测试"
    assert len(plan["tasks"]) == 1
```

#### TC-P08：LLM 输出非法 JSON 的容错
```python
@pytest.mark.asyncio
async def test_planning_invalid_json_raises_planning_error(mock_planning_llm):
    """验证 LLM 返回非法 JSON 时抛出 PlanningError 而非 crash"""
    mock_planning_llm.return_value = "这不是JSON，我在思考但忘记输出JSON了"
    intent = make_structured_intent("simple_table")
    with pytest.raises(PlanningError, match="json"):
        await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
```

#### TC-P09：大数据量接口强制注入过滤参数提示
```python
@pytest.mark.asyncio
async def test_large_data_endpoint_gets_filter_hint_in_prompt(mock_planning_llm, captured_prompt):
    """验证调用 getMarketTrendChart（M12）时，规划 Prompt 中包含 businessSegment 必填约束提示"""
    intent = make_structured_intent("chart_text", subject=["货类结构"])
    await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    # 检查 LLM 收到的 prompt 中包含对大数据量端点的过滤提示
    prompt_text = captured_prompt.get_last_prompt()
    assert "businessSegment" in prompt_text or "过滤" in prompt_text
```

#### TC-P10：full_report 包含 report_structure 字段
```python
@pytest.mark.asyncio
async def test_full_report_plan_has_report_structure(mock_planning_llm):
    """验证 full_report 场景生成的计划包含 report_structure 字段"""
    mock_planning_llm.return_value = json.dumps({
        "title": "港口运营报告",
        "estimated_duration": 600,
        "tasks": [make_task(f"T00{i}") for i in range(1, 7)],
        "report_structure": {
            "sections": ["封面", "目录", "趋势分析", "归因分析", "结论"]
        }
    })
    intent = make_structured_intent("full_report")
    plan = await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    assert plan.report_structure is not None
    assert "sections" in plan.report_structure
```

#### TC-P11：Markdown 展示格式验证
```python
def test_plan_markdown_format():
    """验证格式化后的 Markdown 包含任务 ID、名称和类型"""
    plan = make_test_plan(task_count=3, complexity="chart_text")
    md = format_plan_as_markdown(plan)
    assert "T001" in md
    assert "T002" in md
    assert "T003" in md
    assert "预计" in md  # 时间估计
    assert "[确认执行]" in md or "确认" in md
```

---

### 5.2 规划层与 Mock API 端点匹配测试（tests/unit/test_planning_endpoint_selection.py）

> 基于 MockAPI 模拟建议文档 §5.1「意图识别→API映射规则」，验证规划层的语义路由逻辑。

#### TC-A01：生产域总量查询选取 getThroughputSummary（M01）
```python
@pytest.mark.asyncio
async def test_production_total_query_uses_throughput_summary(mock_planning_llm, captured_prompt):
    """
    「本月全港总吞吐量」意图 → 规划 Prompt 中 getThroughputSummary 被标记为首选。
    对应 MockAPI §5.1 路由规则：「吞吐量 + 总量/全港 → M01 getThroughputSummary」
    """
    intent = make_structured_intent(
        "simple_table", domain="production",
        subject=["本月全港总吞吐量"], time_range_desc="本月"
    )
    await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    prompt = captured_prompt.get_last_prompt()
    assert "getThroughputSummary" in prompt, \
        "全港总量意图应在 Prompt 中标注 getThroughputSummary"
    assert "when_to_use" in prompt.lower() or "适用" in prompt
```

#### TC-A02：市场域当月查询优先 getMarketMonthlyThroughput（M10），而非生产域 M01
```python
@pytest.mark.asyncio
async def test_market_monthly_prefers_M10_over_M01(mock_planning_llm, captured_prompt):
    """
    「本月市场完成情况」意图 → 选 M10 getMarketMonthlyThroughput，不选 M01。
    这是关键路由歧义消除测试：市场域 vs 生产域的「总量」概念区分。
    对应 MockAPI §5.1 路由规则：「市场 + 当月/本月 → M10 getMarketMonthlyThroughput」
    """
    intent = make_structured_intent(
        "simple_table", domain="market",
        subject=["本月市场完成"], time_range_desc="本月"
    )
    await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    prompt = captured_prompt.get_last_prompt()
    assert "getMarketMonthlyThroughput" in prompt, \
        "市场当月意图应标注 getMarketMonthlyThroughput"
    # M01 不应被标注为市场域的首选（避免混用）
    assert prompt.count("getThroughputSummary") <= prompt.count("getMarketMonthlyThroughput"), \
        "市场当月查询中 M10 应比 M01 有更高优先级"
```

#### TC-A03：趋势图查询 getMarketTrendChart（M12）的 businessSegment 必填约束注入
```python
@pytest.mark.asyncio
async def test_trend_chart_business_segment_required_injected(mock_planning_llm, captured_prompt):
    """
    「集装箱趋势」意图 → getMarketTrendChart 的 businessSegment 必填约束被注入 Prompt。
    对应 MockAPI §3.2 M12：businessSegment 为必填参数。
    """
    intent = make_structured_intent(
        "chart_text", domain="market",
        subject=["集装箱趋势图"], cargo_type="集装箱"
    )
    await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    prompt = captured_prompt.get_last_prompt()
    assert "businessSegment" in prompt, \
        "M12 的 businessSegment 必填约束应出现在规划 Prompt 中"
    assert "必填" in prompt or "required" in prompt.lower()
```

#### TC-A04：客户排名应选 getCustomerContributionRanking（M19），不选战略客户 M17
```python
@pytest.mark.asyncio
async def test_customer_ranking_uses_M19_not_M17(mock_planning_llm, captured_prompt):
    """
    「贡献最大的客户排名」意图 → 选 M19 getCustomerContributionRanking。
    对应 MockAPI §5.1：「客户排名/贡献排名 → M19 getCustomerContributionRanking」
    战略客户 M17/M18 仅用于战略级客户专项分析，不应用于通用排名查询。
    """
    intent = make_structured_intent(
        "simple_table", domain="customer",
        subject=["贡献排名", "前10客户"]
    )
    await generate_plan(intent, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    prompt = captured_prompt.get_last_prompt()
    assert "getCustomerContributionRanking" in prompt
    # M17 不应作为排名查询的首选
    ranking_priority = prompt.find("getCustomerContributionRanking")
    strategic_priority = prompt.find("getStrategicCustomerThroughput")
    assert ranking_priority < strategic_priority or strategic_priority == -1, \
        "排名查询中 M19 应比 M17 有更高优先级"
```

#### TC-A05：投资进度查询区分 getInvestPlanSummary（M25）和 getInvestPlanProgress（M26）
```python
@pytest.mark.asyncio
async def test_invest_progress_curve_uses_M26_not_M25(mock_planning_llm, captured_prompt):
    """
    「投资进度曲线/月度节奏」意图 → 选 M26 getInvestPlanProgress（月度数据）。
    「投资计划总览/完成率」意图 → 选 M25 getInvestPlanSummary（汇总数据）。
    对应 MockAPI §5.1：「投资 + 月度/进度曲线 → M26」vs「投资计划/进度 → M25」
    """
    # 场景1：月度进度节奏 → M26
    intent_progress = make_structured_intent(
        "chart_text", domain="invest",
        subject=["投资进度月度节奏", "计划执行曲线"]
    )
    await generate_plan(intent_progress, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    prompt_progress = captured_prompt.get_last_prompt()
    assert "getInvestPlanProgress" in prompt_progress

    # 场景2：年度完成率汇总 → M25
    intent_summary = make_structured_intent(
        "simple_table", domain="invest",
        subject=["投资计划完成率", "年度投资进度"]
    )
    await generate_plan(intent_summary, available_skills=MOCK_SKILLS, available_endpoints=MOCK_ENDPOINTS)
    prompt_summary = captured_prompt.get_last_prompt()
    assert "getInvestPlanSummary" in prompt_summary
```

---

### 5.3 规划方案管理测试（tests/unit/test_plan_management.py）

#### TC-M01：修改方案后版本号递增
```python
def test_plan_version_increments_on_update():
    """验证每次调用 update_plan 后 version 递增"""
    plan = make_test_plan(version=1)
    updated = update_plan(plan, modifications=[{"type": "remove_task", "task_id": "T003"}])
    assert updated.version == 2
    assert plan.version == 1  # 原对象不变
```

#### TC-M02：修改日志被记录
```python
def test_plan_modification_logged():
    """验证修改操作写入 revision_log"""
    plan = make_test_plan()
    updated = update_plan(plan, modifications=[{"type": "remove_task", "task_id": "T002"}])
    assert len(updated.revision_log) == 1
    log_entry = updated.revision_log[0]
    assert "remove_task" in str(log_entry)
    assert "T002" in str(log_entry)
    assert "changed_at" in log_entry
```

#### TC-M03：删除任务时依赖该任务的其他任务也被处理
```python
def test_remove_task_updates_downstream_dependencies():
    """验证删除 T002 后，T003 的 depends_on=[T002] 被清空或自动处理"""
    plan = make_test_plan_with_deps()  # T003 depends_on T002
    updated = update_plan(plan, modifications=[{"type": "remove_task", "task_id": "T002"}])
    t003 = next((t for t in updated.tasks if t.task_id == "T003"), None)
    if t003:
        # T002 已被删除，T003 的依赖中不应再有 T002
        assert "T002" not in t003.depends_on
```

#### TC-M04：重规划保留原版本历史
```python
@pytest.mark.asyncio
async def test_regen_preserves_revision_history(mock_planning_llm):
    """验证 regenerate 请求生成 v2 计划时，v1 的信息在 revision_log 中"""
    original_plan = make_test_plan(version=1)
    mock_planning_llm.return_value = make_plan_json(task_count=4)
    new_plan = await regenerate_plan(original_plan, feedback="增加同比分析", ...)
    assert new_plan.version == 2
    # revision_log 应包含 v1 → v2 的转变记录
    assert any("feedback" in str(log) or "重新规划" in str(log) for log in new_plan.revision_log)
```

#### TC-M05：幂等确认（已确认后再次确认不报错）
```python
@pytest.mark.asyncio
async def test_confirm_plan_idempotent(client):
    """验证已确认的 plan 再次 confirm 返回 200 而非 4xx"""
    session_id = await create_test_session_with_plan(client)
    # 第一次确认
    resp1 = client.post(f"/api/sessions/{session_id}/plan/confirm", json={"confirmed": True})
    assert resp1.status_code == 200
    # 第二次确认（幂等）
    resp2 = client.post(f"/api/sessions/{session_id}/plan/confirm", json={"confirmed": True})
    assert resp2.status_code == 200
```

---

### 5.4 LangGraph 状态机测试（tests/unit/test_state_machine.py）

#### TC-SM01：感知到规划的状态转移
```python
@pytest.mark.asyncio
async def test_route_perception_to_planning_when_intent_set():
    """验证 structured_intent 已设置时，路由到 planning 节点"""
    state = make_state_with_intent()
    next_node = route_after_perception(state)
    assert next_node == "planning"
```

#### TC-SM02：感知节点有空槽时自循环
```python
def test_route_perception_self_loop_when_empty_slots():
    """验证有空必填槽时，路由回 perception 节点（自循环）"""
    state = make_state_with_empty_slots(["time_range"])
    next_node = route_after_perception(state)
    assert next_node == "perception"
```

#### TC-SM03：规划未确认时暂停
```python
def test_route_planning_to_end_when_not_confirmed():
    """验证 plan_confirmed=False 时，路由到 __end__（Human-in-the-Loop 暂停）"""
    state = make_state_with_plan(confirmed=False)
    next_node = route_after_planning(state)
    assert next_node == "__end__"
```

#### TC-SM04：规划确认后进入执行
```python
def test_route_planning_to_execution_when_confirmed():
    """验证 plan_confirmed=True 时，路由到 execution 节点"""
    state = make_state_with_plan(confirmed=True)
    next_node = route_after_planning(state)
    assert next_node == "execution"
```

#### TC-SM05：MySQLCheckpointSaver 写入和读取
```python
@pytest.mark.asyncio
async def test_mysql_checkpoint_put_and_get(test_db_session):
    """验证 MySQLCheckpointSaver 能正确序列化/反序列化状态"""
    saver = MySQLCheckpointSaver(session=test_db_session)
    session_id = str(uuid4())
    original_state = make_test_agent_state(session_id=session_id)
    checkpoint = serialize_state(original_state)
    config = {"configurable": {"thread_id": session_id}}
    await saver.put(config, checkpoint, {}, {})
    loaded = await saver.get(config)
    loaded_state = deserialize_state(loaded)
    assert loaded_state["session_id"] == session_id
    assert loaded_state["plan_version"] == original_state["plan_version"]
```

#### TC-SM06：Checkpoint 持久化后会话可恢复
```python
@pytest.mark.asyncio
async def test_session_recovery_after_checkpoint(test_db_session, mock_perception_llm, mock_planning_llm):
    """验证执行到规划节点暂停后，会话从 MySQL 恢复时状态正确"""
    session_id = str(uuid4())
    state = make_initial_state("分析本月集装箱", session_id)
    # 模拟执行到 planning 节点暂停
    await run_until_planning_pause(state, session_id, test_db_session)
    # 从数据库恢复
    saver = MySQLCheckpointSaver(session=test_db_session)
    checkpoint = await saver.get({"configurable": {"thread_id": session_id}})
    restored_state = deserialize_state(checkpoint)
    assert restored_state["structured_intent"] is not None
    assert restored_state["plan_confirmed"] == False
    assert restored_state["analysis_plan"] is not None
```

#### TC-SM07：状态机不同 session 互不干扰
```python
@pytest.mark.asyncio
async def test_different_sessions_isolated(test_db_session):
    """验证两个并发会话的状态不相互污染"""
    session_a = str(uuid4())
    session_b = str(uuid4())
    state_a = make_test_agent_state(session_id=session_a, plan_version=1)
    state_b = make_test_agent_state(session_id=session_b, plan_version=3)
    saver = MySQLCheckpointSaver(session=test_db_session)
    await saver.put({"configurable": {"thread_id": session_a}}, serialize_state(state_a), {}, {})
    await saver.put({"configurable": {"thread_id": session_b}}, serialize_state(state_b), {}, {})
    loaded_a = deserialize_state(await saver.get({"configurable": {"thread_id": session_a}}))
    loaded_b = deserialize_state(await saver.get({"configurable": {"thread_id": session_b}}))
    assert loaded_a["plan_version"] == 1
    assert loaded_b["plan_version"] == 3
```

---

### 5.5 规划 API 端点测试（tests/integration/test_planning_api.py）

#### TC-API01：GET /api/sessions/{id}/plan 返回正确结构
```python
def test_get_plan_returns_correct_structure(client, session_with_plan):
    """验证 GET /plan 返回 plan_id、version、tasks、markdown_display"""
    sid = session_with_plan["session_id"]
    resp = client.get(f"/api/sessions/{sid}/plan")
    assert resp.status_code == 200
    data = resp.json()
    assert "plan_id" in data
    assert "version" in data
    assert "tasks" in data
    assert "markdown_display" in data
    assert len(data["tasks"]) >= 2
```

#### TC-API02：GET plan 不存在的 session 返回 404
```python
def test_get_plan_nonexistent_session_returns_404(client):
    resp = client.get("/api/sessions/nonexistent-id/plan")
    assert resp.status_code == 404
```

#### TC-API03：POST confirm 触发执行状态变更
```python
@pytest.mark.asyncio
async def test_confirm_plan_triggers_execution(client, session_with_plan):
    """验证 confirm 后 plan_confirmed=True，状态机进入 execution"""
    sid = session_with_plan["session_id"]
    resp = client.post(f"/api/sessions/{sid}/plan/confirm", json={"confirmed": True, "modifications": []})
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("plan_confirmed") == True
    # 会话状态应更新
    state_resp = client.get(f"/api/sessions/{sid}")
    assert state_resp.json().get("plan_confirmed") == True
```

#### TC-API04：POST confirm 带修改（删除任务）
```python
def test_confirm_with_task_removal(client, session_with_plan_3_tasks):
    """验证 confirm 带删除任务修改后，plan.tasks 减少"""
    sid = session_with_plan_3_tasks["session_id"]
    resp = client.post(f"/api/sessions/{sid}/plan/confirm", json={
        "confirmed": True,
        "modifications": [{"type": "remove_task", "task_id": "T002"}]
    })
    assert resp.status_code == 200
    data = resp.json()
    task_ids = [t["task_id"] for t in data["tasks"]]
    assert "T002" not in task_ids
    assert "T001" in task_ids
```

#### TC-API05：POST regenerate 带用户反馈
```python
@pytest.mark.asyncio
async def test_regenerate_with_feedback(client, session_with_plan, mock_planning_llm):
    """验证 regenerate 请求成功生成新版本规划"""
    sid = session_with_plan["session_id"]
    mock_planning_llm.return_value = make_plan_json(task_count=5)
    resp = client.post(f"/api/sessions/{sid}/plan/regenerate", json={"feedback": "增加同比分析"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["version"] == 2
    # revision_log 包含用户反馈
    assert any("增加同比分析" in str(log) for log in data.get("revision_log", []))
```

---

### 5.6 规划层历史模板集成测试（tests/integration/test_planning_with_templates.py）

#### TC-TPL01：有历史模板时注入到规划 Prompt
```python
@pytest.mark.asyncio
async def test_historical_template_injected_into_prompt(test_db_session, mock_planning_llm, captured_prompt):
    """验证 MySQL 中有匹配的历史模板时，其骨架被注入规划 Prompt"""
    user_id = str(uuid4())
    # 预置一个历史模板
    await test_db_session.execute(text("""
        INSERT INTO analysis_templates (template_id, user_id, name, domain, output_complexity, tags, plan_skeleton, usage_count, last_used)
        VALUES (:tid, :uid, '月度吞吐量模板', 'port_ops', 'simple_table', '["throughput","monthly"]', '{"tasks_count": 2}', 5, NOW())
    """), {"tid": str(uuid4()), "uid": user_id})
    intent = make_structured_intent("simple_table", user_id=user_id, domain="port_ops")
    await generate_plan(intent, db_session=test_db_session, ...)
    prompt = captured_prompt.get_last_prompt()
    assert "月度吞吐量模板" in prompt or "参考模板" in prompt
```

#### TC-TPL02：无精确匹配时使用模糊匹配（同 domain）
```python
@pytest.mark.asyncio
async def test_template_fallback_to_domain_match(test_db_session, mock_planning_llm, captured_prompt):
    """验证 domain+complexity 无精确匹配时，退而求 domain 级匹配"""
    user_id = str(uuid4())
    # 只有 chart_text 的模板，但本次是 simple_table
    await insert_template(test_db_session, user_id=user_id, domain="port_ops", complexity="chart_text")
    intent = make_structured_intent("simple_table", user_id=user_id, domain="port_ops")
    await generate_plan(intent, db_session=test_db_session, ...)
    prompt = captured_prompt.get_last_prompt()
    # domain 级匹配的模板也应被注入
    assert "参考模板" in prompt or "port_ops" in prompt
```

#### TC-TPL03：无任何模板时规划正常进行
```python
@pytest.mark.asyncio
async def test_planning_without_templates_proceeds_normally(test_db_session, mock_planning_llm):
    """验证用户无任何历史模板时，规划节点正常工作（不崩溃）"""
    user_id = str(uuid4())  # 新用户，无模板
    intent = make_structured_intent("chart_text", user_id=user_id)
    plan = await generate_plan(intent, db_session=test_db_session, ...)
    assert plan is not None
    assert len(plan.tasks) >= 3
```

---

## 6. 验收检查单

### 功能验收

| 检查项 | 期望结果 | 状态 |
|--------|----------|------|
| simple_table 场景 → 2–3 个任务 | Postman 验证任务数 | ⬜ |
| full_report 场景 → 5–8 个任务，含 report_structure | 任务清单完整 | ⬜ |
| 幻觉技能/端点被过滤，不触发崩溃 | 日志中有 WARNING，任务数减少 | ⬜ |
| LLM <think> 标签被剥离，JSON 解析成功 | 无 JSONDecodeError | ⬜ |
| 规划 Markdown 展示含任务列表和确认按钮 | 格式符合 PRD §7.3 | ⬜ |
| plan_confirmed=True 后 LangGraph 进入 execution | 状态机转移正确 | ⬜ |
| MySQLCheckpointSaver 写入/读取/跨会话隔离 | 测试 TC-SM05/SM06/SM07 通过 | ⬜ |
| GET/POST/PATCH 三个 API 端点正常 | Postman 全部 2xx | ⬜ |

### 测试覆盖验收

| 测试类型 | 要求 | 状态 |
|----------|------|------|
| 单元测试 | ≥ 15 个，全部通过 | ⬜ |
| 规划层代码覆盖率 | > 80% | ⬜ |
| 幻觉防御测试 | 技能/端点幻觉全覆盖 | ⬜ |
| 状态机路由测试 | 5 个关键路由条件全验证 | ⬜ |

### 性能验收

| 指标 | 要求 | 状态 |
|------|------|------|
| simple_table 规划生成时间 | < 5 秒 | ⬜ |
| full_report 规划生成时间 | < 20 秒 | ⬜ |
| Checkpoint 写入 MySQL 单次 | < 100ms | ⬜ |

---

## 补充测试：规划层 LLM 健壮性测试

> **补充说明：** 规划层是 LLM 输出质量最关键的环节——输出质量直接决定后续执行路径的正确性。以下测试覆盖：（1）规划节点超时与重试机制；（2）多样化业务输入下的规划合理性准确率；（3）对抗性输入防御。

---

### TC-PLAN-RETRY：规划节点 LLM 重试机制

> 文件：`tests/unit/test_planning_retry.py`

#### TC-PLAN-RETRY01：规划 LLM 首次超时后重试成功
```python
async def test_planning_retries_on_timeout():
    """
    规划节点 LLM 调用超时（60s），自动重试一次，第二次成功。
    验证：最终返回合法规划方案，call_count == 2。
    """
    call_count = 0
    valid_plan = {
        "plan_id": "P001", "version": 1,
        "tasks": [
            {"task_id": "T1", "type": "data_fetch", "skill": "skill_api_fetch",
             "endpoint": "getThroughputSummary", "depends_on": [], "params": {},
             "description": "获取月度吞吐量", "estimated_seconds": 5}
        ]
    }

    async def mock_planning_llm(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise asyncio.TimeoutError("Planning LLM timeout")
        return json.dumps(valid_plan)

    with patch("app.agent.planning.call_llm", side_effect=mock_planning_llm):
        node = PlanningNode()
        result = await node.run(state=make_test_state(
            intent={"time_range": "2024年", "output_format": "simple_table"}
        ))

    assert call_count == 2
    assert result.plan is not None
    assert len(result.plan.tasks) == 1
```

#### TC-PLAN-RETRY02：规划 LLM 连续两次失败后抛出 PlanningError
```python
async def test_planning_raises_after_max_retries():
    """
    规划节点 LLM 连续两次失败（超时/非法JSON），
    应抛出 PlanningError 而非静默返回空规划（空规划会导致执行层崩溃）。
    """
    async def always_fail(*args, **kwargs):
        raise asyncio.TimeoutError()

    with patch("app.agent.planning.call_llm", side_effect=always_fail):
        node = PlanningNode()
        with pytest.raises(PlanningError) as exc_info:
            await node.run(state=make_test_state(
                intent={"time_range": "2024年", "output_format": "simple_table"}
            ))

    assert "规划失败" in str(exc_info.value) or "timeout" in str(exc_info.value).lower()
```

#### TC-PLAN-RETRY03：规划失败后 LangGraph 路由到重规划路径
```python
async def test_planning_failure_routes_to_replan():
    """
    规划节点抛出 PlanningError 后，LangGraph 应路由到
    'replan' 边而非 'execute' 边，避免以空规划进入执行层。
    """
    with patch("app.agent.planning.PlanningNode.run",
               side_effect=PlanningError("LLM 不可用")):
        graph = build_analytica_graph()
        state = make_test_state(phase="planning")
        result_state = await graph.ainvoke(state)

    assert result_state["phase"] in ("perception", "planning"), \
        "规划失败后应回退到感知或重规划，不应进入执行"
    assert result_state.get("error_message") is not None
```

#### TC-PLAN-RETRY04：规划输出截断（JSON 不完整）后重试
```python
async def test_planning_truncated_json_retries():
    """
    LLM 输出被截断（常见于 max_tokens 不足时），JSON 不完整。
    验证：捕获 JSONDecodeError 后重试，第二次返回完整 JSON。
    """
    call_count = 0

    async def truncated_then_complete(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return '{"plan_id": "P001", "tasks": [{"task_id": "T1"'  # 截断
        return json.dumps(make_valid_simple_plan())

    with patch("app.agent.planning.call_llm", side_effect=truncated_then_complete):
        node = PlanningNode()
        result = await node.run(state=make_test_state(
            intent={"time_range": "2024年", "output_format": "simple_table"}
        ))

    assert call_count == 2
    assert result.plan is not None
```

---

### TC-PLAN-ACC：规划合理性准确率测试（真实 LLM 调用）

> 文件：`tests/accuracy/test_planning_accuracy.py`  
> 标记：`@pytest.mark.llm_real`  
> 目标：给定结构化意图，规划合理性（任务数合规 + 端点选取正确 + 无幻觉）≥ 90%

```python
# 规划准确率测试数据集：(意图描述, 验证规则)
PLANNING_ACCURACY_DATASET = [
    # ── 场景 A：单 API 简单查询 ─────────────────────────────────────
    (
        # §7 A1：板块分类吞吐量 → M02 getThroughputByBusinessType
        {"time_range": "2026-03", "domain": "production",
         "api_hint": "getThroughputByBusinessType", "output_format": "simple_table"},
        {
            "task_count_range": (2, 3),
            "required_endpoints": ["getThroughputByBusinessType"],
            "forbidden_endpoints": ["getMarketMonthlyThroughput"],
            "must_not_have_report_structure": True,
        }
    ),
    (
        # §7 A2：泊位占用率 → M05 getBerthOccupancyRate
        {"domain": "production", "analysis_type": "occupancy",
         "output_format": "chart_text"},
        {
            "task_count_range": (2, 4),
            "required_endpoints": ["getBerthOccupancyRate"],
        }
    ),
    (
        # §7 A5：集装箱TEU目标完成率 → M04 getContainerThroughput
        {"cargo_type": "集装箱", "time_range": "2026年",
         "analysis_type": "target_completion", "output_format": "simple_table"},
        {
            "task_count_range": (2, 3),
            "required_endpoints": ["getContainerThroughput"],
            "must_not_have_report_structure": True,
        }
    ),
    (
        # §7 A8：资产净值汇总 → M21 getAssetOverview
        {"domain": "asset", "analysis_type": "overview",
         "output_format": "simple_table"},
        {
            "task_count_range": (2, 3),
            "required_endpoints": ["getAssetOverview"],
        }
    ),
    (
        # §7 A10：资本类项目明细 → M27 getCapitalProjectList
        {"domain": "invest", "time_range": "2026年",
         "output_format": "simple_table"},
        {
            "task_count_range": (2, 3),
            "required_endpoints": ["getCapitalProjectList"],
        }
    ),
    # ── 场景 B：多 API 图文分析 ─────────────────────────────────────
    (
        # §7 B1：集装箱趋势+归因 → M03+M04+M14
        {"cargo_type": "集装箱", "time_range": "2026年Q1",
         "analysis_type": "trend_with_attribution", "output_format": "chart_text"},
        {
            "task_count_range": (3, 6),
            "required_endpoints_any": ["getThroughputTrendByMonth",
                                        "getContainerThroughput"],
            "required_endpoints_any_2": ["getKeyEnterpriseContribution"],
        }
    ),
    (
        # §7 B2：散杂货市场对比 → M02+M12+M13
        {"cargo_type": "散杂货", "time_range": "2026年",
         "analysis_type": "yoy_comparison", "output_format": "chart_text"},
        {
            "task_count_range": (3, 5),
            "required_endpoints_any": ["getThroughputByBusinessType",
                                        "getMarketTrendChart"],
            "required_endpoints_any_2": ["getMarketZoneThroughput"],
        }
    ),
    (
        # §7 B3：战略客户贡献+流失风险 → M17+M19+M20
        {"domain": "customer", "analysis_type": "contribution_risk",
         "output_format": "chart_text"},
        {
            "task_count_range": (3, 5),
            "required_endpoints_any": ["getStrategicCustomerThroughput",
                                        "getStrategicCustomerRevenue"],
            "required_endpoints_any_2": ["getCustomerCreditInfo",
                                          "getCustomerContributionRanking"],
        }
    ),
    (
        # §7 B4：设备资产+投资 → M23+M24+M25
        {"domain": "asset", "analysis_type": "equipment_health",
         "output_format": "chart_text"},
        {
            "task_count_range": (3, 5),
            "required_endpoints_any": ["getEquipmentFacilityStatus",
                                        "getAssetHistoricalTrend"],
            "required_endpoints_any_2": ["getInvestPlanSummary"],
        }
    ),
    (
        # §7 B7：投资进度节奏 → M26+M25
        {"domain": "invest", "analysis_type": "progress_deviation",
         "output_format": "chart_text"},
        {
            "task_count_range": (3, 4),
            "required_endpoints": ["getInvestPlanProgress"],
            "required_endpoints_any": ["getInvestPlanSummary"],
        }
    ),
    # ── 场景 C：复杂多域报告 ─────────────────────────────────────────
    (
        # §7 C2：月度经营月报（生产+市场+投资）→ M01+M04+M05+M06+M10+M13+M14+M26
        {"output_format": "full_report", "time_range": "2026-03",
         "report_dimensions": ["production", "market", "invest"]},
        {
            "task_count_range": (6, 10),
            "must_have_report_structure": True,
            "required_endpoints": ["getThroughputSummary",
                                   "getMarketMonthlyThroughput",
                                   "getInvestPlanProgress"],
            "all_endpoints_must_be_valid": True,
            "dag_must_be_acyclic": True,
        }
    ),
    (
        # §7 C1：年度货量预测报告 → M03+M11+M02+M13+M14+M17+M25+M27
        {"output_format": "full_report", "analysis_type": "forecast_2027",
         "time_range": "2024-2026年历史"},
        {
            "task_count_range": (7, 12),
            "must_have_report_structure": True,
            "required_endpoints_any": ["getThroughputTrendByMonth",
                                        "getMarketCumulativeThroughput"],
            "all_endpoints_must_be_valid": True,
        }
    ),
    # ── 路由歧义消除 ──────────────────────────────────────────────────
    (
        # 市场域"当月完成"应选 M10，而非生产域 M01
        {"domain": "market", "time_range": "2026-03",
         "analysis_type": "yoy_comparison", "output_format": "simple_table"},
        {
            "task_count_range": (2, 3),
            "required_endpoints": ["getMarketMonthlyThroughput"],
            "forbidden_endpoints": ["getThroughputSummary"],
        }
    ),
    (
        # "客户排名"应选 M19，而非战略客户 M17
        {"domain": "customer", "analysis_type": "contribution_ranking",
         "output_format": "simple_table"},
        {
            "task_count_range": (2, 3),
            "required_endpoints": ["getCustomerContributionRanking"],
            "forbidden_endpoints": ["getStrategicCustomerThroughput"],
        }
    ),
]

VALID_SKILL_IDS = {
    "skill_api_fetch", "skill_web_search", "skill_file_parse",
    "skill_descriptive_analysis", "skill_attribution_analysis",
    "skill_trend_analysis", "skill_proportion_analysis",
    "skill_comparison_analysis", "skill_anomaly_detection",
    "skill_forecast", "skill_narrative_generation",
    "skill_echarts_generation", "skill_table_generation",
    "skill_pptx_generation", "skill_html_generation",
}

# 基于 MockAPI 模拟建议文档 V1.0 的 27 个合法端点（M01-M27）
VALID_ENDPOINT_IDS = {
    # 生产运营域（M01-M09）
    "getThroughputSummary",            # M01
    "getThroughputByBusinessType",     # M02
    "getThroughputTrendByMonth",       # M03
    "getContainerThroughput",          # M04
    "getBerthOccupancyRate",           # M05
    "getVesselEfficiency",             # M06
    "getPortInventory",                # M07
    "getDailyProductionDynamic",       # M08
    "getShipStatus",                   # M09
    # 市场商务域（M10-M15）
    "getMarketMonthlyThroughput",      # M10
    "getMarketCumulativeThroughput",   # M11
    "getMarketTrendChart",             # M12
    "getMarketZoneThroughput",         # M13
    "getKeyEnterpriseContribution",    # M14
    "getMarketBusinessSegment",        # M15
    # 客户管理域（M16-M20）
    "getCustomerBasicInfo",            # M16
    "getStrategicCustomerThroughput",  # M17
    "getStrategicCustomerRevenue",     # M18
    "getCustomerContributionRanking",  # M19
    "getCustomerCreditInfo",           # M20
    # 资产管理域（M21-M24）
    "getAssetOverview",                # M21
    "getAssetDistributionByType",      # M22
    "getEquipmentFacilityStatus",      # M23
    "getAssetHistoricalTrend",         # M24
    # 投资管理域（M25-M27）
    "getInvestPlanSummary",            # M25
    "getInvestPlanProgress",           # M26
    "getCapitalProjectList",           # M27
}

def validate_plan(plan: dict, rules: dict) -> tuple[bool, str]:
    """根据规则验证规划方案，返回 (通过, 失败原因)"""
    tasks = plan.get("tasks", [])

    if "task_count_range" in rules:
        lo, hi = rules["task_count_range"]
        if not (lo <= len(tasks) <= hi):
            return False, f"任务数 {len(tasks)} 不在范围 [{lo},{hi}]"

    endpoints_used = {t.get("endpoint") for t in tasks if t.get("endpoint")}
    skills_used = {t.get("skill") for t in tasks}

    if "required_endpoints" in rules:
        for ep in rules["required_endpoints"]:
            if ep not in endpoints_used:
                return False, f"缺少必要端点 {ep}"

    if "required_endpoints_any" in rules:
        if not any(ep in endpoints_used for ep in rules["required_endpoints_any"]):
            return False, f"应使用以下端点之一: {rules['required_endpoints_any']}"

    if "forbidden_skills" in rules:
        for sk in rules["forbidden_skills"]:
            if sk in skills_used:
                return False, f"不应使用技能 {sk}"

    if rules.get("all_skills_must_be_registered"):
        invalid = skills_used - VALID_SKILL_IDS - {None}
        if invalid:
            return False, f"幻觉技能: {invalid}"

    if rules.get("all_endpoints_must_be_valid"):
        invalid = endpoints_used - VALID_ENDPOINT_IDS - {None}
        if invalid:
            return False, f"幻觉端点: {invalid}"

    if rules.get("dag_must_be_acyclic"):
        # 简单有向图环检测
        graph = {t["task_id"]: t.get("depends_on", []) for t in tasks}
        if _has_cycle(graph):
            return False, "任务依赖图存在环"

    if rules.get("all_dependencies_must_exist"):
        task_ids = {t["task_id"] for t in tasks}
        for t in tasks:
            for dep in t.get("depends_on", []):
                if dep not in task_ids:
                    return False, f"任务 {t['task_id']} 依赖不存在的 {dep}"

    if rules.get("must_have_report_structure"):
        if not plan.get("report_structure"):
            return False, "full_report 场景缺少 report_structure"

    if rules.get("must_not_have_report_structure"):
        if plan.get("report_structure"):
            return False, "simple_table 场景不应有 report_structure"

    return True, ""

def _has_cycle(graph: dict) -> bool:
    visited, rec_stack = set(), set()
    def dfs(node):
        visited.add(node)
        rec_stack.add(node)
        for neighbor in graph.get(node, []):
            if neighbor not in visited:
                if dfs(neighbor):
                    return True
            elif neighbor in rec_stack:
                return True
        rec_stack.discard(node)
        return False
    return any(dfs(n) for n in graph if n not in visited)


@pytest.mark.llm_real
@pytest.mark.parametrize("intent,rules", PLANNING_ACCURACY_DATASET)
async def test_planning_quality_per_scenario(intent, rules):
    """单场景规划合理性验证。"""
    node = PlanningNode()
    result = await node.run(state=make_test_state(intent=intent))
    plan_dict = result.plan.dict()
    passed, reason = validate_plan(plan_dict, rules)
    assert passed, f"规划验证失败：{reason}\n规划内容：{plan_dict}"


@pytest.mark.llm_real
async def test_planning_overall_accuracy():
    """
    数据集整体规划合理性 ≥ 90%。
    这是规划层的核心 KPI：LLM 在真实意图输入下生成的规划方案
    应在大多数场景中满足技能选取正确、端点匹配、无幻觉三项要求。
    """
    node = PlanningNode()
    results = []

    for intent, rules in PLANNING_ACCURACY_DATASET:
        try:
            result = await node.run(state=make_test_state(intent=intent))
            passed, reason = validate_plan(result.plan.dict(), rules)
            results.append((passed, intent, reason))
        except Exception as e:
            results.append((False, intent, str(e)))

    passed_count = sum(1 for r in results if r[0])
    accuracy = passed_count / len(results)

    failed = [(r[1], r[2]) for r in results if not r[0]]
    print(f"\n规划合理性整体准确率: {accuracy:.1%}")
    if failed:
        print("失败场景:")
        for intent, reason in failed:
            print(f"  [{reason}] {intent.get('output_format')} / {intent.get('time_range')}")

    assert accuracy >= 0.90, (
        f"规划合理性 {accuracy:.1%} < 90%，需优化规划 Prompt 或端点选取规则"
    )
```

---

### TC-PLAN-ADV：规划层对抗性输入测试

> 文件：`tests/unit/test_planning_adversarial.py`

#### TC-PLAN-ADV01：LLM 返回超量任务被截断至上限
```python
async def test_planning_caps_task_count_at_maximum():
    """
    LLM 生成 15 个任务（超出 full_report 上限 8 个）。
    规划层应截断至 8 个，并记录警告日志。
    """
    bloated_plan = {"plan_id": "P001", "version": 1, "tasks": [
        {"task_id": f"T{i}", "type": "data_fetch", "skill": "skill_api_fetch",
         "endpoint": "getThroughputSummary", "depends_on": [],
         "params": {}, "description": f"任务{i}", "estimated_seconds": 5}
        for i in range(1, 16)  # 15个任务
    ]}
    with patch("app.agent.planning.call_llm", return_value=json.dumps(bloated_plan)):
        node = PlanningNode()
        result = await node.run(state=make_test_state(
            intent={"output_format": "full_report", "time_range": "2024年"}
        ))
    assert len(result.plan.tasks) <= 8, "超量任务应被截断至最大值 8"
```

#### TC-PLAN-ADV02：LLM 生成循环依赖时被检测并修正
```python
async def test_planning_detects_and_fixes_circular_dependency():
    """
    LLM 生成 T1 依赖 T2，T2 依赖 T1（循环依赖）。
    规划层应检测循环并打破（移除其中一条依赖边），不应将循环图传入执行层。
    """
    circular_plan = {"plan_id": "P001", "version": 1, "tasks": [
        {"task_id": "T1", "type": "data_fetch", "skill": "skill_api_fetch",
         "endpoint": "getThroughputSummary", "depends_on": ["T2"],
         "params": {}, "description": "T1", "estimated_seconds": 5},
        {"task_id": "T2", "type": "analysis", "skill": "skill_descriptive_analysis",
         "depends_on": ["T1"],
         "params": {}, "description": "T2", "estimated_seconds": 10},
    ]}
    with patch("app.agent.planning.call_llm", return_value=json.dumps(circular_plan)):
        node = PlanningNode()
        result = await node.run(state=make_test_state(
            intent={"output_format": "simple_table", "time_range": "2024年"}
        ))
    # 修复后的图不应有环
    graph = {t.task_id: t.depends_on for t in result.plan.tasks}
    assert not _has_cycle(graph), "修复后的规划不应含循环依赖"
```

#### TC-PLAN-ADV03：LLM 忘记 <think> 剥离后仍生成混合内容
```python
async def test_planning_handles_mixed_think_and_json():
    """
    LLM 输出夹杂多个 <think> 块和正文 JSON。
    验证：即使有多个推理块，最终能正确解析规划 JSON。
    """
    mixed_output = (
        "<think>首先我需要理解用户意图...</think>\n"
        "好的，我来制定分析方案：\n"
        "<think>需要选择合适的端点...</think>\n"
        + json.dumps(make_valid_simple_plan())
    )
    with patch("app.agent.planning.call_llm", return_value=mixed_output):
        node = PlanningNode()
        result = await node.run(state=make_test_state(
            intent={"output_format": "simple_table", "time_range": "2024年"}
        ))
    assert result.plan is not None
    assert len(result.plan.tasks) >= 1
```

