"""Endpoint Configuration — 数据源端点配置。

定义 Mock API 的 27 个端点信息，供规划层 Prompt 注入。
"""
from __future__ import annotations

ENDPOINT_REGISTRY: dict[str, dict] = {
    # ── 生产运营域 (M01-M09) ─────────────────────────────────
    "getThroughputSummary": {
        "id": "M01",
        "domain": "production",
        "when_to_use": "全港总吞吐量汇总（生产视角）",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    "getThroughputByBusinessType": {
        "id": "M02",
        "domain": "production",
        "when_to_use": "按业务板块分类吞吐量（集装箱/散杂货/油化品/商品车）",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    "getThroughputTrendByMonth": {
        "id": "M03",
        "domain": "production",
        "when_to_use": "月度吞吐量趋势折线图数据（近 30 个月）",
        "known_caveats": "",
        "required_params": ["startMonth", "endMonth"],
    },
    "getContainerThroughput": {
        "id": "M04",
        "domain": "production",
        "when_to_use": "集装箱 TEU 专项查询（含 TEU 和重量双单位）",
        "known_caveats": "集装箱有 TEU 和吨双单位，不可直接加总",
        "required_params": ["curDateMonth"],
    },
    "getBerthOccupancyRate": {
        "id": "M05",
        "domain": "production",
        "when_to_use": "各港区泊位占用率分析",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    "getVesselEfficiency": {
        "id": "M06",
        "domain": "production",
        "when_to_use": "船舶作业效率指标",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    "getPortInventory": {
        "id": "M07",
        "domain": "production",
        "when_to_use": "港存货物量（在港库存）",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    "getDailyProductionDynamic": {
        "id": "M08",
        "domain": "production",
        "when_to_use": "日度生产动态数据",
        "known_caveats": "",
        "required_params": ["date"],
    },
    "getShipStatus": {
        "id": "M09",
        "domain": "production",
        "when_to_use": "在港/待泊船舶状态",
        "known_caveats": "",
        "required_params": ["date"],
    },
    # ── 市场商务域 (M10-M15) ─────────────────────────────────
    "getMarketMonthlyThroughput": {
        "id": "M10",
        "domain": "market",
        "when_to_use": "市场当月吞吐量完成情况（市场视角，非生产视角）",
        "known_caveats": "与 M01 区别：M10 是市场域口径，M01 是生产域口径",
        "required_params": ["curDateMonth"],
    },
    "getMarketCumulativeThroughput": {
        "id": "M11",
        "domain": "market",
        "when_to_use": "市场年度累计吞吐量",
        "known_caveats": "",
        "required_params": ["year"],
    },
    "getMarketTrendChart": {
        "id": "M12",
        "domain": "market",
        "when_to_use": "市场趋势图（按业务板块）",
        "known_caveats": "businessSegment 为【必填】参数，枚举值：集装箱/散杂货/油化品/商品车/全货类",
        "required_params": ["year", "businessSegment"],
    },
    "getMarketZoneThroughput": {
        "id": "M13",
        "domain": "market",
        "when_to_use": "各港区吞吐量对比",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    "getKeyEnterpriseContribution": {
        "id": "M14",
        "domain": "market",
        "when_to_use": "重点企业贡献排名",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    "getMarketBusinessSegment": {
        "id": "M15",
        "domain": "market",
        "when_to_use": "业务板块占比结构",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    # ── 客户管理域 (M16-M20) ─────────────────────────────────
    "getCustomerBasicInfo": {
        "id": "M16",
        "domain": "customer",
        "when_to_use": "客户基本信息查询",
        "known_caveats": "",
        "required_params": [],
    },
    "getStrategicCustomerThroughput": {
        "id": "M17",
        "domain": "customer",
        "when_to_use": "战略客户货量专项分析",
        "known_caveats": "仅用于战略级客户专项分析，通用排名查询应使用 M19",
        "required_params": ["curDateMonth"],
    },
    "getStrategicCustomerRevenue": {
        "id": "M18",
        "domain": "customer",
        "when_to_use": "战略客户收入专项",
        "known_caveats": "",
        "required_params": ["curDateMonth"],
    },
    "getCustomerContributionRanking": {
        "id": "M19",
        "domain": "customer",
        "when_to_use": "客户贡献排名（全量排名）",
        "known_caveats": "topN 上限为 50，超限自动截断",
        "required_params": ["curDateMonth"],
    },
    "getCustomerCreditInfo": {
        "id": "M20",
        "domain": "customer",
        "when_to_use": "客户信用信息查询",
        "known_caveats": "",
        "required_params": [],
    },
    # ── 资产管理域 (M21-M24) ─────────────────────────────────
    "getAssetOverview": {
        "id": "M21",
        "domain": "asset",
        "when_to_use": "资产总览（净值/原值/折旧）",
        "known_caveats": "",
        "required_params": [],
    },
    "getAssetDistributionByType": {
        "id": "M22",
        "domain": "asset",
        "when_to_use": "资产分类分布",
        "known_caveats": "",
        "required_params": [],
    },
    "getEquipmentFacilityStatus": {
        "id": "M23",
        "domain": "asset",
        "when_to_use": "设备设施状态（完好率/老化率）",
        "known_caveats": "",
        "required_params": [],
    },
    "getAssetHistoricalTrend": {
        "id": "M24",
        "domain": "asset",
        "when_to_use": "资产历史趋势（净值变化）",
        "known_caveats": "",
        "required_params": ["startYear", "endYear"],
    },
    # ── 投资管理域 (M25-M27) ─────────────────────────────────
    "getInvestPlanSummary": {
        "id": "M25",
        "domain": "invest",
        "when_to_use": "投资计划汇总（年度完成率/进度总览）",
        "known_caveats": "汇总数据，非月度明细。月度进度曲线应使用 M26",
        "required_params": ["year"],
    },
    "getInvestPlanProgress": {
        "id": "M26",
        "domain": "invest",
        "when_to_use": "投资月度进度节奏（月度执行曲线/进度偏差）",
        "known_caveats": "月度明细数据。年度完成率汇总应使用 M25",
        "required_params": ["year"],
    },
    "getCapitalProjectList": {
        "id": "M27",
        "domain": "invest",
        "when_to_use": "资本类项目明细列表",
        "known_caveats": "",
        "required_params": ["year"],
    },
}

VALID_ENDPOINT_IDS = set(ENDPOINT_REGISTRY.keys())

# M-code → endpoint function name mapping (e.g. "M01" → "getThroughputSummary")
MCODE_TO_ENDPOINT: dict[str, str] = {
    info["id"]: ep_name
    for ep_name, info in ENDPOINT_REGISTRY.items()
}


def resolve_endpoint_id(raw_id: str) -> str | None:
    """Resolve an endpoint reference to a valid endpoint function name.

    Accepts both full names (getThroughputSummary) and M-codes (M01).
    Returns the resolved name, or None if unrecognizable.
    """
    if raw_id in VALID_ENDPOINT_IDS:
        return raw_id
    # Try M-code lookup (case-insensitive)
    resolved = MCODE_TO_ENDPOINT.get(raw_id.upper())
    if resolved:
        return resolved
    return None


def get_endpoints_description(domain_hint: str | None = None) -> str:
    """Format endpoint descriptions for injection into planning prompt.

    If domain_hint is provided, endpoints from that domain are listed first
    with a priority marker.
    """
    lines = []
    priority_eps = []
    other_eps = []

    for ep_id, info in ENDPOINT_REGISTRY.items():
        ep_line = f"  - {ep_id} ({info['id']}): {info['when_to_use']}"
        if info["known_caveats"]:
            ep_line += f"\n    ⚠️ 约束: {info['known_caveats']}"
        if info["required_params"]:
            ep_line += f"\n    必填参数: {', '.join(info['required_params'])}"

        if domain_hint and info["domain"] == domain_hint:
            priority_eps.append(ep_line)
        else:
            other_eps.append(ep_line)

    if priority_eps:
        lines.append(f"【推荐端点（{domain_hint} 域）】")
        lines.extend(priority_eps)
        lines.append("\n【其他可用端点】")
    lines.extend(other_eps)
    return "\n".join(lines)


def is_valid_endpoint(endpoint_id: str) -> bool:
    """Check if an endpoint ID exists in the registry."""
    return endpoint_id in VALID_ENDPOINT_IDS
