# Analytica 多轮对话能力优化 — 方案设计 V6

**作者**：2026-05-06 架构 Review
**状态**：待评审
**范围**：本 spec 自包含；与历史 spec 的对照关系集中在 §13。

---

## 0. 现状诊断

当前多轮对话实现存在三个相互关联的根因，导致 Agent 无法可靠地在续接轮中复用前轮数据。

### 0.1 根因 A — 关键词路由决定数据复用路径

[graph.py:128-147](../backend/agent/graph.py#L128) `_classify_turn` 用 9 个关键词（`再加`、`换成`、`导出为`等）把用户消息分类为 amend / continue / new。该分类决定后续是走哪条数据传递路径：

| turn_type | 后续路径 | 数据复用机制 |
|---|---|---|
| `amend` | run_stream 直接构造 plan，跳过 perception+planning（[graph.py:964-1035](../backend/agent/graph.py#L964)） | `params._previous_artifacts` + `conversion_context.pkl` |
| `continue` | 正常进 graph，但 perception 强制清空 `empty_required`（[perception.py:894-895](../backend/agent/perception.py#L894)） | **无机制** |
| `new` | 全链路重新跑 | 不需要 |

关键词命中即决定路径，模糊措辞如 "还要个 PPT" 命不中 amend、"再加 2024 年对比" 误中 amend——本应由 LLM 在多轮上下文里判断的事，被规则提前定死。

### 0.2 根因 B — 数据传递两套不互通的机制

- **amend 通路**：报告工具特殊参数 `_previous_artifacts` + 报告生成时把 transitive deps 的 ToolOutput pickle 进 `conversion_context.pkl`（[execution.py:1033-1045](../backend/agent/execution.py#L1033) + [artifact_store.py:248-288](../backend/memory/artifact_store.py#L248)）。下一轮 amend 报告工具靠 `read_conversion_context` 还原前轮完整 DataFrame。**只服务 report 类工具**。
- **continue 通路**：没有。LLM 想复用 R0 数据时三条路都坏：
  - 填 `data_ref="T001"` → execution 当轮 context 没 T001 → 报错
  - 重 fetch 同参数 → 浪费 API + 实时端点口径漂移
  - 塞 `_previous_artifacts` → analysis/chart 工具不识别此参数 → 数据找不到

### 0.3 根因 C — 启发式判重 vs LLM 自决

[execution.py:97-138](../backend/agent/execution.py#L97) `_should_skip_data_fetch` + `_params_match` 在 execution 层用规则猜"两个 task 参数等价就跳过 fetch"。问题不只是规则不准，而是**LLM 在 plan 层完全看不到"已有数据可复用"**——它根本不知道何时该写 `data_ref` 而不是新 `data_fetch`。

### 0.4 V6 的诊断

"会话内有什么数据、能不能复用"应该是 plan 层的一等公民，由统一的会话工作区承载。amend / continue / drill-down 的差别只在 LLM 的规划意图，**数据复用机制本身应该是一套**——不分类、不藏在工具内、不靠规则猜。

### 0.5 范围声明 — V6 不处理的事

为避免 V6 设计被边缘场景拖大，明确不在本方案处理的事：

- **同 task 重新生成**（如用户改报告标题点重生成、改图表类型回看）：V6 没有"重新生成"流程触发点。用户通过新 turn 表达需求，LLM 看 manifest 中相同 endpoint+params 的旧条目自然不会再引用（prompt 范式中只复用最新一份匹配项）。`superseded_by` / 版本链字段留作后续 spec 设计。
- **跨 session 数据共享**：workspace 强绑定 session_id。用户跨 session 复用数据需通过 artifact 下载/重导入，不在 V6 范围。
- **前端 manifest 渲染界面**：V6 实现后端 API + WebSocket 事件，前端 inspector 面板由独立 spec `spec/optimize_session_visibility_V1.md` 覆盖。
- **reflection 节点对 confirmed 的派生标记**：§5.2.3 表中标"暂作为可选扩展"，V6 不强制实现；预留接口位但无逻辑。
- **不兼容历史 session**：V6 是开发期一次性切换，升级时清空既有 session 数据。manifest 不设版本演进机制，旧 session 不做 backfill。

---

## 1. Mission

1. **重做意图路由**：每轮非首轮由 perception LLM 输出 `turn_type` + `structured_intent`，删除现有 `_classify_turn` 关键词路由（详见 §4）。
2. **新设施 SessionWorkspace**：每个 task 完成后无差别落盘，维护 `manifest.json` 索引。manifest 全会话可见，跨轮可引用（详见 §5）。
3. **重做 planning prompt**：注入 manifest 摘要，LLM 看着会话内已有数据列表做规划。`data_ref` 协议天然支持跨轮（指向 manifest 中的任意 task_id）。
4. **重做 execution**：task 启动前自动从 workspace 加载 `data_ref` 引用的产物；完成后自动落盘 + 更新 manifest（详见 §5.3）。
5. **删除两套旧机制**：`_previous_artifacts` 协议、`conversion_context.pkl` transitive 打包、`_should_skip_data_fetch` 启发式判重——manifest 取代之。
6. **修复续接路径三个 bug**：plan_history 归档时机 / turn_index 漂移 / analysis_history 污染（详见 §7）。

**不改动**：
- 单 session 并发锁、四阶段 LangGraph 状态机、WebSocket 事件广播框架
- DB schema 主结构（仅扩展 sessions 表加索引列，或新增 session_workspace_items 表）
- 报告生成「编剧-场工」架构本身（仅替换"加载前轮数据"的入口）
- 现有 `analysis_history` / `trim_analysis_history` / `turn_boundary` 事件——manifest 是补充，不取代 history 的 prompt 摘要

---

## 2. 设计原则

| 原则 | 含义 |
|------|------|
| **意图理解归 LLM** | 关键词只能粗筛是否首轮，不能决定路径分歧 |
| **数据传递归 execution + workspace** | 跨轮数据复用不靠工具内协议，靠 plan 层的 `data_ref` + execution 自动加载 |
| **工具职责单一** | 工具只关心"对 ToolOutput 做什么计算"，不感知跨轮、不读 conversion_context |
| **manifest 是会话内一等公民** | LLM 看得到、用户看得到、execution 看得到。跨轮数据可见性等于 manifest 可见性 |
| **直接替换** | 不保留 `_previous_artifacts` / `conversion_context` 兼容、不加 feature flag、不分阶段 |
| **失败显式化** | 任何"任务终态=done 但产物不可用"的状态都必须翻成 task 失败，向用户和 LLM 显式呈现。不允许通过 prompt 过滤、status 静默标记、silent fallback 等方式让失败"消失" |

---

## 3. 架构变更总览

### 3.1 现状（数据传递的两套机制并存）

```
跨轮数据复用：
  amend 路径
    └── plan 写 _previous_artifacts=[aid] → report 工具内部读 conversion_context.pkl
        → pickle.load 出 dict[task_id, ToolOutput] → 合并进本轮 execution_context

  continue 路径
    └── 无机制。LLM 不知道前轮数据是否可用，要么重 fetch 要么 plan 引用一个不存在的 task_id
```

### 3.2 V6（统一到 SessionWorkspace）

```
所有 task 完成 → 自动落盘到 sessions/{sid}/workspace/{task_id}.{ext}
              → 更新 sessions/{sid}/workspace/manifest.json

planning prompt 注入 manifest 摘要（task_id / kind / schema / sample / confirmed）
LLM 规划任务：
  - 引用现有数据：data_ref=T001（manifest 中存在）
  - 需要新数据：type=data_fetch，正常拉取
  - 不需要 _previous_artifacts，不需要 data_fetch_ref，不需要 _should_skip_data_fetch

execution 启动每个 task 前：
  对 task.params 中的 data_ref / data_refs 字段做解析：
    - 若是字符串 task_id 且在 manifest 中 → workspace.load() 注入 execution_context
    - 若已在 execution_context 中（同轮上游产出）→ 直接用
    - 否则 → fail-fast
```

差异点：
- amend / continue / new 三种意图共用同一条数据复用路径。
- LLM 在 plan 层显式声明"用 T001"，等同于"用 manifest 中的 T001"。
- 工具完全不感知跨轮——它收到的 ToolOutput 跟同轮上游产出无区别。

---

## 4. Layer 1 — 意图理解（perception LLM 路由）

删除 `_classify_turn` 关键词路由（[graph.py:128-147](../backend/agent/graph.py#L128)），由 perception LLM 在多轮上下文里直接产出 `turn_type` + `structured_intent` + 是否追问。

### 4.1 MULTITURN_INTENT_PROMPT

新建专用 prompt（不复用 `SLOT_EXTRACTION_PROMPT`，因为目标不同：本任务要 LLM 在多轮上下文里判断 turn 性质并产出 intent delta，槽位提取作为副产品）：

```python
# backend/agent/perception.py — 新增

MULTITURN_INTENT_PROMPT = """你是一个数据分析多轮对话理解专家。当前是同一会话的第 {turn_index} 轮交互。

【前轮分析摘要】
{prev_summary}

【本会话已有数据（前轮产物 manifest 摘要）】
{manifest_summary_for_perception}

【当前已填充的槽位】
{current_slots_json}

【完整对话消息】
{messages_text}

【本轮用户最新消息】
{latest_user_message}

【任务】
基于历史对话与本轮消息，判断用户意图并输出结构化结果：

1. turn_type — 三选一：
   - "new"      用户开启全新分析话题（与前轮主题/分析对象不同）
   - "continue" 用户在前轮基础上深化、扩展、对比、钻取、调整参数
   - "amend"    用户对前轮已生成的报告/产出物提出格式或副本要求（如追加 PPT、换成 Word），不涉及新数据获取
2. reasoning — 一句话说明判断依据
3. needs_clarification — 是否还需要追问必填槽位（bool）
4. ask_target_slots — 若需追问，列出仍为空且必填的槽位名称
5. structured_intent — 本轮的 intent，含完整槽位（继承前轮 + 本轮 delta）
6. slot_delta — 本轮明确变更或新增的槽位字典（供审计）

【判断规则】
- "amend" 仅在用户**明确**要新格式/新副本，且不涉及数据维度/时间范围变化时给出。模糊场景归 "continue"。
- "new" 必须有强信号：分析对象切换、显式声明（"换个话题"/"新分析"），或与前轮无任何继承关系。模糊场景归 "continue"。
- 当 prev_summary 为"（首轮）"时，turn_type 固定为 "new"。
- 延续模式下若槽位已从前轮继承且无歧义，needs_clarification=false，不再追问。
- manifest 中已有相关产物时，amend / continue 优先复用——具体规划由 §5/§6 的 planning prompt 处理，本步骤只判类型。

【输出格式】（严格 JSON，无 markdown 包裹，无 <think>）
{{
  "turn_type": "new|continue|amend",
  "reasoning": "...",
  "needs_clarification": false,
  "ask_target_slots": [],
  "structured_intent": {{ ... 完整 intent 结构 ... }},
  "slot_delta": {{ "<slot_name>": {{"value": ..., "evidence": "..."}} }}
}}
"""
```

manifest 摘要让 LLM 在判断 turn_type 时多一个信号源：用户说"再生成份 PPT" + manifest 里有 HTML 报告 → 强 amend 信号；用户说"按港区拆分" + manifest 里有粒度=port 的数据 → 强 continue 信号。

### 4.2 perception 节点改造

```python
# backend/agent/perception.py — run_perception 改造关键段

async def run_perception(state: dict) -> dict:
    multiturn = state.get("_multiturn_context")
    is_first_turn = not bool(state.get("slots")) or multiturn is None

    if is_first_turn:
        # 首轮维持现有 SLOT_EXTRACTION_PROMPT 流程（不变）
        return await _run_first_turn_perception(state)

    # 非首轮：LLM 一次性产出 turn_type + intent + 是否追问
    result = await _run_multiturn_perception(state, multiturn)

    state["turn_type"] = result["turn_type"]
    state["structured_intent"] = result["structured_intent"]
    state["slot_delta"] = result["slot_delta"]
    state["empty_required_slots"] = result["ask_target_slots"]
    state["current_target_slot"] = (
        result["ask_target_slots"][0] if result["needs_clarification"] else None
    )
    state["slots"] = _merge_slots_with_delta(
        state.get("slots", {}), result["slot_delta"], result["structured_intent"]
    )
    state["current_phase"] = "perception"
    return state
```

`_run_multiturn_perception` 调用 `MULTITURN_INTENT_PROMPT`，解析 JSON，校验 `turn_type ∈ {new, continue, amend}`（非法值兜底为 `continue`，不引入新分支）。

### 4.3 run_stream 简化

```python
# backend/agent/graph.py — run_stream 中段（替换现有 947-1053）

turn_index = prev_state.get("turn_index", 0)
is_continuation = bool(prev_state.get("slots"))

if not is_continuation:
    # 首轮：现有 make_initial_state 路径
    state = dict(make_initial_state(
        session_id, user_id, user_message,
        employee_id=employee_id,
        web_search_enabled=web_search_enabled,
    ))
    state["turn_index"] = 0
    state["plan_history"] = []
else:
    # 续接：保留 slots、归档旧 plan、注入多轮上下文
    state = dict(prev_state)
    state.setdefault("messages", []).append({"role": "user", "content": user_message})
    # turn_index 自增的守卫见 §7.2.2
    # plan_history 归档见 §7.2.1
    state["structured_intent"] = None
    state["current_target_slot"] = None
    state["current_phase"] = "perception"
    state["error"] = None
    state["task_statuses"] = {}
    state["web_search_enabled"] = web_search_enabled
    # turn_type 不再在此设置——由 perception LLM 写回
    state["turn_type"] = None

    if state.get("analysis_history"):
        state["_multiturn_context"] = _build_multiturn_context_injection(state)

# 之后统一进 graph：perception → (clarification 或 planning) → execution
```

run_stream 之后的逻辑（拿 graph、yield meta、跑 graph、append summary、persist）保持不变，但 `_append_turn_summary` 调用前需加守卫（见 §7.2.3）。

### 4.4 删除项

| 删除位置 | 原因 |
|---------|------|
| [graph.py:128-147](../backend/agent/graph.py#L128) `_classify_turn` 整个函数 | 关键词路由由 LLM 取代 |
| [graph.py:946-1035](../backend/agent/graph.py#L946) run_stream 中 `if turn_type == "amend"` 分支 | amend 不再绕过 graph |
| [graph.py:947-948](../backend/agent/graph.py#L947) `turn_type = _classify_turn(...)` 调用 | 由 perception 输出 |
| [perception.py:894-895](../backend/agent/perception.py#L894) `if multiturn ... empty_required = []` | 是否追问由 LLM 自己判断 |
| [perception.py:854-866](../backend/agent/perception.py#L854) 把摘要塞进 conv_history 的临时方案 | 改为 prompt 显式字段 |

`_classify_turn` 在 [tests/scenarios/test_multiturn_liangang.py:28,263](../tests/scenarios/test_multiturn_liangang.py#L28) 还有引用——一并删除（测试改造见 §9）。

---

## 5. SessionWorkspace（V6 核心新设施）

### 5.1 现状对比

| 设施 | 现状 | V6 后 |
|------|------|------|
| `artifact_store` | 仅服务 report 工具，存 HTML/PPTX 等终态文件 | 扩展为通用 workspace 后端，所有 task 产物均可落盘 |
| `conversion_context.pkl` | report 任务保存时打包 transitive deps 的 ToolOutput | **删除**。被 workspace 平铺落盘取代 |
| `execution_context` | 内存 dict，task 完成不持久化 | 仍是内存，但 task 启动前从 workspace 自动加载 `data_ref` 引用 |
| `analysis_history.data_snapshots` | 给 LLM 看的 sample + 元信息 | 保留（用于 turn_summary 与 prompt 摘要），但不再承担"数据传递"职责 |
| `_should_skip_data_fetch` | execution 层启发式判重 | **删除**。LLM 在 plan 层看 manifest 决定是否新 fetch |
| `_previous_artifacts` | report 工具特殊参数 | **删除**。统一用 `data_ref` / `data_refs` |

### 5.2 设计

#### 5.2.1 落盘策略

每个 task 完成（status=done）后无差别落盘到 `sessions/{sid}/workspace/{task_id}.{ext}`：

| ToolOutput.data 类型 | 序列化格式 | 后缀 | dtype 退路 |
|---|---|---|---|
| `pandas.DataFrame`（标准 dtype） | parquet（pyarrow） | `.parquet` | — |
| `pandas.DataFrame`（含 object 混合 dtype） | 写盘前 dtype 标准化（object→str / numeric coercion）；仍失败则降级 feather | `.parquet` / `.feather` | — |
| `dict` / `list` | json（utf-8，`default=str` 处理日期等） | `.json` | — |
| `str`（含 markdown / 文本分析结果） | 原文 | `.txt` | — |
| `bytes` | 原始字节 | `.bin` | — |
| 文件类型（report tool 已写盘） | 复用 artifact_store 已有路径，manifest 仅记 path | — | （不重复写） |

**安全约束**：**禁止使用 pickle 作为序列化格式**。任何上述格式都无法落盘的产物 → 不写文件，manifest 条目标 `status="unserializable"`，**同时把承载它的 task 整体翻成 failed 状态**：execution 抛 `TaskError("产物无法序列化")`，前端收到 `task_error` 事件，用户看到该 task 失败而非"成功但悄悄不可用"。LLM 在 plan 摘要中能看到该条目，但条目带显式失败标识（见 §5.2.5），不会被静默过滤后误以为"从未存在"。

理由：pickle 反序列化可执行任意代码。即使是单 session 内使用，session 文件可能经备份链路、容器卷迁移、外部恢复等渠道被污染，反序列化构成 RCE 攻击面。

失败 task（`status in {failed, error}`）不落盘但在 manifest 中保留状态记录用于审计，且按"失败显式化"原则进入 LLM prompt 摘要（不被过滤）。

#### 5.2.2 manifest 结构

每个 session 一份 `manifest.json`，结构：

```json
{
  "session_id": "sess-xxx",
  "items": {
    "T001": {
      "task_id": "T001",
      "turn_index": 0,
      "type": "data_fetch",
      "tool": "tool_api_fetch",
      "name": "获取吞吐量趋势",
      "endpoint": "getThroughputAnalysisByYear",
      "params": {"endpoint_id": "...", "dateYear": "2026"},
      "output_kind": "dataframe",
      "path": "T001.parquet",
      "size_bytes": 12345,
      "schema": {
        "columns": ["month", "throughput_ton", "yoy_growth"],
        "dtypes": {"month": "string", "throughput_ton": "float64", "yoy_growth": "float64"}
      },
      "rows": 100,
      "sample": [
        {"month": "2026-01", "throughput_ton": 1234567.0, "yoy_growth": 0.05}
      ],
      "created_at": "2026-05-06T10:00:00Z",
      "user_confirmed": false,
      "confirmed_history": [],
      "tags": ["primary_data"],
      "status": "done",
      "turn_status": "finalized"
    },
    "T002": {
      "task_id": "T002",
      "turn_index": 0,
      "type": "analysis",
      "tool": "tool_desc_analysis",
      "depends_on": ["T001"],
      "output_kind": "str",
      "path": "T002.txt",
      "preview": "Q1总吞吐量同比增长2.3%，3月环比下降5.1%...",
      "user_confirmed": false,
      "confirmed_history": [],
      "status": "done",
      "turn_status": "finalized"
    },
    "G_REPORT_HTML": {
      "task_id": "G_REPORT_HTML",
      "turn_index": 0,
      "type": "report_gen",
      "tool": "tool_report_html",
      "depends_on": ["T001", "T002"],
      "output_kind": "file",
      "path": "../G_REPORT_HTML.html",
      "artifact_id": "art-r0-html-001",
      "user_confirmed": false,
      "confirmed_history": [],
      "status": "done",
      "turn_status": "finalized"
    }
  }
}
```

字段语义：
- `path`：相对 `workspace/` 的路径。`output_kind=file` 时 path 可指向 workspace 之外的 artifact_store 路径。`status` 非 done 时 path 为空。
- `sample` / `preview`：给 LLM prompt 看的截断；`sample` 默认 3 行，`preview` 默认 200 字。
- `user_confirmed` / `confirmed_history`：见 §5.2.3。
- `status`：`done` / `failed` / `unserializable` / `missing`。`done` 条目作为可引用产物；其余三种作为**显式失败条目**进入 LLM prompt 摘要（带失败原因），不被静默过滤——见 §5.2.5 与设计原则"失败显式化"。
- `turn_status`：`ongoing` / `finalized` / `abandoned`，见 §7.2。
- `depends_on`：plan 时的 DAG 快照，由 `_persist_task_to_workspace` 从 `task.depends_on` 一次性拷贝，落盘后**不再变更**。仅用于审计与"重复任务识别"，不保证与运行时实际数据流一致——运行时数据传递以 `data_ref` / `data_refs` 为准。

#### 5.2.3 user_confirmed 语义

两种来源（**取消隐式传播**）：

| 来源 | confirmed_source | 触发时机 |
|---|---|---|
| **显式** | `user_marked` | 前端在 task 结果卡片上点击"采纳/作为基准"按钮 |
| **派生** | `reflection_endorsed` | reflection 节点对 task 结果做质量判断后写入（暂作为可选扩展，V6 不强制实现） |

**为什么不做隐式传播**：原 V6 草案曾设计"report_gen 完成 → 自动把上游 task 标 confirmed"。这等价于猜测用户意图（用户看到报告觉得不对、关闭重来时仍会被误标）。即使加 `artifact_viewed` WebSocket 事件兜底也不可靠（断线/刷新会丢事件，且"看到"≠"认可"）。V6 默认所有 manifest 条目 `confirmed=false`，仅在用户主动操作时翻 true——这是更老实的状态描述。

LLM prompt 中：
- `user_confirmed=true` → "用户已显式认可，优先复用"
- `user_confirmed=false` → "中性产物，可被引用，但若有 confirmed=true 的等价替代则优先后者"

注意：`confirmed=false` **不等于"不可引用"**。LLM 仍能用所有 manifest 条目，confirmed 只是排序/优先级提示。这保证用户从未点过"采纳"按钮时整个系统也正常工作。

#### 5.2.4 跨轮可见性

manifest 全部 `done` 条目跨轮可见。无 turn_index 隔离——R3 的 plan 可以直接 `data_ref="T001"`（R0 的 task）。

`turn_index` 字段只用于：
- 前端展示（按轮次分组）
- 摘要折叠（manifest 大时优先保留近 N 轮 + 全部 confirmed 条目）

#### 5.2.5 清理与淘汰策略

manifest + workspace 文件随 turn 线性增长。V6 内置以下机制控制磁盘占用：

**活跃 session 内单上限**：`WORKSPACE_MAX_ITEMS_PER_SESSION = 100`（settings 可配）。超过时按以下优先级淘汰**文件本身**（manifest 条目保留作审计，path 标 cleared）：

1. `turn_status="abandoned"` 的条目（最先清）
2. `user_confirmed=false` 且 `type ∉ {report_gen, analysis}` 的条目（数据可重新 fetch）
3. 最早的 `turn_index` 的非 confirmed 条目

LLM prompt 摘要中**显式标记**这些不可用条目（如 `[已淘汰: 文件清理] T015 getThroughputByPort` / `[失败: 序列化不支持] T031`），不静默过滤——LLM 自主判断"重新 fetch 还是放弃此分析角度"，避免它误以为该数据从未存在。

**session 关闭/归档时**：删除 `user_confirmed=false` 且 `type != "report_gen"` 的所有 workspace 文件；manifest 完整保留供后续审计 / 复盘 / 重启。`type=report_gen` 的 artifact 文件归档不动（用户可能后续下载）。

**外部清理兜底**：manifest 加载时校验 path 存在性，缺失文件标 `status="missing"`（见 §5.2.2 status 枚举）。`missing` 条目按本节规则在 prompt 中显式呈现，详见 R9 应对。

#### 5.2.6 不做历史 session 兼容

V6 处于开发阶段，明确**不做** "升级前 session → V6 manifest" 的回填路径：

- 不引入 `backfill_from_analysis_history` 逻辑；
- 不引入 `status="backfilled"` 状态；
- alembic 迁移仅加 `sessions.workspace_manifest_json` 列，旧行允许 NULL；新建 session 时初始化为空 manifest 即可。

部署 V6 时清空既有 session 表数据。后续若需要再做兼容，单独 spec 处理；V6 不为此预留接口位（避免引入"两套机制"的隐性兼容路径）。

### 5.3 execution 层 hook

#### 5.3.1 task 启动前：解析 data_ref

```python
# backend/agent/execution.py — 新增
async def _resolve_data_refs(
    task: TaskItem,
    execution_context: dict,
    workspace: SessionWorkspace,
) -> None:
    """For each data_ref in task.params, ensure the referenced ToolOutput
    is loaded into execution_context.

    Lookup order:
      1. Already in execution_context (same-turn upstream task)
      2. workspace.manifest contains this task_id → load from disk
      3. fail-fast (raise TaskError)
    """
    ref_fields = ("data_ref", "data_refs")
    refs: list[str] = []
    for field in ref_fields:
        v = task.params.get(field)
        if isinstance(v, str):
            refs.append(v)
        elif isinstance(v, list):
            refs.extend(x for x in v if isinstance(x, str))

    for ref in refs:
        if ref in execution_context:
            continue
        if ref in workspace.manifest["items"]:
            execution_context[ref] = workspace.load(ref)
            continue
        raise TaskError(
            f"Task {task.task_id} references unknown data_ref={ref!r}; "
            f"not in execution_context and not in workspace manifest"
        )
```

#### 5.3.2 task 完成后：落盘 + 更新 manifest

```python
# backend/agent/execution.py — task 执行完成后
async def _persist_task_to_workspace(
    task: TaskItem,
    output: ToolOutput,
    state: dict,
    workspace: SessionWorkspace,
) -> None:
    """Persist the task output and update manifest in one atomic step."""
    if output.status not in ("done", "success"):
        workspace.record_failure(task, output)
        return
    workspace.persist(task, output, turn_index=state.get("turn_index", 0))
```

`SessionWorkspace.persist` 内部根据 `output.data` 类型选择序列化器，写盘后追加 manifest 条目。**不触发任何隐式 confirmed 标记**——所有新条目默认 `user_confirmed=false`。

#### 5.3.3 confirmed 显式标记（取代原"隐式判定"）

`user_confirmed` 字段仅由前端用户主动点击"采纳"按钮触发，通过专用 API 端点写入：

```python
# backend/main.py — 新增
@app.post("/api/sessions/{session_id}/workspace/{task_id}/confirm")
async def confirm_workspace_item(session_id: str, task_id: str, user_id: str = Depends(...)):
    workspace = SessionWorkspace.for_session(session_id)
    workspace.mark_confirmed(task_id, source="user_marked", actor=user_id)
    await ws_broadcast(session_id, {"event": "workspace_update", "task_id": task_id})

@app.post("/api/sessions/{session_id}/workspace/{task_id}/unconfirm")
async def unconfirm_workspace_item(session_id: str, task_id: str, user_id: str = Depends(...)):
    workspace = SessionWorkspace.for_session(session_id)
    workspace.mark_unconfirmed(task_id, actor=user_id)
    await ws_broadcast(session_id, {"event": "workspace_update", "task_id": task_id})
```

`mark_confirmed` / `mark_unconfirmed` 同步把变更追加进 manifest 条目的 `confirmed_history` 字段（值列表，每项含 `{action, source, actor, timestamp}`），用于审计与回滚。

### 5.4 planning prompt 重做

替换 [planning.py:1651-1673](../backend/agent/planning.py#L1651) 现有的 `multi_turn_text` 构建块为基于 workspace 的版本：

```python
# backend/agent/planning.py — 替换 multi_turn_text 构建

WORKSPACE_BLOCK = """
【本会话已有数据 — 当前可引用的产物】
（共 {total_items} 项，其中 {confirmed_count} 项已被采纳）

{manifest_summary_table}

【data_ref 协议】
- 引用上述任意 task_id 即可复用——execution 会自动加载，无需重新规划 data_fetch
- 优先引用 user_confirmed=true（标记为 ✓）的产物
- 仅在 manifest 中无满足需求的数据时，才规划新的 data_fetch
- 跨轮引用无需特殊参数：data_ref="T001" 即可（无论 T001 来自哪一轮）

【本轮规划约束】
- 当前是第 {turn_idx} 轮，turn_type={turn_type}
- 新增任务的 task_id 必须以 R{turn_idx}_ 为前缀
- amend 模式：只产出 1-2 个 report_gen 任务，data_refs 指向前述 manifest 条目
- continue 模式：可混合 data_ref 复用 + 新 data_fetch
- new 模式：忽略上述 manifest（前轮数据与新话题无关）
"""
```

`manifest_summary_table` 渲染成易读表格，例如：

```
| task_id        | turn | type        | kind      | summary                              | ✓ |
|----------------|------|-------------|-----------|--------------------------------------|---|
| T001           | R0   | data_fetch  | dataframe | getThroughputAnalysisByYear, 100 行  | ✓ |
| T002           | R0   | analysis    | text      | Q1同比增长2.3%, 3月环比下降5.1%...   | ✓ |
| G_REPORT_HTML  | R0   | report_gen  | file      | HTML 报告 (art-r0-html-001)          | ✓ |
| R1_T001        | R1   | data_fetch  | dataframe | getThroughputByZone, 12 行           | ✓ |
| R1_ATTR        | R1   | analysis    | text      | 大窑湾占比45%（实验性）              |   |
```

折叠策略：
- manifest 项 ≤ 30 时全部展开
- 超过时优先保留 `confirmed=true` + 最近 2 轮的全部条目，其他按 turn_index 折叠为 "R0 还有 5 项已折叠（详见 inspector）"

### 5.5 task 协议扩展

`data_ref` 协议升级，向下兼容：

| 旧形式 | 新形式 | 处理 |
|---|---|---|
| `data_ref="T001"`（同轮） | 不变 | execution_context 命中 → 直接用 |
| `data_ref="T001"`（跨轮） | 不变 | execution_context miss → workspace 命中 → load |
| 多个引用 | `data_refs=["T001", "T002"]` | 列表形式，逐个解析 |

**无需新 task type**（早期讨论曾考虑引入 `data_fetch_ref` 类型，V6 用通用 `data_ref` 取代）。**无需 `_previous_artifacts` 参数**（删除）。

**协议承载位置**：`data_ref` / `data_refs` 不在 [TaskItem schema](../backend/models/schemas.py#L95) 上设一等字段，仍由 `task.params` dict 承载——这是项目既有约定（visualization 工具如 [`_config_parser.py:117,181`](../backend/tools/visualization/_config_parser.py#L117) 已在用 `data_refs` 列表，plan_templates JSON 也已在用）。V6 不引入 schema 强制约束，避免破坏现有 plan_templates；execution 层的 `_resolve_data_refs` 主动从 `params` dict 提取这两个键即可（见 §5.3.1）。

### 5.6 删除项

| 文件 | 删除内容 |
|------|---------|
| `backend/agent/planning.py` | `build_amend_plan`、`_previous_artifacts` / `_previous_findings` 参数注入逻辑 |
| `backend/agent/execution.py` | `_should_skip_data_fetch` (execution.py:115)、`_params_match` (execution.py:97)、`_build_multiturn_execution_context` (execution.py:67)、`_collect_report_context` (execution.py:1054) 及其调用点 |
| `backend/memory/artifact_store.py` | `_context_dir` / `write_conversion_context` / `read_conversion_context` (artifact_store.py:238-288)；保留 artifact 文件本身的写盘 |
| `backend/main.py` | `read_conversion_context` 调用点 (main.py:621) 一并删除 |
| `backend/tools/report/_outline_planner.py` | `_previous_artifacts` 处理段 (103-130)，改为标准 `data_refs` 协议从 execution_context 读取 |
| `backend/agent/graph.py` | `_classify_turn`、run_stream amend 分支 |

---

## 6. Layer 3 — 增量规划（基于 workspace）

### 6.1 三种意图的统一规划范式

**关键设计**：planning 的 LLM 不再需要 `mode_directive` 区分 amend / continue / new 写出不同范式——LLM 看 manifest 就知道该引用还是该新增。`turn_type` 仍传入 prompt，但仅作为软提示。

#### 6.1.1 amend 范式

```
用户："再加一份 PPT"
LLM 看 manifest:
  T001 (R0, data_fetch, dataframe, 100 行) ✓
  T002 (R0, analysis, text) ✓
  G_REPORT_HTML (R0, report_gen, file, HTML) ✓

LLM 规划:
  R1_REPORT_PPTX:
    type: report_gen
    tool: tool_report_pptx
    depends_on: []
    params:
      data_refs: ["T001", "T002"]    # 指向 manifest 中的源数据
      report_structure: <从 G_REPORT_HTML 的 manifest 元信息推导>

execution:
  启动 R1_REPORT_PPTX 前 → 解析 data_refs → workspace.load("T001") → execution_context["T001"] = ToolOutput(DataFrame, 100 行)
  报告工具拿到完整 100 行数据生成 PPT
```

#### 6.1.2 continue 范式

```
用户："详细分析下降原因"
LLM 看 manifest:
  T001 (R0, dataframe, 100 行) ✓
  T002 (R0, text 分析结果) ✓

LLM 规划:
  R1_ATTR:
    type: analysis
    tool: tool_attribution
    depends_on: []
    params:
      data_ref: "T001"               # 复用 R0 数据
  R1_SUM:
    type: summary
    tool: tool_summary_gen
    depends_on: ["R1_ATTR"]
    params:
      data_refs: ["T001", "T002", "R1_ATTR"]   # 混合：R0 数据 + R0 文本 + 本轮归因

execution: 同上，所有 ref 自动 load
```

#### 6.1.3 new 范式

```
用户："换个话题，分析设备完好率"
LLM 看 manifest:
  T001 / T002 / G_REPORT_HTML (R0, 与新话题无关)

LLM 规划:
  R1_T001: type=data_fetch (设备相关端点)
  R1_T002: type=analysis (data_ref=R1_T001)
  ...
  manifest 中的旧条目不引用
```

prompt 通过 turn_type=new 提示"前轮 manifest 仅作背景，不必复用"，LLM 自主决定。

**硬约束（落实"失败显式化"）**：planning_node 在拿到 LLM 输出 plan 后做静态校验——`turn_type="new"` 时若 plan 中存在指向 `turn_index < 当前 turn` 的 `data_ref` / `data_refs`，直接抛 `PlanValidationError` 让 LLM 重出 plan，不允许"软提示"被忽略后悄悄复用旧数据。错误信息显式列出违规引用的 task_id，便于 LLM 修正。

### 6.2 plan_history 的角色

V6 中 `plan_history` 仍保留（归档时机修复见 §7.2），但作用降为**规划层的 LLM 思路参考**——告诉 LLM "前几轮规划了哪些任务"避免重复思路。**数据复用完全通过 manifest 完成**，与 plan_history 无关。

prompt 中两块独立：

```
【前轮规划思路（仅供参考，避免重复同样的分析角度）】
{completed_plan_summary from plan_history}

【本会话已有数据（manifest）】
{manifest_summary_table}
```

---

## 7. 续接路径数据治理（三个 bug 修复）

V6 让每轮非首轮都进 perception，会暴露当前续接路径下三个未被发现的 bug。这三处必须随 V6 一起修复——它们不是 V6 的新需求，但 V6 不修就会立刻引发数据漂移和 prompt 注入断裂。

### 7.1 三个 bug

#### 7.1.1 plan_history 在 continue 路径下永远是空的

**症状**：planning prompt 中【前轮已完成任务列表】块永远输出"（无历史计划）"，LLM 看不到 R0/R1/R2 已规划过哪些任务。

**根因**：`state["plan_history"].append(...)` 全代码库只有 3 处触发条件：
- [graph.py:439](../backend/agent/graph.py#L439) `planning_node` auto-confirm 块 — 显式排除 `turn_type in ("continue","amend")`
- [graph.py:987](../backend/agent/graph.py#L987) `run_stream` amend 分支 — V6 删除
- [graph.py:962](../backend/agent/graph.py#L962) `run_stream` new 分支 — 仅透传 `prev_state.plan_history`，不 append 当前 plan

也就是说 `turn_type="continue"` 时旧 plan 永远不会被归档。`_build_multiturn_context_injection` 第 334 行老老实实读 `state["plan_history"]`，但这个 list 一直是空的。

#### 7.1.2 turn_index 在追问期间反复自增

**症状**：用户在第 2 轮提了"按港区拆分"，perception 缺槽位连追问 2 次后才出 intent，turn_index 从 0 跳到 3。下次用户消息 prev_state.turn_index=3，再 +1=4。语义上是第 3 轮，turn_index 已经是 4。

**根因**：[graph.py:1043](../backend/agent/graph.py#L1043) `state["turn_index"] = turn_index + 1` 在 run_stream 每次进入续接分支时无条件执行。run_stream 末尾无论 perception 是否完成都会持久化（[graph.py:1171-1179](../backend/agent/graph.py#L1171)），下次读到的就是漂移后的值。

#### 7.1.3 _append_turn_summary 在追问中断时也执行

**症状**：用户问"按港区拆分" → perception 追问 → run_stream 走到 [graph.py:1171](../backend/agent/graph.py#L1171) 把当前 state 当成"本轮已完成"append 进 analysis_history。但本轮其实只有半个 perception，没有 plan、没有 execution。等用户答完追问真正完成时，本轮还会被 append 第二次。analysis_history 里塞满"半重复摘要"。

**根因**：`_append_turn_summary` 调用前没有检查"本轮是否真的完成"。

### 7.2 修复方案

#### 7.2.1 plan_history 归档前置到 run_stream 续接分支

在 §4.3 简化后的续接 else 块开头无条件归档：

```python
# backend/agent/graph.py — 续接分支开头
if state.get("analysis_plan"):
    state.setdefault("plan_history", []).append(state["analysis_plan"])
    state["analysis_plan"] = None
    state["plan_confirmed"] = False
```

效果：无论上一轮是 new/continue/amend，只要它产生过 plan，本轮一开始就会被归档到 `plan_history`。`_build_multiturn_context_injection` 拿到的 plan_history 自然完整。

同步删除 [graph.py:428-441](../backend/agent/graph.py#L428) `planning_node` 中的 auto-confirm 归档块——归档时机统一在 run_stream，不再分散到 planning_node。auto-confirm 仅保留"如果 plan 已存在且 plan_confirmed=True 就直接执行"这一最小语义（用于 plan 确认 hitl 链路恢复）。

#### 7.2.2 turn_index 自增前置守卫

仅当上一轮真的完成（plan_confirmed 且 execution 终态）才 +1：

```python
# backend/agent/graph.py — 续接分支
prev_completed = (
    prev_state.get("plan_confirmed")
    and prev_state.get("structured_intent") is not None
    and bool(prev_state.get("task_statuses"))
)
if prev_completed:
    state["turn_index"] = turn_index + 1
else:
    # 上一轮还在追问，仍属同一 turn
    state["turn_index"] = turn_index
```

判定条件：`structured_intent` 非空 = perception 通过了；`plan_confirmed` 为 True = planning 跑完了；`task_statuses` 非空 = execution 至少跑过。三者同时满足才算"已完成的一轮"。

#### 7.2.3 _append_turn_summary 守卫

在 [graph.py:1171](../backend/agent/graph.py#L1171) 调用前加守卫：

```python
def _should_append_turn_summary(state: dict) -> bool:
    """Only append when the turn truly completed (perception+planning+execution all ran)."""
    if not state.get("structured_intent"):
        return False  # perception 中断（追问）
    if not state.get("plan_confirmed"):
        return False  # planning 中断或等待确认
    if not state.get("task_statuses"):
        return False  # execution 未跑
    return True

# graph.py:1170-1179
if _should_append_turn_summary(final_state):
    _append_turn_summary(final_state)
    yield _build_turn_boundary_event(final_state)
# 否则只持久化，不发 turn_boundary 事件，不动 analysis_history
```

`safe_state` 持久化逻辑保留——追问中断的 state 也要落库（否则用户答追问时丢失上下文）。只是不动 analysis_history、不发 turn_boundary。

### 7.3 V6 新增修复 — `turn_status` 状态机替代缓冲区

V6 不引入"待提交缓冲区 / commit / rollback"——每个 task 完成立即落盘，简单可靠。turn 完整性由 manifest 条目的 `turn_status` 字段表达：

```python
# task 完成时（execution.py:_persist_task_to_workspace）
manifest["items"][task_id] = {
    ...,
    "status": "done",
    "turn_status": "ongoing",   # 标记本 turn 仍在进行
}

# turn 完整结束时（run_stream 末尾，仅当 _should_append_turn_summary 通过）
def _finalize_turn(workspace, turn_index):
    for item in workspace.manifest["items"].values():
        if item["turn_index"] == turn_index and item["turn_status"] == "ongoing":
            item["turn_status"] = "finalized"

# 新 turn 起步时（run_stream 续接分支开头）
def _abandon_orphaned_turn(workspace, prev_turn_index):
    """如果上一轮未 finalize（追问被用户彻底放弃后开新话题），标 abandoned."""
    for item in workspace.manifest["items"].values():
        if item["turn_index"] == prev_turn_index and item["turn_status"] == "ongoing":
            item["turn_status"] = "abandoned"
```

prompt 摘要规则（与"失败显式化"原则一致）：
- 渲染为可复用产物：`turn_status="finalized"` 且 `status="done"` 的条目
- 渲染为可复用产物：`turn_status="ongoing"` 且 `turn_index == 当前 turn` 且 `status="done"` 的条目（同 turn 内追问期间，已落盘的早期 task 仍可被本 turn 后续 task 引用）
- 渲染为**显式失败条目**（不静默过滤）：`status in {failed, unserializable, missing}` 的条目，附失败原因，让 LLM 自主决定是否重新 fetch
- 不渲染：`turn_status="abandoned"`（已被新轮否定）、跨轮 `turn_status="ongoing"`（本就是状态机的中间态，无审计价值）

好处：
- 没有"内存缓冲区/磁盘缓冲区"的位置抉择问题——manifest 永远是磁盘最新态
- 中途崩溃恢复天然可行（重启后读 manifest 即可，状态自带）
- 已完成的中间 task 可在追问解决后被本 turn 继续使用，不必重做

### 7.4 与 V6 主体的耦合

- §7.2.1 的 plan_history 归档保证 LLM 看到的"前轮规划思路"（§6.2 的第一块）非空。
- §7.2.2 的 turn_index 守卫保证 perception LLM 看到的轮次编号是真实的。
- §7.2.3 的 `_append_turn_summary` 守卫保证 §4.1 prompt 的【前轮分析摘要】块只包含真正完成的轮次。
- §7.3 的 `turn_status` 状态机保证 manifest prompt 摘要不被半成品污染——LLM 看到的"已有数据"反映真实可用产物。

四个修复缺一不可。

---

## 8. Layer 2 不动 / Layer 4 改造说明

### 8.1 Layer 2（上下文编织）不动

`analysis_history` 结构、`_build_turn_summary`、`trim_analysis_history`、`_build_multiturn_context_injection` 全部保留。V6 仅修改 `_multiturn_context` 字典的内容——增加 `workspace_manifest_summary` 字段供 prompt 使用。

### 8.2 Layer 4（执行层）改造

L4 当前实现：
- `_should_skip_data_fetch` 启发式判重
- `_params_match` 参数比对
- `_build_multiturn_execution_context` 把前轮 data_snapshots dict 注入下一轮（实际只是元信息，不是真数据）

V6 改造：
- 上述三个函数全部删除
- 新增 `_resolve_data_refs`（§5.3.1）
- 新增 `_persist_task_to_workspace`（§5.3.2）
- task 是否复用前轮数据完全由 plan 层 `data_ref` 决定，execution 层不再做猜测

---

## 9. 测试方案

### 9.1 删除

依赖已删函数的整套测试一并删除：

- `tests/unit/test_multiturn_classify.py` 整删（依赖 `_classify_turn`）
- `tests/unit/test_multiturn_amend_plan.py` 整删（依赖 `_build_amend_plan` / `_previous_artifacts` / `_previous_findings`）
- `tests/unit/test_multiturn_planning_pr2.py` 整删（依赖 `build_amend_plan` / `_previous_artifacts` / `_previous_findings`）
- `tests/unit/test_multiturn_execution.py` 整删（依赖 `_should_skip_data_fetch` / `_params_match` / `_build_multiturn_execution_context`）
- `tests/integration/test_multiturn_amend_execution.py` 整删（依赖 `build_amend_plan` 端到端）
- `tests/lib/multiturn_helpers.py:make_amend_state` 函数删除（amend 不再有独立 state 形态）

被删的测试覆盖面在 §9.2 新增的测试中以新的形式重新覆盖（amend 数据保真 / continue 数据复用 / workspace data_ref 解析）。

### 9.2 新增

#### 9.2.1 `tests/unit/test_session_workspace.py` — workspace 基础能力

```python
class TestSessionWorkspace:
    def test_persist_dataframe_as_parquet(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        df = pd.DataFrame({"month": ["2026-01"], "value": [100]})
        task = make_task("T001", type="data_fetch", tool="tool_api_fetch")
        ws.persist(task, ToolOutput(data=df, status="done"), turn_index=0)
        assert (tmp_path / "s1" / "workspace" / "T001.parquet").exists()
        item = ws.manifest["items"]["T001"]
        assert item["output_kind"] == "dataframe"
        assert item["rows"] == 1
        assert item["schema"]["columns"] == ["month", "value"]

    def test_persist_str_as_txt(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        task = make_task("T002", type="analysis", tool="tool_desc_analysis")
        ws.persist(task, ToolOutput(data="同比增长2.3%", status="done"), turn_index=0)
        item = ws.manifest["items"]["T002"]
        assert item["output_kind"] == "str"
        assert item["preview"] == "同比增长2.3%"

    def test_load_roundtrips_dataframe(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        df = pd.DataFrame({"x": list(range(100))})
        ws.persist(make_task("T001"), ToolOutput(data=df, status="done"), 0)
        loaded = ws.load("T001")
        assert isinstance(loaded.data, pd.DataFrame)
        assert len(loaded.data) == 100

    def test_failed_task_recorded_but_not_persisted(self, tmp_path):
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        task = make_task("T_FAIL", type="data_fetch")
        ws.persist(task, ToolOutput(data=None, status="failed"), 0)
        assert "T_FAIL" in ws.manifest["items"]
        assert ws.manifest["items"]["T_FAIL"]["status"] == "failed"
        assert not (tmp_path / "s1" / "workspace" / "T_FAIL.parquet").exists()

    def test_unserializable_data_marks_status(self, tmp_path):
        """parquet/feather/json 都失败 → status=unserializable，不写盘."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        task = make_task("T_BAD", type="data_fetch")
        # 构造一个三种序列化器都拒绝的对象（如循环引用 dict）
        bad = {}; bad["self"] = bad
        ws.persist(task, ToolOutput(data=bad, status="done"), 0)
        assert ws.manifest["items"]["T_BAD"]["status"] == "unserializable"
        assert ws.manifest["items"]["T_BAD"]["path"] is None

    def test_no_implicit_confirmed_propagation(self, tmp_path):
        """V6 取消隐式传播——report 完成不会自动标记上游为 confirmed."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001", type="data_fetch"), ToolOutput(data=pd.DataFrame({"x": [1]}), status="done"), 0)
        ws.persist(make_task("T002", type="analysis", depends_on=["T001"]), ToolOutput(data="...", status="done"), 0)
        ws.persist(make_task("R0_REPORT", type="report_gen", depends_on=["T002"]), ToolOutput(data=b"<html>", status="done"), 0)
        # 全部默认 confirmed=false
        assert ws.manifest["items"]["T001"]["user_confirmed"] is False
        assert ws.manifest["items"]["T002"]["user_confirmed"] is False
        assert ws.manifest["items"]["R0_REPORT"]["user_confirmed"] is False

    def test_explicit_confirm_persists_to_history(self, tmp_path):
        """用户主动点采纳 → confirmed=true + confirmed_history 追加记录."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"), ToolOutput(data=pd.DataFrame({"x": [1]}), status="done"), 0)
        ws.mark_confirmed("T001", source="user_marked", actor="alice")
        item = ws.manifest["items"]["T001"]
        assert item["user_confirmed"] is True
        assert len(item["confirmed_history"]) == 1
        assert item["confirmed_history"][0]["action"] == "confirm"
        assert item["confirmed_history"][0]["actor"] == "alice"
        # 撤销后历史保留
        ws.mark_unconfirmed("T001", actor="alice")
        assert ws.manifest["items"]["T001"]["user_confirmed"] is False
        assert len(ws.manifest["items"]["T001"]["confirmed_history"]) == 2

    def test_load_missing_file_raises(self, tmp_path):
        """落盘后文件被外部删除，再 load 应明确报错."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"), ToolOutput(data=pd.DataFrame({"x": [1]}), status="done"), 0)
        # 模拟外部删除
        (tmp_path / "s1" / "workspace" / "T001.parquet").unlink()
        with pytest.raises(WorkspaceError, match="missing|not found"):
            ws.load("T001")

    def test_manifest_status_marked_missing_on_reload(self, tmp_path):
        """重新加载 workspace 时校验 path 存在性，缺失文件标 status=missing."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"), ToolOutput(data=pd.DataFrame({"x": [1]}), status="done"), 0)
        (tmp_path / "s1" / "workspace" / "T001.parquet").unlink()
        # 重新加载（模拟进程重启）
        ws_reloaded = SessionWorkspace(session_id="s1", root=tmp_path)
        ws_reloaded.validate_paths()
        assert ws_reloaded.manifest["items"]["T001"]["status"] == "missing"

    def test_turn_status_lifecycle(self, tmp_path):
        """task 落盘 → ongoing；turn finalize → finalized；新 turn 起步 → 旧 ongoing 转 abandoned."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T001"), ToolOutput(data=pd.DataFrame({"x": [1]}), status="done"), turn_index=0)
        assert ws.manifest["items"]["T001"]["turn_status"] == "ongoing"
        ws.finalize_turn(turn_index=0)
        assert ws.manifest["items"]["T001"]["turn_status"] == "finalized"
        # 模拟 R1 进入了 ongoing 但被放弃
        ws.persist(make_task("R1_T001"), ToolOutput(data=pd.DataFrame({"x": [2]}), status="done"), turn_index=1)
        ws.abandon_orphaned_turn(turn_index=1)
        assert ws.manifest["items"]["R1_T001"]["turn_status"] == "abandoned"

    def test_failed_task_visible_in_prompt_summary(self, tmp_path):
        """失败 / unserializable / missing 条目必须出现在 prompt 摘要中（失败显式化）."""
        ws = SessionWorkspace(session_id="s1", root=tmp_path)
        ws.persist(make_task("T_OK"), ToolOutput(data=pd.DataFrame({"x": [1]}), status="done"), 0)
        ws.persist(make_task("T_FAIL", type="data_fetch"), ToolOutput(data=None, status="failed", error="endpoint timeout"), 0)
        bad = {}; bad["self"] = bad
        ws.persist(make_task("T_BAD"), ToolOutput(data=bad, status="done"), 0)
        summary = ws.render_prompt_summary()
        assert "T_OK" in summary
        assert "T_FAIL" in summary and "失败" in summary
        assert "T_BAD" in summary and ("unserializable" in summary or "无法序列化" in summary)
```

#### 9.2.2 `tests/unit/test_workspace_data_ref.py` — 跨轮 data_ref 解析

```python
async def test_resolve_data_ref_loads_from_workspace(tmp_path):
    """task 引用前轮 task_id，execution 自动从 workspace 加载."""
    ws = seed_workspace(tmp_path, items={"T001": pd.DataFrame({"x": [1, 2, 3]})})
    task = make_task("R1_ATTR", params={"data_ref": "T001"})
    execution_context = {}
    await _resolve_data_refs(task, execution_context, ws)
    assert "T001" in execution_context
    assert len(execution_context["T001"].data) == 3

async def test_resolve_data_refs_list(tmp_path):
    """data_refs 列表形式同时解析多个."""
    ws = seed_workspace(tmp_path, items={"T001": ..., "T002": ...})
    task = make_task("R1_REPORT", params={"data_refs": ["T001", "T002"]})
    ec = {}
    await _resolve_data_refs(task, ec, ws)
    assert {"T001", "T002"} <= set(ec)

async def test_resolve_failfast_on_missing_ref(tmp_path):
    ws = SessionWorkspace("s1", tmp_path)
    task = make_task("R1_X", params={"data_ref": "GHOST"})
    with pytest.raises(TaskError, match="unknown data_ref='GHOST'"):
        await _resolve_data_refs(task, {}, ws)

async def test_resolve_skips_when_already_in_context(tmp_path):
    """同轮上游已产出的不重新加载."""
    ws = SessionWorkspace("s1", tmp_path)
    task = make_task("R1_DOWN", params={"data_ref": "R1_UP"})
    ec = {"R1_UP": ToolOutput(data="from upstream", status="done")}
    await _resolve_data_refs(task, ec, ws)
    assert ec["R1_UP"].data == "from upstream"  # 未被 manifest miss 覆盖
```

#### 9.2.3 `tests/integration/test_amend_data_fidelity.py` — amend 数据保真

**这是 V6 必须通过的关键测试**（§12 验收 #4 的支撑测试）：

```python
async def test_amend_pptx_uses_full_dataframe(multiturn_db_state, recorded_llm):
    """R1 amend 'PPTX' 后，PPTX 内含数据行数 == R0 原始 DataFrame 行数（不是 sample 3 行）."""
    sid = multiturn_db_state  # R0 已完成，T001 含 100 行 DataFrame

    # R1: 触发 amend
    events = await consume_run_stream(sid, "user_x", "再来一份 PPT")
    state = await load_state(sid)
    assert state["turn_type"] == "amend"

    # 找到 R1 PPTX artifact
    pptx_aid = next(
        e["artifact_id"] for e in events
        if e.get("type") == "task_results" and "pptx" in e.get("tool", "")
    )
    pptx_bytes = await download_artifact(pptx_aid)

    import pptx, io
    prs = pptx.Presentation(io.BytesIO(pptx_bytes))
    table_rows = sum(
        len(shape.table.rows) - 1   # 减表头
        for slide in prs.slides
        for shape in slide.shapes
        if shape.has_table
    )
    # R0 的 T001 在 fixture 里是 100 行
    assert table_rows >= 50, f"PPTX 只含 {table_rows} 行，疑似只用了 sample 3 行而非完整数据"
```

#### 9.2.4 `tests/integration/test_continue_data_reuse.py` — continue 数据复用

```python
async def test_continue_attribution_reuses_r0_data_no_refetch(
    multiturn_db_state, recorded_llm, mock_api_server
):
    """R1 '详细分析下降原因' 应复用 R0 的 T001，不发起新 fetch."""
    sid = multiturn_db_state
    fetch_count_before = mock_api_server.call_count("getThroughputAnalysisByYear")

    await consume_run_stream(sid, "user_x", "详细分析下降原因")
    state = await load_state(sid)

    fetch_count_after = mock_api_server.call_count("getThroughputAnalysisByYear")
    assert fetch_count_after == fetch_count_before, (
        "R1 不应重新 fetch 同端点同参数"
    )

    r1_plan = state["analysis_plan"]
    attr_task = next(t for t in r1_plan["tasks"] if t["tool"] == "tool_attribution")
    assert attr_task["params"]["data_ref"] == "T001", (
        f"R1_ATTR 应 data_ref=T001，实际 {attr_task['params'].get('data_ref')}"
    )
```

#### 9.2.5 意图样例矩阵

`tests/unit/test_multiturn_intent_matrix.py` — 用 `recorded_llm` fixture 录制/回放，覆盖同语义不同措辞的意图分类：

```python
INTENT_MATRIX = [
    # ── new ──
    ("multiturn_state", "换个话题，分析下设备完好率", "new", False),
    ("multiturn_state", "新分析：港口投资回报", "new", False),
    ("multiturn_state", "不相关的问题，集装箱客户名单怎么导出", "new", False),

    # ── continue（深化/钻取） ──
    ("multiturn_state", "按港区拆分看看", "continue", False),
    ("multiturn_state", "为什么 3 月环比下降这么多", "continue", False),
    ("multiturn_state", "和去年 Q1 对比一下", "continue", False),
    ("multiturn_state", "详细说说大窑湾港区", "continue", False),

    # ── continue（参数变化） ──
    ("multiturn_state", "把时间范围扩大到全年", "continue", False),
    ("multiturn_state", "再加 2024 年的数据做对比", "continue", False),  # ← 关键词路由必误判为 amend
    ("multiturn_state", "把粒度改成日度", "continue", False),

    # ── amend（明确格式） ──
    ("multiturn_state", "再加一个 PPTX 报告", "amend", False),
    ("multiturn_state", "也来一份 Word", "amend", False),               # ← 关键词路由漏判
    ("multiturn_state", "还要个 PPT", "amend", False),                  # ← 关键词路由漏判
    ("multiturn_state", "把 HTML 换成 PPTX", "amend", False),
    ("multiturn_state", "导出为 PDF", "amend", False),

    # ── 边界（应归 continue 而非 amend） ──
    ("multiturn_state", "换个角度看吞吐量", "continue", False),         # ← 关键词路由误判 amend
    ("multiturn_state", "把分析换成同比口径", "continue", False),       # ← 关键词路由误判 amend
]

@pytest.mark.parametrize("fixture_name, msg, expected_turn, expected_clar", INTENT_MATRIX)
async def test_perception_intent_matrix(
    request, recorded_llm, fixture_name, msg, expected_turn, expected_clar
):
    prev_state = request.getfixturevalue(fixture_name)
    state = make_continue_message(turn_index=1, message=msg, prev_state=prev_state)
    state["_multiturn_context"] = _build_multiturn_context_injection(state)

    result = await run_perception(state)

    assert result["turn_type"] == expected_turn, (
        f"msg={msg!r} expected {expected_turn} got {result['turn_type']} "
        f"reasoning={result.get('reasoning')}"
    )
    assert bool(result.get("current_target_slot")) == expected_clar
```

通过率门槛：≥85%（17 条至少 15 条对）。低于阈值时单条标 xfail 但不修代码绕过——根因要么是 prompt 表达不清，要么是样例本身有歧义。

`multiturn_state` fixture 在 §10.2 列出的新增 helper 中提供，含 V6 形式的 workspace manifest。

#### 9.2.6 续接 + 追问场景

`tests/integration/test_multiturn_clarification_continuity.py` — 验证 §7.1 三个 bug 都被修复 + workspace 不被污染：

```python
async def test_clarification_does_not_inflate_turn_index(multiturn_db_state, recorded_llm):
    """R1 触发 2 次追问，turn_index 应保持为 1 不变，最终完成时才 +1."""
    sid = multiturn_db_state  # R0 已完成，turn_index=0

    # 第 1 次消息：触发追问
    await consume_run_stream(sid, "user_x", "深入看一下")
    state = await load_state(sid)
    assert state["turn_index"] == 1                 # 自增一次（R1 开启）
    assert state["structured_intent"] is None       # perception 未通过
    assert state.get("current_target_slot") is not None

    # 用户答追问
    await consume_run_stream(sid, "user_x", "按港区拆分时间用 Q1")
    state = await load_state(sid)
    assert state["turn_index"] == 1                 # 不再自增（仍在 R1 内）
    assert state["structured_intent"] is not None    # perception 终于通过
    assert state["plan_confirmed"]                   # planning 与 execution 跑完

async def test_clarification_does_not_pollute_analysis_history(multiturn_db_state, recorded_llm):
    """追问中断不应 append analysis_history."""
    sid = multiturn_db_state
    initial_history_len = 1

    await consume_run_stream(sid, "user_x", "深入看看")
    state = await load_state(sid)
    assert len(state["analysis_history"]) == initial_history_len

    await consume_run_stream(sid, "user_x", "按港区拆分时间用 Q1")
    state = await load_state(sid)
    assert len(state["analysis_history"]) == initial_history_len + 1

async def test_plan_history_archived_on_continue(multiturn_db_state, recorded_llm):
    """R1 续接时，R0 plan 应已归档到 plan_history."""
    sid = multiturn_db_state
    await consume_run_stream(sid, "user_x", "按港区拆分看看")
    state = await load_state(sid)
    assert len(state["plan_history"]) == 1
    assert state["plan_history"][0]["plan_id"] == "plan-r0-int"

async def test_clarification_does_not_pollute_workspace(multiturn_db_state, recorded_llm):
    """追问中断不应往 manifest 写半成品."""
    sid = multiturn_db_state
    await consume_run_stream(sid, "user_x", "深入看看")
    state = await load_state(sid)
    ws = SessionWorkspace.for_session(sid)
    # manifest 仅含 R0 的 finalized 条目，无 R1 的 ongoing 半成品
    for item in ws.manifest["items"].values():
        assert item["turn_index"] == 0
        assert item["turn_status"] == "finalized"
```

#### 9.2.7 new 模式跨轮引用硬约束

`tests/unit/test_planning_blocks_cross_turn_ref_in_new_topic.py` — 验证 §6.1.3 的硬约束：

```python
async def test_new_mode_rejects_cross_turn_data_ref(multiturn_db_state, recorded_llm):
    """turn_type=new 时 plan 中若引用前轮 task_id，planning 应抛 PlanValidationError."""
    sid = multiturn_db_state  # R0 含 T001 / T002 已 finalized

    # Mock LLM 故意输出违规 plan：new 话题但引用了 R0 的 T001
    recorded_llm.queue_plan({
        "tasks": [
            {"task_id": "R1_X", "type": "analysis", "tool": "tool_attribution",
             "params": {"data_ref": "T001"}}
        ]
    })

    with pytest.raises(PlanValidationError, match="cross-turn data_ref.*T001"):
        await consume_run_stream(sid, "user_x", "换个话题，分析设备完好率")

async def test_new_mode_accepts_same_turn_data_ref(multiturn_db_state, recorded_llm):
    """new 模式下引用本轮新 fetch 出来的数据应该正常."""
    sid = multiturn_db_state
    # plan 内部 DAG 没问题：R1_FETCH 产数据 → R1_ATTR 引用
    await consume_run_stream(sid, "user_x", "换个话题，分析设备完好率")
    state = await load_state(sid)
    plan = state["analysis_plan"]
    refs_in_plan = [t["params"].get("data_ref") for t in plan["tasks"]]
    # 不应出现指向 turn_index=0 的旧 task
    for ref in refs_in_plan:
        if ref:
            assert ref.startswith("R1_") or ref not in ["T001", "T002"]
```

### 9.3 集成测试保留

- `test_multiturn_state_persistence.py` 保留
- `test_multiturn_context_injection.py` 调整：context 来源从 analysis_history 切到 workspace_manifest_summary

### 9.4 回归阈值

| 测试 | 期望 |
|---|---|
| `test_session_workspace.py` | 100% 通过 |
| `test_workspace_data_ref.py` | 100% 通过 |
| `test_amend_data_fidelity.py` | 100% 通过（**V6 阻断式验收**） |
| `test_continue_data_reuse.py` | 100% 通过（**V6 阻断式验收**） |
| `test_multiturn_intent_matrix.py` | ≥15/17（≥88%） |
| `test_multiturn_clarification_continuity.py` | 100% 通过 |
| `test_planning_blocks_cross_turn_ref_in_new_topic.py` | 100% 通过（**V6 阻断式验收**） |
| `test_multiturn_liangang.py` | 100% 通过 |
| 既有 L2 测试 | 100% 通过（不允许回归） |

---

## 10. 改动清单（一次合并）

### 10.1 删除

| 文件 | 内容 |
|---|---|
| `backend/agent/graph.py` | `_classify_turn`、`_build_amend_plan`、run_stream amend 分支 |
| `backend/agent/planning.py` | `build_amend_plan`、`_previous_artifacts` / `_previous_findings` 注入 |
| `backend/agent/perception.py` | continue 模式 `empty_required = []` 强制、conv_history 摘要塞入 |
| `backend/agent/execution.py` | `_should_skip_data_fetch`、`_params_match`、`_build_multiturn_execution_context`、`_collect_report_context`（transitive deps 打包） |
| `backend/memory/artifact_store.py` | `_context_dir` / `write_conversion_context` / `read_conversion_context` (artifact_store.py:238-288)；保留 artifact 文件本身 |
| `backend/tools/report/_outline_planner.py` | `_previous_artifacts` 处理段（_outline_planner.py:103-130） |
| `backend/main.py` | `read_conversion_context` 调用点（main.py:621），随上游一同删除 |
| `tests/unit/test_multiturn_classify.py` | 整删 |
| `tests/integration/test_multiturn_amend_execution.py` | 整删 |
| `tests/lib/multiturn_helpers.py` | `make_amend_state` |

### 10.2 新增

| 文件 | 内容 |
|---|---|
| `backend/memory/session_workspace.py` | `SessionWorkspace` 类、manifest 读写、persist/load/rollback、confirmed 传播 |
| `backend/agent/execution.py` | `_resolve_data_refs`、`_persist_task_to_workspace` |
| `backend/agent/perception.py` | `MULTITURN_INTENT_PROMPT` 常量、`_run_multiturn_perception` 函数、`_merge_slots_with_delta` |
| `backend/agent/planning.py` | `WORKSPACE_BLOCK` 常量、`_render_manifest_summary_table` 函数 |
| `backend/main.py` | `GET /api/sessions/{id}/workspace` 接口（用户与前端访问 manifest） |
| `backend/main.py` | `POST /api/sessions/{id}/workspace/{task_id}/confirm` 与 `/unconfirm` |
| WS 事件 | `workspace_update`：当 manifest 有新增/标记变更时广播 |
| `tests/unit/test_session_workspace.py` | §9.2.1 |
| `tests/unit/test_workspace_data_ref.py` | §9.2.2 |
| `tests/integration/test_amend_data_fidelity.py` | §9.2.3 |
| `tests/integration/test_continue_data_reuse.py` | §9.2.4 |
| `tests/integration/test_multiturn_clarification_continuity.py` | §9.2.6 |

> **前端范围声明**：V6 实现后端 API + WebSocket 事件即视为完成本 spec 的范围。前端 manifest inspector 面板、采纳按钮 UI、跨轮数据来源标签等渲染与交互由独立 spec [`spec/optimize_session_visibility_V1.md`](optimize_session_visibility_V1.md)（待编写）覆盖。V6 落地后前端 manifest 显示能力暂时不变——LLM/Agent 已能正确利用 workspace，用户可见性单独迭代。

### 10.3 修改

| 文件 | 修改 |
|---|---|
| `backend/agent/perception.py` | `run_perception` 顶部分流；MULTITURN_INTENT_PROMPT 增加 manifest 摘要字段 |
| `backend/agent/graph.py` | `run_stream` 简化为 §4.3 形式 + §7 三个 bug 修复 |
| `backend/agent/planning.py` | `multi_turn_text` 替换为 `WORKSPACE_BLOCK` + manifest 摘要表 |
| `backend/agent/execution.py` | task 启动前调 `_resolve_data_refs`；task 完成后调 `_persist_task_to_workspace`；execution_node 收尾时 commit/rollback workspace |
| `backend/memory/artifact_store.py` | `persist_artifact` 仅写 artifact 文件，不再 pickle context |
| `backend/tools/report/_outline_planner.py` | 删除 `_previous_artifacts` 处理段（103-130），改为标准 `data_refs` 协议直接从 execution_context 取（由 `_resolve_data_refs` 保证已加载） |
| `backend/tools/report/{html_gen,pptx_gen,docx_gen,markdown_gen}.py` | 工具入口签名不变；不再依赖任何 `_previous_*` 参数 |
| `tests/lib/multiturn_helpers.py` | `make_continue_message` 简化为追加 message + 清空 intent/turn_type；新增 `seed_workspace` / `make_task` / `consume_run_stream` helper |
| `tests/scenarios/test_multiturn_liangang.py` | 移除 `_classify_turn` 调用；R3 amend 断言改用 manifest 验证 |
| DB schema | sessions 表新增 `workspace_manifest_json` JSON 列（alembic 迁移，旧 session 默认 NULL，加载时惰性创建空 manifest） |

> 校验确认：[backend/tools/report/_content_collector.py](../backend/tools/report/_content_collector.py) 不引用 `_previous_artifacts` / `conversion_context`，**无需改动**。其他报告子模块（`_block_renderer.py` / `_chart_renderer.py` / `_pptxgen_*` 等）也无跨轮数据假设。

### 10.4 不动

- AgentState `turn_index` / `turn_type` / `analysis_history` / `plan_history` 字段
- `analysis_history` 结构、`trim_analysis_history`、`_build_turn_summary`
- `turn_boundary` 事件、并发锁、四阶段 LangGraph 状态机
- 前端现有 turn_type 显示、TurnDivider、ContextSummaryCard

---

## 11. 风险与应对

| ID | 风险 | 应对（不引入灰度） |
|----|------|-------------------|
| R1 | manifest 增长导致 prompt 超长 | 摘要时优先保留 `confirmed=true` + 最近 2 轮全部条目；其余按 turn 折叠为一行"还有 N 项已折叠（详见 inspector）" |
| R2 | parquet/json 落盘 I/O 慢，阻塞 task 流 | 落盘异步化（`asyncio.to_thread`）；下一 task 的 `_resolve_data_refs` 等待落盘完成（用 await，单 session 串行无竞态）。**落盘异常必须穿透为 task 失败**（不允许 await 后吞异常当成功，符合"失败显式化"原则） |
| R3 | LLM 引用了 `confirmed=false` 的数据 | prompt 明确"未确认数据仅在用户明确指向时使用"；LLM 实际行为通过意图矩阵 + amend/continue 端到端测试覆盖 |
| R4 | `data_ref` 字符串拼写错（如 LLM 写 "T01" 而 manifest 是 "T001"） | execution 层 fail-fast，task 失败带明确错误信息；不做模糊匹配兜底 |
| R5 | 跨进程并发（同 session 多客户端）写 manifest 冲突 | session 内 run_lock 已串行化；workspace 内部用文件锁（fcntl）保护 manifest.json |
| R6 | 现有 report 工具假设 `_previous_artifacts` 存在 | 校验确认改造面**仅 `_outline_planner.py:103-130` 一处**——`_content_collector.py` / chart 渲染 / pptx_gen 等不引用 `_previous_artifacts` 或 `conversion_context`。改造完成后报告工具完全用标准 `data_refs` 协议 |
| R7 | 用户 confirm 后又改主意 | 提供 unconfirm API + UI 按钮；confirmed 状态变更写入 `confirmed_history` 字段供审计 |
| R8 | parquet 不支持某些 dtype（如 object 列含混合类型） | 落盘前做 dtype 标准化（object→str / numeric coercion）；仍失败则降级 feather（pyarrow IPC，dtype 宽容）；feather 也失败 → **task 整体翻为 failed 状态**（execution 抛 `TaskError`、前端发 `task_error` 事件），manifest 条目标 `status=unserializable` 并在 prompt 中显式呈现失败原因，LLM 自主决定是否重新规划 fetch。**不使用 pickle**（避免反序列化 RCE）。**不允许"task=done 但产物悄悄不可用"** |
| R9 | workspace 文件被外部清理（如 docker 重建） | manifest 加载时校验 path 存在性，缺失条目标 `status=missing`，按"失败显式化"原则在 prompt 摘要中显式标注 `[已淘汰: 文件清理]`（不静默过滤）。LLM 自主判断是否重新 fetch |

> **不做的兜底**：不保留 `_previous_artifacts` 协议作为 fallback、不保留 `conversion_context.pkl`、不在 settings 加 `enable_workspace` 开关。错了就改 prompt 或代码，不引入分支让两套逻辑并存。

---

## 12. 验收标准

合并到 master 前必须满足：

1. **关键词清零**：`grep -rn "_classify_turn\|build_amend_plan\|amend_keywords\|new_topic_keywords\|_previous_artifacts\|_previous_findings\|_should_skip_data_fetch\|_params_match\|conversion_context\|read_conversion_context\|_collect_report_context\|_build_multiturn_execution_context" backend/ tests/` 全部为空（仅允许 spec 文档保留历史描述）。
2. **意图矩阵**：`tests/unit/test_multiturn_intent_matrix.py` ≥88% 通过。
3. **workspace 基础能力**：`test_session_workspace.py` + `test_workspace_data_ref.py` 100% 通过。
4. **amend 数据保真**：`test_amend_data_fidelity.py` 100% 通过。R1 PPTX 内含数据行数 ≥ R0 HTML 数据行数（验证不退化为 sample 3 行）。
5. **continue 数据复用**：`test_continue_data_reuse.py` 100% 通过。R1 plan 在 manifest 命中时不重新 fetch。
6. **场景测试**：`test_multiturn_liangang.py` R0→R1→R2→R3 全链路通过，R3 amend plan 含 `data_refs` 指向 R0/R1/R2 manifest 条目。
7. **续接+追问**：`test_multiturn_clarification_continuity.py` 100% 通过——证明 §7 三个 bug 已修复，且追问中断不污染 workspace。
8. **既有 L2 测试**：100% 通过（不允许回归）。
9. **端到端手测（4 轮 + 1 confirm 操作）**：
   - R0: "分析 2026 Q1 大连港吞吐量，HTML" → workspace 含 6 条目，全部 confirmed=true（被 R0 报告引用）
   - R1: "详细分析下降原因" → continue，R1_ATTR 任务 `data_ref="T001"`，未发起新 fetch
   - R2: "再加 2024 年同期对比" → continue，新 R2_T001（新 fetch），R2_COMP（`data_refs=["T001", "R2_T001"]`）
   - R3: "再来一份 PPTX" → amend，R3_REPORT_PPTX `data_refs=["T001", "T002", "R2_COMP"]`，PPTX 内含完整数据
   - 用户在 R0 T001 卡片点"采纳" → workspace API 返回 `user_confirmed=true, confirmed_source=user_marked`
10. **手测追问**：R1 用模糊"深入看看"触发追问 2 次，全部完成后查 DB：`turn_index==1`、`analysis_history` 长度==2、`plan_history` 长度==1、workspace manifest 不含 R1 半成品条目。
11. **无隐式降级审计**（落实"失败显式化"原则）：合并前对 `backend/tools/report/`、`backend/agent/execution.py`、`backend/memory/session_workspace.py` 做人工审计，提交一份"所有可能 task 看似 done 但产物未达预期的代码路径清单"——清单为空（或全部已改为 fail-fast）则通过。重点排查模式：
    - `try / except: return default_value`（吞异常返回默认值）
    - `data.head(N) if not full_data else full_data`（找不到完整数据时退化为 sample）
    - `if data is None: data = pd.DataFrame()`（占位空表使下游"成功"）
    - manifest 失败条目被 `if status != "done": continue` 静默跳过（应改为显式渲染）
    - parquet/feather 落盘异常被 catch 后仅记 warning（应翻 task 失败）
12. **new 模式跨轮引用守护**：`test_planning_blocks_cross_turn_ref_in_new_topic.py` 100% 通过，证明硬约束（§6.1.3）生效。

---

## 13. 与已有代码 / 历史 spec 的关系

### 13.1 当前代码的处理

| 组件 | V6 处理 |
|---|---|
| L2 上下文编织（`analysis_history` / `_build_turn_summary` / `trim_analysis_history`） | 保留 |
| `_classify_turn` 关键词路由（[graph.py:128-147](../backend/agent/graph.py#L128)） | **删除**（§4） |
| run_stream amend 分支（[graph.py:946-1035](../backend/agent/graph.py#L946)） | **删除**（§4.4） |
| `build_amend_plan` 规则引擎（[planning.py:659](../backend/agent/planning.py#L659)） | **删除**（§5.6） |
| `_should_skip_data_fetch` / `_params_match` / `_build_multiturn_execution_context` / `_collect_report_context` | **删除**（§5.6 / §8.2） |
| `conversion_context.pkl` + `_previous_artifacts` 协议 | **删除**（§5.6） |
| 前端 turn_type 显示、TurnDivider、ContextSummaryCard | 保留（前端 manifest 渲染独立 spec） |

### 13.2 历史 spec 索引

V6 是当前 spec 的实施目标，自包含。如需了解设计演进，可参考：

- [`spec/optimize_multiturn_conversationV1.md`](optimize_multiturn_conversationV1.md) — 最初版本，五种 turn_type 关键词路由
- [`spec/optimize_multiturn_conversationV3.md`](optimize_multiturn_conversationV3.md) — 已合并版本，引入 L2 `analysis_history` + L4 启发式判重
- [`spec/optimize_multiturn_conversationV5.md`](optimize_multiturn_conversationV5.md) — 中间方案（未合并），把意图路由改为 LLM、把 amend 吸收进 planning。V6 取代 V5：V5 在 amend / continue 数据复用上保留两套机制，V6 用统一 SessionWorkspace 取代

### 13.3 落地策略

V6 一个 PR 合入。不分阶段、不灰度。但 PR 内部按以下 commit 边界组织，便于 reviewer 逐 commit 审阅而非在 1500+ 行 diff 中跳转：

| Commit | 范围 | 配套测试 | 单 commit 应可独立通过的测试 |
|---|---|---|---|
| 1 | **SessionWorkspace 基础** — `backend/memory/session_workspace.py` 类、manifest 读写、parquet/json/feather 序列化、文件锁、status 枚举、turn_status 状态机、`render_prompt_summary`（含失败条目显式渲染）。**不含** backfill 逻辑（§5.2.6 已说明 V6 不做历史兼容） | `tests/unit/test_session_workspace.py` 全部 | commit 1 |
| 2 | **DB schema 扩展** — alembic 迁移加 `sessions.workspace_manifest_json` JSON 列；`MemoryStore.get_session` 加载时若 manifest 不存在则**初始化空 manifest**（不做 backfill） | （无独立测试，集成测试覆盖） | commit 1+2 |
| 3 | **execution 层 hook** — `_resolve_data_refs`、`_persist_task_to_workspace`（落盘失败穿透为 `TaskError`）、`_finalize_turn`、`_abandon_orphaned_turn` | `tests/unit/test_workspace_data_ref.py` 全部 | commit 1+2+3 |
| 4 | **planning prompt 重做 + new 模式硬约束** — `WORKSPACE_BLOCK` 常量、`_render_manifest_summary_table`、planning_node 注入逻辑、`PlanValidationError` 在 turn_type=new 且引用前轮 task_id 时抛出 | `tests/unit/test_planning_blocks_cross_turn_ref_in_new_topic.py` | commit 1+2+3+4 |
| 5 | **perception LLM 路由** — `MULTITURN_INTENT_PROMPT`、`_run_multiturn_perception`、run_stream 简化 + §7 三个 bug 修复 | `tests/unit/test_multiturn_intent_matrix.py`、`tests/integration/test_multiturn_clarification_continuity.py` | commit 1-5 |
| 6 | **report 工具改造 + 删除旧机制 + 隐式降级审计** — `_outline_planner.py` 去 `_previous_artifacts`；删除 `build_amend_plan` / `_should_skip_data_fetch` / `_params_match` / `_build_multiturn_execution_context` / `_collect_report_context` / `conversion_context` 系列函数；删除依赖这些的旧测试。**人工审计 `tools/report/` 全部 silent fallback 路径并改 fail-fast**（§12 验收 #11） | `tests/integration/test_amend_data_fidelity.py`、`tests/integration/test_continue_data_reuse.py`、`tests/scenarios/test_multiturn_liangang.py` | commit 1-6（全部） |
| 7 | **API + WebSocket** — `GET /api/sessions/{id}/workspace`、`POST .../confirm`、`POST .../unconfirm`、`workspace_update` WS 事件 | （前端联调测试，§12 验收 #9） | commit 1-7 |

每个 commit 的 PR 描述里独立写一段 "本 commit 做了什么 / 为什么需要 / 与下一 commit 的关系"，让 reviewer 可顺序看完。

合并后 reviewer 在 GitHub 上仍以单 PR 形式 squash 或 merge commit；commit 边界仅服务 review 体验，不进 master 历史（如选 squash），或按时间序保留（如选 merge）。
