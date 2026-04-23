# Compatibility shim — backend.skills has been renamed to backend.tools.
# This file exists only so any leftover import of backend.skills.* still works.
from backend.tools.base import (  # noqa: F401
    BaseSkill, SkillInput, SkillOutput, SkillCategory, ErrorCategory,
    classify_exception, skill_executor,
)
from backend.tools.registry import SkillRegistry, register_skill  # noqa: F401
from backend.tools.loader import load_all_skills, load_extra_skills  # noqa: F401
