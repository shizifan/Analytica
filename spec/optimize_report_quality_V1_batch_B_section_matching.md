# 批次 B — Section ↔ Dataset 强匹配 实施方案

> **状态**：待实施 | **父文档**：`spec/optimize_report_quality_V1.md` | **预计工时**：2.5 天
>
> **依存关系**：**依赖 D-2 的 D.3（章节模板库）**完成，因为 section 匹配规则依赖 `required_intents` 字段。实施前确保 `_section_templates.py` 已就位且 `SectionSpec` 的 `metric_focus`、`group_by`、`required_intents`、`domain_roles` 字段可用。

---

## 0. 背景与目标

### 0.1 本批次要解决的问题

| 症状 | 根因编号 | 本批次覆盖 |
|---|---|---|
| 章节↔图表语义错位（"设备结构分析"配月份折线图） | R3：section 与 dataset 是轮询兜底分配，task_refs 未覆盖时按 task_id 轮询塞给 section | B.1/B.2 强匹配逻辑 |
| 多个章节渲染相同数据（运营总览 + 时间趋势两章画同一条线） | R4：LLM 一次性规划所有 section，无差异化逻辑保证每 section 拿到不同 metric | B.3 已用 metric 去重 |

### 0.2 目标

- "设备结构分析"章节配图为机种透视/状态分布/类型构成（不再配月份折线图）
- 任意两个章节的图表 (asset_id, group_by) 组合无完全重叠
- 章节内容差异化（配文也不同）

---

## 1. B.1 — Outline Schema 扩展（0.5 天）

### 1.1 改动

在 `backend/agent/planning.py` 的 `SectionSpec` 中扩展以下字段（D.3 已定义）：

```python
class SectionSpec(BaseModel):
    name: str
    role: Literal["summary", "status", "analysis", "attribution", "recommendation", "appendix"]
    metric_focus: list[str]              # 该章节的核心指标，如 ["usageRate", "serviceableRate"]
    group_by: list[str]                  # 期望的分组维度，如 ["dateMonth", "firstLevelClassName"]
    required_intents: list[AnalysisIntent]  # D.2 定义
    domain_roles: dict[str, str]         # 如 {"D7": "primary", "D5": "context"}
```

这些字段在 D.3 章节模板中定义，经 `planning → execution → content_collector` 传递到本批次使用。

---

## 2. B.2 — Collector 匹配逻辑改造（1.5 天）

### 2.1 问题

**代码位置**：`backend/tools/report/_content_collector.py:370-381`

`_associate()` 函数当前是轮询兜底分配：按 task_id 顺序轮流塞给 section，完全不考虑 section 的语义需求。

### 2.2 改动

**重写 `_associate()` 函数**：按 section 的 `metric_focus` × `group_by` 与 task 的 endpoint metadata 做强匹配。

```python
def _associate(sections, tasks, assets):
    """
    按 section 的 metric_focus / group_by / domain_roles 与 task 的
    endpoint metadata 做强匹配，替代原来的轮询兜底。
    """
    matched = {s.name: [] for s in sections}
    orphan = []

    for task in tasks:
        candidates = [s for s in sections
                      if matches(task, s.metric_focus, s.group_by, s.domain_roles)]

        if len(candidates) == 1:
            matched[candidates[0].name].append(task)
        elif len(candidates) > 1:
            # 优先选 domain_roles 中标记为 primary 的
            primary = [s for s in candidates
                       if s.domain_roles.get(task.domain) == "primary"]
            target = (primary or candidates)[0]
            matched[target.name].append(task)
        else:
            orphan.append(task)

    return matched, orphan
```

**匹配失败的 task 不强塞**：放入 "orphan tasks" 列表。Outline planner 读取 orphan tasks 时显式提示 LLM："以下任务未匹配到任何章节，可考虑补充章节或忽略"。

**`matches()` 函数逻辑**：

1. 检查 task endpoint 的 metric 是否在 section 的 `metric_focus` 中
2. 检查 task endpoint 的 group_by 维度是否与 section 的 `group_by` 兼容
3. 检查 task 的 domain 是否在 section 的 `domain_roles` 中（且不是 "none"）

### 2.3 与 dataset 缓存的注意事项

asset_id 命名规范：`{task_id}_{endpoint}_{params_hash[:8]}`，确保 dataset cache key 包含 `params_sent` 的 deterministic hash。避免同一 endpoint 不同参数的数据混淆（CQ-12 应对）。

---

## 3. B.3 — 已用 Metric 去重（0.5 天）

### 3.1 问题

运营总览 + 时间趋势两章画同一条线（同一组 metric × group_by 组合），如两章都使用 `(usageRate, dateMonth)` 画利用率月度趋势。

### 3.2 改动

**1. `_outline_planner.py` 生成 LLM prompt 时增加"已使用 metric 集合"约束**：

```
## 章节差异化约束
- section[0]「运营总览」已使用：[usageRate@dateMonth]
- section[1]「时间趋势」不可再使用 usageRate@dateMonth，须选择不同的 (metric, group_by) 组合
```

**2. validator：扫描各章节产出的 chart asset_id × group_by**：

若两章节命中同一组合 → 重试 LLM。重试 2 次仍重复 → 保留首个，第二个章节用文字描述替代图表。

**3. 适用 validator 规则**（复用 PR-2 模式）：

| Validator | 触发条件 | 行为 | 上限 |
|---|---|---|---|
| `validate_section_uniqueness` | 两章节 (metric_focus, group_by) 完全重叠 | 重试 LLM | 2 次，超限保留首个 |

**全局上限**：整份 outline 重生成累计 ≤ 6 次。

---

## 4. 验收标准

- [ ] 任意两个章节的图表 (asset_id, group_by) 组合无完全重叠
- [ ] 章节内容差异化（配文也不同，不是简单换图）
- [ ] "设备结构分析"章节配图为机种透视/状态分布/类型构成（不再配月份折线图）
- [ ] "设备成本分析"章节包含资产视角（D5）+ 消耗视角（D7）+ 投资视角（D6）

---

## 5. 文件清单

| 文件 | 改动概要 |
|---|---|
| `backend/agent/planning.py` | B.1: `SectionSpec` 扩展 `metric_focus` / `group_by` / `domain_roles` 字段 |
| `backend/tools/report/_content_collector.py` | B.2: 重写 `_associate()` 函数，按 `metric_focus × group_by × domain_roles` 做强匹配 + orphan tasks 处理 |
| `backend/tools/report/_outline_planner.py` | B.3: LLM prompt 增加"已使用 metric 集合"约束 + validator 去重 |

---

> **下一步**：本批次完成后，所有 5 个批次的实施方案均可闭环。按完整 spec 的里程碑 M3 验收。详见父文档 `optimize_report_quality_V1.md` §7 实施顺序与里程碑。
