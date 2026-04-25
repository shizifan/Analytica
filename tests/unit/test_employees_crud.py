"""Phase 4: employees DAL + Manager CRUD round-trip."""
from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy import text

from backend.employees.manager import EmployeeManager
from backend.memory import employee_store


@pytest_asyncio.fixture(loop_scope="function")
async def clean_employees(test_db_session):
    """Wipe test rows before and after; DB is shared so use a fixed prefix."""
    ids = ("test_emp_alpha", "test_emp_beta")
    for eid in ids:
        await test_db_session.execute(
            text("DELETE FROM employees WHERE employee_id = :eid"),
            {"eid": eid},
        )
        await test_db_session.execute(
            text("DELETE FROM employee_versions WHERE employee_id = :eid"),
            {"eid": eid},
        )
    await test_db_session.commit()
    yield ids
    for eid in ids:
        await test_db_session.execute(
            text("DELETE FROM employees WHERE employee_id = :eid"),
            {"eid": eid},
        )
        await test_db_session.execute(
            text("DELETE FROM employee_versions WHERE employee_id = :eid"),
            {"eid": eid},
        )
    await test_db_session.commit()


@pytest.mark.asyncio(loop_scope="function")
async def test_dal_upsert_get_list_delete(clean_employees, test_db_session):
    db = test_db_session
    eid = clean_employees[0]

    await employee_store.upsert_employee(
        db,
        employee_id=eid,
        name="Alpha",
        description="desc",
        version="1.0",
        initials="AL",
        status="active",
        domains=["D1"],
        endpoints=[],
        tools=["tool_api_fetch"],
        faqs=[{"id": "q1", "question": "hello?"}],
        perception={"system_prompt_suffix": "hi"},
        planning={"prompt_suffix": "plan"},
    )

    got = await employee_store.get_employee(db, eid)
    assert got is not None
    assert got["name"] == "Alpha"
    assert got["domains"] == ["D1"]
    assert got["faqs"][0]["question"] == "hello?"
    assert got["perception"]["system_prompt_suffix"] == "hi"

    lst = await employee_store.list_employees(db)
    assert any(e["employee_id"] == eid for e in lst)

    # soft delete
    ok = await employee_store.delete_employee(db, eid)
    assert ok is True
    again = await employee_store.get_employee(db, eid)
    assert again is not None and again["status"] == "archived"

    # default list filters archived
    lst2 = await employee_store.list_employees(db)
    assert all(e["employee_id"] != eid for e in lst2)


@pytest.mark.asyncio(loop_scope="function")
async def test_dal_version_snapshots(clean_employees, test_db_session):
    db = test_db_session
    eid = clean_employees[0]

    await employee_store.upsert_employee(
        db, employee_id=eid, name="Alpha", description="", version="1.0",
        initials=None, status="active",
        domains=["D1"], endpoints=[], tools=[], faqs=[],
        perception=None, planning=None,
    )
    await employee_store.create_version_snapshot(
        db, eid, "1.0", {"name": "Alpha", "version": "1.0"},
    )
    await employee_store.create_version_snapshot(
        db, eid, "1.1", {"name": "Alpha v1.1", "version": "1.1"}, note="bump",
    )

    versions = await employee_store.list_versions(db, eid)
    assert {v["version"] for v in versions} == {"1.0", "1.1"}
    v11 = await employee_store.get_version_snapshot(db, eid, "1.1")
    assert v11["name"] == "Alpha v1.1"


@pytest.mark.asyncio(loop_scope="function")
async def test_manager_upsert_refreshes_cache(clean_employees, test_db_session):
    """Manager.upsert_employee must hydrate the in-memory cache + drop the
    compiled graph so the next chat turn picks up the new profile."""
    eid = clean_employees[1]
    EmployeeManager.reset()
    mgr = EmployeeManager.get_instance()
    mgr.set_source("db")

    profile = await mgr.upsert_employee(
        eid,
        name="Beta",
        description="",
        version="1.0",
        initials="BE",
        status="active",
        domains=["D1"],
        endpoints=[],
        tools=["tool_api_fetch"],
        faqs=[],
        perception={"system_prompt_suffix": ""},
        planning={"prompt_suffix": ""},
    )
    assert profile is not None
    assert mgr.get_employee(eid) is not None
    assert mgr.get_employee(eid).name == "Beta"

    # Simulate a compiled-graph in cache; a new upsert should evict it.
    mgr._graphs[eid] = object()
    await mgr.upsert_employee(
        eid,
        name="Beta v2",
        description="",
        version="1.1",
        initials="BE",
        status="active",
        domains=["D1"],
        endpoints=[],
        tools=["tool_api_fetch"],
        faqs=[],
        perception={"system_prompt_suffix": ""},
        planning={"prompt_suffix": ""},
    )
    assert mgr.get_employee(eid).name == "Beta v2"
    assert eid not in mgr._graphs


@pytest.mark.asyncio(loop_scope="function")
async def test_manager_yaml_mode_rejects_db_writes(clean_employees):
    EmployeeManager.reset()
    mgr = EmployeeManager.get_instance()
    mgr.set_source("yaml")

    with pytest.raises(RuntimeError):
        await mgr.upsert_employee(
            "whatever", name="x", domains=["D1"], endpoints=[], tools=[],
        )
    with pytest.raises(RuntimeError):
        await mgr.archive_employee("whatever")
