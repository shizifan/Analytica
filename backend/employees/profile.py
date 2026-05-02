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
    # P3.2 — per-employee override of the global ``PLANNING_RULE_HINTS``
    # entries (e.g. ``minimization`` / ``time_param`` / ``cargo_selection``).
    # Semantics, applied per key:
    #   * key absent       → use the global default
    #   * value is ""      → SKIP this rule section (renders empty)
    #   * value is non-""  → REPLACE the default with this string
    # Unknown keys are ignored — they don't crash the prompt builder.
    rule_hints: dict[str, str] = Field(default_factory=dict)
    search_domain_prefix: str = ""  # 搜索 query 自动追加的领域前缀（如"辽港集团 港航物流"）


# ── EmployeeProfile ────────────────────────────────────────


class FAQItem(BaseModel):
    """Phase 4: FAQ entries moved from frontend-only `employeeFaq.ts`
    into the authoritative employee profile so admins can edit them."""

    id: str
    question: str
    tag: Optional[str] = None
    type: Optional[str] = None


class EmployeeProfile(BaseModel):
    employee_id: str
    name: str
    description: str = ""
    version: str = "1.0"
    domains: list[str]
    endpoints: list[str] = Field(default_factory=list)
    tools: list[str]
    perception: PerceptionConfig = Field(default_factory=PerceptionConfig)
    planning: PlanningConfig = Field(default_factory=PlanningConfig)
    # ── Phase 4 additions (DB-first fields) ──
    initials: Optional[str] = None
    status: str = "active"
    faqs: list[FAQItem] = Field(default_factory=list)

    # ── class methods ──

    @classmethod
    def from_yaml(cls, path: Path) -> EmployeeProfile:
        """从 YAML 文件加载 EmployeeProfile。"""
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls(**data)

    # ── 派生属性 ──

    def get_endpoint_names(self) -> frozenset[str]:
        """返回端点白名单。若 endpoints 为空，从 domains 自动推导。

        无论来源是 yaml/DB 显式列出，还是从 domains 自动推导，结果都会
        与运行时 api_registry (BY_NAME) 取交集 —— 自动剔除已下线/重命名
        但 DB 还未同步的陈旧引用，避免它们进入 LLM prompt 与计划验证链路。
        """
        from backend.agent.api_registry import BY_NAME, BY_DOMAIN

        if self.endpoints:
            raw_names: set[str] = set(self.endpoints)
        else:
            raw_names = {ep.name for d in self.domains for ep in BY_DOMAIN.get(d, [])}

        valid = raw_names & set(BY_NAME.keys())
        stale = raw_names - valid
        if stale:
            logger.warning(
                "[%s] dropping %d stale endpoint(s) not in api_registry: %s",
                self.employee_id, len(stale), sorted(stale),
            )
        return frozenset(valid)

    def get_tool_ids(self) -> frozenset[str]:
        """返回工具白名单。"""
        return frozenset(self.tools)

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
        """启动时校验端点和工具是否存在于运行时注册表。返回错误列表。"""
        errors: list[str] = []

        # 校验端点
        from backend.agent.api_registry import BY_NAME
        for ep_name in self.get_endpoint_names():
            if ep_name not in BY_NAME:
                errors.append(f"[{self.employee_id}] Unknown endpoint: {ep_name}")

        # 校验工具
        from backend.tools.registry import ToolRegistry
        runtime_ids = ToolRegistry.get_instance().tool_ids
        for tid in self.tools:
            if tid not in runtime_ids:
                errors.append(f"[{self.employee_id}] Unknown tool: {tid}")

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
