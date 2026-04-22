"""Seed the employees table from `employees/*.yaml` + the frontend FAQ file.

Usage::

    uv run python -m migrations.scripts.seed_employees_from_yaml            # idempotent
    uv run python -m migrations.scripts.seed_employees_from_yaml --force    # overwrite existing rows
    uv run python -m migrations.scripts.seed_employees_from_yaml --dry-run  # preview

The seed stamps an initial version snapshot (v = each YAML's `version`
field, default "1.0") into `employee_versions` so the admin drawer has
a baseline to diff against going forward.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from backend.database import get_session_factory
from backend.memory import employee_store

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
YAML_DIR = REPO_ROOT / "employees"
FAQ_TS_PATH = REPO_ROOT / "frontend" / "src" / "data" / "employeeFaq.ts"

logger = logging.getLogger("seed.employees")


# Curated distinctive initials — avoids "生产" vs "生产运营专家" duplication.
# Fall back to a more generic heuristic for employees we don't know about.
_CURATED_INITIALS: dict[str, str] = {
    "throughput_analyst": "吞吐",
    "customer_insight": "客户",
    "asset_investment": "资产",
}


def _initials_from_name(employee_id: str, name: str) -> str:
    """Pick a 2-char display label.

    Prefers a curated table (for seeded demo employees where first-2-chars
    would duplicate the domain word), then falls back to CJK/Latin
    heuristics for admin-created rows.
    """
    if employee_id in _CURATED_INITIALS:
        return _CURATED_INITIALS[employee_id]
    stripped = (name or "").strip()
    if not stripped:
        return "AN"
    cjk_matches = re.findall(r"[\u4e00-\u9fff]", stripped)
    if cjk_matches:
        return "".join(cjk_matches[:2])
    tokens = re.findall(r"[A-Za-z]+", stripped)
    if tokens:
        return "".join(t[0].upper() for t in tokens[:2]) or stripped[:2].upper()
    return stripped[:2].upper()


def _parse_faqs_ts(ts_path: Path) -> dict[str, list[dict[str, Any]]]:
    """Parse `employeeFaq.ts` into `{employee_id: [{id, question}, ...]}`.

    The TS module is hand-written JS-like literals; rather than wire a
    JS parser we do a focused regex pass. If a future redesign moves FAQ
    authoring to YAML or admin UI, this can be dropped.
    """
    if not ts_path.exists():
        return {}

    src = ts_path.read_text(encoding="utf-8")

    # Match: `const <name>FAQs: EmployeeFAQ = { employee_id: '<id>', faqs: [ ... ] };`
    out: dict[str, list[dict[str, Any]]] = {}
    blocks = re.finditer(
        r"employee_id:\s*'([^']+)'\s*,\s*faqs:\s*\[(.*?)\],?\s*\};",
        src,
        re.DOTALL,
    )
    for m in blocks:
        emp_id = m.group(1)
        body = m.group(2)
        items: list[dict[str, Any]] = []
        for item in re.finditer(
            r"\{\s*id:\s*'([^']+)'\s*,\s*question:\s*'([^']*)'\s*,?\s*\}",
            body,
        ):
            items.append({"id": item.group(1), "question": item.group(2)})
        out[emp_id] = items
    return out


def _profile_dict_from_yaml(path: Path) -> dict[str, Any]:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not contain a YAML mapping")
    return data


def _build_row(
    yaml_data: dict[str, Any], faqs: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "employee_id": yaml_data["employee_id"],
        "name": yaml_data["name"],
        "description": yaml_data.get("description") or "",
        "version": str(yaml_data.get("version", "1.0")),
        "initials": _initials_from_name(yaml_data["employee_id"], yaml_data["name"]),
        "status": "active",
        "domains": yaml_data.get("domains") or [],
        "endpoints": yaml_data.get("endpoints") or [],
        "skills": yaml_data.get("skills") or [],
        "faqs": faqs,
        "perception": yaml_data.get("perception"),
        "planning": yaml_data.get("planning"),
    }


async def run(force: bool = False, dry_run: bool = False) -> int:
    if not YAML_DIR.exists():
        logger.error("YAML dir not found: %s", YAML_DIR)
        return 1

    faq_map = _parse_faqs_ts(FAQ_TS_PATH)
    yaml_files = sorted(YAML_DIR.glob("*.yaml"))
    if not yaml_files:
        logger.error("No YAML files under %s", YAML_DIR)
        return 1

    factory = get_session_factory()
    total = 0
    skipped = 0

    async with factory() as db:
        for path in yaml_files:
            data = _profile_dict_from_yaml(path)
            emp_id = data["employee_id"]
            faqs = faq_map.get(emp_id, [])
            row = _build_row(data, faqs)

            existing = await employee_store.get_employee(db, emp_id)
            if existing and not force:
                logger.info("skip existing %s (use --force to overwrite)", emp_id)
                skipped += 1
                continue

            if dry_run:
                print(f"[dry-run] would upsert {emp_id} (faqs={len(faqs)})")
                total += 1
                continue

            await employee_store.upsert_employee(db, **row)
            await employee_store.create_version_snapshot(
                db,
                employee_id=emp_id,
                version=row["version"],
                snapshot=row,
                note="Seeded from employees/*.yaml",
            )
            logger.info("upserted %s (v%s, %d faqs)", emp_id, row["version"], len(faqs))
            total += 1

    print(
        f"Done. {'simulated ' if dry_run else ''}{total} upserted, "
        f"{skipped} skipped."
    )
    return 0


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="Overwrite existing rows")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    return asyncio.run(run(force=args.force, dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
