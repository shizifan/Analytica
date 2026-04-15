"""Skill Registry — 技能注册中心。

提供所有可用技能的描述，供规划层 Prompt 注入。
"""
from __future__ import annotations

SKILL_REGISTRY: dict[str, dict] = {
    "skill_api_fetch": {
        "description": "调用数据源 API 获取原始数据",
        "input": "endpoint_id + 查询参数",
        "output": "JSON 数据",
    },
    "skill_web_search": {
        "description": "外部信息检索（暂未启用）",
        "input": "搜索关键词",
        "output": "搜索结果摘要",
    },
    "skill_file_parse": {
        "description": "解析用户上传的文件（Excel/CSV/PDF）",
        "input": "文件路径",
        "output": "结构化数据",
    },
    "skill_descriptive_analysis": {
        "description": "描述性统计分析（均值、同比、环比、占比）",
        "input": "数据集 + 维度",
        "output": "统计摘要 JSON",
    },
    "skill_attribution_analysis": {
        "description": "归因分析（变动因素拆解）",
        "input": "指标变动数据 + 维度",
        "output": "归因因素列表",
    },
    "skill_trend_analysis": {
        "description": "趋势分析（时间序列变化模式识别）",
        "input": "时间序列数据",
        "output": "趋势描述 + 拐点",
    },
    "skill_proportion_analysis": {
        "description": "占比结构分析",
        "input": "分类数据",
        "output": "占比排名",
    },
    "skill_comparison_analysis": {
        "description": "对比分析（同比/环比/跨区域）",
        "input": "多期/多维数据",
        "output": "对比结果",
    },
    "skill_anomaly_detection": {
        "description": "异常值检测",
        "input": "数据序列",
        "output": "异常点及原因推测",
    },
    "skill_forecast": {
        "description": "短期预测（基于历史趋势外推）",
        "input": "历史数据",
        "output": "预测值 + 置信区间",
    },
    "skill_narrative_generation": {
        "description": "文本叙述生成（分析结论的自然语言描述）",
        "input": "分析结果 JSON",
        "output": "中文分析叙述",
    },
    "skill_echarts_generation": {
        "description": "ECharts 图表生成",
        "input": "数据 + 图表类型",
        "output": "ECharts option JSON",
    },
    "skill_table_generation": {
        "description": "数据表格生成（Markdown / HTML）",
        "input": "表格数据",
        "output": "Markdown 表格",
    },
    "skill_pptx_generation": {
        "description": "PPT 报告生成",
        "input": "报告结构 + 数据 + 图表",
        "output": "PPTX 文件路径",
    },
    "skill_html_generation": {
        "description": "HTML 报告生成",
        "input": "报告结构 + 数据 + 图表",
        "output": "HTML 文件路径",
    },
}

VALID_SKILL_IDS = set(SKILL_REGISTRY.keys())


def get_skills_description() -> str:
    """Format skill registry for injection into planning prompt."""
    lines = []
    for skill_id, info in SKILL_REGISTRY.items():
        lines.append(f"- {skill_id}: {info['description']}")
        lines.append(f"  输入: {info['input']} → 输出: {info['output']}")
    return "\n".join(lines)


def is_valid_skill(skill_id: str) -> bool:
    """Check if a skill ID exists in the registry."""
    return skill_id in VALID_SKILL_IDS
