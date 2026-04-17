"""Skill base classes and unified output model.

Defines BaseSkill (abstract), SkillInput, SkillOutput, SkillCategory,
and the async skill_executor with timeout support.
"""
from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel

logger = logging.getLogger("analytica.skills")


class SkillCategory(str, Enum):
    DATA_FETCH = "data_fetch"
    ANALYSIS = "analysis"
    VISUALIZATION = "visualization"
    REPORT = "report"
    SEARCH = "search"


class SkillInput(BaseModel):
    params: dict[str, Any] = {}
    context_refs: list[str] = []


class SkillOutput(BaseModel):
    skill_id: str
    status: str  # success | failed | partial
    output_type: str  # dataframe | chart | text | file | json
    data: Any = None
    storage_ref: Optional[str] = None
    metadata: dict[str, Any] = {}
    error_message: Optional[str] = None

    model_config = {"arbitrary_types_allowed": True}


class BaseSkill(ABC):
    skill_id: str = ""
    category: SkillCategory = SkillCategory.DATA_FETCH
    description: str = ""
    input_spec: str = ""    # 供规划层 prompt 使用，如 "endpoint_id + 查询参数"
    output_spec: str = ""   # 供规划层 prompt 使用，如 "DataFrame (JSON 数据)"
    planner_visible: bool = True  # 是否出现在规划层 prompt 中

    @abstractmethod
    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        ...

    def _fail(self, message: str) -> SkillOutput:
        return SkillOutput(
            skill_id=self.skill_id,
            status="failed",
            output_type="json",
            data=None,
            error_message=message,
        )


async def skill_executor(
    skill: BaseSkill,
    inp: SkillInput,
    context: dict[str, Any],
    timeout_seconds: float = 60.0,
) -> SkillOutput:
    """Execute a skill with timeout. Returns SkillOutput(status='failed') on timeout."""
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            skill.execute(inp, context),
            timeout=timeout_seconds,
        )
        elapsed = time.monotonic() - start
        logger.info(
            "Skill %s completed in %.2fs with status=%s",
            skill.skill_id, elapsed, result.status,
        )
        return result
    except asyncio.TimeoutError:
        elapsed = time.monotonic() - start
        logger.warning("Skill %s timed out after %.2fs", skill.skill_id, elapsed)
        return SkillOutput(
            skill_id=skill.skill_id,
            status="failed",
            output_type="json",
            data=None,
            error_message=f"Timeout after {timeout_seconds:.0f}s",
        )
    except Exception as e:
        elapsed = time.monotonic() - start
        logger.exception("Skill %s failed after %.2fs: %s", skill.skill_id, elapsed, e)
        return SkillOutput(
            skill_id=skill.skill_id,
            status="failed",
            output_type="json",
            data=None,
            error_message=str(e),
        )
