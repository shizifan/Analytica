"""Seed ``api_endpoints`` and ``domains`` from ``data/api_registry.json``.

This is the single bridge from the factory-data JSON file into the
running database. Run it after ``alembic upgrade head`` on every fresh
deployment, and again whenever the JSON file changes (idempotent
UPSERT — running twice is safe).

After the first run, all subsequent endpoint/domain edits should go
through the admin console (which writes the DB directly and triggers
``api_registry.reload_from_db`` so the runtime sees the change). The
JSON file is the *initial* dataset, not the long-term source of truth.

Run::

    python -m tools.seed_api_endpoints                 # full sync
    python -m tools.seed_api_endpoints --dry-run       # report only
    python -m tools.seed_api_endpoints --json data/foo # custom source

Exit codes: 0 OK, 1 source missing or invalid.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.config import get_settings
from backend.memory import admin_store

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = REPO_ROOT / "data" / "api_registry.json"
DEFAULT_TOKEN_JSON = REPO_ROOT / "data" / "api_tokens.json"


def _endpoint_to_upsert_kwargs(ep: dict[str, Any]) -> dict[str, Any]:
    """Map JSON endpoint shape → ``admin_store.upsert_api_endpoint`` kwargs.

    Field names diverge between the dataclass / JSON shape and DB columns
    (``required`` vs ``required_params``, ``time`` vs ``time_type``);
    this helper bridges both shapes in one place.
    """
    return {
        "name": ep["name"],
        "method": ep.get("method", "GET"),
        "path": ep["path"],
        "domain": ep["domain"],
        "intent": ep.get("intent") or None,
        "time_type": ep.get("time") or None,
        "granularity": ep.get("granularity") or None,
        "tags": list(ep.get("tags") or []),
        "required_params": list(ep.get("required") or []),
        "optional_params": list(ep.get("optional") or []),
        "returns": ep.get("returns") or None,
        "param_note": ep.get("param_note") or None,
        "disambiguate": ep.get("disambiguate") or None,
        # ``source`` here is the data-source label (mock/prod). UPSERT
        # keeps existing value unchanged on subsequent runs; default for
        # first seed is "mock".
        "source": "mock",
        "enabled": True,
        "field_schema": [list(row) for row in (ep.get("field_schema") or [])],
        "use_cases": list(ep.get("use_cases") or []),
        "chain_with": list(ep.get("chain_with") or []),
        "analysis_note": ep.get("analysis_note") or None,
    }


def _domain_to_upsert_kwargs(dom: dict[str, Any]) -> dict[str, Any]:
    """Map JSON domain shape → ``admin_store.upsert_domain`` kwargs.

    ``api_count`` is omitted: it's a SUM-computed column in
    ``list_domains`` (not stored). ``color`` defaults to None — the
    admin UI can set it later.
    """
    return {
        "code": dom["code"],
        "name": dom["name"],
        "description": dom.get("desc") or None,
        "color": dom.get("color") or None,
        "top_tags": list(dom.get("top_tags") or []),
    }


async def _seed(json_path: Path, dry_run: bool) -> tuple[int, int, int, int]:
    """Returns (planned_endpoints, applied_endpoints, planned_domains, applied_domains)."""
    with open(json_path, encoding="utf-8") as f:
        payload = json.load(f)
    endpoints = payload.get("endpoints") or []
    domains_raw = payload.get("domains") or {}
    # Domains are stored as a dict keyed by code in the JSON — flatten to a list
    # for uniform iteration.
    domains = list(domains_raw.values()) if isinstance(domains_raw, dict) else list(domains_raw)

    if not endpoints:
        print(f"[error] {json_path} has no endpoints", file=sys.stderr)
        return 0, 0, 0, 0
    if not domains:
        print(f"[error] {json_path} has no domains", file=sys.stderr)
        return len(endpoints), 0, 0, 0

    if dry_run:
        return len(endpoints), 0, len(domains), 0

    # Load tokens (file is gitignored, may not exist).
    token_map: dict[str, str] = {}
    if DEFAULT_TOKEN_JSON.exists():
        with open(DEFAULT_TOKEN_JSON, encoding="utf-8") as tf:
            token_map = json.load(tf)
    else:
        print(f"[warn] {DEFAULT_TOKEN_JSON.name} not found, endpoints will have no tokens", file=sys.stderr)

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    applied_eps = 0
    applied_doms = 0
    try:
        async with Session() as session:
            # Seed domains first — endpoints reference domain codes.
            for dom in domains:
                await admin_store.upsert_domain(
                    session, **_domain_to_upsert_kwargs(dom),
                )
                applied_doms += 1
            for ep in endpoints:
                kwargs = _endpoint_to_upsert_kwargs(ep)
                # Inject token from api_tokens.json if available.
                token = token_map.get(ep["path"], "")
                if token:
                    kwargs["api_token"] = token
                await admin_store.upsert_api_endpoint(
                    session, **kwargs,
                )
                applied_eps += 1
    finally:
        await engine.dispose()
    return len(endpoints), applied_eps, len(domains), applied_doms


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--json", type=Path, default=DEFAULT_JSON,
        help=f"Source JSON path (default: {DEFAULT_JSON.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Report what would happen without writing to DB.",
    )
    args = parser.parse_args(argv)

    if not args.json.exists():
        print(f"[error] {args.json} does not exist", file=sys.stderr)
        return 1

    planned_e, applied_e, planned_d, applied_d = asyncio.run(_seed(args.json, args.dry_run))
    if planned_e == 0 or planned_d == 0:
        return 1
    if args.dry_run:
        print(
            f"[dry-run] would upsert {planned_d} domains + {planned_e} endpoints from {args.json}"
        )
    else:
        print(
            f"[ok] upserted {applied_d}/{planned_d} domains + "
            f"{applied_e}/{planned_e} endpoints from {args.json}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
