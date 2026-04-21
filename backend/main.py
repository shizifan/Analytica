from __future__ import annotations
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from pydantic import BaseModel, Field
from sqlalchemy import text

from backend.database import get_db_session, get_engine, Base
from backend.memory.store import MemoryStore
from backend.agent.graph import run_stream

logger = logging.getLogger("analytica")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Analytica backend starting...")

    # 加载技能
    from backend.skills.loader import load_all_skills
    skill_count = load_all_skills()
    logger.info("Loaded %d skill modules", skill_count)

    # 加载员工配置
    from pathlib import Path
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    config_dir = Path(__file__).resolve().parent.parent / "employees"
    emp_count = manager.load_all_profiles(config_dir)
    logger.info("Loaded %d employee profiles", emp_count)

    # 启动校验
    if emp_count > 0:
        errors = manager.validate_all_profiles()
        if errors:
            for e in errors:
                logger.error("Profile validation: %s", e)
        else:
            logger.info("All employee profiles validated successfully")

    yield
    engine = get_engine()
    await engine.dispose()
    logger.info("Analytica backend stopped.")


app = FastAPI(title="Analytica", version="1.0.0", lifespan=lifespan)


# ── Health ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "analytica"}


# ── Employee APIs ────────────────────────────────────────────

class UpdateEmployeeRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


@app.get("/api/employees")
async def list_employees():
    """List all available employees."""
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    return [
        {
            "employee_id": p.employee_id,
            "name": p.name,
            "description": p.description,
            "domains": p.domains,
            "version": p.version,
        }
        for p in manager.list_employees()
    ]


@app.get("/api/employees/{employee_id}")
async def get_employee(employee_id: str):
    """Get employee details."""
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    profile = manager.get_employee(employee_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Employee not found: {employee_id}")
    return {
        "employee_id": profile.employee_id,
        "name": profile.name,
        "description": profile.description,
        "version": profile.version,
        "domains": profile.domains,
        "skills": profile.skills,
        "perception": profile.perception.model_dump(),
        "planning": profile.planning.model_dump(),
    }


@app.put("/api/employees/{employee_id}")
async def update_employee(employee_id: str, req: UpdateEmployeeRequest):
    """Update employee (only name and description)."""
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    updated = manager.update_employee(
        employee_id,
        **req.model_dump(exclude_none=True),
    )
    if updated is None:
        raise HTTPException(status_code=404, detail=f"Employee not found: {employee_id}")
    return {
        "employee_id": updated.employee_id,
        "name": updated.name,
        "description": updated.description,
        "version": updated.version,
        "domains": updated.domains,
        "skills": updated.skills,
        "perception": updated.perception.model_dump(),
        "planning": updated.planning.model_dump(),
    }


# ── Session APIs ─────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    user_id: str
    employee_id: Optional[str] = None


class CreateSessionResponse(BaseModel):
    session_id: str
    employee_id: Optional[str] = None


@app.post("/api/sessions", status_code=201, response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest, db=Depends(get_db_session)):
    """Create a new analysis session."""
    # 校验 employee_id 是否有效
    if req.employee_id:
        from backend.employees.manager import EmployeeManager
        manager = EmployeeManager.get_instance()
        if manager.get_employee(req.employee_id) is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown employee: {req.employee_id}",
            )

    session_id = str(uuid4())
    store = MemoryStore(db)
    await store.create_session(session_id, req.user_id, employee_id=req.employee_id)
    return CreateSessionResponse(session_id=session_id, employee_id=req.employee_id)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, db=Depends(get_db_session)):
    """Get session state."""
    store = MemoryStore(db)
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


# ── Sessions list & replay (Phase 2) ──────────────────────────

@app.get("/api/sessions")
async def list_sessions(
    user_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
    db=Depends(get_db_session),
):
    """List sessions for HistoryPane, newest first.

    `user_id` filter is optional — omit to list every session (dev
    convenience; callers wanting personal history should pass it).
    """
    from backend.memory import session_log
    if limit < 1 or limit > 200:
        limit = 50
    if offset < 0:
        offset = 0
    items = await session_log.list_sessions(
        db, user_id=user_id, limit=limit, offset=offset,
    )
    return {"items": items, "count": len(items)}


