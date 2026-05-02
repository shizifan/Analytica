# HTML 报告生成超时优化方案

**目标读者**：Claude Code 执行实例（无本会话上下文）
**来源**：`tool_report_html` 在生产中频繁出现 `Timeout after 60s` 错误
**状态**：方案拟定中

---

## 1. 超时链路全景

```
execution.py:   per-task timeout = clip(estimated_seconds × 2.0, 30, 120)
                                = clip(30 × 2.0, 30, 120)
                                = 60s                              ← 错误源头

tool_executor(base.py:159):
  asyncio.wait_for(tool.execute(), timeout=60s)
    └─ HtmlReportTool.execute()
         ├── collect_and_associate()        ~0.5s
         ├── plan_outline()                 LLM 调用, timeout=60s   ← 新增于 a8f8aad
         └── _run_html_agent()              LLM × 最多15轮, request_timeout=90s  ← 预存量
```

**核心矛盾**：外层 60s 只能覆盖 outline planner（60s）+ agent loop 第一轮（5-30s），剩余 14 轮 LLM（75-450s）直接触发 `asyncio.TimeoutError`。

## 2. 根因分析

### 2.1 规划升级引入的新瓶颈

| 组件 | 升级前 (≤7021054) | 升级后 (≥a8f8aad) | delta |
|------|-------------------|-------------------|-------|
| Outline Planner | 无 | `invoke_llm(timeout=60s)` | **+60s** |
| 确定性 fallback | 有（html_gen 双路径） | 无（0a48df1 + 4bc52c4 移除） | **-1 逃生路径** |
| Agent loop | 有 | 有（保留） | 0 |

`a8f8aad` 多加了一次 LLM 调用（outline planner 60s），又把唯一逃生路径（确定性 fallback）封死了。之前 agent loop 超时至少还能 fallback 生成一份报告。

### 2.2 estimated_seconds 与实际耗时严重脱节

| | 估计值 | 实际需求 | 倍数 |
|--|--------|----------|------|
| planning.py hint | `estimated_seconds: 30` | — | — |
| resolved timeout | `clip(30*2.0, 30, 120) = 60s` | 150-900s | **2.5-15x** |

### 2.3 Agent loop 的低效设计

`_html_tools.py` system prompt 明确指示 "逐个调用工具"，导致 LLM 每个 response 只 emit 一个 block。典型报告有 30+ blocks + section 头尾 call：

```
实际 LLM 调用次数 = 1 (begin_document)
                   + sections × 2 (begin/end_section)
                   + block_count (emit_*)
                   + 1 (finalize_document)
                   + 可能的纠错轮次
```

每个 LLM 调用需 5-30s（`qwen3-235b-instruct`），即使没有任何出错也轻松超时。

## 3. 优化方案

### 3.1 P0 — 确定性渲染替代 Agent Loop（核心方案）

**现状**：LLM agent loop 执行完全机械化的任务——按 outline 的顺序依次调用 `begin_section → emit_* → end_section`。Outline 已精确指定每个 section 有哪些 block、顺序是什么。

**方案**：在 `html_gen.py` 中用 Python 循环直接遍历 outline 并调用 renderer 方法，跳过 LLM agent loop。

```
改动文件:
  html_gen.py      — _run_html_agent 替换为 _render_outline_deterministic
  _html_tools.py   — 全文件可删除（不再需要 LangChain tool 包装）

新增 ~30 行渲染循环，删除 ~180 行 agent loop + tools。
```

**收益**：
- agent loop 耗时从 150-900s → **< 0.5s**
- 消除 LLM 幻觉风险（编造 block_id、跳过 block）
- 消除 agent 不 finalize 的失败模式
- 减少 LLM API 调用费用

**风险**：agent loop 中 LLM 在 `emit_paragraph` 时可能会微调文案/格式。需确认现有 agent 仅做顺序调度还是确有内容调整。从当前 prompt 和工具代码来看，仅做调度。

**同样适用于 DOCX 报告** (`docx_gen.py`)，可一并优化。

---

### 3.2 P1 — 调整 per-task timeout 和 estimated_seconds（防御性）

