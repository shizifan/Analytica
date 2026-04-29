"""P2.4-2/-3 — admin_store DB read/write contract for the new
semantic-enrichment columns (``field_schema`` / ``use_cases`` /
``chain_with`` / ``analysis_note``).

Verifies:
  * Schema check — all 4 columns exist on the live table.
  * Round-trip — upsert with all four fields, read back identical content.
  * Backward read — rows that pre-date the migration (NULL columns) are
    surfaced as empty list / empty string, never None, so callers can
    treat the shape uniformly.
  * Idempotent UPSERT — running upsert twice with the same payload does
    not duplicate rows or corrupt fields.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

from backend.memory import admin_store

pytestmark = pytest.mark.contract


async def _columns(db, table: str) -> set[str]:
    bind = db.bind
    async with bind.connect() as conn:
        return set(
            c["name"]
            for c in await conn.run_sync(lambda c: inspect(c).get_columns(table))
        )


async def test_api_endpoints_has_semantic_columns(test_db_session):
    cols = await _columns(test_db_session, "api_endpoints")
    for required in ("field_schema", "use_cases", "chain_with", "analysis_note"):
        assert required in cols, f"api_endpoints.{required} column missing"


# ── Round-trip ──────────────────────────────────────────────────────


async def _cleanup(db, name: str) -> None:
    await db.execute(
        text("DELETE FROM api_endpoints WHERE name = :n"),
        {"n": name},
    )
    await db.commit()


async def test_upsert_round_trip_preserves_all_semantic_fields(test_db_session):
    name = "_p24_test_round_trip"
    await _cleanup(test_db_session, name)
    try:
        await admin_store.upsert_api_endpoint(
            test_db_session,
            name=name,
            path=f"/api/test/{name}",
            domain="D1",
            intent="round-trip fixture",
            tags=["test"],
            required_params=[],
            optional_params=[],
            returns="x",
            param_note="",
            disambiguate="",
            field_schema=[
                ["qty", "int", "throughput", "吨吞吐量"],
                ["dateMonth", "str", "month YYYY-MM"],
            ],
            use_cases=["典型用例 1", "典型用例 2"],
            chain_with=["someOtherEndpoint"],
            analysis_note="N 行透视格式，先按 typeName 分组",
        )
        row = await admin_store.get_api_endpoint(test_db_session, name)
        assert row is not None
        assert row["field_schema"] == [
            ["qty", "int", "throughput", "吨吞吐量"],
            ["dateMonth", "str", "month YYYY-MM"],
        ]
        assert row["use_cases"] == ["典型用例 1", "典型用例 2"]
        assert row["chain_with"] == ["someOtherEndpoint"]
        assert row["analysis_note"] == "N 行透视格式，先按 typeName 分组"
    finally:
        await _cleanup(test_db_session, name)


async def test_get_returns_empty_collections_for_null_columns(test_db_session):
    """Pre-P2.4 rows have NULL semantic columns — _api_row must coerce to
    empty lists / "" so reload_from_db (P2.4-5) can rebuild ApiEndpoint
    without per-field None checks."""
    name = "_p24_test_null_coerce"
    await _cleanup(test_db_session, name)
    try:
        # Bypass the upsert helper so the new columns stay NULL.
        await test_db_session.execute(
            text(
                "INSERT INTO api_endpoints "
                "(name, method, path, domain, intent, source, enabled) "
                "VALUES (:n, 'GET', '/x', 'D1', 'i', 'mock', 1)"
            ),
            {"n": name},
        )
        await test_db_session.commit()

        row = await admin_store.get_api_endpoint(test_db_session, name)
        assert row is not None
        assert row["field_schema"] == []
        assert row["use_cases"] == []
        assert row["chain_with"] == []
        assert row["analysis_note"] == ""
    finally:
        await _cleanup(test_db_session, name)


async def test_upsert_is_idempotent(test_db_session):
    """Running the same UPSERT twice must not duplicate or corrupt."""
    name = "_p24_test_idempotent"
    await _cleanup(test_db_session, name)
    try:
        payload = dict(
            name=name,
            path=f"/api/test/{name}",
            domain="D1",
            intent="idempotency fixture",
            tags=["t1"],
            field_schema=[["qty", "int", ""]],
            use_cases=["uc1"],
            chain_with=[],
            analysis_note="note",
        )
        await admin_store.upsert_api_endpoint(test_db_session, **payload)
        await admin_store.upsert_api_endpoint(test_db_session, **payload)

        result = await test_db_session.execute(
            text("SELECT COUNT(*) FROM api_endpoints WHERE name = :n"),
            {"n": name},
        )
        assert result.scalar() == 1
        row = await admin_store.get_api_endpoint(test_db_session, name)
        assert row["field_schema"] == [["qty", "int", ""]]
        assert row["use_cases"] == ["uc1"]
        assert row["analysis_note"] == "note"
    finally:
        await _cleanup(test_db_session, name)


async def test_upsert_overwrites_existing_fields(test_db_session):
    """Second UPSERT with different content must replace, not merge."""
    name = "_p24_test_overwrite"
    await _cleanup(test_db_session, name)
    try:
        await admin_store.upsert_api_endpoint(
            test_db_session,
            name=name, path="/x", domain="D1",
            field_schema=[["a", "int", "first"]],
            use_cases=["original"],
        )
        await admin_store.upsert_api_endpoint(
            test_db_session,
            name=name, path="/x", domain="D1",
            field_schema=[["b", "str", "second"]],
            use_cases=["replaced"],
        )
        row = await admin_store.get_api_endpoint(test_db_session, name)
        assert row["field_schema"] == [["b", "str", "second"]]
        assert row["use_cases"] == ["replaced"]
    finally:
        await _cleanup(test_db_session, name)
