"""Multi-round planning contract.

Pure-Python tests for the deterministic stitch step (no LLM, no DB).
The stitch step is the only place where global tasks (G_ATTR / G_SUM /
G_REPORT_*) get appended and wired up — these tests pin down its
behaviour: dependency wiring, partial-failure tolerance, attribution
opt-out, and multi-format report fan-out.
"""
from __future__ import annotations

import pytest

from backend.agent.planning import PlanningEngine, _extract_time_hints
from backend.exceptions import PlanningError
from backend.models.schemas import PlanSection, PlanSkeleton, TaskItem
from backend.tools.loader import load_all_tools

pytestmark = pytest.mark.contract


@pytest.fixture(scope="module", autouse=True)
def _ensure_tools_loaded():
    load_all_tools()


@pytest.fixture
def engine():
    return PlanningEngine(llm=None, llm_timeout=10, max_retries=1)


def _section_tasks(prefix: str, n_data: int = 2) -> list[TaskItem]:
    """Mimic what _call_section_llm would return for one section."""
    out: list[TaskItem] = []
    for i in range(n_data):
        out.append(TaskItem(
            task_id=f"{prefix}.T{i + 1}",
            type="data_fetch",
            tool="tool_api_fetch",
            params={"endpoint_id": "getInvestPlanByYear"},
        ))
    out.append(TaskItem(
        task_id=f"{prefix}.A1",
        type="analysis",
        tool="tool_desc_analysis",
        depends_on=[f"{prefix}.T1"],
        params={"data_ref": f"{prefix}.T1"},
    ))
    out.append(TaskItem(
        task_id=f"{prefix}.V1",
        type="visualization",
        tool="tool_chart_line",
        depends_on=[f"{prefix}.T1"],
        params={"chart_type": "line"},
    ))
    return out


def test_stitch_appends_global_tasks(engine):
    skel = PlanSkeleton(
        title="t", analysis_goal="g",
        needs_attribution=True, output_formats=["HTML"],
        sections=[
            PlanSection(section_id="S1", name="趋势"),
            PlanSection(section_id="S2", name="结构"),
        ],
    )
    results = [_section_tasks("S1"), _section_tasks("S2")]

    plan = engine._stitch_plan({}, skel, results)

    ids = [t.task_id for t in plan.tasks]
    assert "G_ATTR" in ids
    assert "G_SUM" in ids
    assert "G_REPORT_HTML" in ids
    # Section tasks must still be present
    assert "S1.T1" in ids
    assert "S2.V1" in ids


def test_stitch_summary_depends_on_all_analyses(engine):
    skel = PlanSkeleton(
        title="t", analysis_goal="g",
        needs_attribution=True,
        sections=[PlanSection(section_id="S1", name="x"),
                  PlanSection(section_id="S2", name="y")],
    )
    plan = engine._stitch_plan(
        {}, skel, [_section_tasks("S1"), _section_tasks("S2")],
    )
    summary = next(t for t in plan.tasks if t.task_id == "G_SUM")
    # Summary must depend on every analysis task, including G_ATTR
    assert "G_ATTR" in summary.depends_on
    assert "S1.A1" in summary.depends_on
    assert "S2.A1" in summary.depends_on


def test_stitch_report_depends_on_viz_and_summary(engine):
    skel = PlanSkeleton(
        title="t", analysis_goal="g", output_formats=["HTML"],
        sections=[PlanSection(section_id="S1", name="x")],
    )
    plan = engine._stitch_plan({}, skel, [_section_tasks("S1")])
    report = next(t for t in plan.tasks if t.task_id == "G_REPORT_HTML")
    assert "S1.V1" in report.depends_on
    assert "G_SUM" in report.depends_on


def test_stitch_skips_attribution_when_not_needed(engine):
    skel = PlanSkeleton(
        title="t", analysis_goal="g", needs_attribution=False,
        sections=[PlanSection(section_id="S1", name="x")],
    )
    plan = engine._stitch_plan({}, skel, [_section_tasks("S1")])
    assert all(t.task_id != "G_ATTR" for t in plan.tasks)
    # Summary should still exist (depends on S1.A1)
    summary = next(t for t in plan.tasks if t.task_id == "G_SUM")
    assert "G_ATTR" not in summary.depends_on


