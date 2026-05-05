"""Node executor runtime — Python ↔ pptxgen_executor.js bridge.

PR-4: 辽港数据期刊 — slide dimensions now flow from theme to the
Node executor via CLI args.  Retry decorator applied for transient
bridge failures.
"""
from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

from backend.tools.report._pptxgen_builder import (
    _find_node,
    _find_pptxgenjs_root,
)
from backend.tools.report._retry_config import (
    RENDERER_BRIDGE_TIMEOUT_RETRY,
    renderer_retry,
)

logger = logging.getLogger("analytica.tools.pptxgen_runtime")


_EXECUTOR_JS_PATH = (
    Path(__file__).resolve().parent / "pptxgen_executor.js"
)


@renderer_retry(RENDERER_BRIDGE_TIMEOUT_RETRY, reraise=True)
def run_pptxgen_executor(
    commands_json: str,
    slide_width: float = 10.0,
    slide_height: float = 7.5,
    timeout: int = 90,
) -> bytes:
    """Run the Node executor with ``commands_json`` on stdin.

    ``slide_width`` / ``slide_height`` are passed as CLI args so the
    JS executor can set the pptxgenjs layout dimensions (PR-4: 16:9
    canvas for liangang-journal theme).

    Returns raw .pptx bytes.  Raises ``RuntimeError`` on failure.
    Retries up to 2× on transient bridge timeouts with exponential
    backoff (1 s → 4 s).
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
            [node, str(_EXECUTOR_JS_PATH),
             str(slide_width), str(slide_height)],
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
