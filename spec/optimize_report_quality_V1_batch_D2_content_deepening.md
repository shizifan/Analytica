# 批次 D-2 — 内容深化 实施方案（含 D.3 + D.4）

> **状态**：待实施 | **父文档**：`spec/optimize_report_quality_V1.md` | **预计工时**：3 天 | **包含子项**：D.3 章节模板库（1 天）+ D.4 二维 Crosstab + Anomaly + Comparison（2 天）
>
> **依存关系**：依赖 D-1（跨域基础）验证通过。D.3 完成后才解锁批次 B（section 匹配），因为 B 的匹配规则依赖 `required_intents` 字段。D.4 可与其他并行。

---

## 0. 背景与目标

### 0.1 本批次要解决的问题

在 D-1 建立跨 domain 调用链后，还需解决内容深度不足的问题：

| 症状 | 根因 | 本批次覆盖 |
|---|---|---|
| LLM 自由选择 endpoint 导致章节内容随机、分析视角单一 | 缺模板约束 | D.3 章节模板库 |
| `group_by` 只支持单维，无 anomaly/comparison 能力 | R5：analysis 任务类型只有 1 个口袋 | D.4 二维 crosstab + anomaly + comparison |

### 0.2 目标

- **固化的章节结构**：每种报告类型有规范的章节模板，约束 endpoint 候选清单和分析意图
- **新增分析能力**：二维透视、异常检测、多类型对比

---

## 1. D.3 — 章节模板库（1 天）

### 1.1 问题

LLM 自由选择 endpoint 导致章节内容随机、分析视角单一。需要为每种报告类型提供规范的章节模板，约束 endpoint 候选清单。

### 1.2 新增 `backend/tools/report/_section_templates.py`

以设备运营报告为例（7 章节模板）：

