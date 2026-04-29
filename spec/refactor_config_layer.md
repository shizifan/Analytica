# 配置项分层重构实施方案

**目标读者**：未来接手 Analytica 配置项 / 注册表 / 规划层定制工作的工程师（无本会话上下文）
**实施时段**：本次会话（commit `8d9d134`）
**状态**：已实施并推送到 `origin/master`；contract 测试 186 passed

---

## 0. TL;DR

本次重构把**散落在代码各处的"配置项"**（LLM 参数、字段中文名、FAQ、API 注册表、员工 prompt 等）按**分层模型**重新组织，让它们：

1. **去重**：同一份信息只保留一处来源（_field_labels.py 重命名为更准确的名字；前端 PHASE_LABELS 合并）
2. **集中**：硬编码常量收敛到 `Settings`（LLM 三档温度）或单一来源（DEFAULT_EMPLOYEE_ID）
3. **可编辑**：FAQ / API / Prompt 从代码 → YAML → DB → admin UI，每层都加 contract 测试锁住语义
4. **可定制**：员工级 override（rule_hints、label_zh）+ 全局兜底，避免大锅饭
5. **可灰度**：核心组件（API Registry）切换源时走 `code → file → dual → db` 路径，永远保留 `code` 作为回滚网

**核心架构突破**：配置项分层模型 + dual mode 灰度 + 安全保存门控（dry-run），三个 pattern 一旦建立可复用到其他配置类工作上。

---

## 1. 背景与动机

### 1.1 问题盘点（重构前现状）

| 问题类型 | 具体表现 |
|---|---|
| **重复定义** | `PHASE_LABELS` 在 `Topbar.tsx` 与 `ChatPageV2.tsx` 各写一份；`'asset_investment'` 字符串散在 2 个 TS 文件 |
| **命名误导** | `_i18n.py` 实际做字段→中文显示名映射，与"国际化"无关 |
| **硬编码常量** | LLM `temperature=0.x` 出现在 14 个文件、值 0.1/0.2/0.3 各异，无统一语义注释 |
| **配置代码绑定** | 142 个 API 端点定义嵌在 `api_registry.py` 1645 行硬编码元组里，admin 不能改 |
| **数据多处镜像** | FAQ 数据在 `frontend/src/data/employeeFaq.ts` 写死；YAML 与 TS 双源 |
| **员工配置失能** | `PLANNING_RULE_HINTS` 是全局字典；`prompt_suffix` 只对 single-round 有效，full_report 走的 multi-round 路径**完全不接员工 cookbook** |
| **prompt 改动无保护** | 想改员工 prompt 只能直接 PUT，没办法在不影响线上的前提下试一次 |
| **disambiguate 文本污染** | API 端点的消歧文本可能引用其他 endpoint 名，但那些名字可能：(a) 被该员工显式排除 → LLM 反复尝试 → 规划失败；(b) 已重命名/删除 → 引用不存在的 endpoint |

### 1.2 用户实际遭遇的 bug（驱动力）

**FAQ ai-2 问题**：用户在主页点了一个 FAQ「2026年投资项目进度，以柱状图展示各项目完成率」，规划阶段连续失败 3/3，错误是「过滤后没有剩余任务」。深挖发现：
- `getInvestPlanByYear.disambiguate` 字段写着「若需查询各项目完成率请用 `getCapitalProjectsList` 或 `getPlanFinishByProjectType`」
- 但 `getCapitalProjectsList` **被显式从 asset_investment.yaml 排除**（属于"明细列表 API"分类）
- LLM 看到 prompt 里这条建议反复尝试调用 → 验证器拒掉 → 规划失败

这个 bug 把"配置项分散、缺乏层级感知、无 lint 检查"的痛点暴露了出来，也成为本次重构的具体导火索。

### 1.3 设计目标

| 目标 | 验证手段 |
|---|---|
| 任何配置项都有**单一权威来源** | grep 不到第二处定义 |
| 全局默认 + 员工覆写**两层语义清晰** | resolver 函数 + 三档（缺省 / 跳过 / 覆写）契约 |
| 注册表迁移到 DB 时**0 行为变化** | dual_db 14 天 0 WARN |
| 改 prompt **必须先验证再生效** | 保存按钮 disabled 直到 dry-run pass |
| 修复一类 bug 的同时**杜绝同类回归** | 防御性 contract 测试（覆盖 disambiguate 完整性等） |

---

## 2. 配置项分层模型

