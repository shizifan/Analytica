# Analytica 数据分析 Agent — Phase 0：模拟数据环境
## 实施方案 v1.3 · 阶段文档

---

## 版本记录

| 版本号 | 日期 | 修订说明 | 编制人 |
|--------|------|----------|--------|
| v1.0 | 2026-04-14 | 初版，基于 MockAPI 模拟建议文档 V1.0 构建完整 Mock Server | FAN |

---

## 阶段概览

| 项目 | 内容 |
|------|------|
| **阶段** | Phase 0 — 模拟数据环境搭建 |
| **时间** | Day 0（所有后续阶段的前置条件） |
| **里程碑** | 27 个 Mock API 全部可用，数据符合业务量级，幂等性通过验证 |
| **前置条件** | 无（本阶段是一切开发与测试的基础） |
| **输出物** | Mock Server（`mock_server/`）、pytest fixtures（`tests/fixtures/mock_data.py`）、自检测试套件 |

---

## 一、Mock API 架构总览

### 1.1 五大领域 · 27 个 API

```
┌─────────────────────────────────────────────────────────────────────────┐
│                   Analytica Mock API 架构                                │
│                                                                          │
│  生产运营域（9）     市场商务域（6）     客户管理域（5）                    │
│  M01 吞吐汇总         M10 市场当月         M16 客户基本信息                 │
│  M02 板块分类         M11 市场累计         M17 战略客户货量                 │
│  M03 月度趋势         M12 趋势图数据        M18 战略客户收入                 │
│  M04 集装箱专项        M13 港区对比         M19 客户贡献排名                 │
│  M05 泊位占用率        M14 重点企业贡献      M20 客户信用信息                 │
│  M06 船舶作业效率      M15 板块占比                                         │
│  M07 港存数据                                                              │
│  M08 昼夜生产动态      资产管理域（4）       投资管理域（3）                  │
│  M09 在港船舶状态      M21 资产总览          M25 投资计划汇总                │
│                       M22 资产类型分布        M26 月度进度曲线               │
│                       M23 设备设施状态        M27 资本项目明细               │
│                       M24 资产历年趋势                                      │
│                                                                          │
│  Base URL: http://mock.port-ai.internal/api/v1/                         │
│  Auth: Bearer TEST_TOKEN_2024                                            │
│  数据范围: 2024-01 ～ 2026-06（30个月）                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.2 数据量级基准（辽港集团量级）

| 指标 | 参考量级 | Mock 数据范围 |
|------|----------|--------------|
| 年度货物吞吐量 | 3–4 亿吨/年 | 2.8–4.2 亿吨 |
| 集装箱年吞吐量 | 400–500 万 TEU | 380–520 万 TEU |
| 月度吞吐量均值 | 2500–3500 万吨 | 1800–4500 万吨（含季节波动） |
| 战略客户数量 | 30–50 家 | 25–60 家 |
| 年度投资计划 | 10–15 亿元 | 8–18 亿元（万元为单位） |
| 实物资产总数 | 10000–30000 件 | 8000–35000 件 |

### 1.3 时序数据业务规律

```python
# 月度吞吐量季节性因子（体现港口业务节奏）
SEASONAL_FACTOR = {
    1: 0.85,   # 元旦/春节前，略低
    2: 0.75,   # 春节期间，全年最低
    3: 1.05,   # 春节后恢复，环比大涨
    4: 1.08,   # Q2 旺季启动
    5: 1.10,   # 五月旺季峰值
    6: 1.07,   # 6月末冲量
    7: 1.03,   # 夏季略有下滑
    8: 1.05,   # 旺季持续
    9: 1.08,   # 旺季高峰（全年最高之一）
    10: 1.06,  # 旺季尾声
    11: 0.95,  # 进入淡季
    12: 0.92   # 年末冲量 vs 天气影响，小幅回落
}

# 年度同比增长基准
YOY_GROWTH = {
    2024: 0.048,   # 基准年，增速 4.8%
    2025: 0.062,   # 2025 年增速 6.2%
    2026: 0.057    # 2026 年增速 5.7%（预测中值）
}

# 各港区份额分布（大连为主港）
ZONE_SHARE = {
    "大连港区": 0.52,
    "营口港区": 0.28,
    "丹东港区": 0.12,
    "锦州港区": 0.08,
}

# 业务板块结构
SEGMENT_SHARE = {
    "集装箱": 0.42,
    "散杂货": 0.31,
    "油化品": 0.17,
    "商品车": 0.10,
}
```

---

## 二、Mock Server 完整实现

### 2.1 目录结构

```
mock_server/
├── main.py                  # FastAPI 应用入口
├── utils.py                 # 确定性随机种子工具
├── routers/
│   ├── production.py        # 生产运营域 M01-M09
│   ├── market.py            # 市场商务域 M10-M15
│   ├── customer.py          # 客户管理域 M16-M20
│   ├── asset.py             # 资产管理域 M21-M24
│   └── invest.py            # 投资管理域 M25-M27
├── data/
│   ├── constants.py         # 业务常量（季节因子、量级基准）
│   └── generators.py        # 数据生成函数
└── README.md
```

### 2.2 核心工具函数（utils.py）

```python
# mock_server/utils.py
import hashlib
import random
from datetime import date, datetime
from fastapi import Header, HTTPException

