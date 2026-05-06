# 报告质量优化 V1 — 数据期刊方案的下一轮迭代

> **状态**：待评审 | **起草日期**：2026-05-05 | **作者**：Analytica 团队
>
> **关联前置**：`liangang_journal_design_plan.md`（PR-4 数据期刊视觉方案，已完成）
> **关联并行**：`optimize_multiturn_conversationV3.md`（多轮对话 PR-1，已合入 master）
>
> **拆分实施方案**（按批次独立推进，降低上下文长度）：
> - [批次 A — 数据真实性修复](./optimize_report_quality_V1_batch_A_data_authenticity.md)（3.5 天）
> - [批次 B — Section ↔ Dataset 强匹配](./optimize_report_quality_V1_batch_B_section_matching.md)（2.5 天，依赖 D-2 的 D.3）
> - [批次 C — PPTX 渲染层 Patch](./optimize_report_quality_V1_batch_C_pptx_render.md)（1 天，可与 A 并行）
> - [批次 D-1 — 跨域基础](./optimize_report_quality_V1_batch_D1_cross_domain_foundation.md)（3.5 天，依赖 A.0）
> - [批次 D-2 — 内容深化](./optimize_report_quality_V1_batch_D2_content_deepening.md)（3 天，依赖 D-1 验证通过）

---

## 0. 背景与目标

### 0.1 现状

PR-4 完成"辽港数据期刊"方案后，三种格式的产出现状：

- **HTML**：视觉/排版升级明显（数据期刊感、KPI 卡、章节封面、衬线 + 等宽混排）
- **DOCX**：结构干净，可读性合格
- **PPTX**：仍存在严重排版问题（一项分析散落到 4 张 slide、附录整段重复、信息密度低）

但贯穿三种格式的**内容质量问题**已暴露，且与"漂亮模板"形成强烈反差：

1. KPI 卡数字与下方图表数据完全脱节（KPI "76.4%" / 图表 "99.8%/97%/98.55%"，KPI "47 次" / 图表 "1406/1320/662"）
2. 同环比增长率严重不合理（↑780% / ↑320% / ↑420%）
3. 章节↔图表语义错位（"设备结构分析"配月份折线图）
4. 多个章节渲染相同数据（运营总览 + 时间趋势两章画同一条线）
5. 分析单薄（归因表说"专用机械故障频发"但全报告无任何按设备类型的故障数据）

### 0.2 目标

从"漂亮模板"升级为"**可信、有深度、跨域**的分析报告"：

- **可信**：报告中**每个数据 block**（KPI 卡 / 表 / 图 / 增长率 / 归因表）都必须**可见地标注来源 API**，肉眼可追溯到具体 endpoint。粒度是 block 级（每张表 / 每张图 / 每个 KPI 一个来源标注，不是每个 cell 都标）；多源合成的归因表用 source_asset_ids 列出多个 endpoint。错的数字能立刻定位到错的 endpoint 选择，由后续调提示词或 endpoint 候选清单解决，**不在 spec 里穷举字段映射表**。
- **有深度**：每个章节至少 2-3 个分析视角（趋势 + 下钻 + 对比），归因表的每个结论都有数据支撑
- **跨域**：单份报告横跨 3-5 个 domain（D1 业务 + D5 资产 + D6 投资 + D7 设备），不再"自言自语"。**两个 endpoint 字段对不上时不强行合表**，按 endpoint 分别展示并显式说明口径差异

### 0.3 不在范围

- 报告分发（邮件/订阅/推送）
- 版本管理与协同编辑
- 多模型 ensemble 生成（仍用单 LLM 调用）
- 前端 KPI 独立组件（按需扩展，本 spec 不覆盖）

---

## 1. 诊断

### 1.1 三格式症状对照

| 维度 | HTML | DOCX | PPTX |
|---|---|---|---|
| 视觉/排版 | ✅ 已升级到期刊感 | ✅ 干净 | ❌ 章节散落 4 页/末尾整段重复 |
| KPI 与图表数据一致性 | ❌ | ❌ | ❌ |
| 同环比数值合理性 | ❌ ↑320%/↑780% | ❌ 同上 | ❌ 同上 |
| 章节↔图表语义匹配 | ❌（设备结构章配月份图） | ⚠️ | ❌ |
| 章节差异化 | ❌（前 2 章画同一条线） | ❌ | ❌ |
| 分析维度覆盖 | ⚠️ 仅按月，缺按设备类型/港区下钻 | ⚠️ 同上 | ⚠️ 同上 |

### 1.2 根因层定位

| # | 症状 | 根因 | 代码位置 |
|---|---|---|---|
| R1 | KPI 是假数 | LLM 自由编造，无 SQL 约束 | `backend/tools/report/_outline_planner.py:475-487` 直接吃 `parsed.get("kpi_summary", [])`；`_planner_prompts.py:13-46` prompt 无数据约束 |
| R2 | 同环比 ↑780% | 双重单位转换：`descriptive.py` 返回小数（0.078），`pptxgen.py:814-845` 又乘 100；中间 LLM 可能直接吐百分点 | `backend/tools/analysis/descriptive.py:102-178`、`backend/tools/report/_renderers/pptxgen.py:814-845` |
| R3 | 章节↔图表错位 | section 与 dataset 是轮询兜底分配，task_refs 未覆盖时按 task_id 轮询塞给 section | `backend/tools/report/_content_collector.py:299-382` `_associate()` 函数 Line 370-381 |
| R4 | 跨章节同图 | LLM 一次性规划所有 section，无差异化逻辑保证每 section 拿到不同 metric | `backend/tools/report/_outline_planner.py:107-146` |
| R5 | 分析单薄 | analysis 任务类型只有 1 个口袋，无 intent 细分；`group_by` 只支持单维 | `backend/models/schemas.py:90-92` TaskType 枚举；`backend/tools/analysis/descriptive.py:73-79` |
| R6 | 字段名泄露 | KPI/表头出现 `firstLevelName_起重机械`、列名"数量"配"成本"标题，无字段显示名映射 | 无统一映射层 |
| R7 | PPTX 散落 | 硬编码每 section 强制生成 chart + narrative + growth KPI + stats 共 3-4 张 slide | `backend/tools/report/_renderers/pptxgen.py:968-992` `_render_section_combo()` |
| R8 | PPTX 末尾重复 | `_flush_appendix_deck()` 被触发 2 次（结语前后各一次），无幂等标记 | `backend/tools/report/_renderers/pptxgen.py:878-891` |

### 1.3 现网真实数据取样（实证）

抽 3 个最近的报告生成会话验证假设：

| 会话 | 任务总数 | data_fetch | analysis | viz | report_gen | LLM tokens | 跨 domain |
|---|---|---|---|---|---|---|---|
| `throughput_analyst_monthly_review` (20260421_104336) | 18 | 10 | 3 | 3 | 2 | 5,395 | ❌ 单 domain |
| `asset_investment_equipment_ops` (20260421_112459) | 18 | 15 | 3 | 1 | — | 0（attribution 失败）| ❌ 单 domain |
| `throughput_analyst_monthly_review` (20260421_112459) | 10 | 10 | 0 | 0 | 0 | 0 | ❌ 单 domain |

**关键验证结论**（基于真实数据，非推断）：

| 假设 | 真实情况 |
|---|---|
| 任务数 4-8 个 | ❌ 实际 10-18 个，不是数量不够 |
| 跨 domain 调用 | ✅ 实际 = 0，所有任务集中单一 domain |
| KPI 是 LLM 编的 | ✅ 已证实，`execution_report.json` 无 KPI 字段，markdown 中 KPI 卡片纯文本 |
| 同环比由 LLM 直接产出 | ✅ 已证实，markdown 增长率无后端计算痕迹 |
| 多章节复用同一 dataset | ✅ T003/T005 在多章节重复引用 |

**意外发现 — 持久化缺陷**：

`execution_report.json` 只存任务元数据（`task_id` / `type` / `rows` / `elapsed_seconds` / `tokens`），**不存原始 dataset**。dataset 只在内存/临时目录存活，报告生成完毕即丢失。

**影响**：
- KPI 真值无法事后审计
- 复算/真值校验做不到
- 这是**批次 A 的隐性阻塞**（详见 §3.1）

### 1.4 数据 vs 分析能力的判断

**结论：主要矛盾是「分析+渲染层错配」，不是「数据获取不足」。**

证据：
- 数据库里 SQL 真值是有的（图表里的 99.8/97/98.55、1406/1320/662 都是真）
- 6 domain 共 141 个 endpoint，D7 设备子屏 34 个端点几乎覆盖所有设备运营指标
- 真正缺的不是"数据"而是"按业务维度的下钻 SQL 任务"和"跨 domain 的端点组合"

但**确实存在数据底层的天花板**：
- 按机种（`secondLevelName`）聚合只有 1 个端点支持（`getProductionEquipmentStatistic`）
- 故障数无法直接按机种聚合，需两阶段查询
- 详见附录 A 的维度覆盖矩阵

---

## 2. 总体方案

### 2.1 5 个批次概览

| 批次 | 解决问题 | 工时 | 用户感知 | 技术复杂度 |
|---|---|---|---|---|
| **A** 数据真实性 | KPI 假数 / 增长率离谱 / 字段名泄露 | 3.5 天 | ⭐⭐⭐⭐⭐ 最强 | 低 |
| **B** Section↔Dataset 匹配 | 章节图表错位 / 跨章节同图 | 2.5 天 | ⭐⭐⭐ | 中 |
| **C** PPTX 渲染 patch | 散落多页 / 末尾重复 | 1 天 | ⭐⭐⭐⭐ | 低 |
| **D-1** 跨域基础 | 单 domain / 分析视角不足（路由+约束） | 3.5 天 | ⭐⭐⭐⭐ | 高 |
| **D-2** 内容深化 | 章节模板 / 二维分析 / 异常检测 | 3 天 | ⭐⭐⭐⭐⭐ 长期 | 高 |

**总工时**：13.5 个工作日（含 dataset 持久化前置、perception 层 domain 路由改造）。

### 2.2 关键路径

```
A.0 dataset 持久化 (0.5天)
    ↓ 解锁 KPI 真值
A.1 KPI 走 source_asset_id (2天)
A.2 同环比单位规范 (0.5天)
A.3 字段语义命名层 (0.5天)
    ↓ 可并行
C PPTX 合页 + appendix 幂等 (1天)  // 与 A 并行

D-1.1 perception 层 domain 路由 (2天)   // 验证门
    ↓ 跨 domain chain 打通
D-1.2 planner prompt 增量约束 (1.5天)
    ↓ 章节多样性规则就位
D-2.1 章节模板库落地 (1天)             // 解锁 B
    ↓ 章节意图明确
B section ↔ dataset 强匹配 (2.5天)      // 依赖 D-2.1 的 required_intents
    ↓
D-2.2 二维 crosstab + anomaly + comparison (2天)  // 可与 B 并行
```

**关键依赖**：
- A.0 必须先于 A.1（KPI 真值需要 dataset 可查）
- D-1 验证门必须在推进 D-2 前通过（跨 domain chain 不通则改写方案）
- B 必须晚于 D-2.1（section 匹配规则依赖 required_intents 字段）
- D-2.2 可与其他并行

### 2.3 启动前置

**数据健康度基线**已完成（§9.4），输出 `data/endpoint_health.json` 作为后续所有批次的端点准入清单。

不做单独的 PoC 阶段 — 跨 domain chain 的可行性在 D.1（perception 层 domain 路由）的实施过程中直接验证；如方案行不通，在 D.1 自身的 review 节点回炉，不另起 PoC。

### 2.4 独立可推进性声明（关键）

**本 spec 不依赖任何外部协作（数据团队 / API 团队 / 业务方）即可独立交付**。核心原则：

#### 唯一不变式：`api_registry.json` 内容 ≡ grade ∈ {A, B} 的端点集

注册即可用。没有"已注册但不可用"的中间状态。这意味着：

- **D 级端点不存在于注册表**：14 个当前已注册的 D 级端点必须**从 `data/api_registry.json` 移除**（详见 §9.6 清理动作）。理论上 perception/planning/outline_planner 都看不到这些端点，**无需任何"运行时拉黑"或"防御层"**。
- **注册流程的准入条件**：新端点接入前必须先跑 `tools/endpoint_health_audit.py`，grade ∈ {A, B} 才允许写入 registry。
- **未来 D 级恢复**：数据治理后重跑 audit → 升级到 A/B → 再走标准注册流程加入 registry。不做"先注册再说，运行时过滤"。
- **registry 与 health 的同步**：在 `tools/endpoint_health_audit.py` 加 `--sync-registry` 选项（或新增 `tools/sync_registry.py`），输出"应移除 / 应新增"差异，由人工 review 后应用到 `data/api_registry.json`，同步跑 `tools/seed_api_endpoints.py` 推到 DB。

