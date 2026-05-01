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


# ── API Registry: seed DB + load into memory once per session ─

@pytest_asyncio.fixture(scope="session", autouse=True, loop_scope="session")
async def _seed_and_load_api_registry():
    """Once per pytest session, ensure ``api_endpoints`` + ``domains`` tables
    are seeded from ``data/api_registry.json`` and the in-memory ``api_registry``
    module globals (``BY_NAME``, ``ALL_ENDPOINTS``, ...) are populated.

    The new design treats DB as the only source — the module imports with
    empty globals, and tests that ``from api_registry import BY_NAME`` would
    see an empty dict without this fixture. Running once per session keeps
    the cost negligible (~150 UPSERTs).

    Tests that don't touch the DB or the registry pay no cost — pytest
    collects this fixture lazily for autouse, but the work itself only
    runs on session start. If the DB isn't reachable, log a WARN and
    proceed; tests that need the registry will surface a clear failure
    via empty BY_NAME rather than a confusing connection error.
    """
    import logging
    logger = logging.getLogger("conftest._seed_and_load_api_registry")
    try:
        from pathlib import Path
        from tools.seed_api_endpoints import _seed
        repo_root = Path(__file__).resolve().parent.parent
        json_path = repo_root / "data" / "api_registry.json"
        await _seed(json_path, dry_run=False)
        from backend.agent import api_registry
        ep, dom = await api_registry.reload_from_db()
        logger.info(
            "[api_registry] session-seeded %d endpoints + %d domains", ep, dom,
        )
    except Exception as e:
        logger.warning(
            "[api_registry] seed/reload failed (%s) — tests that need "
            "BY_NAME / DOMAIN_INDEX will fail visibly", e,
        )
    yield


# ── Database Session Fixture ──────────────────────────────────

@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def _reset_global_db_engine_between_tests():
    """Each test runs in a fresh event loop (function-scoped), but
    ``backend.database`` caches a module-level engine bound to whatever
    loop first called ``get_engine()``. Leaving that engine around
    poisons subsequent tests with "got Future attached to a different
    loop". Dispose + null out before each test.
    """
    from backend import database
    if database._engine is not None:
        try:
            await database._engine.dispose()
        except Exception:
            pass
        database._engine = None
        database._session_factory = None
    yield


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


# ── Mock Server fixture (session-scoped, real HTTP) ────────────
#
# Starts the full mock_server_all.py FastAPI app on a random local port for
# integration / smoke tests that want to exercise the real 226 routes
# rather than respx-stubbed handfuls. Sessions auto-shut on test exit.

@pytest.fixture(scope="session")
def mock_server_url():
    """Spin up mock_server_all.py on a random port; yield base URL.

    Only started on demand — pytest fixtures are lazy, so unit tests that
    don't request this fixture pay no startup cost.
    """
    import socket
    import threading
    import time
    import uvicorn

    # Pick a free port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    from mock_server.mock_server_all import app as mock_app
    config = uvicorn.Config(mock_app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)

    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    # Wait up to 5s for server to come up
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(50):
        try:
            with httpx.Client(timeout=0.5) as client:
                r = client.get(f"{base_url}/")
                if r.status_code in (200, 404):  # any HTTP response means server ready
                    break
        except Exception:
            time.sleep(0.1)
    else:
        server.should_exit = True
        raise RuntimeError(f"mock_server failed to start on {base_url}")

    yield base_url

    server.should_exit = True
    thread.join(timeout=3)


@pytest.fixture
def mock_server_settings(monkeypatch, mock_server_url):
    """Point backend.config settings at the running mock_server.

    Use this in any test that wants real HTTP calls to flow through
    mock_server (instead of respx stubs).
    """
    monkeypatch.setenv("MOCK_SERVER_URL", mock_server_url)
    monkeypatch.setenv("API_MODE", "mock")
    yield mock_server_url


# ── LLM record / replay ──────────────────────────────────────
#
# Two LLM entry points exist in the codebase:
#   1) backend.agent.graph.build_llm()  → LangChain ChatOpenAI
#   2) backend.tools._llm.invoke_llm()  → openai SDK call
# The `recorded_llm` fixture patches both and routes through a shared
# JSON cache so tests can replay deterministic responses without real
# LLM calls. Modes (set via CLI):
#   --llm-mode=replay          (default) cache-only; miss → CacheMissError
#   --llm-mode=record-missing  cache hits; misses → call real + store
#   --llm-mode=record-all      always call real + overwrite cache
#   --llm-mode=passthrough     always call real, never write cache

def pytest_addoption(parser):
    parser.addoption(
        "--llm-mode",
        default="replay",
        choices=["replay", "record-missing", "record-all", "passthrough"],
        help=(
            "LLM call mode: replay (default — cache-only), record-missing "
            "(record on miss), record-all (overwrite all), passthrough (no cache)."
        ),
    )


@pytest.fixture(scope="session")
def llm_mode(request):
    return request.config.getoption("--llm-mode")


@pytest.fixture(scope="session")
def llm_cache_dir():
    from pathlib import Path
    p = Path(__file__).parent / "llm_cache"
    p.mkdir(exist_ok=True)
    return p


@pytest.fixture
def recorded_llm(monkeypatch, llm_mode, llm_cache_dir, request):
    """Patch both LLM entry points to route through the JSON cache.

    Yields the LangChain wrapper (so tests can inspect `.calls`).
    The `invoke_llm` patch is transparent — tools call it as before.
    """
    from tests.lib.llm_recorder import (
        RecordingMode, RecordedLangChainLLM, RecordedInvokeLLM,
    )

    mode = RecordingMode(llm_mode)
    test_id = request.node.nodeid

    # Capture the real build_llm BEFORE patching — otherwise our wrapper's
    # internal call recurses into itself.
    from backend.agent import graph as _g
    _real_build_llm = _g.build_llm

    # ── Patch graph.build_llm ──
    def _fake_build_llm(model_key="qwen3-235b", *, request_timeout=200):
        real = None
        if mode != RecordingMode.REPLAY:
            try:
                real = _real_build_llm(model_key, request_timeout=request_timeout)
            except Exception:
                real = None
        return RecordedLangChainLLM(
            real, cache_dir=llm_cache_dir / "langchain", mode=mode,
            model=model_key, temperature=0.1, test_id=test_id,
        )

    monkeypatch.setattr(_g, "build_llm", _fake_build_llm)
    # Also patch the import in employees.graph_factory which does
    # `from backend.agent.graph import build_llm`
    import backend.employees.graph_factory as _gf
    if hasattr(_gf, "build_llm"):
        monkeypatch.setattr(_gf, "build_llm", _fake_build_llm)

    # ── Patch tools._llm.invoke_llm ──
    from backend.tools import _llm as _tllm
    real_invoke = _tllm.invoke_llm
    recorder = RecordedInvokeLLM(
        real_invoke if mode != RecordingMode.REPLAY else None,
        cache_dir=llm_cache_dir / "invoke_llm", mode=mode,
        model="qwen-default", test_id=test_id,
    )
    monkeypatch.setattr(_tllm, "invoke_llm", recorder)

    # Yield a handle so tests can inspect what was called.
    yield {
        "build_llm": _fake_build_llm,
        "invoke_llm_recorder": recorder,
        "mode": mode,
    }
