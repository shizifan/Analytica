"""File Parse Skill — parses CSV, Excel (xlsx), and JSON files into DataFrame."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool

logger = logging.getLogger("analytica.tools.file_parse")


@register_tool("tool_file_parse", ToolCategory.DATA_FETCH, "解析文件（CSV/Excel/JSON）为 DataFrame",
                input_spec="文件路径 file_path",
                output_spec="DataFrame (结构化数据)")
class FileParseTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        file_path = inp.params.get("file_path", "")
        if not file_path:
            return self._fail("缺少 file_path 参数")

        p = Path(file_path)
        if not p.exists():
            return self._fail(f"文件不存在: {file_path}")

        try:
            suffix = p.suffix.lower()
            if suffix == ".csv":
                df = pd.read_csv(p)
            elif suffix in (".xlsx", ".xls"):
                df = pd.read_excel(p)
            elif suffix == ".json":
                with open(p, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    df = pd.DataFrame(data)
                elif isinstance(data, dict) and "data" in data:
                    df = pd.DataFrame(data["data"]) if isinstance(data["data"], list) else pd.DataFrame([data["data"]])
                else:
                    df = pd.DataFrame([data])
            else:
                return self._fail(f"不支持的文件格式: {suffix}")

            return ToolOutput(
                tool_id=self.tool_id,
                status="success",
                output_type="dataframe",
                data=df,
                metadata={
                    "columns": list(df.columns),
                    "dtypes": {c: str(dt) for c, dt in df.dtypes.items()},
                    "rows": len(df),
                },
            )
        except Exception as e:
            logger.exception("File parse error: %s", e)
            return self._fail(str(e))
