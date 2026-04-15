# Analytica · Phase 4：反思层与记忆系统

---

## 版本记录

| 版本号 | 日期 | 修订说明 | 编制人 |
|--------|------|----------|--------|
| v1.0 | 2026-04-14 | 从实施方案 v1.3 拆分，补充 PRD 章节与完整测试用例集 | FAN |

---

## 目录

1. [阶段目标与交付物](#1-阶段目标与交付物)
2. [PRD 关联章节](#2-prd-关联章节)
3. [实施方案：Sprint 10 — 反思节点](#3-实施方案sprint-10--反思节点)
4. [实施方案：Sprint 11 — 记忆存储层](#4-实施方案sprint-11--记忆存储层)
5. [测试用例集](#5-测试用例集)
6. [验收检查单](#6-验收检查单)

---

## 1. 阶段目标与交付物

**时间窗口：** Week 8–9（Day 34–40）

**前置条件：** Phase 3 全部验收通过（full_report 端到端可生成 PPTX）

**阶段目标：** 实现反思摘要生成、用户偏好提取和记忆持久化，使下次分析时能自动调用历史偏好，完成感知-规划-执行-反思完整闭环。

**可运行交付物：**

| 交付物 | 验证方式 |
|--------|----------|
| 反思节点：生成偏好提取+模板摘要的反思卡片 | 人工验证反思内容合理 |
| 记忆存储层：5 个表的 CRUD 全部可用 | `pytest tests/unit/test_memory_store.py` |
| 二次分析时偏好注入验证 | 场景：预设 pptx 偏好，第二次分析自动填充 |
| 完整闭环验证 | 一次完整分析 → 反思 → 保存 → 第二次分析使用偏好 |
| 单元测试 ≥ 20 个，全部通过 | `pytest tests/unit/ -v` |

---

## 2. PRD 关联章节

### 2.1 反思层完整设计（来自 PRD §4.4）

#### 2.1.1 模块职责

反思层在每次完整分析完成后自动触发，总结本次分析过程，提取用户偏好和可复用的分析范式，持久化到 MySQL，供下次分析时在感知层和规划层调用。

反思层的核心价值：**让 Analytica 随使用次数增加而越来越「懂」用户**，减少重复追问，提升规划准确性。

#### 2.1.2 反思摘要结构

```json
{
  "user_preferences": {
    "output_format": "pptx",
    "time_granularity": "monthly",
    "chart_types": ["line", "waterfall"],
    "analysis_depth": {"attribution": true, "predictive": false},
    "domain_terms": {"货量": "throughput_teu", "吞吐": "throughput_teu"}
  },
  "analysis_template": {
    "template_name": "月度港口吞吐量分析",
    "applicable_scenario": "查询特定月份港口各业务板块吞吐量变化及原因",
    "plan_skeleton": {
      "tasks": [
        {"type": "data_fetch", "skill": "skill_api_fetch", "endpoint_hint": "getThroughputByBusinessType"  // M02},
        {"type": "analysis", "skill": "skill_desc_analysis"},
        {"type": "visualization", "skill": "skill_chart_line"},
        {"type": "report_gen", "skill": "skill_report_html"}
      ]
    }
  },
  "slot_quality_review": {
    "slots_auto_filled_correctly": ["output_format", "time_granularity"],
    "slots_corrected": ["output_complexity"],
    "slots_corrected_detail": {"output_complexity": {"from": "simple_table", "to": "chart_text"}}
  },
  "skill_feedback": {
    "well_performed": ["skill_api_fetch", "skill_chart_line"],
    "issues_found": [{"skill": "skill_desc_analysis", "issue": "narrative 未提及关键异常月份"}],
    "suggestions": ["可在 narrative prompt 中明确要求指出异常值"]
  }
}
```

#### 2.1.3 反思 LLM Prompt 设计原则

反思 Prompt 是四层中最复杂的：输入上下文量大（完整会话历史 + Slot 历史 + 执行状态），需要 LLM 做多维度分析，同时保持结构化输出。关键原则：

- 分段提取，不在一个调用中完成所有分析（减少幻觉）
- 每段独立调用 LLM，各自有明确输出格式
- 用于保存的数据（偏好/模板）需用户二次确认，不自动写入

#### 2.1.4 反思层 UX 设计（来自 PRD §7.3）

```
📊 **本次分析总结**

**发现的偏好：**
- 输出格式：PPT（本次明确指定）
- 时间粒度：月度（与历史一致）
- 图表偏好：折线图 + 瀑布图

**可保存模板：**
「月度港口吞吐量分析」— 适用于月度吞吐量趋势与归因分析

**本次 AI 质量反馈：**
- ✅ 数据获取：准时准确（4 条记录）
- ⚠️ 描述性分析：叙述未突出最重要的同比数据

---
[全部保存] [选择保存] [忽略本次]
```

### 2.2 记忆存储设计（来自 PRD §3.2, 实施方案 §7.2）

#### 表结构与查询策略

**user_preferences 表** — 用户全局偏好

| 操作 | SQL 策略 |
|------|----------|
| 写入/更新 | `INSERT INTO ... ON DUPLICATE KEY UPDATE`（依赖 UNIQUE(user_id, key)）|
| 读取全部 | `SELECT * WHERE user_id=?`，合并为字典 |
| 读取单项 | `SELECT value WHERE user_id=? AND key=?` |

**analysis_templates 表** — 分析模板

三级 fallback 查询策略（优先级递减）：
1. `WHERE user_id=? AND domain=? AND output_complexity=?`（精确匹配）
2. `WHERE user_id=? AND domain=?`（仅 domain 匹配）
3. `WHERE user_id=?`（仅用户匹配，取 usage_count 最高）

**slot_history 表** — Slot 填充历史

纠错率统计：`JOIN sessions，统计最近 N 个会话中该槽的 was_corrected 比率`

### 2.3 记忆注入时机（来自实施方案 §7.2）

| 注入时机 | 注入内容 | 接收方 |
|----------|----------|--------|
| 感知层 `initialize_slots()` | output_format / time_granularity / domain_glossary | 感知层槽填充 |
| 感知层 `initialize_slots()` | 纠错率 > 0.3 的槽降级为 memory_low_confidence | 感知层追问逻辑 |
| 规划层 `planning_node()` | 历史模板骨架（三级 fallback） | 规划 LLM Prompt |
| 反思层保存确认后 | 槽纠错标记 → slot_history.was_corrected=1 | 下次纠错率统计 |

---

## 3. 实施方案：Sprint 10 — 反思节点

**时间：** Day 34–37

### 3.1 AI Coding Prompt：反思节点

```
【任务】实现 LangGraph 反思节点（backend/agent/reflection.py）。

【输入】完成执行后的 AgentState（含完整对话历史、Slot 填充历史、执行上下文）

【反思分析拆分为两次 LLM 调用（减少单次上下文负担）】

调用 A — 偏好与模板提取：
输入：对话历史摘要 + Slot 填充历史 + 执行任务列表
输出 JSON：
{
  "user_preferences": {...},
  "analysis_template": {...} | null,
  "slot_quality_review": {
    "slots_auto_filled_correctly": [...],
    "slots_corrected": [...],
    "slots_corrected_detail": {...}
  }
}

调用 B — 技能表现反馈：
输入：task_statuses + 各任务执行时间 + execution_context 摘要
输出 JSON：
{
  "skill_feedback": {
    "well_performed": [...],
    "issues_found": [...],
    "suggestions": [...]
  }
}

【节点逻辑】
1. 并行执行调用 A 和调用 B（asyncio.gather）
2. 合并结果为 reflection_summary
3. 格式化为 Markdown 反思卡片，写入 messages
4. Human-in-the-Loop 暂停，等待用户确认（通过 POST /api/sessions/{id}/reflection/save）
5. 用户选择「全部保存」：
   a. upsert output_format / time_granularity 等到 user_preferences 表
   b. 若有 analysis_template，调用 store.save_template()
   c. 对 slots_corrected 列表调用 store.mark_corrected()
6. 用户选择「忽略」：不写入任何数据

【陷阱】
- LLM 可能识别出与本次分析无关的「偏好」（如用户随口提到的格式）→ 在 Prompt 中强调只提取本次分析中明确体现的偏好
- analysis_template 不应对每次分析都生成（仅当分析流程有通用价值时）→ Prompt 中增加判断条件
- <think> 标签剥离
- domain_terms 可能为空字典，需正常处理

【还需要】
- POST /api/sessions/{id}/reflection/save 端点
  Body: {"save_preferences": true/false, "save_template": true/false, "save_skill_notes": true/false}
- 格式化反思卡片的 format_reflection_card(reflection: dict) -> str 方法

【输出】backend/agent/reflection.py + backend/main.py 新增路由
```

---

## 4. 实施方案：Sprint 11 — 记忆存储层

**时间：** Day 38–40

### 4.1 AI Coding Prompt：记忆存储层

```
【任务】实现记忆存储层（backend/memory/store.py）。
所有检索均使用 SQL 精确查询，不引入任何向量存储或 embedding 依赖。

【接口设计】— MySQL 8.0 + SQLAlchemy 2.0 async

1. user_preferences 表：
   async upsert_preference(user_id, key, value: dict) → None
     INSERT INTO user_preferences (id, user_id, `key`, value, updated_at) VALUES (...)
     ON DUPLICATE KEY UPDATE value=VALUES(value), updated_at=NOW()
   async get_all_preferences(user_id) → dict
     SELECT 全量键值，合并为单一偏好字典
   async get_preference(user_id, key) → Optional[Any]

2. analysis_templates 表：
   async save_template(user_id, name, domain, output_complexity, tags: list[str], plan_skeleton: dict) → str
   async find_templates(user_id, domain, output_complexity, limit=3) → List[dict]
     按三级 fallback 查询（精确→domain→用户全量），取首个非空结果集
   async increment_usage(template_id) → None
     UPDATE usage_count=usage_count+1, last_used=NOW()

3. skill_notes 表：
   async upsert_skill_note(user_id, skill_id, notes, performance_score) → None
     INSERT INTO ... ON DUPLICATE KEY UPDATE notes=VALUES(notes), performance_score=VALUES(performance_score), updated_at=NOW()
   async get_skill_notes(user_id) → dict[str, dict]

4. slot_history 表：
   async record_slot(session_id, slot_name, value, source, round_num) → None
   async mark_corrected(session_id, slot_name) → None
     UPDATE was_corrected=1 WHERE session_id=? AND slot_name=?
   async get_correction_rate(user_id, slot_name, lookback_sessions=20) → float
     SELECT slot_history.was_corrected FROM slot_history JOIN sessions
     ON slot_history.session_id = sessions.session_id
     WHERE sessions.user_id=? AND slot_history.slot_name=?
     ORDER BY sessions.created_at DESC LIMIT 20

【MySQL JSON 列查询注意事项】
- tags 为 JSON 数组列
- 查找包含特定 tag 的模板：JSON_CONTAINS(tags, JSON_QUOTE('throughput'))
- 不使用 PostgreSQL 的 @> 或 ? 操作符

【约束】
- 全异步（async with session）
- 使用 pool_recycle=3600 防止 MySQL 空闲断连
- 事务级别读取防脏读

【输出】backend/memory/store.py + tests/unit/test_memory_store.py（≥ 12 个测试）
```

### 4.2 AI Coding Prompt：偏好注入感知层（Sprint 11 集成）

```
【任务】修改感知层 SlotFillingEngine，集成记忆存储调用。

修改点（perception.py）：
1. initialize_slots(user_id) 改为 async，注入 memory_store 依赖
2. 调用 await store.get_all_preferences(user_id)
3. 按映射填入槽：
   output_format → slots["output_format"]（source="memory", confirmed=False）
   time_granularity → slots["time_granularity"]（source="memory"）
   domain_glossary → slots["domain_glossary"]（source="memory"）
4. 对各记忆槽调用 store.get_correction_rate(user_id, slot_name)：
   correction_rate > 0.3 → source 改为 "memory_low_confidence"
   并在 SLOT_EXTRACTION_PROMPT 对该槽追加注释：
   「注意：{slot_name} 有历史修正记录（纠错率 {rate:.0%}），
   请优先从当前对话中提取，不要直接沿用记忆值」

显式优先原则：source="user_input" 的槽值不允许被 source="memory*" 覆盖。
确保修改不破坏 Phase 1 的全部测试用例（回归检查）。

【输出】修改 backend/agent/perception.py
```

---

## 5. 测试用例集

> **设计原则：** 记忆系统的 AI 不确定性体现在：（1）LLM 偏好提取的准确性和必要性判断；（2）偏好在下次分析中的正确应用；（3）纠错率统计的准确性。测试重点覆盖偏好的读-写-回注完整闭环，以及 MySQL 特定语法（JSON 列、upsert）的边界情况。

### 5.1 记忆存储基础 CRUD 测试（tests/unit/test_memory_store.py）

#### TC-MS01：upsert_preference 首次写入成功
```python
@pytest.mark.asyncio
async def test_upsert_preference_insert(test_db_session):
    """验证首次写入偏好成功"""
    store = MemoryStore(session=test_db_session)
    await store.upsert_preference(user_id="user-001", key="output_format", value={"v": "pptx"})
    result = await store.get_preference("user-001", "output_format")
    assert result == {"v": "pptx"}
```

#### TC-MS02：upsert_preference 更新已有偏好
```python
@pytest.mark.asyncio
async def test_upsert_preference_update(test_db_session):
    """验证 upsert 更新已有偏好，不新增重复行"""
    store = MemoryStore(session=test_db_session)
    await store.upsert_preference("user-001", "output_format", {"v": "pptx"})
    await store.upsert_preference("user-001", "output_format", {"v": "docx"})
    result = await store.get_preference("user-001", "output_format")
    assert result == {"v": "docx"}
    # 验证只有一行
    count = await test_db_session.execute(
        text("SELECT COUNT(*) FROM user_preferences WHERE user_id='user-001' AND `key`='output_format'")
    )
    assert count.scalar() == 1
```

#### TC-MS03：get_all_preferences 返回合并字典
```python
@pytest.mark.asyncio
async def test_get_all_preferences_merges(test_db_session):
    """验证 get_all_preferences 将多个键值合并为单一字典"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    await store.upsert_preference(user_id, "output_format", "pptx")
    await store.upsert_preference(user_id, "time_granularity", "monthly")
    await store.upsert_preference(user_id, "domain_glossary", {"货量": "throughput_teu"})
    prefs = await store.get_all_preferences(user_id)
    assert prefs["output_format"] == "pptx"
    assert prefs["time_granularity"] == "monthly"
    assert prefs["domain_glossary"]["货量"] == "throughput_teu"
```

#### TC-MS04：get_preference 不存在的 key 返回 None
```python
@pytest.mark.asyncio
async def test_get_preference_nonexistent_returns_none(test_db_session):
    store = MemoryStore(session=test_db_session)
    result = await store.get_preference(str(uuid4()), "nonexistent_key")
    assert result is None
```

#### TC-MS05：save_template 写入并可查询
```python
@pytest.mark.asyncio
async def test_save_and_find_template(test_db_session):
    """验证 save_template 后 find_templates 可查到"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    template_id = await store.save_template(
        user_id=user_id, name="月度吞吐量分析",
        domain="port_ops", output_complexity="simple_table",
        tags=["throughput", "monthly"],
        plan_skeleton={"tasks": [{"type": "data_fetch"}]}
    )
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    assert len(templates) >= 1
    assert templates[0]["name"] == "月度吞吐量分析"
    assert templates[0]["template_id"] == template_id
```

#### TC-MS06：find_templates 精确匹配优先（三级 fallback 第一级）
```python
@pytest.mark.asyncio
async def test_find_templates_exact_match_first(test_db_session):
    """验证精确匹配（domain+complexity）的模板比模糊匹配优先返回"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    # 写入精确匹配和模糊匹配两个模板
    exact_id = await store.save_template(user_id, "精确匹配模板", "port_ops", "simple_table", [], {})
    fuzzy_id = await store.save_template(user_id, "模糊匹配模板", "port_ops", "chart_text", [], {})
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    # 第一个结果应是精确匹配的
    assert templates[0]["template_id"] == exact_id
```

#### TC-MS07：find_templates fallback 到 domain 级匹配
```python
@pytest.mark.asyncio
async def test_find_templates_fallback_to_domain(test_db_session):
    """验证无精确匹配时，fallback 到同 domain 的其他 complexity 模板"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    # 只有 chart_text 的模板
    domain_id = await store.save_template(user_id, "域级模板", "port_ops", "chart_text", [], {})
    # 查询 simple_table（无精确匹配）
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    assert len(templates) >= 1
    assert templates[0]["template_id"] == domain_id
```

#### TC-MS08：find_templates fallback 到用户全量（第三级）
```python
@pytest.mark.asyncio
async def test_find_templates_fallback_to_user_level(test_db_session):
    """验证无 domain 匹配时，fallback 到用户全量模板（取 usage_count 最高）"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    # 只有不同 domain 的模板
    id_high = await store.save_template(user_id, "高使用量模板", "finance", "full_report", [], {})
    await test_db_session.execute(
        text("UPDATE analysis_templates SET usage_count=10 WHERE template_id=:tid"),
        {"tid": id_high}
    )
    id_low = await store.save_template(user_id, "低使用量模板", "hr", "simple_table", [], {})
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    assert templates[0]["template_id"] == id_high  # 使用量最高
```

#### TC-MS09：increment_usage 更新计数
```python
@pytest.mark.asyncio
async def test_increment_usage(test_db_session):
    """验证 increment_usage 使 usage_count 加 1"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    tid = await store.save_template(user_id, "测试模板", "port_ops", "simple_table", [], {})
    await store.increment_usage(tid)
    await store.increment_usage(tid)
    result = await test_db_session.execute(
        text("SELECT usage_count FROM analysis_templates WHERE template_id=:tid"), {"tid": tid}
    )
    assert result.scalar() == 2
```

#### TC-MS10：record_slot 写入历史
```python
@pytest.mark.asyncio
async def test_record_slot_written(test_db_session):
    """验证 record_slot 将槽填充记录写入 slot_history 表"""
    store = MemoryStore(session=test_db_session)
    session_id = str(uuid4())
    await store.record_slot(session_id, "time_range", {"start": "2026-01-01", "end": "2026-01-31"}, "user_input", round_num=1)
    result = await test_db_session.execute(
        text("SELECT slot_name, source, was_corrected FROM slot_history WHERE session_id=:sid"),
        {"sid": session_id}
    )
    row = result.fetchone()
    assert row[0] == "time_range"
    assert row[1] == "user_input"
    assert row[2] == 0  # 默认未纠错
```

#### TC-MS11：mark_corrected 更新 was_corrected=1
```python
@pytest.mark.asyncio
async def test_mark_corrected(test_db_session):
    """验证 mark_corrected 将对应槽的 was_corrected 设为 1"""
    store = MemoryStore(session=test_db_session)
    session_id = str(uuid4())
    await store.record_slot(session_id, "output_complexity", "simple_table", "inferred", 1)
    await store.mark_corrected(session_id, "output_complexity")
    result = await test_db_session.execute(
        text("SELECT was_corrected FROM slot_history WHERE session_id=:sid AND slot_name='output_complexity'"),
        {"sid": session_id}
    )
    assert result.scalar() == 1
```

#### TC-MS12：get_correction_rate 统计准确
```python
@pytest.mark.asyncio
async def test_get_correction_rate_accurate(test_db_session):
    """验证纠错率统计：5 次中 2 次纠错 = 40%"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    # 创建 5 个会话，其中 2 个对 output_complexity 进行了纠错
    for i in range(5):
        session_id = str(uuid4())
        await test_db_session.execute(
            text("INSERT INTO sessions (session_id, user_id, state_json, created_at, updated_at) VALUES (:sid, :uid, '{}', NOW(), NOW())"),
            {"sid": session_id, "uid": user_id}
        )
        await store.record_slot(session_id, "output_complexity", "inferred_val", "inferred", 1)
        if i < 2:  # 前 2 个会话被纠错
            await store.mark_corrected(session_id, "output_complexity")
    rate = await store.get_correction_rate(user_id, "output_complexity", lookback_sessions=10)
    assert abs(rate - 0.4) < 0.05  # 允许浮点误差
```

#### TC-MS13：upsert_skill_note 更新已有记录
```python
@pytest.mark.asyncio
async def test_upsert_skill_note_updates(test_db_session):
    """验证 upsert_skill_note 对同一 user+skill 更新而非重复插入"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    await store.upsert_skill_note(user_id, "skill_desc_analysis", "首次备注", 0.7)
    await store.upsert_skill_note(user_id, "skill_desc_analysis", "更新备注", 0.9)
    notes = await store.get_skill_notes(user_id)
    assert notes["skill_desc_analysis"]["notes"] == "更新备注"
    assert notes["skill_desc_analysis"]["performance_score"] == 0.9
    # 只有一条记录
    count = await test_db_session.execute(
        text("SELECT COUNT(*) FROM skill_notes WHERE user_id=:uid AND skill_id='skill_desc_analysis'"),
        {"uid": user_id}
    )
    assert count.scalar() == 1
```

#### TC-MS14：tags JSON 列的 JSON_CONTAINS 查询
```python
@pytest.mark.asyncio
async def test_template_tags_json_contains_query(test_db_session):
    """验证 MySQL JSON_CONTAINS 正确查询 tags 数组中包含特定值的模板"""
    store = MemoryStore(session=test_db_session)
    user_id = str(uuid4())
    await store.save_template(user_id, "含 throughput 标签", "port_ops", "simple_table",
                              tags=["throughput", "monthly"], plan_skeleton={})
    await store.save_template(user_id, "不含该标签", "port_ops", "simple_table",
                              tags=["revenue", "quarterly"], plan_skeleton={})
    # 按 tag 查询
    result = await test_db_session.execute(
        text("SELECT name FROM analysis_templates WHERE user_id=:uid AND JSON_CONTAINS(tags, JSON_QUOTE('throughput'))"),
        {"uid": user_id}
    )
    names = [row[0] for row in result.fetchall()]
    assert "含 throughput 标签" in names
    assert "不含该标签" not in names
```

---

### 5.2 反思节点 LLM 提取测试（tests/unit/test_reflection_node.py）

#### TC-RF01：偏好提取包含 output_format
```python
@pytest.mark.asyncio
async def test_reflection_extracts_output_format(mock_reflection_llm_a):
    """验证反思 LLM 调用 A 正确提取 output_format 偏好"""
    mock_reflection_llm_a.return_value = json.dumps({
        "user_preferences": {
            "output_format": "pptx",
            "time_granularity": "monthly",
            "chart_types": ["line"],
            "analysis_depth": {"attribution": True, "predictive": False},
            "domain_terms": {}
        },
        "analysis_template": None,
        "slot_quality_review": {
            "slots_auto_filled_correctly": ["time_granularity"],
            "slots_corrected": [],
            "slots_corrected_detail": {}
        }
    })
    state = make_completed_session_state(output_format_used="pptx")
    result = await reflection_node(state)
    prefs = result["reflection_summary"]["user_preferences"]
    assert prefs["output_format"] == "pptx"
```

#### TC-RF02：反思不为无意义分析生成模板
```python
@pytest.mark.asyncio
async def test_reflection_no_template_for_trivial_query(mock_reflection_llm_a):
    """验证简单查询（simple_table，1个任务）不生成可复用模板"""
    mock_reflection_llm_a.return_value = json.dumps({
        "user_preferences": {"output_format": "simple_table"},
        "analysis_template": None,  # LLM 判断无复用价值
        "slot_quality_review": {"slots_auto_filled_correctly": [], "slots_corrected": [], "slots_corrected_detail": {}}
    })
    state = make_simple_query_state()
    result = await reflection_node(state)
    assert result["reflection_summary"]["analysis_template"] is None
```

#### TC-RF03：有价值的分析生成模板骨架
```python
@pytest.mark.asyncio
async def test_reflection_generates_template_for_complex_analysis(mock_reflection_llm_a):
    """验证复杂 full_report 分析生成可复用模板骨架"""
    mock_reflection_llm_a.return_value = json.dumps({
        "user_preferences": {"output_format": "pptx"},
        "analysis_template": {
            "template_name": "月度港口运营分析",
            "applicable_scenario": "月度各业务板块吞吐量趋势与归因分析",
            "plan_skeleton": {"tasks": [{"type": "data_fetch"}, {"type": "analysis"}, {"type": "report_gen"}]}
        },
        "slot_quality_review": {"slots_auto_filled_correctly": ["time_granularity", "output_format"], "slots_corrected": []}
    })
    state = make_full_report_state()
    result = await reflection_node(state)
    template = result["reflection_summary"]["analysis_template"]
    assert template is not None
    assert "template_name" in template
    assert len(template["plan_skeleton"]["tasks"]) >= 3
```

#### TC-RF04：slots_corrected 被正确识别
```python
@pytest.mark.asyncio
async def test_reflection_identifies_corrected_slots(mock_reflection_llm_a):
    """验证 LLM 正确识别本次被纠错的槽（用户修改了推断值）"""
    mock_reflection_llm_a.return_value = json.dumps({
        "user_preferences": {},
        "analysis_template": None,
        "slot_quality_review": {
            "slots_auto_filled_correctly": ["time_granularity"],
            "slots_corrected": ["output_complexity"],
            "slots_corrected_detail": {
                "output_complexity": {"from": "simple_table", "to": "chart_text"}
            }
        }
    })
    # 状态中 output_complexity 槽被用户从 simple_table 改为 chart_text
    state = make_state_with_slot_correction("output_complexity", "simple_table", "chart_text")
    result = await reflection_node(state)
    assert "output_complexity" in result["reflection_summary"]["slot_quality_review"]["slots_corrected"]
```

#### TC-RF05：反思卡片 Markdown 格式符合 PRD
```python
@pytest.mark.asyncio
async def test_reflection_card_markdown_format(mock_reflection_llm_a, mock_reflection_llm_b):
    """验证反思卡片包含偏好/模板/技能反馈三个区块"""
    setup_reflection_mocks(mock_reflection_llm_a, mock_reflection_llm_b)
    state = make_full_report_state()
    result = await reflection_node(state)
    # 反思卡片写入了 messages
    reflection_messages = [m for m in result["messages"] if m.get("type") == "reflection_card"]
    assert len(reflection_messages) >= 1
    card = reflection_messages[0]["content"]
    assert "偏好" in card or "输出格式" in card
    assert "全部保存" in card or "保存" in card
```

#### TC-RF06：<think> 标签剥离后正确解析
```python
@pytest.mark.asyncio
async def test_reflection_strips_think_tags(mock_reflection_llm_a):
    """验证反思 LLM 输出的 <think> 块被剥离后能正常解析"""
    raw = "<think>分析用户偏好...</think>\n" + json.dumps({
        "user_preferences": {"output_format": "pptx"},
        "analysis_template": None,
        "slot_quality_review": {"slots_auto_filled_correctly": [], "slots_corrected": []}
    })
    mock_reflection_llm_a.return_value = raw
    state = make_simple_query_state()
    result = await reflection_node(state)
    assert result["reflection_summary"]["user_preferences"]["output_format"] == "pptx"
```

#### TC-RF07：反思 LLM 两次调用并行执行（性能）
```python
@pytest.mark.asyncio
async def test_reflection_llm_calls_parallel(mock_reflection_llm_a, mock_reflection_llm_b):
    """验证两次 LLM 调用通过 asyncio.gather 并行，总耗时 < 两者串行之和"""
    call_times = []
    async def slow_llm_a(*args, **kwargs):
        start = time.time()
        await asyncio.sleep(1)
        call_times.append(("A", time.time() - start))
        return json.dumps({"user_preferences": {}, "analysis_template": None, "slot_quality_review": {}})
    async def slow_llm_b(*args, **kwargs):
        start = time.time()
        await asyncio.sleep(1)
        call_times.append(("B", time.time() - start))
        return json.dumps({"skill_feedback": {"well_performed": [], "issues_found": [], "suggestions": []}})
    mock_reflection_llm_a.side_effect = slow_llm_a
    mock_reflection_llm_b.side_effect = slow_llm_b
    state = make_full_report_state()
    start = time.time()
    await reflection_node(state)
    total = time.time() - start
    assert total < 2.5  # 并行应 < 1+1=2 秒（允许 0.5 秒 overhead）
```

---

### 5.3 偏好注入闭环测试（tests/integration/test_memory_injection.py）

#### TC-INJ01：第二次分析自动填充 output_format
```python
@pytest.mark.asyncio
async def test_second_analysis_auto_fills_output_format(test_db_session):
    """闭环验证：第一次分析后偏好被保存，第二次分析感知层自动填充 output_format"""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)
    # 模拟第一次分析后保存偏好
    await store.upsert_preference(user_id, "output_format", "pptx")
    # 第二次分析：初始化感知层
    engine = SlotFillingEngine(llm=mock_llm, memory_store=store)
    slots = await engine.initialize_slots_async(user_id=user_id)
    assert slots["output_format"].value == "pptx"
    assert slots["output_format"].source == "memory"
    assert slots["output_format"].confirmed == False
```

#### TC-INJ02：高纠错率偏好第二次分析被降级
```python
@pytest.mark.asyncio
async def test_high_correction_rate_downgrades_in_second_analysis(test_db_session):
    """验证高纠错率的偏好在第二次分析时被降级为 memory_low_confidence"""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)
    # 保存偏好
    await store.upsert_preference(user_id, "output_format", "pptx")
    # 模拟 5 次分析，4 次纠错（纠错率 80%）
    for i in range(5):
        sid = str(uuid4())
        await test_db_session.execute(
            text("INSERT INTO sessions (session_id, user_id, state_json, created_at, updated_at) VALUES (:sid, :uid, '{}', NOW(), NOW())"),
            {"sid": sid, "uid": user_id}
        )
        await store.record_slot(sid, "output_format", "pptx", "memory", 1)
        if i < 4:
            await store.mark_corrected(sid, "output_format")
    # 第二次分析初始化
    engine = SlotFillingEngine(llm=mock_llm, memory_store=store)
    slots = await engine.initialize_slots_async(user_id=user_id)
    await engine.apply_correction_rate_check(slots, user_id)
    assert slots["output_format"].source == "memory_low_confidence"
```

#### TC-INJ03：用户显式输入覆盖记忆偏好
```python
@pytest.mark.asyncio
async def test_explicit_input_overrides_memory_preference(test_db_session, mock_llm_explicit_docx):
    """验证用户明确说 DOCX 后，output_format 从 memory.pptx 变为 user_input.docx"""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)
    await store.upsert_preference(user_id, "output_format", "pptx")
    # 初始化有 pptx 记忆
    engine = SlotFillingEngine(llm=mock_llm_explicit_docx, memory_store=store)
    slots = await engine.initialize_slots_async(user_id=user_id)
    assert slots["output_format"].value == "pptx"
    # 用户明确说 DOCX
    updated = await engine.extract_slots_from_text("我要 DOCX 格式", slots, [])
    assert updated["output_format"].value == "docx"
    assert updated["output_format"].source == "user_input"
```

#### TC-INJ04：模板注入规划 Prompt（三级 fallback）
```python
@pytest.mark.asyncio
async def test_template_injected_into_planning_prompt(test_db_session, mock_planning_llm, captured_prompt):
    """验证有历史模板时，规划层将模板骨架注入 LLM Prompt"""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)
    await store.save_template(user_id, "月度分析模板", "port_ops", "simple_table",
                              tags=["monthly"], plan_skeleton={"tasks": [{"type": "data_fetch"}]})
    intent = make_structured_intent("simple_table", user_id=user_id, domain="port_ops")
    await generate_plan(intent, memory_store=store, ...)
    prompt = captured_prompt.get_last_prompt()
    assert "月度分析模板" in prompt or "参考模板" in prompt
```

#### TC-INJ05：反思保存后，下次分析立即生效
```python
@pytest.mark.asyncio
async def test_preference_saved_in_reflection_available_next_analysis(test_db_session):
    """完整闭环：反思保存偏好 → 下次感知层初始化时读到"""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)
    # 模拟反思层保存 output_format=pptx
    await store.upsert_preference(user_id, "output_format", "pptx")
    await store.upsert_preference(user_id, "time_granularity", "monthly")
    # 下次分析感知层初始化
    engine = SlotFillingEngine(llm=mock_llm, memory_store=store)
    slots = await engine.initialize_slots_async(user_id=user_id)
    assert slots["output_format"].value == "pptx"
    assert slots["time_granularity"].value == "monthly"
    assert slots["output_format"].source == "memory"
    assert slots["time_granularity"].source == "memory"
```

#### TC-INJ06：槽纠错标记后纠错率正确更新
```python
@pytest.mark.asyncio
async def test_slot_correction_rate_updates_after_mark(test_db_session):
    """验证反思层调用 mark_corrected 后，get_correction_rate 返回更高的值"""
    user_id = str(uuid4())
    store = MemoryStore(session=test_db_session)
    # 先有 5 次无纠错历史
    for i in range(5):
        sid = str(uuid4())
        await test_db_session.execute(
            text("INSERT INTO sessions VALUES (:sid, :uid, '{}', NOW(), NOW())"),
            {"sid": sid, "uid": user_id}
        )
        await store.record_slot(sid, "output_complexity", "simple_table", "inferred", 1)
    rate_before = await store.get_correction_rate(user_id, "output_complexity")
    assert rate_before == 0.0
    # 本次会话纠错
    sid_new = str(uuid4())
    await test_db_session.execute(
        text("INSERT INTO sessions VALUES (:sid, :uid, '{}', NOW(), NOW())"),
        {"sid": sid_new, "uid": user_id}
    )
    await store.record_slot(sid_new, "output_complexity", "simple_table", "inferred", 1)
    await store.mark_corrected(sid_new, "output_complexity")
    rate_after = await store.get_correction_rate(user_id, "output_complexity")
    assert rate_after > 0.0
```

---

### 5.4 反思 API 端点测试（tests/integration/test_reflection_api.py）

#### TC-RAPI01：POST reflection/save 选择保存偏好
```python
@pytest.mark.asyncio
async def test_save_preferences_only(client, test_db_session, completed_session):
    """验证 save_preferences=True 时，偏好写入 MySQL，模板不写入"""
    sid = completed_session["session_id"]
    user_id = completed_session["user_id"]
    resp = client.post(f"/api/sessions/{sid}/reflection/save", json={
        "save_preferences": True,
        "save_template": False,
        "save_skill_notes": False
    })
    assert resp.status_code == 200
    # 验证 user_preferences 写入
    store = MemoryStore(session=test_db_session)
    prefs = await store.get_all_preferences(user_id)
    assert len(prefs) >= 1
    # 验证 analysis_templates 未写入
    templates = await store.find_templates(user_id, "port_ops", "simple_table")
    assert len(templates) == 0
```

#### TC-RAPI02：POST reflection/save 忽略（不保存任何内容）
```python
def test_ignore_saves_nothing(client, test_db_session, completed_session):
    """验证 save_preferences=False/save_template=False 时，MySQL 中无新数据"""
    sid = completed_session["session_id"]
    resp = client.post(f"/api/sessions/{sid}/reflection/save", json={
        "save_preferences": False,
        "save_template": False,
        "save_skill_notes": False
    })
    assert resp.status_code == 200
    # 数据库中偏好数应为 0（新用户）
    count = test_db_session.execute(
        text("SELECT COUNT(*) FROM user_preferences WHERE user_id=:uid"),
        {"uid": completed_session["user_id"]}
    ).scalar()
    assert count == 0
```

---

## 6. 验收检查单

### 功能验收

| 检查项 | 期望结果 | 状态 |
|--------|----------|------|
| 反思节点生成合理的偏好提取 | 包含 output_format、time_granularity 等 | ⬜ |
| 反思节点识别被纠错的槽 | TC-RF04 通过 | ⬜ |
| 反思卡片符合 PRD §7.3 格式 | 含偏好/模板/技能三区块 | ⬜ |
| 记忆存储 5 个接口全部可用 | TC-MS01 ~ TC-MS14 通过 | ⬜ |
| 偏好写入后第二次分析自动填充 | TC-INJ01/INJ02 通过 | ⬜ |
| 纠错率统计准确（TC-MS12: 40%） | 允许 5% 误差 | ⬜ |
| 三级 fallback 查询逻辑正确 | TC-MS06/07/08 通过 | ⬜ |
| MySQL JSON_CONTAINS 语法正确 | TC-MS14 通过 | ⬜ |
| Phase 1 感知层测试无回归 | 全部 Phase 1 测试通过 | ⬜ |

### 测试覆盖验收

| 测试类型 | 要求 | 状态 |
|----------|------|------|
| 单元测试 | ≥ 20 个，全部通过 | ⬜ |
| 记忆存储覆盖率 | > 90% | ⬜ |
| 闭环集成测试 | 偏好写入→读取→注入全路径 | ⬜ |

### 性能验收

| 指标 | 要求 | 状态 |
|------|------|------|
| 反思节点两次 LLM 并行调用 | 总耗时 < max(A,B) + 0.5s | ⬜ |
| 偏好写入 MySQL 单条 | < 50ms | ⬜ |
| find_templates 三级 fallback | < 200ms | ⬜ |
| 纠错率统计查询（20 个会话）| < 100ms | ⬜ |

---

## 补充测试：反思层 LLM 健壮性测试

> **补充说明：** 反思层有两个特殊的健壮性风险：（1）两次并行 LLM 调用的部分失败处理；（2）LLM 错误地为无意义分析生成偏好或在无数据时生成幻觉偏好。以下测试专项覆盖这两类风险，并补充反思节点的重试机制验证。

---

### TC-RF-PARALLEL：反思层两次并行 LLM 调用健壮性

> 文件：`tests/unit/test_reflection_parallel_robustness.py`

#### TC-RF-PARALLEL01：两次并行调用均成功时结果正确合并
```python
async def test_reflection_parallel_both_succeed():
    """
    反思节点并行调用 LLM-A（偏好提取）和 LLM-B（模板提取）。
    两次均成功时，结果应正确合并到 ReflectionOutput。
    验证：preferences 来自 LLM-A，template_skeleton 来自 LLM-B。
    """
    mock_a_output = {
        "preferences": [
            {"slot_name": "output_format", "value": "chart_text", "confidence": 0.9}
        ],
        "slots_corrected": []
    }
    mock_b_output = {
        "should_save_template": True,
        "template_skeleton": {
            "intent_pattern": "月度集装箱趋势分析",
            "task_structure": ["fetch", "analysis", "chart", "narrative"]
        }
    }

    with patch("app.agent.reflection.call_llm_a", return_value=json.dumps(mock_a_output)), \
         patch("app.agent.reflection.call_llm_b", return_value=json.dumps(mock_b_output)):
        node = ReflectionNode()
        result = await node.run(state=make_post_execution_state())

    assert len(result.reflection.preferences) == 1
    assert result.reflection.preferences[0]["slot_name"] == "output_format"
    assert result.reflection.template_skeleton is not None
    assert result.reflection.template_skeleton["intent_pattern"] == "月度集装箱趋势分析"
```

#### TC-RF-PARALLEL02：LLM-A 失败、LLM-B 成功时降级处理
```python
async def test_reflection_llm_a_fails_llm_b_succeeds():
    """
    偏好提取（LLM-A）调用失败，模板提取（LLM-B）成功。
    降级策略：
    - preferences 为空列表（不抛异常）
    - template_skeleton 正常保存（LLM-B 结果不受影响）
    - 反思卡片降级展示（仅显示"本次分析已完成，偏好提取暂时不可用"）
    """
    with patch("app.agent.reflection.call_llm_a",
               side_effect=asyncio.TimeoutError("LLM-A timeout")), \
         patch("app.agent.reflection.call_llm_b",
               return_value=json.dumps({
                   "should_save_template": True,
                   "template_skeleton": {"intent_pattern": "吞吐量分析"}
               })):
        node = ReflectionNode()
        result = await node.run(state=make_post_execution_state())

    # 不应抛异常
    assert result.reflection is not None

    # 偏好应降级为空（不幻觉填充）
    assert result.reflection.preferences == [], \
        "LLM-A 失败时不应幻觉填充偏好"

    # 模板仍应被保存
    assert result.reflection.template_skeleton is not None

    # 反思卡片应有降级提示
    card = format_reflection_card(result.reflection)
    assert any(w in card for w in ["暂时不可用", "偏好提取失败", "稍后重试"]), \
        f"降级反思卡片应有友好提示，实际：{card}"
```

#### TC-RF-PARALLEL03：LLM-A 成功、LLM-B 失败时降级处理
```python
async def test_reflection_llm_b_fails_llm_a_succeeds():
    """
    模板提取（LLM-B）超时，偏好提取（LLM-A）正常。
    降级策略：
    - preferences 正常保存
    - template_skeleton 为 None（本次不生成模板，不影响偏好）
    """
    with patch("app.agent.reflection.call_llm_a",
               return_value=json.dumps({
                   "preferences": [
                       {"slot_name": "output_format", "value": "simple_table",
                        "confidence": 0.85}
                   ],
                   "slots_corrected": []
               })), \
         patch("app.agent.reflection.call_llm_b",
               side_effect=asyncio.TimeoutError("LLM-B timeout")):
        node = ReflectionNode()
        result = await node.run(state=make_post_execution_state())

    assert len(result.reflection.preferences) == 1
    assert result.reflection.preferences[0]["value"] == "simple_table"
    assert result.reflection.template_skeleton is None
```

#### TC-RF-PARALLEL04：两次并行调用均失败时反思节点不崩溃
```python
async def test_reflection_both_llm_fail_graceful_degradation():
    """
    两次 LLM 调用均失败（如 LLM 服务不可用）。
    反思节点应完全降级：不保存偏好、不保存模板、
    反思卡片显示简单完成消息，Agent 流程继续到 done。
    """
    with patch("app.agent.reflection.call_llm_a",
               side_effect=Exception("LLM service unavailable")), \
         patch("app.agent.reflection.call_llm_b",
               side_effect=Exception("LLM service unavailable")):
        node = ReflectionNode()
        result = await node.run(state=make_post_execution_state())

    # 不应抛异常，流程继续
    assert result is not None
    assert result.phase == "done", \
        "反思层完全失败后 Agent 应进入 done，不应卡住"
    assert result.reflection.preferences == []
    assert result.reflection.template_skeleton is None
```

#### TC-RF-PARALLEL05：验证两次调用确实并行（而非串行）
```python
async def test_reflection_llm_calls_are_concurrent():
    """
    验证 LLM-A 和 LLM-B 是并发执行的，
    总耗时应接近 max(A耗时, B耗时)，而非 A耗时 + B耗时。
    """
    async def slow_llm_a(*args, **kwargs):
        await asyncio.sleep(1.0)
        return json.dumps({"preferences": [], "slots_corrected": []})

    async def slow_llm_b(*args, **kwargs):
        await asyncio.sleep(1.0)
        return json.dumps({"should_save_template": False, "template_skeleton": None})

    with patch("app.agent.reflection.call_llm_a", side_effect=slow_llm_a), \
         patch("app.agent.reflection.call_llm_b", side_effect=slow_llm_b):
        start = time.time()
        node = ReflectionNode()
        await node.run(state=make_post_execution_state())
        elapsed = time.time() - start

    # 并行：总耗时应 < 1.5s（两个 1s 并行，允许 0.5s 开销）
    # 串行：总耗时会 ≥ 2.0s
    assert elapsed < 1.8, (
        f"两次 LLM 调用耗时 {elapsed:.2f}s，疑似串行执行（应 < 1.8s）"
    )
```

---

### TC-RF-RETRY：反思节点重试机制验证

> 文件：`tests/unit/test_reflection_retry.py`

#### TC-RF-RETRY01：LLM-A 首次非法 JSON 后重试成功
```python
async def test_reflection_llm_a_retries_on_invalid_json():
    """
    LLM-A 第一次返回非法 JSON，第二次返回合法结果。
    偏好提取应在重试后成功。
    """
    call_count = 0

    async def flaky_llm_a(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return "<think>分析中...</think>用户喜欢图表格式"  # 非法 JSON
        return json.dumps({
            "preferences": [{"slot_name": "output_format", "value": "chart_text",
                              "confidence": 0.9}],
            "slots_corrected": []
        })

    with patch("app.agent.reflection.call_llm_a", side_effect=flaky_llm_a):
        with patch("app.agent.reflection.call_llm_b",
                   return_value=json.dumps({"should_save_template": False,
                                            "template_skeleton": None})):
            node = ReflectionNode()
            result = await node.run(state=make_post_execution_state())

    assert call_count == 2
    assert len(result.reflection.preferences) == 1
    assert result.reflection.preferences[0]["value"] == "chart_text"
```

#### TC-RF-RETRY02：重试后仍失败时偏好为空（不幻觉）
```python
async def test_reflection_llm_a_max_retries_gives_empty_preferences():
    """
    LLM-A 连续两次返回非法 JSON，最终偏好为空列表。
    关键断言：空偏好 ≠ 上次会话的偏好（不能用旧数据填充）。
    """
    async def always_invalid(*args, **kwargs):
        return "这不是一个有效的 JSON 响应"

    with patch("app.agent.reflection.call_llm_a", side_effect=always_invalid), \
         patch("app.agent.reflection.call_llm_b",
               return_value=json.dumps({"should_save_template": False,
                                        "template_skeleton": None})):
        node = ReflectionNode()
        result = await node.run(state=make_post_execution_state())

    assert result.reflection.preferences == [], \
        "LLM-A 重试耗尽后应返回空偏好，不应使用旧偏好数据填充"
```

---

### TC-RF-QUAL：反思层偏好提取质量测试（真实 LLM 调用）

> 文件：`tests/accuracy/test_reflection_accuracy.py`  
> 标记：`@pytest.mark.llm_real`  
> 执行上下文基于 MockAPI 模拟建议文档 §7 测试问题库真实场景构建。

#### TC-RF-QUAL01：反思层不为低价值分析生成偏好
```python
@pytest.mark.llm_real
@pytest.mark.parametrize("scenario_desc,execution_ctx", [
    (
        # §7 边界测试 E2：日粒度降级查询，价值低，不应提取偏好
        "用户仅查询昨天实时数据（降级为日汇总，信息量少）",
        make_execution_ctx(
            question="昨天下午3点的实时吞吐量是多少？",
            apis_called=["getDailyProductionDynamic"],  # M08
            output_format="simple_table",
            task_count=1,
            was_degraded=True,  # 被降级的查询
        )
    ),
    (
        # 数据不足（Mock Server 返回空）触发提前终止
        "分析因 Mock API 返回空数据提前终止",
        make_execution_ctx(
            question="上个月各业务线的吞吐量是多少？",
            apis_called=["getThroughputByBusinessType"],  # M02
            output_format="simple_table",
            task_count=1,
            execution_status="partial",  # 未完整完成
            empty_data=True,
        )
    ),
    (
        # 用户中途取消（§5.3 兜底后用户放弃）
        "用户中途取消分析",
        make_execution_ctx(
            question="查一下港口整体情况",
            apis_called=["getThroughputSummary"],  # M01（兜底）
            output_format="simple_table",
            task_count=1,
            execution_status="cancelled",
        )
    ),
])
async def test_reflection_skips_trivial_analyses(scenario_desc, execution_ctx):
    """
    低价值分析场景下，反思层不应生成偏好（噪声偏好会污染记忆库）。
    LLM 应识别出本次分析不足以提取有价值的偏好。
    """
    node = ReflectionNode()
    result = await node.run(state=make_post_execution_state(ctx=execution_ctx))

    high_confidence_prefs = [
        p for p in result.reflection.preferences
        if p.get("confidence", 0) >= 0.8
    ]
    assert len(high_confidence_prefs) == 0, (
        f"场景「{scenario_desc}」不应生成高置信度偏好，"
        f"实际生成：{high_confidence_prefs}"
    )
```

#### TC-RF-QUAL02：反思层偏好提取准确率（基于 §7 真实场景）
```python
# 反思准确率数据集：基于 MockAPI §7 测试问题库的典型执行上下文
REFLECTION_ACCURACY_DATASET = [
    (
        # §7 B1：用户明确要求图文格式（chart_text）→ M03+M04+M14
        "§7 B1 集装箱趋势图文分析，用户明确要求出图",
        make_execution_ctx(
            question="分析一下今年Q1港口集装箱吞吐量的变化趋势，以及背后的主要驱动因素",
            apis_called=["getThroughputTrendByMonth", "getContainerThroughput",
                         "getKeyEnterpriseContribution"],
            output_format="chart_text",
            task_count=4,
            slots_explicitly_set=["output_format", "cargo_type"],
        ),
        {"output_format": "chart_text"}
    ),
    (
        # §7 A1~A2：用户月度粒度查询 → M02
        "§7 A1 月度板块分类查询，时间粒度明确为月度",
        make_execution_ctx(
            question="上个月各业务线的吞吐量是多少？",
            apis_called=["getThroughputByBusinessType"],
            output_format="simple_table",
            task_count=2,
            time_granularity="monthly",
            slots_explicitly_set=["time_granularity"],
        ),
        {"time_granularity": "monthly"}
    ),
    (
        # §7 A5：用户指定集装箱货类 → M04
        "§7 A5 集装箱 TEU 目标完成率查询",
        make_execution_ctx(
            question="集装箱吞吐量今年目标是多少TEU，完成率怎样？",
            apis_called=["getContainerThroughput"],
            output_format="simple_table",
            task_count=2,
            cargo_type="集装箱",
            slots_explicitly_set=["cargo_type"],
        ),
        {"cargo_type": "集装箱"}
    ),
    (
        # 用户纠正时间范围（2024年 → 2026年，在数据范围内）
        "用户将 2024年 纠正为 2026年（进入 Mock 数据范围）",
        make_execution_ctx(
            question="2026年各港区吞吐量对比",
            apis_called=["getMarketZoneThroughput"],
            output_format="chart_text",
            task_count=3,
            correction={
                "slot": "time_range",
                "original": "2024年",
                "corrected": "2026年"
            },
        ),
        {"slots_corrected_includes": "time_range"}
    ),
    (
        # §7 C2：full_report 月度月报，无纠正
        "§7 C2 月度经营月报（生产+市场+投资），8个API，用户未纠正",
        make_execution_ctx(
            question="帮我生成3月份港口经营分析月报，PPT格式，包含生产、市场、投资三个维度",
            apis_called=["getThroughputSummary", "getContainerThroughput",
                         "getBerthOccupancyRate", "getVesselEfficiency",
                         "getMarketMonthlyThroughput", "getMarketZoneThroughput",
                         "getKeyEnterpriseContribution", "getInvestPlanProgress"],
            output_format="full_report",
            task_count=8,
            correction=None,
        ),
        {"output_format": "full_report", "slots_corrected_count": 0}
    ),
    (
        # §7 B3：战略客户分析，用户专注客户域
        "§7 B3 战略客户贡献+流失风险分析，客户域偏好",
        make_execution_ctx(
            question="战略客户贡献趋势是否稳定，有没有流失风险？",
            apis_called=["getStrategicCustomerThroughput", "getCustomerContributionRanking",
                         "getCustomerCreditInfo"],
            output_format="chart_text",
            task_count=4,
            domain="customer",
            slots_explicitly_set=["domain"],
        ),
        {"domain": "customer"}
    ),
    (
        # §7 B7：投资进度偏差分析
        "§7 B7 投资进度节奏对比，投资域偏好",
        make_execution_ctx(
            question="投资完成进度是否符合年初节奏安排？",
            apis_called=["getInvestPlanProgress", "getInvestPlanSummary"],
            output_format="chart_text",
            task_count=3,
            domain="invest",
            slots_explicitly_set=["domain"],
        ),
        {"domain": "invest"}
    ),
]

@pytest.mark.llm_real
async def test_reflection_preference_extraction_accuracy():
    """
    反思层偏好提取整体准确率 ≥ 80%（基于 MockAPI §7 真实场景）。
    数据集覆盖5大领域典型执行上下文，比原有通用场景更接近生产环境。
    """
    node = ReflectionNode()
    scores = []

    for desc, ctx, expected in REFLECTION_ACCURACY_DATASET:
        result = await node.run(state=make_post_execution_state(ctx=ctx))
        prefs = {p["slot_name"]: p["value"] for p in result.reflection.preferences}

        hits = 0
        total = 0
        for key, expected_val in expected.items():
            if key == "slots_corrected_includes":
                total += 1
                if expected_val in (result.reflection.slots_corrected or []):
                    hits += 1
            elif key == "slots_corrected_count":
                total += 1
                if len(result.reflection.slots_corrected or []) == expected_val:
                    hits += 1
            else:
                total += 1
                if key in prefs and str(expected_val).lower() in str(prefs[key]).lower():
                    hits += 1

        score = hits / total if total else 1.0
        scores.append((score, desc))

    overall = sum(s for s, _ in scores) / len(scores)
    failed = [(desc, score) for score, desc in scores if score < 0.6]
    print(f"\n反思层偏好提取准确率（§7 真实场景）: {overall:.1%}")
    if failed:
        print("低分场景:")
        for desc, score in failed:
            print(f"  [{score:.0%}] {desc}")

    assert overall >= 0.80, \
        f"反思层偏好提取准确率 {overall:.1%} < 80%，需优化反思 Prompt"
```

