# 批次 A — 数据真实性修复 实施方案

> **状态**：待实施 | **父文档**：`spec/optimize_report_quality_V1.md` | **预计工时**：3.5 天
>
> **依存关系**：A.0 必须先于 A.1（KPI 真值需要 dataset 可查）；A.2/A.3 可与 A.1 并行。基准文档中有 Batch B/C/D 的实施详情，本文件仅聚焦 Batch A。

---

## 0. 背景与目标

### 0.1 本批次要解决的问题

从完整 spec 的 5 大症状中，本批次解决以下问题：

| 症状 | 根因编号 | 本批次覆盖 |
|---|---|---|
| KPI 卡数字与图表数据完全脱节 | R1：LLM 自由编造，无 SQL 约束 | A.1 全数字走 `source_asset_id` 强约束 |
| 同环比增长率严重不合理（↑780%） | R2：双重单位转换 + LLM 直接吐百分点 | A.2 单位口径契约 + sanity validator |
| 字段名泄露（`firstLevelName_起重机械`） | R6：无字段显示名映射 | A.3 字段语义命名层 |
| Dataset 丢失，无法事后审计 | 持久化缺陷 | A.0 前置：dataset 持久化 |

### 0.2 目标

实现"可信"报告的基础层：**报告中每个数据 block（KPI 卡 / 表 / 图 / 增长率 / 归因表）都必须可见地标注来源 API**，肉眼可追溯到具体 endpoint。粒度是 block 级（每张表 / 每张图 / 每个 KPI 一个来源标注）。

---

## 1. 前置：A.0' 数据健康度基线（已完成）

> 脚本 `tools/endpoint_health_audit.py` 已落地，输出 `data/endpoint_health.json`（344 KB）。A.0 启动前完成以下注册表同步。

### 1.1 Registry 同步动作

**从 `data/api_registry.json` 移除 14 个已注册 D 级端点**（数据为空或全 0）：

| Domain | 端点 | 数据情况 |
|---|---|---|
| D5 | `getOriginalValueDistribution` | 0 行 |
| D5 | `getMainAssetsInfo` | 0 行 |
| D5 | `getRealAssetsDistribution` | 0 行 |
| D5 | `getTotalssets` | 1 行 |
| D6 | `getPlanFinishByZone` | 5 行全 0 |
| D3 | `getCurContributionRankOfStrategicCustomer` | 37 行全 0 |
| D3 | `getCurStrategicCustomerContributionByCargoTypeThroughput` | 4 行全 0 |
| D3 | `getSumContributionRankOfStrategicCustomer` | 37 行全 0 |
| D3 | `getSumStrategicCustomerContributionByCargoTypeThroughput` | 4 行全 0 |
| D4 | `getBusinessExpirationInfo` | 0 行 |
| D4 | `getMeetDetail` | 0 行 |
| D4 | `getNewEnterprise` | 0 行 |
| D4 | `getSupervisorIncidentInfo` | 0 行 |
| D4 | `getWithdrawalInfo` | 0 行 |

**补注册 2 个误判的 A/B 级端点**：

| 端点 | Domain | Grade | 行数 |
|---|---|---|---|
| `getCostProjectFinishByYear` | D6 | A | 2 |
| `getCostProjectCurrentStageQtyList` | D6 | B | 16 |

**净变化**：141 → **129** 个端点，全部 grade ∈ {A, B}。§2.4 不变式成立。

执行命令：
```bash
python tools/sync_registry.py --remove  # 移除 D 级端点
# 手动编辑 data/api_registry.json 补注册 2 个端点
python tools/seed_api_endpoints.py      # 推送到 DB
```

---

## 2. A.0 — Dataset 持久化（0.5 天）

### 2.1 问题

当前 `execution_report.json` 只存任务元数据（`task_id` / `type` / `rows` / `elapsed_seconds` / `tokens`），**不存原始 dataset**。dataset 只在内存/临时目录存活，报告生成完毕即丢失。

### 2.2 改动

| 文件 | 改动 |
|---|---|
| `backend/tools/report/_content_collector.py` | 收集 raw items 时，每个 task 的 dataframe 落盘为 JSON（`pd.to_json(orient="records")`），路径 `data/reports/{date}/{report_id}/datasets/{task_id}.json`；同目录写 `{task_id}.meta.json` |
| `backend/tools/report/_outline.py` | `ChartAsset` / `TableAsset` / `StatsAsset` 新增 `dataset_path: str \| None` 字段 |
| `backend/tools/report/_outline_planner.py` | 传给 LLM 的 `assets_summary` 增加 `dataset_path` + `endpoint_grade` 字段 |