#### 三类数据问题的应对

| 问题类别 | 处理 |
|---|---|
| **D 级端点**（数据为空 / 全 0）| 从 registry 移除；spec 模板代码自然不会引用（看不到就选不到） |
| **C 级数据问题**（单位异常、字段名错用、长期无方差） | 代码侧兜底：A.0 quality_flag + A.3 字段映射 + 渲染层降级 |
| **数据不一致**（如故障数 859/1406/47 三组对不上） | A.1 全数字溯源解决：用户看到来源 endpoint，自己判断 |

§9.8 的所有"长期治理建议"都是**非阻塞改进项**。没响应也不影响交付，响应了能进一步提升数据质量。

---

## 3. 批次 A — 数据真实性修复

### A.0 前置：Dataset 持久化（0.5 天）

**问题**：当前 `execution_report.json` 不存原始 dataset，KPI 真值无法溯源。

**前置（一次性，A.0 启动前完成）**：跑 §9.6 治理债清理，从 `data/api_registry.json` 移除 14 个已注册 D 级端点，跑 `tools/seed_api_endpoints.py` 推到 DB。完成后 perception/planning/outline_planner 都看不到这些端点（§2.4 不变式）。

**改动**：
- `backend/tools/report/_content_collector.py`：在收集 raw items 时，把每个 task 的 dataframe 落盘到 `data/reports/{date}/{report_id}/datasets/{task_id}.parquet`
- 同目录写 `{task_id}.meta.json`，包含：
  - audit 字段（复用 prod_data 格式）：`endpoint_id / params_sent / fetched_at / latency_ms`
  - **quality_flags**：基于 `data/endpoint_health.json` 该 endpoint 的 warnings 列表（如 `["P0_NO_VARIANCE", "P1_NAME_VS_INTENT"]`）— 用于 C 级数据降级展示
  - **endpoint_grade**：A / B / C（D 已不在 registry，不会出现）
- `backend/tools/report/_outline_planner.py`：传给 LLM 的 `assets_summary` 增加 `dataset_path` + `endpoint_grade` 字段
- `_renderers/*` 渲染时：按 `source_asset_id` → `task_id` → `parquet` 反查真值；同时读 `quality_flags` 决定渲染策略（详见 A.1 + C.1）

**验收**：
- 14 个 D 级端点已从 `data/api_registry.json` 移除（grep 验证）
- 报告生成完毕后，`data/reports/.../datasets/` 目录存在每个 task 的 parquet + meta.json
- 渲染层能根据 KPI 的 `source_asset_id` 反查到原始 dataframe + quality_flags
- meta.json 中 `endpoint_grade` 不会出现 "D"

### A.1 数据 block 走 source_asset_id 强约束（2 天）

> ⚠️ **范围升级 + 注入流程明确化**：从只约束 KPI 升级为约束**所有承载数字的 block**（KPI 卡 / table / chart / growth_indicators / synthesised_assets 共 5 类）。粒度是 block 级（每张表 / 每张图 / 每个 KPI 一个 source_asset_id），不是 cell 级。一份报告大约 15-30 个 source 标注。错的字段映射不在 spec 里穷举；让 LLM 选 endpoint，错了通过调 prompt 或 endpoint 候选清单（D.3 章节模板库）来纠正，**不写"D2 → D7+D5"这种硬 fallback chain**。

**问题**：`_planner_prompts.py` 的 `kpi_summary` schema 是 `{label, value, sub, trend}`，4 个字段全部 LLM 自由文本。当前 [`_outline_planner.py:608 _block_from_response()`](backend/tools/report/_outline_planner.py:608) 把 LLM 输出 dict 直接转为 dataclass，**值在哪一步注入是模糊的**。本节明确这一流程。

#### 1. Schema 扩展（依赖 A.0 完成 dataset_path 注入）

| 类型 | 文件 | 改动 |
|---|---|---|
| `KPIItem` | [_outline.py:35](backend/tools/report/_outline.py:35) | 新增 `source_asset_id: str` **必填** + `agg: str \| None`（latest/mean/sum/yoy/qoq）+ `format_spec: str \| None`（percent/int/currency/raw） |
| `GrowthIndicatorsBlock` | [_outline.py:266](backend/tools/report/_outline.py:266) | 把 `growth_rates: dict` 改为 `growth_rates: dict[str, GrowthCell]`，新建 `GrowthCell = {yoy: float \| None, mom: float \| None, source_asset_id: str}` |
| `ChartAsset` / `TableAsset` / `StatsAsset` | [_outline.py:153/162/172](backend/tools/report/_outline.py:153) | A.0 已新增 `dataset_path: str \| None` |
| `TableBlock` / `ChartBlock` | [_outline.py:209](backend/tools/report/_outline.py:209) | **不动**（已有 `asset_id`；Asset 已有 `endpoint` 字段，渲染层 asset_id → asset.endpoint 即可） |
| 归因表（synthesised_assets） | _outline.py | **不新增 BlockKind**。归因表 = `TableBlock` + 引用一个 `synthesised TableAsset`（LLM 通过 prompt 中 `synthesised_assets` 字段合成）。新增字段：`TableAsset.source_asset_ids: list[str]`（多源声明，仅当该 asset 是 synthesised 时填）。**数据依据列是 LLM 描述性文本，不做数值注入**（区别于 KPI / GrowthCell）|

#### 2. Prompt 约束（`_planner_prompts.py`）

```
## 数据溯源严格规则（PR-3 新增）
- 每个数据 block（KPI / table / chart / growth_indicators / synthesised_assets）必须有 source_asset_id
- source_asset_id 必填，引用必须存在于「可用 assets」（多源合成的归因表用 source_asset_ids 列表）
- value/数字 字段不要自己写，留给后端填充
- 你只负责选 (label, source_asset_id, agg, format_spec) 四元组
- 选错 endpoint 是允许的 — 后续通过调 prompt 或 endpoint 候选清单纠正
- 但编数字、缺溯源、引用不存在的 asset_id 不允许
```

#### 3. 注入流程（关键决策）

**注入位置**：在 `plan_outline()` 内，紧跟 `_deduplicate_chart_blocks(outline)` 之后、`return outline` 之前，新增独立函数 `_inject_values()`。

**为什么不在 `_block_from_response()` 内部注入？** —— 关注点分离：构造阶段只做 dict → dataclass 翻译；注入阶段独立处理"按 source_asset_id 反查 dataset → 算真值 → 格式化 → 写回"。注入函数可独立单元测试，不依赖 LLM dict schema。已确认 `KPIItem` / `GrowthIndicatorsBlock` 都不是 frozen dataclass，原地修改 `value` / `growth_rates` 安全。

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
                    raw = compute_agg(load_dataset(asset.dataset_path), item.agg)
                    item.value = format_value(raw, item.format_spec)

            elif isinstance(block, GrowthIndicatorsBlock):
                for col, cell in block.growth_rates.items():
                    asset = _resolve_asset(cell.source_asset_id, assets_by_id)
                    cell.yoy, cell.mom = compute_growth(load_dataset(asset.dataset_path), col)

            elif isinstance(block, (TableBlock, ChartBlock)):
                pass  # 数据来自 Asset.df_records / Asset.option，渲染层自取

            elif _is_attribution_block(block, assets_by_id):
                # 归因表"数据依据"列是 LLM 描述性文本，不注入数值
                # validator 校验文本里出现的 endpoint 名 ⊆ 声明的 source_asset_ids
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

#### 4. 格式化在 outline_planner 完成（不在渲染层）

`KPIItem.value: str` 是 dataclass 字段，必须在塞进 dataclass 前 format。新增 [`backend/tools/report/_value_format.py`](backend/tools/report/_value_format.py) 处理：

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

#### 5. 渲染层标注：从 Asset.endpoint 反查（不新增字段）

**关键设计**：渲染层不依赖 block 上新增的 `source_annotation` 字段，而是 `block.asset_id / item.source_asset_id → assets[id].endpoint` 直接拿来源名。HTML/DOCX/PPTX 三格式同步：

- **KPI 卡底部小字**：`源: {asset.endpoint}`
- **表格脚注**：`数据来源：{asset.endpoint}（取自 {asset.fetched_at}）`
- **图表 caption 下方**：同上
- **增长率 KPI**：每个 metric 旁 `源: {asset.endpoint}`
- **归因表"数据依据"列**：LLM 文本里直接含 endpoint 名（validator 保证 ⊆ source_asset_ids）
- **HTML 可点击展开**：source 文本 → tooltip 显示 `params_sent + fetched_at + dataset_path`

**quality_flag 警示**（数据来自 A.0 写入的 meta.json）：

- `P0_NO_VARIANCE` → 数据卡角加 ⚠️ + tooltip "该指标无月度方差，仅展示当期值"
- `P0_RANGE_RATE` / `P1_QUANTITY_LOW` → 数字后加 ⚠️ + tooltip "数据可疑，请核对单位口径"
- `P1_NAME_VS_INTENT` → 字段标签自动用映射后的业务名（如 MTBF），不显示原 `usageRate`
- 用户能直接看到"数据可疑"，但报告不空白 — 显示原值 + 警示

#### 6. Validator 重试（复用 PR-2 模式）

| 触发条件 | 行为 | 上限 |
|---|---|---|
| 任意承载数字的 block 缺 `source_asset_id` | 重试 LLM | 3 次 |
| `source_asset_id` 不在 assets 中 | 重试 LLM | 3 次 |
| `_inject_values()` 抛 `ValidationError` | 重试 LLM | 3 次 |
| 归因表"数据依据"列出现的 endpoint 名 ⊄ source_asset_ids | 重试 LLM | 2 次 |
| 重试超限 | 该 block 不渲染（**不显示假数字**） | — |

#### 7. 验收

- [ ] `Asset` / `KPIItem` / `GrowthCell` schema 扩展通过单元测试
- [ ] `_inject_values()` 单元测试覆盖 5 种 block kind 的注入路径
- [ ] 报告 HTML/DOCX/PPTX 每个数据 block 旁可见来源 endpoint 名
- [ ] 报告内 KPI/图表/表格数字之间一致（差值 < 0.1%）
- [ ] 错的 endpoint 选择能通过"看哪个 endpoint 数字诡异 → 调 D.3 章节模板的 endpoint 候选 → 重生成"的闭环修复

#### 8. 与 A.2 的合并

A.2 的 `GrowthCell` schema 改造已纳入本节（第 1 项 schema 扩展）。A.2 仅保留"小数 vs 百分点契约 + sanity validator"两项。

### A.2 同环比单位口径 + Sanity Validator（0.5 天）

> **范围已瘦身**：`GrowthCell` schema 改造已合并到 A.1（schema 扩展第 1 项）；`_inject_values()` 中 `compute_growth(load_dataset(...), col)` 已承担注入。本节仅保留"全链路单位口径契约"+ "异常区间 validator"。

**问题**：`growth_indicators` block 的 `yoy: float / mom: float` 字段，LLM 可输出 `0.078` 也可输出 `7.8`，下游渲染层又乘 100 → 出现 ↑780%。

**改动**：

1. **明确口径契约（在 [`_planner_prompts.py`](backend/tools/report/_planner_prompts.py) 注释顶部固化）**：
   - 全链路 `GrowthCell.yoy` / `GrowthCell.mom` 统一为**小数形式**（-1.0 ~ 1.0 为常态区间）
   - **渲染层在末端 ×100 + 加 `%`**，三个 renderer（HTML/DOCX/PPTX）只在最末端做一次转换，禁止任何中间层做单位转换
   - LLM **不允许**输出数值（A.1 已强制走后端注入）

2. **后端预算 growth assets**：在 [`_content_collector.py`](backend/tools/report/_content_collector.py) 阶段，对所有 numeric 列预算同环比并写入 dataset，作为 stats asset 注入 `assets_summary`。**优先调用 D2/D7 的 YoY 专用端点**（如 `getThroughputAnalysisYoyMomByMonth`、12 个 `T_YOY` 端点），找不到时本地算。

3. **Sanity validator**（复用 PR-2 重试机制）：
   - `_inject_values()` 注入完成后扫描所有 `GrowthCell`：`abs(yoy) > 2.0` 或 `abs(mom) > 2.0` → 视为异常，重试 LLM 让它换数据源
   - 重试 3 次仍异常 → 该 growth_indicator block 不渲染

