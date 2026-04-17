# Analytica - 港口市场商务智能分析 Agent

Analytica 是一个具备 **感知-规划-执行-反思** 闭环能力的企业级数据分析智能体。通过自然语言交互，帮助业务人员完成从问题澄清到报告交付的全流程数据分析任务。

## 产品架构

```
用户交互层 (React 19 + WebSocket)
         │
智能体核心引擎 (LangGraph State Machine)
  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
  │ 感知模块  │→│ 规划模块  │→│ 执行模块  │→│ 反思模块  │
  │Perception│  │Planning  │  │Execution │  │Reflection│
  └──────────┘  └──────────┘  └──────────┘  └──────────┘
         │              │              │
    数据接入层      技能执行层      记忆存储层
```

### 四阶段流水线

| 阶段 | 职责 | 核心机制 |
|------|------|----------|
| **感知** | 意图理解与槽位填充 | Slot Filling + 多轮追问 |
| **规划** | 生成可执行分析方案 | 任务 DAG + 技能选择 |
| **执行** | 并行执行分析任务 | 异步调度 + 超时恢复 |
| **反思** | 偏好萃取与模板沉淀 | 记忆持久化 + 质量评估 |

## 技术栈

### 后端
- **框架**: FastAPI + Uvicorn
- **Agent 引擎**: LangGraph (状态机编排)
- **LLM**: Qwen3-235B (通过 OpenAI 兼容接口)
- **数据库**: MySQL + SQLAlchemy (异步)
- **迁移**: Alembic

### 前端
- **框架**: React 19 + TypeScript
- **构建**: Vite 8
- **状态管理**: Zustand 5
- **样式**: Tailwind CSS 4
- **图表**: ECharts (echarts-for-react)
- **实时通信**: 原生 WebSocket

## 目录结构

```
├── backend/                    # FastAPI 后端
│   ├── main.py                # 应用入口 + API 路由 + WebSocket
│   ├── config.py              # 配置管理
│   ├── database.py            # 数据库 ORM 模型
│   ├── agent/                 # LangGraph 4阶段流水线
│   │   ├── graph.py           # 状态图定义与流式执行
│   │   ├── perception.py      # 感知层 (Slot 填充引擎)
│   │   ├── planning.py        # 规划层 (任务 DAG 生成)
│   │   ├── execution.py       # 执行层 (并行任务调度)
│   │   ├── reflection.py      # 反思层 (偏好与模板提取)
│   │   ├── api_registry.py    # API 端点注册表
│   │   └── skills.py          # 技能注册辅助
│   ├── employees/             # 员工角色系统
│   │   ├── profile.py         # YAML 配置加载
│   │   ├── manager.py         # 员工管理器 (单例)
│   │   └── graph_factory.py   # 参数化 LangGraph 构建
│   ├── skills/                # 技能库
│   │   ├── data/              # 数据获取 (API/文件/搜索)
│   │   ├── analysis/          # 分析技能 (描述/归因/预测/异常)
│   │   ├── visualization/     # 可视化 (折线/柱状/瀑布图)
│   │   └── report/            # 报告生成 (HTML/DOCX/PPTX)
│   └── memory/                # 记忆存储 (偏好/模板/技能记录)
├── frontend/                  # React 前端
│   └── src/
│       ├── components/        # UI 组件
│       │   ├── SlotStatusCard # Slot 填充状态卡片
│       │   ├── PlanCard       # 分析方案展示
│       │   ├── ExecutionProgress # 任务执行进度
│       │   ├── ReflectionCard # 反思摘要
│       │   ├── EChartsViewer  # 图表渲染
│       │   ├── ChatMessage    # 对话消息 (Markdown)
│       │   └── InputBar       # 输入框
│       ├── stores/            # Zustand 状态管理
│       ├── hooks/             # WebSocket 连接管理
│       └── api/               # HTTP API 客户端
├── employees/                 # 员工角色 YAML 配置
│   ├── throughput_analyst.yaml
│   ├── customer_insight.yaml
│   └── asset_investment.yaml
├── mock_server/               # Mock API 服务器
├── migrations/                # Alembic 数据库迁移
├── tests/                     # 测试套件
├── deploy/                    # Docker 部署脚本
├── Dockerfile
└── docker-compose.yml
```

