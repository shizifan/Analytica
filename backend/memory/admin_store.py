"""Phase 6 — DAL for the admin console.

Groups together CRUD for api_endpoints / tools / domains / audit_logs.
Memory / preference reads are aggregated views on top of existing tables
(user_preferences, analysis_templates, tool_notes) — see
`list_memory_entries` below.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


# ── JSON helpers ───────────────────────────────────────────────

def _json_field(raw: Any) -> Any:
    if isinstance(raw, (list, dict)):
        return raw
    if isinstance(raw, str):
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw
    return raw


def _iso(dt: Any) -> Any:
    if isinstance(dt, datetime):
        return dt.isoformat()
    return dt


# ── api_endpoints ─────────────────────────────────────────────

async def list_api_endpoints(
    db: AsyncSession,
    *,
    domain: Optional[str] = None,
    query: Optional[str] = None,
    limit: int = 500,
) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    params: dict[str, Any] = {"lim": limit}
    if domain:
        where.append("domain = :dom")
        params["dom"] = domain
    if query:
        where.append("(name LIKE :q OR intent LIKE :q)")
        params["q"] = f"%{query}%"

    sql = (
        "SELECT name, method, path, domain, intent, time_type, granularity, "
        "tags, required_params, optional_params, returns, param_note, "
        "disambiguate, source, enabled, created_at, updated_at, "
        "field_schema, use_cases, chain_with, analysis_note "
        "FROM api_endpoints WHERE " + " AND ".join(where) +
        " ORDER BY domain, name LIMIT :lim"
    )
    rows = await db.execute(text(sql), params)
    return [_api_row(r) for r in rows]


def _api_row(r: Any) -> dict[str, Any]:
    return {
        "name": r[0],
        "method": r[1],
        "path": r[2],
        "domain": r[3],
        "intent": r[4],
        "time_type": r[5],
        "granularity": r[6],
        "tags": _json_field(r[7]),
        "required_params": _json_field(r[8]),
        "optional_params": _json_field(r[9]),
        "returns": r[10],
        "param_note": r[11],
        "disambiguate": r[12],
        "source": r[13],
        "enabled": bool(r[14]),
        "created_at": _iso(r[15]),
        "updated_at": _iso(r[16]),
        # P2.4: semantic-enrichment fields. NULL → empty list / "" so the
        # consumers (api_registry.reload_from_db) can rebuild ApiEndpoint
        # without per-field None checks.
        "field_schema": _json_field(r[17]) or [],
        "use_cases": _json_field(r[18]) or [],
        "chain_with": _json_field(r[19]) or [],
        "analysis_note": r[20] or "",
    }


async def get_api_endpoint(
    db: AsyncSession, name: str,
) -> Optional[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT name, method, path, domain, intent, time_type, granularity, "
            "tags, required_params, optional_params, returns, param_note, "
            "disambiguate, source, enabled, created_at, updated_at, "
            "field_schema, use_cases, chain_with, analysis_note "
            "FROM api_endpoints WHERE name = :n"
        ),
        {"n": name},
    )
    row = rows.first()
    if row is None:
        return None
    return _api_row(row)


async def upsert_api_endpoint(
    db: AsyncSession,
    *,
    name: str,
    method: str = "GET",
    path: str,
    domain: str,
    intent: str | None = None,
    time_type: str | None = None,
    granularity: str | None = None,
    tags: list[str] | None = None,
    required_params: list[str] | None = None,
    optional_params: list[str] | None = None,
    returns: str | None = None,
    param_note: str | None = None,
    disambiguate: str | None = None,
    source: str = "mock",
    enabled: bool = True,
    # P2.4: semantic-enrichment fields. ``field_schema`` rows are
    # 3- or 4-element tuples per P2.3a (4th = label_zh).
    field_schema: list[list[Any]] | None = None,
    use_cases: list[str] | None = None,
    chain_with: list[str] | None = None,
    analysis_note: str | None = None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO api_endpoints
                (name, method, path, domain, intent, time_type, granularity,
                 tags, required_params, optional_params, returns,
                 param_note, disambiguate, source, enabled,
                 field_schema, use_cases, chain_with, analysis_note)
            VALUES
                (:n, :method, :path, :dom, :intent, :tt, :gr,
                 :tags, :req, :opt, :ret, :note, :dis, :src, :en,
                 :fs, :uc, :cw, :an)
            ON DUPLICATE KEY UPDATE
                method = VALUES(method),
                path = VALUES(path),
                domain = VALUES(domain),
                intent = VALUES(intent),
                time_type = VALUES(time_type),
                granularity = VALUES(granularity),
                tags = VALUES(tags),
                required_params = VALUES(required_params),
                optional_params = VALUES(optional_params),
                returns = VALUES(returns),
                param_note = VALUES(param_note),
                disambiguate = VALUES(disambiguate),
                source = VALUES(source),
                enabled = VALUES(enabled),
                field_schema = VALUES(field_schema),
                use_cases = VALUES(use_cases),
                chain_with = VALUES(chain_with),
                analysis_note = VALUES(analysis_note),
                updated_at = NOW()
            """
        ),
        {
            "n": name,
            "method": method,
            "path": path,
            "dom": domain,
            "intent": intent,
            "tt": time_type,
            "gr": granularity,
            "tags": json.dumps(tags or [], ensure_ascii=False),
            "req": json.dumps(required_params or [], ensure_ascii=False),
            "opt": json.dumps(optional_params or [], ensure_ascii=False),
            "ret": returns,
            "note": param_note,
            "dis": disambiguate,
            "src": source,
            "en": 1 if enabled else 0,
            "fs": json.dumps(field_schema or [], ensure_ascii=False),
            "uc": json.dumps(use_cases or [], ensure_ascii=False),
            "cw": json.dumps(chain_with or [], ensure_ascii=False),
            "an": analysis_note,
        },
    )
    await db.commit()


