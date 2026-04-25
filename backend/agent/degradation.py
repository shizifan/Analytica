"""Cross-cutting degradation channel.

Records "silent loss avoided" events from any layer of the pipeline:
  • planning      — tasks dropped by validator
  • execution     — tasks failed but pipeline continued
  • collector     — report items reassigned to fallback section
  • parser        — config fields normalised away from invalid shapes

Each event is appended to ``state["degradations"]`` (a list of dicts)
so reflection / chat bubble / Trace tab can surface them to the user.

The principle: every silent fallback in the system either
  ① cascades cleanly (so nothing surprising downstream), AND
  ② emits a DegradationEvent so the user/operator can see what happened.

Never let a drop disappear into log files alone.
"""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any


# ── Severity vocabulary ──
# info  — recoverable, no user-visible impact (e.g. M-code resolved to canonical name)
# warn  — recoverable but user might notice (e.g. axis spec normalised, item reassigned)
# error — partial failure, user-visible (e.g. tasks dropped, plan retried)
SEVERITY_INFO = "info"
SEVERITY_WARN = "warn"
SEVERITY_ERROR = "error"


@dataclass
class DegradationEvent:
    """A single recorded degradation. Designed to round-trip through JSON."""

    layer: str                          # "planning" / "execution" / "collector" / "parser"
    severity: str                       # info / warn / error
    reason: str                         # human-readable, shown to user
    affected: dict[str, Any] = field(default_factory=dict)
    """Structured details: ``{"task_ids": [...], "item_count": N, "config_keys": [...]}``."""
    ts: int = field(default_factory=lambda: int(time.time()))


def record(state: dict[str, Any], event: DegradationEvent) -> None:
    """Append an event to ``state["degradations"]``.

    Safe to call even if ``state`` is missing the key — bootstraps as empty list.
    """
    state.setdefault("degradations", []).append(asdict(event))


def summarize(state: dict[str, Any]) -> str | None:
    """Render degradations as a markdown bullet list, or None if empty.

    Used by chat-bubble assembly to append a "降级提示" section to the
    assistant message when something non-trivial happened.
    """
    events = state.get("degradations") or []
    if not events:
        return None
    by_severity: dict[str, list[dict]] = {SEVERITY_ERROR: [], SEVERITY_WARN: [], SEVERITY_INFO: []}
    for e in events:
        by_severity.setdefault(e.get("severity", SEVERITY_INFO), []).append(e)

    parts: list[str] = []
    for sev, label in [(SEVERITY_ERROR, "❗ 错误降级"), (SEVERITY_WARN, "⚠️ 一般降级"), (SEVERITY_INFO, "ℹ️ 信息")]:
        bucket = by_severity.get(sev) or []
        if not bucket:
            continue
        parts.append(f"**{label}**")
        for e in bucket:
            parts.append(f"- [{e.get('layer','?')}] {e.get('reason','')}")
    return "\n".join(parts) if parts else None