本次重构最重要的产出是**显式化了配置项的"层级模型"**。所有可编辑的配置项都落在以下某一层（或多层），不同层有不同语义：

```
┌─────────────────────────────────────────────────────────────┐
│ Layer 0 — 硬编码源（code）                                   │
│   • Python 常量、TypeScript 常量、Pydantic 默认值             │
│   • 永远保留作为回滚兜底（带 inline TODO 防误删）             │
├─────────────────────────────────────────────────────────────┤
│ Layer 1 — 应用配置（Settings / config.ts）                   │
│   • 通过 env var / config 文件覆写                           │
│   • 例：LLM_TEMPERATURE_DEFAULT、DEFAULT_EMPLOYEE_ID         │
├─────────────────────────────────────────────────────────────┤
│ Layer 2 — 文件源（YAML / JSON）                              │
│   • 受版本控制；启动时加载到内存                              │
│   • 例：employees/*.yaml、data/api_registry.json             │
├─────────────────────────────────────────────────────────────┤
│ Layer 3 — DB 源（admin 可写 + 版本快照）                     │
│   • 在线编辑；改动持久化到表 + 版本表                          │
│   • 例：employees / api_endpoints / employee_versions        │
├─────────────────────────────────────────────────────────────┤
│ Layer 4 — Admin UI（dry-run 保护下的可视化编辑）             │
│   • 编辑前预览影响；保存前自动写版本                           │
│   • 例：EmployeeDetailDrawer / ApiEditDrawer                 │
└─────────────────────────────────────────────────────────────┘
```

**配置项定位与升级路径**：

| 配置项 | 当前层级 | 升级方向 | 限制 |
|---|---|---|---|
| LLM 三档温度 | Layer 1 | 不需要更高层 | 改了要重启进程 |
| 字段中文名（COLUMN_LABELS 全局） | Layer 0 | 已部分到 Layer 2（field_schema 4th 元素） | 每个 endpoint 单独定制 |
| FAQ 列表 | Layer 2 (YAML) + Layer 3 (DB) | Layer 4 admin 编辑 ✅ | DB 模式才能在线写 |
| API 注册表 | Layer 0 → 2 → 3 → 4 灰度中 | dual_db 验证 14 天后切 db | 永远保留 code 作为回滚 |
| 员工 perception/planning prompt | Layer 2 + Layer 3 + Layer 4 | dry-run 保护已就位 | 试运行有 LLM 成本 |
| `PLANNING_RULE_HINTS` | Layer 0 + Layer 2（员工 override） | 需要时升 Layer 3 | 当前足够 |

每个配置项要回答 4 个问题：
1. **它当前在哪一层？**（grep 找定义点）
2. **谁是单一权威源？**（多层时哪层赢）
3. **下游怎么读取？**（lazy import vs 模块级 import 决定刷新语义）
4. **如何切换层级？**（dual mode / 数据迁移脚本）

---

## 3. 实施细节（按 Phase 顺序）

### 3.1 P0 — 去重收敛（基础卫生）

**Task 0.1** — 前端阶段标签合并
- 新建 [`frontend/src/lib/labels.ts`](../frontend/src/lib/labels.ts)，导出 `PHASE_LABELS` / `WS_LABELS`
- `Topbar.tsx`、`ChatPageV2.tsx` 改为 import
- 验证：`grep '感知中' frontend/src` 只剩一处

**Task 0.2** — `DEFAULT_EMPLOYEE_ID` 常量
- 新建 [`frontend/src/config/app.ts`](../frontend/src/config/app.ts)
- 选择常量而非环境变量：这是产品决策（默认显示哪个员工），不是部署配置

**Task 0.3** — LLM 温度三档化
- 全量审计先于动手：14 处 `temperature=0.x` 散在各文件
- 新增 `Settings.LLM_TEMPERATURE_{DEFAULT,BALANCED,CREATIVE} = 0.1/0.2/0.3`，分组语义清晰
  - DEFAULT (0.1)：结构化/确定性输出（参数解析、列选择、KPI 抽取）
  - BALANCED (0.2)：半生成式（归因、HTML/DOCX）
  - CREATIVE (0.3)：生成式（描述性分析、摘要）
- 拆 PR-A（9 处工具）+ PR-B（3 处核心：main / graph / reflection）降低单 commit 回归面

**Task 0.4** — `_i18n.py` → `_field_labels.py`
- 改名 + 8 处 import 更新
- 这一步**先于** P2.3（字段中文名进 field_schema）执行，避免在错命名上继续工作