async def delete_api_endpoint(db: AsyncSession, name: str) -> bool:
    result = await db.execute(
        text("DELETE FROM api_endpoints WHERE name = :n"),
        {"n": name},
    )
    await db.commit()
    return bool(result.rowcount)


async def get_api_stats(
    db: AsyncSession, name: str, days: int = 7,
) -> dict[str, Any]:
    rows = await db.execute(
        text(
            """
            SELECT day, call_count, error_count, p50_ms, p95_ms, last_called_at
            FROM api_call_stats
            WHERE api_name = :n
              AND day >= (CURRENT_DATE - INTERVAL :days DAY)
            ORDER BY day DESC
            """
        ),
        {"n": name, "days": days},
    )
    series: list[dict[str, Any]] = []
    total_calls = 0
    total_errs = 0
    last_called: Any = None
    for r in rows:
        series.append(
            {
                "day": r[0].isoformat() if r[0] else None,
                "call_count": int(r[1] or 0),
                "error_count": int(r[2] or 0),
                "p50_ms": int(r[3]) if r[3] is not None else None,
                "p95_ms": int(r[4]) if r[4] is not None else None,
            }
        )
        total_calls += int(r[1] or 0)
        total_errs += int(r[2] or 0)
        if r[5] and (last_called is None or r[5] > last_called):
            last_called = r[5]
    return {
        "api_name": name,
        "days": days,
        "series": series,
        "total_calls": total_calls,
        "total_errors": total_errs,
        "error_rate": (total_errs / total_calls) if total_calls else 0.0,
        "last_called_at": _iso(last_called),
    }


async def record_api_call(
    db: AsyncSession,
    *,
    api_name: str,
    duration_ms: int,
    success: bool,
) -> None:
    """Idempotent daily roll-up upsert, called from tool_api_fetch."""
    await db.execute(
        text(
            """
            INSERT INTO api_call_stats (api_name, day, call_count, error_count,
                                        p50_ms, p95_ms, last_called_at)
            VALUES (:n, CURRENT_DATE, 1, :err, :ms, :ms, NOW())
            ON DUPLICATE KEY UPDATE
                call_count = call_count + 1,
                error_count = error_count + :err,
                -- rough running proxies for p50/p95: keep min/max so the
                -- admin UI has something to chart (exact quantiles need a
                -- histogram table, out of scope).
                p50_ms = LEAST(COALESCE(p50_ms, :ms), :ms),
                p95_ms = GREATEST(COALESCE(p95_ms, :ms), :ms),
                last_called_at = NOW()
            """
        ),
        {"n": api_name, "err": 0 if success else 1, "ms": int(duration_ms)},
    )
    await db.commit()


# ── domains ───────────────────────────────────────────────────

