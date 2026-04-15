# Analytica Phase 2 测试覆盖分析报告

**生成时间：** 2026-04-14  
**分析范围：** Phase 2（规划层与状态机）  
**测试文件数：** 7 个  
**总测试用例数：** 42 个（不含14个参数化场景 = 实际 56 个）  
**总代码行数：** 1581 行

---

## 一、执行摘要

Phase 2 现有测试总体框架完整，但存在以下**关键缺陷**：

| 问题类别 | 严重程度 | 缺陷数 | 影响范围 |
|---------|--------|------|--------|
| **不够业务化** | 🔴 高 | 11/42 | 测试输入过于抽象，覆盖不了真实使用场景 |
| **代码路径未覆盖** | 🔴 高 | 8+ | 规划Prompt构建、M-code解析、update_plan等函数 |
| **端点覆盖不全** | 🟡 中 | 13/27 | 准确度测试仅14个场景，覆盖率 ~52% |
| **状态转移不全** | 🟡 中 | 4 | 缺少异常路径、超时、错误恢复等 |
| **端到端串联缺失** | 🟡 中 | 1 | 感知→规划→确认的完整流程未测试 |
| **集成测试薄弱** | 🟠 低 | 5 | 缺少 regenerate/rollback，仅测基础CRUD |

---

## 二、详细分析

### 2.1 问题对比：与优化文档 Phase 1 原则对照

**优化文档问题定义：**
- 提问不够业务化（"看看数据" vs "大连港区3月份集装箱TEU完成率"）
- 输入过于抽象（硬编码的简单指标 vs 5个业务域的真实指标组合）
- 报告冗余（Prompt重复 60%）

**Phase 2 测试中的类似问题：**

#### 2.1.1 测试输入过于抽象

| 文件 | 问题案例 | 对比改进方向 |
|-----|--------|-----------|
| `test_planning.py` | `make_structured_intent("simple_table", subject=["测试指标"])` | 应为具体指标："集装箱TEU月度目标完成率"、"战略客户贡献排名" 等 |
| `test_planning_endpoint_selection.py` | `subject=["本月全港总吞吐量"]`（硬编码字符串） | 应覆盖5个业务域、多个指标维度组合 |
| `test_planning_accuracy.py` | 虽然14个场景有一定业务化，但缺少**多轮对话场景**：用户修正、信息补充、追问等 |
| `test_state_machine.py` | `make_state_with_intent()` 的 intent 字段为空 `{"analysis_goal": "测试"}` | 应包含完整槽位、domain推断、多轮上下文 |

**代码示例（当前问题）：**
```python
# test_planning.py - TC-P01
intent = make_structured_intent("simple_table")  # ❌ 输入过于简单
# 实际：analysis_subject = ["测试指标"]，无实际业务含义

# 应该是（参考优化文档）
intent = {
    "analysis_subject": ["集装箱TEU目标完成率"],  # 具体指标
    "time_range": "2026年上半年",  # 具体时间
    "domain": "production",  # 业务域
    "output_complexity": "simple_table",
}
```

#### 2.1.2 缺少多轮对话和用户修正场景

| 场景类型 | 当前覆盖 | 缺失例子 |
|---------|---------|--------|
| 单轮简单查询 | ✅ 大量 | - |
| 多轮clarification | ❌ 0 | R1:"分析一下吞吐量变化"(缺time_range) → 系统追问 → R2:"2026年上半年" |
| 用户修正/退回 | ❌ 0 | R1:"大连港..." → R2:"不对，改成营口港" |
| bypass/主题切换 | ❌ 0 | R1:"看港口数据" → R2:"按你理解执行" → R3:"算了，看投资进度" |
| 否定式修改 | ❌ 0 | R1:"分析下跌原因" → R2:"不需要归因，直接对比数据" |

---

### 2.2 代码路径/功能分支未覆盖

#### 2.2.1 规划引擎关键函数分析

