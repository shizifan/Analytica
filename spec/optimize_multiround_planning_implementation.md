# Multi-Round Planning 骨架生成质量优化 — 详细实施方案

**基于**：spec/optimize_multiround_planning.md（v1.0, 2026-05-01）
**版本**：v1.0
**状态**：待实施
**改动文件**：2 个（planning.py + test_planning_multiround.py）

---

## 一、改动总览

| 序号 | 文件 | 改动类型 | 行数估算 | 说明 |
|------|------|---------|---------|------|
| A1 | `backend/agent/planning.py` | 新增函数 | ~25 行 | `_extract_time_hints` |
| A2 | `backend/agent/planning.py` | 新增代码 | ~15 行 | `_call_section_llm` 内注入 `time_hints_block` + `required_warning` |
| A3 | `backend/agent/planning.py` | 修改模板 | ~8 行 | `SECTION_PROMPT` 新增占位 + 硬约束行 + 示例改进 |
| A4 | `backend/agent/planning.py` | 修改函数签名 | ~5 行 | `_call_section_llm` 新增 `error_feedback` 参数 |
| A5 | `backend/agent/planning.py` | 新增函数 | ~25 行 | `_validate_section_tasks` |
| A6 | `backend/agent/planning.py` | 重写闭包 | ~40 行 | `_generate_plan_multiround` 内的 `_fill_one` + 新增 `_try_section` |
| B1 | `tests/contract/test_planning_multiround.py` | 新增测试 | ~60 行 | 覆盖 `_extract_time_hints`、`_validate_section_tasks`、retry 路径 |

**合计**：~178 行（含测试）

---

## 二、逐项改动详述

### A1. 新增 `_extract_time_hints` 函数

**位置**：`backend/agent/planning.py`，在 `_extract_output_formats` 之后（约第 912 行之后）

**新增代码**：

```python
def _extract_time_hints(intent: dict[str, Any]) -> dict[str, str] | None:
    """从 intent 的 time_range slot 提取具体时间参数候选值。

    用于注入 section prompt，减少 LLM 自行解析 JSON 并推导
    参数值时的遗漏概率（Tier 1 核心优化）。
    """
    slots = intent.get("slots", {})
    if not isinstance(slots, dict):
        return None

    tr = slots.get("time_range", {})
    if not isinstance(tr, dict):
        return None

    tr_val = tr.get("value")
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
            hints["dateYear"] = end[:4]      # "2026-03-31" → "2026"
            hints["dateMonth"] = end[:7]     # "2026-03-31" → "2026-03"
            hints["date"] = end              # 完整日期
    return hints if hints else None
```

**依赖**：无新增 import（`dict[str, Any]` 已通过 `from typing import Any` 可用，但函数签名用 `dict` 泛型需确认 Python 版本。当前 `planning.py` 第 903 行 `_extract_output_formats` 已用 `dict[str, Any]`，故兼容。）

**注意**：此函数是**纯函数**（无 self），放在类外或作为 staticmethod 均可。因 `_extract_output_formats` 是实例方法，此处也保持实例方法风格（但不引用 self）。

---

### A2. `_call_section_llm` 内注入 time_hints_block + required_warning

**位置**：`backend/agent/planning.py`，约第 946-960 行（`prompt = SECTION_PROMPT.format(...)` 调用前）

**当前代码**（第 946-960 行）：
```python
        cookbook_block = (
            f"\n【员工专属规划提示（Cookbook）】\n{prompt_suffix}\n"
            if prompt_suffix else ""
        )

        prompt = SECTION_PROMPT.format(
            section_id=section.section_id,
            section_name=section.name,
            section_description=section.description,
            focus_metrics=", ".join(section.focus_metrics) or "（未指定）",
            expected_task_count=section.expected_task_count,
            intent_json=json.dumps(intent, ensure_ascii=False, default=str),
            section_endpoints_desc=section_endpoints_desc,
            tools_description=tools_desc,
            time_param_rules=resolve_rule_hint("time_param", rule_hints),
            cargo_selection_rules=resolve_rule_hint("cargo_selection", rule_hints),
            employee_cookbook=cookbook_block,
        )
```

**改为**：