**meta.json 格式**：

```json
{
  "audit": {
    "endpoint_id": "getEquipmentUsageRate",
    "params_sent": {"dateMonth": "2026-03", "ownerLgZoneName": "大连港"},
    "fetched_at": "2026-05-06T10:30:00+08:00",
    "latency_ms": 234
  },
  "quality_flags": ["P0_NO_VARIANCE", "P1_NAME_VS_INTENT"],
  "endpoint_grade": "C",
  "lineage": {
    "row_count": 6,
    "column_hash": "a1b2c3d4",
    "row_hashes": ["e5f6", "g7h8", "..."]
  }
}
```

- `quality_flags`：基于 `data/endpoint_health.json` 该 endpoint 的 warnings 列表 + 运行时 `_metric_sanity.py` 检查结果，用于 C 级数据降级展示
- `endpoint_grade`：A / B / C（D 级已从 registry 移除，不会出现）

**配套新增** `backend/tools/analysis/_metric_sanity.py`：定义每个指标的合理区间（如 `usageRate ∈ [0, 1] ∪ [0, 100]`，设备数量 ≥ 50），运行时检测后产出 `quality_flags`，与预计算的 `endpoint_health.json` 互补。

### 2.3 验收

- [ ] 14 个 D 级端点已从 `data/api_registry.json` 移除（grep 验证）
- [ ] 报告生成完毕后，`data/reports/.../datasets/` 目录存在每个 task 的 `{task_id}.json` + `{task_id}.meta.json`
- [ ] 数据集文件可读：`cat T001.json` 直接看到 API 返回的原始数据（与 prod_data 快照格式一致）
- [ ] 渲染层能根据 KPI 的 `source_asset_id` 反查到原始 dataframe + quality_flags
- [ ] meta.json 中 `endpoint_grade` 不会出现 "D"

---

## 3. A.1 — 数据 block 走 source_asset_id 强约束（2 天）

### 3.1 范围

约束**所有承载数字的 block**（KPI 卡 / table / chart / growth_indicators / synthesised_assets 共 5 类）。粒度是 block 级，不是 cell 级。一份报告大约 15-30 个 source 标注。

**关键原则**：让 LLM 选 endpoint，错了通过调 prompt 或 endpoint 候选清单纠正。不写硬 fallback chain。

### 3.2 Schema 扩展

**文件**：`backend/tools/report/_outline.py`

| 类型 | 改动 |
|---|---|
| `KPIItem` | 新增 `source_asset_id: str` **必填**、`agg: str \| None`（latest/mean/sum/yoy/qoq）、`format_spec: str \| None`（percent/int/currency/raw）|
| `GrowthIndicatorsBlock` | `growth_rates: dict` 改为 `growth_rates: dict[str, GrowthCell]`；新建 `GrowthCell = {yoy: float \| None, mom: float \| None, source_asset_id: str}` |
| `ChartAsset` / `TableAsset` / `StatsAsset` | A.0 已新增 `dataset_path: str \| None` |
| `TableAsset`（归因表用） | 新增 `source_asset_ids: list[str]`（多源声明，仅 synthesised 时填）。**数据依据列是 LLM 描述性文本，不做数值注入** |

### 3.3 Prompt 约束

**文件**：`backend/tools/report/_planner_prompts.py`

在现有 `_OUTPUT_SCHEMA_DOC` 之后追加：

```
## 数据溯源严格规则（PR-3 新增）
- 每个数据 block（KPI / table / chart / growth_indicators / synthesised_assets）必须有 source_asset_id
- source_asset_id 必填，引用必须存在于「可用 assets」（多源合成的归因表用 source_asset_ids 列表）
- value/数字 字段不要自己写，留给后端填充
- 你只负责选 (label, source_asset_id, agg, format_spec) 四元组
- 选错 endpoint 是允许的 — 后续通过调 prompt 或 endpoint 候选清单纠正
- 但编数字、缺溯源、引用不存在的 asset_id 不允许
```

### 3.4 注入流程