```python
EQUIPMENT_OPS_SECTIONS = [
    {
        "name": "运营总览",
        "role": "summary",
        "metric_focus": ["usageRate", "serviceableRate", "throughput"],
        "required_intents": [AnalysisIntent.YOY_COMPARE],
        "endpoint_candidates": {
            "primary": ["getSumBusinessDashboardThroughput"],
            "secondary": ["getEquipmentUsageRate", "getEquipmentServiceableRate"],
        },
    },
    {
        "name": "时间趋势",
        "role": "analysis",
        "metric_focus": ["usageRate", "throughput", "faultNum"],
        "required_intents": [AnalysisIntent.SINGLE_METRIC_TREND, AnalysisIntent.CORRELATION],
        "endpoint_candidates": {
            "primary": ["getProductEquipmentUsageRateByMonth",
                       "getProductEquipmentReliabilityByMonth"],
            "context": ["getThroughputAnalysisByYear"],
        },
    },
    {
        "name": "设备结构分析",
        "role": "status",
        "metric_focus": ["secondLevelName", "firstLevelClassName"],
        "required_intents": [AnalysisIntent.BREAKDOWN_BY_DIM, AnalysisIntent.TOP_N],
        "endpoint_candidates": {
            "primary": ["getProductionEquipmentStatistic"],  # 39 行机种数量（仅含 num，不做利用率排行）
            "secondary": ["getEquipmentFirstLevelClassNameList",
                         "getEquipmentFacilityStatusAnalysis"],
        },
    },
    {
        "name": "设备成本分析",
        "role": "analysis",
        "metric_focus": ["originalValue", "useCost", "fuelCost", "electricityCost"],
        "required_intents": [
            AnalysisIntent.SINGLE_METRIC_TREND,
            AnalysisIntent.YOY_COMPARE,
            AnalysisIntent.BREAKDOWN_BY_DIM,
        ],
        "subsections": [
            {
                "name": "资产视角",
                "endpoint_candidates": ["getEquipmentFacilityAnalysisYoy",
                                        "getEquipmentFacilityAnalysis"],
                "groupby_field": "assetTypeName",
            },
            {
                "name": "运营消耗视角",
                "endpoint_candidates": ["getEquipmentIndicatorUseCost",
                                        "getEquipmentElectricityTonCost"],
                "groupby_field": "firstLevelName",
            },
            {
                "name": "投资因果视角",
                "endpoint_candidates": ["getCostProjectFinishByYear"],
                "groupby_field": "dateYear",
            },
        ],
        "diff_note": "本章节三个视角的分类口径不一致（assetTypeName / firstLevelName / dateYear），不跨视角合表对照",
    },
    {
        "name": "故障特征分析",
        "role": "attribution",
        "metric_focus": ["faultNum", "MTBF", "MTTR"],
        "required_intents": [
            AnalysisIntent.SINGLE_METRIC_TREND,
            AnalysisIntent.BREAKDOWN_BY_DIM,
            AnalysisIntent.ANOMALY_DETECT,
        ],
        "endpoint_candidates": {
            "primary": ["getProductionEquipmentFaultNum"],
            "secondary": ["getEquipmentFacilityStatusAnalysis"],
            "context": ["getRealTimeWeather"],
        },
    },
    {
        "name": "业务-设备联动",
        "role": "analysis",
        "metric_focus": ["shipEfficiency", "machineHourRate", "throughput"],
        "required_intents": [AnalysisIntent.CORRELATION, AnalysisIntent.SINGLE_METRIC_TREND],
        "endpoint_candidates": {
            "primary": ["getContainerMachineHourRate"],
            "secondary": ["getProductViewShipOperationRateAvg", "getBerthOccupancyRateByRegion"],
        },
    },
    {
        "name": "可靠性专项",
        "role": "analysis",
        "metric_focus": ["MTBF", "MTTR", "faultNum"],
        "required_intents": [AnalysisIntent.TOP_N, AnalysisIntent.BREAKDOWN_BY_DIM],
        "endpoint_candidates": {
            "primary": ["getMachineDataDisplayEquipmentReliability",
                       "getNonContainerProductionEquipmentReliability"],
        },
        # 这两个端点的 usageRate 实际是 MTBF，必须配合 A.3 字段映射
    },
]
```

> 完整端点 grade 标记详见父文档 §附录 C。

### 1.3 章节模板与 perception 联动 — Section schema 传递链

章节模板的字段需跨 4 个阶段传递：`planning → execution → content_collector → outline_planner`。**统一通过 `report_structure.sections[*]` 的 dict schema 扩展**承载，不新增 `plan_outline()` 参数。

**新 sections schema**（`backend/agent/planning.py` 产出，D.1 已定义）：

```python
class SectionSpec(BaseModel):
    name: str
    role: Literal["summary", "status", "analysis",
                  "attribution", "recommendation", "appendix"]
    focus_metrics: list[str] = []                   # D.1 注入
    domain_hint: str | None = None                  # D.1 注入
    endpoint_hints: list[str] = []                  # D.1 注入
    required_intents: list[AnalysisIntent] = []     # D.3 注入
    endpoint_candidates: dict[str, list[str]] = {}  # D.3 注入
    subsections: list["SubsectionSpec"] | None = None  # D.3 注入
    diff_note: str | None = None                    # D.3 注入
```

**传递链各阶段责任**：

| 阶段 | 文件 | 责任 |
|---|---|---|
| planning | `planning.py PLANNING_PROMPT` | 识别 ReportType → 加载章节模板 → 写入 `report_structure.sections[*]` 全字段 |
| planning | `planning.py _stitch_plan` | **完整透传** sections 全字段（不只 name） |
| planning | `planning.py _sanitize_report_structure` | 白名单清洗，**保留** D.1/D.3 注入的所有字段 |
| execution | execution layer | 把 `report_structure` 透传给 content_collector |
| content_collector | `_content_collector.py _associate()` | 按 `focus_metrics × endpoint_candidates × required_intents` 做强匹配（batch B） |
| outline_planner | `_outline_planner.py plan_outline()` | LLM 不能自由选 endpoint，必须从候选清单选 |