def test_stitch_multi_format_creates_multiple_report_tasks(engine):
    skel = PlanSkeleton(
        title="t", analysis_goal="g",
        output_formats=["HTML", "DOCX", "PPTX"],
        sections=[PlanSection(section_id="S1", name="x")],
    )
    plan = engine._stitch_plan({}, skel, [_section_tasks("S1")])
    report_tasks = [t for t in plan.tasks if t.type == "report_gen"]
    assert {t.tool for t in report_tasks} == {
        "tool_report_html", "tool_report_docx", "tool_report_pptx",
    }


def test_stitch_tolerates_partial_failure(engine):
    skel = PlanSkeleton(
        title="t", analysis_goal="g",
        sections=[PlanSection(section_id=f"S{i}", name=f"sec{i}")
                  for i in range(5)],
    )
    results = [_section_tasks(f"S{i}") for i in range(5)]
    results[1] = TimeoutError("simulated section failure")  # 1/5 = 20%
    plan = engine._stitch_plan({}, skel, results)

    # Failed section's tasks dropped, report_structure shrunk
    section_names = [s["name"] for s in plan.report_structure["sections"]]
    assert "sec1" not in section_names
    assert len(section_names) == 4
    # revision_log records the drop with the contract the graph layer relies on
    log_entry = plan.revision_log[0]
    assert log_entry["phase"] == "multi_round_stitch"
    assert log_entry["sections_kept"] == 4
    assert log_entry["sections_total"] == 5
    assert any("S1" in sid for sid, _ in log_entry["failed_sections"])


def test_stitch_too_many_failures_raises(engine):
    skel = PlanSkeleton(
        title="t", analysis_goal="g",
        sections=[PlanSection(section_id=f"S{i}", name=f"sec{i}")
                  for i in range(4)],
    )
    # 3/4 = 75% failure, default cap is 40%
    results = [
        TimeoutError("x"), TimeoutError("y"), TimeoutError("z"),
        _section_tasks("S3"),
    ]
    with pytest.raises(PlanningError, match="too many sections failed"):
        engine._stitch_plan({}, skel, results)


def test_stitch_treats_empty_section_as_failure(engine):
    skel = PlanSkeleton(
        title="t", analysis_goal="g",
        sections=[PlanSection(section_id="S1", name="x"),
                  PlanSection(section_id="S2", name="y")],
    )
    plan = engine._stitch_plan({}, skel, [_section_tasks("S1"), []])
    # S2 dropped from report_structure
    section_names = [s["name"] for s in plan.report_structure["sections"]]
    assert "y" not in section_names


def test_stitch_no_data_fetch_skips_attribution(engine):
    """If sections produce no data_fetch tasks, G_ATTR has nothing to depend on."""
    skel = PlanSkeleton(
        title="t", analysis_goal="g", needs_attribution=True,
        sections=[PlanSection(section_id="S1", name="x")],
    )
    # Section returns only an analysis task with no data_fetch upstream
    only_analysis = [TaskItem(
        task_id="S1.A1", type="analysis", tool="tool_desc_analysis",
    )]
    plan = engine._stitch_plan({}, skel, [only_analysis])
    assert all(t.task_id != "G_ATTR" for t in plan.tasks)


def test_extract_output_formats_from_slot(engine):
    intent = {"slots": {"output_format": {"value": ["html", "docx"]}}}
    assert engine._extract_output_formats(intent) == ["HTML", "DOCX"]


def test_extract_output_formats_default(engine):
    assert engine._extract_output_formats({}) == ["HTML"]


def test_extract_output_formats_dedupe_and_normalize(engine):
    intent = {"slots": {"output_format": {"value": ["html", "HTML", "pptx"]}}}
    assert engine._extract_output_formats(intent) == ["HTML", "PPTX"]


def test_enrich_section_endpoints_from_domain(engine):
    skel = PlanSkeleton(sections=[
        PlanSection(section_id="S1", name="x", domain_hint="D2"),
    ])
    engine._enrich_section_endpoints(skel)
    assert skel.sections[0].endpoint_hints  # populated from BY_DOMAIN
    assert len(skel.sections[0].endpoint_hints) <= 8


def test_enrich_preserves_existing_hints(engine):
    skel = PlanSkeleton(sections=[
        PlanSection(
            section_id="S1", name="x", domain_hint="D2",
            endpoint_hints=["already_set_endpoint"],
        ),
    ])
    engine._enrich_section_endpoints(skel)
    assert skel.sections[0].endpoint_hints == ["already_set_endpoint"]


