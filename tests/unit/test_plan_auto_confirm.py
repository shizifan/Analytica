"""Phase 3.5.1: auto-confirm for simple plans + confirm bypass routing."""
from __future__ import annotations

import pytest

from backend.agent.planning import format_plan_as_markdown, is_simple_plan
from backend.models.schemas import AnalysisPlan, TaskItem


def _plan(*task_types: str) -> AnalysisPlan:
    tasks = [
        TaskItem(
            task_id=f"T{i:03d}",
            type=t,
            name=f"任务 {i}",
            description="",
            depends_on=[],
            tool="tool_api_fetch" if t == "data_fetch" else f"tool_{t}",
            params={},
            estimated_seconds=5,
        )
        for i, t in enumerate(task_types, 1)
    ]
    return AnalysisPlan(
        plan_id="p",
        version=1,
        title="t",
        analysis_goal="g",
        estimated_duration=10,
        tasks=tasks,
    )


def test_simple_plan_threshold():
    assert is_simple_plan(_plan("data_fetch")) is True
    assert is_simple_plan(_plan("data_fetch", "analysis")) is True
    assert is_simple_plan(_plan("data_fetch", "analysis", "visualization")) is True


def test_plan_over_threshold_requires_confirmation():
    assert is_simple_plan(_plan("data_fetch", "data_fetch", "analysis", "visualization")) is False


def test_plan_with_report_gen_requires_confirmation():
    assert is_simple_plan(_plan("data_fetch", "report_gen")) is False


def test_empty_plan_not_simple():
    p = AnalysisPlan(
        plan_id="p",
        version=1,
        title="t",
        analysis_goal="g",
        estimated_duration=0,
        tasks=[],
    )
    assert is_simple_plan(p) is False


def test_markdown_omits_action_line_when_auto_confirmed():
    p = _plan("data_fetch", "analysis")
    md_normal = format_plan_as_markdown(p, auto_confirmed=False)
    md_auto = format_plan_as_markdown(p, auto_confirmed=True)
    assert "[确认执行]" in md_normal
    assert "[确认执行]" not in md_auto
    assert "_自动执行中…_" in md_auto


@pytest.mark.asyncio(loop_scope="function")
async def test_confirm_fast_path_does_not_rerun_perception(monkeypatch):
    """The '确认执行' short-circuit must not re-trigger perception, nor
    emit another intent summary message."""
    from backend.agent import graph as graph_mod

    # Stub perception so a re-run would be visible. If fast path works,
    # this stub is never called.
    perception_calls = {"n": 0}

    async def fake_perception(state):
        perception_calls["n"] += 1
        return state

    monkeypatch.setattr(graph_mod, "perception_node", fake_perception)

    # Stub execution to skip actual tool work.
    async def fake_exec(state):
        state["task_statuses"] = {"T001": "done"}
        return state

    monkeypatch.setattr(
        "backend.agent.execution.execution_node",
        fake_exec,
    )

    # Seed a pending plan into the session.
    from backend.database import get_session_factory
    from backend.memory.store import MemoryStore
    from sqlalchemy import text
    import uuid
    sid = f"confirm-fp-{uuid.uuid4().hex[:8]}"
    factory = get_session_factory()
    async with factory() as db:
        await MemoryStore(db).create_session(sid, "u1")
        await db.execute(
            text(
                "UPDATE sessions SET state_json = :sj WHERE session_id = :sid"
            ),
            {
                "sid": sid,
                "sj": '{"slots": {"x": {"value": 1}},'
                      '"analysis_plan": {"plan_id": "p", "version": 1,'
                      ' "title": "t", "analysis_goal": "g",'
                      ' "tasks": [{"task_id": "T001", "type": "data_fetch",'
                      ' "name": "n", "description": "", "depends_on": [],'
                      ' "tool": "tool_api_fetch", "params": {},'
                      ' "estimated_seconds": 5}]},'
                      '"plan_confirmed": false,'
                      '"messages": []}',
            },
        )
        await db.commit()

    try:
        emitted_execution = False
        async for evt in graph_mod.run_stream(sid, "u1", "确认执行"):
            if "execution" in evt:
                emitted_execution = True

        assert perception_calls["n"] == 0, "perception should not re-run on '确认执行'"
        assert emitted_execution, "execution node must have been invoked via fast path"
    finally:
        async with factory() as db:
            await db.execute(
                text("DELETE FROM sessions WHERE session_id = :s"), {"s": sid}
            )
            await db.commit()