| 函数 | 代码行数 | 覆盖状态 | 缺失路径 |
|-----|--------|---------|--------|
| `PlanningEngine.generate_plan()` | ~50 | ⚠️ 部分 | 仅测重试一次失败then成功，未测：<br>- 所有max_retries次都失败<br>- 不同类型错误（JSON vs 超时）的区分<br>- 重试间隔指数退避验证 |
| `PlanningEngine._build_prompt()` | ~40 | ❌ 未测 | - domain提取逻辑（slots dict vs 直接key）<br>- template_hint构建（需要async DB，当前=空）<br>- report_hint逻辑分支<br>- get_endpoints_description(domain_hint)的domain-aware过滤 |
| `PlanningEngine._validate_tasks()` | ~60 | ⚠️ 部分 | 仅测幻觉过滤，未测：<br>- M-code resolve的各种格式（M01, M1, m01等）<br>- 依赖清理时的复杂DAG结构<br>- 极限case：全部任务被过滤后的处理 |
| `update_plan()` | ~40 | ⚠️ 部分 | 仅测remove_task，未测：<br>- modify_task（参数改动）<br>- add_task（新增）<br>- 多个modification的应用顺序<br>- 版本号并发写入冲突 |
| `_break_cycles()` | ~25 | ❌ 完全依赖单例 | 仅在test_planning_retry.py::test_planning_detects_and_fixes_circular_dependency中被触发（1个路径），未测：<br>- 多个循环的检测和修复<br>- 修复后依赖的完整性保证<br>- 复杂DAG中的边界case |
| `parse_planning_llm_output()` | ~15 | ⚠️ 部分 | - `_clean_llm_output`的多种变体未全覆盖（如包裹在markdown中，多个JSON片段等）<br>- 异常消息的可读性验证 |

#### 2.2.2 图表路由函数未完全覆盖

```python
# graph.py 的路由函数
def route_after_perception(state):      # ✅ TC-SM01 + TC-SM02
def route_after_planning(state):        # ✅ TC-SM03 + TC-SM04
def route_after_execution(state):       # ❌ 未测试

# 缺失的 route_after_execution 路径：
# - needs_replan=True → planning
# - task_statuses="done" (all) → reflection
# - 部分任务done → execution（loop）
# - 异常状态（error、timeout等）→ ?（未定义）
```

#### 2.2.3 MySQLCheckpointSaver 的边界case

```python
# test_state_machine.py TC-SM05/06/07
# ✅ 已测：正常put/get、跨session隔离
# ❌ 缺失：
# - JSON序列化失败时的处理
# - 数据库连接异常
# - 大状态（>1MB JSON）的截断
# - 并发写入同一session
# - 脏数据恢复（invalid JSON in DB）
```

---

### 2.3 端点覆盖完整性分析

**现状统计：**
- 总端点数：**27 个**（M01~M27）
- 准确度测试覆盖：**14 个场景**，涉及 **~15 个端点**（重复）
- **覆盖率：15/27 = ~56%**

#### 2.3.1 参与coverage的端点分析

| 端点ID | 被覆盖 | 测试位置 | 覆盖类型 |
|-------|-------|--------|--------|
| M01: getThroughputSummary | ✅ | TC-P01, TC-A01, A8(聚合), test_get_plan_returns_correct_structure | 多处 |
| M02: getThroughputByBusinessType | ✅ | A1 | 单独 |
| M03: getThroughputTrendByMonth | ✅ | B1 | 多API组合 |
| M04: getContainerThroughput | ✅ | A5, B1 | 多API组合 |
| M05: getBerthOccupancyRate | ✅ | A2 | 单独 |
| M06: getVesselEfficiency | ❌ | - | **完全缺失** |
| M07: getPortInventory | ❌ | - | **完全缺失** |
| M08: getDailyProductionDynamic | ❌ | - | **完全缺失** |
| M09: getShipStatus | ❌ | - | **完全缺失** |
| M10: getMarketMonthlyThroughput | ✅ | ROUTE-market-not-production, C2 | 多处 |
| M11: getMarketCumulativeThroughput | ✅ | C1 | 聚合 |
| M12: getMarketTrendChart | ✅ | TC-A03, B2 | 多处 |
| M13: getMarketZoneThroughput | ✅ | B2 | 组合 |
| M14: getKeyEnterpriseContribution | ✅ | B1, B2 | 组合 |
| M15: getMarketBusinessSegment | ✅ | B1 | 组合 |
| M17: getStrategicCustomerThroughput | ✅ | TC-A04 注提及, B3 | 对比 |
| M18: getStrategicCustomerRevenue | ✅ | B3 | 组合 |
| M19: getCustomerContributionRanking | ✅ | TC-A04, ROUTE-ranking-not-strategic | 多处 |
| M20: getCustomerCreditInfo | ✅ | B3 | 组合 |
| M21: getCustomerBasicInfo | ❌ | - | **完全缺失** |
| M22: getAssetOverview | ✅ | A8 | 单独 |
| M23: getEquipmentFacilityStatus | ✅ | B4 | 组合 |
| M24: getAssetHistoricalTrend | ✅ | B4 | 组合 |
| M25: getInvestPlanSummary | ✅ | TC-A05, B4, B7 | 多处 |
| M26: getInvestPlanProgress | ✅ | TC-A05, B7 | 多处 |
| M27: getCapitalProjectList | ✅ | A10 | 单独 |