```python
        cookbook_block = (
            f"\n【员工专属规划提示（Cookbook）】\n{prompt_suffix}\n"
            if prompt_suffix else ""
        )

        # ── Tier 1.1: 注入具体时间参数候选值 ──
        time_hints = _extract_time_hints(intent)
        time_hints_block = ""
        if time_hints:
            parts = [f"  {k} = {v}" for k, v in sorted(time_hints.items())]
            time_hints_block = (
                "【时间参数具体值】（从用户 time_range 推导，data_fetch 任务必须使用）\n"
                + "\n".join(parts) + "\n"
            )

        # ── Tier 1.2: 必填参数集中警告 ──
        required_summary = []
        for ep_name in sorted(section_eps):
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

        # ── Tier 2: 错误反馈（retry 时非空） ──
        error_feedback_block = ""
        if error_feedback:
            error_feedback_block = (
                "\n【上一轮规划错误，请修正】\n" + error_feedback + "\n"
            )

        prompt = SECTION_PROMPT.format(
            section_id=section.section_id,
            section_name=section.name,
            section_description=section.description,
            focus_metrics=", ".join(section.focus_metrics) or "（未指定）",
            expected_task_count=section.expected_task_count,
            intent_json=json.dumps(intent, ensure_ascii=False, default=str),
            section_endpoints_desc=section_endpoints_desc,
            tools_description=tools_desc,
            time_param_rules=resolve_rule_hint("time_param", rule_hints),
            cargo_selection_rules=resolve_rule_hint("cargo_selection", rule_hints),
            employee_cookbook=cookbook_block,
            time_hints=time_hints_block,
            required_warning=required_warning,
            error_feedback=error_feedback_block,
        )
```

**关键说明**：
- `time_hints_block`、`required_warning`、`error_feedback_block` 默认空字符串，不影响现有 behavior
- `get_endpoint(ep_name)` 已在第 32 行通过 `from backend.agent.api_registry import get_endpoint` 导入，可直接使用
- `section_eps` 已在第 927-929 行定义为 frozenset，可直接迭代

---

### A3. SECTION_PROMPT 模板修改

**位置**：`backend/agent/planning.py`，第 314-363 行

**当前 SECTION_PROMPT**（第 314-363 行，为节省篇幅仅展示需修改区域）：

```
【可用工具】
{tools_description}

{time_param_rules}

{cargo_selection_rules}
{employee_cookbook}
【硬约束】
```

和输出示例：
```json
"params": {"endpoint_id": "..."}
```

**改为**：

```
【可用工具】
{tools_description}

{time_hints}

{required_warning}

{time_param_rules}

{cargo_selection_rules}
{employee_cookbook}
{error_feedback}
【硬约束】
- 所有 task_id 必须以 "{section_id}." 前缀，例如 {section_id}.T1, {section_id}.T2
- depends_on 只能引用本章节内的 task_id（跨章节依赖由汇总层处理）
- 至少 1 个 data_fetch 任务
- 如有 visualization，必须 depends_on 至少 1 个本章节内的 data_fetch
- analysis 任务遵循"intent 字段描述目标，params 只写 data_ref"原则
- visualization 任务遵循"intent 字段描述图表意图，params 只写 chart_type"原则
- 工具必须从【可用工具】清单中选取，端点必须从【本章节可用端点】中选取
- data_fetch 任务的 params 必须包含所选端点【端点必填参数总览】中列出的全部必填参数
- 时间类参数值必须使用【时间参数具体值】中的候选值

【输出严格 JSON，无 <think>，无 markdown】
{{
  "tasks": [
    {{
      "task_id": "{section_id}.T1",
      "type": "data_fetch",
      "name": "任务名",
      "description": "对用户友好的描述",
      "depends_on": [],
      "tool": "tool_api_fetch",
      "params": {{"endpoint_id": "端点名", "必填参数1": "值1", "必填参数2": "值2"}},
      "intent": "",
      "estimated_seconds": 10
    }}
  ]
}}
```

**改动汇总**：
1. 在 `{tools_description}` 后新增 `{time_hints}` 和 `{required_warning}` 占位（2 行）
2. 在 `{employee_cookbook}` 后新增 `{error_feedback}` 占位（1 行）
3. `【硬约束】` 下新增 2 条规则（2 行）
4. `params` 示例从 `{"endpoint_id": "..."}` 改为 `{"endpoint_id": "端点名", "必填参数1": "值1", "必填参数2": "值2"}`（1 行）

---

### A4. `_call_section_llm` 新增 `error_feedback` 参数

**位置**：`backend/agent/planning.py`，第 914-922 行（函数签名）

**当前签名**：
```python
    async def _call_section_llm(
        self,
        intent: dict[str, Any],
        section: "PlanSection",
        valid_tools: set[str],
        valid_endpoints: set[str],
        rule_hints: dict[str, str] | None = None,
        prompt_suffix: str = "",
    ) -> list[TaskItem]:
```

