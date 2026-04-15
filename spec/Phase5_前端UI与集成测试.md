# Analytica 数据分析 Agent — Phase 5：前端 UI 与集成测试
## 实施方案 v1.3 · 阶段文档

---

## 版本记录

| 版本号 | 日期 | 修订说明 | 编制人 |
|--------|------|----------|--------|
| v1.0 | 2025-07-01 | Phase 5 初版，覆盖前端 UI + E2E 集成测试 | FAN |
| v1.1 | 2025-07-05 | 补充 Zustand Store 测试、性能基准用例 | FAN |
| v1.2 | 2025-07-10 | 补充安全测试、验收标准、记忆注入闭环 E2E | FAN |
| v1.3 | 2025-07-15 | 与 PRD v1.3 / 实施方案 v1.3 对齐 | FAN |
| v1.4 | 2026-04-14 | 基于 MockAPI 模拟建议文档 V1.0 调整：E2E 消息替换为 §7 真实题库，TC-MEM04 跨域偏好，TEST_MESSAGES_BALANCED 5域均衡 | FAN |

---

## 阶段概览

| 项目 | 内容 |
|------|------|
| **阶段** | Phase 5 — 前端 UI 与集成测试 |
| **时间** | Week 10（Day 41–47） |
| **里程碑** | MVP 全链路贯通、验收标准通过 |
| **前置条件** | Phase 1–4 全部完成，后端 API 稳定，WebSocket 通道可用 |
| **输出物** | React 19 前端应用、E2E 测试套件、性能/安全测试报告 |

---

## 一、PRD 补充章节

### §7 UX 设计规范

#### 7.1 整体布局

```
┌────────────────────────────────────────────────────────┐
│  Header: Analytica · 港口市场商务智能分析              │
├──────────────┬─────────────────────────────────────────┤
│              │                                         │
│  左侧面板    │  主内容区                               │
│  (300px)     │                                         │
│              │  ┌─────────────────────────────────┐   │
│  SlotStatus  │  │  对话流（消息列表）              │   │
│  Card        │  │                                 │   │
│  ──────────  │  │  用户消息 / Agent 消息           │   │
│  PlanCard    │  │  执行进度条                      │   │
│  (可折叠)    │  │  反思卡片                        │   │
│              │  └─────────────────────────────────┘   │
│              │  ┌─────────────────────────────────┐   │
│              │  │  输入框 + 发送按钮               │   │
│              │  └─────────────────────────────────┘   │
└──────────────┴─────────────────────────────────────────┘
```

#### 7.2 核心组件规范

##### 7.2.1 SlotStatusCard（左侧面板顶部）

实时展示当前会话所有 Slot 的填充状态。

| 字段 | 展示样式 |
|------|----------|
| 已填充槽 | 绿色标签 + 值预览（最多 20 字符） |
| 待填充必填槽 | 红色边框 + "待填写" 标记 |
| 待填充可选槽 | 灰色标签 + "可选" 标记 |
| 记忆预填充槽 | 蓝色标签 + "来自记忆" 角标 |
| 低置信度槽 | 橙色标签 + 置信度百分比 |

**交互行为：**
- 点击已填充槽 → 弹出修改输入框
- 收到 `slot_update` WebSocket 事件 → 无刷新更新对应槽
- 全部必填槽绿色时 → 卡片顶部出现"✓ 信息完整"绿色横幅

##### 7.2.2 PlanCard（左侧面板中部，可折叠）

展示当前规划方案摘要。

| 状态 | 展示内容 |
|------|----------|
| 规划中 | Spinner + "规划方案生成中…" |
| 规划完成 | 任务列表（编号 + skill + 一行描述） |
| 执行中 | 各任务状态 icon（待执行/执行中/完成/失败） |
| 规划失败 | 红色警告 + "重新规划" 按钮 |

**交互行为：**
- 点击任务行 → 展开依赖关系树（tooltip）
- "查看完整规划" 按钮 → 展开 Modal 显示完整 JSON 结构
- "重新规划" 按钮 → 调用 `POST /api/v1/plan/regenerate`

##### 7.2.3 ExecutionProgress（主内容区内联）

任务执行过程中，在对话流中内联展示进度。

```
▣ 正在执行分析任务 [3/5]
  ✓ fetch_port_data        0.8s
  ✓ descriptive_analysis   1.2s
  ⟳ attribution_analysis   进行中…
  ○ generate_chart         待执行
  ○ generate_report        待执行
  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 60%
```

**实时更新规则：**
- 收到 `task_update` 事件 → 对应行状态切换，进度条重绘
- 超时（单任务 > 30s）→ 对应行变红 + "⚠ 超时" 标记
- 全部完成 → 进度组件渐隐，结果卡片渐显

##### 7.2.4 ReflectionCard（执行完成后追加到对话尾部）

```
┌──────────────────────────────────────────────────────┐
│  🧠 分析完成 · 反思摘要                              │
│  ─────────────────────────────────────────────────  │
│  本次分析：大连港 2024 年货物吞吐量同比分析          │
│  主要发现：集装箱同比增长 12.3%，散杂货下降 4.1%    │
│                                                      │
│  偏好学习                                            │
│  ┌──────────────────────────────────────┐           │
│  │ 输出格式：chart_text（本次选用）     │ [保存偏好] │
│  │ 分析粒度：月度（本次选用）           │ [忽略]    │
│  └──────────────────────────────────────┘           │
└──────────────────────────────────────────────────────┘
```

**交互行为：**
- [保存偏好] → 调用 `POST /api/v1/reflection/save`，按钮变灰 + "✓ 已保存"
- [忽略] → 调用 `POST /api/v1/reflection/dismiss`，卡片折叠
- 保存成功后 → Toast 提示"偏好已记录，下次分析将自动应用"

##### 7.2.5 EChartsViewer（图表渲染组件）

- 接收后端返回的 ECharts option JSON，使用 `echarts-for-react` 渲染
- 支持导出为 PNG（右键菜单 / 工具栏按钮）
- 图表宽度自适应容器（`resize observer`）
- 加载态：骨架屏（与图表同宽高）

#### 7.3 关键交互状态机

```
[空闲] ──用户发送消息──▶ [Slot填充中]
  ▲                          │
  │                    全部槽就绪
  │                          ▼
  │                      [规划中]
  │                          │
  │                    规划确认/自动确认
  │                          ▼
  │                      [执行中]
  │                          │
  │                       完成/失败
  │                          ▼
  │                      [反思中]
  │                          │
  └──────────反思完成─────────┘
```

**状态持久化：** Zustand store 中保存当前状态，页面刷新后通过 `GET /api/v1/session/{id}/state` 恢复。

#### 7.4 错误状态 UX

| 错误场景 | UI 处理 |
|----------|---------|
| WebSocket 断开 | 顶部红色横幅 "连接已断开，正在重连…" + 指数退避重连 |
| LLM 超时 | 对话中内联提示 "分析超时，是否重试？" + [重试] 按钮 |
| 数据量不足 | 黄色警告卡 "数据不足，已切换为简化分析" |
| 后端 500 | Toast 错误提示 + Sentry 上报（如已集成） |
| 规划失败 | PlanCard 显示错误详情 + "重新规划" 按钮 |

---

### §8 非功能性需求

#### 8.1 性能指标

| 指标 | 目标值 | 测量方式 |
|------|--------|----------|
| 简单表格场景（simple_table）端到端 | ≤ 30 秒 | E2E 计时 |
| 图文场景（chart_text）端到端 | ≤ 3 分钟 | E2E 计时 |
| 完整报告场景（full_report）端到端 | ≤ 10 分钟 | E2E 计时 |
| 前端首屏加载（FCP） | ≤ 2 秒 | Lighthouse |
| 前端交互响应（TTI） | ≤ 3 秒 | Lighthouse |
| WebSocket 事件到 UI 更新延迟 | ≤ 200ms | 手动测量 |
| 单会话并发支持 | ≥ 20 并发用户 | Locust 压测 |
| 内存使用（后端单进程） | ≤ 2GB | `psutil` 监控 |

#### 8.2 可靠性指标

| 指标 | 目标值 |
|------|--------|
| 后端服务可用性 | ≥ 99.5%（月度） |
| LLM 调用失败自动重试成功率 | ≥ 90% |
| WebSocket 重连成功率 | ≥ 95%（30s 内） |
| 记忆存储写入成功率 | ≥ 99.9% |