**P0 教训**：
- 提取常量前必须 grep 全量找出所有点；本次实际 14 处比初估的 6 处多 2 倍
- 改名是最低风险的第一步，先做能为后续步骤减少阻力

### 3.2 P1 — FAQ 数据迁移（TS → YAML → DB → UI）

**前置验证（关键）**：先确认 `EmployeeProfile.faqs` Pydantic 字段已存在 + manager `from_yaml` 直通加载——这步如果跳过，会发现"yaml 加了没用"才回头改模型。

**Task 1.1** — 数据迁移
- 把 [`employeeFaq.ts`](../frontend/src/data/employeeFaq.ts) 三个员工 5×3=15 条 FAQ 填入 YAML 的 `faqs:` 段
- 前端简化为只保留 `universalFAQs`（加载态兜底），`getEmployeeFAQs` 函数移除
- contract 测试：每个 yaml `faqs` 长度==5、id 唯一非空、question 非空

**Task 1.2** — 全链路 scenario 测试
- `tests/scenarios/test_faq_full_chain.py`：15 个参数化 case 走 perception → planning
- 标记 `@pytest.mark.scenario`，不进默认回归（首次录制 cache 需真 LLM key + ~$10-20 成本）

**Task 1.3** — Admin 编辑（验收）
- 实地核查发现：前端 `EmployeeDetail.tsx` 的 FAQ 编辑 UI **本就实现了**（addFaq / updateFaq / removeFaq）+ 后端 `PUT /api/employees/{id}` 已支持 `faqs` 字段
- 因此 1.3 实际只需写 round-trip contract 测试锁住「前端 payload → 后端模型 → DB merge → 再读一致」5 个层次
- 决策：跳过原计划的 3 个专项端点（`PUT/POST/DELETE /api/employees/{id}/faqs[/{faq_id}]`）—— 当前批量编辑模式（点编辑 → 多条改 → 一次保存）下专项端点**无对应交互需求**，YAGNI

### 3.3 工作台编辑迁移（设计微调）

实施 P1.3 之后用户截图反馈：编辑入口应该全部走 admin 控制台，chat 工作台只保留只读。

**做法**：
- chat-side `EmployeesDrawer/EmployeeDetail.tsx` 重写为只读：删除 `DraftState`、6 个增删改 handler、所有 `editing ? <input> : <text>` 三元
- 底栏新增「前往控制台编辑」`<Link to="/admin/employees?selected=...">`
- admin `EmployeesView.tsx` 用 `useSearchParams` 接 `?selected=` 自动打开抽屉
- admin `EmployeeDetailDrawer.tsx` 接管 FAQ 编辑（之前只有概览/感知/规划三个 tab，FAQ 信息只是 stat card 计数）

**关键设计**：deep link 是用户体验闭环关键。光把"编辑"按钮移走会让用户失去操作路径；通过 query param 传递选中员工 ID，链接点开后自动 hydrate 到目标抽屉。

### 3.4 P2 — API Registry 分层迁移（最大头）

#### P2.1 — 一次性 JSON 导出 ([data/api_registry.json](../data/api_registry.json))

**关键设计：`serialize_to_dict()` 把 tuple 标准化为 list**

```python
# api_registry.py（不是导出工具）
def serialize_to_dict() -> dict[str, Any]:
    return _to_jsonable({
        "domains": {code: asdict(d) for code, d in _CODE_DOMAIN_INDEX.items()},
        "endpoints": [asdict(ep) for ep in _CODE_ENDPOINTS],
    })
```

为什么 serialize / deserialize 在 `api_registry.py` 而不是 tools 脚本？因为：
- 运行时加载（`_resolve_source('file')` 从 JSON 加载）和导出工具需要**对同一个 on-disk shape 达成一致**
- 把 helper 留在 api_registry.py 中，tools 脚本变成**纯 CLI wrapper**
- 否则 tools 脚本依赖 api_registry.py、api_registry.py 想读 JSON 又得反向依赖 tools——**循环依赖**

**Freshness 契约**：`tools/export_api_registry.py --check` 模式 + 一个 contract 测试都会在 `api_registry.py` 改了但 JSON 没重导时立刻红 CI。

#### P2.2 — 三档源（code / file / dual）

```python
# _resolve_source 调度器（pure function，便于测试）
def _resolve_source(source: str | None = None):
    if source == "code":
        return _CODE_DOMAIN_INDEX, _CODE_ENDPOINTS
    if source == "file":
        return load_from_json(...)
    if source == "dual":
        _diff_dual(file_data)   # 比对 + WARN
        return _CODE_*           # 仍用 code（影子 file）
    # 缺文件 / 解析失败 → fallback 到 code（永不 crash 启动）
```

