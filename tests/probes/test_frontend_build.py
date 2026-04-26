"""Frontend TypeScript compile probe.

Subprocess check: `npx tsc --noEmit` must exit 0. Catches type drift after
backend schema changes (e.g. renaming a field that the frontend reads).

Skipped if `frontend/` or npm not present.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.probe

REPO = Path(__file__).resolve().parent.parent.parent
FRONTEND = REPO / "frontend"


def test_typescript_compiles():
    if not FRONTEND.exists():
        pytest.skip("frontend/ not present")
    if not shutil.which("npx"):
        pytest.skip("npx not on PATH")

    result = subprocess.run(
        ["npx", "tsc", "--noEmit", "-p", "tsconfig.app.json"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if result.returncode != 0:
        pytest.fail(
            "TypeScript compilation failed:\n"
            f"stdout: {result.stdout[-2000:]}\n"
            f"stderr: {result.stderr[-2000:]}"
        )
