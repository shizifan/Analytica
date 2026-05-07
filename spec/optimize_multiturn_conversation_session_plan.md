# V6 多轮对话能力优化 — 会话执行手册

**配套 spec**：[`optimize_multiturn_conversation.md`](optimize_multiturn_conversation.md)（V6，1371 行）
**目标**：把 §13.3 的 7 个 commit 落到 6 个独立会话，控制单会话上下文量，跨会话有清晰交接。
**适用对象**：每个会话只读本手册对应小节 + spec 中点名的章节，不读 spec 全文。

---

## 总览

| 会话 | 包含 commit | 主题 | 上下文风险 |
|---|---|---|---|
| **S1** | 1 + 2 | SessionWorkspace 基础 + DB 迁移 | 中 |
| **S2** | 3 | execution 层 hook | 低 |
| **S3** | 4 | planning prompt 重做 + new 模式硬约束 | 低-中 |
| **S4** | 5 | perception LLM 路由 + 三个 bug 修复 | 中-高 |
| **S5** | 6 | 删除旧机制 + report 工具改造 + 隐式降级审计 | **高**（必要时拆 S5a/S5b） |
| **S6** | 7 | workspace API + WebSocket | 低 |

依赖：S2 依赖 S1；S3 依赖 S1+S2；S4 依赖 S1-S3；S5 依赖 S1-S4；S6 仅依赖 S1。**严格按顺序执行**。

每个会话开头第一件事：`git log --oneline` 确认前置 commit 已落地，`pytest -x <前置会话产出的测试>` 确认未回归。

---

## S1：SessionWorkspace 基础 + DB 迁移

### 目标
落地 workspace 类 + alembic 迁移。开发期不做历史 backfill。

### 必读 spec 章节
- §2（设计原则，含"失败显式化"）
- §5.2.1 / §5.2.2 / §5.2.3 / §5.2.5 / §5.2.6（落盘策略 / manifest 结构 / confirmed 语义 / 清理 / 不兼容历史）
- §7.3（turn_status 状态机）
- §11 R5/R8/R9（文件锁、序列化降级、外部清理）

### 新增文件
- `backend/memory/session_workspace.py`：`SessionWorkspace` 类
  - `persist(task, output, turn_index)`：parquet → 标准化重试 → feather → 失败抛 `WorkspaceSerializationError`
  - `load(task_id) -> ToolOutput`：缺文件抛 `WorkspaceError`
  - `mark_confirmed` / `mark_unconfirmed` / `confirmed_history`
  - `finalize_turn(turn_index)` / `abandon_orphaned_turn(turn_index)`
  - `validate_paths()`：加载时对 manifest 中所有 path 做存在性校验，缺失标 `status="missing"`
  - `render_prompt_summary()`：含失败条目显式渲染（`[失败: 序列化不支持] T_BAD`）
  - 文件锁：`fcntl.flock` 保护 `manifest.json` 写入
- `migrations/versions/<rev>_add_workspace_manifest.py`：在 `sessions` 表加 `workspace_manifest_json JSON NULL` 列
- `tests/unit/test_session_workspace.py`：spec §9.2.1 全部用例（含失败条目可见性测试，**不**含 backfill 测试）

### 修改文件
- `backend/memory/__init__.py`：导出 `SessionWorkspace`
- `backend/database.py` 或 `backend/memory/<store>.py`：`get_session` 加载时若 `workspace_manifest_json` 为 NULL 则初始化空 manifest（不做 backfill）
- `backend/config.py`：加 `WORKSPACE_ROOT`、`WORKSPACE_MAX_ITEMS_PER_SESSION=100`

### 验证清单
```bash
pytest tests/unit/test_session_workspace.py -v        # 全绿
alembic upgrade head && alembic downgrade -1          # 迁移可逆
alembic upgrade head                                   # 准备给后续会话用
```

### 交接给 S2
**关键产出**：
- `SessionWorkspace` 类已可独立 persist / load DataFrame / dict / str / bytes
- DB schema 已扩展，新建 session 自动有空 manifest
- `WorkspaceError` / `WorkspaceSerializationError` 异常类型已定义

**S2 起步要做**：在 execution 层接入这个类，开始往 manifest 写 task 产出。

