# 批次 D-1 — 跨域基础 实施方案（含 D.1 + D.2）

> **状态**：待实施 | **父文档**：`spec/optimize_report_quality_V1.md` | **预计工时**：3.5 天 | **包含子项**：D.1 perception 层 domain 路由（2 天）+ D.2 planner prompt 增量约束（1.5 天）
>
> **依存关系**：依赖 A.0（dataset 持久化）完成。D.1 有验证门 — 跨 domain chain 在此环节直接验证，失败则改写方案。
>
> **后续批次**：D-2（内容深化）在 D-1 验证通过后启动。D-2 的 D.3 完成后才解锁批次 B（section 匹配）。

---

## 0. 背景与目标

### 0.1 本批次要解决的问题

当前报告的两大结构性问题：

| 症状 | 根因 | 本批次覆盖 |
|---|---|---|
| 所有任务集中单一 domain，跨 domain 调用 = 0 | 无 domain 路由机制 | D.1 perception 层 domain 路由 |
| 每章节仅 1 个分析视角，LLM 产出的报告单调重复 | prompt 无内容多样性约束 | D.2 planner 增量约束 |

### 0.2 目标

建立跨 domain 调用链和章节多样性规则，为 D-2 的章节模板和分析模块打下基础：

- **跨域**：单份报告 task 列表跨 domain ≥ 3 个
- **有约束**：每个 analysis 类章节 ≥ 2 种 analysis_intent，不同章节不重复

---

## 1. D.1 — Perception 层 Domain 路由（2 天）

### 1.1 背景

现网真实数据证实跨 domain 调用 = 0。outline planner 拿到的 raw_items 永远只有单 domain，光改 outline planner 解决不了。必须在 perception 层（task 生成阶段）做 domain 路由。

### 1.2 改动

**1. 新增报告类型枚举**（`backend/models/schemas.py`）：

```python
class ReportType(str, Enum):
    EQUIPMENT_OPS = "equipment_ops"          # 设备运营
    BUSINESS_OPS = "business_ops"            # 业务运营
    BUSINESS_DASHBOARD = "business_dashboard" # 商务驾驶舱
    CUSTOMER_PROFILE = "customer_profile"    # 客户专题
    ASSET_INVENTORY = "asset_inventory"      # 资产盘点
    INVESTMENT_PROGRESS = "investment_progress" # 投资进度
    GOVERNANCE = "governance"                # 投企治理
```

**2. 报告类型 → Domain 配置映射**：

```python
REPORT_DOMAIN_CONFIG = {
    ReportType.EQUIPMENT_OPS: {
        "primary": ["D7"],            # 设备子屏
        "secondary": ["D5", "D6"],    # 资产、投资
        "context": ["D1", "D2"],      # 业务、商务
        "endpoint_quota": {"D7": 4, "D5": 2, "D6": 1, "D1": 2, "D2": 1},
    },
    # 其他类型详见父文档 §附录 B
}
```

完整配置表详见父文档 `optimize_report_quality_V1.md` §附录 B（7 种报告类型的 domain 配额）。

**3. PLANNING_PROMPT 改造**（`backend/agent/planning.py`）：

- 第一步：识别报告类型（基于用户问题 + 关键词匹配 + LLM 兜底）
- 第二步：按报告类型选 domain 配置
- 第三步：在每个 domain 的 endpoint 池中按 quota 选端点
- 复杂度规则改造（`_complexity_rules.py:71-127`）：full_report 不再约束总数，约束"每报告类型必须覆盖的 domain 集合"

**4. 去除两道断头路（关键）**：

当前 `planning.py` 有两个函数会**剥离 section metadata**，导致 D.1 选好的 domain / metric / endpoint_hints 跑到 content_collector 全是空的：

- `_stitch_plan` (line 1295)：当前 `"sections": [{"name": s.name} for s in kept_sections]` 只保留 name → **改为完整保留** `{name, role, focus_metrics, domain_hint, endpoint_hints, required_intents, endpoint_candidates, subsections}`
- `_sanitize_report_structure` (line 479)：当前 `s.pop("task_refs", None)` 主动删 task_refs → **改为白名单逐字段清洗**（只剥真正不该有的字段，保留 D.1/D.3 引入的所有 metadata）

**配套验证**：单元测试覆盖"D.1 选定 domain → stitch 后 metadata 仍存在 → content_collector 收到完整 section"端到端 path。

### 1.3 D.1 验证节点

**在此环节直接验证跨 domain chain**，判定标准 + 失败回炉路径：

| D.1 结果 | 决策 |
|---|---|
| ✅ task 列表跨 domain ≥ 3 + 数据正确归到对应章节 | 按计划推进 D.2 / D-2 |
| ⚠️ 跨 domain 调用成功但 section 归属错乱 | 提前启动批次 B（section 匹配）；D.2 / D-2 顺延 1 天 |
| ❌ perception 层无法稳定路由到正确 domain | D.1 方案直接改写（如把"识别报告类型"前置到多轮对话的 perception 层），不留旧路径 |

