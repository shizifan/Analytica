"""Per-session WebSocket fan-out registry (T2).

One SessionHandle per session_id tracks the per-session asyncio.Lock
(preventing concurrent runs — T1) and the set of active WS subscriber
queues (broadcast fan-out — T2).

Design notes
────────────
• asyncio is single-threaded (cooperative), so plain dict/set mutations
  are atomic at the Python level — no additional asyncio.Lock is needed
  to guard this registry.
• broadcast() is a *synchronous* method that uses put_nowait().  This
  lets it be called freely from any coroutine without an extra await.
• QueueFull events are silently dropped.  A slow/disconnecting client
  will hydrate missing events on reconnect via the REST replay endpoints.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

# Drop events when a subscriber's inbox is full.  500 items is generous
# for a single analysis run (typically < 150 events total).
_QUEUE_MAXSIZE = 500


@dataclass
class SessionHandle:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    queues: set[asyncio.Queue] = field(default_factory=set)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


class SessionRegistry:
    """Runtime fan-out state for all active WebSocket sessions.

    One singleton per process.  Thread-safety: single asyncio event loop —
    no preemption between dict/set operations.
    """

    def __init__(self) -> None:
        self._handles: dict[str, SessionHandle] = {}

    # ── internal helpers ─────────────────────────────────────────────

    def _ensure(self, session_id: str) -> SessionHandle:
        """Return (creating if absent) the handle for session_id."""
        if session_id not in self._handles:
            self._handles[session_id] = SessionHandle()
        return self._handles[session_id]

    # ── public API ───────────────────────────────────────────────────

    def get_lock(self, session_id: str) -> asyncio.Lock:
        """Return the execution lock for session_id (T1)."""
        return self._ensure(session_id).lock

    def subscribe(self, session_id: str) -> asyncio.Queue:
        """Register a new WS subscriber; returns its dedicated inbox queue."""
        handle = self._ensure(session_id)
        q: asyncio.Queue[Any] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        handle.queues.add(q)
        return q

    def unsubscribe(self, session_id: str, q: asyncio.Queue) -> None:
        """Remove a subscriber's inbox from the fan-out set."""
        handle = self._handles.get(session_id)
        if handle:
            handle.queues.discard(q)

    def get_cancel_event(self, session_id: str) -> asyncio.Event:
        """Return the cancellation Event for session_id."""
        return self._ensure(session_id).cancel_event

    def request_cancel(self, session_id: str) -> None:
        """Signal the running execution to stop."""
        self._ensure(session_id).cancel_event.set()

    def clear_cancel(self, session_id: str) -> None:
        """Reset cancellation state before a new run starts."""
        handle = self._handles.get(session_id)
        if handle:
            handle.cancel_event.clear()

    def broadcast(self, session_id: str, payload: Any) -> None:
        """Fan out payload to every subscriber's inbox (synchronous)."""
        handle = self._handles.get(session_id)
        if not handle:
            return
        # Snapshot the set to avoid mutation during iteration (a concurrent
        # unsubscribe could otherwise raise RuntimeError).
        for q in list(handle.queues):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                pass  # slow / disconnecting client — will hydrate on reconnect


# Module singleton — imported by main.py
_registry = SessionRegistry()


def get_registry() -> SessionRegistry:
    return _registry
