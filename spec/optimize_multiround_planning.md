# Multi-Round Planning 骨架生成质量优化 — 方案设计

**目标读者**：Claude Code 执行实例（无本会话上下文）
**作者**：2026-05-01 实测诊断沉淀
**状态**：📋 待评审
**前置问题**：资产设备专家 "生成2026年Q1设备运营效能深度报告" 在 multi-round 路径中因 section LLM 缺必填参数导致 16/24 任务被 drop，fallback 到 single-round

---

## 0. Mission

提升 `_call_section_llm` 生成任务时必填参数的填写准确率，降低 multi-round → single-round fallback 的概率，从而保留 multi-round 的分而治之优势（并行章节填充 + 确定性 stitch），减少单轮 prompt 的上下文膨胀压力。

核心路径：`_call_skeleton_llm` → `_enrich_section_endpoints` → `_call_section_llm × N` → `_stitch_plan` → `_validate_tasks`

**不改动**：
- Round 1 skeleton 生成逻辑（维持当前"只看 domain_index，不生成任务"的范围）
- `_stitch_plan` 确定性合并逻辑
- `_validate_tasks` 验证规则

---

## 1. 问题诊断回顾

### 1.1 故障链路

```
Round 2 section LLM 收到端点详情:
  - getEquipmentUsageRate: 查询设备利用率...
    必填参数: dateYear
    可选参数: regionName

LLM 生成任务:
  task_id: S1.T1
  tool: tool_api_fetch
  params: {"endpoint_id": "getEquipmentUsageRate"}   ← 缺 dateYear
             ↓
_validate_tasks Phase 1: _task_drop_reason()
  ep.required = ["dateYear"], query_params = {} → missing = ["dateYear"]
  → drop
             ↓
Phase 2 cascade: 依赖 T1 的 analysis → drop, G_SUM → drop, G_REPORT_HTML → drop
             ↓
_enforce_complexity_constraints: 0 report tools → PlanningError
             ↓
fallback to single-round
```

### 1.2 根因分层

| 层面 | 问题 | 可控性 |
|------|------|--------|
| LLM 行为 | Section prompt 渲染了 `必填参数: dateYear`，但 LLM 仍有概率遗漏 — 不可靠性 | 低（无法根治） |
| Prompt 设计 | `必填参数` 以纯文本形式散落在每个 endpoint 描述中，没有在 params 示例中体现，没有 "你必须" 的集中强化 | 中 |
| 时间值缺失 | prompt 有 `time_param_rules`（推导规则），但没有 `当前 time_range 对应的 dateYear=2026, dateMonth=2026-01` 具体值 | 高 |
| 反馈循环 | section 任务出错后只有终局 stop-the-world（PlanningError），没有 targeted retry with context | 中 |

### 1.3 现有防御层

```
Section LLM 出错
  → _task_drop_reason() 检测 + 掉落任务
  → _stitch_plan 依赖 cascade
  → _enforce_complexity_constraints 硬约束
  → PlanningError → single-round fallback
```

**现状**：只有 "全有 or 全无" 两态。Section 级别没有 soft-landing。

---

## 2. 优化方案：三层递进

### 2.1 Tier 1 — Prompt 工程（\~30 行改动）

**目标**：在 section prompt 中给 LLM 更明确、更具体的参数填写指引。

#### 2.1.1 注入具体时间值

在 `_call_section_llm` 中，从 `intent` 的 `time_range` 槽位提取 `start/end` 日期，计算各端点常用的参数候选值，注入 prompt。

```python
# 新增辅助函数 (planning.py)
def _extract_time_hints(intent: dict) -> dict[str, str] | None:
    """Extract concrete time param values from intent's time_range slot."""
    slots = intent.get("slots", {}) if isinstance(intent.get("slots"), dict) else {}
    tr = slots.get("time_range", {}) if isinstance(slots, dict) else {}
    if isinstance(tr, dict):
        tr_val = tr.get("value")
    else:
        tr_val = None
    if not isinstance(tr_val, dict):
        return None

    start = tr_val.get("start", "")
    end = tr_val.get("end", "")

    hints: dict[str, str] = {}
    if start:
        hints["startDate"] = start
    if end:
        hints["endDate"] = end
        if "-" in end:
            hints["dateYear"] = end[:4]            # "2026-01-01" → "2026"
            hints["dateMonth"] = end[:7]           # "2026-01-01" → "2026-01"
            hints["date"] = end                    # full date
    return hints
```

在 prompt 中注入（加在 SECTION_PROMPT 的 `{time_param_rules}` 之前）：

