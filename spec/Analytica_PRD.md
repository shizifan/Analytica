# 数据分析智能体产品需求文档

## 目录

1. [产品概述](#1-产品概述)
2. [目标用户与使用场景](#2-目标用户与使用场景)
3. [产品架构总览](#3-产品架构总览)
4. [核心能力模块详细设计](#4-核心能力模块详细设计)
   - 4.1 感知层（Perception）
   - 4.2 规划层（Planning）
   - 4.3 执行层（Execution）
   - 4.4 反思层（Reflection）
5. [技能库设计](#5-技能库设计)
6. [数据接入层设计](#6-数据接入层设计)
7. [用户体验设计](#7-用户体验设计)
8. [非功能性需求](#8-非功能性需求)
9. [数据安全与合规](#9-数据安全与合规)
10. [验收标准](#10-验收标准)

---

## 1. 产品概述

### 1.1 产品定位

**产品名称：** Analytica（分析师智能体）

**一句话定义：** 具备感知-规划-执行-反思闭环能力的企业级数据分析智能体，通过自然语言交互帮助业务人员完成从问题澄清到报告交付的全流程数据分析任务。

**核心价值主张：**
- 将非结构化的业务问题转化为结构化的分析方案
- 融合内部数据 API、互联网检索与多种分析技能
- 具备自我优化能力，通过反思机制持续积累用户偏好与分析范式

### 1.2 产品背景

传统数据分析工具存在三个断层：数据工具与业务语境的断层、单次分析与持续优化的断层、工具操作与分析思维的断层。现有 AI 助手虽能辅助分析，但缺乏明确的问题澄清机制、结构化规划过程和结果质量反思能力。

Analytica 通过将智能体分析过程显式化为四个闭环阶段，弥合上述断层，让分析过程可见、可追溯、可改进。

### 1.3 产品边界

**包含：**
- 多轮对话式问题澄清
- 动态分析方案规划与更新
- 数据获取（API + 互联网检索）
- 多类型分析技能调用
- 多格式报告输出
- 用户偏好与技能的反思沉淀

**不包含（MVP 阶段）：**
- 自主数据库 Schema 探索（需显式配置数据源）
- 实时流数据分析
- 多用户协同编辑分析报告

---

## 2. 目标用户与使用场景

### 2.1 目标用户画像

| 用户类型 | 代表角色 | 核心诉求 | 技术门槛 |
|----------|----------|----------|----------|
| 业务决策者 | 部门经理、运营总监 | 快速获得洞察，支撑决策 | 低 |
| 业务分析师 | 数据分析师、运营专员 | 提升分析效率，探索深度 | 中 |
| 技术管理者 | 数字化项目经理 | 可配置、可集成、可审计 | 高 |

### 2.2 典型使用场景

**场景 A：简单数据查询**
用户：「上个月各业务线的吞吐量是多少？」
预期输出：一张格式化数据表格或简洁图表，响应时间 < 30 秒

**场景 B：图文分析**
用户：「分析一下今年 Q1 港口集装箱吞吐量的变化趋势，以及背后的主要驱动因素」
预期输出：含趋势图 + 归因分析文字的混合报告，响应时间 < 3 分钟

**场景 C：复杂分析报告**
用户：「帮我做一份针对明年货量预测的分析报告，结合市场数据和内部历史数据，需要 PPT 格式」
预期输出：完整结构化 PPTX 报告，响应时间 < 10 分钟

### 2.3 用户旅程地图

```
用户输入问题
    │
    ▼
【感知阶段】多轮澄清 ──── 歧义/不完整 ──→ 追问用户
    │ 问题清晰
    ▼
【规划阶段】生成分析方案 ──→ 用户确认/修改方案
    │ 方案确认
    ▼
【执行阶段】逐步执行任务清单
    │ ├─ 调用数据 API
    │ ├─ 检索互联网
    │ ├─ 调用分析技能
    │ └─ 动态更新计划（如发现新问题）
    ▼
【反思阶段】总结本次分析
    │ ├─ 记录用户偏好
    │ └─ 沉淀分析技能
    ▼
输出最终结果 + 反思摘要（用户确认）
```

---

## 3. 产品架构总览

### 3.1 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                       用户交互层                              │
│     Web Chat UI  /  API 接入  /  企业系统集成                 │
└─────────────────────────────┬───────────────────────────────┘
                              │
┌─────────────────────────────▼───────────────────────────────┐
│                    智能体核心引擎                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐   │
│  │ 感知模块  │→│ 规划模块  │→│ 执行模块  │→│ 反思模块  │   │
│  │Perception│  │Planning  │  │Execution │  │Reflection│   │
│  └──────────┘  └──────────┘  └──────────┘  └──────────┘   │
│                      ↕ 状态管理（Session State）              │
└─────────────────────────────┬───────────────────────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       │                      │                      │
┌──────▼──────┐     ┌─────────▼────────┐    ┌───────▼──────┐
│  数据接入层  │     │    技能执行层      │    │  记忆存储层   │
│             │     │                  │    │              │
│ • 数据 API  │     │ • 描述性分析      │    │ • 用户偏好    │
│ • 互联网检索 │     │ • 归因分析        │    │ • 分析模板    │
│ • 文件上传  │     │ • 预测分析        │    │ • 技能配置    │
│             │     │ • 可视化          │    │ • 历史会话    │
└─────────────┘     │ • 文档生成(多格式)│    └──────────────┘
                    └──────────────────┘
```

## 4. 核心能力模块详细设计

### 4.1 感知层（Perception Layer）

#### 4.1.1 模块职责

感知层负责将用户的非结构化自然语言输入转化为明确的、可规划的分析意图描述（Structured Intent）。核心挑战在于：用户表达往往模糊、不完整，或隐含了多种可能的分析路径。

感知层采用 **Slot 填充（Slot Filling）** 机制：明确定义完成一次数据分析所必须确定的信息槽位，逐步从对话历史、用户记忆偏好和当前输入中填充这些槽位，仅对真正缺失且无法推断的槽位向用户发起追问。这一机制使澄清行为有据可查，避免了依赖主观阈值调优的不确定性。

#### 4.1.2 分析意图 Slot 模型

一次数据分析意图由以下 Slot 构成，分为三个优先级层级：

**必填槽（Required Slots）** — 全部填满才可进入规划阶段

| Slot | 含义 | 示例值 |
|------|------|--------|
| `analysis_subject` | 分析对象（指标/实体） | 集装箱吞吐量、各业务线 |
| `time_range` | 分析的时间范围 | 2024年Q1、上个月 |
| `output_complexity` | 结果期望的复杂程度 | `simple_table` / `chart_text` / `full_report` |

**条件槽（Conditional Slots）** — 依据 `output_complexity` 激活

| Slot | 激活条件 | 含义 |
|------|----------|------|
| `output_format` | complexity = `full_report` | docx / pptx / pdf |
| `analysis_depth.attribution` | complexity ≥ `chart_text` | 是否需要归因分析 |
| `analysis_depth.predictive` | complexity = `full_report` | 是否需要预测分析 |

**可推断槽（Inferable Slots）** — 优先从历史记忆和上下文中自动填充，无需追问

| Slot | 推断来源 | 含义 |
|------|----------|------|
| `time_granularity` | 记忆偏好 → 默认月度 | 数据粒度（日/月/季/年） |
| `domain` | 对话实体识别 | 业务领域 |
| `domain_glossary` | 记忆偏好 | 用户自定义业务术语映射 |

**复杂度识别规则：**

| 复杂度级别 | 判断特征 | 默认输出形式 |
|-----------|----------|-------------|
| `simple_table` | 单一指标查询，无时序比较，无归因需求 | 内联 Markdown 表格 |
| `chart_text` | 含趋势分析、对比分析，需要图表 | HTML 图文混排 |
| `full_report` | 多维分析、预测、战略建议，需完整结论 | DOCX / PPTX / PDF |

#### 4.1.3 感知流程

```
用户输入（含对话历史）
         │
         ▼
  ┌──────────────────────────────────────────────────┐
  │              Slot 填充引擎                         │
  │                                                  │
  │  Step 1：从用户当前输入中提取可识别的 Slot 值       │
  │  Step 2：从本轮对话历史中补充填充                  │
  │  Step 3：从用户记忆偏好中自动填充可推断槽           │
  │  Step 4：根据已填 output_complexity 激活条件槽     │
  │  Step 5：检查所有必填槽 + 已激活条件槽的填充状态   │
  └──────────────────────────────────────────────────┘
         │
         ├── 所有必要槽已填满 ──────────────────→ 输出 StructuredIntent → 进入规划
         │
         └── 存在空槽 ────────────────────────→ 选取优先级最高的空槽，
                                                  生成一条聚焦追问
                                                  （附上已推断的值供用户确认）
                                                       │
                                                       ▼
                                                  等待用户回复 → 回到 Step 1
```

**追问优先级（空槽时按此顺序选取最高优先级）：**

1. `time_range`（最常缺失，且对数据获取影响最大）
2. `analysis_subject`（分析对象不清晰时）
3. `output_complexity`（仅在用户意图模糊、无法自动判断时）
4. `output_format`（仅 full_report 且格式未指明时）
5. `analysis_depth.*`（仅 chart_text/full_report 且深度未指明时）

**关键设计原则：**
- 每次追问只针对一个槽，不合并多个问题
- 追问时必须展示已推断的值（「我理解时间范围为……是否正确？」），给用户一个确认的支点而非从零填写
- 若用户明确表示「按你理解执行」，将所有空槽设为推断值或默认值，直接进入规划
- 记忆偏好填充的槽在规划展示时标注「来自偏好」，用户可在确认规划时修改

#### 4.1.4 结构化意图（Structured Intent）数据结构

```json
{
  "intent_id": "uuid",
  "raw_query": "用户原始输入",
  "analysis_goal": "用一句话综合描述的分析目标",
  "slots": {
    "analysis_subject": {
      "value": ["集装箱吞吐量", "各业务线"],
      "source": "user_input | history | memory | default",
      "confirmed": true
    },
    "time_range": {
      "value": {"start": "2024-01-01", "end": "2024-03-31", "description": "2024年Q1"},
      "source": "user_input",
      "confirmed": true
    },
    "output_complexity": {
      "value": "full_report",
      "source": "user_input",
      "confirmed": true
    },
    "output_format": {
      "value": "pptx",
      "source": "memory",
      "confirmed": false
    },
    "analysis_depth": {
      "value": {"descriptive": true, "attribution": true, "predictive": false},
      "source": "inferred",
      "confirmed": false
    },
    "time_granularity": {
      "value": "monthly",
      "source": "memory",
      "confirmed": false
    },
    "domain": {
      "value": "port_operations",
      "source": "inferred",
      "confirmed": false
    },
    "domain_glossary": {
      "value": {"货量": "throughput_teu"},
      "source": "memory",
      "confirmed": false
    }
  },
  "empty_required_slots": [],
  "clarification_history": [
    {"slot": "time_range", "question": "...", "answer": "...", "round": 1}
  ]
}
```

`source` 字段说明槽值的来源，在规划阶段用于向用户透明展示哪些内容是来自记忆偏好自动填充的，哪些是本轮对话中用户明确提供的。

#### 4.1.5 感知层 Prompt 设计规范

```
【系统角色】
你是一个数据分析意图理解专家，负责从对话历史中识别并填充分析所需的关键信息槽位。

【用户记忆偏好（由系统注入）】
{memory_preferences_summary}
注意：记忆偏好作为推断依据，但本轮对话中用户明确表达的内容具有更高优先级。

【当前 Slot 填充状态（由系统注入）】
{current_slot_status_json}
- 标注为 filled 的槽无需再追问
- 标注为 empty 的必填槽需从本轮用户输入中尝试提取

【任务】
1. 结合用户本轮输入和对话历史，尝试填充所有 empty 状态的槽位
2. 检查填充后是否还存在空的必填槽或已激活的条件槽
3. 如果存在，生成一条追问（见追问格式要求）
4. 如果所有必要槽均已填满，输出完整的结构化意图

【追问格式要求】
- 每次只追问一个槽（选优先级最高的空槽）
- 语气自然，以对话方式提问
- 必须附上你基于已有信息的推断值，供用户确认或纠正
- 示例：「您提到分析吞吐量趋势，我理解时间范围是今年 1-3 月，是否正确？
  如果不是，请告诉我您希望分析的时间段。」

【输出格式】（严格 JSON，无任何 markdown 包裹）
{
  "action": "clarify | proceed",
  "filled_slots": { <新填充或更新的槽位键值> },
  "clarification_question": "<action=clarify 时必填，action=proceed 时为 null>",
  "target_slot": "<本次追问针对的槽名，action=clarify 时必填>",
  "analysis_goal_summary": "<action=proceed 时，一句话汇总分析目标>"
}
```

---

### 4.2 规划层（Planning Layer）

#### 4.2.1 模块职责

接收感知层输出的结构化意图，生成可执行的分析方案（Analysis Plan），包含：数据需求、获取路径、分析步骤、技能调用序列和报告组装逻辑。规划方案对用户透明，支持用户确认和修改。

#### 4.2.2 分析方案（Analysis Plan）数据结构

```json
{
  "plan_id": "uuid",
  "intent_id": "关联的意图 ID",
  "title": "本次分析方案标题",
  "estimated_duration": "预计耗时（秒）",
  "tasks": [
    {
      "task_id": "T001",
      "type": "data_fetch | search | analysis | visualization | report_gen",
      "name": "任务名称",
      "description": "任务描述",
      "depends_on": ["T000"],
      "skill": "所用技能名称",
      "params": {
        "api_endpoint": "...",
        "query": "...",
        "method": "GET"
      },
      "status": "pending | running | done | failed",
      "output_ref": "本任务输出的引用 ID"
    }
  ],
  "report_structure": {
    "sections": [
      {"title": "执行摘要", "content_refs": ["T005.output"]},
      {"title": "数据概况", "content_refs": ["T002.output"]},
      {"title": "趋势分析", "content_refs": ["T003.output", "T004.output"]}
    ],
    "format": "pptx"
  },
  "version": 1,
  "revision_log": []
}
```

#### 4.2.3 规划展示与用户交互

规划方案以**可视化任务清单**的形式呈现给用户，支持：
- 查看每个任务的数据来源和分析逻辑
- 删除/跳过某个任务
- 修改输出格式
- 确认执行或要求调整

**展示示例：**

```
📋 分析方案（共 6 个步骤，预计 4 分钟）

✅ 步骤 1｜获取内部数据
   › 调用港口吞吐量 API，时间范围：2024-01 至 2024-03
   › 数据源：内部数据平台 /api/v1/throughput

✅ 步骤 2｜互联网检索
   › 检索 2024Q1 宏观贸易环境、航运市场动态

✅ 步骤 3｜描述性分析
   › 汇总月度数据，计算环比/同比增长率

✅ 步骤 4｜归因分析
   › 结合外部市场数据，分析吞吐量变化驱动因素

✅ 步骤 5｜可视化
   › 生成折线图（月度趋势）+ 瀑布图（归因分解）

✅ 步骤 6｜报告生成
   › 组装为 PPTX 报告，含封面、摘要、图表与结论

[确认执行]  [修改方案]  [更改格式]
```

#### 4.2.4 动态规划更新机制

执行过程中，若发现以下情况，执行层可触发规划更新：
- 数据 API 返回异常，需切换数据源
- 数据质量问题（缺失率超过阈值），需增加数据清洗步骤
- 分析过程中发现新的有价值的维度，需增加探索任务
- 用户在执行过程中追加需求

更新时自动追加到 `revision_log`，并通知用户规划已更新。

---

### 4.3 执行层（Execution Layer）

#### 4.3.1 模块职责

按照规划方案逐步执行任务，调度合适的技能处理每个步骤，汇总输出结果，并维护执行上下文供报告组装使用。

#### 4.3.2 执行调度逻辑

```
┌─────────────────────────────────────────────┐
│              任务调度器（Task Dispatcher）    │
│                                             │
│  遍历 Plan.tasks（按依赖关系拓扑排序）          │
│       │                                     │
│       ▼                                    │
│  任务类型判断                                 │
│  ├── data_fetch  → 数据接入层（API / 文件）    │
│  ├── search      → 互联网检索技能             │
│  ├── analysis    → 分析技能（描述/归因/预测）  │
│  ├── visualization → 可视化技能              │
│  └── report_gen  → 文档生成技能              │
│       │                                     │
│       ▼                                    │
│  结果写入执行上下文（Execution Context）       │
│  更新任务状态 → 检查依赖 → 触发后续任务        │
└─────────────────────────────────────────────┘
```

#### 4.3.3 执行上下文（Execution Context）

```json
{
  "session_id": "uuid",
  "plan_id": "关联规划 ID",
  "artifacts": {
    "T001.output": {
      "type": "dataframe",
      "rows": 92,
      "columns": ["date", "throughput_teu", "business_line"],
      "preview": "...",
      "storage_ref": "local://artifacts/T001.parquet"
    },
    "T005.output": {
      "type": "chart",
      "chart_type": "line",
      "format": "svg",
      "storage_ref": "local://artifacts/T005.svg"
    }
  },
  "execution_log": [
    {"task_id": "T001", "status": "done", "duration_ms": 1240, "timestamp": "..."}
  ]
}
```

#### 4.3.4 执行过程可视化

用户可在执行过程中实时看到进度：
- 当前执行的步骤（高亮显示）
- 已完成步骤的结果摘要（可展开查看）
- 预计剩余时间
- 中间产物的预览（图表、数据表）

#### 4.3.5 错误处理与恢复策略

| 错误类型 | 处理策略 |
|----------|----------|
| API 请求失败 | 重试 3 次，超时后标记任务失败并通知用户 |
| 数据为空 | 触发规划更新，建议扩大时间范围或更换数据源 |
| 分析技能异常 | 降级为基础 LLM 分析，记录异常到反思模块 |
| 文档生成失败 | 降级为 HTML 格式并提示用户 |

---

### 4.4 反思层（Reflection Layer）

#### 4.4.1 模块职责

在每次分析任务完成后，对整个过程进行系统性总结，提取用户偏好、分析范式和技能表现信息，经用户确认后存储为持久化记忆，用于提升下次分析质量。

#### 4.4.2 反思维度

**维度一：用户偏好萃取**

从本次对话和执行过程中识别：
- 时间粒度偏好（月度/季度/年度）
- 图表风格偏好（折线/柱状/散点）
- 报告格式偏好（PPTX / 简洁 HTML）
- 业务术语习惯（用户特有的指标命名）
- 分析深度偏好（是否喜欢归因分析）

**维度二：分析范式发现**

识别本次分析中形成的可复用分析模板：
- 数据获取路径（API 组合）
- 分析方法链（如：吞吐量分析 → 总量 → 同比 → 业务线拆分 → 归因）
- 报告结构模板

**维度三：技能表现评估**

- 哪些技能表现良好（速度、准确度）
- 哪些技能出现问题（错误类型、失败原因）
- 是否发现可优化的技能配置

#### 4.4.3 反思输出与用户确认流程

```
执行完成
    │
    ▼
自动生成反思摘要（用户可见）
    │
    ▼
展示反思卡片：
┌──────────────────────────────────────────┐
│ 💡 本次分析完成，我记录了以下发现          │
│                                          │
│ 用户偏好：                               │
│ ✔ 您更偏好 PPTX 格式报告                  │
│ ✔ 时间粒度倾向月度对比                    │
│                                          │
│ 可复用分析模板：                          │
│ 📌 港口吞吐量分析模板（已生成）            │
│    包含：API 路径、分析步骤、图表配置       │
│                                          │
│ 技能表现：                               │
│ ⚡ 归因分析技能表现良好                    │
│ ⚠️  预测技能（线性回归）置信度偏低，建议     │
│    下次补充更长时序数据                    │
│                                          │
│ [保存这些偏好]  [部分保存]  [不保存]       │
└──────────────────────────────────────────┘
    │
    ▼
用户确认 → 写入记忆存储层
```

#### 4.4.4 记忆存储结构

所有记忆数据统一存储于 MySQL，技能与模板的检索均采用结构化精确查询，无需向量存储。模板匹配逻辑简单透明、行为可预测，且在企业场景下单用户模板量有限，精确检索完全满足需求。

```json
{
  "user_id": "uuid",
  "preferences": {
    "output_format": "pptx",
    "time_granularity": "monthly",
    "chart_types": ["line", "waterfall"],
    "domain_glossary": {
      "货量": "throughput_teu"
    }
  },
  "templates": [
    {
      "template_id": "tpl_001",
      "name": "港口吞吐量分析",
      "domain": "port_operations",
      "output_complexity": "chart_text",
      "tags": ["throughput", "trend", "attribution"],
      "plan_skeleton": {},
      "usage_count": 3,
      "last_used": "2026-04-13"
    }
  ],
  "skill_configs": {
    "attribution_analysis": {"model": "qwen3-235b", "preferred": true},
    "prediction": {"notes": "需要至少 24 个月数据效果更佳"}
  }
}
```

**模板检索策略（精确匹配，按优先级依次收窄）：**

| 优先级 | 查询条件 | 说明 |
|--------|----------|------|
| 1（精确） | `domain` = 当前领域 AND `output_complexity` = 当前复杂度 | 完全匹配，最相关 |
| 2（宽松） | `domain` = 当前领域（忽略复杂度） | 同领域历史经验 |
| 3（兜底） | 无过滤，按 `usage_count DESC, last_used DESC` | 无领域匹配时参考用户最常用模板 |

结果取 top-3，注入规划层 Prompt 供 LLM 参考。

**MySQL 表结构概览：**

| 表名 | 说明 | 关键字段 |
|------|------|----------|
| `sessions` | 会话记录 | session_id, user_id, state_json, created_at |
| `user_preferences` | 用户偏好键值对 | user_id, key, value (jsonb), updated_at |
| `analysis_templates` | 可复用分析模板 | template_id, user_id, name, domain, output_complexity, tags (text[]), plan_skeleton (jsonb), usage_count, last_used |
| `skill_notes` | 技能表现记录 | skill_id, user_id, notes, performance_score, updated_at |
| `slot_history` | Slot 填充历史（感知层） | session_id, slot_name, value, source, was_corrected, round |



---

## 5. 技能库设计

### 5.1 技能注册机制

每个技能以标准接口注册到技能库，支持动态发现和调用：

```python
class Skill:
    skill_id: str          # 唯一标识
    name: str              # 技能名称
    category: SkillCategory
    description: str       # 面向 LLM 的能力描述（用于规划层选择）
    input_schema: dict     # 输入参数 JSON Schema
    output_schema: dict    # 输出格式 JSON Schema
    
    async def execute(self, params: dict, context: ExecutionContext) -> SkillResult:
        ...
```

### 5.2 内置技能清单

#### 5.2.1 数据获取技能

| 技能 ID | 名称 | 功能说明 |
|---------|------|----------|
| `skill_api_fetch` | API 数据获取 | 调用已配置的数据 API 端点，支持 GET/POST，返回结构化数据 |
| `skill_file_parse` | 文件解析 | 解析用户上传的 CSV / Excel / JSON 文件 |
| `skill_web_search` | 互联网检索 | 基于 Tavily / SerpAPI 检索互联网，返回结构化摘要 |
| `skill_web_fetch` | 网页内容获取 | 获取指定 URL 页面的正文内容 |

#### 5.2.2 分析技能

| 技能 ID | 名称 | 功能说明 |
|---------|------|----------|
| `skill_desc_analysis` | 描述性分析 | 计算均值、中位数、分布、同比/环比增长率，生成统计摘要 |
| `skill_attribution` | 归因分析 | 基于 LLM 结合外部上下文，识别指标变化的驱动因素 |
| `skill_prediction` | 预测分析 | 时序预测（Prophet / ARIMA / LLM 辅助预测） |
| `skill_correlation` | 相关性分析 | 多变量相关性计算与热力图生成 |
| `skill_anomaly` | 异常检测 | 识别时序数据中的异常点并给出原因假设 |
| `skill_segmentation` | 分群分析 | 基于规则或聚类的多维数据分群 |

#### 5.2.3 可视化技能

| 技能 ID | 名称 | 功能说明 |
|---------|------|----------|
| `skill_chart_line` | 折线图 | 生成趋势折线图（ECharts / Plotly） |
| `skill_chart_bar` | 柱状图 | 生成对比柱状图（含分组/堆叠） |
| `skill_chart_waterfall` | 瀑布图 | 用于贡献度拆解与归因可视化 |
| `skill_chart_scatter` | 散点图 | 用于相关性与分布可视化 |
| `skill_chart_geo` | 地理热力图 | 基于地理信息的空间分布可视化 |
| `skill_dashboard` | 仪表盘 | 多图表组合成交互式 HTML 仪表盘 |

#### 5.2.4 报告生成技能

| 技能 ID | 名称 | 功能说明 |
|---------|------|----------|
| `skill_report_html` | HTML 报告 | 生成图文混排的 HTML 分析报告 |
| `skill_report_docx` | Word 报告 | 生成 .docx 格式分析报告（含图表嵌入） |
| `skill_report_pptx` | PPT 报告 | 生成 .pptx 格式演示文稿 |
| `skill_report_pdf` | PDF 报告 | 生成 .pdf 格式正式报告 |
| `skill_summary_gen` | 摘要生成 | 基于 LLM 生成执行摘要与核心结论 |

---

## 6. 数据接入层设计

### 6.1 数据源配置

数据源通过管理界面预先配置，智能体在规划阶段可按需选择：

```json
{
  "datasource_id": "ds_port_ops",
  "name": "港口运营数据平台",
  "type": "rest_api",
  "base_url": "https://internal-api.port.com/v1",
  "auth": {"type": "bearer_token", "token_env": "PORT_API_TOKEN"},
  "endpoints": [
    {
      "endpoint_id": "ep_throughput",
      "path": "/throughput",
      "method": "GET",
      "description": "获取港口集装箱吞吐量数据",
      "params": {
        "start_date": {"type": "date", "required": true},
        "end_date": {"type": "date", "required": true},
        "granularity": {"type": "string", "enum": ["daily", "monthly", "quarterly"]},
        "business_line": {"type": "string", "required": false}
      },
      "response_schema": {
        "data": [{"date": "string", "throughput_teu": "number", "business_line": "string"}]
      }
    }
  ]
}
```

### 6.2 互联网检索集成

检索结果经过标准化处理后纳入分析上下文：

```python
search_result = {
    "query": "2024Q1 全球集装箱航运市场",
    "results": [
        {
            "title": "...",
            "source": "...",
            "published_date": "2024-04-10",
            "snippet": "...",
            "relevance_score": 0.92
        }
    ],
    "synthesized_summary": "LLM 对检索结果的综合摘要"
}
```

---

## 7. 用户体验设计

### 7.1 对话界面设计原则

- **渐进式透明**：感知阶段的 Slot 填充进度对用户可见（以紧凑的状态卡片形式展示已填/待填槽），规划阶段任务清单完整展开
- **可打断**：用户可在任意阶段暂停、修改或取消
- **进度感知**：执行阶段提供实时进度和中间结果预览
- **结果可交互**：报告结果支持追问（「为什么 Q2 下降？」）

### 7.2 Slot 状态卡片（感知阶段新增）

在感知阶段的每条追问消息前，以折叠卡片形式展示当前 Slot 填充状态，帮助用户理解智能体正在确认什么：

```
📋 正在理解您的分析需求
┌────────────────────────────────────────────┐
│ ✅ 分析对象   集装箱吞吐量（各业务线）          │
│ ✅ 分析目标   趋势变化及原因                   │
│ ⬜ 时间范围   未确定                          │  ← 当前追问此槽
│ ✅ 输出形式   图文分析（自动判断）              │
│ 💾 输出格式   PPTX（来自您的偏好）             │  ← 标注记忆来源
└────────────────────────────────────────────┘
```

### 7.3 关键交互状态

| 状态 | 视觉反馈 | 用户可操作 |
|------|----------|-----------|
| 感知/Slot 填充中 | Slot 状态卡片 + 流式追问 | 回答追问、跳过（「按你理解执行」） |
| 规划生成中 | 任务清单逐行展开 | 确认、修改、取消 |
| 执行中 | 步骤进度条 + 中间结果 | 查看详情、暂停 |
| 反思中 | 反思卡片 | 保存偏好、忽略 |
| 完成 | 结果展示 + 下载链接 | 追问、重新分析 |
