# 灰度开关 / 死代码 / 残留路径清理总收尾

**周期**：2026-04-30 → 2026-05-01（一次完整审计 + 9 个清理 commit）
**目标读者**：后续维护者；想了解"为什么这些开关都没了"的人

---

## 0. TL;DR

| 指标 | 数值 |
|---|---|
| 清理的 feature flag | **7 个**（最初审计 9 个，保留 2 个性能优化用）|
| 删除的死代码模块 | **`_outline_legacy.py` + `_kpi_extractor.py` + `tools/export_api_registry.py`** |
| 提交数 | 9 个 |
| 净变化 | **+1808 / -3788 = 净删 1980 行** |
| 测试结果 | 全程零回归（370 passed → 372 → 370，差额来自删除的 baseline 测试）|
| Spec 文档 | 3 篇（[employees_db](./refactor_employees_db.md), [report_outline](./refactor_report_outline.md) Step 12 收尾, 本篇）|

---

## 1. 清理时间线

| Commit | 主题 | 净行 |
|---|---|---|
| `0a48df1` | `refactor(report)`: 删 outline LLM + rule fallback 双路径 → 仅 LLM | -549 |
| `7d35ccc` | `refactor(api_registry)`: 删 4 模式源切换 (code/file/db/dual/dual_db) → DB 唯一源 | **-1903** |
| `78846c1` | `feat(admin)`: domain delete + 写后 reload 钩子 | +231 |
| `ad32169` | `feat(admin/ui)`: API 新增按钮 + Domain CRUD drawer | +408 |
| `491e5ea` | `refactor(employees)`: 删 yaml/db 双源 → DB 唯一源 | +43 |
| `2151f05` | `chore(config)`: 删 `REPORT_DEBUG_DUMP_OUTLINE` | -27 |
| `365e941` | `chore(config)`: 删死开关 `FF_NEW_UI`（零引用）| -4 |
| `4bc52c4` | `refactor(report)`: DOCX/HTML 仅 LLM agent → 删 `REPORT_AGENT_ENABLED` | -165 |
| `299c635` | `chore(config)`: thinking events 永远持久化 → 删 `FF_THINKING_STREAM` | -14 |
| **合计** | | **-1980** |

按时间顺序读这个表，看到的是从"先做最大块的源真相统一" → "补管理平台" → "扫尾零碎 flag" 的渐进结构。

---

## 2. 清理清单（按 flag）

### 2.1 删除的 flag（7 个）

| Flag | 旧默认 | 旧用途 | 替代 |
|---|---|---|---|
| `REPORT_OUTLINE_PLANNER_ENABLED` | `False` | LLM planner 主路径 vs 规则 fallback | LLM 唯一路径，失败 raise |
| `REPORT_AGENT_ENABLED` | `True` | DOCX/HTML 是否走 LLM agent | DOCX/HTML 永远 LLM agent，agent 失败 raise；Markdown/PPTX 一直 deterministic 不变 |
| `REPORT_DEBUG_DUMP_OUTLINE` | `False` | 把 outline JSON dump 调试 | 开发者手动 `print(outline.to_json())`，无需 flag |
| `FF_API_REGISTRY_SOURCE` | `"code"` | code/file/db/dual/dual_db 5 种源切换 | DB 唯一源；code 内联数据全部移到 `data/api_registry.json`（出厂数据） |
| `FF_EMPLOYEE_SOURCE` | `"db"` | yaml/db 双源 | DB 唯一源；YAML 文件保留为出厂数据被 seed 用 |
| `FF_NEW_UI` | `False` | Phase 1 三窗格 workbench | 死开关，前后端零引用 |
| `FF_THINKING_STREAM` | `True` | thinking 事件持久化开关 | 永远持久化（与 `trace_span` 事件早已无开关一致）|

### 2.2 删除的模块/文件