# ── Tier 1: _extract_time_hints ─────────────────────────────────

def test_extract_time_hints_full_range():
    intent = {
        "slots": {
            "time_range": {
                "value": {"start": "2026-01-01", "end": "2026-03-31",
                          "description": "2026年Q1"},
            }
        }
    }
    hints = _extract_time_hints(intent)
    assert hints == {
        "date": "2026-03-31",
        "dateMonth": "2026-03",
        "dateYear": "2026",
        "endDate": "2026-03-31",
        "startDate": "2026-01-01",
    }


def test_extract_time_hints_no_slots():
    assert _extract_time_hints({}) is None


def test_extract_time_hints_no_time_range():
    intent = {"slots": {"domain": {"value": "D2"}}}
    assert _extract_time_hints(intent) is None


def test_extract_time_hints_time_range_not_dict():
    """slots.time_range.value 为非 dict 时的防御"""
    intent = {"slots": {"time_range": {"value": "2026年Q1"}}}
    assert _extract_time_hints(intent) is None


def test_extract_time_hints_no_start():
    """仅有 end 时的推导"""
    intent = {
        "slots": {
            "time_range": {
                "value": {"end": "2026-12-31", "description": "2026年"},
            }
        }
    }
    hints = _extract_time_hints(intent)
    assert hints["dateYear"] == "2026"
    assert hints["dateMonth"] == "2026-12"
    assert "startDate" not in hints


def test_extract_time_hints_no_end():
    """仅有 start 时的推导"""
    intent = {
        "slots": {
            "time_range": {
                "value": {"start": "2026-01-01"},
            }
        }
    }
    hints = _extract_time_hints(intent)
    assert hints["startDate"] == "2026-01-01"
    assert "dateYear" not in hints


# ── Tier 2: _validate_section_tasks ────────────────────────────

def test_validate_section_tasks_clean(engine):
    """所有任务有效 → 返回空列表"""
    tasks = [
        TaskItem(
            task_id="S1.T1", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getInvestPlanByYear", "dateYear": "2026"},
        ),
    ]
    valid_tools = {"tool_api_fetch"}
    valid_endpoints = {"getInvestPlanByYear"}
    issues = engine._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    assert issues == []


def test_validate_section_tasks_missing_required_param(engine):
    """缺必填参数 → 返回 issue"""
    tasks = [
        TaskItem(
            task_id="S1.T1", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getEquipmentUsageRate"},  # 缺 dateYear
        ),
    ]
    valid_tools = {"tool_api_fetch"}
    valid_endpoints = {"getEquipmentUsageRate"}
    issues = engine._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    assert len(issues) == 1
    assert issues[0]["task_id"] == "S1.T1"
    assert "missing required params" in issues[0]["reason"]
    assert "dateYear" in issues[0]["reason"]


def test_validate_section_tasks_hallucinated_endpoint(engine):
    """幻觉端点 → 返回 issue"""
    tasks = [
        TaskItem(
            task_id="S1.T1", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "nonexistentEndpoint"},
        ),
    ]
    valid_tools = {"tool_api_fetch"}
    valid_endpoints = {"getThroughputAndTargetThroughputTon"}
    issues = engine._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    assert len(issues) == 1
    assert "hallucinated endpoint" in issues[0]["reason"]


def test_validate_section_tasks_mixed(engine):
    """混合场景：部分有效、部分无效"""
    tasks = [
        TaskItem(
            task_id="S1.T1", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getEquipmentUsageRate"},  # 缺 dateYear
        ),
        TaskItem(
            task_id="S1.T2", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getInvestPlanByYear", "dateYear": "2026"},
        ),
        TaskItem(
            task_id="S1.T3", type="data_fetch", tool="tool_api_fetch",
            params={"endpoint_id": "getProductionEquipmentFaultNum"},  # 缺 dateYear
        ),
    ]
    valid_tools = {"tool_api_fetch"}
    valid_endpoints = {"getEquipmentUsageRate", "getInvestPlanByYear",
                       "getProductionEquipmentFaultNum"}
    issues = engine._validate_section_tasks(tasks, valid_tools, valid_endpoints)
    assert len(issues) == 2
    affected_ids = {i["task_id"] for i in issues}
    assert affected_ids == {"S1.T1", "S1.T3"}