## 快速开始

### 环境要求

- Python 3.12+
- Node.js 18+
- MySQL 5.7+ (或 8.0)
- [uv](https://docs.astral.sh/uv/) (Python 包管理)

### 1. 安装后端依赖

```bash
uv sync
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，配置以下必要项：
# QWEN_API_KEY=your_api_key
# QWEN_BASE_URL=your_qwen_endpoint
# DATABASE_URL=mysql+aiomysql://user:pass@localhost:3306/analytica
```

### 3. 初始化数据库

```bash
uv run alembic upgrade head
```

### 4. 启动后端服务

```bash
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

### 5. 安装并启动前端

```bash
cd frontend
npm install
npm run dev
```

访问 http://localhost:5173 即可使用。

### 6. 启动 Mock API 服务器 (开发环境)

```bash
uv run python -m mock_server.mock_server_all
```

## Docker 部署

```bash
docker-compose up -d
```

## API 端点

### REST API

| 方法 | 路径 | 描述 |
|------|------|------|
| `GET` | `/health` | 健康检查 |
| `GET` | `/api/employees` | 获取所有员工角色列表 |
| `GET` | `/api/employees/{id}` | 获取员工角色详情 |
| `POST` | `/api/sessions` | 创建分析会话 |
| `GET` | `/api/sessions/{id}` | 获取会话状态 |
| `GET` | `/api/sessions/{id}/plan` | 获取当前分析方案 |
| `POST` | `/api/sessions/{id}/plan/confirm` | 确认/修改方案 |
| `POST` | `/api/sessions/{id}/plan/regenerate` | 重新生成方案 |
| `POST` | `/api/sessions/{id}/reflection/save` | 保存反思结果 |

### WebSocket

连接地址: `ws://localhost:8000/ws/chat/{session_id}`

事件类型:
- `slot_update` - Slot 填充进度更新
- `message` - Agent 消息推送
- `intent_ready` - 结构化意图就绪
- `plan_update` - 分析方案生成
- `task_update` - 任务执行状态
- `reflection` - 反思摘要就绪
- `turn_complete` - 对话轮次完成

## 员工角色系统

通过 YAML 配置定义不同分析角色，限定可用的业务领域、API 端点和分析技能：

- **throughput_analyst** - 吞吐量分析师 (生产运营域)
- **customer_insight** - 客户洞察分析师 (客户管理域)
- **asset_investment** - 资产投资分析师 (资产管理 + 投资管理域)

## 技能库

| 类别 | 技能 | 说明 |
|------|------|------|
| 数据获取 | `skill_api_fetch` | 调用数据 API 获取结构化数据 |
| 分析 | `skill_desc_analysis` | 描述性统计 (均值/同比/环比) |
| 分析 | `skill_attribution` | 归因分析 (驱动因素识别) |
| 分析 | `skill_prediction` | 预测分析 (趋势外推) |
| 分析 | `skill_anomaly` | 异常检测 |
| 可视化 | `skill_chart_line` | 折线图 (ECharts) |
| 可视化 | `skill_chart_bar` | 柱状图 (ECharts) |
| 可视化 | `skill_chart_waterfall` | 瀑布图 |
| 报告 | `skill_report_html` | HTML 报告 |
| 报告 | `skill_report_docx` | Word 文档 |
| 报告 | `skill_report_pptx` | PowerPoint 演示文稿 |

## 典型使用场景

**场景 A: 简单查询** (< 30s)
> "上个月各业务线的吞吐量是多少？"
> 输出: 格式化数据表格

**场景 B: 图文分析** (< 3min)
> "分析今年Q1港口集装箱吞吐量变化趋势及驱动因素"
> 输出: 趋势图 + 归因分析文字

**场景 C: 完整报告** (< 10min)
> "生成3月份港口经营分析月报，PPT格式，包含生产、市场、投资三维度"
> 输出: 多页 PPTX 报告

## 测试

```bash
# 后端测试
uv run pytest tests/

# 前端组件测试
cd frontend && npx vitest run
```

## License

Private - Internal Use Only
