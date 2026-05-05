# tool_anomaly 异常检测技能 — 实施方案

**目标读者**：Claude Code 执行实例（无本会话上下文）
**作者**：异常检测调研沉淀（2026-05-02）
**状态**：📋 待启动
**前置依据**：`backend/tools/analysis/descriptive.py`（同骨架参考）、`data/api_registry.json`（141 端点数据形态摸底）

---

## 0. Mission

把 `backend/tools/analysis/anomaly.py` 从**返回固定空结果的 stub**（22 行）落地为**贴合本数据集形态的可解释异常检测技能**，与 `tool_desc_analysis` 同体量、同复用基建。

**核心目标**：
1. 真正能在月度趋势 / 多实体序列 / 截面排名 / KPI 进度等 5 类形态上发现异常点
2. 基于 LLM 给出原因推测（而非仅吐统计数）
3. 复用 `_column_selector` / `_data_summarizer` / `invoke_llm` / `_src_ref` 多源拆分等已有基建
4. 与 `tool_desc_analysis` 输出风格一致，可被 `tool_summary_gen` / `tool_chart_*` 顺畅消费

**非目标**：
- ❌ 不引入 ARIMA / STL / Prophet / Isolation Forest 等需要长序列或大样本的算法（本数据集普遍 ≤16 月度点，不适用）
- ❌ 不重新发明同环比计算（32 个端点已自带 yoyQty/momQty）
- ❌ 不做实时流式 / 在线学习

---

## 1. 当前状态实测

### 1.1 实现层（22 行 stub）

`backend/tools/analysis/anomaly.py`:
```python
@register_tool("tool_anomaly", ToolCategory.ANALYSIS, "异常值检测",
                input_spec="数据序列 data_ref",
                output_spec="异常点及原因推测 JSON")
class AnomalyDetectionTool(BaseTool):
    async def execute(self, inp, context):
        return ToolOutput(
            tool_id=self.tool_id,
            status="partial",
            output_type="json",
            data={"anomalies": [], "method": "stub", "note": "异常检测功能尚未完整实现"},
            metadata={"stub": True},
        )
```

### 1.2 编排层（已 100% 接入，无需改动）

| 项 | 位置 | 内容 |
|---|---|---|
| 复杂度规则 | `backend/agent/_complexity_rules.py:79` | `simple_table` 禁止；`chart_text` / `full_report` 允许 |
| Planning 提示 | `backend/agent/planning.py:191` | "当用户问『异常/反常/突变』时使用" |
| 员工权限 | `employees/throughput_analyst.yaml:15`、`customer_insight.yaml:36`、`asset_investment.yaml:82` | 三个 employee 均授权 |
| 契约测试 | `tests/contract/test_complexity_rules.py:53,87,106` | 三个复杂度级别允许/禁止矩阵 |
| Spec 收录 | `spec/refactor_complexity_boundary.md:268`（"盲点 1 修复"） | 已记入 |

→ **本次只改实现层**，编排/规则/权限/测试矩阵全部复用。

### 1.3 当前问题
LLM 规划出 `tool_anomaly` 任务时拿到 `anomalies: []` + `stub: True`，`status="partial"` 不报错也不告警，下游静默吞掉用户的"异常"诉求。

---

## 2. 数据形态摸底（来自 `data/api_registry.json`）

### 2.1 时间码分布
| 时间码 | 数量 | 含义 |
|---|---|---|
| T_YR | 45 | 年度快照 |
| T_MON | 24 | 月度快照（单月） |
| T_TREND | 15 | 区间趋势（startDate/endDate） |
| T_NONE | 14 | 无时间维度 |
| T_CUM | 12 | 累计 |
| T_YOY | 12 | 已含同比/环比字段 |
| T_RT | 9 | 实时 |
| T_HIST | 9 | 历史 |
| T_DAY | 1 | 日度 |

### 2.2 粒度分布
G_ZONE 52 / G_PORT 35 / G_CMP 11 / G_CLIENT 11 / G_EQUIP 11 / G_ASSET 7 / G_BIZ 6 / G_PROJ 5 / G_CARGO 2 / G_BERTH 1。

→ 多数端点带"实体维度"（港区/公司/客户/设备），异常的真正业务意义往往是"哪个实体在哪个时点突变"。