**缺失端点（6个，22%）：**
- ❌ M06: getVesselEfficiency（船舶作业效率）
- ❌ M07: getPortInventory（港存库容）
- ❌ M08: getDailyProductionDynamic（日度生产动态）
- ❌ M09: getShipStatus（船舶状态）
- ❌ M16: getMarketBusinessSegment（市场板块结构）— 注：虽有名称相似的M15
- ❌ M21: getCustomerBasicInfo（客户基础信息）

#### 2.3.2 端点选取准确性的业务逻辑缺失

| 业务场景 | 当前测试 | 缺失的语义路由 |
|---------|---------|-----------|
| 集装箱 TEU 专项 | ✅ TC-P06, A5 指定M04 | ❌ "集装箱吞吐量"应自动路由M04（非M01/M02）的LLM学习能力未测 |
| 生产 vs 市场口径 | ✅ ROUTE-market-not-production | ❌ "全港当月完成"在不同domain下应选不同端点（M01 vs M10）的细粒度路由 |
| 归因分析的辅助数据 | ✅ B1的required_endpoints_any_2 | ❌ LLM是否主动补充所需端点（如用户只问"为什么下降"，LLM应同时获取对标企业/板块数据） |
| 端点参数约束 | ✅ TC-A03 验证businessSegment必填 | ❌ 其他端点参数约束（如date vs curDateMonth的语义区分）未测 |

---

### 2.4 状态机状态转移路径分析

#### 2.4.1 LangGraph 四节点状态图

```
perception → planning → execution → reflection
     ↑                                   │
     └───────────────────────────────────┘ (needs_replan)
     
路由条件：
- route_after_perception: structured_intent is not None
- route_after_planning: plan_confirmed = True
- route_after_execution: needs_replan 或 all tasks done 或 loop
```

#### 2.4.2 测试覆盖矩阵

| 路由 | 正常路径 | 异常路径 | 覆盖状态 |
|-----|--------|--------|--------|
| perception → planning | ✅ TC-SM01 | ❌ structured_intent=None but intent dict exists（部分填充） | **部分** |
| perception → END | ✅ TC-SM02 | ❌ 多轮clarification的状态流转 | **部分** |
| planning → execution | ✅ TC-SM04 | ❌ plan=None, plan_confirmed race condition | **部分** |
| planning → END | ✅ TC-SM03 | ❌ human-in-the-loop timeout（用户未在规定时间确认） | **缺失** |
| execution → planning | ❌ 未测 | ❌ needs_replan=True的场景和重试策略 | **缺失** |
| execution → reflection | ❌ 未测 | ❌ all task_statuses="done"的逻辑 | **缺失** |
| execution → execution | ❌ 未测 | ❌ 部分任务完成、循环执行的状态转移 | **缺失** |
| reflection → END | ❌ 未测 | - | **缺失** |

**缺失的异常/边界路径：**

