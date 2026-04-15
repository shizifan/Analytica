"""共享 conftest — 提供真实 LLM 客户端和数据库 fixtures。"""
import os

import pytest
import pytest_asyncio
from langchain_openai import ChatOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

# Load .env from project root
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from backend.agent.perception import SlotFillingEngine
from backend.models.schemas import SlotValue, ALL_SLOT_NAMES

TEST_DATABASE_URL = os.environ.get(
    "DATABASE_URL", "mysql+aiomysql://root@localhost:3306/analytica"
)


# ── Real LLM Client ─────────────────────────────────────────

@pytest.fixture(scope="session")
def real_llm():
    """Session-scoped real Qwen3 LLM client."""
    api_base = os.environ.get("QWEN_API_BASE")
    api_key = os.environ.get("QWEN_API_KEY")
    model = os.environ.get("QWEN_MODEL", "Qwen3-235B")
    if not api_base or not api_key:
        pytest.skip("QWEN_API_BASE/QWEN_API_KEY not set, skipping real LLM tests")
    return ChatOpenAI(
        base_url=api_base,
        api_key=api_key,
        model=model,
        temperature=0.1,
        request_timeout=120,
    )


@pytest.fixture
def real_engine(real_llm):
    """SlotFillingEngine with real LLM."""
    return SlotFillingEngine(llm=real_llm, max_clarification_rounds=3, llm_timeout=120.0)


# ── Capturing LLM (交互日志) ────────────────────────────────

from tests.helpers.capturing_llm import CapturingLLM


@pytest.fixture
def capturing_llm(real_llm):
    """包装真实 LLM，记录所有交互。"""
    return CapturingLLM(real_llm)


@pytest.fixture
def capturing_engine(capturing_llm):
    """返回 (engine, capturing_llm) 元组。"""
    engine = SlotFillingEngine(llm=capturing_llm, max_clarification_rounds=3, llm_timeout=120.0)
    return engine, capturing_llm


# ── Database fixtures ────────────────────────────────────────

@pytest_asyncio.fixture
async def test_db_engine():
    """Function-scoped async DB engine."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_db_session():
    """Function-scoped async DB session."""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
        await session.rollback()
    await engine.dispose()


# ── Helpers ──────────────────────────────────────────────────

def make_empty_slots() -> dict[str, SlotValue]:
    """Create all slots with None values."""
    return {
        name: SlotValue(value=None, source="default", confirmed=False)
        for name in ALL_SLOT_NAMES
    }


def make_partial_slots(**kwargs) -> dict[str, SlotValue]:
    """Create slots with some values pre-filled."""
    slots = make_empty_slots()
    field_map = {
        "analysis_subject": ("user_input", True),
        "time_range": ("user_input", True),
        "output_complexity": ("user_input", True),
        "output_format": ("user_input", True),
    }
    for key, val in kwargs.items():
        if key in field_map:
            src, conf = field_map[key]
            slots[key] = SlotValue(value=val, source=src, confirmed=conf)
        elif key == "output_complexity_inferred":
            slots["output_complexity"] = SlotValue(value=val, source="inferred", confirmed=False)
    return slots