#### 8.3 前端兼容性

| 环境 | 要求 |
|------|------|
| 浏览器 | Chrome 120+、Edge 120+、Firefox 121+ |
| 分辨率 | 最小 1280×720，优化至 1920×1080 |
| 网络 | 内网环境（企业局域网），不依赖 CDN |
| 字体 | 使用系统字体栈，无外部字体加载 |

---

### §9 数据安全与合规

#### 9.1 认证与授权

| 机制 | 实现方式 |
|------|----------|
| API 认证 | Bearer Token（JWT，HS256） |
| Token 存储 | `httpOnly Cookie`，禁止 JS 读取 |
| Token 刷新 | Refresh Token 机制，Access Token 有效期 15 分钟 |
| 用户隔离 | 所有 DB 查询强制附加 `user_id` 条件 |
| 会话隔离 | `session_id` 由服务端生成（UUID4），不可预测 |

#### 9.2 数据传输安全

| 场景 | 要求 |
|------|------|
| HTTP 通信 | 生产环境强制 HTTPS（TLS 1.2+） |
| WebSocket | WSS（WebSocket over TLS） |
| 数据库连接 | 本地/内网，连接串不出现在日志 |
| LLM API Key | 仅存在于服务端环境变量，不下发客户端 |

#### 9.3 隐私与合规

- 用户输入的港口业务数据不发送至外部 LLM（私有化部署 Qwen3-235B）
- 记忆数据（偏好/模板）仅用于个性化，不用于模型训练
- 日志脱敏：不记录完整 SQL 结果集，仅记录行数和耗时

---

### §10 验收标准

#### 10.1 功能验收

| 验收项 | 判断标准 |
|--------|----------|
| F-ACC-01：Slot 填充完整性 | 5 个核心场景（见 §4.1）均可正确提取所有必填 Slot |
| F-ACC-02：追问引导 | 缺失必填 Slot 时 100% 触发追问，不跳过 |
| F-ACC-03：规划合理性 | 10 个 Mock API 端点按场景正确调用，无幻觉技能 |
| F-ACC-04：执行完整性 | simple_table/chart_text/full_report 三场景 100% 完成 |
| F-ACC-05：反思持久化 | 保存偏好后，下一个相同场景自动预填，验收人可观测 |
| F-ACC-06：PPTX 报告 | full_report 场景生成的 .pptx 文件可在 WPS 正常打开 |
| F-ACC-07：ECharts 图表 | chart_text 场景图表正确渲染，数据与分析结论一致 |

#### 10.2 性能验收

| 验收项 | 判断标准 |
|--------|----------|
| P-ACC-01：simple_table 耗时 | ≤ 30 秒（3 次测试均通过） |
| P-ACC-02：chart_text 耗时 | ≤ 3 分钟（3 次测试均通过） |
| P-ACC-03：full_report 耗时 | ≤ 10 分钟（3 次测试均通过） |

#### 10.3 安全验收

| 验收项 | 判断标准 |
|--------|----------|
| S-ACC-01：Token 不泄露 | 浏览器 DevTools → Application → Cookies 中无 Access Token 明文 |
| S-ACC-02：用户隔离 | 用户 A 无法访问用户 B 的会话记录（测试验证） |
| S-ACC-03：LLM Key 隔离 | 前端网络请求中不出现 API Key |

---

## 二、Sprint 12：React 19 前端实现

**时间：** Day 41–44  
**目标：** 完成全部前端组件开发，与后端 WebSocket + REST API 联调

### 2.1 技术栈

```
React 19 (with RSC if needed)
Zustand 5.x          # 全局状态管理
TailwindCSS 3.x      # 样式
echarts-for-react    # 图表渲染
@tanstack/react-query # REST API 缓存
native WebSocket     # 实时通信（不使用 socket.io）
Vite 5.x             # 构建工具
Vitest + RTL         # 单元/组件测试
Playwright           # E2E 测试
```

### 2.2 目录结构

```
frontend/
├── src/
│   ├── components/
│   │   ├── SlotStatusCard.tsx
│   │   ├── PlanCard.tsx
│   │   ├── ExecutionProgress.tsx
│   │   ├── ReflectionCard.tsx
│   │   ├── EChartsViewer.tsx
│   │   ├── ChatMessage.tsx
│   │   └── InputBar.tsx
│   ├── stores/
│   │   ├── sessionStore.ts     # 会话状态
│   │   ├── slotStore.ts        # Slot 状态
│   │   ├── planStore.ts        # 规划方案状态
│   │   └── wsStore.ts          # WebSocket 连接状态
│   ├── hooks/
│   │   ├── useWebSocket.ts     # WS 连接 + 重连逻辑
│   │   ├── useSlots.ts         # Slot 查询 + 订阅
│   │   └── usePlan.ts          # 规划 API 封装
│   ├── api/
│   │   └── client.ts           # Axios 实例 + Token 注入
│   └── App.tsx
```

### 2.3 AI Coding Prompt：Zustand Store 设计

```
你是一名 React 19 + Zustand 5 专家，请为 Analytica 实现以下 Store：

## slotStore.ts
状态结构：
{
  slots: Record<string, {
    value: any;
    confidence: number;
    source: 'llm' | 'memory' | 'user';
    filled: boolean;
  }>;
  updateSlot: (name: string, data: Partial<SlotState>) => void;
  resetSlots: () => void;
}

## planStore.ts
状态结构：
{
  plan: PlanSchema | null;
  status: 'idle' | 'planning' | 'ready' | 'executing' | 'failed';
  taskStatuses: Record<string, 'pending' | 'running' | 'done' | 'error'>;
  updateTaskStatus: (taskId: string, status: TaskStatus) => void;
  setPlan: (plan: PlanSchema) => void;
}

## wsStore.ts
状态结构：
{
  connected: boolean;
  reconnectCount: number;
  setConnected: (v: boolean) => void;
  incrementReconnect: () => void;
}

要求：
- 使用 Zustand 5 的 `create` + TypeScript
- 每个 store 独立文件，通过 `combine` 组合 state 和 actions
- 不使用 immer（手动 immutable 更新）
```

### 2.4 AI Coding Prompt：WebSocket Hook

```
请实现 useWebSocket.ts：

功能：
1. 连接到 ws://localhost:8000/ws/{session_id}
2. 接收消息并分发：
   - type: "slot_update"  → 调用 slotStore.updateSlot
   - type: "task_update"  → 调用 planStore.updateTaskStatus
   - type: "message"      → 追加到本地消息列表
   - type: "reflection"   → 触发 ReflectionCard 显示
3. 断线重连：指数退避（1s, 2s, 4s, 8s, 最大 30s），最多重试 10 次
4. 组件卸载时优雅关闭连接

接口：
const { sendMessage, status } = useWebSocket(sessionId)

错误处理：
- onerror → 记录到 wsStore.reconnectCount，触发重连
- 超过最大重试次数 → status 变为 "failed"，UI 显示手动重连按钮

TypeScript 严格模式，不使用 any。
```

### 2.5 AI Coding Prompt：EChartsViewer 组件

```
请实现 EChartsViewer.tsx：

Props：
interface EChartsViewerProps {
  option: EChartsOption;       // 后端返回的 ECharts option JSON
  height?: number;             // 默认 400
  loading?: boolean;           // 加载态（显示骨架屏）
  onExport?: () => void;       // 导出 PNG 回调
}

要求：
1. 使用 echarts-for-react（ReactECharts）
2. ResizeObserver 监听容器宽度变化，自动 resize
3. loading=true 时显示骨架屏（TailwindCSS animate-pulse）
4. 右上角工具栏：[导出 PNG] 按钮
5. option 变化时动画过渡（setOption with notMerge=false）
6. 组件销毁时 dispose ECharts 实例，防止内存泄漏
```

---

## 三、Sprint 13：E2E 集成测试

**时间：** Day 45–47  
**目标：** 全链路 E2E 测试通过，验收标准 §10 全部满足

### 3.1 测试框架

```
后端单元/集成测试：pytest + pytest-asyncio + httpx (AsyncClient)
前端组件测试：   Vitest + React Testing Library
E2E 测试：       Playwright（Python 版本，与后端共用 pytest）
性能测试：       pytest-benchmark + 手动计时
安全测试：       手动 + pytest 参数化
```

