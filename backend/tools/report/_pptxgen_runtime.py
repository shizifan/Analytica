"""Node executor runtime — Python ↔ pptxgen_executor.js bridge.

Concrete subprocess invocation lands in Step 0.3 alongside the
``pptxgen_executor.js`` long-lived script. Step 0.2 only stubs the
contract so ``PptxGenJSBlockRenderer`` can compile and be unit-tested
with mocks.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path

from backend.tools.report._pptxgen_builder import (
    _find_node,
    _find_pptxgenjs_root,
)

logger = logging.getLogger("analytica.tools.pptxgen_runtime")


_EXECUTOR_JS_PATH = (
    Path(__file__).resolve().parent / "pptxgen_executor.js"
)


def run_pptxgen_executor(commands_json: str, timeout: int = 90) -> bytes:
    """Run the long-lived Node executor with ``commands_json`` on stdin.

    Returns the raw .pptx bytes from stdout. Raises ``RuntimeError`` on
    any failure mode (missing node, missing pptxgenjs, executor error,
    timeout). Callers (currently ``PptxGenJSBlockRenderer.end_document``)
    catch and fall back to ``PptxBlockRenderer`` (python-pptx).
    """
    if not _EXECUTOR_JS_PATH.exists():
        raise RuntimeError(
            f"pptxgen_executor.js not found at {_EXECUTOR_JS_PATH}"
        )

    node = _find_node()
    if not node:
        raise RuntimeError("node executable not found on PATH")

    env = dict(os.environ)
    root = _find_pptxgenjs_root()
    if root:
        env["NODE_PATH"] = root + os.pathsep + env.get("NODE_PATH", "")

    try:
        result = subprocess.run(
            [node, str(_EXECUTOR_JS_PATH)],
            input=commands_json.encode("utf-8"),
            capture_output=True,
            timeout=timeout,
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"pptxgen_executor timed out after {timeout}s"
        ) from e
    except FileNotFoundError as e:
        raise RuntimeError(f"failed to launch node: {e}") from e

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace")
        raise RuntimeError(
            f"pptxgen_executor exited {result.returncode}: {stderr[:500]}"
        )

    if not result.stdout:
        raise RuntimeError("pptxgen_executor produced empty stdout")

    return result.stdout
