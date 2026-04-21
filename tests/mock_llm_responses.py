"""LLM Mock 响应模块 — 为测试提供固化的 LLM 生成结果。

设计原则：
1. 基于 prompt 的 domain 特征返回不同领域的专业回复
2. 覆盖 descriptive / summary_gen / attribution 三个技能的调用场景
3. 返回结构与 invoke_llm 保持一致

运行：
    pytest tests/test_json_template_execution_by_mock_llm.py -v
"""
from __future__ import annotations

import hashlib
import re
from typing import Any


# ════════════════════════════════════════════════════════════════
# 固化响应库
# ════════════════════════════════════════════════════════════════

# 吞吐量领域（throughput）描述性分析回复
NARRATIVE_THROUGHPUT = """**吞吐量分析洞察**

2026年Q1，全港完成吞吐量约1.33亿吨，较去年同期增长约6.2%，整体完成率27.75%。其中：
- 大连港区贡献最大，占比约35%，完成率28.1%
- 营口港区占比约28%，完成率27.5%
- 丹东、盘锦港区保持稳定增长，同比增幅约5-7%

环比来看，3月份吞吐量环比增长约8.5%，主要受益于散杂货业务回升。集装箱业务保持良好势头，累计完成TEU同比增长约9.3%。

**关注事项**：部分港区散杂货完成率偏低，需关注后续产能调配。"""

# 客户领域（customer）描述性分析回复
NARRATIVE_CUSTOMER = """**客户战略贡献分析**

2026年Q1，集团战略客户整体贡献度保持稳定：
- TOP10战略客户吞吐量占比约65%，集中度较高
- 钢铁、煤炭类客户贡献同比增长约8.2%
- 集装箱航线客户货量稳步提升

客户结构方面，外贸集装箱业务占比约55%，内贸约45%。分货种看，铁矿石、煤炭、钢材三大货种合计占比约70%。

**关注事项**：部分战略客户应收款周期延长，需加强客户信用管理。"""

# 资产领域（asset）描述性分析回复
NARRATIVE_ASSET = """**资产投资分析**

2026年Q1，资产投资完成情况：
- 资本性投入完成率约22%，符合季节性规律
- 设备更新改造投入占比约35%
- 在建工程进度正常

资产运营效率方面，固定资产周转率同比提升约3.5%，主要受益于设备产能利用率提高。折旧结构保持合理，整体资产质量稳定。

**关注事项**：部分设备更新项目进度滞后，需加快招标采购流程。"""

# 通用领域（generic）描述性分析回复
NARRATIVE_GENERIC = """**数据分析洞察**

基于提供的统计数据，关键发现如下：
- 数据整体趋势平稳，未见明显异常波动
- 主要指标同比保持正增长
- 各维度分布较为均匀

建议后续持续关注数据变化趋势，及时发现潜在风险点。"""


# 归因分析 JSON 回复
ATTRIBUTION_RESULT = {
    "primary_drivers": [
        {
            "factor": "散杂货业务增长",
            "direction": "+",
            "estimated_impact": "约+3.5%",
            "evidence": "Q1散杂货吞吐量同比增长8.2%，是主要增长动力"
        },
        {
            "factor": "集装箱业务回升",
            "direction": "+",
            "estimated_impact": "约+2.1%",
            "evidence": "集装箱TEU同比增长9.3%，航线密度增加"
        }
    ],
    "secondary_factors": [
        {
            "factor": "季节性因素",
            "direction": "+",
            "estimated_impact": "约+0.8%",
            "evidence": "Q1为传统旺季，吞吐量通常较高"
        },
        {
            "factor": "区域协同效应",
            "direction": "+",
            "estimated_impact": "约+0.5%",
            "evidence": "大连、营口双核联动提升整体效率"
        }
    ],
    "uncertainty_note": "归因分析基于内部数据，未纳入外部市场因素（如竞争对手策略调整、国际贸易政策变化等），置信度约75%。",
    "narrative": "**吞吐量增长归因分析**\n\n主要驱动因素包括：一是散杂货业务强劲增长，贡献约3.5%的增量；二是集装箱业务稳步回升，贡献约2.1%的增量。\n\n次要因素方面，季节性因素和区域协同效应合计贡献约1.3%的增长。\n\n建议重点关注散杂货业务的市场拓展，同时关注集装箱航线优化。",
    "waterfall_data": [
        {"name": "基准值", "value": 100},
        {"name": "散杂货增长", "value": 3.5},
        {"name": "集装箱增长", "value": 2.1},
        {"name": "季节性因素", "value": 0.8},
        {"name": "区域协同", "value": 0.5},
        {"name": "其他因素", "value": -0.3},
        {"name": "汇总", "value": 106.6}
    ]
}


# 摘要生成回复（executive 风格）
SUMMARY_EXECUTIVE = """**2026年Q1经营摘要**

吞吐量完成1.33亿吨，完成年度目标27.75%，同比增长6.2%，整体进度符合预期。

核心数字：
- 全港吞吐量同比增长6.2%
- 集装箱TEU同比增长9.3%
- 战略客户贡献占比65%

最大风险：部分港区散杂货完成率偏低，后续产能调配压力大。

建议：
1. 加强散杂货市场开拓，提升货源组织效率
2. 优化集装箱干线布局，增加航线密度
3. 关注战略客户需求变化，巩固合作关系"""