def get_seed(*args) -> int:
    """基于参数生成确定性种子，保证同参数多次调用返回相同数据"""
    key = "|".join(str(a) for a in args if a is not None)
    return int(hashlib.md5(key.encode()).hexdigest()[:8], 16)

def seeded_rng(*args) -> random.Random:
    return random.Random(get_seed(*args))

def verify_token(authorization: str = Header(...)):
    """统一 Bearer Token 验证"""
    if authorization != "Bearer TEST_TOKEN_2024":
        raise HTTPException(status_code=401, detail="Invalid token")

def parse_month(date_str: str) -> tuple[int, int]:
    """解析 yyyy-MM 返回 (year, month)"""
    parts = date_str.split("-")
    return int(parts[0]), int(parts[1])

def in_data_range(year: int, month: int = 1) -> bool:
    """验证日期是否在 Mock 数据范围内（2024-01 ~ 2026-06）"""
    start = (2024, 1)
    end = (2026, 6)
    current = (year, month)
    return start <= current <= end

def calc_throughput_base(year: int, month: int, base_annual: float = 33600.0) -> float:
    """
    计算给定年月的月度吞吐量基准值（万吨）
    base_annual = 33600 万吨/年（约 3.36 亿吨，辽港集团量级）
    """
    from mock_server.data.constants import SEASONAL_FACTOR, YOY_GROWTH
    base_monthly = base_annual / 12
    seasonal = SEASONAL_FACTOR.get(month, 1.0)
    # 叠加年度增长
    growth = 1.0
    for y in range(2024, year):
        growth *= (1 + YOY_GROWTH.get(y, 0.055))
    return base_monthly * seasonal * growth
```

### 2.3 AI Coding Prompt：生产运营域路由（production.py）

```
【任务】用 FastAPI 实现生产运营域 9 个 Mock API（M01-M09）。

【完整接口清单】

M01 GET /api/v1/production/throughput/summary
  params: date(str), dateType(int,0=日1=月2=年), regionName(str,可选)
  response: {totalThroughput,targetThroughput,completionRate,yoyGrowthRate,momGrowthRate,period}
  数据规律：totalThroughput = calc_throughput_base() × 区域份额 × rng.uniform(0.96,1.04)
             completionRate = totalThroughput / targetThroughput × 100
             yoyGrowthRate = rng.uniform(3.0, 9.5)

M02 GET /api/v1/production/throughput/by-business-type
  params: flag(int,0=当月1=累计), dateMonth(str,yyyy-MM), regionName(str,可选)
  response: list of {businessType,throughput,yoyRate,shareRatio}
  businessType 枚举：["集装箱","散杂货","油化品","商品车"]
  shareRatio 参考 SEGMENT_SHARE，加 ±3% 随机扰动

M03 GET /api/v1/production/throughput/monthly-trend
  params: dateYear(str,yyyy), preYear(str,可选,默认dateYear-1), regionName(str,可选)
  response: list of {month,currentYear,prevYear,yoyRate,momRate}
  仅返回 dateYear 已发生的月份（2026年只有1-6月）

M04 GET /api/v1/production/container/throughput
  params: dateYear(str), regionName(str,可选)
  response: {totalTeu,targetTeu,foreignTradeTeu,domesticTradeTeu,completionRate,yoyRate}
  totalTeu 量级：全港年度 400-500 万 TEU；foreignTrade 占比约 65-70%

M05 GET /api/v1/production/berth/occupancy-rate
  params: startDate(str,yyyy-MM-dd), endDate(str), groupBy(str,region|businessType)
  response: list of {name,occupancyRate,berthCount,avgBerthHours}
  大连港区泊位占用率：75-88%（偏高，反映繁忙程度）
  营口港区：60-75%；丹东：35-55%；锦州：40-60%

M06 GET /api/v1/production/vessel/efficiency
  params: startMonth(str), endMonth(str), cmpName(str,可选)
  response: list of {period,avgEfficiency,topCompany,yoyChange}
  avgEfficiency 单位：自然箱/小时，范围 12-22

M07 GET /api/v1/production/port-inventory
  params: date(str,yyyy-MM-dd), businessType(str), regionName(str,可选)
  response: list of {cargoType,inventoryTon,capacityRatio,trend3d}
  capacityRatio 正常范围：40-75%；>85% 时返回高库容预警标记

M08 GET /api/v1/production/daily-dynamic
  params: dispatchDate(str,yyyy-MM-dd), scope(str,port|wharf)
  response: {dayShift:{throughput,shipCount},nightShift:{throughput,shipCount},totalForDay,activeShips}
  白班 > 夜班约 15-25%

