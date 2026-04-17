"""Prediction Skill — time series forecasting (stub implementation)."""
from __future__ import annotations

from typing import Any

from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill


@register_skill("skill_prediction", SkillCategory.ANALYSIS, "预测分析（基于历史趋势外推）",
                input_spec="历史数据 data_ref",
                output_spec="预测值 + 置信区间 JSON")
class PredictionSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        return SkillOutput(
            skill_id=self.skill_id,
            status="partial",
            output_type="json",
            data={"prediction": [], "method": "stub", "note": "预测功能尚未完整实现"},
            metadata={"stub": True},
        )
