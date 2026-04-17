# Phase 4 测试报告：反思层与记忆系统

**日期**: 2026-04-17
**状态**: PASSED (70/70)

---

## 一、Phase 4 实施概览

### Sprint 10 — 反思节点 (Reflection Node)
- 文件: `backend/agent/reflection.py` (新增, 636 行)
- 两次并行 LLM 调用 (`asyncio.gather`):
  - **Call A**: 提取用户偏好 + 分析模板 + 槽位质量评审
  - **Call B**: 提取技能表现反馈
- Markdown 反思卡片格式化，支持 `[全部保存][选择保存][忽略本次]` 按钮
- 优雅降级: A 失败 B 仍保留，双失败不崩溃

### Sprint 11 — 记忆存储层 (Memory Store)
- 文件: `backend/memory/store.py` (增强, 365 行)
- 4 种记忆实体:
  - `user_preferences` — upsert 语义 (ON DUPLICATE KEY UPDATE)
  - `analysis_templates` — 三级回退查询 (精确 > 领域 > 用户级)
  - `slot_history` — 记录/标记纠正/计算纠正率 (lookback_sessions=20)
  - `skill_notes` — upsert 语义

### 感知层集成
- `SlotFillingEngine.initialize_slots()` 支持记忆偏好注入所有槽位
- `apply_correction_rate_check()` 纠正率 > 0.3 降级为 `memory_low_confidence`
- 优先级机制: `user_input(5) > history(4) > memory(3) > memory_low_confidence(2) > inferred(1) > default(0)`

### API 端点
- `POST /api/sessions/{session_id}/reflection/save` — Human-in-the-Loop 确认后持久化

---

## 二、测试结果

### Phase 4 测试 (35 个)

| 测试文件 | 测试数 | 通过 | 失败 |
|---|---|---|---|
| `tests/unit/test_memory_store.py` | 14 | 14 | 0 |
| `tests/unit/test_reflection_node.py` | 13 | 13 | 0 |
| `tests/integration/test_memory_injection.py` | 5 | 5 | 0 |
| `tests/integration/test_reflection_api.py` | 3 | 3 | 0 |
| **合计** | **35** | **35** | **0** |

### 全量回归 (Phase 1~4, 排除真实 LLM 测试)

| 测试集 | 测试数 | 通过 | 失败 |
|---|---|---|---|
| Phase 1~3 Mock E2E | 35 | 35 | 0 |
| Phase 4 全部 | 35 | 35 | 0 |
| **合计** | **70** | **70** | **0** |

> 注: `test_employee_e2e.py` 中的真实 LLM 测试因 `enable_thinking` API 参数兼容问题失败，与 Phase 4 记忆改动无关。

---

## 三、测试用例明细

### 3.1 Memory Store 单元测试 (TC-MS01~MS14)

| ID | 测试名 | 覆盖点 |
|---|---|---|
| MS01 | `test_upsert_preference_insert` | 偏好首次插入 |
| MS02 | `test_upsert_preference_update` | 偏好覆盖更新 |
| MS03 | `test_get_all_preferences_merges` | 多偏好合并为 dict |
| MS04 | `test_get_preference_nonexistent_returns_none` | 不存在的 key 返回 None |
| MS05 | `test_save_and_find_template` | 模板保存 + 查询 |
| MS06 | `test_find_templates_exact_match_first` | 三级回退 Level 1: 精确匹配 |
| MS07 | `test_find_templates_fallback_to_domain` | 三级回退 Level 2: 领域匹配 |
| MS08 | `test_find_templates_fallback_to_user_level` | 三级回退 Level 3: 用户级 |
| MS09 | `test_increment_usage` | usage_count 递增 |
| MS10 | `test_record_slot_written` | 槽位历史写入 |
| MS11 | `test_mark_corrected` | 纠正标记 was_corrected=1 |
| MS12 | `test_get_correction_rate_accurate` | 纠正率精度 (40% = 2/5) |
| MS13 | `test_upsert_skill_note_updates` | 技能笔记覆盖更新 |
| MS14 | `test_template_tags_json_contains_query` | JSON_CONTAINS 标签查询 |

### 3.2 Reflection Node 单元测试 (TC-RF01~RF07 + 6)

