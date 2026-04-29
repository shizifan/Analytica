"""One-shot exporter: backend.agent.api_registry → data/api_registry.json.

P2.1 of the API-registry migration plan: produce a JSON intermediate from the
hardcoded ``ALL_ENDPOINTS`` tuple, so the registry can be loaded from a file
(P2.2 dual-source) and ultimately from the DB (P2.4).

The serialize/deserialize logic lives in ``backend.agent.api_registry`` (so
the runtime loader and this tool agree on the on-disk shape). This script is
just a CLI wrapper.

Run::

    python -m tools.export_api_registry           # writes data/api_registry.json
    python -m tools.export_api_registry --check   # exit 1 if file is stale
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from backend.agent.api_registry import serialize_to_dict

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "data" / "api_registry.json"


def write_json(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--output", "-o", type=Path, default=DEFAULT_OUTPUT,
        help=f"Output JSON path (default: {DEFAULT_OUTPUT.relative_to(REPO_ROOT)})",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Exit 1 if the output file is missing or stale (does not write).",
    )
    args = parser.parse_args(argv)

    payload = serialize_to_dict()

    if args.check:
        if not args.output.exists():
            print(f"[stale] {args.output} does not exist", file=sys.stderr)
            return 1
        with open(args.output, encoding="utf-8") as f:
            current = json.load(f)
        if current != payload:
            print(f"[stale] {args.output} differs from current ALL_ENDPOINTS", file=sys.stderr)
            return 1
        print(f"[ok] {args.output} is up to date")
        return 0

    write_json(payload, args.output)
    print(
        f"[wrote] {args.output.relative_to(REPO_ROOT)} "
        f"({len(payload['endpoints'])} endpoints, {len(payload['domains'])} domains)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
