"""辽港数据期刊 PR-1 — 启动期健康检查。

提供字体自检和 pptxgenjs bridge 可用性探测，在 ``main.py`` 的
lifespan 启动阶段调用。缺失不阻断启动，仅输出 WARNING / CRITICAL 日志。
"""
from __future__ import annotations

import asyncio
import logging
import subprocess

logger = logging.getLogger("analytica.tools.health")


# ---------------------------------------------------------------------------
# 字体自检
# ---------------------------------------------------------------------------

_REQUIRED_FONTS = ("Noto Serif SC", "Noto Sans SC", "JetBrains Mono")


def check_fonts() -> list[str]:
    """返回缺失的关键字体名；缺失不阻断启动。"""
    try:
        result = subprocess.run(
            ["fc-list", ":lang=zh"], capture_output=True, text=True, timeout=10,
        )
        installed = result.stdout + result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        # fc-list 不可用（CI / 非 Linux 环境），跳过检查
        return []

    missing = []
    for name in _REQUIRED_FONTS:
        if name not in installed:
            missing.append(name)
    return missing


# ---------------------------------------------------------------------------
# pptxgenjs bridge 可用性探测
# ---------------------------------------------------------------------------

async def probe_pptxgenjs_bridge() -> bool:
    """检测 pptxgenjs Node bridge 是否可用。

    不可用时返回 False — 调用方应记录 CRITICAL 日志，
    PPTX 生成将被阻断（不降级为 PNG fallback）。
    """
    try:
        from backend.tools.report._pptxgen_builder import check_pptxgen_available

        # check_pptxgen_available 是同步的，放在线程池中执行以避免阻塞启动
        loop = asyncio.get_running_loop()
        available = await loop.run_in_executor(None, check_pptxgen_available)
        return available
    except Exception:
        logger.exception("pptxgenjs bridge probe threw")
        return False
