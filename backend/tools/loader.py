"""工具自动发现加载器。

扫描 backend/tools/ 下所有子目录，自动导入包含 @register_tool 的模块。
也支持从外部路径加载扩展工具。
"""
from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path

import backend.tools as _tools_pkg

logger = logging.getLogger("analytica.tools.loader")

_SCAN_SUB_PACKAGES = ("data", "analysis", "visualization", "report")


def load_all_tools() -> int:
    """自动扫描并导入所有工具模块，返回已加载模块数。"""
    loaded = 0
    package_path = Path(_tools_pkg.__file__).parent
    for sub_pkg in _SCAN_SUB_PACKAGES:
        sub_path = package_path / sub_pkg
        if not sub_path.is_dir():
            continue
        for module_info in pkgutil.iter_modules([str(sub_path)]):
            module_name = f"backend.tools.{sub_pkg}.{module_info.name}"
            try:
                importlib.import_module(module_name)
                loaded += 1
            except Exception:
                logger.exception("Failed to load tool module: %s", module_name)
    logger.info("Loaded %d tool modules from %d sub-packages", loaded, len(_SCAN_SUB_PACKAGES))
    return loaded


def load_extra_tools(module_paths: list[str]) -> int:
    """从外部模块路径加载扩展工具，返回已加载数。"""
    loaded = 0
    for p in module_paths:
        try:
            importlib.import_module(p)
            loaded += 1
        except Exception:
            logger.exception("Failed to load extra tool module: %s", p)
    return loaded