**rollback 安全网**：`code` 分支注释明确「Do NOT remove this `code` branch when promoting `file` to default」。本次注释里也写了 P2.4 的同款约定。

#### P2.3 — `field_schema` 4 元素扩展 + 调用点接线

P2.3a（schema 层）：
- `ApiEndpoint.field_schema: tuple[tuple[str, ...], ...]`（向后兼容 3 元素）
- 第 4 元素 = `label_zh`（Chinese display name）
- `ApiEndpoint.label_for(col_name)` 返回 override 或 None

P2.3b（接线层，焦点版）：
- `DataFrameItem` / `ChartDataItem` 新增 `endpoint_name: str | None`
- `_extract_items` 从 `task_output.metadata["endpoint"]`（api_fetch 已写入）提取
- 新 helper `resolve_col_label(endpoint_name, col)`：endpoint label_zh → 全局 COLUMN_LABELS → 原列名

P2.3 范围调整（用户截图发现的遗漏点）：
- chat 任务结果预览（`_build_task_results_payload`）也需要做翻译
- 不在原计划 P2.3b 范围（计划只点了 `_content_collector` 和 chart_*.py）
- 顺手补完 + 4 个新测试

#### P2.3 / FAQ ai-2 修复（disambiguate 卫生）

发现 4 处问题：
1. `getInvestPlanByYear.disambiguate` 推荐已被 asset_investment 排除的端点
2/3. `getTotalssets` / `getAssetValue.disambiguate` 同上
4. `getCumulativeTrendChart` / `getTrendChart.disambiguate` 引用不存在的端点（疑似旧名）

**防御性 contract**：[`test_planning_prompt_endpoints.py`](../tests/contract/test_planning_prompt_endpoints.py)
- 每个员工 endpoints 列表中的端点，其 disambiguate 不能引用对该员工排除的端点
- 任何 endpoint 的 disambiguate 不能引用注册表里不存在的端点
- `_format_ep_detail` 要兼容 3/4 元素 field_schema

**P2.3a 隐藏 bug**：`_format_ep_detail` 里 `for f, t, _ in ep.field_schema` 是硬编码 3 元素解构。一旦有 endpoint 用了 4 元素 row，prompt 渲染就 `ValueError`。已修为 `row[0], row[1]`。

#### P2.4 — DB 模式（最大灰度变更）

`api_endpoints` 表 schema 缺 4 个语义列（field_schema / use_cases / chain_with / analysis_note）。新建 migration `20260429_0001` 加列。

异步加载模式：
- 模块 import 时（同步）：`_resolve_source('db')` 退化到 code，logger.info 提示「deferring DB load to lifespan」
- FastAPI lifespan 启动时（async）：`await api_registry.lifespan_apply_source()` 真正读 DB → swap module globals

派生索引 in-place mutation：
```python
def _rebuild_derived_indices() -> None:
    BY_NAME.clear(); BY_PATH.clear(); BY_DOMAIN.clear(); BY_TIME.clear()
    for ep in ALL_ENDPOINTS:
        BY_NAME[ep.name] = ep
        BY_PATH[ep.path] = ep
        BY_DOMAIN.setdefault(ep.domain, []).append(ep)
        BY_TIME.setdefault(ep.time, []).append(ep)
```

为什么要 in-place？下游消费者大多用 `from backend.agent.api_registry import BY_NAME`（懒导入或全局），如果 `BY_NAME = {...new dict...}` 重新绑定模块属性，**已经 import 过的副本看不到新值**。in-place mutate 让所有 import 路径自动看到新数据。

dual_db 模式：DB 是新 primary，code 是 shadow——和 P2.2 的 dual（code primary, file shadow）方向**相反**。日志前缀 `[dual_db]` 与 `[dual]` 不同，运维查问题不会混。

实地发现：dev DB 多 2 条 code 已不存在的 endpoint（`getCostProjectCurrentStageQtyList` / `getCostProjectFinishByYear`）。这是 **dual_db 第一次跑就发现的真实数据漂移**——验证了灰度方案的价值。手动 DELETE 掉，DB ↔ code 完全对齐。

#### P2.5 — Admin API 编辑抽屉 ([ApiEditDrawer.tsx](../frontend/src/components/ui/admin/ApiEditDrawer.tsx))