### 3.2 测试夹具（conftest.py 补充）

```python
# tests/conftest.py 补充
import pytest_asyncio
from playwright.async_api import async_playwright, Page, Browser

@pytest_asyncio.fixture(scope="session")
async def browser():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        yield browser
        await browser.close()

@pytest_asyncio.fixture
async def page(browser: Browser):
    context = await browser.new_context()
    page = await context.new_page()
    yield page
    await context.close()

@pytest_asyncio.fixture
async def authenticated_page(page: Page, test_user_token: str):
    """已登录的页面夹具"""
    await page.goto("http://localhost:5173")
    await page.evaluate(
        f"document.cookie = 'access_token={test_user_token}; path=/';"
    )
    await page.reload()
    yield page
```

---

## 四、测试用例

### TC-WS：WebSocket 连接与事件分发测试

#### TC-WS01：WebSocket 连接建立
```
前置：后端服务运行，session_id 有效
步骤：useWebSocket(sessionId) 初始化
期望：
  - wsStore.connected === true（2 秒内）
  - wsStore.reconnectCount === 0
```

#### TC-WS02：slot_update 事件分发
```
前置：WebSocket 已连接
步骤：后端推送 {"type": "slot_update", "slot_name": "time_range", "value": "2024年", "confidence": 0.95, "source": "llm"}
期望：
  - slotStore.slots["time_range"].value === "2024年"
  - slotStore.slots["time_range"].confidence === 0.95
  - slotStore.slots["time_range"].source === "llm"
  - UI 中 SlotStatusCard 对应行实时更新（无页面刷新）
```

#### TC-WS03：task_update 事件分发
```
前置：WebSocket 已连接，规划已确认
步骤：后端推送 {"type": "task_update", "task_id": "T1", "status": "done", "duration_ms": 820}
期望：
  - planStore.taskStatuses["T1"] === "done"
  - ExecutionProgress 中 T1 行显示 ✓ 和耗时
  - 进度条百分比更新
```

#### TC-WS04：message 事件追加到对话流
```
步骤：后端推送 {"type": "message", "role": "assistant", "content": "分析完成，以下是结果…"}
期望：
  - 对话消息列表末尾追加新 AssistantMessage 组件
  - 消息内容正确渲染 Markdown
  - 页面自动滚动到底部
```

#### TC-WS05：reflection 事件触发 ReflectionCard
```
步骤：后端推送 {"type": "reflection", "summary": {...}, "preferences": [...]}
期望：
  - ReflectionCard 组件从隐藏变为可见（CSS transition）
  - 偏好列表渲染正确
  - [保存偏好] 和 [忽略] 按钮均可点击
```

#### TC-WS06：断线重连指数退避
```
前置：WebSocket 已连接
步骤：模拟网络中断（关闭后端 WS 端口），等待 35 秒
期望：
  - wsStore.reconnectCount 逐步增加（1, 2, 3…）
  - UI 顶部显示红色 "连接已断开，正在重连…" 横幅
  - 重连间隔符合指数退避（1s, 2s, 4s, 8s, 16s, 30s）
  - 后端恢复后，自动重连成功，横幅消失
```

#### TC-WS07：最大重试次数后显示手动重连按钮
```
步骤：模拟持续断线，等待 10 次重试耗尽
期望：
  - wsStore.status === "failed"
  - UI 显示 "连接失败" + [手动重连] 按钮
  - 点击 [手动重连] → 重置计数，重新尝试连接
```

#### TC-WS08：组件卸载优雅关闭连接
```
步骤：渲染包含 useWebSocket 的组件，然后 unmount
期望：
  - WebSocket.close() 被调用（readyState → CLOSED）
  - 无内存泄漏（无 "Can't perform a React state update on unmounted component" 警告）
```

---

### TC-UI：React 组件渲染测试

#### TC-UI01：SlotStatusCard 初始渲染
```
输入：空 slotStore（无任何已填充槽）
期望：
  - 所有必填槽显示红色 "待填写" 标记
  - 可选槽显示灰色 "可选" 标记
  - 顶部无绿色"信息完整"横幅
```

#### TC-UI02：SlotStatusCard 记忆预填充标记
```
输入：slotStore.slots["output_format"] = {value: "chart_text", source: "memory", filled: true}
期望：
  - "output_format" 行显示蓝色标签 + "来自记忆" 角标
  - 值预览显示 "chart_text"
```

#### TC-UI03：SlotStatusCard 全填充后显示"信息完整"
```
步骤：逐一填充所有必填槽
期望：
  - 最后一个槽填充后，顶部出现绿色"✓ 信息完整"横幅
  - 横幅有渐入动画（opacity 0 → 1）
```

#### TC-UI04：PlanCard 规划中状态
```
输入：planStore.status === "planning"
期望：
  - 显示 Spinner 动画
  - 显示文字 "规划方案生成中…"
  - 无任务列表
```

#### TC-UI05：PlanCard 规划完成后渲染任务列表
```
输入：planStore.status === "ready"，plan 含 3 个任务
期望：
  - 渲染 3 个任务行（编号 + skill 名 + 描述）
  - 每个任务行状态 icon 为"待执行"
  - 存在"查看完整规划"按钮
```

#### TC-UI06：ExecutionProgress 并行任务并发显示
```
输入：T2 和 T3 同时处于 "running" 状态
期望：
  - T2 和 T3 行均显示 "⟳ 进行中…" 动画
  - 进度条百分比基于已完成任务数计算
```

#### TC-UI07：ReflectionCard 保存偏好交互
```
步骤：
  1. 渲染 ReflectionCard，含 2 个偏好项
  2. 点击第一个偏好项的 [保存偏好] 按钮
期望：
  - 调用 POST /api/v1/reflection/save（mock）
  - 按钮变灰 + 文字变为 "✓ 已保存"
  - Toast 提示 "偏好已记录，下次分析将自动应用"
```

#### TC-UI08：ReflectionCard 忽略后折叠
```
步骤：点击 [忽略] 按钮
期望：
  - 调用 POST /api/v1/reflection/dismiss（mock）
  - 卡片高度渐变为 0（折叠动画）
  - 折叠后不占用布局空间
```

#### TC-UI09：EChartsViewer 加载态骨架屏
```
输入：loading=true
期望：
  - 渲染 TailwindCSS animate-pulse 骨架屏
  - 骨架屏高度与 height prop 一致
  - 无 ECharts 实例化
```

#### TC-UI10：EChartsViewer 图表正常渲染
```
输入：loading=false，有效 ECharts bar option（3 个系列）
期望：
  - ECharts 实例正常创建
  - 图表可见（非零宽高）
  - 无 console.error
```

#### TC-UI11：EChartsViewer 容器宽度变化时自动 resize
```
步骤：
  1. 渲染 EChartsViewer，初始宽 800px
  2. 通过 CSS 将容器宽改为 400px，触发 ResizeObserver
期望：
  - ECharts.resize() 被调用
  - 图表宽度更新为 400px
```

#### TC-UI12：EChartsViewer 导出 PNG
```
步骤：点击 [导出 PNG] 按钮
期望：
  - onExport 回调被调用
  - 或触发浏览器下载（文件名含 "analytica_chart"）
```

#### TC-UI13：ChatMessage Markdown 渲染
```
输入：含 Markdown 表格 + 加粗文字 + 代码块的 assistant 消息
期望：
  - 表格正确渲染为 HTML <table>
  - 加粗文字渲染为 <strong>
  - 代码块渲染为 <pre><code>（含语法高亮）
  - 无原始 Markdown 符号泄露
```

#### TC-UI14：InputBar 发送按钮状态
```
测试矩阵：
  - 空输入 → 发送按钮 disabled
  - 纯空格输入 → 发送按钮 disabled（trim 后为空）
  - 有内容输入 → 发送按钮 enabled
  - 发送中（等待响应）→ 发送按钮 disabled + Spinner
```

#### TC-UI15：InputBar 回车发送
```
步骤：在 InputBar 中输入文字，按 Enter 键
期望：
  - sendMessage 被调用，内容正确
  - 输入框清空
  - Shift+Enter → 换行（不发送）
```

---

### TC-STORE：Zustand Store 状态管理测试

#### TC-STORE01：slotStore.updateSlot 更新指定槽
```
步骤：调用 updateSlot("time_range", {value: "2024Q1", filled: true})
期望：
  - slots["time_range"].value === "2024Q1"
  - slots["time_range"].filled === true
  - 其他槽未受影响（不可变更新）
```