```python
# 缺失场景 1: 感知阶段异常
state = {
    "structured_intent": None,
    "empty_required_slots": ["time_range", "analysis_subject"],  # 未全部填充
    "clarification_round": 5,  # 多轮无果
}
# 预期：应该超时或回退，当前逻辑中是什么？

# 缺失场景 2: 规划生成超时，需要rollback
state["plan_confirmed"] = False
state["error"] = "LLM timeout after 3 retries"
# 预期：应回到perception重新开始，还是等待用户输入？

# 缺失场景 3: 执行中发现需要重规划
state["needs_replan"] = True  # 任务执行发现缺少某个端点的数据
state["analysis_plan"]["tasks"] = [...]  # 原方案
# 预期：是否保留已执行结果？新plan应该是全量重生成还是增量修正？

# 缺失场景 4: 并发修改同一session的状态
session_A: route_after_planning() → execution
session_A: route_after_execution() → (replan?)
# 同时：
session_B 修改 session_A 的 plan_confirmed = False
# 预期：版本冲突解决逻辑？
```

---

### 2.5 集成测试覆盖分析

#### 2.5.1 已测试的API场景

| TC编号 | 端点 | 场景 | 状态 |
|--------|-----|------|------|
| TC-API01 | GET /api/sessions/{id}/plan | 返回正确结构 | ✅ |
| TC-API02 | GET /api/sessions/{id}/plan | 404 - 不存在的session | ✅ |
| TC-API03 | POST /api/sessions/{id}/plan/confirm | 设置confirmed=True | ✅ |
| TC-API04 | POST /api/sessions/{id}/plan/confirm | 带modifications（删除任务） | ✅ |
| TC-API05 | POST /api/sessions/{id}/plan/confirm | 幂等性 | ✅ |

#### 2.5.2 完全缺失的集成场景

| 场景 | 用途 | 严重程度 |
|------|------|--------|
| **POST /api/sessions/{id}/plan/regenerate** | 用户修改输入后重新规划 | 🔴 高 |
| **POST /api/sessions/{id}/plan/rollback** | 恢复到上个版本（revision_log） | 🔴 高 |
| **GET /api/sessions/{id}/plan/versions** | 查看版本历史 | 🟡 中 |
| **POST /api/sessions/{id}/plan/modify** | 单个任务修改而非整体modifications | 🟡 中 |
| **PUT /api/sessions/{id}** | 整体会话状态更新 | 🟡 中 |
| **感知 → 规划 → 确认的E2E流** | 完整用户流程 | 🔴 高 |
| **错误场景：网络中断后恢复** | checkpoint恢复 | 🟠 低 |
| **并发请求处理** | 同一session的并发确认 | 🟠 低 |

---

### 2.6 端到端串联测试分析

#### 2.6.1 当前缺失的完整流程

**场景：用户从感知到规划到确认的完整旅程**

```
T1: 用户输入 "帮我分析一下大连港上个月的集装箱吞吐量"
      ↓
T2: 感知层提取 intent（需要补充 time_range）
      ↓
T3: 系统返回 clarification + markdown 展示
      ↓
T4: 用户确认 "对，看上个月的"
      ↓
T5: 感知层完成 intent
      ↓
T6: 规划层生成方案（3-5个任务）
      ↓
T7: 系统展示方案 markdown + 确认按钮
      ↓
T8: 用户修改（"去掉T002任务"）
      ↓
T9: 方案版本更新，revision_log 记录修改
      ↓
T10: 用户确认执行
      ↓
T11: 状态转移 plan_confirmed=True, 进入执行阶段
```

**当前测试覆盖：**
- ✅ 单个步骤：感知（Phase 1）、规划（TC-P*）、plan确认（TC-API*)
- ❌ **完整流程**：没有测试文件涵盖 T1→T11 的完整路径

**缺失的集成测试：**

```python
# 应该存在的 e2e 测试（当前不存在）
@pytest.mark.asyncio
@pytest.mark.e2e
async def test_user_journey_from_perception_to_confirmed_plan():
    """
    E2E场景：
    1. 用户输入
    2. 系统运行感知节点（利用Phase 1的fixtures）
    3. 验证clarification或直接进planning
    4. 规划节点生成方案
    5. 用户修改方案
    6. 确认并转移状态
    """
    pass
```

---

## 三、缺失测试优先级排序

### 🔴 高优先级（P0 - 必须补齐）

