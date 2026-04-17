"""员工域过滤工具 — 纯函数，无状态。

将 api_registry 和 agent/skills 的描述生成逻辑
包装为按员工白名单过滤的版本。
"""
from __future__ import annotations

from typing import Optional


def filter_endpoints_description(
    allowed: frozenset[str],
    domain_hint: Optional[str] = None,
    time_hint: Optional[set[str]] = None,
    granularity_hint: Optional[str] = None,
) -> str:
    """生成仅包含白名单内端点的 LLM Prompt 描述文本。

    参数与 api_registry.get_endpoints_description 一致，
    增加 allowed 进行硬过滤。
    """
    from backend.agent.api_registry import get_endpoints_description

    return get_endpoints_description(
        domain_hint=domain_hint,
        time_hint=time_hint,
        granularity_hint=granularity_hint,
        max_per_domain=None,  # 员工域内端点数有限，不截断
        allowed_endpoints=allowed,
    )


def filter_skills_description(allowed: frozenset[str]) -> str:
    """生成仅包含白名单内技能的 LLM Prompt 描述文本。"""
    from backend.agent.skills import get_skills_description

    return get_skills_description(allowed_skills=allowed)