---

## S2：execution 层 hook

### 目标
让每个 task 启动前自动 `_resolve_data_refs`、完成后自动 `_persist_task_to_workspace`。落盘异常穿透为 task 失败（"失败显式化"）。

### 必读 spec 章节
- §5.3.1 / §5.3.2（execution hook 代码骨架）
- §5.5（data_ref 协议承载位置——在 `task.params` dict 里）
- §11 R2（落盘异常必须穿透为 task 失败）

### 新增文件
- `tests/unit/test_workspace_data_ref.py`：spec §9.2.2 全部用例

### 修改文件
- `backend/agent/execution.py`：
  - 新增 `_resolve_data_refs(task, execution_context, workspace)`：扫 `task.params["data_ref" / "data_refs"]`，按 spec §5.3.1 的查找顺序解析
  - 新增 `_persist_task_to_workspace(task, output, state, workspace)`
  - 新增 `_finalize_turn(workspace, turn_index)` / `_abandon_orphaned_turn(workspace, prev_turn_index)`
  - task 调度循环：启动前调 `_resolve_data_refs`、完成后调 `_persist_task_to_workspace`
  - **关键**：`_persist_task_to_workspace` 抛异常时把 task 状态翻 `failed` 并广播 `task_error`，不允许 await 后吞异常

### 验证清单
```bash
pytest tests/unit/test_session_workspace.py tests/unit/test_workspace_data_ref.py -v
# 跑一个最小 R0 端到端冒烟（fetch + analysis），确认 manifest 落了 2 条
```

### 交接给 S3
**关键产出**：
- task 启动/完成两端 hook 已就绪
- 同 turn 上游 task 产出可被下游通过 `data_ref` 引用并自动加载
- 跨 turn 引用尚不可用（因为 planning 还没生成带 `data_ref` 的 plan，由 S3 解决）

---

## S3：planning prompt 重做 + new 模式硬约束

### 目标
planning 注入 manifest 摘要，LLM 学会写 `data_ref="T001"`。new 模式下静态校验跨轮引用。

### 必读 spec 章节
- §5.4（WORKSPACE_BLOCK 模板 + manifest 摘要表渲染）
- §6.1 / §6.1.3 末尾（new 模式硬约束 `PlanValidationError`）
- §6.2（plan_history 在 prompt 中的角色）

### 新增文件
- `tests/unit/test_planning_blocks_cross_turn_ref_in_new_topic.py`：spec §9.2.7

### 修改文件
- `backend/agent/planning.py`：
  - 新增 `WORKSPACE_BLOCK` 常量（spec §5.4）
  - 新增 `_render_manifest_summary_table(manifest, current_turn_index)`：折叠策略见 §5.4
  - 替换原 `multi_turn_text` 构建块（[planning.py:1651-1673]）
  - 新增 `validate_plan_against_workspace(plan, turn_type, current_turn_index, workspace)`：turn_type=new 且引用 turn_index < 当前 turn 的 task_id 时抛 `PlanValidationError`
- `backend/exceptions.py`：加 `PlanValidationError`

### 验证清单
```bash
pytest tests/unit/test_planning_blocks_cross_turn_ref_in_new_topic.py -v
# 跑一个 R0 → R1 continue 端到端，验证 R1 plan 中含 data_ref="T001"
```

### 交接给 S4
**关键产出**：
- planning 已能基于 manifest 做规划
- new 模式硬约束已就位
- 但 `turn_type` 仍来自旧的 `_classify_turn`（关键词路由），由 S4 替换为 LLM 路由

---

## S4：perception LLM 路由 + 三个 bug 修复

### 目标
删除 `_classify_turn` 关键词路由，改为 perception LLM 输出 `turn_type`。同时修 §7 列出的 plan_history / turn_index / append_turn_summary 三个 bug。

### 必读 spec 章节
- §4（全节，perception LLM 路由）
- §7（全节，三个 bug + turn_status 状态机收尾）
- §8.1（L2 不动声明，避免误删）