**改为**：
```python
    async def _call_section_llm(
        self,
        intent: dict[str, Any],
        section: "PlanSection",
        valid_tools: set[str],
        valid_endpoints: set[str],
        rule_hints: dict[str, str] | None = None,
        prompt_suffix: str = "",
        error_feedback: str | None = None,
    ) -> list[TaskItem]:
```

**影响分析**：`_call_section_llm` 的调用方仅两处：
1. `_generate_plan_multiround` 内的 `_fill_one` 闭包（第 781-784 行 + 第 792-795 行）— 将被 A6 重写
2. （无其他调用方）

**无外部调用方**，签名变更安全。

---

### A5. 新增 `_validate_section_tasks` 函数

**位置**：`backend/agent/planning.py`，在 `_task_drop_reason` 之前（约第 1458 行之前）或作为 PlanningEngine 的新方法

**新增代码**：

```python
    def _validate_section_tasks(
        self,
        tasks: list[TaskItem],
        valid_tools: set[str],
        valid_endpoints: set[str],
    ) -> list[dict[str, str]]:
        """预验证单个 section 的任务列表。

        在 section 生成任务后、stitch 前调用，检测可修正的问题
        （如缺必填参数），为 retry 提供结构化错误反馈。

        返回被判定为 drop 的任务列表 [{task_id, reason}]。
        注意：此处不执行级联删除（与 _validate_tasks 不同），
        级联逻辑保留在 stitch 后的全局 _validate_tasks 中。
        """
        issues: list[dict[str, str]] = []
        for task in tasks:
            reason = self._task_drop_reason(task, valid_tools, valid_endpoints)
            if reason:
                issues.append({"task_id": task.task_id, "reason": reason})
        return issues
```

**设计要点**：
- 复用现有 `_task_drop_reason`（第 1459 行），单任务验证逻辑零冗余
- 不做级联删除 — 这是刻意设计，因为 `_fill_one` 内的 retry 只需要指出哪些任务本身有问题，级联在 stitch 后的 `_validate_tasks` Phase 2 中统一处理
- 返回 list of dict，而非修改 plan，保持纯函数语义

---

### A6. 重写 `_fill_one` 闭包 + 新增 `_try_section` 内部函数

**位置**：`backend/agent/planning.py`，第 778-802 行

**当前代码**：
```python
        async def _fill_one(sec):
            async with sem:
                try:
                    return await self._call_section_llm(
                        intent, sec, valid_tools, valid_endpoints,
                        rule_hints=rule_hints,
                        prompt_suffix=prompt_suffix,
                    )
                except (asyncio.TimeoutError, PlanningError) as e:
                    logger.warning(
                        "[planning-multiround] section %s first attempt failed: %s",
                        sec.section_id, e,
                    )
                    try:
                        return await self._call_section_llm(
                            intent, sec, valid_tools, valid_endpoints,
                            rule_hints=rule_hints,
                            prompt_suffix=prompt_suffix,
                        )
                    except Exception as e2:
                        logger.warning(
                            "[planning-multiround] section %s retry failed: %s",
                            sec.section_id, e2,
                        )
                        return e2
```

**改为**：

```python
        async def _try_section(sec, error_feedback=None):
            """调用 section LLM + 预验证，返回 (tasks, feedback_or_none)。

            - 正常无问题：返回 (tasks, None)
            - 有验证问题：返回 (tasks, error_feedback_str) — 调用方应 retry
            - TimeoutError/PlanningError：向上传播给 _fill_one 的系统级重试
            """
            tasks = await self._call_section_llm(
                intent, sec, valid_tools, valid_endpoints,
                rule_hints=rule_hints,
                prompt_suffix=prompt_suffix,
                error_feedback=error_feedback,
            )

            issues = self._validate_section_tasks(
                tasks, valid_tools, valid_endpoints,
            )
            if not issues:
                return tasks, None

            # 构造错误反馈（最多 5 条，防止 prompt 膨胀）
            lines = ["上一轮规划任务因以下问题被拒绝："]
            for issue in issues[:5]:
                lines.append(f"  - {issue['task_id']}: {issue['reason']}")
            lines.append("请重新规划本章节，修正上述问题。")
            return tasks, "\n".join(lines)

        async def _fill_one(sec):
            async with sem:
                # ── 首次尝试 ──
                try:
                    tasks, feedback = await _try_section(sec, None)
                except (asyncio.TimeoutError, PlanningError) as e:
                    logger.warning(
                        "[planning-multiround] section %s first attempt failed: %s",
                        sec.section_id, e,
                    )
                    # 系统级盲重试（保留现有行为）
                    try:
                        return await self._call_section_llm(
                            intent, sec, valid_tools, valid_endpoints,
                            rule_hints=rule_hints,
                            prompt_suffix=prompt_suffix,
                        )
                    except Exception as e2:
                        logger.warning(
                            "[planning-multiround] section %s retry failed: %s",
                            sec.section_id, e2,
                        )
                        return e2

                # ── 验证级重试（带错误上下文） ──
                if feedback:
                    logger.info(
                        "[planning-multiround] section %s has validation issues, "
                        "retrying with feedback",
                        sec.section_id,
                    )
                    try:
                        tasks2, _feedback2 = await _try_section(sec, feedback)
                        return tasks2  # 二次结果直接采纳
                    except (asyncio.TimeoutError, PlanningError) as e:
                        logger.warning(
                            "[planning-multiround] section %s feedback retry "
                            "failed: %s, using first-attempt result",
                            sec.section_id, e,
                        )
                        return tasks  # 回退到首次结果

                return tasks
```