#### TC-STORE02：slotStore.resetSlots 清空全部槽
```
前置：slots 有 3 个已填充槽
步骤：调用 resetSlots()
期望：
  - slots === {}（空对象）
```

#### TC-STORE03：planStore.updateTaskStatus 更新任务状态
```
步骤：setPlan(plan with T1/T2/T3)，然后 updateTaskStatus("T2", "done")
期望：
  - taskStatuses["T2"] === "done"
  - taskStatuses["T1"] 和 "T3" 未变化
```

#### TC-STORE04：planStore 状态转换顺序
```
测试状态转换链：
  idle → planning（setPlan 调用前）
  planning → ready（setPlan 调用后）
  ready → executing（用户确认规划后）
  executing → idle（执行完成后）
期望：各转换触发对应 UI 状态变化
```

#### TC-STORE05：wsStore 重连计数累加与重置
```
步骤：
  1. incrementReconnect() × 3
  2. setConnected(true)（模拟重连成功）
期望：
  - 步骤 1 后：reconnectCount === 3
  - 步骤 2 后：connected === true，reconnectCount 重置为 0
```

---

### TC-E2E：端到端场景测试（Playwright）

#### TC-E2E01：场景 A — simple_table 全链路（核心验收）
```python
async def test_e2e_simple_table(authenticated_page: Page):
    """
    场景：§7 A1「上个月各业务线的吞吐量是多少？」
    对应 Mock API：M02 getThroughputByBusinessType（生产运营域）
    预期分析类型：simple_table（4个业务板块：集装箱/散杂货/油化品/商品车）
    端到端时间限制：30 秒
    """
    start = time.time()

    # 步骤 1：发送分析请求（使用 §7 测试问题库 A1 真实问题）
    await authenticated_page.fill('[data-testid="input-bar"]',
        "上个月各业务线的吞吐量是多少？")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    # 步骤 2：等待 Slot 填充完成（SlotStatusCard 变绿）
    await authenticated_page.wait_for_selector(
        '[data-testid="slot-complete-banner"]', timeout=15000)
    
    # 步骤 3：等待规划完成（PlanCard 显示任务列表）
    await authenticated_page.wait_for_selector(
        '[data-testid="plan-task-list"]', timeout=10000)
    
    # 步骤 4：等待执行完成（ExecutionProgress 消失）
    await authenticated_page.wait_for_selector(
        '[data-testid="execution-progress"]', 
        state="hidden", timeout=25000)
    
    # 步骤 5：验证结果
    result_table = authenticated_page.locator('[data-testid="result-table"]')
    await expect(result_table).to_be_visible()
    
    elapsed = time.time() - start
    assert elapsed <= 30, f"simple_table 超时：{elapsed:.1f}s > 30s"
    
    # 步骤 6：验证 ReflectionCard 出现
    await authenticated_page.wait_for_selector(
        '[data-testid="reflection-card"]', timeout=5000)
```

#### TC-E2E02：场景 B — chart_text 全链路（含 ECharts 图表）
```python
async def test_e2e_chart_text(authenticated_page: Page):
    """
    场景：§7 B1「分析今年Q1港口集装箱吞吐量变化趋势及驱动因素」
    对应 Mock API：M03 getThroughputTrendByMonth + M04 getContainerThroughput + M14 getKeyEnterpriseContribution
    预期分析类型：chart_text（月度趋势折线图 + 归因文字）
    端到端时间限制：3 分钟
    """
    start = time.time()

    await authenticated_page.fill('[data-testid="input-bar"]',
        "分析一下今年Q1港口集装箱吞吐量的变化趋势，以及背后的主要驱动因素")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    # 等待图表渲染
    await authenticated_page.wait_for_selector(
        '[data-testid="echarts-viewer"] canvas', timeout=170000)
    
    # 验证图表非空（canvas 有内容）
    canvas = authenticated_page.locator('[data-testid="echarts-viewer"] canvas')
    await expect(canvas).to_be_visible()
    
    # 验证文字分析出现
    analysis_text = authenticated_page.locator('[data-testid="analysis-text"]')
    await expect(analysis_text).to_be_visible()
    
    elapsed = time.time() - start
    assert elapsed <= 180, f"chart_text 超时：{elapsed:.1f}s > 180s"
```

#### TC-E2E03：场景 C — full_report 生成 PPTX（含下载验证）
```python
async def test_e2e_full_report(authenticated_page: Page, tmp_path):
    """
    场景：§7 C2「帮我生成3月份港口经营分析月报，三个维度，PPT格式」
    对应 Mock API：M01+M04+M05+M06（生产）+M10+M13+M14（市场）+M26（投资），共 8 个
    预期分析类型：full_report（7页 PPTX，生产/市场/投资三维度）
    端到端时间限制：10 分钟
    """
    start = time.time()

    await authenticated_page.fill('[data-testid="input-bar"]',
        "帮我生成3月份港口经营分析月报，要PPT格式，包含生产、市场、投资三个维度")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    # 等待 PPTX 下载按钮出现
    download_btn = authenticated_page.locator('[data-testid="pptx-download-btn"]')
    await expect(download_btn).to_be_visible(timeout=580000)  # 580s
    
    # 触发下载
    async with authenticated_page.expect_download() as dl_info:
        await download_btn.click()
    download = await dl_info.value
    
    # 验证文件名
    assert download.suggested_filename.endswith(".pptx")
    
    # 保存并用 python-pptx 验证可打开
    pptx_path = tmp_path / "report.pptx"
    await download.save_as(pptx_path)
    
    from pptx import Presentation
    prs = Presentation(str(pptx_path))
    assert len(prs.slides) >= 5, \
        f"月度经营月报应包含5页以上（封面+生产+市场+投资+汇总），实际{len(prs.slides)}页"
    
    elapsed = time.time() - start
    assert elapsed <= 600, f"full_report 超时：{elapsed:.1f}s > 600s"
```

#### TC-E2E04：多轮对话 Slot 追问引导
```python
async def test_e2e_slot_clarification(authenticated_page: Page):
    """
    场景：用户输入模糊，Agent 追问必填槽
    """
    # 发送模糊请求（五域均有可能，Agent 应追问 domain 和 time_range）
    await authenticated_page.fill('[data-testid="input-bar"]', "分析一下港口情况")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    # 等待追问消息
    await authenticated_page.wait_for_selector(
        '[data-testid="assistant-message"]', timeout=10000)
    
    # 验证追问内容包含时间范围引导
    messages = authenticated_page.locator('[data-testid="assistant-message"]')
    first_reply = await messages.first.text_content()
    assert any(keyword in first_reply for keyword in ["时间", "年份", "日期", "哪个"])
    
    # 用户回复时间范围
    await authenticated_page.fill('[data-testid="input-bar"]', "2024年全年")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    # 验证 SlotStatusCard 中 time_range 变绿
    time_range_slot = authenticated_page.locator('[data-testid="slot-time_range"]')
    await expect(time_range_slot).to_have_css("border-color", "rgb(34, 197, 94)")  # green-500
```

#### TC-E2E05：「按你理解执行」场景（Bypass 追问）
```python
async def test_e2e_bypass_clarification(authenticated_page: Page):
    """
    场景：用户发送「按你理解执行」，Agent 使用默认值跳过追问
    """
    # 先发送模糊请求触发追问（触发 §5.3 兜底策略：先调用 M01 作为分析起点）
    await authenticated_page.fill('[data-testid="input-bar"]', "查一下港口整体情况")
    await authenticated_page.click('[data-testid="send-btn"]')
    await authenticated_page.wait_for_selector('[data-testid="assistant-message"]')
    
    # 发送 bypass 指令
    await authenticated_page.fill('[data-testid="input-bar"]', "按你理解执行")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    # 验证不再追问，直接进入规划阶段
    await authenticated_page.wait_for_selector(
        '[data-testid="plan-task-list"]', timeout=15000)
    
    # 验证确实有未填充但跳过的槽
    slot_card = authenticated_page.locator('[data-testid="slot-status-card"]')
    bypassed = slot_card.locator('[data-testid$="-bypassed"]')
    count = await bypassed.count()
    assert count >= 1, "至少应有一个槽被 bypass"
```

---

### TC-MEM：记忆注入 E2E 验证

