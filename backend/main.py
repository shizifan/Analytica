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

    # Phase 5 — ensure REPORTS_DIR is available for artifact persistence.
    try:
        from backend.memory.artifact_store import ensure_reports_dir
        reports_dir = ensure_reports_dir()
        logger.info("Report artifacts dir: %s", reports_dir)
    except Exception:
        logger.exception("REPORTS_DIR setup failed — downloads will 410")

    # 加载技能
    from backend.skills.loader import load_all_skills
    skill_count = load_all_skills()
    logger.info("Loaded %d skill modules", skill_count)

    # 加载员工配置 — Phase 4: picks DB or YAML based on FF.
    from pathlib import Path
    from backend.config import get_settings
    from backend.employees.manager import EmployeeManager
    settings = get_settings()
    manager = EmployeeManager.get_instance()
    if settings.FF_EMPLOYEE_SOURCE == "db":
        try:
            emp_count = await manager.load_from_db()
            logger.info("Loaded %d employee profiles from DB", emp_count)
        except Exception:
            logger.exception(
                "DB load failed for employees — falling back to YAML",
            )
            config_dir = Path(__file__).resolve().parent.parent / "employees"
            emp_count = manager.load_all_profiles(config_dir)
    else:
        config_dir = Path(__file__).resolve().parent.parent / "employees"
        emp_count = manager.load_all_profiles(config_dir)
        logger.info("Loaded %d employee profiles from YAML", emp_count)

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

class FAQItemPayload(BaseModel):
    id: str
    question: str
    tag: Optional[str] = None
    type: Optional[str] = None


class UpsertEmployeeRequest(BaseModel):
    """Full-field upsert. `employee_id` is taken from the URL, not the
    body, to avoid mismatch bugs."""

    name: str
    description: Optional[str] = None
    version: str = "1.0"
    initials: Optional[str] = None
    status: str = "active"
    domains: list[str] = Field(default_factory=list)
    endpoints: list[str] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    faqs: list[FAQItemPayload] = Field(default_factory=list)
    perception: Optional[dict[str, Any]] = None
    planning: Optional[dict[str, Any]] = None
    snapshot_note: Optional[str] = None


class PatchEmployeeRequest(BaseModel):
    """Partial update; all fields optional. Missing fields keep current values."""

    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    initials: Optional[str] = None
    status: Optional[str] = None
    domains: Optional[list[str]] = None
    endpoints: Optional[list[str]] = None
    skills: Optional[list[str]] = None
    faqs: Optional[list[FAQItemPayload]] = None
    perception: Optional[dict[str, Any]] = None
    planning: Optional[dict[str, Any]] = None
    snapshot_note: Optional[str] = None


def _profile_to_detail(profile: Any) -> dict[str, Any]:
    return {
        "employee_id": profile.employee_id,
        "name": profile.name,
        "description": profile.description,
        "version": profile.version,
        "initials": profile.initials,
        "status": profile.status,
        "domains": profile.domains,
        "endpoints": profile.endpoints,
        "skills": profile.skills,
        "faqs": [f.model_dump() for f in profile.faqs],
        "perception": profile.perception.model_dump(),
        "planning": profile.planning.model_dump(),
    }


def _profile_to_summary(profile: Any) -> dict[str, Any]:
    return {
        "employee_id": profile.employee_id,
        "name": profile.name,
        "description": profile.description,
        "domains": profile.domains,
        "version": profile.version,
        "initials": profile.initials,
        "status": profile.status,
        "faqs_count": len(profile.faqs),
        "skills_count": len(profile.skills),
        "endpoints_count": len(profile.endpoints),
    }


@app.get("/api/employees")
async def list_employees():
    """List all available employees (summary shape)."""
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    return [_profile_to_summary(p) for p in manager.list_employees()]


@app.get("/api/employees/{employee_id}")
async def get_employee(employee_id: str):
    """Get employee details (full profile)."""
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    profile = manager.get_employee(employee_id)
    if profile is None:
        raise HTTPException(status_code=404, detail=f"Employee not found: {employee_id}")
    return _profile_to_detail(profile)


@app.post("/api/employees/reload", status_code=200)
async def reload_employees():
    """Re-read employee profiles from the current source (DB or YAML).

    Used by maintenance scripts (e.g. FAQ bulk update) to invalidate the
    in-memory cache without restarting uvicorn. No auth guard here — gate
    behind RBAC in Phase 7.
    """
    from pathlib import Path
    from backend.config import get_settings
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    settings = get_settings()
    if settings.FF_EMPLOYEE_SOURCE == "db":
        count = await manager.load_from_db()
    else:
        config_dir = Path(__file__).resolve().parent.parent / "employees"
        count = manager.load_all_profiles(config_dir)
    return {"status": "ok", "count": count, "source": settings.FF_EMPLOYEE_SOURCE}