即使实施了 P0，也要做防御性调整。如果 agent loop 短期内不能移除：

```
planning.py  hint:          estimated_seconds: 30 → 90
execution.py _TIMEOUT_PROFILE["report_gen"]:  (30, 120, 2.0) → (90, 300, 2.5)
```

这样 resolved timeout = `clip(90*2.5, 90, 300) = 225s`，足够 outline planner + agent loop 15 轮。

---

### 3.3 P2 — Agent Loop 批量调用（如保留 agent loop）

如 agent loop 必须保留（例如 LLM 确实在段落生成中做了内容润色），修改 system prompt 从逐个调用改为按 section 批量：

[_html_tools.py](backend/tools/report/_html_tools.py:48)
```
当前: 对每个 block 调用对应 emit_* 工具(传入 block_id)
改为: 每个 section 在一次 LLM 响应中完成 begin_section + 全部 emit_* + end_section
```

LLM 调用次数从 ~30+ 降为 ~sections 数 + 1（通常 5-8）。

---

### 3.4 P3 — 大纲规划旁路（减少 1 次 LLM 调用）

对于内容结构明确的报告（吞吐量月报、资产投资报告等），outline 可由规则直接生成：

```
plan_outline() 改为:
  if 简单报告:
    return _build_deterministic_outline(rc)   # 无 LLM 调用
  else:
    return _plan_with_llm(rc)                 # 保留 LLM 路径
```

`_build_deterministic_outline` 直接用 Stage 1 收集到的 ContentItem 构造 outline，每个 item 映射为对应 block，按 section 分组即可（现有 `_convert_item` 已经做了 item→block 映射）。

收益：消除一次 60s LLM 调用。

---

### 3.5 P4 — 缩减 Prompt 尺寸

`serialize_outline()` 把完整 outline 全部发送给 LLM，大报告可能数千字符：

- 只发送当前 section 的 block 列表（分 chunk 处理）
- 删减 block 描述，只保留 `block_id + kind`

收益：每轮 LLM 响应快 20-30%。

---

### 3.6 P5 — 小模型加速 Agent Loop

当前 agent 用 `qwen3-235b-instruct`（235B 参数），对机械性 tool-calling 完全可以换用小模型：

```python
# html_gen.py _run_html_agent 中
llm = ChatOpenAI(
    model="qwen3-7b-instruct",  # 或类似小模型
    ...
)
```

收益：每轮 LLM 响应从 10-30s → **1-3s**。

前提：小模型必须可靠遵循 tool-calling schema，需验证。

---

## 4. 实施优先级

| 优先级 | 方案 | 预估效果 | 改动量 | 风险 |
|--------|------|----------|--------|------|
| **P0** | 确定性渲染替代 agent loop | 消除 90% 超时 + 减少 API 费用 | ~50行 | 低（仅调度逻辑，不改渲染） |
| **P1** | 调整 timeout profile | 防御性：给 LLM 更多时间 | 2行 | 无 |
| **P2** | 批量 tool call prompt | LLM 调用次降 5x | ~5行 prompt | 低 |
| **P3** | 大纲规划旁路 | 取消 1 次 LLM 调用 | ~80行 | 中（需判断要不要走规则） |
| **P4** | 缩减 prompt 尺寸 | 每轮快 20-30% | ~30行 | 低 |
| **P5** | 小模型加速 | 每轮快 5-10x | 1行 | 中（小模型 tool-calling 可靠性） |

## 5. 建议实施路径

1. **先做 P0 + P1** 组合——确定性渲染直接消除 agent loop 超时，同时调大 timeout 做兜底
2. **P2-P5 可以不做**——如果 P0 解决了 agent loop，这些优化就失去目标
3. **P3 独立于 P0**——大纲规划的 60s LLM 调用仍然存在，但这部分目前稳定，可后续优化

## 6. 对 DOCX 的影响

`docx_gen.py` 使用相同的 `_agent_loop.py` + `_run_html_agent` 模式。P0 确定性渲染同样适用于 DOCX 格式。建议 HTML 先行验证后一并推广。
