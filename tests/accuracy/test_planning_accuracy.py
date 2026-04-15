"""TC-PLAN-ACC: 规划合理性准确率测试（真实 LLM 调用）。

文件：tests/accuracy/test_planning_accuracy.py
标记：@pytest.mark.llm_real
目标：给定结构化意图，规划合理性（任务数合规 + 端点选取正确 + 无幻觉）≥ 90%

数据集覆盖：单 API 查询(10) + 多 API 图文(7) + 多域报告(4) + 歧义消除(4) = 25 个场景。
端点覆盖：27/27 = 100%（含 M06/M07/M08/M09/M16/M22 等原零覆盖端点）。
"""
import json

import pytest

from backend.agent.planning import PlanningEngine, _has_cycle
from backend.agent.skills import VALID_SKILL_IDS
from backend.agent.endpoints import VALID_ENDPOINT_IDS

# ═══════════════════════════════════════════════════════════════
#  规划准确率测试数据集：(意图 dict, 验证规则 dict)
# ═══════════════════════════════════════════════════════════════

PLANNING_ACCURACY_DATASET = [
    # ── A 类：单 API 查询 (10 个, simple_table) ──────────────────
    # A01: 全港月度吞吐量 → M01 getThroughputSummary
    (
        {"time_range": "2026-03", "domain": "production", "output_format": "simple_table",
         "analysis_subject": "2026年3月全港货物吞吐量完成情况汇总"},
        {"task_count_range": (2, 3), "required_endpoints": ["getThroughputSummary"],
         "forbidden_endpoints": ["getMarketMonthlyThroughput"], "must_not_have_report_structure": True},
    ),
    # A02: 泊位占用率 → M05 getBerthOccupancyRate
    (
        {"time_range": "2026-03", "domain": "production", "analysis_type": "occupancy",
         "output_format": "simple_table", "analysis_subject": "2026年3月各港区泊位占用率对比"},
        {"task_count_range": (2, 3), "required_endpoints": ["getBerthOccupancyRate"],
         "must_not_have_report_structure": True},
    ),
    # A03: 船舶作业效率 → M06 getVesselEfficiency (新增，填补零覆盖)
    (
        {"time_range": "2026-03", "domain": "production", "analysis_type": "efficiency",
         "output_format": "simple_table", "analysis_subject": "本月船舶作业效率指标查询"},
        {"task_count_range": (2, 3), "required_endpoints": ["getVesselEfficiency"],
         "forbidden_endpoints": ["getBerthOccupancyRate"], "must_not_have_report_structure": True},
    ),
    # A04: 港存货物量 → M07 getPortInventory (新增，填补零覆盖)
    (
        {"time_range": "2026-03", "domain": "production", "output_format": "simple_table",
         "analysis_subject": "营口港区当前港存货物量查询"},
        {"task_count_range": (2, 3), "required_endpoints": ["getPortInventory"],
         "must_not_have_report_structure": True},
    ),
    # A05: 日度生产动态 → M08 getDailyProductionDynamic (新增，填补零覆盖)
    (
        {"time_range": "2026-03-15", "domain": "production", "output_format": "simple_table",
         "analysis_subject": "2026年3月15日全港生产动态数据"},
        {"task_count_range": (2, 3), "required_endpoints": ["getDailyProductionDynamic"],
         "must_not_have_report_structure": True},
    ),
    # A06: 在港船舶状态 → M09 getShipStatus (新增，填补零覆盖)
    (
        {"time_range": "2026-03-15", "domain": "production", "output_format": "simple_table",
         "analysis_subject": "今日在港船舶及待泊船舶状态一览"},
        {"task_count_range": (2, 3), "required_endpoints": ["getShipStatus"],
         "forbidden_endpoints": ["getVesselEfficiency"], "must_not_have_report_structure": True},
    ),
    # A07: 集装箱TEU完成率 → M04 getContainerThroughput
    (
        {"cargo_type": "集装箱", "time_range": "2026年", "domain": "production",
         "analysis_type": "target_completion", "output_format": "simple_table",
         "analysis_subject": "2026年集装箱TEU目标完成率"},
        {"task_count_range": (2, 3), "required_endpoints": ["getContainerThroughput"],
         "must_not_have_report_structure": True},
    ),
    # A08: 客户基本信息 → M16 getCustomerBasicInfo (新增，填补零覆盖)
    (
        {"domain": "customer", "output_format": "simple_table",
         "analysis_subject": "中远海运集装箱运输有限公司基本信息查询"},
        {"task_count_range": (2, 3), "required_endpoints": ["getCustomerBasicInfo"],
         "forbidden_endpoints": ["getStrategicCustomerThroughput", "getCustomerContributionRanking"],
         "must_not_have_report_structure": True},
    ),
    # A09: 资产分类分布 → M22 getAssetDistributionByType (新增，填补零覆盖)
    (
        {"domain": "asset", "output_format": "simple_table",
         "analysis_subject": "全港固定资产按类型分类的分布情况"},
        {"task_count_range": (2, 3), "required_endpoints": ["getAssetDistributionByType"],
         "forbidden_endpoints": ["getAssetOverview"], "must_not_have_report_structure": True},
    ),
    # A10: 资本类项目明细 → M27 getCapitalProjectList
    (
        {"domain": "invest", "time_range": "2026年", "output_format": "simple_table",
         "analysis_subject": "2026年在建资本类投资项目明细列表"},
        {"task_count_range": (2, 3), "required_endpoints": ["getCapitalProjectList"],
         "must_not_have_report_structure": True},
    ),
    # ── B 类：多 API 图文分析 (7 个, chart_text) ─────────────────
    # B01: 集装箱趋势+归因 → M03/M04 + M14/M02/M15
    (
        {"cargo_type": "集装箱", "time_range": "2026年Q1", "domain": "production",
         "analysis_type": "trend_with_attribution", "output_format": "chart_text",
         "analysis_subject": "2026年一季度集装箱吞吐量趋势及变动归因分析"},
        {"task_count_range": (3, 6),
         "required_endpoints_any": ["getThroughputTrendByMonth", "getContainerThroughput"],
         "required_endpoints_any_2": ["getKeyEnterpriseContribution", "getThroughputByBusinessType", "getMarketBusinessSegment"]},
    ),
    # B02: 散杂货市场同比+港区对比 → M12/M02 + M13/M15/M11
    (
        {"cargo_type": "散杂货", "time_range": "2026年", "domain": "market",
         "analysis_type": "yoy_comparison", "output_format": "chart_text",
         "analysis_subject": "散杂货市场同比分析及各港区吞吐量对比"},
        {"task_count_range": (3, 5),
         "required_endpoints_any": ["getMarketTrendChart", "getThroughputByBusinessType"],
         "required_endpoints_any_2": ["getMarketZoneThroughput", "getMarketBusinessSegment", "getMarketCumulativeThroughput"]},
    ),
    # B03: 战略客户贡献+信用风险 → M17/M18 + M20/M19
    (
        {"domain": "customer", "time_range": "2026年上半年",
         "analysis_type": "contribution_risk", "output_format": "chart_text",
         "analysis_subject": "战略客户货量贡献分析及信用风险评估"},
        {"task_count_range": (3, 5),
         "required_endpoints_any": ["getStrategicCustomerThroughput", "getStrategicCustomerRevenue"],
         "required_endpoints_any_2": ["getCustomerCreditInfo", "getCustomerContributionRanking"]},
    ),
    # B04: 生产运营综合(效率+港存) → M06/M07 + M08/M09/M05 (新增)
    (
        {"domain": "production", "time_range": "2026-03",
         "analysis_type": "operational_overview", "output_format": "chart_text",
         "analysis_subject": "3月份港口作业效率与港存货物量综合分析"},
        {"task_count_range": (3, 5),
         "required_endpoints_any": ["getVesselEfficiency", "getPortInventory"],
         "required_endpoints_any_2": ["getDailyProductionDynamic", "getShipStatus", "getBerthOccupancyRate"]},
    ),
    # B05: 资产结构+设备+趋势 → M22/M23 + M24/M21 (新增)
    (
        {"domain": "asset", "analysis_type": "comprehensive_asset",
         "output_format": "chart_text",
         "analysis_subject": "全港资产分类结构及设备健康状况趋势分析"},
        {"task_count_range": (3, 5),
         "required_endpoints_any": ["getAssetDistributionByType", "getEquipmentFacilityStatus"],
         "required_endpoints_any_2": ["getAssetHistoricalTrend", "getAssetOverview"]},
    ),
    # B06: 投资进度节奏+偏差 → M26+M25
    (
        {"domain": "invest", "analysis_type": "progress_deviation",
         "output_format": "chart_text",
         "analysis_subject": "2026年投资月度执行节奏与年度计划完成率偏差分析"},
        {"task_count_range": (3, 5),
         "required_endpoints_any": ["getInvestPlanProgress", "getInvestPlanSummary"]},
    ),
    # B07: 客户画像综合 → M16/M20 + M19/M17 (新增)
    (
        {"domain": "customer", "time_range": "2026-03",
         "analysis_type": "customer_profile", "output_format": "chart_text",
         "analysis_subject": "重点客户画像分析：基本信息、信用评级与贡献排名"},
        {"task_count_range": (3, 5),
         "required_endpoints_any": ["getCustomerBasicInfo", "getCustomerCreditInfo"],
         "required_endpoints_any_2": ["getCustomerContributionRanking", "getStrategicCustomerThroughput"]},
    ),
    # ── C 类：多域报告 (4 个, full_report) ───────────────────────
    # C01: 月度经营月报（生产+市场+投资）
    (
        {"output_format": "full_report", "time_range": "2026-03",
         "report_dimensions": ["production", "market", "invest"],
         "analysis_subject": "2026年3月月度经营分析报告"},
        {"task_count_range": (5, 8), "must_have_report_structure": True,
         "required_endpoints_any": ["getThroughputSummary", "getMarketMonthlyThroughput"],
         "all_endpoints_must_be_valid": True, "all_skills_must_be_registered": True,
         "dag_must_be_acyclic": True},
    ),
    # C02: 年度货量预测报告
    (
        {"output_format": "full_report", "analysis_type": "forecast_2027",
         "time_range": "2024-2026年历史",
         "analysis_subject": "基于2024-2026历史数据的2027年全港货量预测报告"},
        {"task_count_range": (5, 8), "must_have_report_structure": True,
         "required_endpoints_any": ["getThroughputTrendByMonth", "getMarketCumulativeThroughput"],
         "all_endpoints_must_be_valid": True, "all_skills_must_be_registered": True},
    ),
    # C03: 客户+资产年度报告 (新增)
    (
        {"output_format": "full_report", "time_range": "2025年",
         "report_dimensions": ["customer", "asset"],
         "analysis_subject": "2025年度客户经营与资产管理综合报告"},
        {"task_count_range": (5, 8), "must_have_report_structure": True,
         "required_endpoints_any": ["getStrategicCustomerRevenue", "getCustomerContributionRanking", "getStrategicCustomerThroughput"],
         "required_endpoints_any_2": ["getAssetOverview", "getAssetDistributionByType", "getEquipmentFacilityStatus"],
         "all_endpoints_must_be_valid": True, "all_skills_must_be_registered": True,
         "dag_must_be_acyclic": True},
    ),
    # C04: 五域全量月报 (新增，最大压力测试)
    (
        {"output_format": "full_report", "time_range": "2026-03",
         "report_dimensions": ["production", "market", "customer", "asset", "invest"],
         "analysis_subject": "2026年3月全港五域综合经营分析报告"},
        {"task_count_range": (5, 8), "must_have_report_structure": True,
         "all_endpoints_must_be_valid": True, "all_skills_must_be_registered": True,
         "dag_must_be_acyclic": True, "all_dependencies_must_exist": True},
    ),
    # ── D 类：路由歧义消除 (4 个) ────────────────────────────────
    # D01: 市场 vs 生产吞吐量 → M10 正确, M01 错误
    (
        {"domain": "market", "time_range": "2026-03", "analysis_type": "yoy_comparison",
         "output_format": "simple_table", "analysis_subject": "本月市场吞吐量完成情况同比分析"},
        {"task_count_range": (2, 3), "required_endpoints": ["getMarketMonthlyThroughput"],
         "forbidden_endpoints": ["getThroughputSummary"]},
    ),
    # D02: 全量排名 vs 战略客户 → M19 正确, M17 错误
    (
        {"domain": "customer", "analysis_type": "contribution_ranking",
         "output_format": "simple_table", "analysis_subject": "本月全量客户贡献排名Top10"},
        {"task_count_range": (2, 3), "required_endpoints": ["getCustomerContributionRanking"],
         "forbidden_endpoints": ["getStrategicCustomerThroughput"]},
    ),
    # D03: 船舶状态 vs 效率 → M09 正确, M06 错误 (新增)
    (
        {"domain": "production", "time_range": "2026-03-15", "output_format": "simple_table",
         "analysis_subject": "当前在港和待泊的船舶实时状态查询"},
        {"task_count_range": (2, 3), "required_endpoints": ["getShipStatus"],
         "forbidden_endpoints": ["getVesselEfficiency"]},
    ),
    # D04: 投资月度进度 vs 年度汇总 → M26 正确, M25 错误 (新增)
    (
        {"domain": "invest", "time_range": "2026年", "output_format": "simple_table",
         "analysis_subject": "全港投资月度执行进度曲线数据"},
        {"task_count_range": (2, 3), "required_endpoints": ["getInvestPlanProgress"],
         "forbidden_endpoints": ["getInvestPlanSummary"]},
    ),
]

