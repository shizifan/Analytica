"""Shared test fixtures for Phase 1 tests."""
import asyncio
import json
import os
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from backend.database import Base
from backend.models.schemas import SlotValue, ALL_SLOT_NAMES, SLOT_SCHEMA_MAP

# Ensure test environment — 不再覆盖真实 API 配置
# 通过 conftest.py 的 load_dotenv 加载 .env 中的真实配置

TEST_DATABASE_URL = "mysql+aiomysql://root@localhost:3306/analytica"


@pytest_asyncio.fixture(scope="session")
async def test_db_engine():
    """Create a test database engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session(test_db_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create a test database session with transaction rollback."""
    factory = async_sessionmaker(test_db_engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()


class MockLLMResponse:
    """Mock LangChain ChatModel response."""
    def __init__(self, content: str):
        self.content = content


def make_mock_llm(output: str) -> AsyncMock:
    """Create a mock LLM that returns a fixed output."""
    mock = AsyncMock()
    mock.ainvoke = AsyncMock(return_value=MockLLMResponse(output))
    return mock


def make_empty_slots() -> dict[str, SlotValue]:
    """Create a dict of all slots with None values."""
    return {name: SlotValue(value=None, source="default", confirmed=False) for name in ALL_SLOT_NAMES}


def make_partial_slots(**kwargs) -> dict[str, SlotValue]:
    """Create slots with some values filled.

    Supports: analysis_subject, time_range, output_complexity,
              output_format, output_format_from_history,
              output_complexity_inferred, etc.
    """
    slots = make_empty_slots()

    if "analysis_subject" in kwargs:
        slots["analysis_subject"] = SlotValue(
            value=kwargs["analysis_subject"], source="user_input", confirmed=True
        )
    if "time_range" in kwargs:
        slots["time_range"] = SlotValue(
            value=kwargs["time_range"], source="user_input", confirmed=True
        )
    if "output_complexity" in kwargs:
        slots["output_complexity"] = SlotValue(
            value=kwargs["output_complexity"], source="user_input", confirmed=True
        )
    if "output_complexity_inferred" in kwargs:
        slots["output_complexity"] = SlotValue(
            value=kwargs["output_complexity_inferred"], source="inferred", confirmed=False
        )
    if "output_format" in kwargs:
        slots["output_format"] = SlotValue(
            value=kwargs["output_format"], source="user_input", confirmed=True
        )
    if "output_format_from_history" in kwargs:
        slots["output_format"] = SlotValue(
            value=kwargs["output_format_from_history"], source="history", confirmed=False
        )
    return slots


def make_fully_filled_slots(complexity: str = "simple_table") -> dict[str, SlotValue]:
    """Create a fully filled slot set for given complexity."""
    slots = {
        "analysis_subject": SlotValue(value=["集装箱吞吐量"], source="user_input", confirmed=True),
        "time_range": SlotValue(
            value={"start": "2026-03-01", "end": "2026-03-31", "description": "上个月"},
            source="user_input", confirmed=True,
        ),
        "output_complexity": SlotValue(value=complexity, source="user_input", confirmed=True),
        "output_format": SlotValue(value=None, source="default", confirmed=False),
        "attribution_needed": SlotValue(value=None, source="default", confirmed=False),
        "predictive_needed": SlotValue(value=None, source="default", confirmed=False),
        "time_granularity": SlotValue(value="monthly", source="inferred", confirmed=False),
        "domain": SlotValue(value="production", source="inferred", confirmed=False),
        "domain_glossary": SlotValue(value=None, source="default", confirmed=False),
    }

    if complexity == "full_report":
        slots["output_format"] = SlotValue(value="pptx", source="memory", confirmed=False)
        slots["attribution_needed"] = SlotValue(value=True, source="user_input", confirmed=True)
        slots["predictive_needed"] = SlotValue(value=False, source="inferred", confirmed=False)
    elif complexity == "chart_text":
        slots["attribution_needed"] = SlotValue(value=True, source="user_input", confirmed=True)

    return slots


# Mock LLM fixture
mock_llm = make_mock_llm('{"extracted": {}}')
