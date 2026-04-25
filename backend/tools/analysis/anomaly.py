"""Anomaly Detection Skill — identifies anomalies in time series (stub implementation)."""
from __future__ import annotations

from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool


@register_tool("tool_anomaly", ToolCategory.ANALYSIS, "异常值检测",
                input_spec="数据序列 data_ref",
                output_spec="异常点及原因推测 JSON")
class AnomalyDetectionTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        return ToolOutput(
            tool_id=self.tool_id,
            status="partial",
            output_type="json",
            data={"anomalies": [], "method": "stub", "note": "异常检测功能尚未完整实现"},
            metadata={"stub": True},
        )