SCENARIO_IDS = [
    "A01-production-total-throughput",
    "A02-production-berth-occupancy",
    "A03-production-vessel-efficiency",
    "A04-production-port-inventory",
    "A05-production-daily-dynamic",
    "A06-production-ship-status",
    "A07-production-container-TEU",
    "A08-customer-basic-info",
    "A09-asset-distribution-by-type",
    "A10-invest-capital-project-list",
    "B01-container-trend-attribution",
    "B02-bulk-market-yoy-comparison",
    "B03-strategic-customer-risk",
    "B04-production-vessel-inventory-dynamic",
    "B05-asset-structure-equipment-trend",
    "B06-invest-progress-deviation",
    "B07-customer-profile-credit-ranking",
    "C01-monthly-operations-report",
    "C02-annual-forecast-report",
    "C03-customer-asset-annual-report",
    "C04-five-domain-full-report",
    "D01-market-not-production-throughput",
    "D02-ranking-not-strategic-customer",
    "D03-ship-status-not-efficiency",
    "D04-invest-monthly-not-summary",
]


# ═══════════════════════════════════════════════════════════════
#  验证函数
# ═══════════════════════════════════════════════════════════════

def _extract_endpoints_from_plan(plan_dict: dict) -> set[str]:
    """Extract all endpoint_ids used in a plan dict.

    Handles both params.endpoint_id (our implementation) and
    top-level endpoint field (spec convention).
    """
    endpoints = set()
    for t in plan_dict.get("tasks", []):
        # Primary: params.endpoint_id
        ep = t.get("params", {}).get("endpoint_id")
        if ep:
            endpoints.add(ep)
        # Fallback: top-level endpoint field
        ep2 = t.get("endpoint")
        if ep2:
            endpoints.add(ep2)
    return endpoints