| 路径 | 行数 | 原因 |
|---|---|---|
| `backend/tools/report/_outline_legacy.py` | 189 | rule fallback 死后无人调用 |
| `backend/tools/report/_kpi_extractor.py` | 136 | 旧路径独立 KPI 抽取，新路径已合并 |
| `backend/agent/api_registry.py` 内联数据 | ~1400 | 业务数据搬到 `data/api_registry.json` + DB |
| `tools/export_api_registry.py` | 65 | code 不再是真相源，无 export 需求 |
| `tests/contract/test_outline_planner_fallback.py` | 141 | fallback 路径已删 |
| `tests/contract/test_api_registry_source_override.py` | 165 | 5 种源已剩 1 种 |
| `tests/contract/test_api_registry_export.py` | 56 | 与 export 工具同生共死 |
| `tests/fixtures/report_baseline/normal/golden.docx` | binary | DOCX 现在永远 LLM，输出非确定 |
| `tests/fixtures/report_baseline/normal/golden.html` | binary | 同上 |

### 2.3 保留的 flag（2 个）

| Flag | 默认 | 保留原因 |
|---|---|---|
| `ENABLE_TEMPLATE_HINT` | `True` | 性能优化（在 prompt 注入历史模板提示），效果好就开，无副作用 |
| `ENABLE_TEMPLATE_BYPASS` | `True` | 性能优化（关键词命中跳过 LLM planning，秒级返回），关掉只是慢一点不会出错 |

这两个不是"行为切换"或"路径选择"，是**纯成本/速度旋钮**，无清理诉求。

---

## 3. 统一设计原则（核心精神）

整轮清理贯穿了 4 条原则。新代码若违背这些原则，回看本节。

### 3.1 单一路径，不要 silent fallback

**反例**（清理前 `_outline_planner.py`）：
```python
if settings.REPORT_OUTLINE_PLANNER_ENABLED:
    try:
        outline = await llm_plan(...)
    except Exception as e:
        logger.warning("LLM failed, falling back to rule path")
return rule_plan(...)  # ← 静默退化，bug 被遮蔽
```

**正例**（清理后）：
```python
outline = await llm_plan(...)  # 失败直接抛 _LLMPlannerFailure
```

silent fallback 三重伤害：
1. 出错的根因不可见（用户看到的是"另一种正常输出"）
2. 测试更难写（要兼容两种输出）
3. 维护者要懂两条路径才能调试

### 3.2 Fail-fast 启动

DB 没 seed = 启动炸，立刻知道是部署清单漏跑了 seed 命令。**不要**在 lifespan 里 try/except 后用 code 内联数据"应急"——那只会把"DB 没 seed"问题推迟到第一次有真实查询时才暴露，而且每次重启都要靠运维记得 seed。

清理后 `lifespan_apply_source` 长这样：
```python
async def lifespan_apply_source() -> None:
    ep_count, dom_count = await reload_from_db()
    if ep_count == 0:
        raise RuntimeError(
            "api_endpoints table is empty — run "
            "`uv run python -m tools.seed_api_endpoints`"
        )
```

错误信息直接告诉运维下一步该跑什么命令。

### 3.3 业务数据离开代码

清理前：`api_registry.py` 1400 行内联端点数据，运维改个 API 描述要重新发版。
清理后：`data/api_registry.json` 是出厂数据；运行后所有变更通过管理平台直写 DB；改 JSON 跑一次 seed 就把新出厂数据合并进去。

### 3.4 写后立即生效

管理平台写了 DB，但内存全局变量还是旧数据 = 用户看到"保存成功"但运行时没生效 = 难以排查的鬼故事。清理后所有 admin 写路由 `commit DB → 调用 reload_from_db()`，UI 上"保存成功"等于"立即生效"。

`EmployeeManager` 早就内置了这个模式（`upsert_employee` 写 DB 后立即刷新 `_profiles` + 失效 `_graphs`）。`api_registry` 后来也补齐了。

---

## 4. 部署清单（清理后）

首次部署必须按顺序执行：

```bash
uv sync                                                       # 1. 装依赖
cp .env.example .env && vi .env                                # 2. 填 QWEN_API_KEY 等
uv run alembic upgrade head                                    # 3. 建表
uv run python -m tools.seed_api_endpoints                      # 4. 灌 API 注册表 + 域
uv run python -m migrations.scripts.seed_admin_tables          # 5. 灌内置工具
uv run python -m migrations.scripts.seed_employees_from_yaml   # 6. 灌员工档案
uv run uvicorn backend.main:app                                # 7. 启动
```

