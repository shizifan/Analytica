"""Unit tests for backend/agent/session_registry.py (T1 + T2).

TC-REG01  subscribe() creates an independent queue per caller
TC-REG02  unsubscribe() removes queue from fan-out set
TC-REG03  get_lock() returns the same Lock for the same session_id
TC-REG04  get_lock() returns distinct Locks for different session_ids
TC-REG05  broadcast() delivers to all active subscribers
TC-REG06  broadcast() to a session with no subscribers is a silent no-op
TC-REG07  broadcast() survives QueueFull without raising
TC-REG08  broadcast() after unsubscribe does not deliver to that queue
TC-REG09  T1 — lock is unlocked initially; locked while held; released after
TC-REG10  T1 — each session_id has its own independent lock
TC-REG11  T2 — multiple windows: one run, both windows receive all events
TC-REG12  late subscriber does not receive pre-subscription events
"""
from __future__ import annotations

import asyncio
import pytest

from backend.agent.session_registry import SessionRegistry


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def make_registry() -> SessionRegistry:
    """Return a fresh registry for each test (not the module singleton)."""
    return SessionRegistry()


async def drain(q: asyncio.Queue, n: int) -> list:
    """Pull exactly n items from queue without blocking forever."""
    items = []
    for _ in range(n):
        items.append(await asyncio.wait_for(q.get(), timeout=1.0))
    return items


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG01: subscribe() creates independent queues
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_subscribe_creates_independent_queues():
    """Each subscriber gets its own queue; items do not bleed between them."""
    reg = make_registry()
    q1 = reg.subscribe("s1")
    q2 = reg.subscribe("s1")

    assert q1 is not q2, "each subscriber must get a distinct queue"

    reg.broadcast("s1", {"msg": "hello"})

    item1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    item2 = await asyncio.wait_for(q2.get(), timeout=1.0)
    assert item1 == item2 == {"msg": "hello"}


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG02: unsubscribe() stops delivery
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unsubscribe_stops_delivery():
    reg = make_registry()
    q = reg.subscribe("s1")

    reg.broadcast("s1", "before_unsub")
    reg.unsubscribe("s1", q)
    reg.broadcast("s1", "after_unsub")

    # Only the first message should be in the queue
    item = await asyncio.wait_for(q.get(), timeout=1.0)
    assert item == "before_unsub"
    assert q.empty(), "second broadcast must not reach unsubscribed queue"


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG03 / TC-REG04: get_lock() identity
# ─────────────────────────────────────────────────────────────────────────────

def test_get_lock_same_session_returns_same_object():
    """T1: must hand back the identical lock so 'locked()' is meaningful."""
    reg = make_registry()
    lock_a = reg.get_lock("s1")
    lock_b = reg.get_lock("s1")
    assert lock_a is lock_b


def test_get_lock_different_sessions_return_different_objects():
    """T1: each session serialises independently."""
    reg = make_registry()
    assert reg.get_lock("s1") is not reg.get_lock("s2")


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG05: broadcast() delivers to all subscribers
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_broadcast_delivers_to_all_subscribers():
    reg = make_registry()
    queues = [reg.subscribe("s1") for _ in range(5)]

    payload = {"event": "task_update", "task_id": "T001", "status": "done"}
    reg.broadcast("s1", payload)

    for q in queues:
        received = await asyncio.wait_for(q.get(), timeout=1.0)
        assert received == payload


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG06: broadcast() to non-existent session is silent
# ─────────────────────────────────────────────────────────────────────────────

def test_broadcast_no_subscribers_is_noop():
    reg = make_registry()
    # Must not raise; there's simply nobody to receive it.
    reg.broadcast("unknown_session", {"event": "turn_complete"})


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG07: broadcast() handles QueueFull gracefully
# ─────────────────────────────────────────────────────────────────────────────