# 摘要生成回复（analytical 风格）
SUMMARY_ANALYTICAL = """**深度分析摘要**

三个关键发现：

1. **业务结构优化**：集装箱业务占比提升至42%，较去年同期提高3个百分点，业务结构持续优化，高附加值货种占比增加。

2. **区域协同效应显现**：大连、营口双核联动效果显著，跨港区调箱效率提升约15%，整体运营成本下降约2%。

3. **客户集中度偏高**：TOP10客户贡献占比65%，存在一定依赖风险，建议加大中小客户开发力度。

驱动因素：受益于腹地经济复苏、港口集疏运体系完善、政策支持等因素，预计Q2将继续保持增长态势。"""


# 摘要生成回复（narrative 风格）
SUMMARY_NARRATIVE = """2026年第一季度，港口运营整体稳健。吞吐量稳步增长，业务结构持续优化，战略客户合作深化。各港区协同效应逐步显现，整体竞争力提升。展望未来，需持续关注市场变化，把握增长机遇。"""


# ════════════════════════════════════════════════════════════════
# Mock LLM 函数
# ════════════════════════════════════════════════════════════════

def mock_invoke_llm(
    user_prompt: str,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.3,
    timeout: int = 90,
    max_prompt_chars: int = 8000,
) -> dict[str, Any]:
    """Mock LLM 调用，返回固化的响应结果。

    根据 prompt 内容推断 domain 和调用场景，返回相应的固化回复。

    返回格式与 invoke_llm 保持一致：
    {
        "text": str,
        "tokens": {"prompt": int, "completion": int},
        "elapsed": float,
        "error_category": str | None,
        "error": str | None,
        "prompt_chars": int,
    }
    """
    import json

    prompt_lower = user_prompt.lower()
    system_lower = (system_prompt or "").lower()

    # 判断 domain
    domain = "generic"
    if any(kw in prompt_lower for kw in ["throughput", "吞吐", "港区", "港口"]):
        domain = "throughput"
    elif any(kw in prompt_lower for kw in ["customer", "客户", "战略", "货种"]):
        domain = "customer"
    elif any(kw in prompt_lower for kw in ["asset", "资产", "设备", "投资", "折旧"]):
        domain = "asset"

    # 判断调用场景
    # 1. 归因分析：system_prompt 包含因果/归因特征
    if system_prompt and ("因果" in system_lower or "归因" in system_lower):
        return {
            "text": json.dumps(ATTRIBUTION_RESULT, ensure_ascii=False),
            "tokens": {"prompt": 800, "completion": 600},
            "elapsed": 0.05,
            "error_category": None,
            "error": None,
            "prompt_chars": len(user_prompt) + (len(system_prompt) if system_prompt else 0),
        }

    # 2. 摘要生成：根据 summary_style 判断
    if "摘要" in prompt_lower or "executive" in prompt_lower or "分析摘要" in prompt_lower:
        if "220" in prompt_lower or "高管" in prompt_lower or "executive" in prompt_lower:
            text = SUMMARY_EXECUTIVE
        elif "300" in prompt_lower or "深度" in prompt_lower or "analytical" in prompt_lower:
            text = SUMMARY_ANALYTICAL
        else:
            text = SUMMARY_NARRATIVE

        return {
            "text": text,
            "tokens": {"prompt": 600, "completion": 200},
            "elapsed": 0.03,
            "error_category": None,
            "error": None,
            "prompt_chars": len(user_prompt),
        }

    # 3. 描述性分析：根据 domain 返回
    if domain == "throughput":
        text = NARRATIVE_THROUGHPUT
    elif domain == "customer":
        text = NARRATIVE_CUSTOMER
    elif domain == "asset":
        text = NARRATIVE_ASSET
    else:
        text = NARRATIVE_GENERIC

    return {
        "text": text,
        "tokens": {"prompt": 500, "completion": 180},
        "elapsed": 0.04,
        "error_category": None,
        "error": None,
        "prompt_chars": len(user_prompt),
    }


async def mock_invoke_llm_async(
    user_prompt: str,
    *,
    system_prompt: str | None = None,
    temperature: float = 0.3,
    timeout: int = 90,
    max_prompt_chars: int = 8000,
) -> dict[str, Any]:
    """异步版本的 Mock LLM 调用。"""
    import asyncio
    await asyncio.sleep(0.001)  # 模拟异步调用
    return mock_invoke_llm(
        user_prompt,
        system_prompt=system_prompt,
        temperature=temperature,
        timeout=timeout,
        max_prompt_chars=max_prompt_chars,
    )


# ════════════════════════════════════════════════════════════════
# 基于 prompt hash 的确定性 Mock（可选）
# ════════════════════════════════════════════════════════════════

def _hash_prompt(prompt: str) -> str:
    """对 prompt 进行 hash，用于生成确定性的 mock 结果。"""
    return hashlib.md5(prompt.encode("utf-8")).hexdigest()[:8]


# 预定义的变体响应（可用于测试同一 prompt 的不同输出）
VARIANT_RESPONSES = {
    "default": mock_invoke_llm,
    "fail_network": lambda **kw: {
        "text": "",
        "tokens": {},
        "elapsed": 0.01,
        "error_category": "NETWORK_ERROR",
        "error": "Connection timeout",
        "prompt_chars": kw.get("user_prompt", "") and len(kw["user_prompt"]) or 0,
    },
    "fail_rate_limit": lambda **kw: {
        "text": "",
        "tokens": {},
        "elapsed": 0.5,
        "error_category": "RATE_LIMIT",
        "error": "Rate limit exceeded",
        "prompt_chars": kw.get("user_prompt", "") and len(kw["user_prompt"]) or 0,
    },
}


def get_mock_llm(variant: str = "default"):
    """获取指定变体的 mock LLM 函数。"""
    return VARIANT_RESPONSES.get(variant, VARIANT_RESPONSES["default"])