**注入位置**：在 `plan_outline()` 内，紧跟 `_deduplicate_chart_blocks(outline)` 之后、`return outline` 之前，新增独立函数 `_inject_values()`。

**为什么不在 `_block_from_response()` 内部注入？** —— 关注点分离：构造阶段只做 dict → dataclass 翻译；注入阶段独立处理"按 source_asset_id 反查 dataset → 算真值 → 格式化 → 写回"。注入函数可独立单元测试。

```python
# backend/tools/report/_outline_planner.py
async def plan_outline(...):
    ...
    outline = _build_outline_from_response(...)
    _deduplicate_chart_blocks(outline)
    _inject_values(outline, assets_by_id)   # ← 新增单步
    return outline


def _inject_values(outline: ReportOutline, assets_by_id: dict[str, Asset]) -> None:
    """LLM 输出解析完成后、返回前的值注入。修改 mutable dataclass 的 value 字段."""
    for section in outline.sections:
        for block in section.blocks:
            if isinstance(block, KpiRowBlock):
                for item in block.items:
                    asset = _resolve_asset(item.source_asset_id, assets_by_id)
                    raw = compute_agg(pd.read_json(asset.dataset_path, orient="records"), item.agg)
                    item.value = format_value(raw, item.format_spec)

            elif isinstance(block, GrowthIndicatorsBlock):
                for col, cell in block.growth_rates.items():
                    asset = _resolve_asset(cell.source_asset_id, assets_by_id)
                    cell.yoy, cell.mom = compute_growth(pd.read_json(asset.dataset_path, orient="records"), col)

            elif isinstance(block, (TableBlock, ChartBlock)):
                pass  # 数据来自 Asset.df_records / Asset.option，渲染层自取

            elif _is_attribution_block(block, assets_by_id):
                # 归因表"数据依据"列是 LLM 描述性文本，不注入数值
                _validate_attribution_sources(block, assets_by_id)


def _is_attribution_block(block, assets_by_id) -> bool:
    """归因表 = TableBlock + 引用一个 synthesised TableAsset.

    判定依据：BlockKind 不新增 attribution 这个 kind；归因表复用 table。
    通过查 asset 的 source_asset_ids 是否非空来识别（synthesised TableAsset 才有此字段）。
    """
    if not isinstance(block, TableBlock):
        return False
    asset = assets_by_id.get(block.asset_id)
    return asset is not None and bool(getattr(asset, "source_asset_ids", None))


def _resolve_asset(asset_id, assets_by_id):
    asset = assets_by_id.get(asset_id)
    if not asset:
        raise ValidationError(f"引用了不存在的 asset_id: {asset_id}")
    if not asset.dataset_path:
        raise ValidationError(f"asset {asset_id} 缺少 dataset_path（A.0 未完成？）")
    return asset
```

### 3.5 格式化

新增 `backend/tools/report/_value_format.py`：

| format_spec | 输入 | 输出 |
|---|---|---|
| `percent` | 0.764 | "76.4%" |
| `percent_signed` | -0.018 | "-1.8%" |
| `int` | 47.0 | "47" |
| `int_with_unit` | 47.0 | "47 次"（unit 由 prompt 给）|
| `currency` | 18650.0 | "¥18,650" |
| `large_number` | 339192779.15 | "3.39 亿" |
| `raw` | 76.4 | "76.4" |

渲染层直接读 `item.value` 字符串，不再做数值转换。

### 3.6 渲染层标注

从 `block.asset_id / item.source_asset_id → assets[id].endpoint` 直接拿来源名。三格式同步：

- **KPI 卡底部小字**：`源: {asset.endpoint}`
- **表格脚注**：`数据来源：{asset.endpoint}（取自 {asset.fetched_at}）`
- **图表 caption 下方**：同上
- **增长率 KPI**：每个 metric 旁 `源: {asset.endpoint}`
- **归因表"数据依据"列**：LLM 文本里直接含 endpoint 名（validator 保证 ⊆ source_asset_ids）
- **HTML 可点击展开**：source 文本 → tooltip 显示 `params_sent + fetched_at + dataset_path`

**quality_flag 警示**（数据来自 A.0 写入的 meta.json）：

| Flag | 渲染行为 |
|---|---|
| `P0_NO_VARIANCE` | 数据卡角加 ⚠️ + tooltip "该指标无月度方差，仅展示当期值" |
| `P0_RANGE_RATE` / `P1_QUANTITY_LOW` | 数字后加 ⚠️ + tooltip "数据可疑，请核对单位口径" |
| `P1_NAME_VS_INTENT` | 字段标签自动用映射后的业务名 |

