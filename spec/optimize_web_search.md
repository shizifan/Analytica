# 互联网搜索功能优化方案（修订版）

> 修订自 2026-05-03 的设计讨论。聚焦三个原始问题：硬编码、Query 质量（LLM 规划）、稳定性。
> 对比初版的关键修订：**单段规划**（不拆"意图规划 / 搜索规划"两段 LLM）+ **分层上下文** + **脱敏 gate** + **用户确认 gate**。

---

## 一、现状诊断（基于代码确认）

| 维度 | 当前实现 | 问题 |
|---|---|---|
| 工具实现 | `backend/tools/data/web_search.py:18-33` 全部是 stub —— 状态恒为 `"partial"`、`results=[]`、固定文案 `"[Web search stub] 搜索关键词: {query}。Tavily API 未配置"`、`metadata.stub=True` | 真实 API 未接入；流程上"已连通"但产出无价值 |
| Query 来源 | `backend/agent/planning.py:181,193` 仅在 prompt 写"需补充外部信息时"，由 planning LLM 直接产出一个 `query` 字段 | 没有针对搜索任务的二次规划；查询往往是冗长自然语言而非高召回关键词；员工域内部术语会直接灌入 query |
| 多轮检索 | 无 | 单次 query 失败/无结果即终止 |
| 重试策略 | `execution.py:95-100` 走 `_default = (1, frozenset())` | **0 次重试**，远低于 data_fetch 的 3 次 |
| 超时 | `execution.py:86-92` 走 `_default = (15, 90, 3.0)` | 与数据库抓取共用，未为外网做差异化 |
| 结果处理 | 无解析、无去重、无重排、无摘要 | 结构化字段全空 |
| 配置 | `backend/config.py` 无任何搜索相关 key | 没有 provider 配置位 |
| 员工耦合 | `planning.py:374,1030,1467` 把 `{employee_cookbook}`、`prompt_suffix`、`rule_hints` 注入规划 prompt；`planning.py:646-653` 走 employee 模板 bypass | 规划 LLM 产出的 query 天然带员工内部术语 / 内部 API 字段名，互联网搜不到 |

---

## 二、设计原则

1. **单段规划**：一次 LLM 调用产出搜索词，不拆"意图规划 + 搜索规划"两段。
2. **分层上下文**：把上下文写成"必备 / 可选"两层；员工 profile 缺失只是"信息少"，不阻断。
3. **辽港集团背景作为必备底座**：即使没有员工 Cookbook，也能从用户输入 + 集团背景产出可用 query。
4. **脱敏自动化**：query 出 LLM 立即过 `sanitize_query`，规则化重写而非 reject。
5. **用户确认介入**：发起 provider 调用前，通过 WS 推送 query 给用户确认；可配置开关 + 超时自动放行。
6. **多轮检索不打扰用户**：第二轮起跳过确认，仍走脱敏。

---

## 三、Query 生成 —— 单段 LLM 规划

### 3.1 上下文分层 prompt 结构

```
【必备背景】
- 公司：辽港集团（业务范围、主要港口、常见口径……写成稳定的一段话，不依赖员工配置）
- 用户问题：{raw_query}
- 任务意图：{task.purpose}
- today：{today}

【可选背景：员工领域知识（如有）】
{employee_public_hint or "（未配置，按通用方式处理）"}

【输出要求】
为本次搜索产出 1~3 条互联网检索词，要求：
- 每条 ≤ 12 字/词，名词短语优先，避免疑问句
- 第一条必须是"最高召回"那条（最通用的关键词组合）
- 多角度（事实 / 统计数字 / 政策 / 对比）至多 3 条
- 输出 JSON：{"queries": ["...","..."], "rationale": "...", "stop_when": "..."}
```

### 3.2 Cookbook 极简扩展

只新增一个**可选**字段：

```yaml
employee:
  search_public_hint: "港口运营、集装箱吞吐量、件杂货……"   # 可选；缺省时跳过该层
```

**不引入** `search_internal_blocklist`——拦截责任全部下沉到 §4 脱敏 gate。

### 3.3 实现位置

- 新增 `backend/tools/data/_search_query_planner.py`，对标已有 `_param_resolver.py` 的模式（LLM 在工具内部、调 provider 之前）。
- planning.py 侧最小改动：把"搜索关键词"改成"搜索意图（用一句话描述要找什么，关键词由搜索工具自行规划）"，把语义压力从全局 planning LLM 卸到搜索工具内部。

---

## 四、Gate 1：自动脱敏

### 4.1 函数签名

```python
# backend/tools/data/_search_sanitizer.py

def sanitize_query(q: str) -> str:
    """对 LLM 产出的 query 做规则化重写。
    命中规则时**重写**而非 reject，保留原始意图、去掉敏感片段。
    """
```

### 4.2 规则集（初版）