**关键设计决策**：

1. **保留系统级盲重试**：TimeoutError/PlanningError 仍由 `_fill_one` 捕获并盲重试一次，retry 失败则返回异常对象（stitch 通过 `isinstance(result, BaseException)` 处理）

2. **验证级 retry 不抛异常**：retry 中若再次 TimeoutError/PlanningError，fallback 到首次结果 `tasks`（不做第三次尝试），让 stitch 和 `_validate_tasks` 的现有容错逻辑接手

3. **二次结果直接采纳**：不进行二次验证（避免无限循环），stitch 后的 `_validate_tasks` 会做最终裁决

4. **`_try_section` 不捕获 TimeoutError/PlanningError**：这些异常向上传播给 `_fill_one`，不混淆"验证失败"和"系统错误"两个重试路径

---

## 三、测试用例

### B1. `tests/contract/test_planning_multiround.py` 新增测试

在文件末尾（第 228 行之后）新增以下测试：

```python
# ── Tier 1: _extract_time_hints ─────────────────────────────────

def test_extract_time_hints_full_range():
    intent = {
        "slots": {
            "time_range": {
                "value": {"start": "2026-01-01", "end": "2026-03-31",
                          "description": "2026年Q1"},
            }
        }
    }
    hints = _extract_time_hints(intent)
    assert hints == {
        "date": "2026-03-31",
        "dateMonth": "2026-03",
        "dateYear": "2026",
        "endDate": "2026-03-31",
        "startDate": "2026-01-01",
    }


def test_extract_time_hints_no_slots():
    assert _extract_time_hints({}) is None


def test_extract_time_hints_no_time_range():
    intent = {"slots": {"domain": {"value": "D2"}}}
    assert _extract_time_hints(intent) is None


def test_extract_time_hints_time_range_not_dict():
    """slots.time_range.value 为非 dict 时的防御"""
    intent = {"slots": {"time_range": {"value": "2026年Q1"}}}
    assert _extract_time_hints(intent) is None


def test_extract_time_hints_no_start():
    """仅有 end 时的推导"""
    intent = {
        "slots": {
            "time_range": {
                "value": {"end": "2026-12-31", "description": "2026年"},
            }
        }
    }
    hints = _extract_time_hints(intent)
    assert hints["dateYear"] == "2026"
    assert hints["dateMonth"] == "2026-12"
    assert "startDate" not in hints


def test_extract_time_hints_no_end():
    """仅有 start 时的推导"""
    intent = {
        "slots": {
            "time_range": {
                "value": {"start": "2026-01-01"},
            }
        }
    }
    hints = _extract_time_hints(intent)
    assert hints["startDate"] == "2026-01-01"
    assert "dateYear" not in hints


# ── Tier 2: _validate_section_tasks ────────────────────────────

def test_validate_section_tasks_clean(engine):
    """所有任务有效 → 返回空列表"""
    tasks = [
        TaskItem(
            task_id="S1.T1", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getInvestPlanByYear", "dateYear": "2026"},
        ),
    ]
    valid_tools = {"tool_api_fetch"}
    valid_endpoints = {"getInvestPlanByYear"}
    issues = engine._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    assert issues == []


def test_validate_section_tasks_missing_required_param(engine):
    """缺必填参数 → 返回 issue"""
    tasks = [
        TaskItem(
            task_id="S1.T1", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getEquipmentUsageRate"},  # 缺 dateYear
        ),
    ]
    valid_tools = {"tool_api_fetch"}
    valid_endpoints = {"getEquipmentUsageRate"}
    issues = engine._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    assert len(issues) == 1
    assert issues[0]["task_id"] == "S1.T1"
    assert "missing required params" in issues[0]["reason"]
    assert "dateYear" in issues[0]["reason"]


def test_validate_section_tasks_hallucinated_endpoint(engine):
    """幻觉端点 → 返回 issue"""
    tasks = [
        TaskItem(
            task_id="S1.T1", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "nonexistentEndpoint"},
        ),
    ]
    valid_tools = {"tool_api_fetch"}
    valid_endpoints = {"getThroughputAndTargetThroughputTon"}
    issues = engine._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    assert len(issues) == 1
    assert "hallucinated endpoint" in issues[0]["reason"]


def test_validate_section_tasks_mixed(engine):
    """混合场景：部分有效、部分无效"""
    tasks = [
        TaskItem(
            task_id="S1.T1", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getEquipmentUsageRate"},  # 缺 dateYear
        ),
        TaskItem(
            task_id="S1.T2", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getInvestPlanByYear", "dateYear": "2026"},
        ),
        TaskItem(
            task_id="S1.T3", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getProductionEquipmentFaultNum"},  # 缺 dateYear
        ),
    ]
    valid_tools = {"tool_api_fetch"}
    valid_endpoints = {"getEquipmentUsageRate", "getInvestPlanByYear",
                       "getProductionEquipmentFaultNum"}
    issues = engine._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    assert len(issues) == 2
    affected_ids = {i["task_id"] for i in issues}
    assert affected_ids == {"S1.T1", "S1.T3"}
```

