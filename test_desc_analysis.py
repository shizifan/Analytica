#!/usr/bin/env python3
"""测试描述性分析技能使用mock数据的表现"""

import asyncio
import pandas as pd
from backend.skills.analysis.descriptive import DescriptiveAnalysisSkill
from backend.skills.base import SkillInput

async def test_descriptive_analysis():
    """测试描述性分析技能"""
    print("测试描述性分析技能...")
    
    # 创建测试数据（模拟mock_server_all返回的数据）
    test_data = {
        "dateMonth": ["2026-01", "2026-02", "2026-03", "2026-04"],
        "usageRate": [3.1, 7.9, 3.5, 6.0],
        "serviceableRate": [0.998, 0.97, 0.9855, 0.9576]
    }
    df = pd.DataFrame(test_data)
    
    # 创建技能输入
    skill_input = SkillInput(
        params={
            "target_columns": ["usageRate", "serviceableRate"],
            "analysis_goal": "生产设备利用率和完好率月度趋势分析"
        },
        context_refs=["test_data"]
    )
    
    # 创建上下文
    context = {
        "test_data": df
    }
    
    # 执行分析
    skill = DescriptiveAnalysisSkill()
    result = await skill.execute(skill_input, context)
    
    # 打印结果
    print(f"状态: {result.status}")
    print(f"输出类型: {result.output_type}")
    print(f"数据: {result.data}")
    print(f"元数据: {result.metadata}")
    
    # 检查是否成功
    if result.status == "success":
        print("✓ 描述性分析成功")
        print(f"叙述: {result.data.get('narrative')}")
    else:
        print("✗ 描述性分析失败")

if __name__ == "__main__":
    asyncio.run(test_descriptive_analysis())