### 2.3 关键事实
- **序列极短**：T_TREND 端点典型 4-16 月度点，机器学习/分解类几乎不可用
- **业务自带同环比**：32 个端点直接返回 yoyQty/momQty 字段，重新计算会重复且口径可能漂移
- **多源混合单位**：上游可能 concat 不同单位（TEU vs 吨 vs 万箱），`descriptive.py` 已用 `_src_ref` 标记拆分，本工具必须沿用
- **透视格式普遍**（num/typeName）：D2/D5/D7 大量端点返回长表，需 unpivot 后才能按指标检测
- **22 个排名/占比端点**：纯截面（无时间），头部集中度本身就是异常信号

### 2.4 5 类典型形态
| 代号 | 形态 | 典型示例 | 行数 |
|---|---|---|---|
| **A** | 单序列时间 | `getThroughputAnalysisByYear`（dateMonth × qty） | 4-16 |
| **B** | 多实体时间 | `getBerthOccupancyRateByRegion`（regionName × dateMonth × rate） | 实体数 × 月数 |
| **C** | 截面快照 | `getKeyEnterprise`、`getMonthlyZoneThroughput`（实体 × 值） | 5-20 |
| **D** | 预计算 YoY/MoM | `getThroughputAnalysisYoyMomByMonth`（regionName × qty × yoyQty × momQty） | 5-20 |
| **E** | 目标 vs 完成 KPI | `getThroughputAndTargetThroughputTon`、`getDeliveryRate`、`planInvestAndPayYoy` | 通常 1 行 |

---

## 3. 总体架构

### 3.1 调用骨架（与 `descriptive.py` 同构）

```
┌─────────────────────────────────────────────────────────┐
│ AnomalyDetectionTool.execute(inp, context)              │
│                                                         │
│ 1. 解析 data_ref / context_refs → DataFrame             │
│    （沿用 descriptive.py 270-301 行的解析逻辑）          │
│                                                         │
│ 2. _src_ref 多源拆分（沿用 descriptive.py 177-190）      │
│                                                         │
│ 3. _column_selector.select_analysis_columns(df, intent) │
│    → target_columns / time_column / group_by / col_schema│
│                                                         │
│ 4. shape_dispatcher(df_clean, cols) → shape_code        │
│      ↓                                                  │
│   ┌─ A: detect_single_series                            │
│   ├─ B: detect_multi_entity_series                      │
│   ├─ C: detect_cross_section                            │
│   ├─ D: detect_precomputed_yoy_mom                      │
│   └─ E: detect_kpi_progress                             │
│      ↓                                                  │
│ 5. 候选异常按 severity 排序，截 top-K（默认 K=10）       │
│                                                         │
│ 6. _generate_anomaly_narrative(候选, intent, col_schema)│
│    → LLM 生成 narrative + 每条异常的 likely_cause       │
│                                                         │
│ 7. 返回 ToolOutput(status, data={anomalies, method,     │
│    summary, narrative}, metadata={...})                 │
└─────────────────────────────────────────────────────────┘
```

### 3.2 文件清单

| 文件 | 操作 | 说明 |
|---|---|---|
| `backend/tools/analysis/anomaly.py` | 重写 | 主技能，约 280-330 行 |
| `backend/tools/analysis/_anomaly_detectors.py` | 新增 | 5 个 detector + dispatcher，约 250 行 |
| `tests/unit/tools/test_anomaly_detectors.py` | 新增 | 各 detector 单测，约 200 行 |
| `tests/integration/tools/test_anomaly_tool.py` | 新增 | 端到端集成测试，约 150 行 |
| `tests/llm_cache/...` | 新增 | LLM 调用 cassette（按既有缓存机制） |

不动：
- `backend/agent/_complexity_rules.py` / `planning.py` / `employees/*.yaml` / `tests/contract/test_complexity_rules.py`

---

## 4. Detector 详细设计

### 4.1 形态识别 `shape_dispatcher`

输入：`df_clean`、`{target_columns, time_column, group_by, entity_column}`
返回：`shape_code ∈ {"A","B","C","D","E","unknown"}`

判别顺序（先匹配先返回）：

```
有 finishQty/targetQty 或 planInvestAmt/finishInvestAmt 等成对列   → E (KPI)
列名含 yoyQty/momQty/yoyRate/momRate                              → D (预计算)
有 time_column ∧ 有 entity_column (或 group_by)                   → B (多实体时间)
有 time_column ∧ 无 entity_column                                  → A (单序列)
无 time_column ∧ 有 entity_column ∧ ≥1 数值列                     → C (截面)
其它                                                                → unknown (跳过检测)
```

