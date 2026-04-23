"""Skill Registry — singleton registry with @register_skill decorator.

Skills register themselves at import time via the decorator.
"""
from __future__ import annotations

import logging
from typing import Optional

from backend.tools.base import BaseSkill, SkillCategory

logger = logging.getLogger("analytica.tools.registry")


class SkillRegistry:
    """Singleton skill registry."""

    _instance: Optional[SkillRegistry] = None
    _skills: dict[str, BaseSkill]

    def __init__(self) -> None:
        self._skills = {}

    @classmethod
    def get_instance(cls) -> SkillRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def register(self, skill: BaseSkill) -> None:
        logger.info("Registering skill: %s", skill.skill_id)
        self._skills[skill.skill_id] = skill

    def get_skill(self, skill_id: str) -> Optional[BaseSkill]:
        return self._skills.get(skill_id)

    def list_skills(self, category: Optional[str] = None) -> list[dict]:
        results = []
        for sid, skill in self._skills.items():
            if category and skill.category.value != category:
                continue
            results.append({
                "skill_id": sid,
                "category": skill.category.value,
                "description": skill.description,
            })
        return results

    def get_skills_description(self) -> str:
        lines = []
        for sid, skill in self._skills.items():
            lines.append(f"- {sid} [{skill.category.value}]: {skill.description}")
        return "\n".join(lines)

    @property
    def skill_ids(self) -> set[str]:
        return set(self._skills.keys())


def register_skill(
    skill_id: str,
    category: SkillCategory,
    description: str,
    input_spec: str = "",
    output_spec: str = "",
    planner_visible: bool = True,
):
    """Decorator to register a skill class at import time."""
    def decorator(cls):
        instance = cls()
        instance.skill_id = skill_id
        instance.category = category
        instance.description = description
        instance.input_spec = input_spec
        instance.output_spec = output_spec
        instance.planner_visible = planner_visible
        SkillRegistry.get_instance().register(instance)
        return cls
    return decorator