```python
time_hints = _extract_time_hints(intent)
time_hints_block = ""
if time_hints:
    parts = [f"  {k} = {v}" for k, v in sorted(time_hints.items())]
    time_hints_block = (
        "【时间参数具体值】（从用户 time_range 推导，data_fetch 任务必须使用）\n"
        + "\n".join(parts) + "\n"
    )
```

**改动位置**：
- 新增 `_extract_time_hints`：约 25 行
- `_call_section_llm` 中注入 `time_hints_block`：约 10 行
- `SECTION_PROMPT` 新增占位 `{time_hints}`

#### 2.1.2 必填参数集中警告

在 `section_endpoints_desc` 之后追加一段强制说明：

```python
# 在 _call_section_llm 中，get_endpoints_description() 之后
required_summary = []
for ep_name in section_eps:
    ep = get_endpoint(ep_name)
    if ep and ep.required:
        required_summary.append(
            f"  - {ep_name} 必填: {', '.join(ep.required)}"
        )
required_warning = ""
if required_summary:
    required_warning = (
        "【端点必填参数总览】（⚠️ 每个 data_fetch 任务必须在 params 中包含下列参数）\n"
        + "\n".join(required_summary) + "\n"
    )
```

**改动位置**：`_call_section_llm` 中约 15 行

#### 2.1.3 SECTION_PROMPT params 示例改进

当前 `SECTION_PROMPT` 的 params 示例是：
```json
"params": {"endpoint_id": "..."}
```

改为包含必填参数的完整示例：
```json
"params": {"endpoint_id": "端点名", "必填参数1": "值1", ...}
```

并在 prompt 中加一条硬约束：
```
- data_fetch 任务的 params 必须包含所选端点【端点必填参数总览】中列出的全部必填参数
- 时间类参数值请使用【时间参数具体值】中的候选值
```

**改动位置**：`SECTION_PROMPT` 模板，约 5 行

#### Tier 1 效果预估

| 指标 | 当前 | 预计 |
|------|------|------|
| section LLM 缺必填参数概率 | 40-60%（资产设备场景） | 10-20% |
| 改动量 | — | ~60 行（含 prompt） |
| 风险 | — | 极低（纯 prompt 工程，不改逻辑） |

---

### 2.2 Tier 2 — Section 级重试（\~80 行改动）

**目标**：当 Tier 1 仍无法避免 section LLM 出错时，用 targeted retry 代替直接 fallback。

#### 2.2.1 设计思路

当前 `_generate_plan_multiround` 中的 section retry（planning.py:786-802）只 retry 超时/异常，不针对"验证未通过"的场景。新增：

```
Section LLM 生成任务
  → 预验证：_task_drop_reason() 逐一检查
  → 如果有任务因缺必填参数被判定 drop
    → 构造错误反馈消息
    → 用原 section + 错误反馈 重新调用一次 section LLM
    → 仍失败 → 该 section 标记为 failed（进入 stitch 容错逻辑）
```

#### 2.2.2 重试 prompt 格式

在原 `SECTION_PROMPT` 基础上追加错误反馈段：

```
【上一轮规划错误，请修正】
以下任务因缺少必填参数被拒绝：
- S1.T1 (getEquipmentUsageRate) 缺: dateYear
- S1.T3 (getProductionEquipmentFaultNum) 缺: dateYear
请重新生成本章节任务，确保所有 data_fetch 任务的 params 包含对应端点的全部必填参数。
```

#### 2.2.3 实现概要

**新增函数** `_validate_section_tasks`（planning.py）：
```python
def _validate_section_tasks(
    self,
    tasks: list[TaskItem],
    valid_tools: set[str],
    valid_endpoints: set[str],
) -> list[dict]:
    """Pre-validate section tasks. Returns list of {task_id, reason} for dropped ones."""
    issues = []
    for task in tasks:
        reason = self._task_drop_reason(task, valid_tools, valid_endpoints)
        if reason:
            issues.append({"task_id": task.task_id, "reason": reason})
    return issues
```

**修改 `_fill_one` 内部闭包**（planning.py:778-802）：
```python
async def _fill_one(sec):
    async with sem:
        # First attempt
        tasks, feedback = await _try_section(sec, None)
        if feedback:
            # One retry with explicit error context
            tasks2, feedback2 = await _try_section(sec, feedback)
            return tasks2  # second result wins even if still incomplete
        return tasks
```

其中 `_try_section` 封装 LLM 调用 + 验证 + feedback 生成：