`entity_column` 推断：取 `group_by`，否则取首个非 time_column 的低基数 categorical 列（基数 2-30）。

特殊处理：**透视格式（num/typeName）**
- 在 dispatcher 入口检查：若同时存在 `num`(数值) 和 `typeName`(categorical) 而无其它数值列，先 pivot：`df.pivot_table(index=time_or_entity, columns="typeName", values="num")` 再走形态识别。

### 4.2 Shape A — 单序列时间

```python
def detect_single_series(series: pd.Series, time_index: pd.Series, *,
                         z_threshold_moderate=2.5, z_threshold_severe=3.5,
                         min_periods=3) -> list[Anomaly]:
    """滚动 z-score + 末点变化率双信号。"""
    n = len(series)
    if n < min_periods or series.nunique() <= 1:
        return []

    window = max(min_periods, min(6, n // 2))
    rolling_mean = series.rolling(window, min_periods=min_periods).mean().shift(1)
    rolling_std  = series.rolling(window, min_periods=min_periods).std().shift(1)
    z = (series - rolling_mean) / rolling_std.replace(0, np.nan)

    anomalies = []
    for i, zi in enumerate(z):
        if pd.isna(zi) or abs(zi) < z_threshold_moderate:
            continue
        anomalies.append(Anomaly(
            entity=None,
            metric=series.name,
            time=str(time_index.iloc[i]),
            value=float(series.iloc[i]),
            expected=float(rolling_mean.iloc[i]) if pd.notna(rolling_mean.iloc[i]) else None,
            score=float(zi),
            method="rolling_zscore",
            severity="severe" if abs(zi) >= z_threshold_severe else "moderate",
        ))

    # 末点 MoM/YoY 阈值（独立信号，可能与 z-score 重合，去重时按 time+metric）
    anomalies.extend(_check_endpoint_change(series, time_index))
    return _dedup(anomalies)
```

阈值参数化（写在文件顶部常量区，便于调）：
```python
Z_MODERATE = 2.5    # 中度异常 z 阈值
Z_SEVERE   = 3.5    # 严重异常 z 阈值
MOM_MODERATE = 0.30 # 末点环比 ±30% 中度
MOM_SEVERE   = 0.50 # 末点环比 ±50% 严重
YOY_MODERATE = 0.50
YOY_SEVERE   = 1.00
```

### 4.3 Shape B — 多实体时间序列

按 `entity_column` 分组，每组单独跑 `detect_single_series`，再追加一个 **末点截面 outlier**：

```python
def detect_multi_entity_series(df, time_col, entity_col, value_col):
    out = []
    # 1. 各实体内部时序异常
    for entity, sub in df.groupby(entity_col):
        sub = sub.sort_values(time_col)
        out.extend(detect_single_series(sub[value_col], sub[time_col],
                                         _entity_label=entity))

    # 2. 末点截面 MAD（同时点不同实体之间的偏离）
    latest_t = df[time_col].max()
    latest_slice = df[df[time_col] == latest_t]
    out.extend(detect_cross_section(latest_slice, entity_col, value_col,
                                     _time_label=str(latest_t)))
    return out
```

### 4.4 Shape C — 截面快照

```python
def detect_cross_section(df, entity_col, value_col, *, mad_threshold=3.5):
    """中位数 ± k·MAD outlier；MAD=0 时回退到 mean ± 2σ。"""
    s = pd.to_numeric(df[value_col], errors="coerce").dropna()
    if len(s) < 4:
        return []

    median = s.median()
    mad = (s - median).abs().median()

    if mad > 0:
        scores = (s - median).abs() / (mad * 1.4826)  # 1.4826: MAD→σ 比例
        threshold = mad_threshold
        method = "mad_outlier"
    else:
        std = s.std()
        if std == 0:
            return []
        scores = (s - s.mean()).abs() / std
        threshold = 2.0
        method = "zscore_fallback"

    anomalies = []
    for idx, score in scores.items():
        if score < threshold:
            continue
        anomalies.append(Anomaly(
            entity=str(df.loc[idx, entity_col]),
            metric=value_col,
            time=None,
            value=float(s.loc[idx]),
            expected=float(median),
            score=float(score),
            method=method,
            severity="severe" if score >= threshold * 1.5 else "moderate",
        ))
    return anomalies
```