### 1.4 验收

- [ ] 设备运营报告 task 列表跨 domain ≥ 3 个（D7+D5+D1 至少各 1）
- [ ] 报告类型识别准确率 ≥ 90%（人工抽样 20 份验证）
- [ ] 单元测试：`_stitch_plan` 和 `_sanitize_report_structure` 不再丢弃 D.1 注入的 section 字段

---

## 2. D.2 — Planner Prompt 增量约束（1.5 天）

### 2.1 问题

`_planner_prompts.py` 现有 schema 对章节内容多样性和跨 domain 协作无约束，导致 LLM 产出的报告单调重复。

### 2.2 关键判断

**不重写 prompt，追加约束**。现有 schema 已经成熟，只加增量规则 + metadata。

### 2.3 改动

**1. `assets_summary` 增加 metadata**：

```json
{
  "asset_id": "T003_chart",
  "kind": "chart",
  "source_task": "T003",
  "endpoint_id": "getEquipmentUsageRate",
  "domain": "D7",
  "domain_role": "primary",
  "metric_focus": ["usageRate"],
  "group_by": ["dateMonth", "ownerLgZoneName"],
  "preview": "..."
}
```

D.1 注入的 `domain` / `domain_role` / `metric_focus` / `group_by` 在此处首次被 LLM 可见。

**2. 新增 `AnalysisIntent` 枚举**（`backend/models/schemas.py`）：

```python
class AnalysisIntent(str, Enum):
    SINGLE_METRIC_TREND = "single_metric_trend"      # 单指标时间趋势
    BREAKDOWN_BY_DIM = "breakdown_by_dim"            # 单维下钻
    CROSSTAB_2D = "crosstab_2d"                      # 二维透视
    YOY_COMPARE = "yoy_compare"                      # 同比对比
    CORRELATION = "correlation"                      # 相关性
    ANOMALY_DETECT = "anomaly_detect"                # 异常检测
    TOP_N = "top_n"                                  # Top N 排名
```

**3. prompt 追加约束**（在 `_planner_prompts.py` 现有 `_OUTPUT_SCHEMA_DOC` 之后追加）：

```
## 章节内容多样性约束
- 每个 analysis 类章节必须覆盖至少 2 种不同的 analysis_intent
- 不同章节的 (metric_focus, group_by) 组合不可完全重复
- 章节配图须与 metric_focus 一致（不能给"成本章节"配"利用率图"）

## 跨 domain 协作约束
- 优先使用 domain_role=primary 的 asset 作为主图
- secondary domain 的 asset 用于补充对比或上下文
- 一个章节可引用 ≤2 个 domain 的 asset

## AnalysisIntent 枚举
- single_metric_trend : 单指标时间趋势（line）
- breakdown_by_dim   : 单维下钻（bar/pie）
- crosstab_2d        : 二维透视（heatmap/stacked bar/grouped bar）
- yoy_compare        : 同比对比（双轴 line/grouped bar）
- correlation        : 相关性（scatter/双轴 line）
- anomaly_detect     : 异常检测（line + 异常点标注）
- top_n              : Top N 排名（横向 bar）
```

**4. 复用 PR-2 validator 三件套**：

- intent 多样性 validator（每章 ≥ 2 种 intent）
- metric_focus 一致性 validator（图表 metric ⊆ 章节 metric_focus）
- 跨章节去重 validator（详见 batch B.3）

---

## 3. 文件清单

| 文件 | 改动概要 |
|---|---|
| `backend/models/schemas.py` | D.1/D.2: 加 `ReportType`、`AnalysisIntent` 枚举；加 `SectionSpec` |
| `backend/agent/planning.py` | D.1: `PLANNING_PROMPT` 加报告类型识别 + domain 路由；`_stitch_plan` 完整透传 sections；`_sanitize_report_structure` 白名单清洗 |
| `backend/agent/_complexity_rules.py` | D.1: 改约束维度（intent/domain 覆盖率） |
| `backend/tools/report/_planner_prompts.py` | D.2: 章节多样性 + 跨 domain 协作约束 + AnalysisIntent 枚举 |

---

## 4. 验收标准

- [ ] 单份报告 task 列表跨 domain ≥ 3 个
- [ ] 每个 analysis 类章节包含 ≥ 2 种 analysis_intent
- [ ] 任意两个章节的 (metric_focus, group_by) 组合无完全重叠

---

> **下一步**：D.1 验证通过后启动 **D-2 内容深化**（章节模板库 + 二维分析），详见 `optimize_report_quality_V1_batch_D2_content_deepening.md`。