4 tab 设计：
- **基础**：method / path / domain / intent / time_type / granularity / source / enabled / tags
- **参数**：required / optional params（增删行）/ param_note / returns
- **字段**：field_schema 4 列编辑器；保存时第 4 列空字符串自动降级为 3 元素（保持 wire 形态精简）
- **语义**：disambiguate / use_cases / chain_with / analysis_note

**抽屉自取数据**模式：组件接收 `name` 而非 `AdminApi` 对象，自己 GET。这避免列表 shape（缺 enrichment 字段）和详情 shape 不一致带来的隐患，保存后再次 GET 确保拿到最新值。

### 3.5 P3 — 员工层个性化

#### P3.1 — Prompt 编辑 + dry-run 保护

后端：
- `POST /api/admin/employees/{id}/dryrun-perception` / `dryrun-planning`
- helper `_profile_with_overrides`：用 Pydantic `model_copy` 拷贝 + 覆写，**完全不污染 manager singleton**
- 引擎抛错 → 422，前端能看到失败信息

前端：
- 感知/规划 tab 从只读 JsonBlock 改为可编辑 textarea
- 各 tab 独立 sample query 输入 + 「试运行」按钮
- 保存按钮 disabled 直到对应 tab 的 dry-run 通过 + **prompt 没再变**（promptSnapshot 比对）

```typescript
// 关键 gate 逻辑
const perceptionGateOk =
  perceptionDryRun.status === 'ok'
  && perceptionDryRun.promptSnapshot === perceptionPrompt;

const saveDisabled =
  saving || !name.trim()
  || (perceptionPromptDirty && !perceptionGateOk)
  || (planningPromptDirty && !planningGateOk);
```

「↺ 恢复默认（v1.0）」按钮：`GET /api/employees/{id}/versions/1.0` → 回填 draft + 重置 dry-run state。

**保存时的 merge 关键**：PUT 用 `{...detail.perception, system_prompt_suffix: newPrompt}` 形式，避免 wipe 掉 `extra_slots` / `slot_constraints` / `domain_keywords` 等其他字段。

#### P3.2 — `rule_hints` 三档语义 + multi-round bug 修复

**`rule_hints` 字段**（`PlanningConfig`）：
- 缺省 / 不在 dict 中 → 全局默认
- 空字符串 → 跳过该规则
- 非空字符串 → 覆写

```python
def resolve_rule_hint(key: str, overrides: dict[str, str] | None) -> str:
    overrides = overrides or {}
    if key in overrides:
        return overrides[key]
    return PLANNING_RULE_HINTS.get(key, "")
```

**意外修复的隐藏 bug**：

P3.2 实施过程中发现，`_generate_plan_multiround` 路径**完全不接 `prompt_suffix`**——signature 里就没有这个参数。意味着 full_report 复杂度（multi-round 默认入口）下，**任何员工的 cookbook 都是空转**。

`_call_section_llm` 的 SECTION_PROMPT 模板也没有 cookbook placeholder。修复：
- 加 `{employee_cookbook}` placeholder
- 把 `prompt_suffix` 串到 multi-round 路径
- 渲染条件式：空 cookbook 不留空块

成本权衡：每次 full_report 多消耗 4-6 × cookbook 长度（约 5-6KB）的 input tokens。换来的是规划质量对齐。

---

## 4. 反复使用的 Pattern

### 4.1 Dual mode 灰度

**用途**：当某个数据源（code → file → DB）需要切换时，运行时同时加载新旧两个源，比对差异，但**对外仍服务旧源**，让生产侧 0 行为变化。

**实现要点**：
- 命名隔离：`dual` vs `dual_db` 是不同 mode（不互相覆盖）
- 日志前缀区分：`[dual]` / `[dual_db]`，运维 grep 不歧义
- 永远保留 fallback 路径 + inline TODO 防误删
- 退出条件：14 天 0 WARN（按计划）

**适用范围**：
- ✅ 注册表/枚举类数据迁移（已用：API Registry）
- ✅ 缓存层切换（未来：employee profile 切到 Redis）
- ⚠️ 不适合需要写入的迁移（dual write 是另一个 pattern）

### 4.2 全局兜底 + 局部 override

**形态**：
```python
def resolve_xxx(specific_context, key) -> str:
    # 1. 局部上下文（员工/端点/会话）
    local = specific_context.get(key) if specific_context else None
    if local is not None:
        return local
    # 2. 全局默认
    return GLOBAL_DEFAULTS.get(key, "")
```