### 新增/修改文件
- `backend/agent/perception.py`：
  - 新增 `MULTITURN_INTENT_PROMPT`、`_run_multiturn_perception`、`_merge_slots_with_delta`
  - `run_perception` 顶部按 §4.2 分流首轮 / 续接
  - **删除** [perception.py:894-895] continue 模式 `empty_required = []` 强制
  - **删除** [perception.py:854-866] conv_history 摘要塞入临时方案
- `backend/agent/graph.py`：
  - **删除** `_classify_turn` 函数（[graph.py:128-147]）
  - **删除** run_stream amend 分支（[graph.py:946-1035]）
  - run_stream 续接分支按 §4.3 简化
  - §7.2.1：plan_history 归档前置；同步删 [graph.py:428-441] auto-confirm 归档块
  - §7.2.2：turn_index 自增前置守卫
  - §7.2.3：`_should_append_turn_summary` 守卫
  - §7.3：`_finalize_turn` / `_abandon_orphaned_turn` 调用接入
- `tests/unit/test_multiturn_intent_matrix.py`：spec §9.2.5
- `tests/integration/test_multiturn_clarification_continuity.py`：spec §9.2.6

### 验证清单
```bash
pytest tests/unit/test_multiturn_intent_matrix.py -v        # ≥15/17
pytest tests/integration/test_multiturn_clarification_continuity.py -v
pytest tests/unit/test_session_workspace.py tests/unit/test_workspace_data_ref.py tests/unit/test_planning_blocks_cross_turn_ref_in_new_topic.py -v   # 不允许回归
```

### 交接给 S5
**关键产出**：
- perception → planning → execution 完整链路已用 V6 形式跑通
- 但旧 amend 数据通路（`_previous_artifacts` / `conversion_context.pkl`）尚未删除——它们当前是死代码，但 spec §12 验收 #1 要求关键词清零，由 S5 收尾

---

## S5：删除旧机制 + report 工具改造 + 隐式降级审计

### 目标
**最重的会话**。彻底拔除两套旧机制，改造 report 工具入口为统一 `data_refs` 协议，并对所有 silent fallback 做人工审计。

### 必读 spec 章节
- §5.6（删除项清单）
- §10.1 / §10.3（改动清单详表）
- §12 验收 #11（无隐式降级审计的 grep 模式）

### 删除清单（按文件）
| 文件 | 删除内容 |
|---|---|
| `backend/agent/planning.py` | `build_amend_plan` 函数 + `_previous_artifacts` / `_previous_findings` 注入逻辑 |
| `backend/agent/execution.py` | `_should_skip_data_fetch` / `_params_match` / `_build_multiturn_execution_context` / `_collect_report_context` |
| `backend/memory/artifact_store.py` | `_context_dir` / `write_conversion_context` / `read_conversion_context`（保留 artifact 文件本身） |
| `backend/main.py` | `read_conversion_context` 调用点 |
| `backend/tools/report/_outline_planner.py` | `_previous_artifacts` 处理段（103-130），改为标准 `data_refs` |
| `tests/unit/test_multiturn_classify.py` | 整删 |
| `tests/unit/test_multiturn_amend_plan.py` | 整删 |
| `tests/unit/test_multiturn_planning_pr2.py` | 整删 |
| `tests/unit/test_multiturn_execution.py` | 整删 |
| `tests/integration/test_multiturn_amend_execution.py` | 整删 |
| `tests/lib/multiturn_helpers.py` | `make_amend_state` |
| `tests/scenarios/test_multiturn_liangang.py` | `_classify_turn` 引用、R3 amend 断言改用 manifest |

### 新增/修改文件
- `tests/integration/test_amend_data_fidelity.py`（spec §9.2.3）
- `tests/integration/test_continue_data_reuse.py`（spec §9.2.4）
- `tests/lib/multiturn_helpers.py`：新增 `seed_workspace` / `make_task` / `consume_run_stream`
- `backend/tools/report/{html_gen,pptx_gen,docx_gen,markdown_gen}.py`：去除任何 `_previous_*` 参数依赖

### 隐式降级审计（验收 #11）
对以下 3 个目录人工 grep + 评估，提交一份审计清单：