### 4.5 Shape D — 预计算 YoY/MoM

直接对 `yoyQty` / `momQty` / `yoyRate` / `momRate` 列阈值检查，不再二次计算：

```python
def detect_precomputed_yoy_mom(df, *, yoy_cols=("yoyQty","yoyRate"),
                                       mom_cols=("momQty","momRate")):
    out = []
    for _, row in df.iterrows():
        for col in yoy_cols:
            if col in df.columns:
                v = _to_pct(row[col])
                if v is not None and abs(v) >= YOY_MODERATE:
                    out.append(_make_anom(row, col, v,
                        threshold_severe=YOY_SEVERE, kind="yoy"))
        for col in mom_cols:
            if col in df.columns:
                v = _to_pct(row[col])
                if v is not None and abs(v) >= MOM_MODERATE:
                    out.append(_make_anom(row, col, v,
                        threshold_severe=MOM_SEVERE, kind="mom"))
    return out
```

`_to_pct` 处理两种约定：
- `yoyRate` 通常为小数（0.18 表 18%）
- `yoyQty` 是绝对差值，需要除以基数；若基数列缺失则跳过该字段

### 4.6 Shape E — KPI 进度差

适用列对：
- `targetQty` / `finishQty`（吞吐量目标）
- `planInvestAmt` / `finishInvestAmt`（投资计划）
- `planPayAmt` / `finishPayAmt`（成本支付）

```python
def detect_kpi_progress(df, *, current_month: int | None = None):
    """progress_gap = actual_completion_rate − expected_progress
    expected_progress 默认按当前月/12，未知时退化为 0.5。"""
    pairs = _detect_target_actual_pairs(df.columns)  # 返回 [(target_col, actual_col, label)]
    if not pairs:
        return []

    if current_month is None:
        current_month = _infer_current_month_from_data(df) or 6
    expected = current_month / 12

    out = []
    for tcol, acol, label in pairs:
        for idx, row in df.iterrows():
            target = _safe_float(row[tcol])
            actual = _safe_float(row[acol])
            if not target or target == 0:
                continue
            completion = actual / target
            gap = completion - expected
            if abs(gap) >= 0.10:
                out.append(Anomaly(
                    entity=_row_label(row),
                    metric=label,
                    time=None,
                    value=round(completion, 4),
                    expected=round(expected, 4),
                    score=round(abs(gap), 4),
                    method="progress_gap",
                    severity="severe" if abs(gap) >= 0.20 else "moderate",
                ))
    return out
```

---

## 5. 严重度排序与裁剪

候选异常合并后统一打分：

```python
def _rank_and_trim(anomalies: list[Anomaly], top_k: int = 10) -> list[Anomaly]:
    severity_weight = {"severe": 2.0, "moderate": 1.0}
    anomalies.sort(
        key=lambda a: severity_weight[a.severity] * abs(a.score),
        reverse=True,
    )
    return anomalies[:top_k]
```

`top_k` 默认 10，可被 `params.top_k` 覆盖；若用户问的是"最显著的异常"则裁到 5。

---

## 6. LLM 解释阶段

### 6.1 Prompt 设计（仿 descriptive 单一通用提示）

```python
_ANOMALY_SYSTEM = "你是数据分析专家，擅长识别异常并推测业务原因，结论需基于数据证据。"

_ANOMALY_PROMPT = """【分析意图】
{intent}

【数据列说明】
{col_schema}

【数据摘要】
{data_summary}

【检出的候选异常】（按显著度从高到低，已截 top-{k}）
{anomalies_table}

请输出严格 JSON（不要 markdown 包裹）：
{{
  "ranked": [
    {{"index": 0, "likely_cause": "原因推测（1-2 句，须援引数据）",
      "confidence": "high/medium/low"}},
    ...
  ],
  "narrative": "2-3 段中文异常解读，围绕分析意图，
                 优先讨论最显著的 1-2 个异常，给出业务含义",
  "overall_risk_level": "high/medium/low/none"
}}

要求：
- 不杜撰数据中没有的因素
- 不重复罗列每条异常的统计值（narrative 已有）
- 若候选异常列表为空，narrative 写"未检出显著异常"，overall_risk_level=none"""
```