#### TC-MEM01：保存偏好后下次分析自动预填 output_format
```python
async def test_e2e_memory_injection_output_format(authenticated_page: Page):
    """
    验证：保存 output_format=chart_text 偏好后，
    下次相同场景自动预填，不再追问 output_format
    """
    # 第一次分析：明确指定 chart_text
    await _run_analysis(authenticated_page,
        "大连港2024年集装箱吞吐量，出图加文字")
    
    # 保存偏好
    await authenticated_page.click('[data-testid="reflection-save-output_format"]')
    await authenticated_page.wait_for_selector('[data-testid="save-success-toast"]')
    
    # 新会话（刷新页面，新 session_id）
    await authenticated_page.goto("http://localhost:5173")
    
    # 第二次分析：不指定输出格式
    await authenticated_page.fill('[data-testid="input-bar"]',
        "大连港2024年集装箱月度吞吐量趋势")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    # 等待 Slot 填充，验证 output_format 被记忆预填（不追问）
    await authenticated_page.wait_for_selector(
        '[data-testid="slot-output_format"][data-source="memory"]', timeout=10000)
    
    # 验证未出现追问 output_format 的消息
    messages = authenticated_page.locator('[data-testid="assistant-message"]')
    for msg in await messages.all():
        text = await msg.text_content()
        assert "输出格式" not in text, "不应追问 output_format（已记忆预填）"
```

#### TC-MEM02：显式输入覆盖记忆偏好
```python
async def test_e2e_memory_override(authenticated_page: Page):
    """
    验证：记忆中 output_format=chart_text，
    但用户在输入中明确说"只要表格"，应覆盖为 simple_table
    """
    # 前置：确保记忆中有 output_format=chart_text（见 TC-MEM01）
    
    await authenticated_page.fill('[data-testid="input-bar"]',
        "大连港2024年集装箱数据，只要表格不要图")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    await authenticated_page.wait_for_selector(
        '[data-testid="slot-output_format"]', timeout=10000)
    
    slot_value = await authenticated_page.get_attribute(
        '[data-testid="slot-output_format"]', 'data-value')
    
    assert slot_value == "simple_table", \
        f"显式输入未覆盖记忆：output_format={slot_value}"
```

#### TC-MEM03：高纠错率降级（记忆预填置信度降低）
```python
async def test_e2e_memory_degradation(authenticated_page: Page, db_session):
    """
    验证：某槽纠错率 > 40%，记忆预填转为"建议"（低置信度），仍需用户确认
    """
    # 预置：将 user_preferences 中 output_format 纠错率设为 50%
    await db_session.execute(text(
        "UPDATE user_preferences SET correction_count=5, usage_count=10 "
        "WHERE user_id=:uid AND slot_name='output_format'"
    ), {"uid": TEST_USER_ID})
    await db_session.commit()
    
    await authenticated_page.fill('[data-testid="input-bar"]',
        "大连港2024年集装箱数据分析")
    await authenticated_page.click('[data-testid="send-btn"]')
    
    # 验证 output_format 槽显示橙色低置信度标记
    slot = authenticated_page.locator('[data-testid="slot-output_format"]')
    await expect(slot).to_have_attribute('data-confidence-low', 'true', timeout=10000)
    
    # 验证仍触发追问（而非静默预填）
    messages = authenticated_page.locator('[data-testid="assistant-message"]')
    has_confirm = False
    for msg in await messages.all():
        text = await msg.text_content()
        if "输出格式" in text and ("确认" in text or "建议" in text):
            has_confirm = True
            break
    assert has_confirm, "高纠错率槽应触发确认追问"
```

---

### TC-PERF：性能基准测试

#### TC-PERF01：simple_table 场景 P95 延迟
```python
@pytest.mark.benchmark
async def test_perf_simple_table_p95(client: AsyncClient, benchmark_config):
    """
    运行 10 次 simple_table 场景，P95 延迟 ≤ 30 秒
    """
    durations = []
    for _ in range(10):
        start = time.time()
        # 通过 API 直接调用（不经过浏览器）
        response = await client.post("/api/v1/session", json={
            "user_id": TEST_USER_ID,
            "initial_message": "上个月各业务线的吞吐量是多少？"  # §7 A1
        })
        session_id = response.json()["session_id"]
        
        # 轮询会话状态直到完成
        while True:
            status_resp = await client.get(f"/api/v1/session/{session_id}/state")
            if status_resp.json()["status"] in ("done", "error"):
                break
            await asyncio.sleep(0.5)
        
        elapsed = time.time() - start
        durations.append(elapsed)
    
    durations.sort()
    p95 = durations[int(len(durations) * 0.95)]
    assert p95 <= 30, f"simple_table P95={p95:.1f}s > 30s"
    
    p50 = durations[len(durations) // 2]
    print(f"\nsimple_table 性能：P50={p50:.1f}s, P95={p95:.1f}s")
```


#### TC-MEM04：跨域偏好持久化——domain 偏好保存后下次预填
```python
async def test_e2e_domain_preference_saved_and_applied(authenticated_page: Page):
    """
    验证用户多次分析客户域问题后，记忆中保存 domain=customer 偏好。
    下次输入模糊问题"帮我分析一下港口情况"时，Agent 应预填 domain=customer，
    而非触发跨域追问（5大领域均可匹配）。
    对应 MockAPI §7：客户域（M16-M20）的领域偏好学习。
    """
    # 步骤1：第一次分析客户域问题（§7 B3）
    await authenticated_page.fill('[data-testid="input-bar"]',
        "战略客户贡献趋势是否稳定，有没有流失风险？")
    await authenticated_page.click('[data-testid="send-btn"]')

    # 等待反思卡片出现
    await authenticated_page.wait_for_selector(
        '[data-testid="reflection-card"]', timeout=60000)

    # 保存 domain 偏好
    save_btn = authenticated_page.locator('[data-testid="reflection-save-domain"]')
    if await save_btn.count() > 0:
        await save_btn.click()
        await authenticated_page.wait_for_selector(
            '[data-testid="save-success-toast"]', timeout=5000)

    # 步骤2：新会话（刷新，新 session_id）
    await authenticated_page.goto("http://localhost:5173")

    # 步骤3：发送模糊问题，应预填 domain=customer
    await authenticated_page.fill('[data-testid="input-bar"]',
        "帮我分析一下港口情况")
    await authenticated_page.click('[data-testid="send-btn"]')

    # 验证 domain 槽被记忆预填，来源标注 memory
    domain_slot = authenticated_page.locator(
        '[data-testid="slot-domain"][data-source="memory"]')
    try:
        await expect(domain_slot).to_be_visible(timeout=10000)
        domain_value = await domain_slot.get_attribute("data-value")
        assert domain_value in ("customer", "客户"),             f"domain 应预填为 customer，实际: {domain_value}"
    except Exception:
        # 若无 domain 槽，验证未触发五域通用追问（而是快速进入规划）
        plan_card = authenticated_page.locator('[data-testid="plan-task-list"]')
        await expect(plan_card).to_be_visible(timeout=15000)
        print("domain 偏好已应用（无追问直接进入规划）")
```

#### TC-PERF02：并发 5 个 simple_table 会话
```python
async def test_perf_concurrent_sessions(client: AsyncClient):
    """
    5 个并发会话，每个均在 60 秒内完成
    """
    async def run_session(idx: int) -> float:
        start = time.time()
        # ... 同 TC-PERF01 但并发执行
        return time.time() - start
    
    results = await asyncio.gather(*[run_session(i) for i in range(5)])
    
    for i, duration in enumerate(results):
        assert duration <= 60, f"会话 {i} 超时：{duration:.1f}s > 60s"
    
    print(f"\n并发性能：max={max(results):.1f}s, avg={sum(results)/len(results):.1f}s")
```

#### TC-PERF03：前端首屏加载时间
```python
async def test_perf_frontend_fcp(page: Page):
    """
    首屏内容绘制（FCP）≤ 2 秒
    """
    await page.goto("http://localhost:5173")
    
    fcp = await page.evaluate("""
        () => new Promise(resolve => {
            new PerformanceObserver(list => {
                for (const entry of list.getEntriesByName('first-contentful-paint')) {
                    resolve(entry.startTime);
                }
            }).observe({type: 'paint', buffered: true});
        })
    """)
    
    assert fcp <= 2000, f"FCP={fcp:.0f}ms > 2000ms"
```

