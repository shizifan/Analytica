from __future__ import annotations
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Any, Optional
from uuid import uuid4

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends, UploadFile, File
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
    from backend.tools.loader import load_all_tools
    tool_count = load_all_tools()
    logger.info("Loaded %d tool modules", tool_count)

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
            # 兜底：DB 可用但表里是空的（seed 未跑 / 还没导入）时也回退
            # 到 YAML，避免前端拿到空列表只剩"通用模式"。
            if emp_count == 0:
                logger.warning(
                    "DB returned 0 employees — falling back to YAML "
                    "(run `python -m migrations.scripts.seed_employees_from_yaml` to seed DB)"
                )
                config_dir = Path(__file__).resolve().parent.parent / "employees"
                emp_count = manager.load_all_profiles(config_dir)
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

    # API registry — load endpoints + domains from DB (the only source).
    # Empty DB raises immediately to surface a missing seed step before
    # the backend silently degrades.
    from backend.agent import api_registry
    await api_registry.lifespan_apply_source()

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
    tools: list[str] = Field(default_factory=list)
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
    tools: Optional[list[str]] = None
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
        "tools": profile.tools,
        "faqs": [f.model_dump() for f in profile.faqs],
        "perception": profile.perception.model_dump(),
        "planning": profile.planning.model_dump(),
    }


