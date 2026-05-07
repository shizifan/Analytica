class AnalyticaError(Exception):
    """Base exception for Analytica."""


class SlotFillingError(AnalyticaError):
    """Raised when slot filling encounters an unrecoverable error."""


class PlanningError(AnalyticaError):
    """Raised when planning encounters an unrecoverable error."""


class ExecutionError(AnalyticaError):
    """Raised when execution encounters an unrecoverable error."""


class DatabaseError(AnalyticaError):
    """Raised when a database operation fails."""


class WorkspaceError(AnalyticaError):
    """SessionWorkspace cannot satisfy a request (missing file, manifest
    entry not found, lock failure...)."""


class WorkspaceSerializationError(WorkspaceError):
    """A ToolOutput.data value cannot be persisted in any of the
    supported formats (parquet/feather/json/text/bytes).

    Carries the failing task_id so callers can flip the task status to
    failed (V6 §11 R8 — failure must surface, never悄悄不可用)."""

    def __init__(self, message: str, *, task_id: str | None = None) -> None:
        super().__init__(message)
        self.task_id = task_id


class TaskError(ExecutionError):
    """A single task failed in a way the executor must surface as
    task_error (not a process-level crash). Used by fail-fast paths
    like data_ref resolution and workspace persistence (V6 §5.3)."""
