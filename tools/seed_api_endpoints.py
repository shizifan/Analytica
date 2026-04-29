"""Seed ``api_endpoints`` from ``data/api_registry.json``.

P2.4-4 of the API-registry → DB migration. Idempotent UPSERT (decision Q3):
running the script twice changes nothing on the second pass, and changes
to the JSON propagate row-by-row on subsequent runs.

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

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from backend.config import get_settings
from backend.memory import admin_store

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_JSON = REPO_ROOT / "data" / "api_registry.json"


def _endpoint_to_upsert_kwargs(ep: dict[str, Any]) -> dict[str, Any]:
    """Map JSON endpoint shape → ``admin_store.upsert_api_endpoint`` kwargs.

    The ApiEndpoint dataclass field names diverge from DB columns
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
        # ``source`` here is the data-source label (mock/prod), not the
        # registry-source mode. UPSERT keeps existing value unchanged on
        # subsequent runs; default for first seed is "mock".
        "source": "mock",
        "enabled": True,
        "field_schema": [list(row) for row in (ep.get("field_schema") or [])],
        "use_cases": list(ep.get("use_cases") or []),
        "chain_with": list(ep.get("chain_with") or []),
        "analysis_note": ep.get("analysis_note") or None,
    }


async def _seed(json_path: Path, dry_run: bool) -> tuple[int, int]:
    """Returns (planned_count, applied_count). In dry-run, applied=0."""
    with open(json_path, encoding="utf-8") as f:
        payload = json.load(f)
    endpoints = payload.get("endpoints") or []
    if not endpoints:
        print(f"[error] {json_path} has no endpoints", file=sys.stderr)
        return 0, 0

    if dry_run:
        return len(endpoints), 0

    settings = get_settings()
    engine = create_async_engine(settings.DATABASE_URL, future=True)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    applied = 0
    try:
        async with Session() as session:
            for ep in endpoints:
                await admin_store.upsert_api_endpoint(
                    session, **_endpoint_to_upsert_kwargs(ep),
                )
                applied += 1
    finally:
        await engine.dispose()
    return len(endpoints), applied


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

    planned, applied = asyncio.run(_seed(args.json, args.dry_run))
    if planned == 0:
        return 1
    if args.dry_run:
        print(f"[dry-run] would upsert {planned} endpoints from {args.json}")
    else:
        print(f"[ok] upserted {applied}/{planned} endpoints from {args.json}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
