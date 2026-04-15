import pytest


TEST_DATES = {
    "latest_month":     "2026-03",
    "latest_year":      "2026",
    "prev_month":       "2026-02",
    "prev_year":        "2025",
    "q1_start":         "2026-01",
    "q1_end":           "2026-03",
    "full_year_2025":   "2025",
    "full_year_2024":   "2024",
    "trend_30m_start":  "2024-01",
    "trend_30m_end":    "2026-06",
}

REGIONS = ["大连港区", "营口港区", "丹东港区", "锦州港区"]

BUSINESS_TYPES = ["集装箱", "散杂货", "油化品", "商品车"]

STRATEGIC_CLIENTS = [
    "中远海运集装箱运输", "马士基航运", "地中海航运",
    "华能煤业", "中储粮总公司", "鞍山钢铁集团",
    "中国石化", "中国石油", "大众汽车进出口",
    "宝马汽车进出口", "国家能源集团",
]

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
    return TEST_DATES.copy()


@pytest.fixture
def throughput_expectation():
    return {
        "monthly_min_wan_ton": 1800.0,
        "monthly_max_wan_ton": 4500.0,
        "annual_min_wan_ton": 280000.0,
        "annual_max_wan_ton": 420000.0,
        "container_annual_min_teu": 3_800_000,
        "container_annual_max_teu": 5_200_000,
        "yoy_reasonable_min": -10.0,
        "yoy_reasonable_max": 20.0,
    }