**验收**：
- 报告中所有同环比数字绝对值 ≤ 200%（除非数据本身极端）
- 单位口径文档化在 `_planner_prompts.py` 注释顶部
- HTML/DOCX/PPTX 三 renderer 中"小数 ×100 加 %"只出现一次（grep 验证）

### A.3 字段语义命名层（0.5 天）

**问题**：KPI 显示 `firstLevelName_起重机械`、表头叫"数量"配"成本"标题。

**改动**：

1. **新增字段映射文件**：`backend/tools/report/_field_labels.py`（已存在，扩展之）
   ```python
   FIELD_DISPLAY_NAMES = {
       "firstLevelName": "设备一级分类",
       "secondLevelName": "机种",
       "ownerLgZoneName": "港区",
       "usageRate": "利用率",
       "serviceableRate": "完好率",
       "machineHourRate": "机时效率",
       "num": {  # 多义字段按上下文映射
           "default": "数量",
           "fault": "故障次数",
           "cost": "成本(元)",
           "throughput": "吞吐量(吨)",
       },
       # ...
   }
   ```

2. **多义字段消歧**：在 task 元数据里增加 `semantic_context` 标签（如 `cost`/`fault`/`throughput`），渲染层按 context 选名字。

3. **改动位置**：
   - `_block_renderer.py`：表头/坐标轴/legend 全部走 `field_labels.resolve(field, context)`
   - `_outline_planner.py`：传给 LLM 的 `assets_summary` 中的字段名先做映射

**验收**：
- 整份报告无任何 `firstLevelName_xxx`、`*_yoy`、`secondLevelName_xxx` 形式的字段名
- "成本"章节的表头读起来是"成本/元"而不是"数量"

---

## 4. 批次 B — Section ↔ Dataset 强匹配

### B.1 Outline Schema 扩展（0.5 天）

在 section 定义中加入 metric_focus / group_by / required_intents：

```python
# backend/models/schemas.py 或新增 _section_schema.py
class SectionDefinition(BaseModel):
    name: str
    role: Literal["summary", "status", "analysis", "attribution", "recommendation", "appendix"]
    metric_focus: list[str]              # 该章节的核心指标，如 ["usageRate", "serviceableRate"]
    group_by: list[str]                  # 期望的分组维度，如 ["dateMonth", "firstLevelClassName"]
    required_intents: list[AnalysisIntent]  # 详见 D.2
    domain_roles: dict[str, str]         # 如 {"D7": "primary", "D5": "context"}
```

### B.2 Collector 匹配逻辑改造（1.5 天）

**问题**：`_content_collector.py:370-381` 当前是轮询兜底。

**改动**：
- 重写 `_associate()` 函数：按 section 的 `metric_focus` × `group_by` 与 task 的 endpoint metadata 做强匹配
- 匹配失败的 task 不强塞给某 section，而是放入 "orphan tasks" 列表
- Outline planner 读取 orphan tasks 时显式提示 LLM："以下任务未匹配到任何章节，可考虑补充章节或忽略"

```python
def _associate(sections, tasks, assets):
    matched = {s.name: [] for s in sections}
    orphan = []
    for task in tasks:
        candidates = [s for s in sections
                      if matches(task, s.metric_focus, s.group_by, s.domain_roles)]
        if len(candidates) == 1:
            matched[candidates[0].name].append(task)
        elif len(candidates) > 1:
            # 优先选 domain_roles 中标记为 primary 的
            primary = [s for s in candidates if s.domain_roles.get(task.domain) == "primary"]
            (primary or candidates)[0]._receive(task)
        else:
            orphan.append(task)
    return matched, orphan
```

### B.3 已用 Metric 去重（0.5 天）

**问题**：运营总览 + 时间趋势两章画同一条线（同一组 [1.0, 0.97, 0.99]）。

**改动**：
- `_outline_planner.py` 在生成 LLM prompt 时增加"已使用 metric 集合"约束：
  ```
  ## 章节差异化约束
  - section[0] 已使用：[usageRate@dateMonth]
  - section[1] 不可再使用 usageRate@dateMonth，须选择不同的 (metric, group_by) 组合
  ```
- validator：扫描各章节产出的 chart asset_id × group_by，若两章节命中同一组合 → 重试

**验收**：
- 任意两个章节的图表 (asset_id, group_by) 组合无完全重叠
- 章节内容差异化（不能简单换图，配文也要不同）

---

## 5. 批次 C — PPTX 渲染层 Patch

### C.1 章节内容合页 (Layout-Aware)（0.5 天）

**问题**：`_render_section_combo()` (Line 968-992) 硬编码每章 3-4 张 slide。

**改动**：
- 新增 `_estimate_section_complexity()` 函数：
  - 统计该 section 的 chart 数、narrative 字数、KPI 数
  - 返回 layout 决策：`single_page` / `chart_text_split` / `multi_page`
- `_render_section_combo()` 按决策走不同分支：
  - `single_page`（默认）：1 张 slide 容纳 chart + narrative + ≤3 KPI
  - `chart_text_split`：chart 占满一页，narrative + KPI 合到下一页
  - `multi_page`：仅当 chart > 2 或 narrative > 200 字时启用
- **删除"每章节专用增长率页"** — 增长率合并进章节内的 KPI 行

### C.2 Appendix 幂等（0.5 天）

**问题**：`_flush_appendix_deck()` 被触发 2 次。

**改动**：
- 在 `pptxgen.py` 的 builder state 加 `_appendix_flushed: bool = False` 标记
- `_flush_appendix_deck` 进入时检查标记，已 flush 直接返回
- 单元测试覆盖："连续调用 flush 两次只产出一份附录"

**验收**：
- 设备运营报告 PPTX slide 数从当前 24 张降到 12-14 张
- 任意章节占 1-2 张 slide，不再出现章节封面 + 图表页 + 文字页 + KPI 页四联
- 附录与结语只出现 1 次

---

## 6. 批次 D — 分析深度（核心）

### D.1 Perception 层 Domain 路由（2 天）

**背景**：现网真实数据证实跨 domain 调用 = 0。outline planner 拿到的 raw_items 永远只有单 domain，光改 outline planner 解决不了。

**改动**：

1. **新增报告类型枚举**：
   ```python
   # backend/models/schemas.py
   class ReportType(str, Enum):
       EQUIPMENT_OPS = "equipment_ops"          # 设备运营
       BUSINESS_OPS = "business_ops"            # 业务运营
       BUSINESS_DASHBOARD = "business_dashboard" # 商务驾驶舱
       CUSTOMER_PROFILE = "customer_profile"    # 客户专题
       ASSET_INVENTORY = "asset_inventory"      # 资产盘点
       INVESTMENT_PROGRESS = "investment_progress" # 投资进度
       GOVERNANCE = "governance"                # 投企治理
   ```

2. **报告类型 → Domain 配置映射**（详见附录 B）：
   ```python
   REPORT_DOMAIN_CONFIG = {
       ReportType.EQUIPMENT_OPS: {
           "primary": ["D7"],            # 设备子屏
           "secondary": ["D5", "D6"],    # 资产、投资
           "context": ["D1", "D2"],      # 业务、商务
           "endpoint_quota": {"D7": 4, "D5": 2, "D6": 1, "D1": 2, "D2": 1},
       },
       # ...
   }
   ```

3. **PLANNING_PROMPT 改造**（[`backend/agent/planning.py`](backend/agent/planning.py)）：
   - 第一步：识别报告类型（基于用户问题 + 关键词匹配 + LLM 兜底）
   - 第二步：按报告类型选 domain 配置
   - 第三步：在每个 domain 的 endpoint 池中按 quota 选端点
   - 复杂度规则改造（[`_complexity_rules.py:71-127`](backend/agent/_complexity_rules.py:71)）：full_report 不再约束总数，约束 "每报告类型必须覆盖的 domain 集合"

4. **去除两道断头路**（关键 — 不做这步前面三步全白做）：

   当前 [planning.py](backend/agent/planning.py) 有两个函数会**剥离 section metadata**，导致 D.1 选好的 domain / metric / endpoint_hints 跑到 content_collector 全是空的：

   - [`_stitch_plan` (planning.py:1295)](backend/agent/planning.py:1295)：当前 `"sections": [{"name": s.name} for s in kept_sections]` 只保留 name → **改为完整保留 `{name, role, focus_metrics, domain_hint, endpoint_hints, required_intents, endpoint_candidates, subsections}`**
   - [`_sanitize_report_structure` (planning.py:479)](backend/agent/planning.py:479)：当前 `s.pop("task_refs", None)` 主动删 task_refs → **改为白名单逐字段清洗**（只剥真正不该有的字段，保留 D.1/D.3 引入的所有 metadata）

   配套验证：单元测试覆盖"D.1 选定 domain → stitch 后 metadata 仍存在 → content_collector 收到完整 section"端到端 path。

**验收**：
- 设备运营报告 task 列表跨 domain ≥ 3 个（D7+D5+D1 至少各 1）
- 报告类型识别准确率 ≥ 90%（人工抽样 20 份验证）
- 单元测试：`_stitch_plan` 和 `_sanitize_report_structure` 不再丢弃 D.1 注入的 section 字段

### D.2 Planner Prompt 增量约束（1.5 天）

**关键判断**：`_planner_prompts.py` 现有 schema 已经成熟，不重写，**追加约束**。

**改动**：

1. **`assets_summary` 增加 metadata**：
   ```json
   {
     "asset_id": "T003_chart",
     "kind": "chart",
     "source_task": "T003",
     "endpoint_id": "getEquipmentUsageRate",   // 新增
     "domain": "D7",                            // 新增
     "domain_role": "primary",                  // 新增
     "metric_focus": ["usageRate"],             // 新增
     "group_by": ["dateMonth", "ownerLgZoneName"], // 新增
     "preview": "..."
   }
   ```

2. **新增 `AnalysisIntent` 枚举**：
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

3. **prompt 追加约束（PR-3 新增）**：
   ```
   ## 章节内容多样性约束
   - 每个 analysis 类章节必须覆盖至少 2 种不同的 analysis_intent
   - 不同章节的 (metric_focus, group_by) 组合不可完全重复
   - 章节配图须与 metric_focus 一致（不能给"成本章节"配"利用率图"）

   ## 跨 domain 协作约束
   - 优先使用 domain_role=primary 的 asset 作为主图
   - secondary domain 的 asset 用于补充对比或上下文
   - 一个章节可引用 ≤2 个 domain 的 asset
   ```

4. **复用 PR-2 validator 三件套**：
   - intent 多样性 validator（每章 ≥ 2 种 intent）
   - metric_focus 一致性 validator（图表 metric ⊆ 章节 metric_focus）
   - 跨章节去重 validator（详见 B.3）

### D.3 章节模板库（1 天）

> ⚠️ **数据警示**：本节代码示例的 `endpoint_candidates` **只列 A/B 级端点 + A\* 待补注册端点**。D 级端点已从所有候选清单完全剔除（详见 §2.4）。
> - `getProductionEquipmentStatistic` (A 级但仅含数量) → TOP_N 改为"机种数量排行"，不要做"利用率排行"

**改动**：

1. **新增 `backend/tools/report/_section_templates.py`**：
   ```python
   EQUIPMENT_OPS_SECTIONS = [
       {
           "name": "运营总览",
           "role": "summary",
           "metric_focus": ["usageRate", "serviceableRate", "throughput"],
           "required_intents": [AnalysisIntent.YOY_COMPARE],
           "endpoint_candidates": {
               "primary": ["getSumBusinessDashboardThroughput"],  # D2 KPI 端点
               "secondary": ["getEquipmentUsageRate", "getEquipmentServiceableRate"],
           },
       },
       {
           "name": "设备结构分析",
           "role": "status",
           "metric_focus": ["secondLevelName", "firstLevelClassName"],
           "required_intents": [
               AnalysisIntent.BREAKDOWN_BY_DIM,
               AnalysisIntent.TOP_N,
           ],
           "endpoint_candidates": {
               "primary": ["getProductionEquipmentStatistic"],  # 39 行机种透视
               "secondary": ["getEquipmentFirstLevelClassNameList",
                            "getEquipmentFacilityStatusAnalysis"],  # D5 状态分布
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
           # 多视角并列展示，禁止跨 endpoint 合表（详见 §6 D.3 末尾"跨 domain 拼接策略"）
           # 模板源码只列 A/B 级端点，D 级端点不写（详见 §2.4）
           "subsections": [
               {
                   "name": "资产视角",      # D5: 按 assetTypeName 分组
                   "endpoint_candidates": ["getEquipmentFacilityAnalysisYoy",   # A
                                           "getEquipmentFacilityAnalysis"],     # B (长表)
                   "groupby_field": "assetTypeName",
               },
               {
                   "name": "运营消耗视角",  # D7: 按 firstLevelName 分组
                   "endpoint_candidates": ["getEquipmentIndicatorUseCost",      # B (字段 alias)
                                           "getEquipmentElectricityTonCost"],   # A
                   "groupby_field": "firstLevelName",
               },
               {
                   "name": "投资因果视角",  # D6（待补注册）
                   "endpoint_candidates": ["getCostProjectFinishByYear"],       # A* (待补注册)
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
               "secondary": ["getEquipmentFacilityStatusAnalysis"],   # D5 强归因
               "context": ["getRealTimeWeather"],                     # D1 弱上下文
           },
       },
       # ... 其他章节见附录 C
   ]
   ```

