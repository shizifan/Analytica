from __future__ import annotations
from typing import Any, Literal, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


# ── Slot Definitions ─────────────────────────────────────────

class SlotDefinition(BaseModel):
    """Defines a single slot in the Slot schema."""

    name: str
    required: bool
    condition: Optional[str] = None
    priority: int
    inferable: bool = False


SLOT_SCHEMA: list[SlotDefinition] = [
    SlotDefinition(name="analysis_subject", required=True, priority=2, inferable=False),
    SlotDefinition(name="time_range", required=True, priority=1, inferable=False),
    SlotDefinition(name="output_complexity", required=False, priority=3, inferable=True),
    SlotDefinition(name="output_format", required=False, priority=4, condition="output_complexity=full_report"),
    SlotDefinition(name="attribution_needed", required=False, priority=5, inferable=True, condition="output_complexity in [chart_text,full_report]"),
    SlotDefinition(name="predictive_needed", required=False, priority=6, inferable=True, condition="output_complexity=full_report"),
    SlotDefinition(name="time_granularity", required=False, priority=99, inferable=True),
    SlotDefinition(name="domain", required=False, priority=7, inferable=True),
    SlotDefinition(name="domain_glossary", required=False, priority=99, inferable=True),
    SlotDefinition(name="comparison_type", required=False, priority=99, inferable=True),
    SlotDefinition(name="region", required=False, priority=99, inferable=True),
    SlotDefinition(name="data_granularity", required=False, priority=99, inferable=True),
]

ALL_SLOT_NAMES = [s.name for s in SLOT_SCHEMA]

SLOT_SCHEMA_MAP: dict[str, SlotDefinition] = {s.name: s for s in SLOT_SCHEMA}


# ── Slot Values ──────────────────────────────────────────────

SlotSource = Literal["user_input", "history", "memory", "memory_low_confidence", "inferred", "default"]


class SlotValue(BaseModel):
    """Value of a single slot with provenance."""

    value: Optional[Any] = None
    source: SlotSource = "default"
    confirmed: bool = False


# ── Structured Intent ────────────────────────────────────────

class StructuredIntent(BaseModel):
    """The structured analysis intent output by the perception layer."""

    intent_id: str = Field(default_factory=lambda: str(uuid4()))
    raw_query: str
    analysis_goal: str = ""
    slots: dict[str, SlotValue]
    empty_required_slots: list[str] = Field(default_factory=list)
    clarification_history: list[dict[str, Any]] = Field(default_factory=list)


# ── Analysis Plan ─────────────────────────────────────────────

TaskType = Literal[
    "data_fetch", "search", "analysis", "visualization", "report_gen"
]


class TaskItem(BaseModel):
    task_id: str
    type: TaskType = "data_fetch"
    name: str = ""
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    skill: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    estimated_seconds: int = 10
    # Execution-phase fields (Phase 3)
    status: str = "pending"
    output_ref: str = ""


class AnalysisPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = 1
    title: str = ""
    analysis_goal: str = ""
    estimated_duration: int = 0
    tasks: list[TaskItem] = Field(default_factory=list)
    report_structure: Optional[dict[str, Any]] = None
    revision_log: list[dict[str, Any]] = Field(default_factory=list)


# ── Skill Result (placeholder for Phase 3) ───────────────────

class SkillResult(BaseModel):
    skill_id: str = ""
    status: str = "pending"
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