```python
async def _try_section(sec, prev_error_feedback=None):
    try:
        tasks = await self._call_section_llm(
            intent, sec, valid_tools, valid_endpoints,
            rule_hints=rule_hints,
            prompt_suffix=prompt_suffix,
            error_feedback=prev_error_feedback,
        )
    except (asyncio.TimeoutError, PlanningError) as e:
        return [], None  # propagate to existing retry

    issues = self._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    if not issues:
        return tasks, None

    # Build error feedback for potential retry
    lines = ["上一轮规划任务因以下问题被拒绝："]
    for issue in issues[:5]:  # cap at 5 to keep prompt manageable
        lines.append(f"  - {issue['task_id']}: {issue['reason']}")
    lines.append("请重新规划本章节，修正上述问题。")
    return tasks, "\n".join(lines)
```

**`_call_section_llm` 新增参数** `error_feedback: str | None = None`，当非 None 时追加到 prompt 末尾。

#### Tier 2 效果预估

| 指标 | Tier 1 only | Tier 1 + 2 |
|------|------------|------------|
| section LLM fallback 率 | ~15% | ~3% |
| 额外延迟（场景需要 retry） | 0 | +~60s per section |
| 改动量 | ~60 行 | +~80 行 |

---

### 2.3 Tier 3 — 架构层优化（待定，不在本次方案范围）

| 方向 | 描述 | 不纳入原因 |
|------|------|-----------|
| `_enrich_section_endpoints` 携带 required param 元数据 | Endpoint hint 不仅存名称，还存 required params 列表，section prompt 直接用 | 需要改 `PlanSection` schema，影响面较大 |
| Partial plan acceptance | 当部分 section 健康时，减小 plan 范围而非 full fallback | 底层语义复杂（报告的"不完整交付"策略需要产品层决策） |
| Stitch 前 param 自动补全 | 用 time_range 推导的候选值自动填充缺失的 dateYear 等参数 | 自动补全可能填错值，不如让 LLM 纠错 |

---

## 3. 实施方案（Tier 1 + Tier 2 联合）

### 3.1 改动文件

| 文件 | 操作 | 说明 |
|------|------|------|
| `backend/agent/planning.py` | **改造** | 新增 `_extract_time_hints`、`_validate_section_tasks`；改造 `_call_section_llm`（+error_feedback 参数、注入时间值、必填参数警告）；改造 `_fill_one` 闭包（section 重试逻辑） |
| `tests/contract/test_planning_multiround.py` | **新增测试** | 覆盖 `_extract_time_hints`、`_validate_section_tasks`、section retry 路径 |

### 3.2 不改动

- `SECTION_PROMPT` 模板保留（仅新增 `{time_hints}` / `{required_warning}` / `{error_feedback}` 占位，不影响现有 format 调用）
- `_enrich_section_endpoints` 函数签名不变
- `_stitch_plan` 不变
- `_validate_tasks` 不变
- `_generate_plan_multiround` 主流程不变（仅 `_fill_one` 内部增强）

### 3.3 落地步骤

```
Step 1: _extract_time_hints + 单元测试
Step 2: _call_section_llm 注入 time_hints_block + required_warning
Step 3: SECTION_PROMPT 示例改进 + 新增硬约束行
Step 4: _validate_section_tasks + 单元测试
Step 5: _fill_one 增加 section retry 逻辑
Step 6: 全量 contract 测试 + 人工跑原问题验证
```

### 3.4 验收标准

- [ ] `_extract_time_hints({"time_range": {"start": "2026-01-01", "end": "2026-03-31"}})` → `{"dateYear": "2026", "dateMonth": "2026-03", "date": "2026-03-31", "startDate": "2026-01-01", "endDate": "2026-03-31"}`
- [ ] `_validate_section_tasks` 正确检测缺参数任务并返回 issues 列表
- [ ] Section prompt 渲染后包含 `【时间参数具体值】` 和 `【端点必填参数总览】` 两段
- [ ] Section retry 在首轮缺参数时触发
- [ ] Section retry 不超过 1 次
- [ ] 全量 contract 测试通过
- [ ] 人工跑 "生成2026年Q1设备运营效能深度报告" — multi-round 路径成功产出 plan，不 fallback

---

## 4. 风险

| 风险 | 缓解 |
|------|------|
| Section retry 增加延迟 | 仅在首轮验证不通过时触发（正常路径零开销），且 retry 不超过 1 次；section LLM 本身有 60s 超时 |
| Tier 1 prompt 改动可能影响已有正常案例 | 改为追加式注入（新增占位），不影响原有 prompt 段；全量测试兜底 |
| time_range 推导错误（如用户问 "2026年" 但 time_range.end 是 "2026-12-31"） | `end[:4]` = "2026"，`end[:7]` = "2026-12" — 推导正确；仅注入不强制 |

---

*版本 v1.0 — 2026-05-01*
