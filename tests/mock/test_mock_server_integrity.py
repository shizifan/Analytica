import asyncio
import time
import pytest


pytestmark = pytest.mark.asyncio


# ═══════════════════════════════════════════════════════════════
# TC-M0S: Mock Server 基础功能
# ═══════════════════════════════════════════════════════════════

async def test_health_check(mock_client):
    """TC-M0S01: 健康检查端点正常"""
    resp = await mock_client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["api_count"] == 27


async def test_all_27_apis_registered(mock_client):
    """TC-M0S02: 27 个 API 全部已注册"""
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


async def test_unauthenticated_returns_401(mock_client_no_auth):
    """TC-M0S03: 无 Token 请求返回 401"""
    resp = await mock_client_no_auth.get(
        "/api/v1/production/throughput/summary",
        params={"date": "2025-03", "dateType": 1},
    )
    assert resp.status_code in (401, 403, 422)


@pytest.mark.parametrize("date_param", ["2020-01", "2030-12", "2023-12"])
async def test_out_of_range_returns_404(mock_client, date_param):
    """TC-M0S04: 超出数据范围返回 404"""
    resp = await mock_client.get(
        "/api/v1/production/throughput/summary",
        params={"date": date_param, "dateType": 1},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == 404
    assert "超出" in data["msg"] or data["data"] is None


@pytest.mark.parametrize(
    "endpoint,params",
    [
        (
            "/api/v1/production/throughput/summary",
            {"date": "2025-06", "dateType": 1},
        ),
        (
            "/api/v1/market/throughput/monthly",
            {"curDateMonth": "2025-06", "yearDateMonth": "2024-06"},
        ),
        (
            "/api/v1/customer/strategic/throughput",
            {"curDate": "2025", "statisticType": 1},
        ),
    ],
)
async def test_idempotency(mock_client, endpoint, params):
    """TC-M0S05: 幂等性验证（同参数两次调用结果相同）"""
    resp1 = await mock_client.get(endpoint, params=params)
    resp2 = await mock_client.get(endpoint, params=params)
    assert resp1.json() == resp2.json(), f"{endpoint} 幂等性失效"


# ═══════════════════════════════════════════════════════════════
# TC-M0D: Mock 数据业务合理性验证
# ═══════════════════════════════════════════════════════════════

async def test_monthly_throughput_in_business_range(mock_client):
    """TC-M0D01: 月度吞吐量在合理业务范围内（全 30 个月）"""
    months = []
    for year in [2024, 2025]:
        for month in range(1, 13):
            months.append(f"{year}-{month:02d}")
    for month in range(1, 7):
        months.append(f"2026-{month:02d}")

    for date_str in months:
        resp = await mock_client.get(
            "/api/v1/production/throughput/summary",
            params={"date": date_str, "dateType": 1},
        )
        data = resp.json()["data"]
        assert data is not None, f"{date_str} 返回 null"
        v = data["totalThroughput"]
        assert 1800 <= v <= 4500, (
            f"{date_str} 月度吞吐量 {v} 万吨不在合理范围 [1800, 4500]"
        )


async def test_seasonal_pattern_reflected(mock_client):
    """TC-M0D02: 季节性规律体现（2月最低，5月偏高）"""
    resp_feb = await mock_client.get(
        "/api/v1/production/throughput/summary",
        params={"date": "2025-02", "dateType": 1},
    )
    resp_may = await mock_client.get(
        "/api/v1/production/throughput/summary",
        params={"date": "2025-05", "dateType": 1},
    )
    feb_val = resp_feb.json()["data"]["totalThroughput"]
    may_val = resp_may.json()["data"]["totalThroughput"]
    assert feb_val < may_val, (
        f"季节性规律异常：2月({feb_val}) 应 < 5月({may_val})"
    )


async def test_yoy_growth_trend(mock_client):
    """TC-M0D03: 2025年同比增速高于2024年（业务规律）"""
    months = [f"{m:02d}" for m in [3, 4, 5, 6, 7, 8, 9]]
    for m in months:
        resp_2025 = await mock_client.get(
            "/api/v1/production/throughput/summary",
            params={"date": f"2025-{m}", "dateType": 1},
        )
        resp_2024 = await mock_client.get(
            "/api/v1/production/throughput/summary",
            params={"date": f"2024-{m}", "dateType": 1},
        )
        v_2025 = resp_2025.json()["data"]["totalThroughput"]
        v_2024 = resp_2024.json()["data"]["totalThroughput"]
        assert v_2025 > v_2024, (
            f"{m}月：2025({v_2025}) 应 > 2024({v_2024})（同比增长应为正）"
        )


async def test_zone_sum_matches_total(mock_client):
    """TC-M0D04: 各港区吞吐量之和≈全港总量（跨域一致性）"""
    month = "2025-06"
    resp_total = await mock_client.get(
        "/api/v1/market/throughput/monthly",
        params={"curDateMonth": month, "yearDateMonth": "2024-06"},
    )
    resp_zones = await mock_client.get(
        "/api/v1/market/throughput/by-zone",
        params={"curDateMonth": month, "yearDateMonth": "2024-06"},
    )
    total = resp_total.json()["data"]["curMonthTotal"]
    zone_sum = sum(z["throughput"] for z in resp_zones.json()["data"])
    deviation = abs(zone_sum - total) / total
    assert deviation <= 0.10, (
        f"港区之和({zone_sum:.1f}) 与全港总量({total:.1f}) 偏差 {deviation:.1%} > 10%"
    )


async def test_segment_share_sums_to_100(mock_client):
    """TC-M0D05: 各业务板块 shareRatio 之和 = 100%"""
    resp = await mock_client.get(
        "/api/v1/market/business-segment",
        params={
            "curDateMonth": "2025-06",
            "yearDateMonth": "2024-06",
            "statisticType": 0,
        },
    )
    shares = [s["shareRatio"] for s in resp.json()["data"]]
    total = sum(shares)
    assert abs(total - 100.0) <= 1.0, (
        f"业务板块占比之和 {total:.1f}% ≠ 100%"
    )


async def test_container_teu_in_range(mock_client):
    """TC-M0D06: 集装箱年吞吐量在 TEU 合理范围"""
    for year in ["2024", "2025"]:
        resp = await mock_client.get(
            "/api/v1/production/container/throughput",
            params={"dateYear": year},
        )
        data = resp.json()["data"]
        teu = data["totalTeu"]
        assert 3_800_000 <= teu <= 5_200_000, (
            f"{year}年集装箱吞吐量 {teu} TEU 不在合理范围"
        )
        assert abs(data["foreignTradeTeu"] + data["domesticTradeTeu"] - teu) <= 100, (
            "内贸+外贸 ≠ 总TEU"
        )
        foreign_ratio = data["foreignTradeTeu"] / teu
        assert 0.60 <= foreign_ratio <= 0.80, (
            f"外贸占比 {foreign_ratio:.1%} 超出合理范围 [60%, 80%]"
        )


async def test_strategic_customer_contribution(mock_client):
    """TC-M0D07: 战略客户 TOP10 贡献率之和 ≤ 总贡献上限"""
    resp = await mock_client.get(
        "/api/v1/customer/strategic/throughput",
        params={"curDate": "2025", "statisticType": 1},
    )
    customers = resp.json()["data"]
    assert 25 <= len(customers) <= 60, (
        f"战略客户数量 {len(customers)} 超出合理范围 [25, 60]"
    )
    top10_contribution = sum(c["contributionRate"] for c in customers[:10])
    assert 45 <= top10_contribution <= 75, (
        f"TOP10战略客户贡献率之和 {top10_contribution:.1f}% 超出合理范围 [45%, 75%]"
    )


async def test_invest_completion_rate_increases_over_year(mock_client):
    """TC-M0D08: 投资完成率与月份正相关（年末高于年初）"""
    resp_progress = await mock_client.get(
        "/api/v1/invest/plan/monthly-progress",
        params={"startMonth": "2025-01", "endMonth": "2025-12"},
    )
    progress = resp_progress.json()["data"]
    mar_cumulative = next(
        p["cumulativeActual"] for p in progress if p["month"] == "2025-03"
    )
    jun_cumulative = next(
        p["cumulativeActual"] for p in progress if p["month"] == "2025-06"
    )
    assert jun_cumulative > mar_cumulative, (
        f"6月累计投资({jun_cumulative}) 应 > 3月({mar_cumulative})"
    )


async def test_credit_level_distribution(mock_client):
    """TC-M0D09: 信用等级分布符合业务合理性"""
    resp = await mock_client.get("/api/v1/customer/credit-info")
    customers = resp.json()["data"]
    levels = [c["creditLevel"] for c in customers]
    high_quality = sum(1 for lv in levels if lv in ("AAA", "AA", "A"))
    assert high_quality / len(levels) >= 0.75, (
        f"高质量客户(AAA/AA/A)占比 {high_quality/len(levels):.1%} 过低"
    )
    c_level = sum(1 for lv in levels if lv == "C")
    assert c_level / len(levels) <= 0.10


async def test_equipment_status_normal_ratio(mock_client):
    """TC-M0D10: 设备状态"正常"占比符合运营规律"""
    for year in ["2024", "2025", "2026"]:
        resp = await mock_client.get(
            "/api/v1/asset/equipment/status",
            params={"dateYear": year, "type": 1},
        )
        statuses = resp.json()["data"]
        normal = next((s for s in statuses if s["status"] == "正常"), None)
        assert normal is not None
        assert 0.80 <= normal["ratio"] <= 0.92, (
            f"{year}年设备正常率 {normal['ratio']:.1%} 超出合理范围 [80%, 92%]"
        )


# ═══════════════════════════════════════════════════════════════
# TC-M0P: Mock Server 性能基准
# ═══════════════════════════════════════════════════════════════

@pytest.mark.parametrize(
    "endpoint,params",
    [
        (
            "/api/v1/production/throughput/summary",
            {"date": "2025-06", "dateType": 1},
        ),
        (
            "/api/v1/market/throughput/monthly",
            {"curDateMonth": "2025-06", "yearDateMonth": "2024-06"},
        ),
        (
            "/api/v1/customer/strategic/throughput",
            {"curDate": "2025", "statisticType": 1},
        ),
        ("/api/v1/invest/plan/summary", {"currYear": "2025"}),
    ],
)
async def test_single_api_response_time(mock_client, endpoint, params):
    """TC-M0P01: 单 API 响应时间 ≤ 200ms"""
    start = time.time()
    resp = await mock_client.get(endpoint, params=params)
    elapsed_ms = (time.time() - start) * 1000
    assert resp.status_code == 200
    assert elapsed_ms <= 200, f"{endpoint} 响应时间 {elapsed_ms:.0f}ms > 200ms"


async def test_concurrent_8_apis_under_500ms(mock_client):
    """TC-M0P02: 8 个 API 并发调用总时间 ≤ 500ms"""
    start = time.time()
    tasks = [
        mock_client.get(
            "/api/v1/production/throughput/summary",
            params={"date": "2026-03", "dateType": 1},
        ),
        mock_client.get(
            "/api/v1/production/container/throughput",
            params={"dateYear": "2026"},
        ),
        mock_client.get(
            "/api/v1/production/berth/occupancy-rate",
            params={
                "startDate": "2026-03-01",
                "endDate": "2026-03-31",
                "groupBy": "region",
            },
        ),
        mock_client.get(
            "/api/v1/production/vessel/efficiency",
            params={"startMonth": "2026-03", "endMonth": "2026-03"},
        ),
        mock_client.get(
            "/api/v1/market/throughput/monthly",
            params={"curDateMonth": "2026-03", "yearDateMonth": "2025-03"},
        ),
        mock_client.get(
            "/api/v1/market/throughput/by-zone",
            params={"curDateMonth": "2026-03", "yearDateMonth": "2025-03"},
        ),
        mock_client.get(
            "/api/v1/market/key-enterprise",
            params={
                "businessSegment": "集装箱",
                "curDateMonth": "2026-03",
                "statisticType": 0,
            },
        ),
        mock_client.get(
            "/api/v1/invest/plan/monthly-progress",
            params={"startMonth": "2026-01", "endMonth": "2026-03"},
        ),
    ]
    await asyncio.gather(*tasks)
    elapsed_ms = (time.time() - start) * 1000
    assert elapsed_ms <= 500, (
        f"8个并发 API 总耗时 {elapsed_ms:.0f}ms > 500ms（Mock Server 性能不足）"
    )