M09 GET /api/v1/production/ships/status
  params: shipStatus(str,C=锚地|D=在泊), regionName(str,可选)
  response: list of {shipName,status,region,expectedDeparture,cargoType}
  在泊船舶 15-35 艘，锚地 3-12 艘

【通用要求】
- 每个 endpoint 均调用 verify_token(authorization) 进行 Bearer Token 验证
- 参数缺失时返回 400；日期超出范围（非 2024-01 ~ 2026-06）返回 {"code": 404, "data": null, "msg": "数据不存在：超出可查询范围"}
- 所有数值使用 seeded_rng(endpoint_name, *params) 生成，保证幂等性
- 统一响应格式：{"code": 200, "data": {...}, "msg": "success"}
- 数值精度：吞吐量保留1位小数，金额2位，比率1位
```

### 2.4 AI Coding Prompt：市场商务域路由（market.py）

```
【任务】实现市场商务域 6 个 Mock API（M10-M15）。

M10 GET /api/v1/market/throughput/monthly
  params: curDateMonth(str,yyyy-MM), yearDateMonth(str,yyyy-MM)
  response: {curMonthTotal,prevYearSame,yoyDiff,yoyRate,completionRate}
  curMonthTotal = calc_throughput_base(curYear,curMonth) × rng.uniform(0.97,1.03)
  prevYearSame = calc_throughput_base(prevYear,sameMonth) × rng.uniform(0.97,1.03)
  yoyRate = (curMonthTotal - prevYearSame) / prevYearSame × 100

M11 GET /api/v1/market/throughput/cumulative
  params: curDateYear(str,yyyy), yearDateYear(str,yyyy)
  response: {curYearCumulative,prevYearCumulative,yoyDiff,yoyRate}
  curYearCumulative = sum of monthly for all completed months in curDateYear
  2026年只能计算到6月（数据截止）

M12 GET /api/v1/market/trend-chart
  params: businessSegment(str), startDate(str,yyyy-MM), endDate(str,yyyy-MM)
  response: list of {month,value,yoyRate}
  businessSegment 枚举：["集装箱","散杂货","油化品","商品车","全货类"]
  value 基于 SEGMENT_SHARE[segment] × 月度总量 × 扰动

M13 GET /api/v1/market/throughput/by-zone
  params: curDateMonth(str,yyyy-MM), yearDateMonth(str,yyyy-MM)
  response: list of {zoneName,throughput,yoyRate,shareRatio}
  zoneName 枚举：["大连港区","营口港区","丹东港区","锦州港区"]

M14 GET /api/v1/market/key-enterprise
  params: businessSegment(str), curDateMonth(str), statisticType(int,0=当月1=累计)
  response: list(10) of {rank,enterpriseName,throughput,contribution,yoyRate}
  企业名称从预定义列表随机抽取（见 constants.py），排名1贡献率约12-18%，排名10约2-4%

M15 GET /api/v1/market/business-segment
  params: curDateMonth(str), yearDateMonth(str), statisticType(int)
  response: list of {segmentName,throughput,shareRatio,yoyRate}
  4个板块，shareRatio之和=100%

【说明】市场商务域与生产运营域数据保持一致性：
M10 的 curMonthTotal ≈ M01 在相同月份的 totalThroughput（允许5%偏差）
M13 的各港区之和 ≈ M10 的 curMonthTotal
```

### 2.5 AI Coding Prompt：客户管理域路由（customer.py）

```
【任务】实现客户管理域 5 个 Mock API（M16-M20）。

M16 GET /api/v1/customer/basic-info
  params: 无必填参数
  response: {totalCustomers:int, typeDistribution:[{type,count,ratio}], fieldDistribution:[{field,count}]}
  totalCustomers: 580-680（辽港集团实际客户量级）
  typeDistribution: 货主(50%)、代理(30%)、船公司(20%)

M17 GET /api/v1/customer/strategic/throughput
  params: curDate(str,yyyy-MM或yyyy), statisticType(int,0=月度1=年度), clientName(str,可选)
  response: list of {clientName,throughput,contributionRate,yoyRate,rank}
  战略客户总数：35-45家；TOP1贡献率约8-12%；TOP10合计贡献约55-65%
  预定义战略客户名称（来自常量）：COSCO、中远海运、中储粮、华能集团、鞍钢、国家电网等

M18 GET /api/v1/customer/strategic/revenue
  params: curDate(str), statisticType(int), clientName(str,可选)
  response: list of {clientName,revenue,revenueShare,yoyRate}
  收入单位：万元；战略客户年收入贡献总计约 1.5-2.5 亿元

M19 GET /api/v1/customer/contribution/ranking
  params: date(str), statisticType(int,0=当月1=累计), cargoCategoryName(str,可选), topN(int,默认10)
  response: list of {rank,clientName,throughput,contributionRate,yoyChange}
  支持 topN 最大 50