**已应用**：
- `resolve_col_label(endpoint_name, col)` — endpoint label_zh → 全局 COLUMN_LABELS
- `resolve_rule_hint(key, overrides)` — 员工 rule_hints → 全局 PLANNING_RULE_HINTS
- 隐含：`ApiEndpoint.label_for` → `col_label`

**三档语义**（rule_hints 引入）：
- key 缺省 → 用全局默认
- key 存在但空字符串 → **跳过**（输出空，不输出全局默认）
- key 存在且非空 → 覆写

这个三档比朴素的「有就用，没有就 fallback」多一档「显式跳过」。一些场景（如 asset_investment 不分析吞吐货类，整段 cargo_selection 规则是噪声）需要这个能力。

### 4.3 Save guard via dry-run

**适用场景**：当某项配置改错会**直接破坏线上服务**（prompt 写废、规则配错），保存前必须能预览影响。

**模式**：
1. 提供「试运行」endpoint，接受未保存的覆写参数 + 样例输入
2. 服务端构造**临时配置对象**（Pydantic `model_copy`，不污染 manager 单例）
3. 跑实际引擎（perception / planning 等），返回结果
4. 前端展示结果 + ✓/✗ 状态
5. 「保存」按钮 disabled until ✓
6. **关键**：试运行后再次编辑 prompt → 状态失效，必须重跑（promptSnapshot 比对）

成本可接受：dry-run 一次 ≈ 真实一次调用的成本，admin 操作频率低。

---

## 5. 测试策略

### 5.1 三层测试金字塔（本次新增）

| 层 | 数量 | 例子 |
|---|---|---|
| **单元 / Pure helper** | ~30 | `resolve_rule_hint` 三档 / `_to_jsonable` 形态 / `label_for` 4 元素 |
| **Contract** | ~45 | DB schema 列存在 / round-trip 无损 / payload shape 一致 / dual 日志前缀 |
| **Integration / scenario** | 15（不进默认回归）| FAQ 全链路 perception→planning 录制 |

### 5.2 防御性 contract（最有价值）

这次重构沉淀的几个**永久守护型测试**：

1. **`test_planning_prompt_endpoints.py`** — 任何 endpoint 的 disambiguate 不能引用：
   - 该员工排除的端点 → 阻止 FAQ ai-2 类回归
   - 注册表里不存在的端点 → 阻止 typo 残留

2. **`test_api_registry_export.py::test_checked_in_json_matches_current_registry`** — JSON 跟代码不同步立刻红 CI

3. **`test_api_registry_db_lifespan.py::test_diff_dual_db_uses_distinct_log_prefix`** — `[dual]` 与 `[dual_db]` 不能在 grep 时混淆

4. **`test_planning_rule_hints.py::test_section_call_renders_employee_cookbook`** — multi-round 路径不能再次"忘记"传 cookbook

这些测试的共同点：**每个对应一个真实发生过的 bug**。它们存在不是为了"覆盖率"，是为了**让同类 bug 不能复发**。

---

## 6. 操作 Runbook

### 6.1 部署 P2.4（API Registry → DB）

```bash
# 1. 升级数据库 schema
alembic upgrade head

# 2. 一次性 seed（幂等，可重复跑）
python -m tools.seed_api_endpoints

# 3. 启用 dual_db 模式（DB 主、code 影子）
export FF_API_REGISTRY_SOURCE=dual_db

# 重启后端，观察日志 14 天，应当 0 行 [dual_db] WARN
# 若有 WARN，按提示评估：
#   - "endpoints only in DB"  → admin 误加？保留还是删？
#   - "endpoints only in code" → 有人在线删了？补回还是同步删 code？
#   - "field divergence on X"  → 内容漂移，逐字段对账

# 4. 切默认到 db
export FF_API_REGISTRY_SOURCE=db

# 5. 永久保留作为回滚
export FF_API_REGISTRY_SOURCE=code  # 应急时
```

### 6.2 在线编辑 prompt（P3.1）

1. 进 `/admin/employees?selected=<id>`，切到「感知配置」或「规划配置」tab
2. 编辑 textarea
3. **必须**点「试运行」，看到 ✓ 通过 + 槽位/任务数符合预期
4. 保存
5. 触发 `employee_versions` 版本快照
6. 出问题 → 点「↺ 恢复默认（v1.0）」 → 再保存

### 6.3 重新生成 `data/api_registry.json`

