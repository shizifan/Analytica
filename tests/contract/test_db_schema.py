"""DB schema invariants — fails immediately if migrations diverge from ORM
or if a recent rename (skill→tool, etc.) is incomplete on either side.

These are read-only inspection tests; no data is written.
"""
from __future__ import annotations

import pytest
from sqlalchemy import inspect, text

pytestmark = pytest.mark.contract


async def _table_names(db) -> set[str]:
    bind = db.bind
    async with bind.connect() as conn:
        return set(await conn.run_sync(lambda c: inspect(c).get_table_names()))


async def _columns(db, table: str) -> set[str]:
    bind = db.bind
    async with bind.connect() as conn:
        return set(
            c["name"]
            for c in await conn.run_sync(lambda c: inspect(c).get_columns(table))
        )


async def test_employees_has_tools_column_not_skills(test_db_session):
    """Migration 20260425 renamed `employees.skills` → `employees.tools`."""
    cols = await _columns(test_db_session, "employees")
    assert "tools" in cols, "employees.tools column missing — migration not applied"
    assert "skills" not in cols, "employees.skills column still present — old schema"


async def test_tool_notes_table_exists_not_skill_notes(test_db_session):
    """Migration 20260425 renamed `skill_notes` table → `tool_notes`."""
    tables = await _table_names(test_db_session)
    assert "tool_notes" in tables, "tool_notes table missing"
    assert "skill_notes" not in tables, "skill_notes table still present"


async def test_tools_table_uses_tool_id_pk(test_db_session):
    """Migration 20260425 renamed `tools.skill_id` → `tools.tool_id`."""
    cols = await _columns(test_db_session, "tools")
    assert "tool_id" in cols, "tools.tool_id column missing"
    assert "skill_id" not in cols, "tools.skill_id column still present"


async def test_report_artifacts_uses_tool_id(test_db_session):
    cols = await _columns(test_db_session, "report_artifacts")
    assert "tool_id" in cols
    assert "skill_id" not in cols


async def test_tool_notes_uses_tool_id(test_db_session):
    cols = await _columns(test_db_session, "tool_notes")
    assert "tool_id" in cols
    assert "skill_id" not in cols


async def test_agent_skills_table_preserved(test_db_session):
    """`agent_skills` (real SOP concept) must NOT have been touched by the
    rename — its skill_id column is intentional."""
    tables = await _table_names(test_db_session)
    assert "agent_skills" in tables
    cols = await _columns(test_db_session, "agent_skills")
    assert "skill_id" in cols, "agent_skills.skill_id (SOP id) was incorrectly renamed"


async def test_orm_tablename_matches_db(test_db_session):
    """Smoke: every ORM model with __tablename__ must exist in the DB."""
    from backend.database import Base
    db_tables = await _table_names(test_db_session)
    for mapper in Base.registry.mappers:
        cls = mapper.class_
        tablename = getattr(cls, "__tablename__", None)
        if not tablename:
            continue
        assert tablename in db_tables, (
            f"ORM model {cls.__name__} expects table {tablename!r} but DB has none. "
            "Migrations are out of sync with ORM."
        )


async def test_alembic_head_matches_latest(test_db_session):
    """The DB's recorded migration revision must match the latest file
    (= no pending migrations). Catches "forgot to run upgrade" mistakes."""
    rows = await test_db_session.execute(text("SELECT version_num FROM alembic_version"))
    db_rev = rows.scalar_one_or_none()
    assert db_rev is not None, "alembic_version table empty — DB never migrated"

    # Find latest revision file by lexical sort (our IDs are date-prefixed).
    from pathlib import Path
    versions_dir = Path(__file__).resolve().parent.parent.parent / "migrations" / "versions"
    files = sorted(versions_dir.glob("*.py"))
    assert files, "no migration files found"
    # Read each file's `revision: str = "..."` line and pick the chain head.
    import re
    revs = {}
    for f in files:
        src = f.read_text(encoding="utf-8")
        m_rev = re.search(r'revision:\s*str\s*=\s*"([^"]+)"', src)
        m_down = re.search(r'down_revision:\s*Union\[str,\s*None\]\s*=\s*"([^"]+)"', src)
        if not m_rev:
            continue
        revs[m_rev.group(1)] = m_down.group(1) if m_down else None
    # Head = revision that no other revision points to as down_revision.
    pointed_to = {dr for dr in revs.values() if dr}
    heads = [r for r in revs if r not in pointed_to]
    assert len(heads) == 1, f"multiple migration heads: {heads}"
    assert db_rev == heads[0], (
        f"DB at {db_rev} but latest migration is {heads[0]} — run `alembic upgrade head`"
    )