### 3.7 Validator 重试

| 触发条件 | 行为 | 上限 |
|---|---|---|
| 任意承载数字的 block 缺 `source_asset_id` | 重试 LLM | 3 次 |
| `source_asset_id` 不在 assets 中 | 重试 LLM | 3 次 |
| `_inject_values()` 抛 `ValidationError` | 重试 LLM | 3 次 |
| 归因表"数据依据"列出现的 endpoint 名 ⊄ source_asset_ids | 重试 LLM | 2 次 |
| 重试超限 | 该 block 不渲染（**不显示假数字**）| — |

**全局上限**：整份 outline 重生成累计 ≤ 6 次。达到后未通过的 block 直接降级。

### 3.8 验收

- [ ] `Asset` / `KPIItem` / `GrowthCell` schema 扩展通过单元测试
- [ ] `_inject_values()` 单元测试覆盖 5 种 block kind 的注入路径
- [ ] 报告 HTML/DOCX/PPTX 每个数据 block 旁可见来源 endpoint 名
- [ ] 报告内 KPI/图表/表格数字之间一致（差值 < 0.1%）
- [ ] 错的 endpoint 选择能通过"看哪个 endpoint 数字诡异 → 调 D.3 章节模板的 endpoint 候选 → 重生成"的闭环修复

---

## 4. A.2 — 同环比单位口径 + Sanity Validator（0.5 天）

> `GrowthCell` schema 改造已合并到 A.1。本节仅保留"小数 vs 百分点契约 + sanity validator"。

### 4.1 问题

`growth_indicators` block 的 `yoy: float / mom: float` 字段，LLM 可输出 `0.078` 也可输出 `7.8`，下游渲染层又乘 100 → 出现 ↑780%。

### 4.2 改动

**1. 单位口径契约**（在 `_planner_prompts.py` 注释顶部固化）：

- 全链路 `GrowthCell.yoy` / `GrowthCell.mom` 统一为**小数形式**（-1.0 ~ 1.0 为常态区间）
- **渲染层在末端 ×100 + 加 `%`**，三个 renderer（HTML/DOCX/PPTX）只在最末端做一次转换，禁止任何中间层做单位转换
- LLM **不允许**输出数值（A.1 已强制走后端注入）

**2. 后端预算 growth assets**（`_content_collector.py`）：

对所有 numeric 列预算同环比并写入 dataset，作为 stats asset 注入 `assets_summary`。优先调用 D2/D7 的 YoY 专用端点，找不到时本地算。

**3. Sanity validator**：

`_inject_values()` 注入完成后扫描所有 `GrowthCell`：`abs(yoy) > 2.0` 或 `abs(mom) > 2.0` → 视为异常，重试 LLM 让它换数据源。重试 3 次仍异常 → 该 growth_indicator block 不渲染。

### 4.3 验收

- [ ] 报告中所有同环比数字绝对值 ≤ 200%（除非数据本身极端）
- [ ] 单位口径文档化在 `_planner_prompts.py` 注释顶部
- [ ] HTML/DOCX/PPTX 三 renderer 中"小数 ×100 加 %"只出现一次（grep 验证）

---

## 5. A.3 — 字段语义命名层（0.5 天）

### 5.1 问题

KPI 显示 `firstLevelName_起重机械`、表头叫"数量"配"成本"标题。尤其注意 CQ-5：`usageRate` 字段实际承载 MTBF 数据（小时数），映射必须支持 `(field, endpoint_id) → display_name` 二元 key，**不能只看字段名**。

### 5.2 改动

**1. 扩展字段映射文件**：`backend/tools/report/_field_labels.py`

```python
FIELD_DISPLAY_NAMES = {
    # 按字段名映射
    "firstLevelName": "设备一级分类",
    "secondLevelName": "机种",
    "ownerLgZoneName": "港区",
    "serviceableRate": "完好率",
    "machineHourRate": "机时效率",
    # 多义字段按上下文映射
    "num": {
        "default": "数量",
        "fault": "故障次数",
        "cost": "成本(元)",
        "throughput": "吞吐量(吨)",
    },
}

# 按 (field_name, endpoint_id) 二元 key 的特殊映射（CQ-5 应对）
ENDPOINT_SPECIFIC_LABELS = {
    ("usageRate", "getMachineDataDisplayEquipmentReliability"): "MTBF",
    ("usageRate", "getNonContainerProductionEquipmentReliability"): "MTBF",
}

# 字段别名表（CQ-6 应对：同一概念不同字段名）
FIELD_ALIASES = {
    "firstLevelName": "firstLevelClassName",
    "secondLevelName": "secondLevelClassName",
}
```