```bash
# 任何 backend/agent/api_registry.py 改动后必须跑：
python -m tools.export_api_registry

# CI 上检查 freshness：
python -m tools.export_api_registry --check
# exit 0 = 同步；exit 1 = 需要重导
```

### 6.4 添加新员工的 rule_hints 覆写（演示）

在 `employees/<emp_id>.yaml` 的 `planning:` 段下：

```yaml
planning:
  prompt_suffix: |
    （现有 cookbook）
  rule_hints:
    cargo_selection: ""        # asset_investment 不分析吞吐货类，跳过
    minimization: |            # 自定义最小化规则
      - 资产分析单端点优先
      - 不要为凑数把房屋+土地+设备拆三个 fetch
    # time_param 不出现 → 用全局默认
```

DB 模式下：通过 admin UI 编辑 employee → 同样保存到 `employees.planning` JSON 列。

---

## 7. 后续待办（明确未做）

| 项目 | 优先级 | 备注 |
|---|---|---|
| **P2.3c**：chart_*.py 调用点也用 `resolve_col_label` | 中 | 当前 chart 系列名仍用全局 COLUMN_LABELS；如果要让某 endpoint 的图表系列名也支持覆写需要做这一步。chart 工具读 DataFrame 但不读 task_output.metadata，需要重构数据流 |
| **disambiguate 自动过滤** | 中 | 计划 v2 末尾提到的「更大架构题」：planning prompt builder 在拼接 disambiguate 时，按 `allowed_endpoints` 过滤掉指向不可用端点的引用。当前用 lint contract 检测，未自动 strip |
| **多语言 i18n 框架** | 低 | 当前只是字段→中文映射，不是真正的 i18n。`_field_labels.py` 命名就是这个含义 |
| **Plan template 在线编辑** | 中 | P4 候选；JSON 编辑器复杂度较高 |
| **Domain D1-D7 进 DB** | 低 | 当前在 `DOMAIN_INDEX` 写死。变更频率极低，进 DB 收益有限 |
| **Memory 手动写入 UI** | 低 | P4 候选 |
| **LLM A/B 测试框架** | 高 | 本次 dry-run 只能跑一次；要做 prompt 版本 A vs B 对比需要更系统的框架 |
| **`PLANNING_RULE_HINTS` 升级到 Layer 3（DB）** | 低 | 当前 Layer 0+员工 override 已经覆盖大多数场景。如果出现"全员 cargo_selection 都需要改"的场景，再升级 |
| **Fallback 标识机制** | 中 | 当 `_resolve_source` 因 DB 故障 fallback 到 code 时，admin UI 应该有一个全局 banner「当前 API 注册表来自 fallback 源，部分端点可能未更新」 |

---

## 8. 决策日志（关键 Q&A）

| 问题 | 决策 | 理由 |
|---|---|---|
| LLM temperature 用 nested LLMSettings 还是 flat? | flat | 与现有 `Settings.QWEN_*` 风格一致；nested 是为了"分组"但单个 Settings 类已经够大 |
| `DEFAULT_EMPLOYEE_ID` 用常量还是 env var? | 常量 | 这是产品决策，env var 反而让本地/线上分叉 |
| `field_schema` 加列还是用 JSON 单列存? | 加列（4 个） | 可索引、admin UI 编辑友好、与 code 字段一一对应；DB 上不解析 JSON 没意义（用户原话） |
| seed 脚本：UPSERT 还是首次 INSERT? | UPSERT | 可重复运行；code 改了重 seed 同步到 DB |
| dual_db 是 DB 主还是 code 主? | DB 主，code 影子 | 这是「DB 准备替换 code」的灰度方向，与 P2.2 的 dual（code 主）相反 |
| `rule_hints` 是 dict[str, str] 还是 dict[str, str/None]? | dict[str, str]，空字符串=跳过 | YAML 中 `null` 语义易混；空字符串作为"显式跳过"信号更明确 |
| dry-run 失败时返回什么状态码? | 422 | 让前端知道是"业务失败"（保存按钮保持 disabled），与 4xx 客户端错误区分 |
| 试运行 prompt 改动是否就地保存? | 不 | 必须显式点保存。dry-run 只是预览 |
| `data/api_registry.json` 进版本控制吗? | 进 | freshness contract 测试需要它；它是 P2.1 的产出 |
| 编辑能力放 chat 还是 admin? | admin only | 工作台保持只读；deep link 跳转 |
| chat 任务结果预览的列名翻译，算 P2.3 吗? | 算（顺手补） | 用户截图反馈才发现 P2.3b 计划没覆盖这条路径，但属于同类问题 |
| 是否给所有 142 endpoints 填 label_zh? | 不 | 增量按需。当前全局 COLUMN_LABELS 已覆盖大多数；只在某 endpoint 的列名要"和别人不同"时才覆写 |

