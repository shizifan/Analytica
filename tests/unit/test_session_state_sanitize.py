"""Regression tests for ``backend.memory.store._strip_nan_inf``.

Tools occasionally produce ``NaN`` / ``Infinity`` (waterfall deltas,
divisions by zero, pandas missing values). MySQL's JSON column type
rejects those tokens with ``ER_INVALID_JSON_TEXT`` (3140), so the
session-state save path needs a defensive sanitizer that turns
non-finite floats into ``None`` *before* they reach the wire.

This is unit-level — we don't need MySQL to verify the sanitizer
itself.
"""
from __future__ import annotations

import json
import math

import pytest

from backend.memory.store import _strip_nan_inf


class TestStripNanInf:

    def test_passes_through_finite_floats(self):
        assert _strip_nan_inf(1.5) == 1.5
        assert _strip_nan_inf(0.0) == 0.0
        assert _strip_nan_inf(-3.14) == -3.14

    def test_replaces_nan_with_none(self):
        assert _strip_nan_inf(float("nan")) is None

    def test_replaces_positive_infinity_with_none(self):
        assert _strip_nan_inf(float("inf")) is None

    def test_replaces_negative_infinity_with_none(self):
        assert _strip_nan_inf(float("-inf")) is None

    def test_preserves_non_float_primitives(self):
        assert _strip_nan_inf(0) == 0
        assert _strip_nan_inf(42) == 42
        assert _strip_nan_inf("hello") == "hello"
        assert _strip_nan_inf(None) is None
        assert _strip_nan_inf(True) is True
        assert _strip_nan_inf(False) is False

    def test_nested_dict(self):
        out = _strip_nan_inf({
            "ok": 1.0,
            "broken": float("nan"),
            "deep": {"also_broken": float("inf"), "fine": "x"},
        })
        assert out == {
            "ok": 1.0,
            "broken": None,
            "deep": {"also_broken": None, "fine": "x"},
        }

    def test_nested_list(self):
        assert _strip_nan_inf([1, float("nan"), 3, [float("inf"), 5]]) == [
            1, None, 3, [None, 5],
        ]

    def test_tuple_becomes_list(self):
        """Tuples aren't valid JSON; we coerce to list while sanitising
        so the caller doesn't have to do a separate normalisation pass."""
        assert _strip_nan_inf((1, float("nan"), 2)) == [1, None, 2]

    def test_realistic_state_payload_round_trips_through_json(self):
        """The real failure mode: a session_state dict with a NaN
        buried in a tool output's metadata. After sanitising,
        ``json.dumps(allow_nan=False)`` must succeed."""
        state = {
            "turn_index": 1,
            "task_statuses": {"T001": "done"},
            "execution_context": {
                "T001": {
                    "metadata": {
                        # waterfall deltas frequently produce NaN when
                        # the previous bucket is missing.
                        "yoy_growth": float("nan"),
                        "rows": 12,
                    },
                    "data": [
                        {"month": "2026-01", "value": 100.0},
                        {"month": "2026-02", "value": float("nan")},
                    ],
                },
            },
            "analysis_history": [
                {"key_findings": ["Q1 同比 +2.3%"], "ratio": float("inf")},
            ],
        }

        sanitized = _strip_nan_inf(state)
        payload = json.dumps(sanitized, ensure_ascii=False, allow_nan=False)
        # Round-trips back to a dict with `None` where NaN/Inf was.
        roundtrip = json.loads(payload)
        assert roundtrip["execution_context"]["T001"]["metadata"]["yoy_growth"] is None
        assert roundtrip["execution_context"]["T001"]["data"][1]["value"] is None
        assert roundtrip["analysis_history"][0]["ratio"] is None

    def test_does_not_explode_on_non_serialisable_objects(self):
        """If something exotic slips in, we leave it alone — the
        downstream ``json.dumps`` will raise a clearer ``TypeError``
        than silently mangling a dict-like."""

        class _Custom:
            pass

        obj = _Custom()
        out = _strip_nan_inf({"x": obj, "y": float("nan")})
        assert out["x"] is obj
        assert out["y"] is None

    def test_idempotent(self):
        """Running the sanitizer twice yields the same result — handy
        when callers chain it conservatively."""
        once = _strip_nan_inf({"a": float("nan"), "b": [1, float("inf")]})
        twice = _strip_nan_inf(once)
        assert once == twice


class TestStrictDumps:
    """Smoke tests pinning the ``allow_nan=False`` contract — if the
    sanitizer ever stops scrubbing a value, ``json.dumps`` raises
    instead of writing a malformed payload that MySQL rejects."""

    def test_allow_nan_false_rejects_unsanitized_nan(self):
        with pytest.raises(ValueError):
            json.dumps({"x": float("nan")}, allow_nan=False)

    def test_sanitized_payload_passes_strict_dumps(self):
        payload = json.dumps(
            _strip_nan_inf({"x": float("nan"), "y": 1.5}),
            ensure_ascii=False, allow_nan=False,
        )
        assert json.loads(payload) == {"x": None, "y": 1.5}