### 6.2 调用约束
- 复用 `invoke_llm`、`get_settings().LLM_TEMPERATURE_CREATIVE`、`timeout=90`
- 复用 `extract_json` 解析（容忍 markdown 包裹和 `<think>` 块）
- 失败回退：`narrative = f"[narrative_failed:{error_category}]"`，`status="partial"`，但**统计层异常列表照样返回**（不因 LLM 失败让整个工具失败）

---

## 7. 输出契约

### 7.1 ToolOutput.data
```json
{
  "anomalies": [
    {
      "entity": "天津港 A 港区",
      "metric": "rate",
      "time": "2026-03",
      "value": 0.91,
      "expected": 0.62,
      "score": 3.8,
      "method": "rolling_zscore",
      "severity": "severe",
      "likely_cause": "...（来自 LLM）",
      "confidence": "medium"
    }
  ],
  "summary": {
    "total_candidates": 14,
    "kept": 10,
    "shape_detected": "B",
    "methods_used": ["rolling_zscore", "mad_outlier"],
    "overall_risk_level": "medium"
  },
  "narrative": "...2-3 段中文..."
}
```

### 7.2 ToolOutput.metadata
```python
{
    "rows_analyzed": int,
    "shape_detected": "A|B|C|D|E|unknown",
    "entity_column": str | None,
    "time_column": str | None,
    "target_columns": list[str],
    "narrative_error_category": str | None,
}
```

### 7.3 status 决策
| 条件 | status |
|---|---|
| shape_detected="unknown" 或无可分析数值列 | `failed` + `error_message` |
| 数据为空 | `failed` |
| 检出 ≥1 异常且 LLM 成功 | `success` |
| 检出 ≥1 异常但 LLM 失败 | `partial`（保留统计结果） |
| 检出 0 异常且 LLM 成功 | `success`（narrative="未检出显著异常"） |
| 检出 0 异常且 LLM 失败 | `partial` |

→ 与现有 `tool_desc_analysis` 的 status 语义一致，`tool_summary_gen` 可顺畅消费。

---

## 8. 阈值参数化与可调

所有阈值集中放在 `_anomaly_detectors.py` 顶部，便于后续调优：

```python
# ── 时序检测阈值 ───────────────────────────────
Z_MODERATE = 2.5
Z_SEVERE   = 3.5
MIN_PERIODS = 3
MAX_WINDOW = 6

# ── 变化率阈值 ─────────────────────────────────
MOM_MODERATE = 0.30
MOM_SEVERE   = 0.50
YOY_MODERATE = 0.50
YOY_SEVERE   = 1.00

# ── 截面 MAD ──────────────────────────────────
MAD_THRESHOLD = 3.5
MAD_FALLBACK_SIGMA = 2.0

# ── KPI 进度差 ────────────────────────────────
PROGRESS_GAP_MODERATE = 0.10  # 10pp
PROGRESS_GAP_SEVERE   = 0.20  # 20pp

# ── 输出裁剪 ──────────────────────────────────
DEFAULT_TOP_K = 10
```

支持 `params` 覆盖：`{"top_k": 5, "z_threshold": 3.0}`，但不在 Planning prompt 中暴露（默认值已合理，避免 LLM 乱调）。

---

## 9. 边界情况与降级

| 场景 | 处理 |
|---|---|
| `df` 为空 | `status="failed"`，error_message="输入数据为空" |
| 无数值列 | `status="failed"`，error_message="未找到可分析的数值列" |
| 序列长度 < 3 | 跳过该序列，不生成异常（不报错） |
| 所有值相等（std=0、MAD=0） | 跳过；若全部跳过 → 0 异常，narrative="未检出显著异常" |
| 多源 `_src_ref` ≥2 | 拆分后各自检测，结果合并；entity 字段加 src 前缀避免冲突 |
| 透视格式（num/typeName） | dispatcher 入口先 pivot |
| LLM 解析失败 | `status="partial"`，统计结果照常返回，narrative 含 `[narrative_failed:*]` |
| LLM 超时 | 同上，`narrative_error_category="timeout"` |
| 候选 > top_k | 排序后裁剪，`summary.total_candidates` 保留原数量 |

---

## 10. 测试矩阵

### 10.1 单元测试 `tests/unit/tools/test_anomaly_detectors.py`