@app.get("/api/sessions/{session_id}/messages")
async def replay_messages(
    session_id: str,
    since_id: int = 0,
    limit: int = 200,
    db=Depends(get_db_session),
):
    """Replay chat messages for a session (for refresh/hydration)."""
    from backend.memory import session_log
    if limit < 1 or limit > 1000:
        limit = 200
    if since_id < 0:
        since_id = 0
    items = await session_log.list_chat_messages(
        db, session_id, since_id=since_id, limit=limit,
    )
    return {"items": items, "count": len(items), "since_id": since_id}


@app.get("/api/sessions/{session_id}/thinking")
async def replay_thinking(
    session_id: str,
    since_id: int = 0,
    kind: Optional[str] = None,
    limit: int = 500,
    db=Depends(get_db_session),
):
    """Replay thinking/tool/decision events for a session."""
    from backend.memory import session_log
    if limit < 1 or limit > 2000:
        limit = 500
    if since_id < 0:
        since_id = 0
    items = await session_log.list_thinking_events(
        db, session_id, since_id=since_id, kind=kind, limit=limit,
    )
    return {"items": items, "count": len(items), "since_id": since_id}


# ── Planning APIs ─────────────────────────────────────────────

class PlanConfirmRequest(BaseModel):
    confirmed: bool = True
    modifications: list[dict[str, Any]] = Field(default_factory=list)


class PlanRegenerateRequest(BaseModel):
    feedback: str


@app.get("/api/sessions/{session_id}/plan")
async def get_plan(session_id: str, db=Depends(get_db_session)):
    """Get the current analysis plan for a session."""
    store = MemoryStore(db)
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = session.get("state_json", {})
    plan = state.get("analysis_plan")
    if plan is None:
        raise HTTPException(status_code=404, detail="No plan generated yet")

    from backend.agent.planning import format_plan_as_markdown
    from backend.models.schemas import AnalysisPlan

    plan_obj = AnalysisPlan(**plan)
    md = format_plan_as_markdown(plan_obj)

    return {
        **plan,
        "markdown_display": md,
        "plan_confirmed": state.get("plan_confirmed", False),
    }


@app.post("/api/sessions/{session_id}/plan/confirm")
async def confirm_plan(
    session_id: str,
    req: PlanConfirmRequest,
    db=Depends(get_db_session),
):
    """Confirm or modify the analysis plan. Idempotent."""
    store = MemoryStore(db)
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = session.get("state_json", {})
    plan = state.get("analysis_plan")
    if plan is None:
        raise HTTPException(status_code=404, detail="No plan generated yet")

    from backend.agent.planning import update_plan, format_plan_as_markdown
    from backend.models.schemas import AnalysisPlan

    plan_obj = AnalysisPlan(**plan)

    if req.modifications:
        plan_obj = update_plan(plan_obj, req.modifications)

    if req.confirmed:
        state["plan_confirmed"] = True

    state["analysis_plan"] = plan_obj.model_dump()
    state["plan_version"] = plan_obj.version

    await store.save_session_state(session_id, state)

    md = format_plan_as_markdown(plan_obj)
    return {
        **plan_obj.model_dump(),
        "markdown_display": md,
        "plan_confirmed": state.get("plan_confirmed", False),
    }


@app.post("/api/sessions/{session_id}/plan/regenerate")
async def regenerate_plan_endpoint(
    session_id: str,
    req: PlanRegenerateRequest,
    db=Depends(get_db_session),
):
    """Regenerate the analysis plan with user feedback."""
    store = MemoryStore(db)
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = session.get("state_json", {})
    plan = state.get("analysis_plan")
    intent = state.get("structured_intent")
    if plan is None or intent is None:
        raise HTTPException(status_code=404, detail="No plan or intent available")

    from backend.agent.planning import PlanningEngine, regenerate_plan, format_plan_as_markdown
    from backend.models.schemas import AnalysisPlan
    from backend.config import get_settings
    from langchain_openai import ChatOpenAI

    settings = get_settings()
    llm = ChatOpenAI(
        base_url=settings.QWEN_API_BASE,
        api_key=settings.QWEN_API_KEY,
        model=settings.QWEN_MODEL,
        temperature=0.1,
        request_timeout=120,
        extra_body={"enable_thinking": False},
    )

    engine = PlanningEngine(llm=llm, llm_timeout=120.0, max_retries=3)
    original_plan = AnalysisPlan(**plan)

    new_plan = await regenerate_plan(original_plan, req.feedback, engine, intent)

    state["analysis_plan"] = new_plan.model_dump()
    state["plan_confirmed"] = False
    state["plan_version"] = new_plan.version

    await store.save_session_state(session_id, state)

    md = format_plan_as_markdown(new_plan)
    return {
        **new_plan.model_dump(),
        "markdown_display": md,
        "plan_confirmed": False,
    }