M20 GET /api/v1/customer/credit-info
  params: orgName(str,可选), customerName(str,可选)
  response: list of {customerName,creditLevel,creditLimit,usedCredit,availableCredit}
  creditLevel 分布：AAA(15%)、AA(30%)、A(35%)、B(15%)、C(5%)
  无参数时返回全部客户摘要（信用等级分布统计），有 customerName 时返回单客户详情
```

### 2.6 AI Coding Prompt：资产管理域 + 投资管理域（asset.py / invest.py）

```
【任务】实现资产管理域（M21-M24）和投资管理域（M25-M27）。

【资产管理域】

M21 GET /api/v1/asset/overview
  params: dateYear(str,yyyy), ownerZone(str,可选)
  response: {totalAssetCount,totalOriginalValue,totalNetValue,depreciationRate,byZone:[...]}
  totalAssetCount: 全港约 18000-25000 件（年度微增）
  totalOriginalValue: 约 500000-650000 万元
  totalNetValue / totalOriginalValue = 净值率 55-65%
  depreciationRate: 平均折旧率 35-45%

M22 GET /api/v1/asset/distribution/by-type
  params: dateYear(str), ownerZone(str,可选)
  response: list of {assetType,count,originalValue,netValue,shareRatio}
  assetType 枚举：["设备","设施","房屋","土地海域"]
  设备占比：数量55%、价值45%；设施：25%/30%；房屋：15%/15%；土地：5%/10%

M23 GET /api/v1/asset/equipment/status
  params: dateYear(str), type(int,1=设备2=设施), ownerZone(str,可选)
  response: list of {status,count,ratio,yoyChange}
  status 枚举：["正常","维修中","报废","闲置"]
  正常占比：82-88%；维修中：5-8%；报废：3-6%；闲置：2-5%

M24 GET /api/v1/asset/historical-trend
  params: startYear(str,yyyy), endYear(str,yyyy), ownerZone(str,可选)
  response: list of {year,newAssetCount,newAssetValue,scrapAssetCount,endNetValue}
  新增资产价值 = 对应年度投资额 × 0.8（资本化比例）

【投资管理域】

M25 GET /api/v1/invest/plan/summary
  params: currYear(str,yyyy), ownerLgZoneName(str,可选)
  response: {approvedAmount,completedAmount,paidAmount,completionRate,deliveryRate,projectCount:{capital,cost,unplanned}}
  approvedAmount: 80000-150000 万元/年
  completionRate 随月份递增：1月约5-10%，12月约85-95%
  2026年截至6月：completionRate ≈ 32-42%

M26 GET /api/v1/invest/plan/monthly-progress
  params: startMonth(str,yyyy-MM), endMonth(str,yyyy-MM), ownerLgZoneName(str,可选)
  response: list of {month,plannedAmount,actualAmount,cumulativePlan,cumulativeActual,progressRatio}
  actual通常略低于planned（实际执行偏慢），累计进度比约85-95%

M27 GET /api/v1/invest/capital-projects
  params: dateYear(str), investProjectType(str,可选), regionName(str,可选)
  response: list of {projectName,investProjectType,approvedAmount,completedAmount,visualProgress,deliveryStatus,deliveryDate}
  每年约20-30个资本类项目；deliveryStatus 枚举：["已交付","在建","未开工"]
  预定义典型项目名称（来自常量）：
    "大连港集装箱码头改扩建"、"营口港散货泊位自动化升级"、
    "丹东港综合物流园区建设"、"智慧港口数字化平台项目" 等

【通用约束与数据一致性规则】
1. M24 新增资产价值与 M25/M26 投资额保持 ~80% 对应关系
2. M21 净值 ≈ 上一年净值 + M24 新增资产价值 - 当年折旧额
3. M23 维修中设备数量应在 M06 效率数据中有所反映（效率偏低时维修数量偏高）
```

---

## 三、pytest Fixtures（测试数据环境）

### 3.1 Mock Server Fixture

```python
# tests/fixtures/mock_server.py
import pytest
import pytest_asyncio
import asyncio
import subprocess
import time
import httpx
from mock_server.main import app