| 用例 | 期望 |
|---|---|
| Shape A: 12 月稳定 + 第 10 月 spike | 检出 1 条 severe，method=rolling_zscore |
| Shape A: 4 月单调上升（无突变） | 0 异常 |
| Shape A: 全等序列 | 0 异常，不报错 |
| Shape A: 长度 2 | 0 异常 |
| Shape B: 5 港区 × 6 月，1 港区某月暴跌 | 检出该 entity+time |
| Shape B: 末点截面差异（1 港区显著偏高） | 末点截面 MAD 触发 |
| Shape C: 10 实体，1 个值 = 5×中位数 | MAD outlier 命中，method=mad_outlier |
| Shape C: MAD=0 但 std>0 | 回退 zscore_fallback |
| Shape D: yoyRate=0.6 行 | 命中 YOY_MODERATE，severity=moderate |
| Shape D: momQty 但无基数列 | 跳过 momQty，不报错 |
| Shape E: target=100 / finish=20 / 当前 6 月 | gap=−0.30 → severe |
| Shape E: target=0 | 跳过该行（避免除零） |
| dispatcher: 透视格式 | 自动 pivot 后正确识别 shape |
| `_src_ref` 多源 | 拆分检测，结果带 src 前缀 |
| top_k 裁剪 | 12 候选 + top_k=5 → 输出 5，summary.total_candidates=12 |

### 10.2 集成测试 `tests/integration/tools/test_anomaly_tool.py`

| 用例 | 期望 |
|---|---|
| 真实 fixture（getBerthOccupancyRateByRegion 模拟） | status=success，anomalies≥1 |
| 空 DataFrame | status=failed |
| LLM 失败（mock invoke_llm 抛错） | status=partial，anomalies 仍存在 |
| LLM 返回非法 JSON | status=partial，每条异常的 likely_cause=None |
| 与 tool_desc_analysis 串联（同一 data_ref） | 双方读同一 context 不互相污染 |

### 10.3 LLM cache 录制
按既有 `tests/llm_cache/langchain/` 机制录制 2-3 个稳定 cassette，覆盖：
- 有显著异常的解释路径
- 无异常的"未检出"路径
- JSON 解析容错路径

### 10.4 不需新增的测试
`tests/contract/test_complexity_rules.py` 已覆盖 `tool_anomaly` 在三个复杂度下的允许/禁止矩阵 → **保持不动**。

---

## 11. 实施步骤（建议顺序）

| 步骤 | 任务 | 产出 | 预估行数 |
|---|---|---|---|
| 1 | 新建 `_anomaly_detectors.py`：常量 + Anomaly dataclass + dispatcher | 骨架 | ~50 |
| 2 | 实现 5 个 detector（A→E） | 核心算法 | ~150 |
| 3 | 实现 `_rank_and_trim` + `_dedup` 工具函数 | ~30 |
| 4 | 单测 `test_anomaly_detectors.py`（覆盖 10.1） | 全绿 | ~200 |
| 5 | 重写 `anomaly.py`：复用 descriptive 的解析 + 调 dispatcher + LLM | 主技能 | ~280 |
| 6 | LLM prompt 调优 + cassette 录制 | 2-3 cassette | - |
| 7 | 集成测试 `test_anomaly_tool.py`（覆盖 10.2） | 全绿 | ~150 |
| 8 | 灰度验证：用 `throughput_analyst` 三个 employee 各跑 1 个含"异常"关键词的 FAQ | 人工核对 | - |

每步均独立可提交，建议按 1→2→4（单测先行驱动）→3→5→6→7→8 的顺序推进。

---

## 12. 验收标准

| # | 标准 | 验证方式 |
|---|---|---|
| 1 | 所有 5 类形态各有≥1 用例端到端通过 | 单测 + 集成 |
| 2 | LLM 失败时 statistics 仍返回（非空 anomalies） | mock 集成测试 |
| 3 | `anomalies_returned` 时 status≠`partial`（除非 LLM 失败） | 输出契约校验 |
| 4 | `tests/contract/test_complexity_rules.py` 不动且全绿 | 跑测 |
| 5 | 与 `tool_desc_analysis` 同一 data_ref 串联无副作用 | 集成测试 |
| 6 | 三个 employee 的"异常 / 反常 / 突变"FAQ 走通 | 灰度 |
| 7 | 输出 JSON 字段命名与现有 analysis 工具一致（`narrative` / `summary` / `metadata.rows_analyzed`）| 契约 review |

---

## 13. 不做与延迟项