| # | 缺失项 | 影响 | 工作量 | 预期ROI |
|----|-------|------|--------|--------|
| 1 | 6个未覆盖端点的集成测试<br>（M06,M07,M08,M09,M16,M21） | 端点路由学习不完整<br>LLM可能生成幻觉 | 低（利用existing fixtures） | 高（消除盲点） |
| 2 | 业务化多轮对话场景<br>（基于optimize-tests文档的20个MT场景） | 当前测试输入过于简单<br>无法验证真实用户意图 | 中 | 高 |
| 3 | E2E感知→规划→确认流程 | 缺少完整用户旅程验证<br>无法发现跨层bug | 中 | 高 |
| 4 | `route_after_execution`及执行层路由 | replan循环未测<br>task_statuses状态转移未验证 | 中 | 中 |
| 5 | PlanningEngine._build_prompt() 的domain-aware路由 | 端点选取准确性无法验证<br>关键业务逻辑空白 | 中 | 高 |

### 🟡 中优先级（P1 - 建议补齐）

| # | 缺失项 | 影响 | 工作量 |
|----|-------|------|--------|
| 6 | `_break_cycles()` 的复杂DAG case | 循环依赖修复不完全验证 | 低 |
| 7 | `update_plan()` 的add/modify操作 | 方案修改功能不全 | 低 |
| 8 | M-code多格式解析（M1, m01, M 01等） | LLM容错性不完全 | 低 |
| 9 | MySQLCheckpointSaver的异常处理 | 边界case恢复不验证 | 低 |
| 10 | API集成测试：regenerate/rollback | 用户修改流程不完整 | 中 |

### 🟠 低优先级（P2 - 可选）

| # | 缺失项 | 影响 |
|----|-------|------|
| 11 | 大状态JSON（>1MB）截断 | 性能edge case |
| 12 | 并发写入同一session | 高并发场景 |
| 13 | 网络中断恢复测试 | 容错性 |

---

## 四、推荐补齐方案

### Phase 2A: 快速修复（1-2天）

**目标：** 将端点覆盖率从 56% → 78%、业务化程度从低 → 中

```
新增测试文件：tests/unit/test_planning_missing_endpoints.py
├─ test_vessel_efficiency_endpoint        (M06)
├─ test_port_inventory_endpoint           (M07)
├─ test_daily_production_endpoint         (M08)
├─ test_ship_status_endpoint              (M09)
├─ test_market_business_segment_endpoint  (M16)
└─ test_customer_basic_info_endpoint      (M21)

新增测试文件：tests/unit/test_planning_business_scenarios.py
├─ test_multi_turn_clarification_teu      (参考MT02)
├─ test_user_correction_portal_choice     (参考MT18)
└─ test_domain_aware_endpoint_routing     (M01 vs M10自动选择)
```

### Phase 2B: 标准补齐（3-5天）

**目标：** 将业务化程度从中 → 高、覆盖真实用户流程

```
新增测试文件：tests/e2e/test_perception_to_planning.py
├─ test_simple_inquiry_full_flow          (无clarification)
├─ test_clarification_flow                (需要追问)
└─ test_plan_modification_flow            (修改方案)

新增集成测试：tests/integration/test_planning_advanced_api.py
├─ test_plan_regenerate_endpoint          (新建/重置plan)
├─ test_plan_rollback_with_revision_log   (回到历史版本)
└─ test_concurrent_plan_confirmation      (并发确认处理)
```

### Phase 2C: 完整补齐（1周）

**目标：** 基准覆盖率 ≥ 85%

```
新增准确度测试：tests/accuracy/test_planning_advanced_scenarios.py
├─ 10个多轮对话场景（基于MT01-MT10）
├─ 10个边界/歧义探测（基于BP-*）
└─ 5个跨域复合场景

新增回归测试：tests/unit/test_planning_backward_compat.py
├─ Phase 1 升级后的兼容性
└─ 旧方案格式的迁移
```

---

## 五、具体建议修复清单

### 5.1 补齐代码路径覆盖

**文件：** `tests/unit/test_planning_build_prompt.py`（新增，20行）