**注意**：`_extract_time_hints` 是模块级函数，测试中需导入：
```python
from backend.agent.planning import PlanningEngine, _extract_time_hints
```

---

## 四、实施顺序

按风险递增、可独立验证的顺序执行：

| 步骤 | 内容 | 验收方式 | 依赖 |
|------|------|---------|------|
| **Step 1** | A1: 新增 `_extract_time_hints` + B1 对应测试 | `pytest tests/contract/test_planning_multiround.py -k "extract_time_hints"` | 无 |
| **Step 2** | A2 + A3 + A4: `_call_section_llm` 注入 time_hints/required_warning/error_feedback + SECTION_PROMPT 改版 | 代码审查：检查 prompt 渲染后包含新占位内容 | Step 1 |
| **Step 3** | A5: 新增 `_validate_section_tasks` + B1 对应测试 | `pytest tests/contract/test_planning_multiround.py -k "validate_section_tasks"` | Step 2 |
| **Step 4** | A6: 重写 `_fill_one` + `_try_section` | 代码审查：确认两层 retry 逻辑正确 | Step 2, 3 |
| **Step 5** | 全量 contract 测试 | `pytest tests/contract/test_planning_multiround.py -v` | Step 4 |
| **Step 6** | 全量 planning 相关测试 | `pytest tests/contract/ -k "planning" -v` | Step 5 |
| **Step 7** | 人工验证原问题场景 | 跑 "生成2026年Q1设备运营效能深度报告"，确认 multi-round 成功 | Step 6 |

---

## 五、回滚方案

所有改动均为增量式（新增占位/参数均有默认值），回滚简单：

1. **Prompt 层**：从 SECTION_PROMPT 中移除 `{time_hints}`、`{required_warning}`、`{error_feedback}` 占位及新增硬约束行
2. **逻辑层**：`_fill_one` 恢复为原始的 try/except 盲重试
3. **函数**：删除 `_extract_time_hints`、`_validate_section_tasks`、`_try_section`
4. **签名**：`_call_section_llm` 移除 `error_feedback` 参数（调用方恢复后不影响）

---

## 六、风险矩阵

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| `_extract_time_hints` 在边缘 intent 格式下返回错误推导值 | 低 | 中（可能填入错误年份） | 多层 `isinstance` 防御；推导值仅作为提示，不强制，LLM 仍可自行覆盖 |
| SECTION_PROMPT 新增行影响已有正常案例的规划质量 | 低 | 中 | 限追加式注入（全部为新占位），不影响现有 prompt 段；全量测试兜底 |
| validation retry 增加延迟 | 仅故障路径 | 低 | 仅首轮验证不通过时触发（正常路径零开销）；retry 不超过 1 次 |
| `_try_section` 内部 TimeoutError 传播破坏 `_fill_one` 原有 retry | 低 | 高 | A6 设计已明确保留系统级盲重试层，Timeouterror 不上抛到 stitch |
| format() 调用因新增占位而报 KeyError | 中 | 高 | 在 `_call_section_llm` 中对占位统一设置默认值 `""`；Step 2 完成后立即跑测试 |

---

*版本 v1.0 — 2026-05-01*