async def list_domains(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            """
            SELECT d.code, d.name, d.description, d.color, d.top_tags, d.updated_at,
                   (SELECT COUNT(*) FROM api_endpoints e WHERE e.domain = d.code) AS api_count,
                   (SELECT COUNT(*) FROM employees emp
                     WHERE JSON_CONTAINS(emp.domains, JSON_QUOTE(d.code))) AS employee_count
            FROM domains d ORDER BY d.code
            """
        )
    )
    out = []
    for r in rows:
        out.append(
            {
                "code": r[0],
                "name": r[1],
                "description": r[2],
                "color": r[3],
                "top_tags": _json_field(r[4]),
                "updated_at": _iso(r[5]),
                "api_count": int(r[6] or 0),
                "employee_count": int(r[7] or 0),
            }
        )
    return out


async def upsert_domain(
    db: AsyncSession,
    *,
    code: str,
    name: str,
    description: str | None = None,
    color: str | None = None,
    top_tags: list[str] | None = None,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO domains (code, name, description, color, top_tags)
            VALUES (:c, :n, :d, :col, :t)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                description = VALUES(description),
                color = VALUES(color),
                top_tags = VALUES(top_tags),
                updated_at = NOW()
            """
        ),
        {
            "c": code,
            "n": name,
            "d": description,
            "col": color,
            "t": json.dumps(top_tags or [], ensure_ascii=False),
        },
    )
    await db.commit()


# ── audit_logs ─────────────────────────────────────────────────

async def append_audit(
    db: AsyncSession,
    *,
    action: str,
    resource_type: str | None = None,
    resource_id: str | None = None,
    actor_id: str | None = None,
    actor_type: str = "user",
    result: str = "success",
    duration_ms: int | None = None,
    diff: dict[str, Any] | None = None,
    ip: str | None = None,
) -> int:
    r = await db.execute(
        text(
            """
            INSERT INTO audit_logs
                (actor_id, actor_type, action, resource_type, resource_id,
                 result, duration_ms, diff, ip)
            VALUES
                (:aid, :atype, :action, :rtype, :rid, :res, :dur, :diff, :ip)
            """
        ),
        {
            "aid": actor_id,
            "atype": actor_type,
            "action": action,
            "rtype": resource_type,
            "rid": resource_id,
            "res": result,
            "dur": duration_ms,
            "diff": json.dumps(diff, ensure_ascii=False, default=str) if diff else None,
            "ip": ip,
        },
    )
    await db.commit()
    return int(r.lastrowid or 0)


async def list_audit(
    db: AsyncSession,
    *,
    resource_type: Optional[str] = None,
    actor_id: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    where = ["1 = 1"]
    params: dict[str, Any] = {"lim": limit, "off": offset}
    if resource_type:
        where.append("resource_type = :rt")
        params["rt"] = resource_type
    if actor_id:
        where.append("actor_id = :aid")
        params["aid"] = actor_id
    sql = (
        "SELECT id, ts, actor_id, actor_type, action, resource_type, "
        "resource_id, result, duration_ms, diff, ip "
        "FROM audit_logs WHERE " + " AND ".join(where) +
        " ORDER BY ts DESC LIMIT :lim OFFSET :off"
    )
    rows = await db.execute(text(sql), params)
    out = []
    for r in rows:
        out.append(
            {
                "id": int(r[0]),
                "ts": _iso(r[1]),
                "actor_id": r[2],
                "actor_type": r[3],
                "action": r[4],
                "resource_type": r[5],
                "resource_id": r[6],
                "result": r[7],
                "duration_ms": int(r[8]) if r[8] is not None else None,
                "diff": _json_field(r[9]),
                "ip": r[10],
            }
        )
    return out


# ── memory / preferences (read-only aggregate) ─────────────────

async def list_memory_entries(
    db: AsyncSession,
    *,
    user_id: Optional[str] = None,
    limit: int = 100,
) -> dict[str, list[dict[str, Any]]]:
    """Aggregate `user_preferences. + .analysis_templates. + .tool_notes.
    into a single read-only view."""
    where = "" if user_id is None else "WHERE user_id = :uid"
    params: dict[str, Any] = {"lim": limit}
    if user_id is not None:
        params["uid"] = user_id

    prefs = await db.execute(
        text(
            f"SELECT id, user_id, `key`, value, updated_at "
            f"FROM user_preferences {where} ORDER BY updated_at DESC LIMIT :lim"
        ),
        params,
    )
    templates = await db.execute(
        text(
            f"SELECT template_id, user_id, name, domain, output_complexity, "
            f"usage_count, last_used FROM analysis_templates {where} "
            f"ORDER BY last_used DESC LIMIT :lim"
        ),
        params,
    )
    notes = await db.execute(
        text(
            f"SELECT id, tool_id, user_id, notes, performance_score, updated_at "
            f"FROM tool_notes {where} ORDER BY updated_at DESC LIMIT :lim"
        ),
        params,
    )

    return {
        "preferences": [
            {
                "id": p[0],
                "user_id": p[1],
                "key": p[2],
                "value": _json_field(p[3]),
                "updated_at": _iso(p[4]),
            }
            for p in prefs
        ],
        "templates": [
            {
                "template_id": t[0],
                "user_id": t[1],
                "name": t[2],
                "domain": t[3],
                "output_complexity": t[4],
                "usage_count": int(t[5] or 0),
                "last_used": _iso(t[6]),
            }
            for t in templates
        ],
        "tool_notes": [
            {
                "id": n[0],
                "tool_id": n[1],
                "user_id": n[2],
                "notes": n[3],
                "performance_score": float(n[4]) if n[4] is not None else None,
                "updated_at": _iso(n[5]),
            }
            for n in notes
        ],
    }


async def delete_memory_entry(
    db: AsyncSession, kind: str, entry_id: str,
) -> bool:
    """kind: 'preference' | 'template' | 'tool_note'"""
    table_pk = {
        "preference": ("user_preferences", "id"),
        "template": ("analysis_templates", "template_id"),
        "tool_note": ("tool_notes", "id"),
    }.get(kind)
    if not table_pk:
        return False
    tbl, pk = table_pk
    r = await db.execute(
        text(f"DELETE FROM {tbl} WHERE {pk} = :k"),
        {"k": entry_id},
    )
    await db.commit()
    return bool(r.rowcount)


# ── tools (renamed from skills) ───────────────────────────────

def _tool_row(r: Any) -> dict[str, Any]:
    return {
        "tool_id": r[0],
        "name": r[1],
        "kind": r[2],
        "description": r[3],
        "input_spec": r[4],
        "output_spec": r[5],
        "domains": _json_field(r[6]),
        "enabled": bool(r[7]),
        "run_count": int(r[8] or 0),
        "error_count": int(r[9] or 0),
        "avg_latency_ms": int(r[10]) if r[10] is not None else None,
        "last_error_at": _iso(r[11]),
        "last_error_msg": r[12],
        "updated_at": _iso(r[13]),
    }


async def list_tools(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT tool_id, name, kind, description, input_spec, output_spec, "
            "domains, enabled, run_count, error_count, avg_latency_ms, "
            "last_error_at, last_error_msg, updated_at FROM tools "
            "ORDER BY kind, tool_id"
        )
    )
    return [_tool_row(r) for r in rows]


async def get_tool(db: AsyncSession, tool_id: str) -> Optional[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT tool_id, name, kind, description, input_spec, output_spec, "
            "domains, enabled, run_count, error_count, avg_latency_ms, "
            "last_error_at, last_error_msg, updated_at FROM tools "
            "WHERE tool_id = :sid"
        ),
        {"sid": tool_id},
    )
    row = rows.first()
    if row is None:
        return None
    return _tool_row(row)


async def upsert_tool(
    db: AsyncSession,
    *,
    tool_id: str,
    name: str,
    kind: str,
    description: str | None = None,
    input_spec: str | None = None,
    output_spec: str | None = None,
    domains: list[str] | None = None,
    enabled: bool = True,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO tools
                (tool_id, name, kind, description, input_spec, output_spec,
                 domains, enabled)
            VALUES
                (:sid, :name, :kind, :desc, :ins, :outs, :doms, :en)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                kind = VALUES(kind),
                description = VALUES(description),
                input_spec = VALUES(input_spec),
                output_spec = VALUES(output_spec),
                domains = VALUES(domains),
                enabled = VALUES(enabled),
                updated_at = NOW()
            """
        ),
        {
            "sid": tool_id,
            "name": name,
            "kind": kind,
            "desc": description,
            "ins": input_spec,
            "outs": output_spec,
            "doms": json.dumps(domains or [], ensure_ascii=False),
            "en": 1 if enabled else 0,
        },
    )
    await db.commit()


async def toggle_tool(
    db: AsyncSession, tool_id: str, enabled: bool,
) -> bool:
    result = await db.execute(
        text("UPDATE tools SET enabled = :en WHERE tool_id = :sid"),
        {"en": 1 if enabled else 0, "sid": tool_id},
    )
    await db.commit()
    return bool(result.rowcount)


async def record_tool_run(
    db: AsyncSession,
    *,
    tool_id: str,
    duration_ms: int,
    success: bool,
    error_message: str | None = None,
) -> None:
    await db.execute(
        text(
            """
            UPDATE tools SET
                run_count = run_count + 1,
                error_count = error_count + :err,
                avg_latency_ms = ROUND(
                    (COALESCE(avg_latency_ms, 0) * run_count + :ms) / (run_count + 1)
                ),
                last_error_at = CASE WHEN :err = 1 THEN NOW() ELSE last_error_at END,
                last_error_msg = CASE WHEN :err = 1 THEN :msg ELSE last_error_msg END
            WHERE tool_id = :sid
            """
        ),
        {
            "sid": tool_id,
            "err": 0 if success else 1,
            "ms": int(duration_ms),
            "msg": (error_message or "")[:500] if error_message else None,
        },
    )
    await db.commit()


# ── agent_skills ───────────────────────────────────────────────

async def list_agent_skills(db: AsyncSession) -> list[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT skill_id, name, description, author, version, tags, enabled, "
            "created_at, updated_at FROM agent_skills ORDER BY name"
        )
    )
    return [_agent_skill_row(r) for r in rows]


def _agent_skill_row(r: Any) -> dict[str, Any]:
    return {
        "skill_id": r[0],
        "name": r[1],
        "description": r[2],
        "author": r[3],
        "version": r[4],
        "tags": _json_field(r[5]),
        "enabled": bool(r[6]),
        "created_at": _iso(r[7]),
        "updated_at": _iso(r[8]),
    }


async def get_agent_skill(db: AsyncSession, skill_id: str) -> Optional[dict[str, Any]]:
    rows = await db.execute(
        text(
            "SELECT skill_id, name, description, content, author, version, tags, enabled, "
            "created_at, updated_at FROM agent_skills WHERE skill_id = :sid"
        ),
        {"sid": skill_id},
    )
    row = rows.first()
    if row is None:
        return None
    return {
        "skill_id": row[0],
        "name": row[1],
        "description": row[2],
        "content": row[3],
        "author": row[4],
        "version": row[5],
        "tags": _json_field(row[6]),
        "enabled": bool(row[7]),
        "created_at": _iso(row[8]),
        "updated_at": _iso(row[9]),
    }


async def upsert_agent_skill(
    db: AsyncSession,
    *,
    skill_id: str,
    name: str,
    description: str | None = None,
    content: str,
    author: str | None = None,
    version: str = "1.0",
    tags: list[str] | None = None,
    enabled: bool = True,
) -> None:
    await db.execute(
        text(
            """
            INSERT INTO agent_skills
                (skill_id, name, description, content, author, version, tags, enabled)
            VALUES
                (:sid, :name, :desc, :content, :author, :ver, :tags, :en)
            ON DUPLICATE KEY UPDATE
                name = VALUES(name),
                description = VALUES(description),
                content = VALUES(content),
                author = VALUES(author),
                version = VALUES(version),
                tags = VALUES(tags),
                enabled = VALUES(enabled),
                updated_at = NOW()
            """
        ),
        {
            "sid": skill_id,
            "name": name,
            "desc": description,
            "content": content,
            "author": author,
            "ver": version,
            "tags": json.dumps(tags or [], ensure_ascii=False),
            "en": 1 if enabled else 0,
        },
    )
    await db.commit()


async def delete_agent_skill(db: AsyncSession, skill_id: str) -> bool:
    result = await db.execute(
        text("DELETE FROM agent_skills WHERE skill_id = :sid"),
        {"sid": skill_id},
    )
    await db.commit()
    return bool(result.rowcount)


async def toggle_agent_skill(
    db: AsyncSession, skill_id: str, enabled: bool,
) -> bool:
    result = await db.execute(
        text("UPDATE agent_skills SET enabled = :en WHERE skill_id = :sid"),
        {"en": 1 if enabled else 0, "sid": skill_id},
    )
    await db.commit()
    return bool(result.rowcount)


async def list_enabled_agent_skills(db: AsyncSession) -> list[dict[str, Any]]:
    """Returns enabled agent skills with content — used by the planning layer."""
    rows = await db.execute(
        text(
            "SELECT skill_id, name, description, content FROM agent_skills "
            "WHERE enabled = 1 ORDER BY name"
        )
    )
    return [
        {"skill_id": r[0], "name": r[1], "description": r[2], "content": r[3]}
        for r in rows
    ]