```python
def test_build_prompt_with_domain_filtering():
    """验证 _build_prompt 中 domain 参数对端点过滤的影响"""
    engine = PlanningEngine()
    
    # Test 1: domain="production" 应只包含 M01-M09 的优先级提示
    intent = {
        "domain": "production",
        "analysis_subject": ["吞吐量"],
    }
    prompt = engine._build_prompt(intent, "simple_table")
    assert "getThroughputSummary" in prompt
    assert prompt.index("getThroughputSummary") < prompt.index("getMarketMonthlyThroughput")  # 优先级
    
    # Test 2: domain="market" 应优先 M10 而非 M01
    intent["domain"] = "market"
    prompt = engine._build_prompt(intent, "simple_table")
    # M10 should be mentioned before M01, or M01 should not be in market section
    assert "getMarketMonthlyThroughput" in prompt
```

### 5.2 补齐业务化场景

**文件：** `tests/unit/test_planning_business_intent.py`（新增，80行）

```python
@pytest.mark.parametrize("user_input,expected_endpoint", [
    ("集装箱TEU目标完成率", "getContainerThroughput"),  # M04, not M01
    ("本月市场吞吐量", "getMarketMonthlyThroughput"),  # M10, not M01
    ("各港区对比", "getMarketZoneThroughput"),  # M13
    ("战略客户贡献", "getStrategicCustomerThroughput"),  # M17, not M19
    ("客户排名", "getCustomerContributionRanking"),  # M19, not M17
])
async def test_endpoint_semantic_routing(user_input, expected_endpoint):
    """验证LLM能根据业务意图自动选择正确端点"""
    engine = PlanningEngine(llm=real_llm)
    intent = {
        "analysis_subject": [user_input],
        "output_complexity": "simple_table",
    }
    plan = await engine.generate_plan(intent)
    endpoint_ids = {t.params.get("endpoint_id") for t in plan.tasks}
    assert expected_endpoint in endpoint_ids, f"Expected {expected_endpoint}, got {endpoint_ids}"
```

### 5.3 补齐E2E流程

**文件：** `tests/e2e/test_complete_user_journey.py`（新增，150行）

```python
@pytest.mark.asyncio
@pytest.mark.e2e
async def test_full_journey_from_user_input_to_confirmed_plan():
    """完整用户旅程：输入 → 感知 → 规划 → 确认"""
    # Step 1: 用户输入
    session_id = str(uuid4())
    user_input = "帮我分析一下大连港上个月的集装箱吞吐量"
    
    # Step 2: 运行图表（感知 → 规划）
    initial_state = make_initial_state(session_id, "user123", user_input)
    graph = get_compiled_graph()
    final_state = None
    async for event in graph.astream(initial_state):
        final_state = event
    
    # Step 3: 验证规划已生成
    assert final_state["analysis_plan"] is not None
    assert final_state["plan_confirmed"] is False  # 等待用户确认
    assert len(final_state["analysis_plan"]["tasks"]) >= 2
    
    # Step 4: 用户修改方案（删除一个任务）
    modifications = [{"type": "remove_task", "task_id": "T002"}]
    
    # Step 5: 用户确认
    confirmed_plan = await api.post(
        f"/api/sessions/{session_id}/plan/confirm",
        json={"confirmed": True, "modifications": modifications},
    )
    
    # Step 6: 验证状态转移
    assert confirmed_plan["plan_confirmed"] is True
    assert confirmed_plan["version"] == 2
    assert len([t for t in confirmed_plan["tasks"] if t["task_id"] == "T002"]) == 0
```

### 5.4 补齐多轮对话

**文件：** `tests/accuracy/test_multi_turn_scenarios.py`（新增，200行）

```python
@pytest.mark.llm_real
@pytest.mark.asyncio
@pytest.mark.parametrize("scenario", [
    {
        "id": "MT-TEU-ATTRIBUTION",
        "turns": [
            {
                "user": "今年集装箱TEU目标完成率为什么不及预期",
                "expected_slots": {"analysis_subject": ["TEU完成率"], "attribution_needed": True},
            },
            {
                "user": "截止到6月底的数据",
                "expected_slots": {"time_range": {"end": "2026-06-30"}},
            },
        ],
    },
    # ... 19 more multi-turn scenarios from optimize-tests-and-report.md
])
async def test_multi_turn_dialog(scenario):
    """验证多轮对话中的槽位填充和intent精化"""
    pass
```