def test_broadcast_survives_queue_full():
    """A slow / disconnecting subscriber's full inbox must not raise or block."""
    from backend.agent.session_registry import _QUEUE_MAXSIZE

    reg = make_registry()
    q_slow = reg.subscribe("s1")

    # Fill the queue to capacity
    for i in range(_QUEUE_MAXSIZE):
        q_slow.put_nowait(i)

    # One more broadcast must NOT raise
    reg.broadcast("s1", "overflow_event")

    # The queue still holds exactly _QUEUE_MAXSIZE items (overflow dropped)
    assert q_slow.qsize() == _QUEUE_MAXSIZE


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG08: unsubscribed queue does not receive subsequent broadcasts
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_unsubscribed_queue_receives_nothing_after_removal():
    reg = make_registry()
    q_active = reg.subscribe("s1")
    q_gone = reg.subscribe("s1")

    reg.unsubscribe("s1", q_gone)
    reg.broadcast("s1", "event_after_unsub")

    # Active subscriber receives
    item = await asyncio.wait_for(q_active.get(), timeout=1.0)
    assert item == "event_after_unsub"

    # Removed subscriber is empty
    assert q_gone.empty()


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG09: T1 — lock lifecycle (unlocked → locked → released)
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_lock_lifecycle():
    reg = make_registry()
    lock = reg.get_lock("s1")

    # Initially unlocked
    assert not lock.locked(), "lock must be free at creation"

    # Held inside context
    acquired = asyncio.Event()
    released = asyncio.Event()

    async def holder():
        async with lock:
            acquired.set()
            await released.wait()

    task = asyncio.create_task(holder())
    await asyncio.wait_for(acquired.wait(), timeout=1.0)
    assert lock.locked(), "lock must be held inside 'async with'"

    released.set()
    await asyncio.wait_for(task, timeout=1.0)
    assert not lock.locked(), "lock must be released after 'async with'"


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG10: T1 — sessions have independent locks
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_sessions_have_independent_locks():
    """Locking session A must not affect session B."""
    reg = make_registry()
    lock_a = reg.get_lock("s_a")
    lock_b = reg.get_lock("s_b")

    async with lock_a:
        assert lock_a.locked()
        assert not lock_b.locked(), "session B lock must remain free"

    assert not lock_a.locked()


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG11: T2 — one run, two windows, both receive all events
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_two_windows_same_session_receive_identical_events():
    """Core multi-window scenario: one run broadcasts, both WS clients see it."""
    reg = make_registry()
    inbox_a = reg.subscribe("session_x")
    inbox_b = reg.subscribe("session_x")
    lock = reg.get_lock("session_x")

    events = [
        {"event": "message", "content": "已理解", "message_id": 101},
        {"event": "task_update", "task_id": "T001", "status": "running"},
        {"event": "task_update", "task_id": "T001", "status": "done"},
        {"event": "turn_complete"},
    ]

    # Simulate one run holding the lock and broadcasting events
    async with lock:
        assert lock.locked()
        for e in events:
            reg.broadcast("session_x", e)

    received_a = await drain(inbox_a, len(events))
    received_b = await drain(inbox_b, len(events))

    assert received_a == events, "window A must receive all events in order"
    assert received_b == events, "window B must receive all events in order"


# ─────────────────────────────────────────────────────────────────────────────
# TC-REG12: late subscriber misses pre-subscription events
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_late_subscriber_does_not_receive_prior_events():
    """A window connecting mid-run only sees events after its subscribe()."""
    reg = make_registry()
    early = reg.subscribe("s1")

    reg.broadcast("s1", {"event": "message", "message_id": 1})
    reg.broadcast("s1", {"event": "message", "message_id": 2})

    # Late subscriber joins after two events have been broadcast
    late = reg.subscribe("s1")

    reg.broadcast("s1", {"event": "message", "message_id": 3})

    early_items = await drain(early, 3)
    late_items = await drain(late, 1)

    assert [i["message_id"] for i in early_items] == [1, 2, 3]
    assert late_items[0]["message_id"] == 3, "late subscriber only sees post-join events"
    assert late.empty()