@pytest_asyncio.fixture(scope="session")
async def mock_server():
    """
    启动 Mock Server 进程，供所有测试共享。
    返回 base_url 和预配置的 httpx.AsyncClient。
    """
    base_url = "http://localhost:18080"
    process = subprocess.Popen(
        ["uvicorn", "mock_server.main:app", "--port", "18080", "--log-level", "warning"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )
    # 等待服务就绪（最多 10s）
    for _ in range(20):
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{base_url}/health")
                if resp.status_code == 200:
                    break
        except Exception:
            pass
        await asyncio.sleep(0.5)
    else:
        process.terminate()
        pytest.fail("Mock Server 未能在 10s 内启动")

    yield base_url

    process.terminate()
    process.wait()


@pytest_asyncio.fixture
async def mock_client(mock_server):
    """带 AUTH Token 的 httpx.AsyncClient"""
    async with httpx.AsyncClient(
        base_url=mock_server,
        headers={"Authorization": "Bearer TEST_TOKEN_2024"},
        timeout=10.0
    ) as client:
        yield client


@pytest_asyncio.fixture
async def mock_client_no_auth(mock_server):
    """无 Token 的客户端，用于测试鉴权"""
    async with httpx.AsyncClient(base_url=mock_server, timeout=10.0) as client:
        yield client
```

### 3.2 标准数据 Fixtures（供 Agent 测试使用）

```python
# tests/fixtures/mock_data.py
import pytest
from datetime import date

# ─── 时间参数标准集 ────────────────────────────────────────────────
TEST_DATES = {
    "latest_month":     "2026-03",   # 最近完整月（当前为4月）
    "latest_year":      "2026",
    "prev_month":       "2026-02",
    "prev_year":        "2025",
    "q1_start":         "2026-01",
    "q1_end":           "2026-03",
    "full_year_2025":   "2025",
    "full_year_2024":   "2024",
    "trend_30m_start":  "2024-01",
    "trend_30m_end":    "2026-06",   # 数据范围终点
}

# ─── 港区枚举 ─────────────────────────────────────────────────────
REGIONS = ["大连港区", "营口港区", "丹东港区", "锦州港区"]

# ─── 业务板块枚举 ─────────────────────────────────────────────────
BUSINESS_TYPES = ["集装箱", "散杂货", "油化品", "商品车"]

# ─── 预定义战略客户 ───────────────────────────────────────────────
STRATEGIC_CLIENTS = [
    "中远海运集装箱运输", "马士基航运", "地中海航运",
    "华能煤业", "中储粮总公司", "鞍山钢铁集团",
    "中国石化", "中国石油", "大众汽车进出口",
    "宝马汽车进出口", "国家能源集团",
]

# ─── 预定义重点项目 ───────────────────────────────────────────────
CAPITAL_PROJECTS = [
    ("大连港集装箱码头改扩建工程", "资本类"),
    ("营口港散货泊位自动化升级改造", "资本类"),
    ("丹东港综合物流园区建设", "资本类"),
    ("智慧港口生产管控系统", "成本类"),
    ("锦州港液散码头扩容", "资本类"),
    ("港口设备智能化改造项目", "成本类"),
    ("绿色港口岸电系统建设", "资本类"),
]

@pytest.fixture
def standard_params():
    """返回标准化测试参数字典，供所有 Agent 测试使用"""
    return TEST_DATES.copy()

@pytest.fixture
def throughput_expectation():
    """返回各月度吞吐量的合理范围（用于断言校验）"""
    return {
        "monthly_min_wan_ton": 1800.0,
        "monthly_max_wan_ton": 4500.0,
        "annual_min_wan_ton": 280000.0,
        "annual_max_wan_ton": 420000.0,
        "container_annual_min_teu": 3_800_000,
        "container_annual_max_teu": 5_200_000,
        "yoy_reasonable_min": -10.0,   # 合理同比下限 %
        "yoy_reasonable_max": 20.0,    # 合理同比上限 %
    }
```

---

## 四、Mock Server 自检测试套件

> 文件：`tests/mock/test_mock_server_integrity.py`  
> 目的：确保 Mock Server 在所有后续阶段测试启动前已完全就绪，数据符合业务规范。

### TC-M0S：Mock Server 基础功能

#### TC-M0S01：健康检查端点正常
```python
async def test_health_check(mock_client):
    resp = await mock_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["api_count"] == 27
```

#### TC-M0S02：27 个 API 全部已注册
```python
async def test_all_27_apis_registered(mock_client):
    resp = await mock_client.get("/openapi.json")
    paths = resp.json()["paths"]
    expected_paths = [
        "/api/v1/production/throughput/summary",
        "/api/v1/production/throughput/by-business-type",
        "/api/v1/production/throughput/monthly-trend",
        "/api/v1/production/container/throughput",
        "/api/v1/production/berth/occupancy-rate",
        "/api/v1/production/vessel/efficiency",
        "/api/v1/production/port-inventory",
        "/api/v1/production/daily-dynamic",
        "/api/v1/production/ships/status",
        "/api/v1/market/throughput/monthly",
        "/api/v1/market/throughput/cumulative",
        "/api/v1/market/trend-chart",
        "/api/v1/market/throughput/by-zone",
        "/api/v1/market/key-enterprise",
        "/api/v1/market/business-segment",
        "/api/v1/customer/basic-info",
        "/api/v1/customer/strategic/throughput",
        "/api/v1/customer/strategic/revenue",
        "/api/v1/customer/contribution/ranking",
        "/api/v1/customer/credit-info",
        "/api/v1/asset/overview",
        "/api/v1/asset/distribution/by-type",
        "/api/v1/asset/equipment/status",
        "/api/v1/asset/historical-trend",
        "/api/v1/invest/plan/summary",
        "/api/v1/invest/plan/monthly-progress",
        "/api/v1/invest/capital-projects",
    ]
    for path in expected_paths:
        assert path in paths, f"API 路径 {path} 未注册"
```

#### TC-M0S03：无 Token 请求返回 401
```python
async def test_unauthenticated_returns_401(mock_client_no_auth):
    resp = await mock_client_no_auth.get(
        "/api/v1/production/throughput/summary",
        params={"date": "2025-03", "dateType": 1}
    )
    assert resp.status_code == 401
```

#### TC-M0S04：超出数据范围返回 404
```python
@pytest.mark.parametrize("date_param", ["2020-01", "2030-12", "2023-12"])
async def test_out_of_range_returns_404(mock_client, date_param):
    resp = await mock_client.get(
        "/api/v1/production/throughput/summary",
        params={"date": date_param, "dateType": 1}
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 404
    assert "超出" in data["msg"] or data["data"] is None
```

#### TC-M0S05：幂等性验证（同参数两次调用结果相同）
```python
@pytest.mark.parametrize("endpoint,params", [
    ("/api/v1/production/throughput/summary",
     {"date": "2025-06", "dateType": 1}),
    ("/api/v1/market/throughput/monthly",
     {"curDateMonth": "2025-06", "yearDateMonth": "2024-06"}),
    ("/api/v1/customer/strategic/throughput",
     {"curDate": "2025", "statisticType": 1}),
])
async def test_idempotency(mock_client, endpoint, params):
    resp1 = await mock_client.get(endpoint, params=params)
    resp2 = await mock_client.get(endpoint, params=params)
    assert resp1.json() == resp2.json(), f"{endpoint} 幂等性失效"
```

---

### TC-M0D：Mock 数据业务合理性验证

#### TC-M0D01：月度吞吐量在合理业务范围内（全 30 个月）
```python
async def test_monthly_throughput_in_business_range(mock_client):
    """验证 30 个月的月度数据均在辽港集团量级范围内"""
    months = []
    for year in [2024, 2025]:
        for month in range(1, 13):
            months.append(f"{year}-{month:02d}")
    for month in range(1, 7):
        months.append(f"2026-{month:02d}")

    for date_str in months:
        resp = await mock_client.get(
            "/api/v1/production/throughput/summary",
            params={"date": date_str, "dateType": 1}
        )
        data = resp.json()["data"]
        assert data is not None, f"{date_str} 返回 null"
        v = data["totalThroughput"]
        assert 1800 <= v <= 4500, \
            f"{date_str} 月度吞吐量 {v} 万吨不在合理范围 [1800, 4500]"
```

#### TC-M0D02：季节性规律体现（2月最低，5月偏高）
```python
async def test_seasonal_pattern_reflected(mock_client):
    """2月吞吐量应低于5月，反映港口季节规律"""
    resp_feb = await mock_client.get(
        "/api/v1/production/throughput/summary",
        params={"date": "2025-02", "dateType": 1}
    )
    resp_may = await mock_client.get(
        "/api/v1/production/throughput/summary",
        params={"date": "2025-05", "dateType": 1}
    )
    feb_val = resp_feb.json()["data"]["totalThroughput"]
    may_val = resp_may.json()["data"]["totalThroughput"]
    assert feb_val < may_val, \
        f"季节性规律异常：2月({feb_val}) 应 < 5月({may_val})"
```

#### TC-M0D03：2025年同比增速高于2024年（业务规律）
```python
async def test_yoy_growth_trend(mock_client):
    """2025年月度吞吐量整体应高于2024年同期（同比增长 >0）"""
    months = [f"{m:02d}" for m in [3, 4, 5, 6, 7, 8, 9]]  # 避开春节月份
    for m in months:
        resp_2025 = await mock_client.get(
            "/api/v1/production/throughput/summary",
            params={"date": f"2025-{m}", "dateType": 1}
        )
        resp_2024 = await mock_client.get(
            "/api/v1/production/throughput/summary",
            params={"date": f"2024-{m}", "dateType": 1}
        )
        v_2025 = resp_2025.json()["data"]["totalThroughput"]
        v_2024 = resp_2024.json()["data"]["totalThroughput"]
        assert v_2025 > v_2024, \
            f"{m}月：2025({v_2025}) 应 > 2024({v_2024})（同比增长应为正）"
```

#### TC-M0D04：各港区吞吐量之和≈全港总量（跨域一致性）
```python
async def test_zone_sum_matches_total(mock_client):
    """M13各港区之和应与M10全港总量大致吻合（允许5%偏差）"""
    month = "2025-06"
    resp_total = await mock_client.get(
        "/api/v1/market/throughput/monthly",
        params={"curDateMonth": month, "yearDateMonth": "2024-06"}
    )
    resp_zones = await mock_client.get(
        "/api/v1/market/throughput/by-zone",
        params={"curDateMonth": month, "yearDateMonth": "2024-06"}
    )
    total = resp_total.json()["data"]["curMonthTotal"]
    zone_sum = sum(z["throughput"] for z in resp_zones.json()["data"])
    deviation = abs(zone_sum - total) / total
    assert deviation <= 0.05, \
        f"港区之和({zone_sum:.1f}) 与全港总量({total:.1f}) 偏差 {deviation:.1%} > 5%"
```

#### TC-M0D05：各业务板块 shareRatio 之和 = 100%
```python
async def test_segment_share_sums_to_100(mock_client):
    resp = await mock_client.get(
        "/api/v1/market/business-segment",
        params={"curDateMonth": "2025-06", "yearDateMonth": "2024-06",
                "statisticType": 0}
    )
    shares = [s["shareRatio"] for s in resp.json()["data"]]
    total = sum(shares)
    assert abs(total - 100.0) <= 0.5, \
        f"业务板块占比之和 {total:.1f}% ≠ 100%"
```

#### TC-M0D06：集装箱年吞吐量在 TEU 合理范围
```python
async def test_container_teu_in_range(mock_client):
    for year in ["2024", "2025"]:
        resp = await mock_client.get(
            "/api/v1/production/container/throughput",
            params={"dateYear": year}
        )
        data = resp.json()["data"]
        teu = data["totalTeu"]
        assert 3_800_000 <= teu <= 5_200_000, \
            f"{year}年集装箱吞吐量 {teu} TEU 不在合理范围"
        # 内外贸之和=总量
        assert abs(data["foreignTradeTeu"] + data["domesticTradeTeu"] - teu) <= 100, \
            "内贸+外贸 ≠ 总TEU"
        # 外贸占比 65-75%
        foreign_ratio = data["foreignTradeTeu"] / teu
        assert 0.60 <= foreign_ratio <= 0.80, \
            f"外贸占比 {foreign_ratio:.1%} 超出合理范围 [60%, 80%]"
```

#### TC-M0D07：战略客户 TOP10 贡献率之和 ≤ 总贡献上限
```python
async def test_strategic_customer_contribution(mock_client):
    resp = await mock_client.get(
        "/api/v1/customer/strategic/throughput",
        params={"curDate": "2025", "statisticType": 1}
    )
    customers = resp.json()["data"]
    assert 25 <= len(customers) <= 60, \
        f"战略客户数量 {len(customers)} 超出合理范围 [25, 60]"
    top10_contribution = sum(c["contributionRate"] for c in customers[:10])
    assert 45 <= top10_contribution <= 75, \
        f"TOP10战略客户贡献率之和 {top10_contribution:.1f}% 超出合理范围 [45%, 75%]"
```

#### TC-M0D08：投资完成率与月份正相关（年末高于年初）
```python
async def test_invest_completion_rate_increases_over_year(mock_client):
    resp_q1 = await mock_client.get(
        "/api/v1/invest/plan/summary", params={"currYear": "2025"}
    )
    # 通过月度进度数据验证：6月累计 > 3月累计
    resp_progress = await mock_client.get(
        "/api/v1/invest/plan/monthly-progress",
        params={"startMonth": "2025-01", "endMonth": "2025-12"}
    )
    progress = resp_progress.json()["data"]
    mar_cumulative = next(p["cumulativeActual"] for p in progress if p["month"] == "2025-03")
    jun_cumulative = next(p["cumulativeActual"] for p in progress if p["month"] == "2025-06")
    assert jun_cumulative > mar_cumulative, \
        f"6月累计投资({jun_cumulative}) 应 > 3月({mar_cumulative})"
```

#### TC-M0D09：信用等级分布符合业务合理性
```python
async def test_credit_level_distribution(mock_client):
    resp = await mock_client.get("/api/v1/customer/credit-info")
    customers = resp.json()["data"]
    levels = [c["creditLevel"] for c in customers]
    # AAA+AA+A 应占多数（健康客户结构）
    high_quality = sum(1 for l in levels if l in ("AAA", "AA", "A"))
    assert high_quality / len(levels) >= 0.75, \
        f"高质量客户(AAA/AA/A)占比 {high_quality/len(levels):.1%} 过低"
    # C 级客户不超过 10%
    c_level = sum(1 for l in levels if l == "C")
    assert c_level / len(levels) <= 0.10
```

#### TC-M0D10：设备状态"正常"占比符合运营规律
```python
async def test_equipment_status_normal_ratio(mock_client):
    for year in ["2024", "2025", "2026"]:
        resp = await mock_client.get(
            "/api/v1/asset/equipment/status",
            params={"dateYear": year, "type": 1}
        )
        statuses = resp.json()["data"]
        normal = next((s for s in statuses if s["status"] == "正常"), None)
        assert normal is not None
        assert 0.80 <= normal["ratio"] <= 0.92, \
            f"{year}年设备正常率 {normal['ratio']:.1%} 超出合理范围 [80%, 92%]"
```

---

### TC-M0P：Mock Server 性能基准

#### TC-M0P01：单 API 响应时间 ≤ 200ms
```python
import time
@pytest.mark.parametrize("endpoint,params", [
    ("/api/v1/production/throughput/summary",
     {"date": "2025-06", "dateType": 1}),
    ("/api/v1/market/throughput/monthly",
     {"curDateMonth": "2025-06", "yearDateMonth": "2024-06"}),
    ("/api/v1/customer/strategic/throughput",
     {"curDate": "2025", "statisticType": 1}),
    ("/api/v1/invest/plan/summary", {"currYear": "2025"}),
])
async def test_single_api_response_time(mock_client, endpoint, params):
    start = time.time()
    resp = await mock_client.get(endpoint, params=params)
    elapsed_ms = (time.time() - start) * 1000
    assert resp.status_code == 200
    assert elapsed_ms <= 200, \
        f"{endpoint} 响应时间 {elapsed_ms:.0f}ms > 200ms"
```

#### TC-M0P02：8 个 API 并发调用总时间 ≤ 500ms（场景 C 基准）
```python
async def test_concurrent_8_apis_under_500ms(mock_client):
    """模拟场景 C（月报生成）的并发 API 调用性能基准"""
    start = time.time()
    tasks = [
        mock_client.get("/api/v1/production/throughput/summary",
                        params={"date": "2026-03", "dateType": 1}),
        mock_client.get("/api/v1/production/container/throughput",
                        params={"dateYear": "2026"}),
        mock_client.get("/api/v1/production/berth/occupancy-rate",
                        params={"startDate": "2026-03-01", "endDate": "2026-03-31",
                                "groupBy": "region"}),
        mock_client.get("/api/v1/production/vessel/efficiency",
                        params={"startMonth": "2026-03", "endMonth": "2026-03"}),
        mock_client.get("/api/v1/market/throughput/monthly",
                        params={"curDateMonth": "2026-03", "yearDateMonth": "2025-03"}),
        mock_client.get("/api/v1/market/throughput/by-zone",
                        params={"curDateMonth": "2026-03", "yearDateMonth": "2025-03"}),
        mock_client.get("/api/v1/market/key-enterprise",
                        params={"businessSegment": "集装箱",
                                "curDateMonth": "2026-03", "statisticType": 0}),
        mock_client.get("/api/v1/invest/plan/monthly-progress",
                        params={"startMonth": "2026-01", "endMonth": "2026-03"}),
    ]
    await asyncio.gather(*tasks)
    elapsed_ms = (time.time() - start) * 1000
    assert elapsed_ms <= 500, \
        f"8个并发 API 总耗时 {elapsed_ms:.0f}ms > 500ms（Mock Server 性能不足）"
```

---

## 五、Phase 0 完成标准

| 验收项 | 判断标准 |
|--------|----------|
| 27 个 API 全部可用 | TC-M0S02 通过 |
| Token 鉴权生效 | TC-M0S03 通过 |
| 数据范围边界正确 | TC-M0S04 通过（超范围返回404） |
| 幂等性保证 | TC-M0S05 全部通过 |
| 业务量级合理 | TC-M0D01~TC-M0D10 全部通过 |
| 跨域数据一致性 | TC-M0D04（港区≈全港）、TC-M0D05（板块=100%） |
| 性能基准 | TC-M0P01（单 API ≤200ms）、TC-M0P02（8并发≤500ms） |
| 所有后续 Phase 的 conftest.py 已引用 `mock_server` fixture | 代码 Review 确认 |


---

## 六、验收检查单

### Mock Server 服务可用性

| 验收项 | 判断标准 | 状态 |
|--------|----------|------|
| 27 个 API 全部注册 | TC-M0S02 通过 | ⬜ |
| Bearer Token 鉴权生效 | TC-M0S03 通过（无 Token → 401）| ⬜ |
| 数据范围边界正确 | TC-M0S04 通过（超范围 → code=404）| ⬜ |
| 同参数幂等性 | TC-M0S05 全部通过 | ⬜ |

### Mock 数据业务合理性

| 验收项 | 判断标准 | 状态 |
|--------|----------|------|
| 月度吞吐量在辽港量级 [1800, 4500] 万吨 | TC-M0D01 通过 | ⬜ |
| 季节性规律：2月 < 5月 | TC-M0D02 通过 | ⬜ |
| 同比：2025年 > 2024年同期 | TC-M0D03 通过 | ⬜ |
| 跨域一致性：港区之和 ≈ 全港总量（±5%）| TC-M0D04 通过 | ⬜ |
| 板块占比之和 = 100% | TC-M0D05 通过 | ⬜ |
| 集装箱 TEU 在 [380万, 520万] | TC-M0D06 通过 | ⬜ |
| 战略客户 TOP10 贡献率 [45%, 75%] | TC-M0D07 通过 | ⬜ |
| 投资完成率随月份递增 | TC-M0D08 通过 | ⬜ |
| 信用等级高质量占比 ≥ 75% | TC-M0D09 通过 | ⬜ |
| 设备正常率 [80%, 92%] | TC-M0D10 通过 | ⬜ |

### 性能验收

| 指标 | 要求 | 状态 |
|------|------|------|
| 单 API 响应时间 | ≤ 200ms | ⬜ |
| 8 个并发 API 总时间 | ≤ 500ms | ⬜ |
