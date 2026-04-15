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