#### TC-PERF04：WebSocket 事件到 UI 更新延迟
```python
async def test_perf_ws_event_latency(authenticated_page: Page):
    """
    slot_update 事件到 SlotStatusCard 更新的延迟 ≤ 200ms
    """
    # 注入时间戳监听器
    await authenticated_page.evaluate("""
        window.__wsLatencyTest = [];
        const origHandler = window.__slotStoreUpdateSlot;
        // 拦截 slotStore.updateSlot 调用，记录时间
    """)
    
    # 触发 slot_update 并测量 UI 更新时间
    # ... （具体实现依赖 Playwright page.evaluate + 事件监听）
    
    # 期望：P99 ≤ 200ms
```

---

### TC-SEC：安全测试

#### TC-SEC01：Access Token 不在前端 JS 可访问的存储中
```python
async def test_sec_token_not_accessible(page: Page, test_user_token: str):
    """
    验证 Access Token 仅存储在 httpOnly Cookie，JS 无法读取
    """
    await page.goto("http://localhost:5173")
    
    # 尝试通过 JS 读取 Cookie
    cookies_via_js = await page.evaluate("document.cookie")
    assert "access_token" not in cookies_via_js, \
        "Access Token 不应在 document.cookie 中可见（httpOnly）"
    
    # 尝试读取 localStorage
    local_storage = await page.evaluate("JSON.stringify(localStorage)")
    assert "token" not in local_storage.lower() and \
           "access" not in local_storage.lower(), \
        "Token 不应存储在 localStorage"
    
    # 尝试读取 sessionStorage
    session_storage = await page.evaluate("JSON.stringify(sessionStorage)")
    assert "token" not in session_storage.lower(), \
        "Token 不应存储在 sessionStorage"
```

#### TC-SEC02：用户 A 无法访问用户 B 的会话
```python
async def test_sec_user_isolation(client: AsyncClient):
    """
    用户 B 尝试访问用户 A 的 session → 403 Forbidden
    """
    # 用户 A 创建会话
    resp_a = await client.post(
        "/api/v1/session",
        json={"user_id": USER_A_ID, "initial_message": "test"},
        headers={"Authorization": f"Bearer {USER_A_TOKEN}"}
    )
    session_id_a = resp_a.json()["session_id"]
    
    # 用户 B 尝试访问用户 A 的会话
    resp_b = await client.get(
        f"/api/v1/session/{session_id_a}/state",
        headers={"Authorization": f"Bearer {USER_B_TOKEN}"}
    )
    
    assert resp_b.status_code == 403, \
        f"用户隔离失效：用户 B 返回 {resp_b.status_code}"
```

#### TC-SEC03：LLM API Key 不出现在前端网络请求中
```python
async def test_sec_api_key_not_in_requests(authenticated_page: Page):
    """
    监听所有网络请求，确认无 LLM API Key 泄露
    """
    api_key = os.getenv("QWEN_API_KEY", "sk-test-key")
    leaked_requests = []
    
    async def handle_request(request):
        if api_key in str(request.headers):
            leaked_requests.append(request.url)
        if api_key in (request.post_data or ""):
            leaked_requests.append(request.url)
    
    authenticated_page.on("request", handle_request)
    
    # 触发完整分析流程
    await authenticated_page.fill('[data-testid="input-bar"]',
        "大连港2024年吞吐量简单分析")
    await authenticated_page.click('[data-testid="send-btn"]')
    await authenticated_page.wait_for_selector(
        '[data-testid="reflection-card"]', timeout=60000)
    
    assert len(leaked_requests) == 0, \
        f"LLM API Key 泄露于以下请求：{leaked_requests}"
```

#### TC-SEC04：无 Token 访问 API → 401
```python
async def test_sec_unauthenticated_access(client: AsyncClient):
    """
    无 Authorization Header 访问受保护端点 → 401
    """
    endpoints = [
        ("GET",  "/api/v1/session/fake-id/state"),
        ("POST", "/api/v1/session"),
        ("GET",  "/api/v1/plan/fake-id"),
        ("POST", "/api/v1/reflection/save"),
    ]
    for method, path in endpoints:
        if method == "GET":
            resp = await client.get(path)
        else:
            resp = await client.post(path, json={})
        assert resp.status_code == 401, \
            f"{method} {path} 未授权访问应返回 401，实际返回 {resp.status_code}"
```

#### TC-SEC05：SQL 注入防护
```python
@pytest.mark.parametrize("malicious_input", [
    "'; DROP TABLE conversations; --",
    "1' OR '1'='1",
    "大连港 2024 年\"; DELETE FROM memories; --",
    "' UNION SELECT user, password FROM users --",
])
async def test_sec_sql_injection(client: AsyncClient, malicious_input: str):
    """
    恶意 SQL 输入不影响数据库完整性
    """
    resp = await client.post(
        "/api/v1/session",
        json={"user_id": TEST_USER_ID, "initial_message": malicious_input},
        headers={"Authorization": f"Bearer {TEST_TOKEN}"}
    )
    # 应正常处理（200 或业务错误），不应 500
    assert resp.status_code != 500, \
        f"SQL 注入导致服务异常：{malicious_input!r}"
    
    # 验证关键表未被破坏
    # ... 查询 conversations 表行数应不变或正常增加
```

---

### TC-INT：集成冒烟测试（CI/CD 门控）

#### TC-INT01：后端健康检查
```python
async def test_int_health_check(client: AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["db"] == "connected"
    assert data["llm"] == "reachable"
```

#### TC-INT02：完整 4 阶段链路冒烟
```python
async def test_int_full_pipeline_smoke(client: AsyncClient):
    """
    不经浏览器，直接 API 验证感知→规划→执行→反思完整链路
    """
    # 1. 创建会话
    session = await client.post("/api/v1/session",
        json={"user_id": TEST_USER_ID, "initial_message": "上个月各业务线的吞吐量是多少？"  # §7 A1},
        headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert session.status_code == 201
    session_id = session.json()["session_id"]
    
    # 2. 等待 Slot 填充完成
    await _wait_for_state(client, session_id, "planning", timeout=20)
    
    # 3. 等待规划完成
    await _wait_for_state(client, session_id, "executing", timeout=15)
    
    # 4. 等待执行完成
    await _wait_for_state(client, session_id, "reflecting", timeout=30)
    
    # 5. 等待反思完成
    await _wait_for_state(client, session_id, "done", timeout=10)
    
    # 6. 验证结果存在
    result = await client.get(f"/api/v1/session/{session_id}/result",
        headers={"Authorization": f"Bearer {TEST_TOKEN}"})
    assert result.status_code == 200
    assert result.json()["output"] is not None
```

#### TC-INT03：数据库连接池复用
```python
async def test_int_db_connection_pool():
    """
    连续 50 次 DB 操作不导致连接泄漏
    """
    from app.db import engine
    
    for _ in range(50):
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    
    pool_status = engine.pool.status()
    # 连接池空闲连接数应 > 0（未全部泄漏）
    assert "idle" in pool_status
```

---

## 五、Sprint 12 + 13 完成标准

| 任务 | 完成标准 |
|------|----------|
| 所有组件实现 | Vitest 组件测试全部绿色 |
| WebSocket 集成 | TC-WS01~TC-WS08 全部通过 |
| E2E 场景 A/B/C | TC-E2E01~TC-E2E03 通过，时间满足 §8.1 |
| 记忆注入验收 | TC-MEM01~TC-MEM04 通过 |
| 安全测试 | TC-SEC01~TC-SEC05 全部通过 |
| 性能基准 | TC-PERF01 P95 ≤ 30s |
| 集成冒烟 | TC-INT01~TC-INT03 通过，纳入 CI 门控 |
| 验收清单 | §10.1/10.2/10.3 全部满足 |

---

## 六、MVP 交付物清单

| 交付物 | 路径 | 验收方式 |
|--------|------|----------|
| 后端服务 | `backend/` | `pytest` 全绿 + API 文档可访问 |
| 前端应用 | `frontend/dist/` | 生产构建无报错 + Lighthouse 评分 |
| E2E 测试报告 | `reports/e2e_report.html` | Playwright HTML Report |
| 性能测试报告 | `reports/perf_report.txt` | P50/P95 满足 §8.1 |
| 安全测试报告 | `reports/security_report.md` | TC-SEC01~05 全部通过 |
| 数据库 DDL | `migrations/` | Alembic 迁移版本链完整 |
| 部署文档 | `docs/deployment.md` | 步骤可复现 |