# ── Reflection APIs ──────────────────────────────────────────

class ReflectionSaveRequest(BaseModel):
    save_preferences: bool = True
    save_template: bool = True
    save_skill_notes: bool = True


@app.post("/api/sessions/{session_id}/reflection/save")
async def save_reflection_endpoint(
    session_id: str,
    req: ReflectionSaveRequest,
    db=Depends(get_db_session),
):
    """Save reflection results to memory store.

    Human-in-the-Loop: user confirms what to persist after reviewing
    the reflection card.
    """
    store = MemoryStore(db)
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")

    state = session.get("state_json", {})
    reflection_summary = state.get("reflection_summary")
    if reflection_summary is None:
        raise HTTPException(status_code=404, detail="No reflection summary available")

    user_id = session.get("user_id", "anonymous")

    from backend.agent.reflection import save_reflection
    saved = await save_reflection(
        session_id=session_id,
        reflection_summary=reflection_summary,
        save_preferences=req.save_preferences,
        save_template=req.save_template,
        save_skill_notes=req.save_skill_notes,
        user_id=user_id,
        db_session=db,
    )

    return {
        "status": "ok",
        "saved": saved,
    }


# ── WebSocket Chat ───────────────────────────────────────────

@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(ws: WebSocket, session_id: str):
    """WebSocket endpoint for streaming chat."""
    await ws.accept()

    # 从 session 获取 employee_id
    from backend.database import get_session_factory
    from backend.memory import session_log
    from backend.config import get_settings
    settings = get_settings()
    thinking_stream_enabled = settings.FF_THINKING_STREAM

    factory = get_session_factory()
    employee_id = None
    async with factory() as db_session:
        store = MemoryStore(db_session)
        session_data = await store.get_session(session_id)
        if session_data:
            employee_id = session_data.get("employee_id")

    await ws.send_json({
        "type": "connected",
        "session_id": session_id,
        "employee_id": employee_id,
    })

    try:
        while True:
            data = await ws.receive_json()

            if data.get("type") == "ping":
                await ws.send_json({"type": "pong"})
                continue

            user_message = data.get("message", data.get("content", ""))
            user_id = data.get("user_id", "anonymous")

            if not user_message:
                await ws.send_json({"type": "error", "message": "Empty message"})
                continue

            # ── Phase 2: persist user message + seed session title ────
            # Plan-confirmation control words are sent through the same
            # sendMessage path from the frontend; they must never become
            # the session title because they overwrite the real first
            # message. Filter them out here.
            control_phrases = {"确认执行", "修改方案", "重新规划"}
            async with factory() as db_session:
                await session_log.append_chat_message(
                    db_session, session_id, role="user", content=user_message,
                    type="text", phase=None,
                )
                # Always check the live DB title, not a cached connect-time
                # snapshot (which didn't include the column before).
                row = await db_session.execute(
                    text("SELECT title FROM sessions WHERE session_id = :sid"),
                    {"sid": session_id},
                )
                current_title = row.scalar()
                stripped = user_message.strip().replace("\n", " ")
                if (
                    not current_title
                    and stripped
                    and stripped not in control_phrases
                ):
                    await session_log.update_session_title(
                        db_session, session_id, stripped[:80],
                    )

            try:
                prev_task_statuses: dict[str, str] = {}
                prev_msg_count = 0

                # Build a ws_callback that both forwards to the client and
                # persists tool_call_* events to thinking_events.
                async def _ws_callback(payload: dict) -> None:
                    evt = payload.get("event")
                    if evt in ("tool_call_start", "tool_call_end"):
                        if thinking_stream_enabled:
                            try:
                                async with factory() as tx:
                                    await session_log.append_thinking_event(
                                        tx, session_id,
                                        kind="tool",
                                        payload=payload,
                                        phase="execution",
                                    )
                            except Exception:
                                logger.exception("thinking_events insert failed")
                        # Always forward — the client can decide whether to
                        # render the rich inspector or not.
                        await ws.send_json(payload)
                    else:
                        # pass-through for task_update etc.
                        await ws.send_json(payload)

                async for event in run_stream(
                    session_id, user_id, user_message, employee_id=employee_id,
                    ws_callback=_ws_callback,
                ):
                    # 处理 run_stream 发出的初始元信息（消息基线）
                    if "__meta__" in event:
                        prev_msg_count = event["__meta__"].get("initial_msg_count", 0)
                        continue

                    # Thinking stream (node-boundary events from graph.run_stream)
                    if "__thinking__" in event:
                        thinking = event["__thinking__"]
                        if thinking_stream_enabled:
                            try:
                                async with factory() as tx:
                                    await session_log.append_thinking_event(
                                        tx, session_id,
                                        kind=thinking.get("kind", "thinking"),
                                        payload=thinking.get("payload"),
                                        phase=thinking.get("phase"),
                                    )
                            except Exception:
                                logger.exception("thinking_events insert failed")
                        # Always forward — the UI renders regardless of
                        # whether we're persisting for audit.
                        await ws.send_json({
                            "event": "thinking_stream",
                            "kind": thinking.get("kind", "thinking"),
                            "phase": thinking.get("phase"),
                            "payload": thinking.get("payload"),
                        })
                        continue

                    for node_name, node_state in event.items():
                        # Push slot updates
                        if "slots" in node_state:
                            await ws.send_json({
                                "event": "slot_update",
                                "slots": node_state.get("slots", {}),
                                "current_asking": node_state.get("current_target_slot"),
                            })

                        # Push messages — only send NEW messages (skip already-sent)
                        messages = node_state.get("messages", [])
                        cur_msg_count = len(messages)
                        if cur_msg_count > prev_msg_count:
                            for msg in messages[prev_msg_count:]:
                                if msg.get("role") == "assistant":
                                    phase = node_state.get("current_phase", "unknown")
                                    content = msg["content"]
                                    # Persist assistant message (Phase 2)
                                    persisted_id = 0
                                    try:
                                        async with factory() as tx:
                                            persisted_id = await session_log.append_chat_message(
                                                tx, session_id,
                                                role="assistant",
                                                content=content,
                                                type="text",
                                                phase=phase,
                                            )
                                    except Exception:
                                        logger.exception("chat_messages insert failed")
                                    await ws.send_json({
                                        "event": "message",
                                        "content": content,
                                        "phase": phase,
                                        "message_id": persisted_id or None,
                                    })
                            prev_msg_count = cur_msg_count

                        # Push structured intent if ready
                        if node_state.get("structured_intent"):
                            await ws.send_json({
                                "event": "intent_ready",
                                "intent": node_state["structured_intent"],
                            })

                        # Push plan update
                        if node_state.get("analysis_plan"):
                            await ws.send_json({
                                "event": "plan_update",
                                "plan": node_state["analysis_plan"],
                            })

                        # Push individual task status changes
                        cur_task_statuses = node_state.get("task_statuses", {})
                        for tid, ts in cur_task_statuses.items():
                            if prev_task_statuses.get(tid) != ts:
                                await ws.send_json({
                                    "event": "task_update",
                                    "task_id": tid,
                                    "status": ts,
                                })
                        if cur_task_statuses:
                            prev_task_statuses = dict(cur_task_statuses)

                        # Push reflection summary
                        if node_state.get("reflection_summary"):
                            await ws.send_json({
                                "event": "reflection",
                                "summary": node_state["reflection_summary"],
                            })

                await ws.send_json({"event": "turn_complete"})
            except Exception as e:
                logger.exception("Error in graph execution")
                await ws.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