@app.post("/api/employees/{employee_id}", status_code=201)
async def create_or_replace_employee(
    employee_id: str, req: UpsertEmployeeRequest,
):
    """Create (or full-replace) an employee — DB mode only."""
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    if manager.source != "db":
        raise HTTPException(
            status_code=400,
            detail="Employee creation requires FF_EMPLOYEE_SOURCE=db",
        )
    try:
        profile = await manager.upsert_employee(
            employee_id,
            **req.model_dump(exclude={"snapshot_note"}),
            snapshot_note=req.snapshot_note,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    if profile is None:
        raise HTTPException(status_code=500, detail="Employee upsert failed")
    return _profile_to_detail(profile)


@app.put("/api/employees/{employee_id}")
async def update_employee(employee_id: str, req: PatchEmployeeRequest):
    """Patch an employee. YAML mode: name/description only (in-memory).
    DB mode: all fields; persisted + version snapshot."""
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()

    if manager.source == "yaml":
        # Back-compat: YAML mode only supports the two simple fields.
        updated = manager.update_employee(
            employee_id,
            name=req.name,
            description=req.description,
        )
        if updated is None:
            raise HTTPException(status_code=404, detail=f"Employee not found: {employee_id}")
        return _profile_to_detail(updated)

    # DB mode — merge over current profile for fields the caller omitted.
    current = manager.get_employee(employee_id)
    if current is None:
        raise HTTPException(status_code=404, detail=f"Employee not found: {employee_id}")

    patch = req.model_dump(exclude_unset=True, exclude_none=True)
    faqs_override = patch.get("faqs")
    if faqs_override is not None:
        # pydantic dumped FAQItemPayload → list[dict]; pass through
        faqs = faqs_override
    else:
        faqs = [f.model_dump() for f in current.faqs]

    merged = {
        "name": patch.get("name", current.name),
        "description": patch.get("description", current.description),
        "version": patch.get("version", current.version),
        "initials": patch.get("initials", current.initials),
        "status": patch.get("status", current.status),
        "domains": patch.get("domains", current.domains),
        "endpoints": patch.get("endpoints", current.endpoints),
        "skills": patch.get("skills", current.skills),
        "faqs": faqs,
        "perception": patch.get("perception", current.perception.model_dump()),
        "planning": patch.get("planning", current.planning.model_dump()),
        "snapshot_note": patch.get("snapshot_note"),
    }

    profile = await manager.upsert_employee(employee_id, **merged)
    if profile is None:
        raise HTTPException(status_code=500, detail="Employee update failed")
    return _profile_to_detail(profile)


@app.delete("/api/employees/{employee_id}")
async def archive_employee(employee_id: str):
    """Archive (soft delete) an employee — DB mode only."""
    from backend.employees.manager import EmployeeManager
    manager = EmployeeManager.get_instance()
    if manager.source != "db":
        raise HTTPException(
            status_code=400,
            detail="Archive requires FF_EMPLOYEE_SOURCE=db",
        )
    ok = await manager.archive_employee(employee_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Employee not found or already archived: {employee_id}",
        )
    return {"status": "ok", "employee_id": employee_id}


@app.get("/api/employees/{employee_id}/versions")
async def list_employee_versions(employee_id: str, db=Depends(get_db_session)):
    """Return the version history for an employee (DB mode only)."""
    from backend.employees.manager import EmployeeManager
    from backend.memory import employee_store
    if EmployeeManager.get_instance().source != "db":
        raise HTTPException(
            status_code=400,
            detail="Version history requires FF_EMPLOYEE_SOURCE=db",
        )
    items = await employee_store.list_versions(db, employee_id)
    return {"items": items, "count": len(items)}


@app.get("/api/employees/{employee_id}/versions/{version}")
async def get_employee_version(
    employee_id: str, version: str, db=Depends(get_db_session),
):
    """Return the snapshot of a specific employee version (DB mode only)."""
    from backend.employees.manager import EmployeeManager
    from backend.memory import employee_store
    if EmployeeManager.get_instance().source != "db":
        raise HTTPException(
            status_code=400,
            detail="Version history requires FF_EMPLOYEE_SOURCE=db",
        )
    snap = await employee_store.get_version_snapshot(db, employee_id, version)
    if snap is None:
        raise HTTPException(
            status_code=404,
            detail=f"Version not found: {employee_id}@{version}",
        )
    return {"employee_id": employee_id, "version": version, "snapshot": snap}


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


# ── Report Artifacts (Phase 5) ────────────────────────────────

@app.get("/api/sessions/{session_id}/reports")
async def list_session_reports(
    session_id: str, db=Depends(get_db_session),
):
    """Every artifact generated for a given session."""
    from backend.memory import artifact_store
    items = await artifact_store.list_artifacts(db, session_id)
    return {"items": items, "count": len(items)}


@app.get("/api/reports/{artifact_id}/download")
async def download_report(
    artifact_id: str, db=Depends(get_db_session),
):
    """Stream the artifact file as a download attachment."""
    from fastapi.responses import FileResponse
    from backend.memory import artifact_store

    artifact = await artifact_store.get_artifact(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    fs_path = artifact_store.resolve_artifact_path(artifact)
    if not fs_path.exists():
        raise HTTPException(
            status_code=410,
            detail="Artifact file missing on disk (may have been purged)",
        )

    fmt = artifact.get("format", "file")
    mime = {
        "html": "text/html; charset=utf-8",
        "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "md": "text/markdown; charset=utf-8",
        "markdown": "text/markdown; charset=utf-8",
    }.get(fmt, "application/octet-stream")

    filename = fs_path.name
    return FileResponse(
        path=str(fs_path),
        media_type=mime,
        filename=filename,
    )


@app.post("/api/reports/{artifact_id}/convert")
async def convert_report(
    artifact_id: str,
    format: str,
    db=Depends(get_db_session),
):
    """Phase 5.7 — on-demand DOCX / PPTX generation from an already-
    generated HTML report.

    Reads the conversion context pickled during the original execution,
    re-invokes the matching report skill, writes a new artifact row,
    and returns the new `artifact_id`. Seconds instead of minutes
    because no data-fetch / analysis re-runs.
    """
    from backend.memory import artifact_store
    from backend.skills.base import SkillInput, skill_executor
    from backend.skills.registry import SkillRegistry

    fmt = format.lower()
    if fmt not in ("docx", "pptx"):
        raise HTTPException(
            status_code=400,
            detail="format must be 'docx' or 'pptx'",
        )

    source = await artifact_store.get_artifact(db, artifact_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source artifact not found")

    ctx = artifact_store.read_conversion_context(artifact_id)
    if ctx is None:
        raise HTTPException(
            status_code=410,
            detail="Conversion context missing — original generation may have been purged",
        )

    # Ensure all skills are registered (lazy-loaded at app startup, but
    # an uvicorn --reload cycle can leave the registry bound to a fresh
    # module copy without the decorators re-running).
    import backend.skills.loader  # noqa: F401

    # Re-invoke the docx / pptx skill with the same params + saved context.
    skill_id = f"skill_report_{fmt}"
    skill = SkillRegistry.get_instance().get_skill(skill_id)
    if skill is None:
        raise HTTPException(
            status_code=500, detail=f"Skill not available: {skill_id}",
        )

    params = dict(ctx.get("params") or {})
    context = ctx.get("context") or {}
    inp = SkillInput(
        params=params,
        context_refs=list(params.get("_task_order") or context.keys()),
    )

    try:
        output = await skill_executor(skill, inp, context, timeout_seconds=120.0)
    except Exception as e:
        logger.exception("convert_report skill execution failed")
        raise HTTPException(
            status_code=500, detail=f"Skill raised: {type(e).__name__}: {e}",
        )
    if output.status not in ("success", "partial"):
        raise HTTPException(
            status_code=500,
            detail=f"Generation failed: {output.error_message or 'unknown'}",
        )

    # Persist the new artifact under the same session.
    session_id = source["session_id"]
    title = (output.metadata or {}).get("title") or source.get("title")
    new_row = await artifact_store.persist_artifact(
        db,
        session_id=session_id,
        task_id=source.get("task_id"),
        skill_id=skill_id,
        fmt=fmt,
        title=title,
        content=output.data,
        meta={
            **(output.metadata or {}),
            "source_artifact_id": artifact_id,
            "converted_from": "html",
        },
    )
    if new_row is None:
        raise HTTPException(status_code=500, detail="artifact persistence failed")

    return {"artifact_id": new_row["id"], "format": fmt, "status": "ready"}


@app.get("/api/reports/{artifact_id}/preview")
async def preview_report(
    artifact_id: str, db=Depends(get_db_session),
):
    """Inline preview for HTML / Markdown artifacts. Binary formats
    redirect the caller to the download endpoint."""
    from fastapi.responses import FileResponse, RedirectResponse
    from backend.memory import artifact_store

    artifact = await artifact_store.get_artifact(db, artifact_id)
    if artifact is None:
        raise HTTPException(status_code=404, detail="Artifact not found")

    fmt = artifact.get("format", "file")
    if fmt not in ("html", "markdown", "md"):
        return RedirectResponse(url=f"/api/reports/{artifact_id}/download")

    fs_path = artifact_store.resolve_artifact_path(artifact)
    if not fs_path.exists():
        raise HTTPException(status_code=410, detail="Artifact file missing")

    mime = "text/html; charset=utf-8" if fmt == "html" else "text/markdown; charset=utf-8"
    return FileResponse(path=str(fs_path), media_type=mime)


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str, db=Depends(get_db_session)):
    """Soft-delete a session — hides it from HistoryPane while keeping
    chat_messages / thinking_events intact for audit."""
    from backend.memory import session_log
    deleted = await session_log.soft_delete_session(db, session_id)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail="Session not found or already deleted",
        )
    return {"status": "ok", "session_id": session_id}


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
        request_timeout=200,  # must exceed the largest per-complexity timeout (180s)
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

                # Wrap ws.send_json so client-disconnect errors don't kill
                # the in-flight run_stream generator. If the user switches
                # sessions mid-execution we want the task to finish and the
                # final state/messages to be persisted; the returning user
                # will hydrate from DB. Send failures are logged at debug
                # level only — the client is gone, nothing to do.
                async def _safe_send(payload: dict) -> None:
                    try:
                        await ws.send_json(payload)
                    except Exception:
                        logger.debug("ws.send_json failed (client disconnected); continuing")

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
                    await _safe_send(payload)

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
                        await _safe_send({
                            "event": "thinking_stream",
                            "kind": thinking.get("kind", "thinking"),
                            "phase": thinking.get("phase"),
                            "payload": thinking.get("payload"),
                        })
                        continue

                    for node_name, node_state in event.items():
                        # Push slot updates
                        if "slots" in node_state:
                            await _safe_send({
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
                                    content = msg.get("content", "")
                                    msg_type = msg.get("type") or "text"
                                    msg_payload = msg.get("payload")
                                    # Persist assistant message (Phase 2 + 3.7)
                                    persisted_id = 0
                                    try:
                                        async with factory() as tx:
                                            persisted_id = await session_log.append_chat_message(
                                                tx, session_id,
                                                role="assistant",
                                                content=content,
                                                type=msg_type,
                                                phase=phase,
                                                payload=msg_payload,
                                            )
                                    except Exception:
                                        logger.exception("chat_messages insert failed")
                                    out: dict[str, Any] = {
                                        "event": "message",
                                        "content": content,
                                        "phase": phase,
                                        "message_id": persisted_id or None,
                                    }
                                    if msg_type and msg_type != "text":
                                        out["type"] = msg_type
                                    if msg_payload is not None:
                                        out["payload"] = msg_payload
                                    await _safe_send(out)
                            prev_msg_count = cur_msg_count

                        # Push structured intent if ready
                        if node_state.get("structured_intent"):
                            await _safe_send({
                                "event": "intent_ready",
                                "intent": node_state["structured_intent"],
                            })

                        # Push plan update
                        if node_state.get("analysis_plan"):
                            await _safe_send({
                                "event": "plan_update",
                                "plan": node_state["analysis_plan"],
                            })

                        # Push individual task status changes
                        cur_task_statuses = node_state.get("task_statuses", {})
                        for tid, ts in cur_task_statuses.items():
                            if prev_task_statuses.get(tid) != ts:
                                await _safe_send({
                                    "event": "task_update",
                                    "task_id": tid,
                                    "status": ts,
                                })
                        if cur_task_statuses:
                            prev_task_statuses = dict(cur_task_statuses)

                        # Push reflection summary
                        if node_state.get("reflection_summary"):
                            await _safe_send({
                                "event": "reflection",
                                "summary": node_state["reflection_summary"],
                            })

                await _safe_send({"event": "turn_complete"})
            except Exception as e:
                logger.exception("Error in graph execution")
                await _safe_send({"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected: {session_id}")
    except Exception as e:
        logger.exception(f"WebSocket error: {e}")