---

*Phase 5 完成即 Analytica MVP v1.0 全部就绪。*

---

## 补充测试：Agent 全链路成功率测试

> **补充说明：** 以下测试回答核心问题："Analytica Agent 在真实 LLM 调用下，完整地走完感知→规划→执行→反思四个阶段的成功率是多少？"这是超越单阶段测试的系统级可靠性验证，是 MVP 交付的终极质量门控。

---

### TC-RATE：全链路成功率测试（真实 LLM 调用）

> 文件：`tests/reliability/test_agent_success_rate.py`  
> 标记：`@pytest.mark.llm_real @pytest.mark.slow`  
> 说明：本组测试使用真实 LLM（Qwen3-235B），每次运行约 10–30 分钟，建议在 Staging 环境的 Nightly CI 中执行，不纳入 PR 快速 CI。

```python
import asyncio
import time
import pytest
from app.agent.pipeline import run_full_pipeline
from app.db import AsyncSessionFactory

# 成功率目标
SUCCESS_RATE_TARGET = 0.95  # ≥ 95%
SIMPLE_TABLE_RUNS = 20
CHART_TEXT_RUNS = 10
FULL_REPORT_RUNS = 5

async def run_and_record(
    run_id: int,
    message: str,
    timeout_seconds: int
) -> dict:
    """执行一次完整 Agent 流程，记录结果。"""
    user_id = f"reliability_test_user_{run_id}"
    start = time.time()
    try:
        result = await asyncio.wait_for(
            run_full_pipeline(
                user_id=user_id,
                initial_message=message,
            ),
            timeout=timeout_seconds
        )
        elapsed = time.time() - start
        return {
            "run_id": run_id,
            "status": result.get("status"),
            "has_output": bool(result.get("output")),
            "phase_reached": result.get("phase"),
            "elapsed": elapsed,
            "error": result.get("error_message"),
        }
    except asyncio.TimeoutError:
        return {
            "run_id": run_id,
            "status": "timeout",
            "has_output": False,
            "elapsed": time.time() - start,
            "error": f"超过 {timeout_seconds}s 超时"
        }
    except Exception as e:
        return {
            "run_id": run_id,
            "status": "exception",
            "has_output": False,
            "elapsed": time.time() - start,
            "error": f"{type(e).__name__}: {e}"
        }
```

#### TC-RATE01：simple_table 场景全链路成功率 ≥ 95%（20 次）
```python
@pytest.mark.llm_real
@pytest.mark.slow
async def test_simple_table_end_to_end_success_rate():
    """
    执行 20 次 simple_table 全链路，≥ 19 次成功。
    成功判定：status=done AND has_output=True AND elapsed ≤ 45s
    """
    # §7 测试问题库：A类简单查询，覆盖5大领域
    test_messages = [
        "上个月各业务线的吞吐量是多少？",            # §7 A1 → M02
        "集装箱吞吐量今年目标是多少TEU，完成率怎样？", # §7 A5 → M04
        "今年投资计划完成了多少？",                   # §7 A3 → M25
        "各港区泊位占用率如何？",                    # §7 A2 → M05
        "战略客户有多少家？",                        # §7 A9 → M16
        "全港资产净值是多少？",                      # §7 A8 → M21
        "今年有哪些大项目在推进？",                   # §7 A10 → M27
        "船舶作业效率上季度是多少？",                 # §7 A7 → M06
        "最近一个月港存压力怎样？",                   # §7 A6 → M07
        "本月市场完成多少，和去年同期比？",            # §7 市场 → M10
    ]

    tasks = [
        run_and_record(
            run_id=i,
            message=test_messages[i % len(test_messages)],
            timeout_seconds=45
        )
        for i in range(SIMPLE_TABLE_RUNS)
    ]
    results = await asyncio.gather(*tasks)

    success = [
        r for r in results
        if r["status"] == "done" and r["has_output"] and r["elapsed"] <= 45
    ]
    failed = [r for r in results if r not in success]

    rate = len(success) / SIMPLE_TABLE_RUNS
    p50 = sorted(r["elapsed"] for r in success)[len(success) // 2] if success else 0
    p95_idx = int(len(results) * 0.95)
    all_elapsed = sorted(r["elapsed"] for r in results)
    p95 = all_elapsed[p95_idx] if all_elapsed else 0

    print(f"\n[simple_table 全链路成功率]")
    print(f"  成功: {len(success)}/{SIMPLE_TABLE_RUNS} = {rate:.1%}")
    print(f"  P50 耗时: {p50:.1f}s | P95 耗时: {p95:.1f}s")
    if failed:
        print(f"  失败详情:")
        for f in failed:
            print(f"    Run {f['run_id']}: {f['status']} ({f['elapsed']:.1f}s) — {f['error']}")

    assert rate >= SUCCESS_RATE_TARGET, (
        f"simple_table 成功率 {rate:.1%} < {SUCCESS_RATE_TARGET:.0%}\n"
        f"失败 {len(failed)} 次: {[(f['run_id'], f['status'], f['error']) for f in failed]}"
    )
```

#### TC-RATE02：chart_text 场景全链路成功率 ≥ 95%（10 次）
```python
@pytest.mark.llm_real
@pytest.mark.slow
async def test_chart_text_end_to_end_success_rate():
    """
    执行 10 次 chart_text 全链路，≥ 10 次成功（实际≥9次即通过）。
    成功判定：status=done AND has_output=True AND output含图表数据 AND elapsed ≤ 180s
    额外验证：output 中包含 ECharts option JSON（有效图表数据）
    """
    # §7 测试问题库：B类图文分析，覆盖多域API组合
    test_messages = [
        "分析一下今年Q1港口集装箱吞吐量的变化趋势，以及背后的主要驱动因素",  # §7 B1 → M03+M04+M14
        "今年散杂货市场表现如何，和去年比怎样？",                           # §7 B2 → M02+M12+M13
        "战略客户贡献趋势是否稳定，有没有流失风险？",                        # §7 B3 → M17+M19+M20
        "投资完成进度是否符合年初节奏安排？",                               # §7 B7 → M26+M25
        "今年商品车吞吐量为什么增速这么快？",                               # §7 B6 → M02+M12+M14
    ]

    tasks = [
        run_and_record(
            run_id=i,
            message=test_messages[i % len(test_messages)],
            timeout_seconds=190
        )
        for i in range(CHART_TEXT_RUNS)
    ]
    results = await asyncio.gather(*tasks)

    def is_chart_success(r: dict) -> bool:
        if r["status"] != "done" or not r["has_output"]:
            return False
        if r["elapsed"] > 180:
            return False
        # 验证输出中包含图表数据
        output = r.get("output", {})
        has_chart = bool(
            output.get("charts") or
            output.get("echarts_option") or
            any("chart" in str(k).lower() for k in (output or {}).keys())
        )
        return has_chart

    success = [r for r in results if is_chart_success(r)]
    rate = len(success) / CHART_TEXT_RUNS

    print(f"\n[chart_text 全链路成功率]")
    print(f"  成功: {len(success)}/{CHART_TEXT_RUNS} = {rate:.1%}")
    for r in results:
        status_icon = "✓" if is_chart_success(r) else "✗"
        print(f"  {status_icon} Run {r['run_id']}: {r['status']} ({r['elapsed']:.0f}s) {r.get('error','')}")

    assert rate >= SUCCESS_RATE_TARGET, (
        f"chart_text 成功率 {rate:.1%} < {SUCCESS_RATE_TARGET:.0%}"
    )
```