2. **章节模板与 perception 联动 — Section schema 传递链**：

   章节模板的字段需跨 4 个阶段传递：`planning → execution → content_collector → outline_planner`。**统一通过 `report_structure.sections[*]` 的 dict schema 扩展**承载，不新增 `plan_outline()` 参数（最少破坏面）。

   **新 sections schema**（在 [`backend/models/schemas.py`](backend/models/schemas.py) 定义 + [`backend/agent/planning.py`](backend/agent/planning.py) 产出）：
   ```python
   class SectionSpec(BaseModel):
       name: str                                       # 现有
       role: Literal["summary", "status", "analysis",
                     "attribution", "recommendation", "appendix"]
       focus_metrics: list[str] = []                   # D.1 注入
       domain_hint: str | None = None                  # D.1 注入（D1-D7）
       endpoint_hints: list[str] = []                  # D.1 注入
       required_intents: list[AnalysisIntent] = []     # D.3 注入
       endpoint_candidates: dict[str, list[str]] = {}  # D.3 注入 (primary/secondary/context)
       subsections: list["SubsectionSpec"] | None = None  # D.3 注入（跨 domain 并列展示）
       diff_note: str | None = None                    # D.3 注入
   ```

   **传递链各阶段责任**：

   | 阶段 | 文件 | 责任 |
   |---|---|---|
   | planning | [`planning.py PLANNING_PROMPT`](backend/agent/planning.py) | 识别 ReportType → 加载章节模板（来自 [`_section_templates.py`](backend/tools/report/_section_templates.py)）→ 写入 `report_structure.sections[*]` 全字段 |
   | planning | [`planning.py _stitch_plan`](backend/agent/planning.py:1295) | **完整透传** sections 全字段（不只 name —— 见 D.1 改动 4） |
   | planning | [`planning.py _sanitize_report_structure`](backend/agent/planning.py:479) | 白名单清洗，**保留** D.1/D.3 注入的所有字段 |
   | execution | execution layer 把 `report_structure` 透传给 content_collector | 不动 |
   | content_collector | [`_content_collector.py _associate()`](backend/tools/report/_content_collector.py) | 按 `focus_metrics × endpoint_candidates × required_intents` 做强匹配（B.2） |
   | outline_planner | [`_outline_planner.py plan_outline()`](backend/tools/report/_outline_planner.py) | 把 `endpoint_candidates` 限制条件传给 LLM prompt；LLM 不能自由选 endpoint，必须从候选清单选 |

   **outline_planner 不需要新参数**：原本就接收 `params: dict`，sections 在 `params["report_structure"]["sections"]` 里，扩字段不破坏函数签名。

   **schema 演化兼容**：旧字段（只有 name）的 section 视为 D.1/D.3 未生效的退化模式，行为与本 spec 实施前一致（不会崩溃）。

3. **跨 domain 拼接策略**（关键决策）：

   多个 endpoint 的字段维度对不上时（如 D5 的 `assetTypeName` 与 D7 的 `firstLevelName` 是不同的设备分类标准），**禁止跨 endpoint 合表**。改用以下三种方式：

   - **subsections 并列**：章节内分子节，每个 endpoint 一个子节独立成图/表（见上"设备成本分析"示例）
   - **diff_note 显式说明**：章节末尾用 `callout-info` 明示"本章节几个视角口径不一致，不跨表对照"
   - **chart_table_pair 不混用**：图与表必须来自同一 endpoint

   渲染层 + validator 配合：
   - validator 检测同一 chart 或 table 的 `source_asset_id` 唯一性 → 多于一个直接重试
   - 渲染层在每个子节标题处显示"按 {groupby_field} 分组（来源：{endpoint}）"
   - 归因表如确需引用多 endpoint，必须在"数据依据"列分别列出 endpoint 名

### D.4 二维 Crosstab + Anomaly + Comparison（2 天）

**D.4.1 二维 crosstab**（0.5 天）：
- `descriptive.py:73-79` 改造：`group_by` 接受 `List[str]`，输出 pandas pivot
- `_chart_renderer.py` 新增 heatmap / stacked bar / grouped bar 路由
- prompt 中明示 `crosstab_2d` intent 的产出格式

**D.4.2 Anomaly 实装**（0.5 天）：
- `anomaly.py` 当前是占位 — 实装 z-score（默认）和 IQR（备选）
- 接受 `(dataframe, metric, group_by, threshold=2.0)`，输出"异常时段/异常组"列表
- 在归因表中作为"数据依据"列引用

**D.4.3 Comparison 模块新增**（1 天）：
- 新增 `backend/tools/analysis/comparison.py`
- 三个核心函数：
  - `yoy_compare(df, metric, time_col)`：跨期对比
  - `cross_group_compare(df, metric, group_col)`：跨组对比
  - `target_vs_actual(df, target_col, actual_col)`：计划 vs 实际
- 优先复用 D2 的 YoY 专用端点结果（避免重复计算）

---

## 7. 实施顺序与里程碑

### 7.1 周计划

**Week 1（数据真实性 + PPTX 修复）**