def _profile_to_summary(profile: Any) -> dict[str, Any]:
    from backend.agent.api_registry import BY_DOMAIN
    if profile.endpoints:
        ep_count = len(profile.endpoints)
    else:
        ep_count = sum(len(BY_DOMAIN.get(d, [])) for d in (profile.domains or []))
    return {
        "employee_id": profile.employee_id,
        "name": profile.name,
        "description": profile.description,
        "domains": profile.domains,
        "version": profile.version,
        "initials": profile.initials,
        "status": profile.status,
        "faqs_count": len(profile.faqs),
        "tools_count": len(profile.tools),
        "endpoints_count": ep_count,
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
        "tools": patch.get("tools", current.tools),
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


# ── Prompt dry-run (P3.1) ─────────────────────────────────────
#
# Lets the admin UI exercise a draft perception / planning config before
# saving. Both endpoints accept a partial override and run the engine
# against the live registry; nothing is persisted. The save button in
# the admin drawer stays disabled until at least one dry-run succeeds —
# that's the protection bar we promised in the v2 plan.

class _DryRunPerceptionRequest(BaseModel):
    query: str
    # Optional partial override of `perception:` from the YAML. Missing
    # fields fall through to the saved profile.
    perception: Optional[dict[str, Any]] = None


class _DryRunPlanningRequest(BaseModel):
    # Either provide a full structured intent (chained from a previous
    # dryrun-perception) or a query (we'll re-run perception inline).
    query: Optional[str] = None
    intent: Optional[dict[str, Any]] = None
    planning: Optional[dict[str, Any]] = None
    perception: Optional[dict[str, Any]] = None  # only used when query is set


def _profile_with_overrides(
    employee_id: str,
    perception_override: Optional[dict[str, Any]] = None,
    planning_override: Optional[dict[str, Any]] = None,
):
    """Return a copy of the saved profile with the supplied overrides
    applied. Raises 404 if the employee doesn't exist.

    The override dicts mirror the YAML/DB payload — partial is fine;
    omitted fields keep the saved value.
    """
    from backend.employees.manager import EmployeeManager
    from backend.employees.profile import PerceptionConfig, PlanningConfig

    base = EmployeeManager.get_instance().get_employee(employee_id)
    if base is None:
        raise HTTPException(status_code=404, detail=f"Employee not found: {employee_id}")

    perception = base.perception
    if perception_override is not None:
        merged = {**base.perception.model_dump(), **perception_override}
        perception = PerceptionConfig(**merged)

    planning = base.planning
    if planning_override is not None:
        merged = {**base.planning.model_dump(), **planning_override}
        planning = PlanningConfig(**merged)

    return base.model_copy(update={"perception": perception, "planning": planning})


@app.post("/api/admin/employees/{employee_id}/dryrun-perception")
async def dryrun_perception(employee_id: str, req: _DryRunPerceptionRequest):
    """Run perception with an unsaved config override; return the slot result."""
    from backend.agent.perception import run_perception

    if not req.query.strip():
        raise HTTPException(status_code=400, detail="query is required")

    profile = _profile_with_overrides(employee_id, perception_override=req.perception)

    state = {
        "messages": [{"role": "user", "content": req.query}],
        "raw_query": req.query,
        "session_id": f"dryrun-{employee_id}",
        "user_id": f"dryrun_{employee_id}",
        "employee_id": employee_id,
    }
    try:
        out = await run_perception(state, profile=profile)
    except Exception as e:
        # Surface as 422 — the admin sees it and the UI keeps save disabled.
        raise HTTPException(status_code=422, detail=f"perception 失败: {e}")

    return {
        "structured_intent": out.get("structured_intent"),
        "empty_required_slots": out.get("empty_required_slots") or [],
        "current_target_slot": out.get("current_target_slot"),
        "clarification_round": out.get("clarification_round", 0),
    }


@app.post("/api/admin/employees/{employee_id}/dryrun-planning")
async def dryrun_planning(employee_id: str, req: _DryRunPlanningRequest):
    """Run planning with an unsaved config override; return the plan tasks."""
    from backend.agent.planning import PlanningEngine
    from backend.agent.graph import build_llm
    from backend.agent.perception import run_perception

    profile = _profile_with_overrides(
        employee_id,
        perception_override=req.perception,
        planning_override=req.planning,
    )

    intent = req.intent
    if intent is None:
        if not req.query or not req.query.strip():
            raise HTTPException(status_code=400, detail="query or intent is required")
        # Inline perception so a planning dry-run can stand alone.
        state = {
            "messages": [{"role": "user", "content": req.query}],
            "raw_query": req.query,
            "session_id": f"dryrun-{employee_id}",
            "user_id": f"dryrun_{employee_id}",
            "employee_id": employee_id,
        }
        try:
            out = await run_perception(state, profile=profile)
        except Exception as e:
            raise HTTPException(status_code=422, detail=f"perception 失败: {e}")
        intent = out.get("structured_intent")
        if not intent:
            raise HTTPException(status_code=422, detail="perception 未产出 intent — 请补充必填槽位")

    llm = build_llm("qwen3-235b", request_timeout=200)
    engine = PlanningEngine(llm=llm, llm_timeout=120.0, max_retries=3)
    try:
        plan = await engine.generate_plan(
            intent,
            allowed_endpoints=profile.get_endpoint_names(),
            allowed_tools=profile.get_tool_ids(),
            prompt_suffix=profile.planning.prompt_suffix or "",
            rule_hints=profile.planning.rule_hints or {},
            employee_id=employee_id,
        )
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"planning 失败: {e}")

    return {
        "plan": plan.model_dump(),
        "task_count": len(plan.tasks),
        "intent_used": intent,
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
    re-invokes the matching report tool, writes a new artifact row,
    and returns the new `artifact_id`. Seconds instead of minutes
    because no data-fetch / analysis re-runs.
    """
    from backend.memory import artifact_store
    from backend.tools.base import ToolInput, tool_executor
    from backend.tools.registry import ToolRegistry

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

    # Ensure all tools are registered (lazy-loaded at app startup, but
    # an uvicorn --reload cycle can leave the registry bound to a fresh
    # module copy without the decorators re-running).
    import backend.tools.loader  # noqa: F401

    # Re-invoke the docx / pptx tool with the same params + saved context.
    tool_id = f"tool_report_{fmt}"
    tool = ToolRegistry.get_instance().get_tool(tool_id)
    if tool is None:
        raise HTTPException(
            status_code=500, detail=f"Tool not available: {tool_id}",
        )

    params = dict(ctx.get("params") or {})
    context = ctx.get("context") or {}
    inp = ToolInput(
        params=params,
        context_refs=list(params.get("_task_order") or context.keys()),
    )

    try:
        output = await tool_executor(tool, inp, context, timeout_seconds=120.0)
    except Exception as e:
        logger.exception("convert_report tool execution failed")
        raise HTTPException(
            status_code=500, detail=f"Tool raised: {type(e).__name__}: {e}",
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
        tool_id=tool_id,
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


@app.post("/api/sessions/{session_id}/cancel")
async def cancel_session_execution(session_id: str):
    """Signal the running execution for this session to stop.

    Idempotent — safe to call even when nothing is running.
    The execution loop checks this event between task layers and will stop
    cleanly, marking pending tasks as skipped, before returning control.
    """
    from backend.agent.session_registry import get_registry
    get_registry().request_cancel(session_id)
    return {"status": "ok", "session_id": session_id}


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


@app.get("/api/sessions/{session_id}/trace")
async def get_trace(session_id: str, db=Depends(get_db_session)):
    """Return API and LLM call spans grouped by task_id for the trace viewer."""
    from backend.memory import session_log
    rows = await session_log.list_thinking_events(
        db, session_id, kind="span", limit=2000,
    )
    tasks: dict[str, list] = {}
    for row in rows:
        span = row.get("payload") or {}
        tid = span.get("task_id", "unknown")
        tasks.setdefault(tid, []).append(span)

    return {
        "session_id": session_id,
        "tasks": [
            {"task_id": tid, "spans": spans}
            for tid, spans in tasks.items()
        ],
    }


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
        temperature=settings.LLM_TEMPERATURE_DEFAULT,
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
    save_tool_notes: bool = True


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
        save_tool_notes=req.save_tool_notes,
        user_id=user_id,
        db_session=db,
    )

    return {
        "status": "ok",
        "saved": saved,
    }


# ── Admin Console · Phase 6 ──────────────────────────────────

class ApiEndpointUpsert(BaseModel):
    name: str
    method: str = "GET"
    path: str
    domain: str
    intent: Optional[str] = None
    time_type: Optional[str] = None
    granularity: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    required_params: list[str] = Field(default_factory=list)
    optional_params: list[str] = Field(default_factory=list)
    returns: Optional[str] = None
    param_note: Optional[str] = None
    disambiguate: Optional[str] = None
    source: str = "mock"
    enabled: bool = True
    # P2.4: semantic-enrichment fields. ``field_schema`` rows are 3- or
    # 4-element lists per P2.3a — accept ``list[Any]`` so we don't reject
    # 4-element rows carrying a label_zh.
    field_schema: list[list[Any]] = Field(default_factory=list)
    use_cases: list[str] = Field(default_factory=list)
    chain_with: list[str] = Field(default_factory=list)
    analysis_note: Optional[str] = None


@app.get("/api/admin/apis")
async def admin_list_apis(
    domain: Optional[str] = None,
    q: Optional[str] = None,
    limit: int = 500,
    db=Depends(get_db_session),
):
    from backend.memory import admin_store
    items = await admin_store.list_api_endpoints(
        db, domain=domain, query=q, limit=limit,
    )
    return {"items": items, "count": len(items)}


@app.get("/api/admin/apis/{name}")
async def admin_get_api(name: str, db=Depends(get_db_session)):
    from backend.memory import admin_store
    row = await admin_store.get_api_endpoint(db, name)
    if row is None:
        raise HTTPException(status_code=404, detail="API not found")
    return row


@app.put("/api/admin/apis/{name}")
async def admin_upsert_api(
    name: str, req: ApiEndpointUpsert, db=Depends(get_db_session),
):
    from backend.memory import admin_store
    payload = req.model_dump()
    payload["name"] = name  # URL wins
    await admin_store.upsert_api_endpoint(db, **payload)
    await admin_store.append_audit(
        db, action="update", resource_type="api_endpoint", resource_id=name,
        actor_type="user", diff=payload,
    )
    return await admin_store.get_api_endpoint(db, name)


@app.delete("/api/admin/apis/{name}")
async def admin_delete_api(name: str, db=Depends(get_db_session)):
    from backend.memory import admin_store
    ok = await admin_store.delete_api_endpoint(db, name)
    if not ok:
        raise HTTPException(status_code=404, detail="API not found")
    await admin_store.append_audit(
        db, action="delete", resource_type="api_endpoint", resource_id=name,
    )
    return {"status": "ok", "name": name}


@app.get("/api/admin/apis/{name}/stats")
async def admin_api_stats(
    name: str, days: int = 7, db=Depends(get_db_session),
):
    from backend.memory import admin_store
    return await admin_store.get_api_stats(db, name, days=days)


class ApiTestRequest(BaseModel):
    params: dict[str, Any] = Field(default_factory=dict)
    mode: str = "mock"  # "mock" | "prod"


@app.post("/api/admin/apis/{name}/test")
async def admin_test_api(name: str, req: ApiTestRequest):
    """Proxy a test call to the underlying data API and return the raw response."""
    import time as _time
    import httpx
    from backend.agent.api_registry import get_endpoint_path, resolve_endpoint_id
    from backend.tools.data.api_fetch import _build_auth_headers
    from backend.config import get_settings

    endpoint_id = resolve_endpoint_id(name)
    if not endpoint_id:
        raise HTTPException(status_code=404, detail=f"API endpoint '{name}' not found")

    path = get_endpoint_path(endpoint_id)
    if not path:
        raise HTTPException(status_code=404, detail=f"No path for endpoint '{endpoint_id}'")

    settings = get_settings()
    use_prod = req.mode == "prod"
    if use_prod:
        if not settings.PROD_API_BASE:
            raise HTTPException(status_code=400, detail="生产接口地址未配置（PROD_API_BASE 为空）")
        api_base = settings.PROD_API_BASE
        verify_ssl = False  # prod uses self-signed cert
    else:
        api_base = settings.MOCK_SERVER_URL
        verify_ssl = True

    url = f"{api_base}{path}"
    headers = _build_auth_headers(path)

    start = _time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=15.0, verify=verify_ssl, trust_env=False) as client:
            resp = await client.get(url, params=req.params, headers=headers)
        duration_ms = round((_time.monotonic() - start) * 1000)
        try:
            body = resp.json()
        except Exception:
            body = resp.text
        return {
            "status_code": resp.status_code,
            "duration_ms": duration_ms,
            "url": str(resp.url),
            "mode": req.mode,
            "data": body,
        }
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Upstream API timed out")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc))


class ToolUpsert(BaseModel):
    name: str
    kind: str
    description: Optional[str] = None
    input_spec: Optional[str] = None
    output_spec: Optional[str] = None
    domains: list[str] = Field(default_factory=list)
    enabled: bool = True


@app.get("/api/admin/tools")
async def admin_list_tools(db=Depends(get_db_session)):
    from backend.memory import admin_store
    items = await admin_store.list_tools(db)
    return {"items": items, "count": len(items)}


@app.get("/api/admin/tools/{tool_id}")
async def admin_get_tool(tool_id: str, db=Depends(get_db_session)):
    from backend.memory import admin_store
    row = await admin_store.get_tool(db, tool_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Tool not found")
    return row


@app.get("/api/admin/tools/{tool_id}/source")
async def admin_tool_source(tool_id: str):
    """Return the Python source file of a registered tool."""
    import inspect
    from pathlib import Path
    from backend.tools.registry import ToolRegistry
    tool = ToolRegistry.get_instance().get_tool(tool_id)
    if tool is None:
        raise HTTPException(status_code=404, detail="Tool not found or not loaded")
    try:
        src_path = Path(inspect.getfile(type(tool)))
        source = src_path.read_text(encoding="utf-8")
        return {
            "tool_id": tool_id,
            "file": str(src_path.relative_to(Path(__file__).parent.parent)),
            "source": source,
        }
    except (TypeError, OSError) as exc:
        raise HTTPException(status_code=500, detail=f"Cannot read source: {exc}")


@app.put("/api/admin/tools/{tool_id}")
async def admin_upsert_tool(
    tool_id: str, req: ToolUpsert, db=Depends(get_db_session),
):
    from backend.memory import admin_store
    await admin_store.upsert_tool(db, tool_id=tool_id, **req.model_dump())
    await admin_store.append_audit(
        db, action="update", resource_type="tool", resource_id=tool_id,
        diff=req.model_dump(),
    )
    return await admin_store.get_tool(db, tool_id)


@app.post("/api/admin/tools/{tool_id}/toggle")
async def admin_toggle_tool(
    tool_id: str, enabled: bool = True, db=Depends(get_db_session),
):
    from backend.memory import admin_store
    ok = await admin_store.toggle_tool(db, tool_id, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Tool not found")
    await admin_store.append_audit(
        db, action="toggle", resource_type="tool", resource_id=tool_id,
        diff={"enabled": enabled},
    )
    return {"status": "ok", "tool_id": tool_id, "enabled": enabled}


# ── Agent Skills (SKILL.md workflow instructions) ─────────────


@app.get("/api/admin/agent-skills")
async def admin_list_agent_skills(db=Depends(get_db_session)):
    from backend.memory import admin_store
    items = await admin_store.list_agent_skills(db)
    return {"items": items, "count": len(items)}


@app.get("/api/admin/agent-skills/{skill_id}")
async def admin_get_agent_skill(skill_id: str, db=Depends(get_db_session)):
    from backend.memory import admin_store
    row = await admin_store.get_agent_skill(db, skill_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Agent skill not found")
    return row


@app.post("/api/admin/agent-skills")
async def admin_upload_agent_skill(
    file: UploadFile = File(...),
    db=Depends(get_db_session),
):
    """Upload a SKILL.md file. Parses YAML frontmatter for metadata."""
    import yaml as _yaml
    import re as _re
    content = (await file.read()).decode("utf-8")
    meta: dict = {}
    if content.startswith("---"):
        m = _re.match(r"^---\s*\n(.*?)\n---\s*\n", content, _re.DOTALL)
        if m:
            try:
                meta = _yaml.safe_load(m.group(1)) or {}
            except Exception:
                meta = {}

    name = meta.get("name") or (file.filename or "").replace(".md", "")
    if not name:
        raise HTTPException(status_code=400, detail="Cannot determine skill name from file or frontmatter")

    skill_id = meta.get("id") or name.lower().replace(" ", "_")
    description = meta.get("description")
    author = meta.get("author")
    version = str(meta.get("version", "1.0"))
    tags = meta.get("tags") or []
    if isinstance(tags, str):
        tags = [t.strip() for t in tags.split(",") if t.strip()]

    from backend.memory import admin_store
    await admin_store.upsert_agent_skill(
        db,
        tool_id=tool_id,
        name=name,
        description=description,
        content=content,
        author=author,
        version=version,
        tags=tags,
        enabled=True,
    )
    await admin_store.append_audit(
        db, action="upload", resource_type="agent_skill", resource_id=skill_id,
    )
    return await admin_store.get_agent_skill(db, skill_id)


@app.delete("/api/admin/agent-skills/{skill_id}")
async def admin_delete_agent_skill(skill_id: str, db=Depends(get_db_session)):
    from backend.memory import admin_store
    ok = await admin_store.delete_agent_skill(db, skill_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent skill not found")
    await admin_store.append_audit(
        db, action="delete", resource_type="agent_skill", resource_id=skill_id,
    )
    return {"status": "ok", "skill_id": skill_id}


@app.post("/api/admin/agent-skills/{skill_id}/toggle")
async def admin_toggle_agent_skill(
    skill_id: str, enabled: bool = True, db=Depends(get_db_session),
):
    from backend.memory import admin_store
    ok = await admin_store.toggle_agent_skill(db, skill_id, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Agent skill not found")
    await admin_store.append_audit(
        db, action="toggle", resource_type="agent_skill", resource_id=skill_id,
        diff={"enabled": enabled},
    )
    return {"status": "ok", "skill_id": skill_id, "enabled": enabled}


@app.get("/api/admin/domains")
async def admin_list_domains(db=Depends(get_db_session)):
    from backend.memory import admin_store
    items = await admin_store.list_domains(db)
    return {"items": items, "count": len(items)}


class DomainUpsert(BaseModel):
    name: str
    description: Optional[str] = None
    color: Optional[str] = None
    top_tags: list[str] = Field(default_factory=list)


@app.put("/api/admin/domains/{code}")
async def admin_upsert_domain(
    code: str, req: DomainUpsert, db=Depends(get_db_session),
):
    from backend.memory import admin_store
    await admin_store.upsert_domain(db, code=code, **req.model_dump())
    await admin_store.append_audit(
        db, action="update", resource_type="domain", resource_id=code,
        diff=req.model_dump(),
    )
    domains = await admin_store.list_domains(db)
    return next((d for d in domains if d["code"] == code), None)


@app.get("/api/admin/memories")
async def admin_list_memories(
    user_id: Optional[str] = None,
    limit: int = 100,
    db=Depends(get_db_session),
):
    from backend.memory import admin_store
    return await admin_store.list_memory_entries(db, user_id=user_id, limit=limit)


@app.delete("/api/admin/memories/{kind}/{entry_id}")
async def admin_delete_memory(
    kind: str, entry_id: str, db=Depends(get_db_session),
):
    from backend.memory import admin_store
    ok = await admin_store.delete_memory_entry(db, kind, entry_id)
    if not ok:
        raise HTTPException(
            status_code=404,
            detail=f"Memory entry not found: {kind}/{entry_id}",
        )
    await admin_store.append_audit(
        db, action="delete", resource_type=f"memory_{kind}",
        resource_id=entry_id,
    )
    return {"status": "ok", "kind": kind, "id": entry_id}


@app.get("/api/admin/audit")
async def admin_list_audit(
    resource_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    db=Depends(get_db_session),
):
    from backend.memory import admin_store
    items = await admin_store.list_audit(
        db,
        resource_type=resource_type,
        actor_id=actor_id,
        limit=limit,
        offset=offset,
    )
    return {"items": items, "count": len(items)}


# ── WebSocket Chat ───────────────────────────────────────────

@app.websocket("/ws/chat/{session_id}")
async def websocket_chat(ws: WebSocket, session_id: str):
    """WebSocket endpoint for streaming chat.

    T1: per-session asyncio.Lock prevents concurrent run_stream() calls.
    T2: SessionRegistry fan-out — every subscribed WS sees the same events
        via its own inbox queue drained by a background task.
    T3: every 'message' event carries message_id (DB id) for frontend dedup;
        'connected' event carries last_message_id for delta hydration.
    """
    await ws.accept()

    from backend.database import get_session_factory
    from backend.memory import session_log
    from backend.config import get_settings
    from backend.agent.session_registry import get_registry

    settings = get_settings()
    thinking_stream_enabled = settings.FF_THINKING_STREAM

    factory = get_session_factory()
    registry = get_registry()

    # ── T2: subscribe this connection ────────────────────────────────
    inbox: asyncio.Queue = registry.subscribe(session_id)
    run_lock = registry.get_lock(session_id)

    async def _drain() -> None:
        """Pump broadcast events → this WS.  Runs as a concurrent task.
        Exits on sentinel (None) or on any send failure."""
        while True:
            payload = await inbox.get()
            if payload is None:          # sentinel sent by finally block
                return
            try:
                await ws.send_json(payload)
            except Exception:
                return                   # client disconnected; exit cleanly

    drain_task = asyncio.create_task(_drain())

    # Load employee_id + last_message_id (T3) in one DB round-trip
    employee_id = None
    last_message_id = 0
    async with factory() as db_session:
        store = MemoryStore(db_session)
        session_data = await store.get_session(session_id)
        if session_data:
            employee_id = session_data.get("employee_id")
        # T3: seed client's maxMessageId so delta hydration starts correctly
        row = await db_session.execute(
            text("SELECT MAX(id) FROM chat_messages WHERE session_id = :sid"),
            {"sid": session_id},
        )
        last_message_id = int(row.scalar() or 0)

    # "connected" is per-connection metadata — send directly, not via broadcast
    try:
        await ws.send_json({
            "type": "connected",
            "session_id": session_id,
            "employee_id": employee_id,
            "last_message_id": last_message_id,   # T3
        })
    except Exception:
        pass

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

            # ── T1: per-session execution lock ────────────────────────
            # run_lock is obtained once at connect-time from the registry
            # (see above).  Serialise run_stream() per session_id. If
            # another WS connection already holds the lock, notify this
            # client only and skip — never wait for the lock, because
            # the run would execute again once released (plan_confirmed
            # is True in the DB by then).
            if run_lock.locked():
                try:
                    await ws.send_json({
                        "event": "already_running",
                        "message": "分析正在进行中，请在右侧面板查看实时进度",
                    })
                except Exception:
                    pass
                continue

            async with run_lock:
                try:
                    prev_task_statuses: dict[str, str] = {}
                    prev_msg_count = 0

                    # T2: ws_callback persists tool events then broadcasts
                    # to all subscribers (not just this WS).
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
                        elif evt == "trace_span":
                            try:
                                span = payload.get("span") or {}
                                # Persist using the span's declared phase so
                                # planning / perception spans land in their
                                # own phase bucket. Legacy spans without a
                                # phase field still default to "execution".
                                span_phase = span.get("phase") or "execution"
                                async with factory() as tx:
                                    await session_log.append_thinking_event(
                                        tx, session_id,
                                        kind="span",
                                        payload=span,
                                        phase=span_phase,
                                    )
                            except Exception:
                                logger.exception("trace_span persist failed")
                        elif evt == "task_update":
                            # Sync diff state so the post-node task_statuses loop
                            # skips statuses already broadcast here (prevents duplicates).
                            tid = payload.get("task_id")
                            ts = payload.get("status")
                            if tid and ts:
                                prev_task_statuses[tid] = ts
                        registry.broadcast(session_id, payload)

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
                            # Broadcast to all subscribers — drain tasks
                            # forward to each WS.
                            registry.broadcast(session_id, {
                                "event": "thinking_stream",
                                "kind": thinking.get("kind", "thinking"),
                                "phase": thinking.get("phase"),
                                "payload": thinking.get("payload"),
                            })
                            continue

                        for node_name, node_state in event.items():
                            # Push slot updates
                            if "slots" in node_state:
                                registry.broadcast(session_id, {
                                    "event": "slot_update",
                                    "slots": node_state.get("slots", {}),
                                    "current_asking": node_state.get("current_target_slot"),
                                })

                            # Push messages — only emit NEW messages (skip already-sent)
                            messages = node_state.get("messages", [])
                            cur_msg_count = len(messages)
                            if cur_msg_count > prev_msg_count:
                                for msg in messages[prev_msg_count:]:
                                    if msg.get("role") == "assistant":
                                        phase = node_state.get("current_phase", "unknown")
                                        content = msg.get("content", "")
                                        msg_type = msg.get("type") or "text"
                                        msg_payload = msg.get("payload")
                                        # Persist assistant message
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
                                            "message_id": persisted_id or None,  # T3
                                        }
                                        if msg_type and msg_type != "text":
                                            out["type"] = msg_type
                                        if msg_payload is not None:
                                            out["payload"] = msg_payload
                                        registry.broadcast(session_id, out)
                                prev_msg_count = cur_msg_count

                            # Push structured intent if ready
                            if node_state.get("structured_intent"):
                                registry.broadcast(session_id, {
                                    "event": "intent_ready",
                                    "intent": node_state["structured_intent"],
                                })

                            # Push plan update
                            if node_state.get("analysis_plan"):
                                registry.broadcast(session_id, {
                                    "event": "plan_update",
                                    "plan": node_state["analysis_plan"],
                                })

                            # Push individual task status changes
                            cur_task_statuses = node_state.get("task_statuses", {})
                            for tid, ts in cur_task_statuses.items():
                                if prev_task_statuses.get(tid) != ts:
                                    registry.broadcast(session_id, {
                                        "event": "task_update",
                                        "task_id": tid,
                                        "status": ts,
                                    })
                            if cur_task_statuses:
                                prev_task_statuses = dict(cur_task_statuses)

                            # Push reflection summary
                            if node_state.get("reflection_summary"):
                                registry.broadcast(session_id, {
                                    "event": "reflection",
                                    "summary": node_state["reflection_summary"],
                                })

                    registry.broadcast(session_id, {"event": "turn_complete"})
                except Exception as e:
                    logger.exception("Error in graph execution")
                    registry.broadcast(session_id, {"type": "error", "message": str(e)})

    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", session_id)
    except Exception as e:
        logger.exception("WebSocket error: %s", e)
    finally:
        # ── T2: clean up this subscriber ─────────────────────────────
        registry.unsubscribe(session_id, inbox)
        inbox.put_nowait(None)       # sentinel — tell drain task to exit
        try:
            await asyncio.wait_for(drain_task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            drain_task.cancel()
