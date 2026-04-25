"""Prediction Skill — time series forecasting (stub implementation)."""
from __future__ import annotations

from typing import Any

from backend.tools.base import BaseTool, ToolCategory, ToolInput, ToolOutput
from backend.tools.registry import register_tool


@register_tool("tool_prediction", ToolCategory.ANALYSIS, "预测分析（基于历史趋势外推）",
                input_spec="历史数据 data_ref",
                output_spec="预测值 + 置信区间 JSON")
class PredictionTool(BaseTool):

    async def execute(self, inp: ToolInput, context: dict[str, Any]) -> ToolOutput:
        return ToolOutput(
            tool_id=self.tool_id,
            status="partial",
            output_type="json",
            data={"prediction": [], "method": "stub", "note": "预测功能尚未完整实现"},
            metadata={"stub": True},
        )
