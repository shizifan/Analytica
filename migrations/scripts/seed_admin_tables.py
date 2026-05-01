"""Seed the ``tools`` table from the in-process ToolRegistry.

API endpoints and domains used to be seeded here from
``backend/agent/api_registry.py`` inline data, but that data has moved
to ``data/api_registry.json``. Run ``python -m tools.seed_api_endpoints``
for the API registry; this script only handles the tools table now.

Idempotent — upserts by primary key. Run once per schema change:

    uv run python -m migrations.scripts.seed_admin_tables
"""
from __future__ import annotations

import asyncio
import logging

from backend.database import get_session_factory
from backend.memory import admin_store


logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger("seed_admin")


SKILL_KIND_BY_CATEGORY: dict[str, str] = {
    "DATA_FETCH": "data_fetch",
    "ANALYSIS": "analysis",
    "VISUALIZATION": "visualization",
    "REPORT": "report",
    "SEARCH": "search",
}


async def _seed_tools(db) -> int:
    from backend.tools.loader import load_all_tools
    from backend.tools.registry import ToolRegistry

    load_all_tools()
    registry = ToolRegistry.get_instance()
    count = 0
    for tool in registry._tools.values():
        category_name = (
            tool.category.name
            if hasattr(tool.category, "name")
            else str(tool.category)
        )
        kind = SKILL_KIND_BY_CATEGORY.get(category_name, category_name.lower())
        await admin_store.upsert_tool(
            db,
            tool_id=tool.tool_id,
            name=getattr(tool, "name", None) or tool.tool_id,
            kind=kind,
            description=getattr(tool, "description", None),
            input_spec=getattr(tool, "input_spec", None),
            output_spec=getattr(tool, "output_spec", None),
            domains=list(getattr(tool, "domains", None) or []),
            enabled=True,
        )
        count += 1
    return count


async def main() -> int:
    factory = get_session_factory()
    async with factory() as db:
        n_tools = await _seed_tools(db)
        log.info("tools: %d rows upserted", n_tools)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
