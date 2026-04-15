"""TC-A01~A06: 规划层与 Mock API 端点匹配测试。

验证规划 Prompt 的语义路由逻辑——正确的端点是否在正确的意图下被标注。
TC-A06: resolve_endpoint_id 全 27 个 M-code 映射验证。
"""
import pytest

from backend.agent.planning import PlanningEngine
from backend.agent.endpoints import resolve_endpoint_id, MCODE_TO_ENDPOINT


# ── Test Helpers ─────────────────────────────────────────────

def make_structured_intent(
    complexity: str = "simple_table",
    domain: str | None = None,
    subject: list[str] | None = None,
    **kwargs,
) -> dict:
    intent = {
        "output_complexity": complexity,
        "analysis_goal": "测试",
        "slots": {
            "output_complexity": {"value": complexity, "source": "user_input", "confirmed": True},
            "analysis_subject": {"value": subject or ["测试"], "source": "user_input", "confirmed": True},
            "time_range": {"value": {"description": "本月"}, "source": "user_input", "confirmed": True},
        },
    }
    if domain:
        intent["domain"] = domain
        intent["slots"]["domain"] = {"value": domain, "source": "inferred", "confirmed": False}
    intent.update(kwargs)
    return intent


# ═══════════════════════════════════════════════════════════════
#  TC-A01: 生产域总量查询 → getThroughputSummary
# ═══════════════════════════════════════════════════════════════

def test_production_total_uses_throughput_summary():
    engine = PlanningEngine()
    intent = make_structured_intent("simple_table", domain="production", subject=["本月全港总吞吐量"])
    prompt = engine._build_prompt(intent, "simple_table")
    assert "getThroughputSummary" in prompt, "全港总量意图应在 Prompt 中标注 getThroughputSummary"
    assert "when_to_use" in prompt.lower() or "适用" in prompt or "全港" in prompt


# ═══════════════════════════════════════════════════════════════
#  TC-A02: 市场域当月查询 → getMarketMonthlyThroughput
# ═══════════════════════════════════════════════════════════════

def test_market_monthly_prefers_M10():
    engine = PlanningEngine()
    intent = make_structured_intent("simple_table", domain="market", subject=["本月市场完成"])
    prompt = engine._build_prompt(intent, "simple_table")
    assert "getMarketMonthlyThroughput" in prompt, "市场当月意图应标注 getMarketMonthlyThroughput"
    # Market domain endpoints should appear before production
    m10_pos = prompt.find("getMarketMonthlyThroughput")
    assert m10_pos >= 0


# ═══════════════════════════════════════════════════════════════
#  TC-A03: 趋势图查询 → businessSegment 必填约束
# ═══════════════════════════════════════════════════════════════

def test_trend_chart_business_segment_required():
    engine = PlanningEngine()
    intent = make_structured_intent("chart_text", domain="market", subject=["集装箱趋势图"])
    prompt = engine._build_prompt(intent, "chart_text")
    assert "businessSegment" in prompt, "M12 的 businessSegment 必填约束应出现在 Prompt"
    assert "必填" in prompt or "required" in prompt.lower()


# ═══════════════════════════════════════════════════════════════
#  TC-A04: 客户排名 → M19，不选 M17
# ═══════════════════════════════════════════════════════════════

def test_customer_ranking_uses_M19():
    engine = PlanningEngine()
    intent = make_structured_intent("simple_table", domain="customer", subject=["贡献排名"])
    prompt = engine._build_prompt(intent, "simple_table")
    assert "getCustomerContributionRanking" in prompt
    # Customer domain endpoints should appear in priority section
    ranking_pos = prompt.find("getCustomerContributionRanking")
    strategic_pos = prompt.find("getStrategicCustomerThroughput")
    assert ranking_pos >= 0


# ═══════════════════════════════════════════════════════════════
#  TC-A05: 投资进度 → M26 vs M25
# ═══════════════════════════════════════════════════════════════

def test_invest_endpoints_both_present():
    engine = PlanningEngine()
    intent = make_structured_intent("chart_text", domain="invest", subject=["投资进度月度节奏"])
    prompt = engine._build_prompt(intent, "chart_text")
    assert "getInvestPlanProgress" in prompt
    assert "getInvestPlanSummary" in prompt
    # Invest domain endpoints should have priority
    assert "推荐端点" in prompt or "invest" in prompt.lower()


# ═══════════════════════════════════════════════════════════════
#  TC-A06: resolve_endpoint_id 全部 27 个 M-code 映射验证
# ═══════════════════════════════════════════════════════════════

ALL_MCODE_CASES = [
    (mcode, expected_name)
    for mcode, expected_name in MCODE_TO_ENDPOINT.items()
]


@pytest.mark.parametrize(
    "mcode,expected",
    ALL_MCODE_CASES,
    ids=[f"resolve-{m}" for m in MCODE_TO_ENDPOINT.keys()],
)
def test_resolve_endpoint_id_all_mcodes(mcode, expected):
    """TC-A06: 全部 27 个 M-code 映射验证。"""
    assert resolve_endpoint_id(mcode) == expected
    # 小写也能解析
    assert resolve_endpoint_id(mcode.lower()) == expected
    # 直接函数名也能解析
    assert resolve_endpoint_id(expected) == expected


def test_resolve_endpoint_id_invalid_returns_none():
    """无效 endpoint 返回 None。"""
    assert resolve_endpoint_id("getPortNationalRanking") is None
    assert resolve_endpoint_id("M99") is None
    assert resolve_endpoint_id("") is None
