from __future__ import annotations
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
from pydantic import BaseModel, Field

from backend.database import get_db_session, get_engine, Base
from backend.memory.store import MemoryStore
from backend.agent.graph import run_stream

logger = logging.getLogger("analytica")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: startup and shutdown."""
    logger.info("Analytica backend starting...")
    yield
    engine = get_engine()
    await engine.dispose()
    logger.info("Analytica backend stopped.")


app = FastAPI(title="Analytica", version="1.0.0", lifespan=lifespan)


# ── Health ───────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "service": "analytica"}


# ── Session APIs ─────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    user_id: str


class CreateSessionResponse(BaseModel):
    session_id: str


@app.post("/api/sessions", status_code=201, response_model=CreateSessionResponse)
async def create_session(req: CreateSessionRequest, db=Depends(get_db_session)):
    """Create a new analysis session."""
    session_id = str(uuid4())
    store = MemoryStore(db)
    await store.create_session(session_id, req.user_id)
    return CreateSessionResponse(session_id=session_id)


@app.get("/api/sessions/{session_id}")
async def get_session(session_id: str, db=Depends(get_db_session)):
    """Get session state."""
    store = MemoryStore(db)
    session = await store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


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


# ── WebSocket Chat ───────────────────────────────────────────

@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(ws: WebSocket, session_id: str):
    """WebSocket endpoint for streaming chat."""
    await ws.accept()
    await ws.send_json({"type": "connected", "session_id": session_id})

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

            try:
                async for event in run_stream(session_id, user_id, user_message):
                    for node_name, node_state in event.items():
                        # Push slot updates
                        if "slots" in node_state:
                            await ws.send_json({
                                "event": "slot_update",
                                "slots": node_state.get("slots", {}),
                                "current_asking": node_state.get("current_target_slot"),
                            })

                        # Push messages
                        messages = node_state.get("messages", [])
                        if messages:
                            last_msg = messages[-1]
                            if last_msg.get("role") == "assistant":
                                await ws.send_json({
                                    "event": "message",
                                    "content": last_msg["content"],
                                    "phase": node_state.get("current_phase", "unknown"),
                                })

                        # Push structured intent if ready
                        if node_state.get("structured_intent"):
                            await ws.send_json({
                                "event": "intent_ready",
                                "intent": node_state["structured_intent"],
                            })

                await ws.send_json({"event": "turn_complete"})
            except Exception as e:
                logger.exception("Error in graph execution")
                await ws.send_json({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