任何一步漏跑，第 7 步的 lifespan 会立即 raise 并指出缺哪个 seed 命令。CI workflow `.github/workflows/regression.yml` 已经按这个顺序配好。

---

## 5. 运行时契约（清理后）

### 5.1 数据流（统一为"出厂 JSON/YAML → seed → DB → 内存"）

```
data/api_registry.json + employees/*.yaml  ← 出厂数据，git 跟踪
              │
              ↓ seed_api_endpoints / seed_employees_from_yaml （UPSERT，幂等）
              │
        api_endpoints / domains / employees  ← DB 是运行时唯一源
              │
              ↓ reload_from_db() / EmployeeManager.load_from_db()
              │
        in-memory globals （BY_NAME / DOMAIN_INDEX / EmployeeManager._profiles）
              │
              ↓ admin 写 DB → 立即调 reload
              │
       所有调用方 （planning / agent / chat）
```

### 5.2 报告生成路径（不再有 fallback）

| 端 | 路径 |
|---|---|
| Markdown | `render_outline()` deterministic（无 LLM） |
| PPTX | `render_outline()` + 可选 PptxGenJS Node 桥（无 LLM） |
| DOCX | LLM agent loop（唯一路径，失败 raise） |
| HTML | LLM agent loop（唯一路径，失败 raise） |
| Outline 规划 | LLM 单次 call（唯一路径，失败 raise `_LLMPlannerFailure`）|

---

## 6. 测试基础设施变化

新增 conftest session-scope autouse fixture（一次启动，惠及全测试）：

| Fixture | 作用 |
|---|---|
| `_seed_and_load_api_registry` | seed `api_endpoints` + `domains` → 调 `reload_from_db()` 把 `BY_NAME` / `DOMAIN_INDEX` 填满 |
| `_seed_and_load_employees` | seed `employees` + `employee_versions` → 调 `EmployeeManager.load_from_db()` |

测试中常用的辅助函数：
- `stub_planner_llm(monkeypatch)` ← outline planner 走 stub LLM 输出（baseline 测试用）
- `disable_pptxgen_bridge(monkeypatch)` ← 关掉可选 Node 桥（曾叫 `disable_skill_mode`）

删除的辅助：
- `freeze_kpis(monkeypatch)` ← 旧 KPI extractor 已删，stub_planner_llm 取代它

---

## 7. 不要在新代码里再做的事

给后人看的"避雷指南"：

| 反模式 | 替代 |
|---|---|
| 给一个新功能加 `if settings.NEW_FF_xxx:` 分支 | 直接做新行为；要灰度就用部署级别策略（金丝雀 / 蓝绿）|
| LLM 失败 → silent fallback 到旧路径 | LLM 失败 raise，让监控/告警接住 |
| 把业务数据写在 Python module 顶层 | 出厂数据放 `data/*.json`，运行时 DB 装载 |
| 改了 DB 但内存缓存不刷 | admin 写路由结尾必跑 `reload_from_db()` |
| lifespan try/except 吞错 | DB 不可用就 raise，不要"先跑起来再说"|
| 加 debug flag 把对象 dump 到磁盘 | 加一行 `print(...)` / `logger.debug(...)` 比专用 flag 实用得多 |

---

## 8. 完整 commit 序列（备查）

```
299c635 chore(config): always persist thinking events; drop FF_THINKING_STREAM
4bc52c4 refactor(report): DOCX/HTML LLM agent is the only path; drop REPORT_AGENT_ENABLED
365e941 chore(config): remove dead FF_NEW_UI flag
2151f05 chore(config): remove unused REPORT_DEBUG_DUMP_OUTLINE flag
491e5ea refactor(employees): single source of truth via DB; remove FF_EMPLOYEE_SOURCE
ad32169 feat(admin/ui): API create button + full domain CRUD drawer
78846c1 feat(admin): domain delete + reload-after-write so admin edits take effect immediately
7d35ccc refactor(api_registry): single source of truth via DB; remove FF_API_REGISTRY_SOURCE
0a48df1 refactor(report): remove rule fallback path; LLM planner is now sole outline source
```

每个 commit message 是 self-contained 的——`git show <sha>` 看了就懂。