---

## 9. 文件影响清单（commit `8d9d134`）

```
后端 (9 文件)
├── backend/agent/api_registry.py          源调度器 + reload + dual_db
├── backend/agent/planning.py              rule_hints + multi-round cookbook
├── backend/agent/execution.py             chat 任务结果预览翻译
├── backend/employees/profile.py           PlanningConfig.rule_hints
├── backend/employees/graph_factory.py     传 rule_hints 给 engine
├── backend/main.py                        dryrun endpoints + ApiEndpointUpsert
├── backend/memory/admin_store.py          api_endpoints 4 列读写
├── backend/tools/_field_labels.py         resolve_col_label
└── backend/tools/report/_content_collector.py  endpoint_name 透传

前端 (7 文件)
├── frontend/src/api/client.ts             AdminApi 扩展 + dryrun + getEmployeeVersion
├── frontend/src/components/ui/admin/EmployeeDetailDrawer.tsx  prompt 编辑 + dry-run
├── frontend/src/components/ui/admin/ApiEditDrawer.tsx         新增（P2.5）
├── frontend/src/components/ui/EmployeesDrawer/EmployeeDetail.tsx 改只读
├── frontend/src/components/ui/EmployeesDrawer/index.tsx       去编辑 plumbing
├── frontend/src/pages/admin/ApisView.tsx  挂编辑按钮
└── frontend/src/pages/admin/EmployeesView.tsx  deep-link

数据/迁移/工具 (4 文件)
├── data/api_registry.json                 142 endpoints 导出（P2.1）
├── migrations/versions/20260429_0001_api_endpoint_semantic_columns.py
├── tools/export_api_registry.py           CLI wrapper（--check / --output）
└── tools/seed_api_endpoints.py            幂等 UPSERT seeder

测试 (12 新文件)
├── tests/contract/test_api_endpoints_db_round_trip.py    (5 cases)
├── tests/contract/test_api_registry_db_lifespan.py       (8 cases)
├── tests/contract/test_api_registry_export.py            (3 cases)
├── tests/contract/test_api_registry_field_labels.py      (7 cases)
├── tests/contract/test_api_registry_reload_from_db.py    (5 cases)
├── tests/contract/test_api_registry_source_override.py   (10 cases)
├── tests/contract/test_employee_dryrun.py                (11 cases)
├── tests/contract/test_field_label_resolution.py         (11 cases)
├── tests/contract/test_planning_prompt_endpoints.py      (5 cases)
├── tests/contract/test_planning_rule_hints.py            (12 cases)
└── tests/contract/test_task_results_label_translation.py (4 cases)

合计：32 文件改动 / +5500 行 / -350 行
```

---

## 10. 验收

**自动化**：
- 默认 pytest 套件：186 passed / 1 skipped / 76 deselected (scenario)
- 3 个 pre-existing LLM cache miss（perception_health / planning_health / full_chain）— 与本次重构无关，需要单独录制
- 前端 `tsc --noEmit`：0 error
- 前端 `npm run build`：934 modules / ~400ms
- alembic：从 `20260425_0001` 顺利升到 `20260429_0001`，无 schema 冲突

**手动**（推荐执行）：
1. `/admin/apis` 任一行 → 编辑 → 字段 tab 加一行 4 元素 row → 保存 → 该 endpoint 的报告/任务预览列名变化
2. `/admin/employees?selected=asset_investment` → 感知配置 → 改 prompt → 试运行 → 保存
3. chat 工作台员工抽屉 → 「前往控制台编辑」按钮 → admin 自动打开对应员工
4. （DB 模式下）`FF_API_REGISTRY_SOURCE=dual_db` 重启后端 → 日志 0 行 `[dual_db]` WARN
5. （生产）跑 `python -m tools.seed_api_endpoints --dry-run` → 确认 142 条
6. 触发一个 full_report 复杂度查询 → planning prompt 应包含「员工专属规划提示（Cookbook）」段（验证 P3.2 multi-round 修复）

**未自动化的回归**：
- FAQ 全链路 scenario 测试（`tests/scenarios/test_faq_full_chain.py`，15 cases）首次跑需要 `--llm-mode=record-missing` 录制约 30 个 LLM 响应（成本 ~$10-20）
- 录制后再跑零成本 replay
