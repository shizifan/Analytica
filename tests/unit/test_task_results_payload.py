"""Phase 3.7: _build_task_results_payload shape + rounding contract."""
from __future__ import annotations

import pandas as pd

from backend.agent.execution import _build_task_results_payload
from backend.models.schemas import TaskItem
from backend.skills.base import SkillOutput


def _task(tid: str, skill: str, ttype: str, deps: list[str] | None = None,
          params: dict | None = None) -> TaskItem:
    return TaskItem(
        task_id=tid,
        type=ttype,
        name=f"name-{tid}",
        description="",
        depends_on=deps or [],
        skill=skill,
        params=params or {},
        estimated_seconds=1,
    )


def test_dataframe_becomes_table_with_full_rows_for_csv():
    tasks = [_task("T001", "skill_api_fetch", "data_fetch", params={"endpoint_id": "getFoo"})]
    df = pd.DataFrame({"dateMonth": ["2026-01", "2026-02"], "qty": [100.0, 200.5]})
    out = SkillOutput(
        skill_id="skill_api_fetch",
        status="success",
        output_type="dataframe",
        data=df,
    )
    payload = _build_task_results_payload(tasks, {"T001": out}, {"T001": "done"})
    assert len(payload["tasks"]) == 1
    entry = payload["tasks"][0]
    assert entry["output_type"] == "table"
    assert entry["source_api"] == "getFoo"
    assert entry["data"]["columns"] == ["dateMonth", "qty"]
    assert entry["data"]["total_rows"] == 2
    assert entry["data"]["rows"] == [["2026-01", 100.0], ["2026-02", 200.5]]


def test_chart_output_preserves_depends_on_and_option():
    tasks = [
        _task("T001", "skill_api_fetch", "data_fetch"),
        _task("T002", "skill_chart_line", "visualization", deps=["T001"]),
    ]
    df = pd.DataFrame({"dateMonth": ["2026-01"], "qty": [100]})
    ctx = {
        "T001": SkillOutput(skill_id="skill_api_fetch", status="success", output_type="dataframe", data=df),
        "T002": SkillOutput(
            skill_id="skill_chart_line",
            status="success",
            output_type="chart",
            data={"title": {"text": "Trend"}, "series": [{"type": "line", "data": [100]}]},
        ),
    }
    payload = _build_task_results_payload(tasks, ctx, {"T001": "done", "T002": "done"})
    chart_entry = next(t for t in payload["tasks"] if t["task_id"] == "T002")
    assert chart_entry["output_type"] == "chart"
    assert chart_entry["depends_on"] == ["T001"]
    assert chart_entry["data"]["option"]["title"]["text"] == "Trend"


def test_text_and_json_narrative_become_text():
    tasks = [
        _task("T001", "skill_desc_analysis", "analysis"),
        _task("T002", "skill_attribution", "analysis"),
    ]
    ctx = {
        "T001": SkillOutput(skill_id="skill_desc_analysis", status="success", output_type="text", data="dataset mean 3123"),
        "T002": SkillOutput(
            skill_id="skill_attribution", status="success", output_type="json",
            data={"narrative": "因 A 增长 5% 贡献 60%", "raw": {"A": 5, "B": 2}},
        ),
    }
    payload = _build_task_results_payload(tasks, ctx, {"T001": "done", "T002": "done"})
    assert payload["tasks"][0]["output_type"] == "text"
    assert payload["tasks"][0]["data"]["text"] == "dataset mean 3123"
    assert payload["tasks"][1]["output_type"] == "text"
    assert payload["tasks"][1]["data"]["text"].startswith("因 A")


def test_failed_and_skipped_tasks_filtered_out():
    tasks = [_task("T001", "skill_api_fetch", "data_fetch")]
    out = SkillOutput(skill_id="skill_api_fetch", status="failed", output_type="dataframe", data=None)
    payload = _build_task_results_payload(tasks, {"T001": out}, {"T001": "failed"})
    assert payload["tasks"] == []


def test_report_pipeline_hides_intermediate_tasks():
    """When the pipeline produces a file (HTML report), the chat stream
    payload must omit the upstream table / chart / text cards — all that
    info lives in the rendered report file."""
    tasks = [
        _task("T001", "skill_api_fetch", "data_fetch"),
        _task("T002", "skill_desc_analysis", "analysis", deps=["T001"]),
        _task("T003", "skill_chart_line", "visualization", deps=["T001"]),
        _task("T004", "skill_report_html", "report_gen", deps=["T001", "T002", "T003"]),
    ]
    df = pd.DataFrame({"month": ["2026-01"], "qty": [100]})
    ctx = {
        "T001": SkillOutput(skill_id="skill_api_fetch", status="success", output_type="dataframe", data=df),
        "T002": SkillOutput(skill_id="skill_desc_analysis", status="success", output_type="text", data="均值 100"),
        "T003": SkillOutput(skill_id="skill_chart_line", status="success", output_type="chart", data={"series": []}),
        "T004": SkillOutput(skill_id="skill_report_html", status="success", output_type="file",
                            data="<html/>", metadata={"format": "html", "title": "Q1 报告"}),
    }
    statuses = {t.task_id: "done" for t in tasks}

    payload = _build_task_results_payload(
        tasks, ctx, statuses,
        artifacts={"T004": {"id": "art-1", "size_bytes": 5900}},
    )
    ids = [e["task_id"] for e in payload["tasks"]]
    assert ids == ["T004"], "only file-output task should remain"
    assert payload.get("pipeline") == "report"
    assert payload["tasks"][0]["data"]["artifact_id"] == "art-1"


def test_non_report_pipeline_keeps_all_entries():
    """Without any file output, the normal structured payload wins."""
    tasks = [
        _task("T001", "skill_api_fetch", "data_fetch"),
        _task("T002", "skill_chart_line", "visualization", deps=["T001"]),
    ]
    df = pd.DataFrame({"month": ["2026-01"], "qty": [100]})
    ctx = {
        "T001": SkillOutput(skill_id="skill_api_fetch", status="success", output_type="dataframe", data=df),
        "T002": SkillOutput(skill_id="skill_chart_line", status="success", output_type="chart", data={"series": []}),
    }
    statuses = {t.task_id: "done" for t in tasks}
    payload = _build_task_results_payload(tasks, ctx, statuses)
    assert {e["task_id"] for e in payload["tasks"]} == {"T001", "T002"}
    assert payload.get("pipeline") is None


def test_nulls_preserved_in_table_rows():
    """NaN in the DataFrame should serialize as JSON null (not 'NaN'
    string) so the frontend can render em-dash consistently."""
    tasks = [_task("T001", "skill_api_fetch", "data_fetch")]
    df = pd.DataFrame({"a": [1, None], "b": ["x", None]})
    ctx = {"T001": SkillOutput(skill_id="skill_api_fetch", status="success", output_type="dataframe", data=df)}
    payload = _build_task_results_payload(tasks, ctx, {"T001": "done"})
    rows = payload["tasks"][0]["data"]["rows"]
    assert rows[1][0] is None
    assert rows[1][1] is None
