"""EmployeeManager — 员工管理单例。

Phase 4: dual-source —
  * `FF_EMPLOYEE_SOURCE=yaml` (default) → load from `employees/*.yaml`;
    admin writes are in-memory only.
  * `FF_EMPLOYEE_SOURCE=db` → load from `employees` table; admin writes
    persist to DB, snapshot to `employee_versions`, and invalidate the
    compiled-graph cache so the next session picks up the change.
"""
from __future__ import annotations

import copy
import logging
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

from backend.employees.profile import EmployeeProfile, FAQItem

logger = logging.getLogger("analytica.employees.manager")


class EmployeeManager:
    """员工管理单例 — 管理 profiles 和 compiled graphs 缓存。"""

    _instance: EmployeeManager | None = None
    _profiles: dict[str, EmployeeProfile]
    _graphs: dict[str, Any]  # employee_id -> CompiledGraph
    _source: str  # "yaml" | "db"

    def __init__(self) -> None:
        self._profiles = {}
        self._graphs = {}
        self._source = "yaml"

    @classmethod
    def get_instance(cls) -> EmployeeManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    # ── source selection ────────────────────────────────────

    @property
    def source(self) -> str:
        return self._source

    def set_source(self, source: str) -> None:
        if source not in ("yaml", "db"):
            raise ValueError(f"Unknown employee source: {source!r}")
        self._source = source

    # ── loaders ─────────────────────────────────────────────

    def load_all_profiles(self, config_dir: Path) -> int:
        """从目录加载所有 YAML 员工配置。返回加载数量。"""
        self._source = "yaml"
        loaded = 0
        if not config_dir.is_dir():
            logger.warning("Employee config directory not found: %s", config_dir)
            return loaded

        for yaml_path in sorted(config_dir.glob("*.yaml")):
            try:
                profile = EmployeeProfile.from_yaml(yaml_path)
                self._profiles[profile.employee_id] = profile
                loaded += 1
                logger.info(
                    "Loaded employee profile from YAML: %s (%s) <- %s",
                    profile.employee_id, profile.name, yaml_path.name,
                )
            except Exception:
                logger.exception("Failed to load employee YAML: %s", yaml_path)

        logger.info("Loaded %d employee profiles from YAML", loaded)
        return loaded

    async def load_from_db(self) -> int:
        """Phase 4 — load profiles from the employees table.

        Replaces in-memory cache with DB state; subsequent admin writes
        go through `upsert_employee()` / `delete_employee()` which also
        refresh the cache.
        """
        from backend.database import get_session_factory
        from backend.memory import employee_store

        self._source = "db"
        factory = get_session_factory()
        async with factory() as db:
            rows = await employee_store.list_employees(db, include_archived=False)

        self._profiles = {}
        self._graphs = {}
        for row in rows:
            try:
                profile = _profile_from_row(row)
                self._profiles[profile.employee_id] = profile
            except Exception:
                logger.exception(
                    "Failed to hydrate profile for %s", row.get("employee_id"),
                )
        logger.info("Loaded %d employee profiles from DB", len(self._profiles))
        return len(self._profiles)

    def validate_all_profiles(self) -> list[str]:
        """对所有已加载的 profile 进行运行时注册表校验。返回错误列表。"""
        all_errors: list[str] = []
        for profile in self._profiles.values():
            errors = profile.validate_against_registry()
            all_errors.extend(errors)
        return all_errors

    # ── read ────────────────────────────────────────────────

    def get_employee(self, employee_id: str) -> EmployeeProfile | None:
        return self._profiles.get(employee_id)

    def list_employees(self) -> list[EmployeeProfile]:
        return list(self._profiles.values())

    def get_graph(self, employee_id: str) -> Any:
        """获取员工的 CompiledGraph（延迟构建 + 缓存）。"""
        if employee_id in self._graphs:
            return self._graphs[employee_id]

        profile = self._profiles.get(employee_id)
        if profile is None:
            raise ValueError(f"Unknown employee: {employee_id}")

        from backend.employees.graph_factory import build_employee_graph
        compiled = build_employee_graph(profile)
        self._graphs[employee_id] = compiled
        return compiled

    async def run_employee_stream(
        self,
        employee_id: str,
        session_id: str,
        user_id: str,
        user_message: str,
    ) -> AsyncGenerator[dict, None]:
        """运行员工图并流式返回状态更新。"""
        from backend.agent.graph import make_initial_state

        graph = self.get_graph(employee_id)
        initial = make_initial_state(
            session_id, user_id, user_message, employee_id=employee_id,
        )

        async for event in graph.astream(initial):
            yield event

    # ── admin writes (Phase 4) ─────────────────────────────

    def update_employee(self, employee_id: str, **kwargs) -> EmployeeProfile | None:
        """In-memory update (back-compat for YAML mode).

        DB mode admins should call ``upsert_employee`` instead so writes
        persist. This shim still works in DB mode but its changes are
        lost on restart.
        """
        profile = self._profiles.get(employee_id)
        if profile is None:
            return None
        updates = {k: v for k, v in kwargs.items() if v is not None}
        if not updates:
            return profile
        updated = profile.model_copy(update=updates)
        self._profiles[employee_id] = updated
        self._graphs.pop(employee_id, None)
        logger.info("In-memory update %s: %s", employee_id, list(updates.keys()))
        return updated

    async def upsert_employee(
        self,
        employee_id: str,
        *,
        name: str,
        description: str | None = None,
        version: str = "1.0",
        initials: str | None = None,
        status: str = "active",
        domains: list[str] | None = None,
        endpoints: list[str] | None = None,
        skills: list[str] | None = None,
        faqs: list[dict[str, Any]] | None = None,
        perception: dict[str, Any] | None = None,
        planning: dict[str, Any] | None = None,
        snapshot_note: str | None = None,
    ) -> EmployeeProfile | None:
        """DB-mode create-or-update. Writes employees row + a version
        snapshot, then refreshes the in-memory profile and invalidates
        the graph cache."""
        if self._source != "db":
            raise RuntimeError(
                "upsert_employee requires FF_EMPLOYEE_SOURCE=db "
                f"(current: {self._source})"
            )

        from backend.database import get_session_factory
        from backend.memory import employee_store

        row = {
            "employee_id": employee_id,
            "name": name,
            "description": description or "",
            "version": version,
            "initials": initials,
            "status": status,
            "domains": domains or [],
            "endpoints": endpoints or [],
            "skills": skills or [],
            "faqs": faqs or [],
            "perception": perception,
            "planning": planning,
        }

        factory = get_session_factory()
        async with factory() as db:
            await employee_store.upsert_employee(db, **row)
            # Snapshot this version for audit/diff
            await employee_store.create_version_snapshot(
                db,
                employee_id=employee_id,
                version=version,
                snapshot=row,
                note=snapshot_note,
            )
            refreshed = await employee_store.get_employee(db, employee_id)

        if refreshed is None:
            return None
        try:
            profile = _profile_from_row(refreshed)
        except Exception:
            logger.exception("Post-upsert profile hydration failed for %s", employee_id)
            return None

        self._profiles[employee_id] = profile
        self._graphs.pop(employee_id, None)
        logger.info("DB upsert %s (v%s)", employee_id, version)
        return profile

    async def archive_employee(self, employee_id: str) -> bool:
        """DB-mode soft delete. Returns True if the row was archived."""
        if self._source != "db":
            raise RuntimeError(
                "archive_employee requires FF_EMPLOYEE_SOURCE=db "
                f"(current: {self._source})"
            )

        from backend.database import get_session_factory
        from backend.memory import employee_store

        factory = get_session_factory()
        async with factory() as db:
            ok = await employee_store.delete_employee(db, employee_id)

        if ok:
            self._profiles.pop(employee_id, None)
            self._graphs.pop(employee_id, None)
            logger.info("Archived employee %s", employee_id)
        return ok


# ── helpers ─────────────────────────────────────────────────

def _profile_from_row(row: dict[str, Any]) -> EmployeeProfile:
    """DB row → EmployeeProfile. Tolerates missing sub-configs."""
    from backend.employees.profile import PerceptionConfig, PlanningConfig

    perception_raw = row.get("perception") or {}
    planning_raw = row.get("planning") or {}

    # Nested dataclasses: let pydantic coerce
    perception = PerceptionConfig(**copy.deepcopy(perception_raw))
    planning = PlanningConfig(**copy.deepcopy(planning_raw))

    faqs_raw = row.get("faqs") or []
    faqs = [FAQItem(**copy.deepcopy(f)) for f in faqs_raw if isinstance(f, dict)]

    return EmployeeProfile(
        employee_id=row["employee_id"],
        name=row["name"],
        description=row.get("description") or "",
        version=row.get("version") or "1.0",
        domains=row.get("domains") or [],
        endpoints=row.get("endpoints") or [],
        skills=row.get("skills") or [],
        perception=perception,
        planning=planning,
        initials=row.get("initials"),
        status=row.get("status") or "active",
        faqs=faqs,
    )
