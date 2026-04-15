"""共享 conftest — accuracy 测试目录复用 unit 目录的 fixtures。"""
import os
import sys

import pytest
import pytest_asyncio
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", "..", ".env"))

from backend.agent.perception import SlotFillingEngine
from backend.models.schemas import SlotValue, ALL_SLOT_NAMES


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


# ── 合理性判断工具 ───────────────────────────────────────────

VALID_DOMAINS = {"production", "market", "customer", "asset", "invest"}

# LLM 返回的 domain 值可能是中文描述，需要映射到标准枚举
DOMAIN_ALIASES = {
    "production": {"production", "生产", "运营", "港口运营", "港口", "港口生产", "作业", "吞吐", "泊位", "港存"},
    "market": {"market", "市场", "商务", "市场商务", "营销", "业务", "竞争", "份额"},
    "customer": {"customer", "客户", "客户管理", "战略客户", "信用", "大客户"},
    "asset": {"asset", "资产", "设备", "固定资产", "资产管理", "折旧"},
    "invest": {"invest", "投资", "投资管理", "项目", "在建工程", "工程"},
}

GRANULARITY_ALIASES = {
    "daily": {"daily", "day", "日", "每日", "天"},
    "monthly": {"monthly", "month", "月", "月度", "每月"},
    "quarterly": {"quarterly", "quarter", "季", "季度", "每季"},
    "yearly": {"yearly", "year", "annual", "年", "年度", "每年"},
}


def is_domain_reasonable(actual_value, acceptable_domains: set) -> str:
    """判断 domain 推断结果是否合理。

    支持 LLM 返回中文描述（如"港口运营"）匹配到标准枚举（如"production"）。

    Returns:
        'REASONABLE' — 推断值在可接受集合内
        'UNEXPECTED' — 推断了值但不在可接受集合内
        'NOT_INFERRED' — 未推断出 domain
    """
    if actual_value is None:
        return "NOT_INFERRED"
    val = str(actual_value).lower().strip()
    if not val:
        return "NOT_INFERRED"

    # 直接匹配
    for domain in acceptable_domains:
        if domain in val or val in domain:
            return "REASONABLE"

    # 通过别名映射匹配
    for domain in acceptable_domains:
        aliases = DOMAIN_ALIASES.get(domain, set())
        for alias in aliases:
            if alias in val or val in alias:
                return "REASONABLE"

    return "UNEXPECTED"


def is_granularity_reasonable(actual_value, expected_hint: str) -> bool:
    """检查粒度值是否在同义词组内。

    expected_hint: 'daily' | 'monthly' | 'quarterly' | 'yearly'
    """
    if actual_value is None:
        return False
    val = str(actual_value).lower().strip()
    aliases = GRANULARITY_ALIASES.get(expected_hint, set())
    return val in aliases or expected_hint in val


def make_empty_slots():
    """创建全空槽位字典。"""
    return {name: SlotValue(value=None, source="default", confirmed=False) for name in ALL_SLOT_NAMES}
