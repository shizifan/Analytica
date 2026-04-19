"""EmployeeManager — 员工管理单例。

职责：
1. 从 YAML 目录加载所有 EmployeeProfile
2. 为每个员工延迟构建 CompiledGraph（缓存）
3. 提供 run_employee_stream() 作为 WebSocket 调用入口
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, AsyncGenerator

from backend.employees.profile import EmployeeProfile

logger = logging.getLogger("analytica.employees.manager")


class EmployeeManager:
    """员工管理单例 — 管理 profiles 和 compiled graphs 缓存。"""

    _instance: EmployeeManager | None = None
    _profiles: dict[str, EmployeeProfile]
    _graphs: dict[str, Any]  # employee_id -> CompiledGraph

    def __init__(self) -> None:
        self._profiles = {}
        self._graphs = {}

    @classmethod
    def get_instance(cls) -> EmployeeManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset singleton (for testing)."""
        cls._instance = None

    def load_all_profiles(self, config_dir: Path) -> int:
        """从目录加载所有 YAML 员工配置。返回加载数量。"""
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
                    "Loaded employee profile: %s (%s) from %s",
                    profile.employee_id, profile.name, yaml_path.name,
                )
            except Exception:
                logger.exception("Failed to load employee YAML: %s", yaml_path)

        logger.info("Loaded %d employee profiles total", loaded)
        return loaded

    def validate_all_profiles(self) -> list[str]:
        """对所有已加载的 profile 进行运行时注册表校验。返回错误列表。"""
        all_errors: list[str] = []
        for profile in self._profiles.values():
            errors = profile.validate_against_registry()
            all_errors.extend(errors)
        return all_errors

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

    def update_employee(self, employee_id: str, **kwargs) -> EmployeeProfile | None:
        """更新员工配置（仅内存，重启后从 YAML 重新加载）。"""
        profile = self._profiles.get(employee_id)
        if profile is None:
            return None
        # Filter out None values
        updates = {k: v for k, v in kwargs.items() if v is not None}
        if not updates:
            return profile
        updated = profile.model_copy(update=updates)
        self._profiles[employee_id] = updated
        # Invalidate cached graph
        self._graphs.pop(employee_id, None)
        logger.info("Updated employee %s: %s", employee_id, list(updates.keys()))
        return updated