| ID | 测试名 | 覆盖点 |
|---|---|---|
| RF01 | `test_reflection_extracts_output_format` | 偏好提取 (output_format) |
| RF02 | `test_reflection_no_template_for_trivial_query` | 简单查询不生成模板 |
| RF03 | `test_reflection_generates_template_for_complex_analysis` | 复杂分析生成模板骨架 |
| RF04 | `test_reflection_identifies_corrected_slots` | 纠正槽位识别 |
| RF05 | `test_reflection_card_markdown_format` | 反思卡片 Markdown 格式 |
| RF06 | `test_reflection_strips_think_tags` | Qwen3 think 标签清理 |
| RF07 | `test_reflection_llm_calls_parallel` | 双 LLM 并行执行验证 |
| + | `test_call_llm_a_partial_failure_returns_none` | Call A JSON 解析失败返回 None |
| + | `test_call_llm_b_exception_returns_none` | Call B 异常返回 None |
| + | `test_reflection_node_both_fail_graceful` | 双失败优雅降级 |
| + | `test_reflection_node_a_fails_b_succeeds` | A 失败 B 成功部分降级 |
| + | `test_format_reflection_card_degraded` | 降级卡片格式正确 |
| + | `test_extract_json_from_markdown_fences` | markdown fence 内 JSON 提取 |

### 3.3 Memory Injection 集成测试 (TC-INJ)

| ID | 测试名 | 覆盖点 |
|---|---|---|
| INJ01 | `test_second_analysis_auto_fills_output_format` | 记忆偏好自动填充槽位 |
| INJ02 | `test_high_correction_rate_downgrades_in_second_analysis` | 80% 纠正率降级为 memory_low_confidence |
| INJ03 | `test_explicit_input_overrides_memory_preference` | 用户显式输入覆盖记忆 |
| INJ05 | `test_preference_saved_in_reflection_available_next_analysis` | 反思保存 -> 下次分析可用 |
| INJ06 | `test_slot_correction_rate_updates_after_mark` | mark_corrected 后纠正率变化 |

### 3.4 Reflection API 集成测试 (TC-RAPI)

| ID | 测试名 | 覆盖点 |
|---|---|---|
| RAPI01 | `test_save_preferences_only` | 仅保存偏好，模板不写入 |
| RAPI02 | `test_ignore_saves_nothing` | 忽略 -> DB 无写入 |
| RAPI03 | `test_save_all_marks_corrected_slots` | 全保存 + 槽位纠正标记 |

---

## 四、代码变更汇总

| 文件 | 变更类型 | 描述 |
|---|---|---|
| `backend/agent/reflection.py` | **新增** | 反思节点核心 (双 LLM 并行 + 卡片 + 保存逻辑) |
| `backend/memory/store.py` | **增强** | 完整 CRUD: upsert/三级回退/纠正率/技能笔记 |
| `backend/agent/perception.py` | **修改** | `initialize_slots()` 支持记忆注入所有槽位 |
| `backend/agent/graph.py` | **修改** | AgentState 添加 `reflection_summary`; reflection_node 接入 |
| `backend/main.py` | **修改** | 添加 `/api/sessions/{id}/reflection/save` 端点 |
| `tests/conftest.py` | **修改** | 添加 `test_db_session` fixture (NullPool + function loop_scope) |
| `tests/unit/test_memory_store.py` | **新增** | 14 个存储层单元测试 |
| `tests/unit/test_reflection_node.py` | **新增** | 13 个反思节点单元测试 |
| `tests/integration/test_memory_injection.py` | **新增** | 5 个记忆注入集成测试 |
| `tests/integration/test_reflection_api.py` | **新增** | 3 个 API 端点集成测试 |

---

## 五、已知问题

1. **`enable_thinking` API 兼容性** — `test_employee_e2e.py` 因 Qwen3 API 不支持 `enable_thinking` 参数失败，与 Phase 4 无关
2. **记忆读取侧规划层集成** — `find_templates()` / `get_skill_notes()` 已实现查询但规划层尚未调用，当前记忆系统以数据积累为主

---

## 六、累计测试统计

| Phase | 新增测试 | 累计通过 |
|---|---|---|
| Phase 0 (Mock Server) | 24 | 24 |
| Phase 1 (感知层) | 91 | 115 |
| Phase 2 (规划 + 状态机) | 54 | 169 |
| Phase 3 (执行 + 技能) | 54 | 192* |
| **Phase 4 (反思 + 记忆)** | **35** | **70 (mock 回归)** |

> *注: 累计数包含真实 LLM 测试; mock 回归的 70 个不含依赖真实 API 的测试。