def _extract_skills_from_plan(plan_dict: dict) -> set[str]:
    """Extract all skill ids used in a plan dict."""
    return {t.get("skill") for t in plan_dict.get("tasks", []) if t.get("skill")}


def validate_plan(plan_dict: dict, rules: dict) -> tuple[bool, str]:
    """根据规则验证规划方案，返回 (通过, 失败原因)。"""
    tasks = plan_dict.get("tasks", [])

    # 任务数量范围
    if "task_count_range" in rules:
        lo, hi = rules["task_count_range"]
        if not (lo <= len(tasks) <= hi):
            return False, f"任务数 {len(tasks)} 不在范围 [{lo},{hi}]"

    endpoints_used = _extract_endpoints_from_plan(plan_dict)
    skills_used = _extract_skills_from_plan(plan_dict)

    # 必须包含的端点（全部）
    if "required_endpoints" in rules:
        for ep in rules["required_endpoints"]:
            if ep not in endpoints_used:
                return False, f"缺少必要端点 {ep}，实际使用: {endpoints_used}"

    # 必须包含的端点（至少一个）
    if "required_endpoints_any" in rules:
        if not any(ep in endpoints_used for ep in rules["required_endpoints_any"]):
            return False, (
                f"应使用以下端点之一: {rules['required_endpoints_any']}，"
                f"实际使用: {endpoints_used}"
            )

    # 第二组可选端点
    if "required_endpoints_any_2" in rules:
        if not any(ep in endpoints_used for ep in rules["required_endpoints_any_2"]):
            return False, (
                f"应使用以下端点之一(组2): {rules['required_endpoints_any_2']}，"
                f"实际使用: {endpoints_used}"
            )

    # 禁止使用的端点
    if "forbidden_endpoints" in rules:
        for ep in rules["forbidden_endpoints"]:
            if ep in endpoints_used:
                return False, f"不应使用端点 {ep}"

    # 禁止使用的技能
    if "forbidden_skills" in rules:
        for sk in rules["forbidden_skills"]:
            if sk in skills_used:
                return False, f"不应使用技能 {sk}"

    # 所有技能必须注册
    if rules.get("all_skills_must_be_registered"):
        invalid = skills_used - VALID_SKILL_IDS
        if invalid:
            return False, f"幻觉技能: {invalid}"

    # 所有端点必须合法
    if rules.get("all_endpoints_must_be_valid"):
        invalid = endpoints_used - VALID_ENDPOINT_IDS
        if invalid:
            return False, f"幻觉端点: {invalid}"

    # DAG 无环
    if rules.get("dag_must_be_acyclic"):
        graph = {t["task_id"]: t.get("depends_on", []) for t in tasks}
        if _has_cycle(graph):
            return False, "任务依赖图存在环"

    # 依赖引用存在性
    if rules.get("all_dependencies_must_exist"):
        task_ids = {t["task_id"] for t in tasks}
        for t in tasks:
            for dep in t.get("depends_on", []):
                if dep not in task_ids:
                    return False, f"任务 {t['task_id']} 依赖不存在的 {dep}"

    # report_structure 检查
    if rules.get("must_have_report_structure"):
        if not plan_dict.get("report_structure"):
            return False, "full_report 场景缺少 report_structure"

    if rules.get("must_not_have_report_structure"):
        if plan_dict.get("report_structure"):
            return False, "simple_table 场景不应有 report_structure"

    return True, ""


