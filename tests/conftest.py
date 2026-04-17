"""Shared test fixtures — mock LLM, mock HTTP API responses, etc."""
from __future__ import annotations

import json
import os
from typing import Any
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
import respx
import httpx
from dotenv import load_dotenv

# Load .env for test settings
load_dotenv()


# ── Database Session Fixture ──────────────────────────────────

@pytest_asyncio.fixture(loop_scope="function")
async def test_db_session():
    """Provide an async database session for tests.

    Each test gets a fresh session. Test isolation relies on unique
    UUIDs per test (no cross-test collisions). Tables are ensured
    to exist at fixture creation time.
    """
    from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
    from sqlalchemy.pool import NullPool
    from backend.database import Base

    db_url = os.getenv("DATABASE_URL", "mysql+aiomysql://root@localhost:3306/analytica")
    engine = create_async_engine(db_url, echo=False, poolclass=NullPool)

    # Ensure tables exist
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session = AsyncSession(engine, expire_on_commit=False)
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


# ── Mock LLM ──────────────────────────────────────────────────

class MockLLM:
    """Deterministic LLM stub that returns pre-configured responses based on prompt keywords."""

    def __init__(self, responses: dict[str, str] | None = None):
        self._responses = responses or {}
        self._default = '{"extracted": {}}'
        self._call_log: list[str] = []

    def set_response(self, keyword: str, response: str) -> None:
        self._responses[keyword] = response

    async def ainvoke(self, prompt: str | Any) -> _FakeAIMessage:
        text = prompt if isinstance(prompt, str) else str(prompt)
        self._call_log.append(text)
        for keyword, resp in self._responses.items():
            if keyword in text:
                return _FakeAIMessage(resp)
        return _FakeAIMessage(self._default)

    @property
    def call_count(self) -> int:
        return len(self._call_log)


class _FakeAIMessage:
    def __init__(self, content: str):
        self.content = content


@pytest.fixture
def mock_llm():
    """Provide a MockLLM instance with common preset responses."""
    llm = MockLLM()

    # Slot extraction response for a throughput query
    llm.set_response("槽位提取专家", json.dumps({
        "extracted": {
            "analysis_subject": {
                "value": ["集装箱吞吐量"],
                "evidence": "集装箱吞吐量",
                "confidence": "explicit"
            },
            "time_range": {
                "value": {
                    "start": "2026-01-01",
                    "end": "2026-03-31",
                    "description": "2026年第一季度"
                },
                "evidence": "2026年第一季度",
                "confidence": "explicit"
            },
            "output_complexity": {
                "value": "simple_table",
                "evidence": "查询吞吐量数据",
                "confidence": "implicit"
            },
            "domain": {
                "value": "D1",
                "evidence": "集装箱吞吐量",
                "confidence": "implicit"
            },
            "region": {
                "value": "大连港区",
                "evidence": "大连港区",
                "confidence": "explicit"
            }
        }
    }, ensure_ascii=False))

    # Clarification response
    llm.set_response("澄清分析需求", "请问您希望查看哪个时间范围的数据？")

    return llm


# ── Mock API Responses ────────────────────────────────────────

MOCK_THROUGHPUT_RESPONSE = {
    "code": 200,
    "msg": "success",
    "data": [
        {"targetQty": 48000.0, "finishQty": 13320.63}
    ]
}

MOCK_BERTH_REGION_RESPONSE = {
    "code": 200,
    "msg": "success",
    "data": [
        {"regionName": "大连港", "dateMonth": "2026-01", "rate": 0.3258},
        {"regionName": "大连港", "dateMonth": "2026-02", "rate": 0.2914},
        {"regionName": "营口港", "dateMonth": "2026-01", "rate": 0.2810},
        {"regionName": "锦州港", "dateMonth": "2026-01", "rate": 0.2550},
    ]
}

MOCK_TEU_RESPONSE = {
    "code": 200,
    "msg": "success",
    "data": [
        {"targetQty": 1200.0, "finishQty": 338.89}
    ]
}

MOCK_TP_BY_YEAR_RESPONSE = {
    "code": 200,
    "msg": "success",
    "data": [
        {"dateMonth": "2025-01", "qty": 4177.1},
        {"dateMonth": "2025-02", "qty": 3192.6},
        {"dateMonth": "2025-03", "qty": 3850.0},
    ]
}


@pytest.fixture
def mock_api_routes():
    """Set up respx mock routes for common API endpoints."""
    with respx.mock(assert_all_mocked=False, assert_all_called=False) as router:
        # Throughput (ton)
        router.get(
            url__regex=r".*/api/gateway/getThroughputAndTargetThroughputTon.*"
        ).mock(return_value=httpx.Response(200, json=MOCK_THROUGHPUT_RESPONSE))

        # Berth occupancy by region
        router.get(
            url__regex=r".*/api/gateway/getBerthOccupancyRateByRegion.*"
        ).mock(return_value=httpx.Response(200, json=MOCK_BERTH_REGION_RESPONSE))

        # TEU throughput
        router.get(
            url__regex=r".*/api/gateway/getThroughputAndTargetThroughputTeu.*"
        ).mock(return_value=httpx.Response(200, json=MOCK_TEU_RESPONSE))

        # Throughput by year (monthly trend)
        router.get(
            url__regex=r".*/api/gateway/getThroughputAnalysisByYear.*"
        ).mock(return_value=httpx.Response(200, json=MOCK_TP_BY_YEAR_RESPONSE))

        yield router