**schema 演化兼容**：旧字段（只有 name）的 section 视为退化模式，行为与实施前一致。

### 1.4 跨 domain 拼接策略

多个 endpoint 的字段维度对不上时（如 D5 的 `assetTypeName` 与 D7 的 `firstLevelName` 是不同的设备分类标准），**禁止跨 endpoint 合表**。改用：

- **subsections 并列**：章节内分子节，每个 endpoint 一个子节独立成图/表
- **diff_note 显式说明**：章节末尾用 callout 明示口径差异
- **chart_table_pair 不混用**：图与表必须来自同一 endpoint

渲染层 + validator 配合：
- validator 检测同一 chart/table 的 `source_asset_id` 唯一性 → 多于一个直接重试
- 渲染层在每个子节标题处显示"按 {groupby_field} 分组（来源：{endpoint}）"
- 归因表如确需引用多 endpoint，必须在"数据依据"列分别列出 endpoint 名

---

## 2. D.4 — 二维 Crosstab + Anomaly + Comparison（2 天）

### 2.1 二维 crosstab（0.5 天）

**改动**：

- `backend/tools/analysis/descriptive.py:73-79`：`group_by` 接受 `List[str]`，输出 pandas pivot
- `backend/tools/report/_chart_renderer.py`：新增 heatmap / stacked bar / grouped bar 路由
- prompt 中明示 `crosstab_2d` intent 的产出格式

### 2.2 Anomaly 实装（0.5 天）

**问题**：`backend/tools/analysis/anomaly.py` 当前是占位。

**改动**：

- 实装 z-score（默认，threshold=2.0）和 IQR（备选）
- 接受 `(dataframe, metric, group_by, threshold=2.0)`，输出"异常时段/异常组"列表
- 在归因表中作为"数据依据"列引用

> z-score 阈值 2.0 对港口数据可能不合适，实施 D.4 时按 metric 设阈值表（详见父文档 §附录 I.2 待定问题 8）。

### 2.3 Comparison 模块新增（1 天）

**新增** `backend/tools/analysis/comparison.py`，三个核心函数：

- `yoy_compare(df, metric, time_col)`：跨期对比
- `cross_group_compare(df, metric, group_col)`：跨组对比
- `target_vs_actual(df, target_col, actual_col)`：计划 vs 实际

优先复用 D2 的 YoY 专用端点结果，避免重复计算。

---

## 3. 文件清单

| 文件 | 改动概要 |
|---|---|
| `backend/tools/report/_section_templates.py` | D.3: **新增** 章节模板库 |
| `backend/tools/report/_outline_planner.py` | D.3: 章节模板加载 |
| `backend/tools/analysis/descriptive.py` | D.4: 二维 group_by |
| `backend/tools/analysis/anomaly.py` | D.4: 实装 z-score / IQR |
| `backend/tools/analysis/comparison.py` | D.4: **新增** YoY/跨组/计划实际 |
| `backend/tools/report/_chart_renderer.py` | D.4: heatmap / stacked bar 路由 |

---

## 4. 验收标准

- [ ] 归因表的每行"数据依据"列引用的 asset_id 可在报告内找到对应图表
- [ ] "设备结构分析"章节配图为机种透视/状态分布/类型构成（不再配月份折线图）
- [ ] "设备成本分析"章节包含资产视角（D5）+ 消耗视角（D7）+ 投资视角（D6）
- [ ] 多 endpoint 视角并列的章节末尾有 `diff_note` 说明口径差异

---

> **下一步**：D.3 完成后启动 **批次 B**（Section ↔ Dataset 强匹配），因为 B 的匹配规则依赖 D.3 的 `required_intents` 字段。详见 `optimize_report_quality_V1_batch_B_section_matching.md`。