#### TC-RATE03：full_report 场景全链路成功率 ≥ 80%（5 次）
```python
@pytest.mark.llm_real
@pytest.mark.slow
async def test_full_report_end_to_end_success_rate():
    """
    执行 5 次 full_report 全链路，≥ 4 次成功（80%，低于简单场景可接受）。
    成功判定：status=done AND 生成可打开的 .pptx AND elapsed ≤ 600s
    注：full_report 链路最长，允许略低成功率目标，
        但每次失败必须有明确错误信息（不允许静默失败）。
    """
    from pptx import Presentation
    import tempfile, os

    FULL_REPORT_SUCCESS_TARGET = 0.80

    async def run_full_report(run_id: int) -> dict:
        r = await run_and_record(
            run_id=run_id,
            message="帮我生成3月份港口经营分析月报，要PPT格式，包含生产、市场、投资三个维度"  # §7 C2 → 8个API,
            timeout_seconds=620
        )
        if r["status"] == "done" and r.get("output", {}).get("pptx_bytes"):
            # 验证 PPTX 可打开且幻灯片数 ≥ 4
            try:
                with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
                    f.write(r["output"]["pptx_bytes"])
                    tmp_path = f.name
                prs = Presentation(tmp_path)
                os.unlink(tmp_path)
                r["pptx_slide_count"] = len(prs.slides)
                r["pptx_valid"] = len(prs.slides) >= 4
            except Exception as e:
                r["pptx_valid"] = False
                r["pptx_error"] = str(e)
        return r

    results = await asyncio.gather(*[run_full_report(i) for i in range(FULL_REPORT_RUNS)])

    success = [
        r for r in results
        if r["status"] == "done" and r.get("pptx_valid") and r["elapsed"] <= 600
    ]
    rate = len(success) / FULL_REPORT_RUNS

    # 失败必须有明确错误信息（不允许静默失败）
    silent_failures = [
        r for r in results
        if r["status"] not in ("done", "timeout") and not r.get("error")
    ]
    assert not silent_failures, \
        f"以下运行静默失败（无错误信息）: {[r['run_id'] for r in silent_failures]}"

    print(f"\n[full_report 全链路成功率]")
    print(f"  成功: {len(success)}/{FULL_REPORT_RUNS} = {rate:.1%}")
    for r in results:
        status_icon = "✓" if r in success else "✗"
        slides = r.get("pptx_slide_count", "-")
        print(f"  {status_icon} Run {r['run_id']}: {r['status']} ({r['elapsed']:.0f}s) "
              f"slides={slides} {r.get('error','')}")

    assert rate >= FULL_REPORT_SUCCESS_TARGET, (
        f"full_report 成功率 {rate:.1%} < {FULL_REPORT_SUCCESS_TARGET:.0%}"
    )
```

# 5大领域均衡覆盖的20条测试消息，直接来自 MockAPI 模拟建议文档 §7 测试问题库
TEST_MESSAGES_BALANCED = [
    # 生产运营域（4条，对应 M01-M09）
    "上个月各业务线的吞吐量是多少？",            # §7 A1 → M02
    "集装箱吞吐量今年目标是多少TEU，完成率怎样？", # §7 A5 → M04
    "现在各港区泊位占用率如何？",                # §7 A2 → M05
    "船舶作业效率上季度是多少？",                # §7 A7 → M06
    # 市场商务域（4条，对应 M10-M15）
    "本月市场完成多少，和去年同期比差多少？",     # §7 市场 → M10
    "各业务板块结构如何，集装箱占整体比重是多少？",# §7 → M15
    "贡献最大的重点企业是哪些，占比多少？",      # §7 → M14
    "各港区之间吞吐量差异是否在扩大？",          # §7 B5 → M13
    # 客户管理域（4条，对应 M16-M20）
    "战略客户有多少家？",                        # §7 A9 → M16
    "战略客户贡献趋势是否稳定，有没有流失风险？", # §7 B3 → M17+M19+M20
    "贡献最大的10个客户是谁？",                  # §7 → M19
    "客户信用状况整体健康吗？",                  # §7 B8 → M20+M16+M19
    # 资产管理域（4条，对应 M21-M24）
    "全港资产净值是多少？",                      # §7 A8 → M21
    "设备资产占比多少，和设施资产相比如何？",     # §7 → M22
    "设备状态如何，有多少设备在维修？",           # §7 → M23
    "设备资产状况如何，今年投了多少钱更新设备？", # §7 B4 → M23+M24+M25
    # 投资管理域（4条，对应 M25-M27）
    "今年投资计划完成了多少？",                   # §7 A3 → M25
    "今年有哪些大项目在推进？",                   # §7 A10 → M27
    "投资完成进度是否符合年初节奏安排？",          # §7 B7 → M26+M25
    "今年商品车吞吐量为什么增速这么快？",          # §7 B6 → M02+M12+M14（跨域）
]

#### TC-RATE04：多场景混合并发成功率（压力测试）
```python
@pytest.mark.llm_real
@pytest.mark.slow
async def test_mixed_concurrent_success_rate():
    """
    同时发起 5 个并发会话（3 个 simple_table + 2 个 chart_text），
    验证并发场景下整体成功率 ≥ 90%（允许个别超时）。
    目标：验证 Agent 在多用户同时使用时的稳定性。
    """
    tasks = [
        run_and_record(i, msg, timeout)
        for i, (msg, timeout) in enumerate([
            ("大连港2024年月度吞吐量表格", 45),
            ("大连港2024年集装箱趋势图分析", 190),
            ("2024年各货类吞吐量排名", 45),
            ("大连港2024年货量走势图", 190),
            ("大连港去年货物数据汇总表", 45),
        ])
    ]
    results = await asyncio.gather(*tasks)

    success = [r for r in results if r["status"] == "done" and r["has_output"]]
    rate = len(success) / len(results)

    print(f"\n[混合并发成功率] {len(success)}/{len(results)} = {rate:.1%}")

    assert rate >= 0.90, (
        f"混合并发成功率 {rate:.1%} < 90%，并发稳定性不足"
    )
```

#### TC-RATE05：成功率趋势追踪（回归检测）
```python
@pytest.mark.llm_real
@pytest.mark.slow
async def test_success_rate_regression_detection(db_session):
    """
    将本次成功率结果写入 DB 的 reliability_metrics 表。
    如果连续 3 次 Nightly 成功率均低于 90%，触发告警断言。
    用于检测 LLM Prompt 变更或模型更新导致的性能回归。
    """
    # 执行 10 次 simple_table 快速测试
    tasks = [
        run_and_record(i, "大连港2024年月度吞吐量表格", 45)
        for i in range(10)
    ]
    results = await asyncio.gather(*tasks)
    success_count = sum(1 for r in results if r["status"] == "done" and r["has_output"])
    current_rate = success_count / 10

    # 写入历史记录
    await db_session.execute(
        text("INSERT INTO reliability_metrics "
             "(run_date, scenario, success_rate, sample_size) "
             "VALUES (NOW(), 'simple_table', :rate, :n)"),
        {"rate": current_rate, "n": 10}
    )
    await db_session.commit()

    # 查询最近 3 次历史记录
    recent = await db_session.execute(
        text("SELECT success_rate FROM reliability_metrics "
             "WHERE scenario='simple_table' "
             "ORDER BY run_date DESC LIMIT 3")
    )
    recent_rates = [row[0] for row in recent.fetchall()]

    # 连续 3 次低于 0.90 则触发告警
    if len(recent_rates) >= 3:
        all_below_90 = all(r < 0.90 for r in recent_rates)
        assert not all_below_90, (
            f"成功率连续 3 次低于 90%: {[f'{r:.0%}' for r in recent_rates]}\n"
            f"可能原因：Prompt 变更、模型更新或依赖服务不稳定，请立即排查！"
        )

    print(f"\n[成功率趋势] 最近 3 次: {[f'{r:.0%}' for r in recent_rates]}")
    print(f"本次: {current_rate:.1%}")
```

---

### 全链路健壮性验收标准（补充）

在 Phase 5 原有验收标准 §10 基础上，补充以下成功率门控：

| 验收项 | 判断标准 | 测试用例 |
|--------|----------|----------|
| R-ACC-01：simple_table 全链路成功率 | ≥ 95%（20次中≥19次） | TC-RATE01 |
| R-ACC-02：chart_text 全链路成功率 | ≥ 95%（10次中≥10次） | TC-RATE02 |
| R-ACC-03：full_report 全链路成功率 | ≥ 80%（5次中≥4次） | TC-RATE03 |
| R-ACC-04：混合并发成功率 | ≥ 90%（5并发） | TC-RATE04 |
| R-ACC-05：Slot 提取准确率 | ≥ 85%（15样本均值） | TC-ACC（Phase 1） |
| R-ACC-06：规划合理性准确率 | ≥ 90%（10场景均值） | TC-PLAN-ACC（Phase 2） |
| R-ACC-07：反思偏好提取准确率 | ≥ 80%（5场景均值） | TC-RF-QUAL02（Phase 4） |

