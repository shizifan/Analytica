"""EmployeeProfile — 数字员工配置模型 + YAML 加载器。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

import yaml
from pydantic import BaseModel, Field, model_validator

logger = logging.getLogger("analytica.employees.profile")


# ── 感知层配置 ─────────────────────────────────────────────


class ExtraSlotDef(BaseModel):
    """员工域专属的额外槽位定义。"""

    name: str
    required: bool = False
    priority: int = 10
    inferable: bool = True
    meaning: str = ""
    allowed_values: list[str] = Field(default_factory=list)


class SlotConstraint(BaseModel):
    """对基础槽位的值域约束 / 默认值覆盖。"""

    allowed_values: list[str] = Field(default_factory=list)
    default_value: Optional[Any] = None


class PerceptionConfig(BaseModel):
    domain_keywords: dict[str, list[str]] = Field(default_factory=dict)
    system_prompt_suffix: str = ""
    slot_defaults: dict[str, Any] = Field(default_factory=dict)
    extra_slots: list[ExtraSlotDef] = Field(default_factory=list)
    slot_constraints: dict[str, SlotConstraint] = Field(default_factory=dict)


# ── 规划层配置 ─────────────────────────────────────────────


class PlanningConfig(BaseModel):
    prompt_suffix: str = ""
    preferred_endpoints: list[str] = Field(default_factory=list)


# ── EmployeeProfile ────────────────────────────────────────


class EmployeeProfile(BaseModel):
    employee_id: str
    name: str
    description: str = ""
    version: str = "1.0"
    domains: list[str]
    endpoints: list[str] = Field(default_factory=list)
    skills: list[str]
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    planning: PlanningConfig = Field(default_factory=PlanningConfig)

    # ── class methods ──

    @classmethod
    def from_yaml(cls, path: Path) -> EmployeeProfile:
        """从 YAML 文件加载 EmployeeProfile。"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    # ── 派生属性 ──

    def get_endpoint_names(self) -> frozenset[str]:
        """返回端点白名单。若 endpoints 为空，从 domains 自动推导。"""
        if self.endpoints:
            return frozenset(self.endpoints)
        # 从 api_registry 按域自动推导
        from backend.agent.api_registry import BY_DOMAIN
        names: set[str] = set()
        for domain in self.domains:
            for ep in BY_DOMAIN.get(domain, []):
                names.add(ep.name)
        return frozenset(names)

    def get_skill_ids(self) -> frozenset[str]:
        """返回技能白名单。"""
        return frozenset(self.skills)

    def get_extra_slot_names(self) -> list[str]:
        """返回所有额外槽位名。"""
        return [s.name for s in self.perception.extra_slots]

    # ── 启动校验 ──

    @model_validator(mode="after")
    def _validate_domains(self) -> EmployeeProfile:
        valid = {"D1", "D2", "D3", "D4", "D5", "D6", "D7"}
        for d in self.domains:
            if d not in valid:
                raise ValueError(f"Unknown domain: {d}")
        return self

    def validate_against_registry(self) -> list[str]:
        """启动时校验端点和技能是否存在于运行时注册表。返回错误列表。"""
        errors: list[str] = []

        # 校验端点
        from backend.agent.api_registry import BY_NAME
        for ep_name in self.get_endpoint_names():
            if ep_name not in BY_NAME:
                errors.append(f"[{self.employee_id}] Unknown endpoint: {ep_name}")

        # 校验技能
        from backend.skills.registry import SkillRegistry
        runtime_ids = SkillRegistry.get_instance().skill_ids
        for sid in self.skills:
            if sid not in runtime_ids:
                errors.append(f"[{self.employee_id}] Unknown skill: {sid}")

        # 校验 extra_slots 不与基础槽位冲突
        from backend.models.schemas import ALL_SLOT_NAMES
        for es in self.perception.extra_slots:
            if es.name in ALL_SLOT_NAMES:
                errors.append(
                    f"[{self.employee_id}] extra_slot '{es.name}' conflicts with base slot"
                )

        # 校验 slot_constraints key 是否为已知槽位
        all_known = set(ALL_SLOT_NAMES) | {s.name for s in self.perception.extra_slots}
        for key in self.perception.slot_constraints:
            if key not in all_known:
                errors.append(
                    f"[{self.employee_id}] slot_constraint key '{key}' is not a known slot"
                )

        if errors:
            for e in errors:
                logger.error(e)
        else:
            logger.info("[%s] Profile validation passed", self.employee_id)

        return errors