# ═══════════════════════════════════════════════════════════════
#  测试用例
# ═══════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def planning_engine(real_llm):
    """PlanningEngine with real LLM (module-scoped for reuse)."""
    return PlanningEngine(llm=real_llm, llm_timeout=120.0, max_retries=3)


@pytest.mark.llm_real
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "intent,rules",
    PLANNING_ACCURACY_DATASET,
    ids=SCENARIO_IDS,
)
async def test_planning_quality_per_scenario(planning_engine, intent, rules):
    """单场景规划合理性验证（真实 LLM 调用）。"""
    plan = await planning_engine.generate_plan(intent)
    plan_dict = plan.model_dump()
    passed, reason = validate_plan(plan_dict, rules)
    if not passed:
        # Print the full plan for debugging
        print(f"\n[FAIL] 意图: {json.dumps(intent, ensure_ascii=False)}")
        print(f"[FAIL] 原因: {reason}")
        tasks_summary = [
            {
                "task_id": t.task_id,
                "skill": t.skill,
                "endpoint": t.params.get("endpoint_id", ""),
            }
            for t in plan.tasks
        ]
        print(f"[FAIL] 任务: {json.dumps(tasks_summary, ensure_ascii=False)}")
    assert passed, f"规划验证失败：{reason}"


@pytest.mark.llm_real
@pytest.mark.asyncio
async def test_planning_overall_accuracy(planning_engine):
    """数据集整体规划合理性 ≥ 90%。

    这是规划层的核心 KPI：LLM 在真实意图输入下生成的规划方案
    应在大多数场景中满足技能选取正确、端点匹配、无幻觉三项要求。
    """
    results = []

    for intent, rules in PLANNING_ACCURACY_DATASET:
        try:
            plan = await planning_engine.generate_plan(intent)
            plan_dict = plan.model_dump()
            passed, reason = validate_plan(plan_dict, rules)
            results.append((passed, intent, reason))
        except Exception as e:
            results.append((False, intent, str(e)))

    passed_count = sum(1 for r in results if r[0])
    total = len(results)
    accuracy = passed_count / total if total > 0 else 0

    # Report
    print(f"\n{'='*60}")
    print(f"规划合理性整体准确率: {passed_count}/{total} = {accuracy:.1%}")
    print(f"{'='*60}")

    failed = [(r[1], r[2]) for r in results if not r[0]]
    if failed:
        print("\n失败场景:")
        for idx, (intent, reason) in enumerate(failed, 1):
            fmt = intent.get("output_format", "?")
            subj = intent.get("analysis_subject", intent.get("time_range", "?"))
            print(f"  {idx}. [{fmt}] {subj}")
            print(f"     原因: {reason}")

    passed_list = [(r[1],) for r in results if r[0]]
    if passed_list:
        print(f"\n通过场景 ({passed_count}):")
        for (intent,) in passed_list:
            fmt = intent.get("output_format", "?")
            subj = intent.get("analysis_subject", intent.get("time_range", "?"))
            print(f"  ✓ [{fmt}] {subj}")

    assert accuracy >= 0.90, (
        f"规划合理性 {accuracy:.1%} < 90%，需优化规划 Prompt 或端点选取规则"
    )