| Day | 任务 | 产出 |
|---|---|---|
| 1 | A.0 dataset 持久化（含 dataset_path 字段 + meta.json + quality_flags） | datasets/*.parquet + meta.json 落盘；Asset schema 扩展 |
| 2 | A.1（上）schema 扩展：`KPIItem` / `GrowthCell` / Asset；新增 `_value_format.py` | dataclass + 格式化函数就绪 |
| 3 | A.1（下）`_inject_values()` 实装 + prompt 约束 + validator 重试 | 真值注入闭环跑通 |
| 4 | A.2 单位口径契约 + sanity validator（schema 已并入 A.1）+ A.3 字段命名 | 假数据问题清零 |
| 5 | C.1 PPTX 合页 + C.2 appendix 幂等 + M1 完整测试 | PPTX 12-14 张 slide；三格式回归通过 |

**里程碑 M1**（Week 1 末）：报告"看起来可信"。三格式所有 KPI/增长率/字段名问题清零，PPTX 不再散落。**用户感知最强的痛点全部解决**。

**Week 2（跨域基础 D-1）**

| Day | 任务 | 产出 |
|---|---|---|
| 6-7 | D-1.1 perception 层 domain 路由 | task 跨 domain ≥ 3 个；跨 domain chain 在此环节直接验证 |
| 8-9 | D-1.2 planner prompt 增量约束 | 章节多样性 + intent 覆盖 |

**里程碑 M2**（Week 2 末）：跨 domain 调用链打通，每章节 ≥ 2 种 intent。

**Week 3（内容深化 D-2 + Section 匹配 B）**

| Day | 任务 | 产出 |
|---|---|---|
| 10 | D-2.1 章节模板库（设备运营报告） | 7 章节模板就绪 |
| 11-12 | B section ↔ dataset 强匹配 | 章节图表语义一致 |
| 13 | D-2.2 crosstab + anomaly + comparison | 二维分析能力上线 |

**里程碑 M3**（Week 3 末）：报告"分析能力达标"。归因表的每个结论都有数据支撑，二维下钻可用。

### 7.2 D-1.1 验证节点

D-1.1 实施过程中（Day 6-7）必须验证跨 domain chain 的端到端打通。判定标准 + 失败回炉路径：

| D-1.1 结果 | 决策 |
|---|---|
| ✅ task 列表跨 domain ≥ 3 + 数据正确归到对应章节 | 按计划推进 D-1.2 / D-2 |
| ⚠️ 跨 domain 调用成功但 section 归属错乱 | 提前启动 B（section 匹配）；D-1.2 / D-2 顺延 1 天 |
| ❌ perception 层无法稳定路由到正确 domain | D-1.1 方案直接改写（更换路由策略，例如把"识别报告类型"前置到多轮对话的 perception 层），不留旧路径 |

---

## 8. 验收标准

### 8.1 数据真实性

- [ ] **每个数据 block（KPI 卡 / 表 / 图 / 增长率 / 归因表）旁可见来源 endpoint 名**（核心验收，block 级粒度，非 cell 级）
- [ ] 任意 KPI 卡的数字与下方图表/表格的真值一致（差值 < 0.1%）
- [ ] 任意同环比绝对值 ≤ 200%
- [ ] 整份报告无 `firstLevelName_xxx` / `*_yoy` 等字段名泄露
- [ ] 报告生成完毕后 datasets/ 目录有完整 parquet 留存
- [ ] 同一图表 / 表格的 `source_asset_id` 唯一（不跨 endpoint 合表；归因表例外，用 source_asset_ids 列出多源）
- [ ] 多 endpoint 视角并列的章节末尾有 `diff_note` 说明口径差异

### 8.2 分析深度

- [ ] 单份报告 task 列表跨 domain ≥ 3 个
- [ ] 每个 analysis 类章节包含 ≥ 2 种 analysis_intent
- [ ] 任意两个章节的 (metric_focus, group_by) 组合无完全重叠
- [ ] 归因表的每行 "数据依据" 列引用的 asset_id 可在报告内找到对应图表

### 8.3 PPTX 排版

- [ ] 设备运营报告 PPTX slide 数 12-16 张（当前 24 张）
- [ ] 任意章节占 1-2 张 slide
- [ ] 附录与结语各出现 1 次（不重复）

### 8.4 章节匹配

- [ ] "设备结构分析"章节配图为机种透视/状态分布/类型构成（不再配月份折线图）
- [ ] "设备成本分析"章节包含资产视角（D5）+ 消耗视角（D7）+ 投资视角（D6）

### 8.5 数据健康度（基于 §9 校验）

- [ ] 渲染前对每个 dataset 自动跑 §9.2 健康度检查，3 类风险（null/empty/range）有 fallback
- [ ] 关键 endpoint（A/B/C 级）健康度看板每日刷新
- [ ] 任意 KPI 数字都有 audit trail 可反查到 (endpoint, params, fetched_at, agg_func)

---

## 9. 常见问题（基于真实数据校验）

> **来源**：`mock_server/prod_data/` 目录下 215 份真实 API 响应快照（2026-04-16 抓取）的逐端点验证。
>
> **价值**：原 spec 的批次 A/B/C/D 设计假设"数据底层是干净的、字段语义是清晰的、单位是统一的"。真实数据校验**推翻了多个假设**——如果不在实施前处理这些问题，批次 A.1 的 KPI 真值方案、批次 D.3 的章节模板都会**直接失败**。

### 9.1 12 个常见问题（按严重程度）

#### 🚨 P0 — 数据本身的严重问题

**CQ-1：KPI 真值"标准答案"端点存在大量 null**

- 端点：`D2_getSumBusinessDashboardThroughput`（spec §3 A.1 推荐的 KPI 主源）
- 真实数据：8 行中 4 行 `num=null`：
  ```json
  [
    {"num": null,    "typeName": "同期吞吐量"},
    {"num": null,    "typeName": "当期吞吐量"},
    {"num": 1204.35, "typeName": "同期集装箱吞吐量"},
    {"num": null,    "typeName": "当期中转量吞吐量"},
    {"num": 187.38,  "typeName": "当期集装箱吞吐量"},
    {"num": 41.43,   "typeName": "同期海铁联吞吐量"},
    {"num": 1144114, "typeName": "同期中转量吞吐量"},
    {"num": null,    "typeName": "当期海铁联吞吐量"}
  ]
  ```
- **影响范围**：批次 A.1 的"KPI 走 source_asset_id"假设依赖该端点提供"计划/实际/同期"五元组，实际有 50% 字段为 null
- **应对**：A.1 实施时增加 fallback chain — 主源 D2 → 辅源 D7 (利用率/完好率) + D5 (资产净值) 多端点拼接；KPI 缺失时显示 "—" 而非编造数字

**CQ-2：关键 endpoint 数据完全为空**

| 端点 | 真实数据 | spec 中的角色 |
|---|---|---|
| `D5_getOriginalValueDistribution` | **0 行** | D.3 设备成本分析章节 primary 端点 |
| `D6_getFinishProgressAndDeliveryRate` | 1 行，所有金额字段 = 0 | D.3 设备成本分析"投资因果上游" |

- **应对**：
  - D.3 章节模板必须支持 "primary 失败 → secondary 兜底" 优雅降级
  - perception 层在选端点前先调用 endpoint health check（基于 prod_data 快照统计 `data_count > 0` 比例）
  - 健康度 < 80% 的端点不进入 `endpoint_candidates`

**CQ-3：利用率/完好率单位异常**

- `D7_getEquipmentUsageRate.usageRate`：真实值 4.3 / 5.2 / 5.5
- 如果是百分比 → 4.3% 太低不合理；如果是小数 → 0.043 也太低
- 但报告里画的是 99.8%/97%/98.55% — **这两组数对不上**！可能报告用了别的 endpoint 或自己算了一遍
- `D7_getEquipmentServiceableRate.serviceableRate`：真实值 1.0 / 1.0 / 1.0（三个月全 100%，无方差）
- **应对**（不依赖外部）：
  - 新增 `backend/tools/analysis/_metric_sanity.py`：定义每个指标的合理区间（如 `usageRate ∈ [0, 1] OR [0, 100]`），超出时落入 `quality_flags`
  - 方差检测：当指标 `var(x) < threshold` 时降级为"显示当期值，不画趋势线"
  - 渲染层显示 ⚠️ + tooltip "数据可疑"，配合 A.1 全数字溯源，用户能直接判断
  - （数据 owner 确认真实口径是长期改进项，详见 §9.8 — 不阻塞 spec 交付）

**CQ-4：单一指标重复 N 个月相同值（无信号）**

- `D7_getEquipmentServiceableRate` 三个月全 1.0
- 类似情况可能还存在于 `D7_getEquipmentElectricityTonCost.tonCost = 0.0`（电量吨成本 = 0）
- **影响**：硬画趋势图等于"用户花时间看了一条直线 + 一个等于 0 的数据"
- **应对**：A.0 dataset 持久化阶段加 `quality_flags` 字段，渲染层据此选择不同模板

#### ⚠️ P1 — 字段语义错用（影响渲染层）

**CQ-5：字段名 `usageRate` 实际承载 MTBF 数据**

- `D7_getMachineDataDisplayEquipmentReliability` 的 intent 是"集装箱设备可靠性指标 MTBF/MTTR/故障次数"
- 实际数据字段叫 `usageRate`，但值是 1665.24 / 4646.48 — 显然是 MTBF（小时数）
- 同样 `D7_getNonContainerProductionEquipmentReliability` 字段名 `usageRate`，值 21838.43
- **影响**：A.3 字段映射层如果按字段名映射，会把 MTBF 显示成"利用率"
- **应对**：A.3 的 `FIELD_DISPLAY_NAMES` 必须支持 `(field_name, endpoint_id) → display_name` 二元 key，不能只看字段名

**CQ-6：同一业务概念字段名不统一**

- `D7_getEquipmentIndicatorUseCost` 字段：`firstLevelName`
- `D7_getEquipmentFirstLevelClassNameList` 字段：`firstLevelClassName`
- **同一业务概念两个字段名** — B 批次的 section ↔ dataset 强匹配如果按字段名 join 会失败
- **应对**：A.3 字段映射层增加 alias 表：
  ```python
  FIELD_ALIASES = {
      "firstLevelName": "firstLevelClassName",
      "secondLevelName": "secondLevelClassName",
      # ...
  }
  ```

**CQ-7：报告显示故障数与 endpoint 真值不一致**

- 真实 `getProductionEquipmentFaultNum`：月度 859 / 615 / 716
- 报告图表显示：1406 / 1320 / 662
- 报告 KPI 写"Q1 共 47 次"
- **三组数字完全不一致** — 当前 pipeline 不知在哪一步引入了错位
- **应对**：A.0 dataset 持久化时同时记录每个 dataset 的 `lineage`（`endpoint_id` + `params_sent` + `fetched_at` + 行 hash），renderer 输出每个图/KPI 都带 lineage tooltip

**CQ-8：设备数量级异常**

- `D7_getEquipmentFirstLevelClassNameList` 第一行 `辅助生产机械: num=2.0`
- 全港只有 2 台辅助生产机械显然不真实（可能是单位"千台"或数据缺失）
- **应对**：metric sanity 检查表加"数量级哨兵"——根据指标类型预设合理区间（设备数量 ≥ 50、资产净值 ≥ 1e7、月吞吐量 ≥ 100 等）

#### ⚠️ P2 — 数据形态需要二次处理

**CQ-9：大部分 endpoint 是长表（long format），需要 melt → pivot**

- `D5_getEquipmentFacilityStatusAnalysis`：24 行 = 8 状态 × 3 指标（实物资产数/资产原值/资产净值）
- `D5_getEquipmentFacilityAnalysis`：60 行 = 多 assetType × 多 typeName × 多 dateYear 三维长表
- `D2_getCumulativeRegionalThroughput`：6 行 = 港区 × {计划吞吐量, 实际吞吐量, 同期, ...} 二维
- **影响**：当前 LLM 看到的是原始 list，识别不出透视结构 — 这是 spec §1.2 R3 "章节↔图表错位"的隐性诱因
- **应对**：在 `_content_collector` 阶段做 schema 推断：
  - 检测"重复 typeName + 不同 metric"模式 → 自动 melt 到 wide
  - 传给 LLM 的 `assets_summary.preview` 用 wide format
  - 配套 `_renderers/_chart_renderer.py` 加 wide → heatmap / stacked bar 路由

**CQ-10：`getProductionEquipmentStatistic` 实际不含完好率/利用率/役龄**

- spec §附录 A.2 描述："39 行机种透视表，按机种分类返回完好率/利用率/役龄"
- 真实数据：39 行 × **字段只有 `num` + `secondLevelName`** — 只有数量
- **影响**：D.3 章节模板里"机种 TOP_N 利用率排行"无法实现
- **应对**：
  - 修正 spec §附录 A.2（已在本次更新）
  - D.3 章节模板"设备结构分析"的 TOP_N intent 改为"机种数量 TOP_N"
  - 若真要做"按机种利用率排行"，必须走机种展示屏端点的两阶段查询（先 list 机种 → 循环查每个）

#### ⚠️ P3 — 元数据与缓存

**CQ-11：prod_data 已有 audit 字段，运行时持久化应复用**

- 真实 prod_data JSON 已含：`api / path / domain / intent / params_sent / response_pattern / data_type / data_count / latency_ms / fetched_at / base_url`
- spec A.0 持久化 datasets/*.parquet 时应复用同样的 audit 字段
- **应对**：A.0 落盘格式调整为 `{task_id}.parquet` + `{task_id}.meta.json`（meta 包含上述 audit 字段 + lineage）

**CQ-12：同一 endpoint 不同参数 → 数据形态完全不同**

- `getMachineDataDisplayEquipmentReliability` 必传 `secondLevelClassName=岸桥` → 单机种 15 行月度数据
- `getProductionEquipmentFaultNum` 不传 `secondLevelClassName` → 港区聚合 3 行
- **影响**：B 批次的 dataset 缓存如果 cache key 不含 params，会把不同形态数据混淆
- **应对**：
  - asset_id 命名规范：`{task_id}_{endpoint}_{params_hash[:8]}`
  - dataset cache key 必须含 `params_sent` 的 deterministic hash

### 9.2 Endpoint 数据健康度概览（spec 关键端点）

> ⚠️ **本节为人工初评**。脚本 `tools/endpoint_health_audit.py` 已落地并跑过完整的 214 端点机器化评级（详见 §9.5），与本节有 13/22 = 59% 不一致 — 实施时**以脚本实测为准**。差异原因详见 §9.5 末尾的"评级 reconciliation"。

基于 prod_data 快照对 spec 涉及的 22 个关键端点进行健康度评级：

| Grade | 含义 |
|---|---|
| A | 数据完整、字段语义清晰、可直接消费 |
| B | 数据可用但需要二次处理（pivot/alias/单位归一） |
| C | 数据部分有效（含 null / 部分字段为 0） |
| D | 数据完全为空或全 0 — 实施前必须先做数据治理 |

| 端点 | Grade | 真实情况 | 影响 spec 章节 |
|---|---|---|---|
| D5_getEquipmentFacilityStatusAnalysis | **A** | 24 行透视，8 状态 × 3 指标完整 | D.3 故障特征 / 设备结构 |
| D5_getEquipmentFacilityAnalysis | **A** | 60 行三维透视完整 | D.3 设备结构 |
| D5_getEquipmentFacilityAnalysisYoy | **A** | 6 行 YoY，资产净值 339 亿合理 | D.3 设备成本 |
| D7_getProductionEquipmentStatistic | **A** | 39 行机种数量分布 | D.3 设备结构（仅数量） |
| D7_getEquipmentIndicatorUseCost | **A** | 10 行一级分类成本 | D.3 设备成本 |
| D7_getEquipmentFirstLevelClassNameList | **B** | 数量级异常需 sanity check (CQ-8) | D.3 设备结构 |
| D7_getProductionEquipmentFaultNum | **B** | 数据存在但与报告不一致 (CQ-7) | D.3 故障特征 |
| D2_getCumulativeRegionalThroughput | **B** | 长表需 pivot (CQ-9) | A.1 KPI 兜底 |
| D1_getThroughputAnalysisYoyMomByMonth | **B** | 6 行 YoY 完整但需理解 yoyQty/momQty 口径 | A.2 同环比 |
| D7_getEquipmentFuelOilTonCost | **B** | 数值 0.1 偏低，需确认单位 | D.3 设备成本 |
| D7_getContainerMachineHourRate | **B** | 数值 10.7 合理（自然箱/小时）| D.3 时间趋势 |
| D5_getMainAssetsInfo | **B** | 未抽样验证，待确认 | D.3 资产视角 |
| D7_getEquipmentUsageRate | **C** | 单位异常 4.3（CQ-3） | D.3 总览/趋势 |
| D7_getEquipmentServiceableRate | **C** | 三月全 1.0 无方差 (CQ-3/4) | D.3 总览/趋势 |
| D7_getEquipmentElectricityTonCost | **C** | tonCost=0.0 (CQ-4 类似) | D.3 设备成本 |
| D7_getMachineDataDisplayEquipmentReliability | **C** | 字段名 usageRate 实为 MTBF (CQ-5) | D.3 可靠性 |
| D7_getNonContainerProductionEquipmentReliability | **C** | 同上 (CQ-5) | D.3 可靠性 |
| D2_getSumBusinessDashboardThroughput | **C** | 50% 字段 null (CQ-1) | A.1 KPI 主源（降级） |
| D5_getOriginalValueDistribution | **D** | 0 行 (CQ-2) | D.3 设备成本 — 必须替换 |
| D6_getFinishProgressAndDeliveryRate | **D** | 1 行全 0 (CQ-2) | D.3 设备成本 — 必须替换 |
| D1_getThroughputAnalysisYoyMomByYear | B | 47 行需理解 statType/dateType 二维 | A.2 同环比 |
| D1_getBusinessTypeThroughputAnalysisYoyMomByMonth | 待验 | 抽样为空 | A.2 同环比 |

**统计**：
- A 级：5 / 22（23%）— 可直接消费
- B 级：8 / 22（36%）— 需二次处理
- C 级：6 / 22（27%）— 数据有问题但可降级使用
- D 级：2 / 22（9%）— **必须替换**或先做数据治理

### 9.3 对原 spec 的修正项

基于 §9.1/9.2/9.5/9.6/9.7，原 spec 的以下设计**必须调整**才能实施（已结合脚本实测）：

| 原 spec 位置 | 修正 |
|---|---|
| §3 A.1 KPI 真值（推荐 D2 主源） | 改为 fallback chain：D2 → D7+D5 兜底；prompt 中明示 "value 字段允许为 '—' 占位" |
| §3 A.0 dataset 持久化 | 落盘格式扩展为 `parquet + meta.json`，meta 复用 prod_data 的 audit 字段 + lineage |
| §3 A.3 字段映射 | `FIELD_DISPLAY_NAMES` 必须支持 `(field, endpoint_id) → label` 二元 key（CQ-5） + alias 表（CQ-6）；脚本实测 `getEquipmentIndicatorUseCost` 等也命中 alias |
| §6 D.3 设备成本章节模板 | D 级端点直接剔除（§2.4 决策），不写到模板源码；primary 用 `getEquipmentFacilityAnalysisYoy` (A 级) + `getEquipmentFacilityAnalysis` (B 级) ；secondary 加入 §9.7 推荐的 `getCostProjectFinishByYear` (A* 待补注册) |
| §6 D.3 故障特征章节 | "投资因果上游"端点 `getFinishProgressAndDeliveryRate` 脚本实测为 A 级但业务无信号（1 行全 0）— **当作 D 级处理**直接从模板剔除；待数据治理后复评再加入 |
| §6 D.3 设备结构章节 TOP_N | "机种利用率 TOP_N" 改为"机种数量 TOP_N"；脚本实测 `getProductionEquipmentStatistic` 是 C 级（CQ-8 + CQ-6），渲染前必须 sanity check |
| §6 D.3 故障特征章节"按设备类型" | 脚本实测 `getProductEquipmentReliabilityByMonth/ByYear` 三重命中（P0_RANGE_RATE + P1_NAME_VS_INTENT + P2_LONG_FORMAT），评级 C 级。MTBF 视角必须配合 A.3 字段映射 + 长表 pivot |
| §附录 A.2 D7 端点描述 | `getProductionEquipmentStatistic` 描述修正为"39 行 × 仅 num/secondLevelName"，删除"含完好率/利用率/役龄"（已修正） |
| §附录 D Planner Prompt | 加入"长表识别提示"：当 assets_summary 中出现重复 typeName 模式时优先用 wide preview。**实测 §9.5 显示长表是 B 级最常见原因** |
| §附录 E Validator | 新增 `validate_data_health`：渲染前检查 dataset 的 null 比例、方差、行数；规则集复用 `tools/endpoint_health_audit.py` 的 10 个触发码 |
| `data/api_registry.json` | 补注册 §9.7 的 2 个端点：`getCostProjectFinishByYear` + `getCostProjectCurrentStageQtyList` |
| §3 批次 A 总工时 | A.0' 已完成；A.0 +0.5 天（datasets + meta + dataset_path 字段）；A.1 升级到 2 天（schema 扩展 + `_inject_values` + format_spec）；A.2 瘦身 0.5 天（schema 已并入 A.1）；A.3 加 endpoint context 二元映射 |

### 9.4 前置任务：A.0' 数据健康度基线 ✅ 已完成

> 状态：脚本 `tools/endpoint_health_audit.py` 已落地，输出 `data/endpoint_health.json`（344 KB）。本节描述实际产出的内容与下游用法。

**实施内容**：

1. 跑一次 `mock_server/prod_data/` 全部 214 份快照的 health check（覆盖 141 注册 + 73 未注册）
2. 输出 `data/endpoint_health.json`（结构：`generated_at / summary / endpoints[]`）
3. **作为 `data/api_registry.json` 的注册准入依据**（§2.4 不变式）：grade ∈ {A, B} 才允许进入 registry
4. **A.0 启动前**先按 §9.6 / §9.7 同步 registry（移除 14 个 D 级 + 补注册 2 个误判 A/B 级）

**脚本健康检查规则**（10 类警告码，对应 §9.1 的 12 个 CQ）：

| 触发码 | 严重度 | 触发条件 | 影响 Grade |
|---|---|---|---|
| `D_EMPTY` | FATAL | data 数组为空 (CQ-2) | D |
| `D_ALL_ZERO` | FATAL | 所有数值字段全 0 (CQ-2) | D |
| `D_NON_TABULAR` | FATAL | data 非表格结构 | D |
| `P0_HIGH_NULL` | P0 | numeric 字段 null > 30% (CQ-1) | C |
| `P0_NO_VARIANCE` | P0 | numeric 字段方差 = 0 (CQ-4) | C |
| `P0_RANGE_RATE` | P0 | rate 字段不在 [0, 1] ∪ [0, 100] (CQ-3) | C |
| `P1_NAME_VS_INTENT` | P1 | usageRate 字段但 intent 含 MTBF/可靠性 (CQ-5) | C |
| `P1_QUANTITY_LOW` | P1 | num 字段值 < 10 + 类目字段 (CQ-8) | C |
| `P2_LONG_FORMAT` | P2 | 检测到长表（重复透视维度）(CQ-9) | B |
| `P2_FIELD_ALIAS` | P2 | 用 firstLevelName 而非 firstLevelClassName (CQ-6) | B |
| `P2_PARAMS_DRIVEN` | P2 | 必传 secondLevelClassName 等单值参数 (CQ-12) | B |

**修正后总工时**：~~13-15 天~~（A.0' 基线已完成，**回到 12-14 天**）。

### 9.5 实测结果概览（脚本输出）

```
ENDPOINT HEALTH AUDIT — 2026-05-06
========================================
总计: 214 端点 (注册 141 + 未注册 73)

Grade 分布:
  A:  69  (reg=68, unreg=1)   32%
  B:  44  (reg=43, unreg=1)   21%
  C:  16  (reg=16, unreg=0)    7%
  D:  85  (reg=14, unreg=71)  40%
```

**Domain × Grade 矩阵**：

| Domain | A | B | C | D | 总数 | D 级占比 |
|---|---|---|---|---|---|---|
| D1 生产运营 | 17 | 17 | 0 | 18 | 52 | 35% |
| D2 市场商务 | 10 | 2 | 2 | 7 | 21 | 33% |
| D3 客户管理 | 5 | 3 | 0 | 12 | 20 | 60% |
| D4 投企管理 | 1 | 0 | 0 | 6 | 7 | **86%** ⚠️ |
| D5 资产管理 | 6 | 9 | 1 | 23 | 39 | **59%** ⚠️ |
| D6 投资管理 | 16 | 4 | 2 | 9 | 31 | 29% |
| D7 设备子屏 | 14 | 9 | 11 | 10 | 44 | 23% ✅ 最好 |

**关键统计**：
- **可直接用的端点：A+B = 113 / 214 = 53%** — 这是 perception 层的"白名单"基础
- **必须治理的端点：D 级 85 个**（其中 14 个已注册 = 治理债，详见 §9.6）
- **97% 未注册端点判断正确**：73 个里 71 个确实是 D 级（详见 §9.7）

**与 §9.2 人工评级的 reconciliation**：

13/22 端点的脚本评级与 §9.2 不一致。原因分两类：

| 类别 | 数量 | 典型例子 |
|---|---|---|
| 脚本评级**比 §9.2 严格**（脚本检出新问题）| 6 个 | `getProductionEquipmentStatistic`：脚本 C（CQ-8 数量异常 + CQ-6 字段 alias），§9.2 漏看 |
| 脚本评级**比 §9.2 宽松**（脚本规则不够严）| 7 个 | `getEquipmentUsageRate`：脚本 A（4.3 通过 0-105 区间检查），§9.2 标记 C（4.3% 不真实） |

**实施决策**：
- **脚本严格的部分（P2_LONG_FORMAT / P2_FIELD_ALIAS / P1_QUANTITY_LOW）→ 以脚本为准**，spec 之前漏看
- **脚本宽松的部分（业务上不合理但通过区间检查）→ 维持 §9.2 评级 + 长期补 sanity rule**，例如：
  - `getEquipmentUsageRate` (4.3/5.2/5.5)：脚本 A，业务上 C（详见 §9.8）
  - `getFinishProgressAndDeliveryRate` (1 行非全 0)：脚本 A，业务上 D（无业务信号）
  - 计划在脚本 v2 增加"窄区间检查"：rate 类字段用 [0.1, 1.0] ∪ [10, 100] 而非现在的宽区间

### 9.6 14 个已注册 D 级端点（治理债清单）

这些端点已在 `api_registry.json` 注册，但 prod_data 显示数据空或全 0 — **违反 §2.4 不变式**（注册 = 可用），必须立即从 registry 移除。

> **执行动作**：A.0 启动前完成本节清单，跑 `tools/sync_registry.py --remove` 把这 14 个端点从 `data/api_registry.json` 移除，再跑 `tools/seed_api_endpoints.py` 推到 DB。完成后 perception/planning/outline_planner 不再看到这些端点，spec 实施过程中**不需要任何运行时过滤**。

| Domain | 端点 | 数据情况 | 替代方案（如有相关章节需要） |
|---|---|---|---|
| D5 | `getOriginalValueDistribution` | 0 行 | D.3 设备成本资产视角用 `getEquipmentFacilityAnalysisYoy` (A) |
| D5 | `getMainAssetsInfo` | 0 行 | 资产视角用 `getEquipmentFacilityAnalysis` (B) |
| D5 | `getRealAssetsDistribution` | 0 行 | 资产盘点用 `getCategoryAnalysis` (A) |
| D5 | `getTotalssets` | 1 行 | 总览类 KPI 走其他 A 级端点 |
| D6 | `getPlanFinishByZone` | 5 行全 0 | D.3 投资因果视角用 `getCostProjectFinishByYear` (A*，待补注册) |
| D3 | `getCurContributionRankOfStrategicCustomer` | 37 行全 0 | 客户专题报告（非本 spec 范围）受影响 |
| D3 | `getCurStrategicCustomerContributionByCargoTypeThroughput` | 4 行全 0 | — |
| D3 | `getSumContributionRankOfStrategicCustomer` | 37 行全 0 | — |
| D3 | `getSumStrategicCustomerContributionByCargoTypeThroughput` | 4 行全 0 | — |
| D4 | `getBusinessExpirationInfo` | 0 行 | spec 已排除 D4 域 |
| D4 | `getMeetDetail` | 0 行 | 同上 |
| D4 | `getNewEnterprise` | 0 行 | 同上 |
| D4 | `getSupervisorIncidentInfo` | 0 行 | 同上 |
| D4 | `getWithdrawalInfo` | 0 行 | 同上 |

**未来恢复路径**：数据治理后重跑 `tools/endpoint_health_audit.py` → 升级到 A/B → 走标准注册流程重新加入 registry → 才能在章节模板里引用。**不做"留个划线占位等以后启用"**。

### 9.7 73 个未注册端点的复核结论 + Registry 同步净变化

先前判断这 73 个端点"线上无数据"。脚本复核：

| 结论 | 数量 | 占比 |
|---|---|---|
| ✅ 维持未注册（D 级，确认无数据）| 71 | **97%** |
| ❌ 误判，必须补注册 | 2 | 3% |

**必须补注册的 2 个端点**（A.0 启动前完成）：

| 端点 | Domain | Grade | 行数 | Intent | 建议章节 |
|---|---|---|---|---|---|
| `getCostProjectFinishByYear` | D6 | **A** | 2 | 查询近 5 年成本性项目完成情况 | D.3 设备成本投资因果视角 |
| `getCostProjectCurrentStageQtyList` | D6 | **B** | 16 | 查询成本性项目当前阶段数量（立项/招标/施工/竣工）| 投资进度报告 |

#### Registry 同步净变化

执行 §9.6 + §9.7 后，`data/api_registry.json` 的净变化：

| 动作 | 数量 | 来源 |
|---|---|---|
| 移除已注册的 D 级端点 | -14 | §9.6 |
| 补注册误判的 A/B 级端点 | +2 | §9.7 |
| **净变化** | **-12** | 141 → **129** |

同步后 `api_registry.json` = 129 个端点，全部 grade ∈ {A, B}。**§2.4 不变式成立**。

**71 个 D 级未注册端点的 domain 分布**：
- D1 生产运营: 18  /  D2 市场商务: 7  /  D3 客户管理: 8
- D4 投企管理: 1  /  D5 资产管理: 19  /  D6 投资管理: 8  /  D7 设备子屏: 10

→ 其中 D5 资产管理 19 个未注册 D 级端点（多为单设备明细查询，需特定参数才有数据），与 D5 已注册 23 个 D 级端点合计 **42 个 D5 域 D 级端点** — D5 域是数据治理最大的负担。

### 9.8 长期改进项（非阻塞，无外部协作也能交付）

> **现实约束**：当前阶段数据团队 / API 团队的工单响应不可期。本节所有项都在 spec 内有"代码侧应对"，**没响应也不影响交付**。响应了能进一步提升数据质量。

| # | 长期改进项 | spec 内代码侧应对（不依赖外部） |
|---|---|---|
| 1 | §9.6 14 个 D 级端点排查（数据可恢复后才考虑重新加入 registry） | A.0 启动前从 registry 移除（§2.4 不变式），spec 已为每个 P0 给出 A/B 级替代 |
| 2 | `getEquipmentUsageRate.usageRate=4.3` 单位口径不符 | A.0 持久化时 health 脚本打 `quality_flag=suspicious_unit`；A.1 渲染层在该数字旁加"⚠️ 数据可疑"小标 + endpoint 来源；用户自溯源判断 |
| 3 | `getEquipmentServiceableRate=1.0` 长期 100% | A.0 持久化打 `quality_flag=no_variance`；C.1 渲染层据此降级（不画无方差趋势线，改为单一数值卡片）|
| 4 | `usageRate` 字段名实为 MTBF | A.3 字段映射用 `(field, endpoint_id) → display_name` 二元 key，spec 内自己映射，不等 API 改字段名 |
| 5 | 故障数 endpoint(859) ≠ 报告图表(1406) ≠ KPI(47) | A.1 全数字溯源，三个数字旁分别可见来源 endpoint，用户能看出哪条数据流"对" |
| 6 | D5 域 42 个 D 级端点集中治理 | spec 已知 D5 是治理最重的 domain，章节模板对 D5 的依赖最小，主要靠 D7 |
| 7 | 脚本 v2 窄区间 sanity rule | 自维护，本仓库内即可改 `tools/endpoint_health_audit.py`，不需要外部 |

**结论**：spec 实施的关键路径上，零外部依赖。如未来某 D 级端点被治理后恢复数据，重跑 audit 升级评级，再走 §2.4 标准注册流程加入 registry。**不需要改业务代码、不需要解除"运行时拉黑"（因为根本没有这个机制）**。

---

## 附录 A — 6 Domain 维度覆盖矩阵

### A.1 各 Domain 概览

| Domain | 名称 | 端点数 | 主时间维度 | 主分组维度 | 与设备运营报告相关性 |
|---|---|---|---|---|---|
| D1 | 生产运营 | 34 | T_RT/T_TREND/T_YOY | G_ZONE/G_BIZ/G_PORT | ⭐⭐⭐⭐ 业务上下文 |
| D2 | 市场商务 | 14 | T_MON/T_CUM/T_YOY | G_PORT/G_ZONE/G_BIZ/G_CLIENT | ⭐⭐⭐ KPI 真值 |
| D3 | 客户管理 | 12 | T_NONE/T_MON/T_HIST | G_CLIENT/G_CARGO | ⭐ 低 |
| D4 | 投企管理 | 6 | T_NONE/T_YR/T_MON | G_CMP | ⭐ 几乎无关 |
| D5 | 资产管理 | 20 | T_YR/T_NONE/T_YOY | G_ZONE/G_ASSET | ⭐⭐⭐⭐ 资产视角 |
| D6 | 投资管理 | 21 | T_YR/T_YOY/T_HIST | G_ZONE/G_PORT/G_PROJ | ⭐⭐⭐ 因果上游 |
| D7 | 设备子屏 | 34 | T_MON/T_YR/T_HIST | G_ZONE/G_EQUIP | ⭐⭐⭐⭐⭐ 主体 |

### A.2 D7 设备子屏关键端点（34 个，按用途分类）

| 用途 | 关键端点 | 时间×维度 | 下钻参数 |
|---|---|---|---|
| 月度可用率 | `getEquipmentUsageRate`、`getProductEquipmentUsageRateByMonth` | T_YR / G_ZONE | `ownerLgZoneName`、`firstLevelClassName` |
| 月度完好率 | `getEquipmentServiceableRate`、`getProductEquipmentIntegrityRateByMonth` | T_YR / G_ZONE | 同上 |
| 月度故障数 | `getProductionEquipmentFaultNum` | T_YR / G_ZONE | 仅港区 |
| 月度作业量 | `getQuayEquipmentWorkingAmount`、`getProductEquipmentWorkingAmountByMonth` | T_MON / G_ZONE | 同上 |
| 机时效率 | `getContainerMachineHourRate` | T_YR / G_ZONE | 同上 |
| 历年对比 (5 年) | `*ByYear` 系列 5 个 | T_HIST / G_ZONE | 同上 |
| **机种数量分布** | `getProductionEquipmentStatistic`（39 行 × 仅 `num`+`secondLevelName`，**不含完好率/利用率/役龄**，详见 §9.1 CQ-10）| T_MON / G_EQUIP | secondLevelName |
| 设备结构 | `getEquipmentFirstLevelClassNameList` | T_YR / G_ZONE | — |
| MTBF/MTTR | `getMachineDataDisplayEquipmentReliability`（集装箱）+ `getNonContainerProductionEquipmentReliability` | T_YR / G_EQUIP | 必须指定机种 |
| 能耗/燃油/电量 | `getEquipmentEnergyConsumptionPerUnit`、`getEquipmentFuelOilTonCost`、`getEquipmentElectricityTonCost` 等 4 个 | T_YR / G_ZONE | 港区+一级分类 |

### A.3 D5 资产管理关键端点（20 个，本次报告完全没用）

| 用途 | 关键端点 | 价值 |
|---|---|---|
| **设备资产专题（6 个）** | `getEquipmentFacilityAnalysis`、`getEquipmentFacilityAnalysisYoy`、`getEquipmentFacilityStatusAnalysis`、`getEquipmentFacilityWorthAnalysis`、`getEquipmentFacilityRegionalAnalysis` | 数量/净值同比、**状态分布（正常/维修/超期/闲置）**、净值区间分布 |
| 资产分布 | ~~`getOriginalValueDistribution`~~（D 级治理债，§9.6）、`getCategoryAnalysis` | 各类资产原值占比 |
| 港区对比 | `getRegionalAnalysis` | 各港区资产对比 |

⚠️ D5 全部 T_YR/T_NONE/T_YOY，**无月度** — 月度趋势必须靠 D7。

### A.4 D2 市场商务关键端点（KPI 真值来源）

| 用途 | 关键端点 | 价值 |
|---|---|---|
| **商务 KPI 仪表盘** | `getSumBusinessDashboardThroughput`、`getCumulativeRegionalThroughput` | 直接返回"计划/实际/去年同期/增速/完成进度"五元组 |
| 当月/累计吞吐 | `getMonthlyThroughput`、`getCumulativeThroughput` | 同比专用 |
| 重点企业 Top10 | `getKeyEnterprise`、`getCumulativeKeyEnterprise` | "客户拉动"视角 |

### A.5 D6 投资管理关键端点（设备成本因果上游）

| 用途 | 关键端点 | 价值 |
|---|---|---|
| 投资同比 | `planInvestAndPayYoy`、`getCostProjectYoyList` | T_YOY 专用 |
| 完成进度/交付率 | ~~`getFinishProgressAndDeliveryRate`~~（D 级治理债，§9.6）、`getDeliveryRate` | 解释成本结构变化原因 |
| 项目类型分布 | `getPlanFinishByProjectType` | 对接设备资产分类 |

### A.6 维度覆盖矩阵（D7 为主）

| 下钻维度 | 参数名 | D7 覆盖端点数 | 覆盖率 |
|---|---|---|---|
| 港区 | `ownerLgZoneName` / `ownerZone` | 31/34 | **91%** ✅ |
| 一级分类（装卸/运输/起重/输送/特种） | `firstLevelClassName` | 14/34 | **41%** ⚠️ |
| 公司 | `cmpName` | 19/34 | 56% |
| 时间·月 | `dateMonth` | 24+ | ✅ |
| 时间·年 / 同比 | `dateYear` / T_YOY | 12 / 12 | ✅ |
| **机种聚合** | `secondLevelName` | **仅 1 个** | **3%** ❌ |
| 机种维度查询 | 必须指定单机种 | 9 个 | 需两阶段 |

---

## 附录 B — 报告类型 × Domain 配置表

| 报告类型 | 主 domain | 辅 domain | 上下文 domain | 建议端点配额 | 典型章节 |
|---|---|---|---|---|---|
| 设备运营 | D7 (4) | D5 (2), D6 (1) | D1 (2), D2 (1) | 共 10-12 | 总览/趋势/结构/成本/故障/可靠性/联动 |
| 业务运营 | D1 (4) | D2 (2) | D3 (1), D7 (2) | 共 8-10 | 总览/吞吐/船舶/泊位/客户/设备 |
| 商务驾驶舱 | D2 (4) | D3 (2) | D1 (1) | 共 6-8 | KPI/重点企业/业务板块/同比 |
| 客户专题 | D3 (5) | D2 (2) | — | 共 6-8 | 客户结构/战略客户/货类贡献/排名 |
| 资产盘点 | D5 (5) | D6 (2) | D7 (2) | 共 8-10 | 总量/原值/分布/状态/同比 |
| 投资进度 | D6 (5) | D5 (2) | — | 共 6-8 | 计划/完成/交付率/同比/计划外 |
| 投企治理 | D4 (4) | — | — | 共 4-6 | 持股/议案/新设/退出/到期 |

---

## 附录 C — 章节模板库设计（设备运营报告 7 章节）

> 端点 grade 标记说明：A = 数据完整可直接用 | B = 需二次处理（pivot/alias）| C = 数据有问题但可降级 | A* = 待补注册的 A 级。以 `data/endpoint_health.json` 实测为准（见 §9.5）。
>
> **D 级端点不出现在本表 / 章节模板源码 / 任何 endpoint_candidates 中**（详见 §2.4）。D 级端点的完整清单见 §9.6 治理债。

| 章节 | role | metric_focus | required_intents | 端点候选（primary/secondary/context，附 grade）|
|---|---|---|---|---|
| 1. 运营总览 | summary | usageRate, serviceableRate, throughput | yoy_compare | D2: `getSumBusinessDashboardThroughput`(C) / D7: `getEquipmentUsageRate`(A 但单位疑问 §9.1 CQ-3), `getEquipmentServiceableRate`(C 无方差) |
| 2. 时间趋势 | analysis | usageRate, throughput, faultNum | single_metric_trend, correlation | D7: `getProductEquipmentUsageRateByMonth`(A), `getProductEquipmentReliabilityByMonth`(C 字段名错用) / D1: `getThroughputAnalysisByYear`(A) |
| 3. 设备结构分析 | status | secondLevelName, firstLevelClassName, status | breakdown_by_dim, top_n | D7: `getProductionEquipmentStatistic`(C 仅含数量 §9.1 CQ-10) / D5: `getEquipmentFirstLevelClassNameList`(B), `getEquipmentFacilityStatusAnalysis`(B 长表) |
| **4. 设备成本分析** | analysis | originalValue, useCost, fuelCost | single_metric_trend, yoy_compare, breakdown_by_dim | **subsections 三视角并列设计（D.3 决策）**：<br>① **资产视角**（按 assetTypeName）：D5: `getEquipmentFacilityAnalysisYoy`(A), `getEquipmentFacilityAnalysis`(B 长表)<br>② **运营消耗视角**（按 firstLevelName）：D7: `getEquipmentIndicatorUseCost`(B 字段 alias), `getEquipmentElectricityTonCost`(A)<br>③ **投资因果视角**（按 dateYear）：D6: `getCostProjectFinishByYear`(A*，待补注册)<br>**diff_note**: "三视角分类口径不一致，不跨表对照" |
| 5. 故障特征分析 | attribution | faultNum, MTBF, MTTR, status | single_metric_trend, breakdown_by_dim, anomaly_detect | D7: `getProductionEquipmentFaultNum`(A) / D5: `getEquipmentFacilityStatusAnalysis`(B) / D1: `getRealTimeWeather` |
| 6. 业务-设备联动（新增） | analysis | shipEfficiency, machineHourRate, throughput | correlation, single_metric_trend | D1: `getProductViewShipOperationRateAvg`, `getBerthOccupancyRateByRegion` / D7: `getContainerMachineHourRate`(A) |
| 7. 可靠性专项（新增） | analysis | MTBF, MTTR, faultNum | top_n, breakdown_by_dim | D7: `getMachineDataDisplayEquipmentReliability`(C 字段错用), `getNonContainerProductionEquipmentReliability`(C 字段错用) — 必须配合 A.3 字段映射纠正显示名 |

---

## 附录 D — Planner Prompt 增量约束清单

在 `_planner_prompts.py` 现有 `_OUTPUT_SCHEMA_DOC` 之后追加：

```
## KPI 严格规则 (PR-3 新增)
- 每个 KPI 必须基于 assets 中的真实数据
- source_asset_id 必填，引用必须存在于「可用 assets」
- value 字段不要自己写数字，留给后端填充（保持空字符串或占位符）
- agg 字段从 {latest, mean, sum, yoy, qoq} 中选择

## growth_indicators 严格规则 (PR-3 新增)
- growth_rates 字段必须从「后端预算 growth assets」引用
- 不要自己计算 yoy/mom 数值
- 后端会注入 {col: {yoy: 小数, mom: 小数}}，你只负责挑选展示哪些列
- 单位口径：小数形式 [-1.0, 1.0]，渲染时后端 ×100

## 章节内容多样性约束 (PR-3 新增)
- 每个 analysis 类章节必须覆盖至少 2 种不同的 analysis_intent
- 不同章节的 (metric_focus, group_by) 组合不可完全重复
- 章节配图的 metric 须与 metric_focus 一致

## 跨 domain 协作约束 (PR-3 新增)
- 优先使用 domain_role=primary 的 asset 作为主图
- secondary domain 的 asset 用于补充对比或上下文
- 一个章节可引用 ≤2 个 domain 的 asset

## AnalysisIntent 枚举 (PR-3 新增)
- single_metric_trend : 单指标时间趋势（line）
- breakdown_by_dim   : 单维下钻（bar/pie）
- crosstab_2d        : 二维透视（heatmap/stacked bar/grouped bar）
- yoy_compare        : 同比对比（双轴 line/grouped bar）
- correlation        : 相关性（scatter/双轴 line）
- anomaly_detect     : 异常检测（line + 异常点标注）
- top_n              : Top N 排名（横向 bar）
```

---

## 附录 E — Validator 规则集

复用 PR-2 `validate_chart_title` 的"约束 + validator + 重试"模式。新增以下 validator：

| Validator | 触发条件 | 行为 | 上限 |
|---|---|---|---|
| `validate_kpi_source` | KPI 缺 `source_asset_id` 或引用不存在 | 重试 LLM | 3 次，超限降级为不显示该 KPI |
| `validate_growth_unit` | `abs(yoy) > 2.0` 或 `abs(mom) > 2.0` | 重试 LLM 让其换数据源 | 3 次，超限不展示该 growth_indicator |
| `validate_intent_coverage` | analysis 章节 intent 覆盖 < 2 种 | 重试 LLM | 2 次，超限警告并展示 |
| `validate_section_uniqueness` | 两章节 (metric_focus, group_by) 完全重叠 | 重试 LLM | 2 次，超限保留首个 |
| `validate_metric_chart_match` | 章节 metric_focus 与图表 metric 不一致 | 重试 LLM | 2 次，超限替换为占位 |
| `validate_domain_diversity` | 整份报告跨 domain < 3（仅 full_report 类型） | 重试 perception 层 | 1 次 |

### E.1 重试粒度与累计上限（关键）

**重试范围 = 整份 outline 重生成**。outline planner 的最小 LLM 调用粒度就是一次性产出所有 section 的所有 block，没有"只重生成某个 section"的能力（pattern 继承自 PR-2 的 `validate_chart_title`）。

含义：
- 一次重试 = 一次完整 LLM 调用（约 3-5k tokens）
- 重试可能改变之前正确的部分（不保证单调收敛）
- 上表 6 个 validator 各自的"重试上限"是独立计数 — **总和最多可达 18 次 LLM 调用**

**全局上限**（必须实施）：
```python
MAX_TOTAL_OUTLINE_RETRIES = 6   # 整份 outline 重生成的累计上限
```

任何 validator 触发重试时累计 +1，达到 6 次后**所有未通过的 block 直接降级**（KPI 不显示 / growth_indicator 不渲染 / 章节用文字替代图）。

理由：
- 6 次重试 ≈ 18-30k tokens 的额外开销，已是单次报告生成 token 预算的 1.5-2 倍
- 超过 6 次仍不收敛说明 prompt 或数据有结构性问题，应该看日志手工排查，不是继续 burn token
- 单 validator 重试上限保留作为"局部信号"，全局上限保留作为"成本闸门"

**日志要求**：每次重试在 [`backend/tracing.py`](backend/tracing.py) 写入 `outline_retry` 事件，含触发 validator + 失败原因 + 累计次数，方便事后追因。

---

## 附录 F — 现网真实任务取样数据

### F.1 取样 1：throughput_analyst_monthly_review (20260421_104336)

| 字段 | 值 |
|---|---|
| 任务总数 | 18 |
| data_fetch | 10（全 D1/D2 吞吐量端点） |
| analysis | 3（skill_desc_analysis × 2, skill_attribution × 1） |
| visualization | 3 |
| report_gen | 2 |
| LLM tokens | 3,687 (prompt) + 1,708 (completion) |
| 跨 domain | ❌ 单 domain（D1/D2 算同 family） |
| 数据量 | T001=1, T003=16, T005=54 |

### F.2 取样 2：asset_investment_equipment_ops (20260421_112459)

| 字段 | 值 |
|---|---|
| 任务总数 | 18 |
| data_fetch | 15 |
| analysis | 3（attribution timeout） |
| visualization | 1 |
| 失败率 | 1/18 |
| 跨 domain | ❌ 单 domain（D5） |

### F.3 取样 3：throughput_analyst_monthly_review (20260421_112459)

| 字段 | 值 |
|---|---|
| 任务总数 | 10 |
| data_fetch | 10 |
| analysis | 0 |
| LLM tokens | 0 |
| 备注 | 简化版/数据探查类 |

### F.4 假设验证总表

| 假设 | 真实情况 | 原方案修正 |
|---|---|---|
| 任务数 4-8 个 | 实际 10-18 个 | 批次 D 不再加任务数，改加 intent/domain 多样性 |
| 全集中单一 domain | ✅ 跨 domain = 0 | 必须在 perception 层动（D.1） |
| KPI 是 LLM 编的 | ✅ 已证实 | 批次 A.1 必须做 |
| 跨章节复用 dataset | ✅ 已证实 | 批次 B.3 去重必要 |
| 同环比由 LLM 产出 | ✅ 已证实 | 批次 A.2 走后端预算 |
| **dataset 持久化** | ❌ 不存原始 dataset | **A.0 前置必做** |

---

## 附录 G — 前端集成评估

| 维度 | 状态 | 对批次 D 的影响 |
|---|---|---|
| 前端框架 | React + TypeScript + Vite + Tailwind + ECharts 6 | — |
| 报告渲染 | 后端模板渲染 HTML，前端 iframe 预览 | 后端可自由演进 |
| 新 chart_type 支持 | `option: Record<unknown>` 无类型白名单 | **零阻塞** |
| KPI 卡片组件 | 当前无独立组件 | 可走 `file` 兜底，或扩展 `output_type: 'kpi'`（≤50 行） |
| 多轮对话与报告耦合 | 完全解耦 | 后端自由迭代 |
| 关键文件 | `frontend/src/types.ts:214-256`、`components/ui/TaskResultCard.tsx`、`components/ui/ChartView.tsx` | 仅契约定义需同步 |

**结论**：批次 D 不会被前端卡住。

---

## 附录 H — 文件清单（需改动）

### 后端

| 文件 | 改动批次 | 改动概要 |
|---|---|---|
| `backend/models/schemas.py` | A.1, B.1, D.1, D.2 | 加 `AnalysisIntent`、`ReportType`、`SectionDefinition` 扩展 |
| `backend/tools/report/_outline.py` | **A.1** | `KPIItem` 加 `source_asset_id/agg/format_spec`；`GrowthIndicatorsBlock.growth_rates` 改为 `dict[str, GrowthCell]`；新增 `GrowthCell` dataclass；`ChartAsset/TableAsset/StatsAsset` 加 `dataset_path` |
| `backend/agent/planning.py` | D.1 | `PLANNING_PROMPT` 加报告类型识别 + domain 路由；**`_stitch_plan` (line 1295) 改为完整透传 sections 全字段**；**`_sanitize_report_structure` (line 479) 改为白名单清洗保留 D.1/D.3 metadata** |
| `backend/agent/_complexity_rules.py` | D.1 | 改约束维度（intent/domain 覆盖率） |
| `backend/tools/report/_planner_prompts.py` | A.1, A.2, D.2 | 数据溯源严格规则 + 单位口径契约 + PR-3 约束 |
| `backend/tools/report/_outline_planner.py` | **A.1**, B.2, D.3 | 新增 `_inject_values()`（在 `_deduplicate_chart_blocks` 之后调用）、章节模板加载 |
| `backend/tools/report/_value_format.py` | **A.1 新增** | KPI value 格式化（percent/int/currency/large_number 等 7 种 format_spec）|
| `backend/tools/report/_content_collector.py` | A.0, A.2, B.2 | dataset 持久化（含 `dataset_path` + `quality_flags` + `endpoint_grade`）、growth assets 预算、强匹配 `_associate()` |
| `backend/tools/report/_field_labels.py` | A.3 | `(field, endpoint_id) → display_name` 二元 key + alias 表 |
| `backend/tools/report/_section_templates.py` | D.3 | **新增** 章节模板库；endpoint_candidates 只能引用 `data/api_registry.json` 中已注册的端点（自然不含 D 级，因为 D 级在 §9.6/§9.7 注册同步阶段已被移除）|
| `data/api_registry.json` | **A.0 前置** | 移除 §9.6 列出的 14 个 D 级端点；补注册 §9.7 的 2 个 A/B 级误判端点；净变化 -12（141 → 129）|
| `tools/sync_registry.py`（可选）| A.0 前置 | 新增辅助工具：读 `endpoint_health.json` + 当前 `api_registry.json`，输出"应移除 / 应新增"差异，人工 review 后应用 |
| `backend/tools/analysis/_metric_sanity.py` | **A.0 新增** | 指标合理区间表（rate ∈ [0,1] ∪ [0,100] 等），输出 quality_flags |
| `backend/tools/analysis/descriptive.py` | D.4 | 二维 group_by |
| `backend/tools/analysis/anomaly.py` | D.4 | 实装 z-score / IQR |
| `backend/tools/analysis/comparison.py` | D.4 | **新增** YoY/跨组/计划实际 |
| `backend/tools/report/_renderers/htmlgen.py` | A.1, A.2 | 数据 block 来源标注（asset.endpoint）、quality_flag 警示、单位末端 ×100 |
| `backend/tools/report/_renderers/docxgen.py` | A.1, A.2 | 同上 |
| `backend/tools/report/_renderers/pptxgen.py` | A.1, A.2, C.1, C.2 | 同上 + `_render_section_combo` 改造、appendix 幂等 |
| `backend/tools/report/_chart_renderer.py` | D.4 | heatmap / stacked bar 路由 |

### 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/types.ts` | （可选）`TaskOutputKind` 加 `'kpi'` |
| `frontend/src/components/ui/TaskResultCard.tsx` | （可选）KPI 分支 |

---

## 附录 I — 未决问题与开放讨论

### I.1 已决（保留作为决策记录）

| # | 问题 | 决策 |
|---|---|---|
| 1 | KPI / 数据字段映射要不要在 spec 里穷举？ | **不穷举**。让 LLM 选 endpoint，错的通过调 prompt 或 endpoint 候选清单纠正。前提：每个数据 block 必须 source_asset_id 可见溯源（block 级粒度，非 cell 级）|
| 2 | 多 endpoint 字段对不上怎么办？ | **不强行合表**。subsections 并列展示 + 章节末尾 `diff_note` 显式说明口径差异 |
| 3 | 怎么知道改对了（回归测试）？ | **靠"全数字可溯源 + 抽样肉眼检查"**。不写"金标测试集"。错的字段一眼能看出来自哪个 endpoint，反推去调 prompt 或候选清单 |
| 4 | endpoint_quota 是硬约束还是软建议？ | **硬约束**。配额不合适就改配额本身 |

### I.2 待定

1. **D.1 报告类型识别准确率不达标怎么办？**
   候选方案：用户在多轮对话中显式声明报告类型（"我要做设备运营月报"）；或在 perception 层预设关键词字典 + LLM 兜底双层。

2. **章节模板库的维护成本？**
   每新增一种报告类型需要写一份模板。先只做 EQUIPMENT_OPS（覆盖当前主场景），其他类型按需扩展。

3. **二维 crosstab 的 LLM 选择能力？**
   crosstab_2d intent 对 LLM 的要求较高（需要选对 row/col/value），可能需要在 prompt 里给具体示例。

4. **anomaly_detect 与 LLM 归因的衔接？**
   anomaly 输出"异常点列表"后，LLM 是否能正确把它写进归因表的"数据依据"列？需要 D.2 prompt 中显式指引。

5. **`D5_getMainAssetsInfo` 评级 B 但未抽样验证** — 实施 D.3 资产视角时验证。

6. **dataset 持久化的清理策略**（A.0 落 parquet 何时删，磁盘占用如何控制）— 实施 A.0 时定。

7. **PPTX 合页阈值**（"chart > 2 或 narrative > 200 字"的 200 凭感觉）— 实施 C.1 时按真实测试用例调。

8. **anomaly z-score 阈值**（默认 2.0 对港口数据可能不合适）— 实施 D.4 时按 metric 设阈值表。

---

> **下一步**：评审本 spec → 拆分 PR 分支推进（建议从 Week 1 的 A.0 / A.1 同时开两个分支启动）。
