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


def _build_slot_condition(slot_name: str) -> str | None:
    """Derive a slot's condition string from the single source of truth.

    Returns None when the slot is relevant to every complexity level (no
    filtering needed), or when the slot is relevant to no complexity level.
    """
    from backend.agent._complexity_rules import COMPLEXITY_RULES

    relevant_complexities = [
        complexity for complexity, rule in COMPLEXITY_RULES.items()
        if slot_name in rule.relevant_slots
    ]
    if not relevant_complexities or len(relevant_complexities) == len(COMPLEXITY_RULES):
        return None
    if len(relevant_complexities) == 1:
        return f"output_complexity={relevant_complexities[0]}"
    return f"output_complexity in [{','.join(sorted(relevant_complexities))}]"


SLOT_SCHEMA: list[SlotDefinition] = [
    SlotDefinition(name="analysis_subject", required=True, priority=2, inferable=False),
    SlotDefinition(name="time_range", required=True, priority=1, inferable=False),
    SlotDefinition(name="output_complexity", required=False, priority=3, inferable=True),
    SlotDefinition(name="output_format", required=False, priority=4,
                   condition=_build_slot_condition("output_format")),
    SlotDefinition(name="attribution_needed", required=False, priority=5, inferable=True,
                   condition=_build_slot_condition("attribution_needed")),
    SlotDefinition(name="predictive_needed", required=False, priority=6, inferable=True,
                   condition=_build_slot_condition("predictive_needed")),
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
    "data_fetch", "search", "analysis", "visualization", "summary", "report_gen"
]


class TaskItem(BaseModel):
    task_id: str
    type: TaskType = "data_fetch"
    name: str = ""
    description: str = ""
    depends_on: list[str] = Field(default_factory=list)
    tool: str = ""
    params: dict[str, Any] = Field(default_factory=dict)
    estimated_seconds: int = 10
    # Execution-phase fields (Phase 3)
    status: str = "pending"
    output_ref: str = ""
    # Intent field: human-readable goal for this task (visualization/analysis)
    # Tools use this at execution time to drive LLM-powered decisions.
    intent: str = ""


class AnalysisPlan(BaseModel):
    plan_id: str = Field(default_factory=lambda: str(uuid4()))
    version: int = 1
    title: str = ""
    analysis_goal: str = ""
    estimated_duration: int = 0
    tasks: list[TaskItem] = Field(default_factory=list)
    report_structure: Optional[dict[str, Any]] = None
    revision_log: list[dict[str, Any]] = Field(default_factory=list)


# ── Multi-round Planning (full_report) ───────────────────────
# Used by PlanningEngine when ENABLE_MULTI_ROUND_PLANNING is on:
# round 1 produces a PlanSkeleton (sections only), round 2 fills each
# section's concrete tasks in parallel, then a deterministic stitch step
# assembles the final AnalysisPlan.

class PlanSection(BaseModel):
    section_id: str
    name: str
    description: str = ""
    focus_metrics: list[str] = Field(default_factory=list)
    domain_hint: Optional[str] = None
    endpoint_hints: list[str] = Field(default_factory=list)
    expected_task_count: int = 3


class PlanSkeleton(BaseModel):
    title: str = ""
    analysis_goal: str = ""
    sections: list[PlanSection] = Field(default_factory=list)
    needs_attribution: bool = True
    output_formats: list[str] = Field(default_factory=lambda: ["HTML"])


# ── Tool Result (placeholder for Phase 3) ────────────────────

class ToolResult(BaseModel):
    tool_id: str = ""
    status: str = "pending"
    output: Any = None
    error: Optional[str] = None
    duration_ms: float = 0.0