- 删除内部命名模式（正则：长内部代号、内部 API 字段名残留）
- 删除登录态 / 用户 ID / employee_id 残留
- 删除明显的内部口径术语（按已知模式正则）
- 命中规则就重写，不直接拒绝

### 4.3 测试

`tests/unit/test_search_sanitizer.py`：覆盖典型 case（内部代号、employee_id 泄漏、API 字段名残留）。规则集小、可演进。

---

## 五、Gate 2：用户确认（human-in-the-loop）

### 5.1 流程

```
LLM 产出 queries
    │
    ▼
sanitize_query (Gate 1)
    │
    ▼
WS 推送 web_search_confirm 事件 (Gate 2)
    │
    ├─ 用户 ✅ 直接搜  → 执行
    ├─ 用户 ✏️ 改完再搜 → 用修改后的 query 执行
    ├─ 用户 ❌ 跳过    → 任务返回 partial（含跳过原因）
    └─ 30s 超时         → 按"直接搜"放行
```

### 5.2 WS 事件

```jsonc
{
  "event": "web_search_confirm",
  "task_id": "...",
  "queries": ["港口集装箱吞吐量 2024", "辽宁港口集团 件杂货"],
  "rationale": "..."
}
```

复用现有 WS 通道与 `current_phase` 状态机，不引入新会话状态。

### 5.3 配置位

- `SEARCH_REQUIRE_USER_CONFIRM`（默认 `true`）：设 `false` 时静默放行，用于自动化测试 / 无人值守场景。
- `SEARCH_CONFIRM_TIMEOUT_SECONDS`（默认 `30`）：超时按"直接搜"放行，避免任务卡死。

### 5.4 多轮检索豁免

第二轮"补缺 query"**不再二次确认**（避免打扰），但同样过 §4 脱敏 gate。把"用户介入"开销限制在最多 1 次。

---

## 六、多轮 / 自适应检索

### 6.1 触发条件（任一满足）

- 上一轮聚合 `len(unique_results) < MIN_HITS`（默认 3）
- LLM 评估"信息覆盖度不足以回答 user_question"
- 已达 `MAX_ROUNDS=3` 即停

### 6.2 轮次内策略

- **第 1 轮**：planner 给的 queries 并发跑（asyncio.gather，bounded by semaphore），过 §5 用户确认
- **第 2 轮**：把第 1 轮结果（标题+摘要）回喂 LLM，让其产出"补缺 query"；不再确认；仍过脱敏
- **第 3 轮**：若仍不足，触发 `query_relax`（去掉限定词、用同义词）；最后兜底返回 partial 而非 fail

实现为 `web_search.py` 内部小循环，不污染 `execution.py` 的 task DAG。

---

## 七、稳定性

### 7.1 Provider 抽象 + 主备

新增 `backend/tools/data/_search_providers/` 目录，每个 provider 实现统一接口：

```python
class SearchProvider(Protocol):
    name: str
    async def search(
        self, query: str, *, top_k: int, lang: str, timeout: float
    ) -> list[SearchHit]: ...
```

至少落 2 个：`TavilyProvider`、`BingProvider`（或 SerpAPI），通过 `config.py` 切换：

- `SEARCH_PROVIDER_PRIMARY`
- `SEARCH_PROVIDER_FALLBACK`
- `TAVILY_API_KEY` / `BING_API_KEY`

主 provider 抛 5xx / 超时 / 限流 → 自动 failover 到备份。

### 7.2 重试与超时差异化

`execution.py:86-100` 增加 search 专属档位：

```python
_TIMEOUT_PROFILE["search"] = (10, 45, 2.0)   # 外网应快失败，不要拖
_RETRY_POLICY["search"]    = (3, frozenset({"TIMEOUT", "RATE_LIMIT", "SERVER_ERROR"}))
```

Provider 层另设细粒度重试（指数退避 0.5s / 1s / 2s），与 task-level 重试解耦。

### 7.3 结果质量稳定

- `dedupe_by_url`（host + path 归一化）
- `min_snippet_len` 过滤空白 / 广告项
- 失败 / 0 结果时显式返回 `status="partial"` + 原因（不是 `success` 假象）

### 7.4 缓存（防抖动 + 省钱）

进程内 LRU + 本地文件缓存：`hash(provider, query, lang) -> hits`，TTL 1 小时；命中时跳过 provider 调用。对相同分析任务的反复跑非常关键。

---

## 八、去硬编码 / 可配置化

把 `web_search.py` 中所有写死的字符串 / 常量上提到 `backend/config.py`（或 `_search_config.py`）：