```bash
# 高危模式 grep
rg -nP "except[^:]*:\s*\n\s*return\s+(\[\]|\{\}|None|pd\.DataFrame|0|False|\"\")" \
   backend/tools/report/ backend/agent/execution.py backend/memory/session_workspace.py
rg -n "head\(\d+\)" backend/tools/report/
rg -nP "if\s+\w+\s+is\s+None\s*:\s*\n\s*\w+\s*=\s*(pd\.DataFrame|\[\]|\{\})" backend/tools/report/
rg -n "status\s*!=\s*[\"']done[\"']" backend/  # spec 仅允许在显式渲染处使用
```

每命中一处：判定是 fail-fast 还是必要的占位（如纯文本拼接的空字符串），**fail-fast 优先**。命中清单 + 处理方案写到 PR 描述。

### 验证清单
```bash
# spec §12 验收 #1：关键词清零
rg "_classify_turn|build_amend_plan|amend_keywords|new_topic_keywords|_previous_artifacts|_previous_findings|_should_skip_data_fetch|_params_match|conversion_context|read_conversion_context|_collect_report_context|_build_multiturn_execution_context" backend/ tests/

# 关键测试
pytest tests/integration/test_amend_data_fidelity.py tests/integration/test_continue_data_reuse.py tests/scenarios/test_multiturn_liangang.py -v

# 全量回归
pytest tests/ -x
```

### 必要时拆 S5a / S5b
若 S5 单会话上下文吃紧（grep 出 silent fallback 数 > 10 处或 report 工具改造涉及超过 5 个文件），按以下边界拆：
- **S5a**：删除旧机制 + 删依赖测试 + `_outline_planner.py` 改造 + report 工具入口去 `_previous_*` 参数
- **S5b**：silent fallback 人工审计 + 整改 fail-fast + `test_amend_data_fidelity.py` / `test_continue_data_reuse.py` 跑通

### 交接给 S6
**关键产出**：
- 后端代码层面 V6 已可工作，所有阻断式测试通过
- 但前端无法看到 manifest（无 API），用户也无法点采纳按钮——由 S6 解决

---

## S6：workspace API + WebSocket

### 目标
对外暴露 manifest 查询 + 用户采纳/撤销操作 + WS 广播。前端 UI 不在本 spec 范围（独立 spec）。

### 必读 spec 章节
- §5.3.3（confirm / unconfirm 端点骨架）
- §10.2 末尾"前端范围声明"

### 新增文件
- `tests/integration/test_workspace_api.py`：confirm/unconfirm 端点 + WS 事件断言

### 修改文件
- `backend/main.py`：
  - `GET /api/sessions/{id}/workspace`：返回 manifest（脱敏 path 字段为相对路径）
  - `POST /api/sessions/{id}/workspace/{task_id}/confirm`
  - `POST /api/sessions/{id}/workspace/{task_id}/unconfirm`
  - `workspace_update` WS 事件广播

### 验证清单
```bash
pytest tests/integration/test_workspace_api.py -v
# 端到端手测：spec §12 验收 #9（4 轮 + 1 confirm 操作）
# 端到端手测：spec §12 验收 #10（追问 2 次后 turn_index/analysis_history/plan_history 检查）
```

### 交接给后续
- V6 spec 全部验收项过；本 spec 任务结束
- 前端 manifest inspector 由 `optimize_session_visibility_V1.md`（待编写）覆盖

---

## 跨会话通用约定

1. **每个会话只创建一个 commit**（除 S1 含 commit 1+2、S5 可拆 S5a+S5b）。commit message 体例：
   ```
   feat(workspace): commit 1 — SessionWorkspace 基础 (V6 §5.2)
   ```
2. **会话开始检查清单**：
   ```bash
   git log --oneline -5                    # 确认前置 commit
   git status                              # 工作树干净
   pytest <前置会话产出的测试> -x          # 不允许回归
   ```
3. **会话结束检查清单**：
   - 本会话所有"验证清单"命令全绿
   - 提交并推送到 `claude/analytica-conversation-optimization-FjNFg`
   - 在 PR #16 描述里追加一行"S<n> 完成于 <commit-sha>"
4. **遇到 spec 含糊处不要扩展解读**：补一条"待 spec 澄清"加到本手册末尾的"未决问题"区，由人决定后再继续。

---

## 未决问题（执行中追加）

（暂无）