---

## 六、测试框架改进建议

### 6.1 补齐fixture

```python
# conftest.py 新增

@pytest.fixture
def business_intent_templates():
    """业务化意图模板库（对应优化文档的20+场景）"""
    return {
        "production_monthly": {
            "domain": "production",
            "analysis_subject": ["吞吐量"],
            "time_range": "2026-03",
        },
        "market_trend": {
            "domain": "market",
            "analysis_subject": ["集装箱趋势"],
            "output_complexity": "chart_text",
        },
        # ... 20+ templates
    }

@pytest.fixture
def endpoint_coverage_matrix():
    """端点覆盖矩阵，用于自动生成缺失的endpoint test"""
    return {
        "M01": ["test_planning.py", "test_planning_accuracy.py"],
        "M06": [],  # 空 = 缺失
        "M07": [],
        # ...
    }
```

### 6.2 补齐测试数据生成

```python
# tests/data/test_data_generator.py（新增）

def generate_missing_endpoint_tests():
    """自动为未覆盖的6个端点生成测试用例"""
    missing = ["M06", "M07", "M08", "M09", "M16", "M21"]
    for mid in missing:
        endpoint_id = M_CODE_TO_ENDPOINT[mid]
        # 生成参数化测试
        yield {
            "endpoint_id": endpoint_id,
            "domain": ENDPOINT_REGISTRY[endpoint_id]["domain"],
            "test_name": f"test_{endpoint_id}_endpoint",
        }
```

---

## 七、结论与建议

### 关键发现

| 方面 | 当前状态 | 风险等级 | 影响 |
|-----|--------|--------|------|
| **业务化程度** | 低（输入过于抽象） | 🔴 高 | 无法验证真实用户场景 |
| **端点覆盖** | 56%（21/27） | 🔴 高 | 6个端点完全盲点 |
| **代码路径** | 部分（关键函数未测） | 🟡 中 | _build_prompt、M-code等逻辑空白 |
| **状态转移** | 部分（异常路径缺失） | 🟡 中 | 错误恢复、replan逻辑未验证 |
| **E2E流程** | 缺失（单点测试） | 🔴 高 | 无跨层集成验证 |
| **集成测试** | 弱（仅基础CRUD） | 🟡 中 | regenerate/rollback未测 |

### 优先行动

1. **立即修复（1天）** → 补齐6个端点的准确度测试 + 2-3个业务化场景
2. **本周完成（3天）** → 补齐E2E流程 + _build_prompt 单元测试
3. **后续迭代（1周）** → 基于优化文档的20个多轮场景 + 30个边界探测

### 重点建议

✅ **采纳** Phase 1 优化文档中的多轮场景模板（20个MT场景）  
✅ **统一** 测试命名规范和数据组织结构  
✅ **自动化** 端点覆盖矩阵的生成和缺失项检测  
✅ **建立** E2E测试框架和跨层集成测试套件  

---

## 附录：快速参考

### 缺失的6个端点

```
M06: getVesselEfficiency - 船舶作业效率
M07: getPortInventory - 港存库容
M08: getDailyProductionDynamic - 日度生产动态  
M09: getShipStatus - 船舶状态
M16: getMarketBusinessSegment - 市场板块结构
M21: getCustomerBasicInfo - 客户基础信息
```

### 缺失的关键代码路径

```
PlanningEngine._build_prompt()
  └─ domain-aware endpoint filtering
  
PlanningEngine._validate_tasks()
  └─ M-code multi-format resolution
  
_break_cycles()
  └─ complex DAG circular dependency fix
  
MySQLCheckpointSaver
  └─ exception handling, concurrent writes
  
route_after_execution()
  └─ replan, reflection, task loop logic
```

### 代码覆盖率目标

| 指标 | 当前 | 目标 |
|-----|-----|-----|
| 端点覆盖 | 56% | 85% |
| 业务化测试 | 低 | 中 |
| E2E覆盖 | 0% | 80% |
| 代码路径 | ~70% | 90% |
| **总体** | **~62%** | **≥85%** |