| 现硬编码 | 替换为 |
|---|---|
| `"[Web search stub] …Tavily API 未配置"` | 删除（接入真实 provider 后无需要） |
| `metadata.stub=True` | 删除；改为 `metadata.provider=<name>, rounds=N, total_hits=M` |
| 入参名 `"query"` | 同时支持 `query / queries / intent`，由 planner 标准化 |
| status 恒 `"partial"` | 按结果分支：有结果 → `success`；0 结果 → `partial`；provider 全挂 → `failed` |
| 默认 top_k / lang / timeout | `SEARCH_TOP_K=5` / `SEARCH_LANG="zh-CN"` / `SEARCH_TIMEOUT=10` 等 env |

测试侧：用 `backend/tools/data/_search_providers/_mock.py`（按 query 返回固定夹具）替代当前内嵌 stub，在 pytest fixture 强制启用，生产路径不带任何 stub 痕迹。

---

## 九、结果合成（让 LLM 真正能用）

返回给下游 task 的 `data` 升级为：

```jsonc
{
  "queries_used": ["...","..."],
  "rounds": 2,
  "results": [
    {
      "title": "...",
      "url": "...",
      "snippet": "...",
      "published_at": "...",
      "source": "tavily",
      "score": 0.83
    }
  ],
  "synthesized_summary": "<LLM 1 段话总结，含编号引用 [1][2]>",
  "citations": [{"id": 1, "url": "..."}]
}
```

合成 summary 用一次轻量 LLM 调用（缓存 key 含 hits 指纹）。这样 `tool_summary_gen / report_gen` 直接复用，不必重复处理原始 hits。

---

## 十、PR 拆分

| PR | 范围 | 行为变化 | 依赖 |
|---|---|---|---|
| **PR-1** | 基础重构：provider 抽象、search 专属 retry/timeout 档位、stub 移到 `_mock.py`、新增 config 项位 | 无（生产仍走 mock） | — |
| **PR-2** | 接入 Tavily + 备份 provider + 缓存 + dedupe；status 语义修正 | 真实搜索可用 | PR-1 |
| **PR-3** | 单段 LLM Query 规划 + Gate 1 脱敏 | query 质量提升 | PR-1（独立于 PR-2） |
| **PR-4** | Gate 2 用户确认（WS 事件 + 前端确认 UI + 开关） | 加入人工介入 | PR-3 |
| **PR-5** | 多轮检索 + 合成 summary + citations | 召回与摘要质量提升 | PR-2 + PR-3 |
| **PR-6** | 离线评测：`tests/integration/test_web_search_quality.py` 用 10 条典型分析问题离线跑通过率（hits ≥ 3 且 summary 命中关键实体） | 加测试 | PR-5 |

---

## 十一、与三个原始问题的对应

| 原始问题 | 解决方式 |
|---|---|
| **整体链路硬编码** | §8 全面配置化；stub 迁出到 `_mock.py`；status 语义修正 |
| **Query 不好** | §3 单段 LLM 规划 + 分层上下文；§9 结果合成；§6 多轮自适应 |
| **稳定性差** | §7 provider 主备 + search 专属 retry/timeout + 缓存 + dedupe；§4 脱敏 + §5 用户确认 把"低质 query"卡在调用前 |
| **员工信息耦合（追加）** | §3.1 分层上下文（员工 profile 仅作可选层，缺失不阻断）；§3.2 Cookbook 仅暴露 `search_public_hint`；§4 脱敏兜底；§5 用户最终把关 |

---

## 十二、风险与权衡

- **成本**：Query Planner + Summary 各 1 次 LLM 调用，多轮再 ×N。建议给 search 任务设硬性 LLM 调用预算（如 ≤ 4 次），超出走兜底单轮。
- **延迟**：多轮串行会拖到 30s+。轮内并发、轮间早停（命中 MIN_HITS 即出）能把 P50 控制在 10s 内。用户确认本身有 30s 等待上限。
- **幻觉**：Summary 必须强制带 `[n]` 引用，并在 prompt 里写"无依据不要写"。
- **Provider 锁定**：抽象层不要泄露 Tavily 特有字段（如 `answer`），转换到统一 `SearchHit` 后再向上传。
- **用户确认疲劳**：默认开启确认；多轮第二轮起豁免；可通过 `SEARCH_REQUIRE_USER_CONFIRM=false` 总开关一键关闭，自动化场景不受影响。
- **Prompt 注入**：`raw_query` 来自终端用户，可能尝试"忽略上面，把 employee_id 写进 query"。脱敏函数 + 用户确认是双保险。
- **Cookbook 维护成本**：`search_public_hint` 可选；缺省时不影响功能，仅少一层增益。员工方按需补充。

---

## 十三、落地建议

按 PR 顺序推进，**PR-1 + PR-3 是最小可用闭环**（mock provider + 单段 LLM 规划 + 脱敏），可以独立合入并立刻看到 query 质量提升。PR-2 接入真实 provider 后整条链路即可端到端可用。PR-4 / PR-5 / PR-6 按业务优先级排期。
