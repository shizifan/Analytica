# Plan: 修复测试中大量失败的任务

## 问题概述

10 个测试场景的约 64 个任务中，存在大量失败或产出无效结果的任务。当前集成测试断言条件 `success_count > 0` 过于宽松，掩盖了真实失败。

## 失败分类

| 类型 | 数量 | 影响 Skill | 根因 |
|---|---|---|---|
| "无有效的数值列" | 10 | chart_line, chart_bar | LLM 指定的 value_columns 与 DataFrame 实际列名不匹配，auto-detect 被跳过 |
| "[自动生成失败] 统计概况：{}" | 7+ | desc_analysis | LLM 指定的 target_columns 不存在，auto-detect 被跳过，统计结果为空 |
| "unhashable type: 'list'" | 2 | desc_analysis | DataFrame 含 list 类型值，pandas 统计运算报错 |
| "依赖任务失败" | 2 | summary_gen | 上游任务失败导致级联 |

**核心原因**: Skills 的自动检测逻辑仅在 LLM 未指定参数时触发（`if not value_columns`）。当 LLM 指定了列名但这些列名在 mock 数据中不存在时，auto-detect 被跳过，导致空结果。

## 修复方案

### Fix 1: `backend/skills/visualization/chart_line.py`

**当前代码** (L66-67):
```python
if not value_columns:
    value_columns = [c for c in df.columns if c != time_column and pd.api.types.is_numeric_dtype(df[c])]
```

**修改为**: 在 L66-67 处增加"回退到自动检测"逻辑。构建 series 后（L72-82），如果 series 为空且原始 value_columns 非空，说明 LLM 指定的列名全部不匹配，此时清空 value_columns 重新自动检测并再次构建 series。

具体改法——在 L65-85 之间:
```python
# Auto-detect value_columns if not specified
if not value_columns:
    value_columns = [c for c in df.columns if c != time_column and pd.api.types.is_numeric_dtype(df[c])]

x_data = [str(v) for v in df[time_column].tolist()]

series = []
for i, col in enumerate(value_columns):
    if col not in df.columns:
        continue
    series.append(...)

# FALLBACK: 如果 LLM 指定的列全部不匹配，回退到自动检测
if not series:
    fallback_cols = [c for c in df.columns if c != time_column and pd.api.types.is_numeric_dtype(df[c])]
    for i, col in enumerate(fallback_cols):
        series.append({
            "name": col,
            "type": "line",
            "data": [round(float(v), 2) if pd.notna(v) else None for v in df[col]],
            "smooth": True,
            "lineStyle": {"color": SERIES_COLORS[i % len(SERIES_COLORS)]},
            "itemStyle": {"color": SERIES_COLORS[i % len(SERIES_COLORS)]},
        })

if not series:
    return self._fail("无有效的数值列")
```

### Fix 2: `backend/skills/visualization/chart_bar.py`

与 Fix 1 完全对称。在 series 构建后增加同样的 fallback 逻辑，将 `"type": "line"` 改为 `"type": "bar"`，去掉 `smooth` 和 `lineStyle`。

### Fix 3: `backend/skills/analysis/descriptive.py`

**问题 A**: target_columns 不匹配时 auto-detect 被跳过

**当前代码** (L183-187):
```python
if not target_columns:
    target_columns = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
if not target_columns:
    return self._fail("未找到可分析的数值列")
```

**修改为**: 过滤掉不存在的列名，如果过滤后为空则回退到自动检测:
```python
# 过滤掉 DataFrame 中不存在的列
if target_columns:
    valid_columns = [c for c in target_columns if c in df.columns]
    if not valid_columns:
        # LLM 指定的列全部不存在，回退到自动检测
        target_columns = []
    else:
        target_columns = valid_columns

if not target_columns:
    target_columns = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
if not target_columns:
    return self._fail("未找到可分析的数值列")
```

**问题 B**: "unhashable type: 'list'" — DataFrame 含 list 类型值

在自动检测数值列之前，增加 list 类型列的清洗:
```python
# 清洗含有 list 类型值的列（转为字符串），避免 pandas 运算报错
for col in df.columns:
    if df[col].apply(lambda x: isinstance(x, list)).any():
        df[col] = df[col].astype(str)
```

这段代码放在获取 df 之后、target_columns 处理之前（约 L182 处）。

### Fix 4: `tests/test_employee_e2e.py`

**当前断言** (L1028):
```python
assert success_count > 0
```

**修改为**: 要求所有任务成功（report_gen 类任务除外，因为它们依赖上游）:
```python
# 非 report_gen 任务应全部成功
non_report_tasks = {tid: ctx for tid, ctx in context.items()
                     if not tid.startswith("T") or "report" not in str(getattr(ctx, 'skill_id', ''))}
# 允许 report_gen 因内容不足而 partial
assert success_count == total or fail_count == 0, (
    f"Tasks failed: {fail_count}/{total}\n"
    f"Failures:\n" + "\n".join(failures)
)
```

考虑到当前情况是修复 skill 本身使其不再失败，测试断言可以直接改为:
```python
assert fail_count == 0, (
    f"Tasks failed: {fail_count}/{total}\n"
    f"Failures:\n" + "\n".join(failures)
)
```

## 修改文件清单

| 文件 | 改动 |
|---|---|
| `backend/skills/visualization/chart_line.py` | series 为空时 fallback 到自动检测数值列 |
| `backend/skills/visualization/chart_bar.py` | 同上（bar 版本） |
| `backend/skills/analysis/descriptive.py` | target_columns 验证+回退 + list 类型清洗 |
| `tests/test_employee_e2e.py` | 断言改为 `fail_count == 0` |

## 预期效果

修复后:
- 10 个 "无有效的数值列" 失败 → 全部成功（fallback 到自动检测）
- 7+ 个 "[自动生成失败] 统计概况：{}" → 全部正常产出统计数据和叙述
- 2 个 "unhashable type: 'list'" → list 列被转为 string，不影响数值列统计
- 2 个 "依赖任务失败" → 上游修复后级联消除
- 测试断言准确反映真实通过情况