**2. 多义字段消歧**：在 task 元数据里增加 `semantic_context` 标签（如 `cost`/`fault`/`throughput`），渲染层按 context 选名字。

**3. 改动位置**：

- `_block_renderer.py`：表头/坐标轴/legend 全部走 `field_labels.resolve(field, context, endpoint_id)`
- `_outline_planner.py`：传给 LLM 的 `assets_summary` 中的字段名先做映射

### 5.3 验收

- [ ] 整份报告无任何 `firstLevelName_xxx`、`*_yoy`、`secondLevelName_xxx` 形式的字段名
- [ ] "成本"章节的表头读起来是"成本/元"而不是"数量"
- [ ] MTBF 指标显示为"MTBF"而非"利用率"（CQ-5）

---

## 6. 文件清单

| 文件 | 改动概要 |
|---|---|
| `data/api_registry.json` | **A.0 前置**：移除 14 个 D 级 + 补注册 2 个 A/B 级 |
| `backend/tools/report/_content_collector.py` | A.0: dataset 持久化（`{task_id}.json` + `{task_id}.meta.json` + dataset_path/quality_flags/endpoint_grade）；A.2: growth assets 预算 |
| `backend/tools/report/_outline.py` | A.1: `KPIItem` 加 `source_asset_id/agg/format_spec`；`GrowthIndicatorsBlock.growth_rates` 改为 `dict[str, GrowthCell]`；新增 `GrowthCell`；`ChartAsset/TableAsset/StatsAsset` 加 `dataset_path`；`TableAsset` 加 `source_asset_ids` |
| `backend/tools/report/_outline_planner.py` | A.1: 新增 `_inject_values()` |
| `backend/tools/report/_value_format.py` | A.1 **新增**：KPI value 格式化 |
| `backend/tools/report/_planner_prompts.py` | A.1/A.2: 数据溯源规则 + 单位口径契约 |
| `backend/tools/report/_field_labels.py` | A.3: `(field, endpoint_id) → label` 二元 key + alias 表 |
| `backend/tools/analysis/_metric_sanity.py` | A.0 **新增**：指标合理区间表（usageRate ∈ [0,1] ∪ [0,100] 等），运行时输出 quality_flags |
| `backend/tools/report/_renderers/htmlgen.py` | A.1/A.2: 数据来源标注 + quality_flag 警示 + 单位末端 ×100 |
| `backend/tools/report/_renderers/docxgen.py` | A.1/A.2: 同上 |
| `backend/tools/report/_renderers/pptxgen.py` | A.1/A.2: 同上 |

---

## 7. 验收标准

- [ ] **每个数据 block（KPI 卡 / 表 / 图 / 增长率 / 归因表）旁可见来源 endpoint 名**
- [ ] 任意 KPI 卡的数字与下方图表/表格的真值一致（差值 < 0.1%）
- [ ] 任意同环比绝对值 ≤ 200%
- [ ] 整份报告无 `firstLevelName_xxx` / `*_yoy` 等字段名泄露
- [ ] 报告生成完毕后 datasets/ 目录有完整 `{task_id}.json` 留存
- [ ] 同一图表 / 表格的 `source_asset_id` 唯一（不跨 endpoint 合表；归因表例外用 source_asset_ids）
- [ ] 任意 KPI 数字都有 audit trail 可反查到 (endpoint, params, fetched_at, agg_func)
- [ ] 渲染前对每个 dataset 自动跑健康度检查（null 比例 / 方差 / 行数），3 类风险（null/empty/range）有 fallback（不渲染假数字）
- [ ] 关键 endpoint（A/B/C 级）健康度看板每日刷新（基于 `tools/endpoint_health_audit.py`）

---

> **下一步**：A.0/A.1 完成后开启批次 C（PPTX 渲染修复）或批次 D（分析深度）。详见父文档 `optimize_report_quality_V1.md` §7 实施顺序。
