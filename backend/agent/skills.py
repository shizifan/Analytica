"""Skill descriptions — 从运行时 SkillRegistry 动态生成。

供规划层 Prompt 注入。不再维护静态 dict，所有技能元数据来自 @register_skill。
"""
from __future__ import annotations

from typing import Optional


def get_skills_description(allowed_skills: Optional[frozenset[str]] = None) -> str:
    """从运行时 SkillRegistry 动态生成规划层技能描述。

    Args:
        allowed_skills: 技能 ID 白名单；None 表示不过滤。
    """
    from backend.skills.registry import SkillRegistry
    registry = SkillRegistry.get_instance()
    lines: list[str] = []
    for sid, skill in registry._skills.items():
        if not skill.planner_visible:
            continue
        if allowed_skills is not None and sid not in allowed_skills:
            continue
        lines.append(f"- {sid}: {skill.description}")
        if skill.input_spec or skill.output_spec:
            lines.append(f"  输入: {skill.input_spec} → 输出: {skill.output_spec}")
    return "\n".join(lines)


def get_valid_skill_ids(allowed_skills: Optional[frozenset[str]] = None) -> set[str]:
    """从运行时注册表获取合法技能 ID 集合。"""
    from backend.skills.registry import SkillRegistry
    all_ids = SkillRegistry.get_instance().skill_ids
    if allowed_skills is not None:
        return all_ids & allowed_skills
    return all_ids


def is_valid_skill(skill_id: str) -> bool:
    """检查技能 ID 是否在运行时注册表中。"""
    from backend.skills.registry import SkillRegistry
    return skill_id in SkillRegistry.get_instance().skill_ids