| 项 | 理由 | 何时再考虑 |
|---|---|---|
| ARIMA / STL / Prophet | 序列普遍 ≤16 点 | 出现 ≥36 点的日度数据后 |
| Isolation Forest / LOF | 维度低、可解释差 | 引入多指标联合异常时 |
| 在线 / 流式检测 | 当前是离线 LLM 规划 | 引入实时驾驶舱后 |
| 用户自定义阈值 UI | 默认值已合理，避免 LLM prompt 膨胀 | 出现稳定误报反馈后 |
| 跨任务异常关联（多 data_ref 联合检测） | 复杂度高，先把单源做扎实 | v1.1 |
| 自动选择 top_k | 当前固定 10，足够 | 用户反馈后调整 |

---

## 14. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| 短序列 z-score 假阳性 | 用户对低显著度异常困惑 | min_periods=3 + Z_MODERATE=2.5（偏保守）+ severity 分级 |
| LLM 推测不基于数据 | 误导决策 | Prompt 强调"援引数据"+ confidence 字段 + 不杜撰约束 |
| 透视格式 pivot 失败 | 整个工具 fallback 到 unknown shape | dispatcher 中 try/except 包裹 pivot；失败时按原表走 C |
| 阈值与业务直觉不符 | 误报/漏报 | 集中常量区参数化；灰度后按 employee 反馈调 |
| top_k=10 在长尾场景过少 | 隐藏中等异常 | summary.total_candidates 保留原数量；narrative 提示"另有 N 条次显著异常" |

---

## 15. 与既有架构的一致性 Checklist

- [ ] 复用 `_column_selector.select_analysis_columns`（不自己选列）
- [ ] 复用 `_data_summarizer.summarize_sources`（喂 LLM 数据摘要）
- [ ] 复用 `invoke_llm`（不直连 LLM SDK）
- [ ] 复用 `_src_ref` 多源拆分（与 descriptive 同款）
- [ ] 复用 `extract_json`（容忍 markdown / `<think>` 块）
- [ ] `ToolOutput` 字段命名与 descriptive/attribution 对齐：`narrative` / `summary` / `metadata.rows_analyzed` / `error_category`
- [ ] `status` 决策表与现有 analysis 工具一致
- [ ] 不引入新依赖（pandas/numpy 已在 requirements）
- [ ] 不改 `_complexity_rules.py` / `planning.py` / `employees/*.yaml`
- [ ] 不改 `tests/contract/test_complexity_rules.py`

---

## 附录 A：与现有同类工具对照

| 维度 | tool_desc_analysis | tool_attribution | tool_anomaly（本方案） |
|---|---|---|---|
| 入参 | data_ref + intent | data_ref + intent | data_ref + intent + (top_k 可选) |
| 选列 | `_column_selector` | `_data_summarizer` | `_column_selector` + dispatcher |
| 计算层 | 统计 + 同环比 | LLM 单步 | 5 detector + ranking |
| LLM 用途 | 生成 narrative | 生成 drivers + narrative | 生成 likely_cause + narrative + risk_level |
| 输出关键字段 | summary_stats / growth_rates / narrative | primary_drivers / waterfall_data / narrative | anomalies / summary / narrative |
| status=partial 触发 | LLM narrative 失败 | LLM 失败 | LLM 失败（统计仍返回） |
| 行数（参考） | 358 | ~250 | 预计 280-330 + 250 (detectors) |

## 附录 B：Anomaly dataclass 定义

```python
from dataclasses import dataclass, asdict
from typing import Literal

@dataclass
class Anomaly:
    entity: str | None        # 港区/客户/公司名；单序列为 None
    metric: str               # 指标列名
    time: str | None          # YYYY-MM 或 None（截面）
    value: float              # 实际观测值
    expected: float | None    # 预期值（rolling_mean / median / 应完成进度）
    score: float              # 标准化打分（z 值或 |gap|）
    method: Literal[
        "rolling_zscore", "endpoint_change",
        "mad_outlier", "zscore_fallback",
        "yoy_threshold", "mom_threshold",
        "progress_gap",
    ]
    severity: Literal["moderate", "severe"]
    likely_cause: str | None = None    # 由 LLM 阶段填充
    confidence: Literal["high", "medium", "low"] | None = None

    def to_dict(self) -> dict:
        return {k: v for k, v in asdict(self).items() if v is not None}
```

---

**End of plan.**
