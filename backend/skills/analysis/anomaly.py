"""Anomaly Detection Skill — identifies anomalies in time series (stub implementation)."""
from __future__ import annotations

from typing import Any

from backend.skills.base import BaseSkill, SkillCategory, SkillInput, SkillOutput
from backend.skills.registry import register_skill


@register_skill("skill_anomaly", SkillCategory.ANALYSIS, "异常值检测",
                input_spec="数据序列 data_ref",
                output_spec="异常点及原因推测 JSON")
class AnomalyDetectionSkill(BaseSkill):

    async def execute(self, inp: SkillInput, context: dict[str, Any]) -> SkillOutput:
        return SkillOutput(
            skill_id=self.skill_id,
            status="partial",
            output_type="json",
            data={"anomalies": [], "method": "stub", "note": "异常检测功能尚未完整实现"},
            metadata={"stub": True},
        )
