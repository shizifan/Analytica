"""Seed admin tables from the code-native registries.

Populates:
  - api_endpoints  ← backend/agent/api_registry.ALL_ENDPOINTS
  - skills         ← SkillRegistry singleton
  - domains        ← DOMAIN_INDEX

Idempotent — upserts by primary key. Run once per schema change:
    uv run python -m migrations.scripts.seed_admin_tables
"""
from __future__ import annotations

import asyncio
import logging

from backend.agent import api_registry
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


# Gentle brand palette — maps a domain code to an accent color chip.
DOMAIN_COLORS: dict[str, str] = {
    "D1": "oklch(0.70 0.12 220)",
    "D2": "oklch(0.70 0.13 160)",
    "D3": "oklch(0.70 0.15 25)",
    "D4": "oklch(0.72 0.13 300)",
    "D5": "oklch(0.70 0.12 55)",
    "D6": "oklch(0.70 0.14 195)",
    "D7": "oklch(0.68 0.12 350)",
}


async def _seed_api_endpoints(db) -> int:
    count = 0
    for ep in api_registry.ALL_ENDPOINTS:
        await admin_store.upsert_api_endpoint(
            db,
            name=ep.name,
            method=getattr(ep, "method", "GET") or "GET",
            path=ep.path,
            domain=ep.domain,
            intent=ep.intent,
            time_type=ep.time,
            granularity=ep.granularity,
            tags=list(ep.tags or ()),
            required_params=list(ep.required or ()),
            optional_params=list(ep.optional or ()),
            returns=ep.returns,
            param_note=ep.param_note,
            disambiguate=ep.disambiguate,
            source="mock",
            enabled=True,
        )
        count += 1
    return count


async def _seed_skills(db) -> int:
    from backend.skills.loader import load_all_skills
    from backend.skills.registry import SkillRegistry

    load_all_skills()
    registry = SkillRegistry.get_instance()
    count = 0
    for skill in registry._skills.values():
        category_name = (
            skill.category.name
            if hasattr(skill.category, "name")
            else str(skill.category)
        )
        kind = SKILL_KIND_BY_CATEGORY.get(category_name, category_name.lower())
        await admin_store.upsert_skill(
            db,
            skill_id=skill.skill_id,
            name=getattr(skill, "name", None) or skill.skill_id,
            kind=kind,
            description=getattr(skill, "description", None),
            input_spec=getattr(skill, "input_spec", None),
            output_spec=getattr(skill, "output_spec", None),
            domains=list(getattr(skill, "domains", None) or []),
            enabled=True,
        )
        count += 1
    return count


async def _seed_domains(db) -> int:
    count = 0
    for code, info in api_registry.DOMAIN_INDEX.items():
        await admin_store.upsert_domain(
            db,
            code=code,
            name=info.name,
            description=info.desc,
            color=DOMAIN_COLORS.get(code),
            top_tags=list(info.top_tags or ()),
        )
        count += 1
    return count


async def main() -> int:
    factory = get_session_factory()
    async with factory() as db:
        n_apis = await _seed_api_endpoints(db)
        log.info("api_endpoints: %d rows upserted", n_apis)
        n_skills = await _seed_skills(db)
        log.info("skills: %d rows upserted", n_skills)
        n_dom = await _seed_domains(db)
        log.info("domains: %d rows upserted", n_dom)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(asyncio.run(main()))
