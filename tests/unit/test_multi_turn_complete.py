"""TC-MT: 完整多轮对话场景测试（真实 LLM 调用 + 预定义用户脚本）。

20 个场景覆盖 5 大业务域（生产/市场/客户/资产/投资），
围绕真实 API 指标、过滤条件、组合查询设计。
每个场景最多 3 轮，验证槽位填充完成性。
"""
import pytest

from backend.agent.perception import SlotFillingEngine
from backend.models.schemas import SlotValue, ALL_SLOT_NAMES


def make_empty_slots():
    return {name: SlotValue(value=None, source="default", confirmed=False) for name in ALL_SLOT_NAMES}


# ═══════════════════════════════════════════════════════════════
#  辅助函数
# ═══════════════════════════════════════════════════════════════

def _print_interactions(cap_llm, label: str):
    """打印最近的 LLM 交互日志并清空。"""
    ixns = cap_llm.pop_all()
    for i, ixn in enumerate(ixns):
        print(f"    [{label}#{i+1}] response: {ixn.cleaned_response[:200]}")
    return ixns


def _print_slots(slots):
    """打印所有非空槽位。"""
    for k, v in slots.items():
        if v.value is not None:
            print(f"    {k}: {str(v.value)[:60]} (source={v.source}, confirmed={v.confirmed})")


# ═══════════════════════════════════════════════════════════════
#  生产运营域 (MT01-MT05)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt01_throughput_precise_query(capturing_engine):
    """MT01: 大连港区月度吞吐量精确查询 — 单轮完成。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()

    slots = await engine.extract_slots_from_text(
        "大连港区今年3月份的货物吞吐量完成了多少", slots, []
    )
    print(f"\n  [MT01] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None
    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt02_teu_completion_attribution(capturing_engine):
    """MT02: TEU完成率+归因 — R1 提取指标+归因意图 → R2 补充时间。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "今年集装箱TEU目标完成率为什么不及预期", slots, history
    )
    print(f"\n  [MT02] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_clarification_question("time_range", slots)
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "今年集装箱TEU目标完成率为什么不及预期"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text("截止到6月底的数据", slots, history)
    print(f"  [MT02] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt03_berth_occupancy_cross_region(capturing_engine):
    """MT03: 泊位利用率跨区对比 — R1 提取对比意图 → R2 补充时间。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "对比一下四个港区上个月的泊位利用率", slots, history
    )
    print(f"\n  [MT03] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    # 如果 time_range 还没填，追问
    if slots["time_range"].value is None:
        question = await engine.generate_clarification_question("time_range", slots)
        _print_interactions(cap, "R1-clarify")
        history.extend([
            {"role": "user", "content": "对比一下四个港区上个月的泊位利用率"},
            {"role": "assistant", "content": question},
        ])

        slots = await engine.extract_slots_from_text("2026年3月的", slots, history)
        print(f"  [MT03] R2:")
        _print_interactions(cap, "R2")
        _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt04_vessel_efficiency_trend(capturing_engine):
    """MT04: 船舶效率趋势+公司过滤 — R1 提取指标+公司 → R2 明确输出类型。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "中远海运最近三个月的船舶作业效率表现怎么样", slots, history
    )
    print(f"\n  [MT04] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_multi_slot_clarification(
        ["output_complexity"], slots
    )
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "中远海运最近三个月的船舶作业效率表现怎么样"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text("给我画个趋势图看看", slots, history)
    print(f"  [MT04] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt05_port_inventory_filter(capturing_engine):
    """MT05: 港存库容+业务类型过滤 — R1 提取指标+区域+业务 → R2 补充时间。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "营口港区散杂货的港存库容情况怎么样", slots, history
    )
    print(f"\n  [MT05] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_clarification_question("time_range", slots)
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "营口港区散杂货的港存库容情况怎么样"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text("看最新的就行，这个月的", slots, history)
    print(f"  [MT05] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


# ═══════════════════════════════════════════════════════════════
#  市场商务域 (MT06-MT08)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt06_market_yoy_comparison(capturing_engine):
    """MT06: 月度同比分析 — 单轮完成。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()

    slots = await engine.extract_slots_from_text(
        "这个月全港吞吐量和去年同月比增长了多少", slots, []
    )
    print(f"\n  [MT06] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None
    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt07_key_enterprise_top_n(capturing_engine):
    """MT07: 重点企业TOP-N排名 — R1 提取指标 → R2 确认时间范围。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "今年累计集装箱板块前十大重点企业的贡献排名", slots, history
    )
    print(f"\n  [MT07] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    if slots["time_range"].value is None:
        question = await engine.generate_clarification_question("time_range", slots)
        _print_interactions(cap, "R1-clarify")
        history.extend([
            {"role": "user", "content": "今年累计集装箱板块前十大重点企业的贡献排名"},
            {"role": "assistant", "content": question},
        ])

        # R2
        slots = await engine.extract_slots_from_text(
            "对，看今年1到6月的累计数据", slots, history
        )
        print(f"  [MT07] R2:")
        _print_interactions(cap, "R2")
        _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt08_segment_structure(capturing_engine):
    """MT08: 四大板块结构占比 — R1 提取指标+时间 → R2 明确输出类型。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "一季度四大货类的吞吐量结构占比变化情况", slots, history
    )
    print(f"\n  [MT08] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_clarification_question("output_complexity", slots)
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "一季度四大货类的吞吐量结构占比变化情况"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text("做成图文分析就行", slots, history)
    print(f"  [MT08] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


# ═══════════════════════════════════════════════════════════════
#  客户管理域 (MT09-MT11)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt09_strategic_client_metrics(capturing_engine):
    """MT09: 战略客户吞吐+收入 — R1 提取客户+指标 → R2 明确输出类型。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "中远海运集装箱运输今年上半年的吞吐量和营收贡献情况", slots, history
    )
    print(f"\n  [MT09] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_clarification_question("output_complexity", slots)
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "中远海运集装箱运输今年上半年的吞吐量和营收贡献情况"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text("做个简单的表格就行", slots, history)
    print(f"  [MT09] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt10_credit_rating_distribution(capturing_engine):
    """MT10: 信用评级分布 — 单轮完成。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()

    slots = await engine.extract_slots_from_text(
        "港口客户的信用评级分布是什么样的，AAA级客户有多少个", slots, []
    )
    print(f"\n  [MT10] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt11_cargo_contribution_top_n(capturing_engine):
    """MT11: 货类贡献TOP-N — R1 提取指标 → R2 确认统计类型。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "上个月散粮品类的客户贡献TOP5是哪些企业", slots, history
    )
    print(f"\n  [MT11] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_multi_slot_clarification(
        ["output_complexity"], slots
    )
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "上个月散粮品类的客户贡献TOP5是哪些企业"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text(
        "看月度数据就行，不是累计的", slots, history
    )
    print(f"  [MT11] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


# ═══════════════════════════════════════════════════════════════
#  资产管理域 (MT12-MT13)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt12_asset_overview_by_region(capturing_engine):
    """MT12: 固定资产概况+区域 — R1 提取指标+区域+时间 → R2 明确输出类型。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "营口港区去年的固定资产总量和折旧率是多少", slots, history
    )
    print(f"\n  [MT12] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_clarification_question("output_complexity", slots)
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "营口港区去年的固定资产总量和折旧率是多少"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text("就看数字，简单表格", slots, history)
    print(f"  [MT12] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt13_equipment_status(capturing_engine):
    """MT13: 设备状态 — R1 提取指标 → R2 补充区域范围。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "今年港口设备的正常运行率和报废率分别是多少", slots, history
    )
    print(f"\n  [MT13] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    history.extend([
        {"role": "user", "content": "今年港口设备的正常运行率和报废率分别是多少"},
        {"role": "assistant", "content": "请问您想看哪个港区的设备状态？还是看全港的数据？"},
    ])

    # R2
    slots = await engine.extract_slots_from_text("全港的，不分港区", slots, history)
    print(f"  [MT13] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


# ═══════════════════════════════════════════════════════════════
#  投资管理域 (MT14-MT15)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt14_invest_plan_completion(capturing_engine):
    """MT14: 资本类计划执行率 — R1 提取指标 → R2 补充输出需求。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "今年资本类投资项目的计划完成率怎么样", slots, history
    )
    print(f"\n  [MT14] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_multi_slot_clarification(
        ["output_complexity"], slots
    )
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "今年资本类投资项目的计划完成率怎么样"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text(
        "全港的数据，按月看进度趋势", slots, history
    )
    print(f"  [MT14] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt15_invest_monthly_progress(capturing_engine):
    """MT15: 月度进度计划vs实际 — 单轮完成。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()

    slots = await engine.extract_slots_from_text(
        "帮我拉一下1到6月的全港投资月度进度，看计划和实际完成额的对比", slots, []
    )
    print(f"\n  [MT15] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None
    assert slots["time_range"].value is not None


# ═══════════════════════════════════════════════════════════════
#  跨域 & 综合场景 (MT16-MT17)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt16_cross_domain_share_trend(capturing_engine):
    """MT16: 生产+市场占比趋势+归因 — R1 提取指标 → R2 明确归因+输出。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "大连港区集装箱在全港吞吐量的市场占比是多少，最近半年的趋势",
        slots, history,
    )
    print(f"\n  [MT16] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    question = await engine.generate_multi_slot_clarification(
        ["output_complexity", "attribution_needed"], slots
    )
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "大连港区集装箱在全港吞吐量的市场占比是多少，最近半年的趋势"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text(
        "出个图文分析，需要归因分析下占比变化的原因", slots, history
    )
    print(f"  [MT16] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt17_annual_report_three_rounds(capturing_engine):
    """MT17: 三域年度报告 — 3轮逐步构建 full_report。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "帮我做一份2025年度港口经营分析报告", slots, history
    )
    print(f"\n  [MT17] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    question = await engine.generate_multi_slot_clarification(
        ["output_format", "attribution_needed"], slots
    )
    _print_interactions(cap, "R1-clarify")
    history.extend([
        {"role": "user", "content": "帮我做一份2025年度港口经营分析报告"},
        {"role": "assistant", "content": question},
    ])
    print(f"  追问: {question}")

    # R2
    slots = await engine.extract_slots_from_text(
        "PPT格式，涵盖生产运营、市场和投资三个板块", slots, history
    )
    print(f"  [MT17] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    question2 = await engine.generate_multi_slot_clarification(
        ["predictive_needed"], slots
    )
    _print_interactions(cap, "R2-clarify")
    history.extend([
        {"role": "user", "content": "PPT格式，涵盖生产运营、市场和投资三个板块"},
        {"role": "assistant", "content": question2},
    ])
    print(f"  追问: {question2}")

    # R3
    slots = await engine.extract_slots_from_text("要归因分析，不需要预测", slots, history)
    print(f"  [MT17] R3:")
    _print_interactions(cap, "R3")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None
    assert slots["time_range"].value is not None


# ═══════════════════════════════════════════════════════════════
#  修正 & 特殊场景 (MT18-MT20)
# ═══════════════════════════════════════════════════════════════


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt18_multi_field_correction(capturing_engine):
    """MT18: 用户修正主体+区域 — R1 油化品+大连 → R2 改为散杂货+营口。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "看看大连港区上个月的油化品库存", slots, history
    )
    print(f"\n  [MT18] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)
    r1_subject = str(slots["analysis_subject"].value) if slots["analysis_subject"].value else ""

    history.extend([
        {"role": "user", "content": "看看大连港区上个月的油化品库存"},
        {"role": "assistant", "content": "好的，正在查看大连港区上个月的油化品库存数据。"},
    ])

    # R2: 修正
    slots = await engine.extract_slots_from_text(
        "不对，我要看散杂货的，而且改成营口港区", slots, history
    )
    print(f"  [MT18] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    r2_subject = str(slots["analysis_subject"].value).lower() if slots["analysis_subject"].value else ""
    assert "散杂" in r2_subject or "杂货" in r2_subject or "散" in r2_subject, \
        f"analysis_subject 应修正为散杂货相关, 实际: {slots['analysis_subject'].value}"
    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt19_negation_cancel_attribution(capturing_engine):
    """MT19: 否定式退回取消归因 — R1 归因分析 → R2 取消归因改为简单查数。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text(
        "分析一下上个月各港区吞吐量下降的原因", slots, history
    )
    print(f"\n  [MT19] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None

    history.extend([
        {"role": "user", "content": "分析一下上个月各港区吞吐量下降的原因"},
        {"role": "assistant", "content": "好的，我来分析上个月各港区吞吐量下降的原因。"},
    ])

    # R2: 否定归因
    slots = await engine.extract_slots_from_text(
        "归因就不需要了，直接给我一个对比数据表就行", slots, history
    )
    print(f"  [MT19] R2:")
    _print_interactions(cap, "R2")
    _print_slots(slots)

    assert slots["time_range"].value is not None


@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_mt20_bypass_then_topic_switch(capturing_engine):
    """MT20: Bypass+主题切换 — R1 模糊 → R2 bypass → R3 切换到投资域。"""
    engine, cap = capturing_engine
    slots = make_empty_slots()
    history = []

    # R1
    slots = await engine.extract_slots_from_text("看看港口运营数据", slots, history)
    print(f"\n  [MT20] R1:")
    _print_interactions(cap, "R1")
    _print_slots(slots)

    history.extend([
        {"role": "user", "content": "看看港口运营数据"},
        {"role": "assistant", "content": "请问您具体想看哪方面的运营数据？"},
    ])

    # R2: bypass
    bypass_result = await engine.handle_bypass("按你理解执行", slots)
    print(f"  [MT20] R2: bypass={bypass_result}")
    _print_slots(slots)
    assert bypass_result["bypass_triggered"] is True

    history.extend([
        {"role": "user", "content": "按你理解执行"},
        {"role": "assistant", "content": "好的，按我的理解为您分析。"},
    ])

    # R3: 完全切换主题
    slots = await engine.extract_slots_from_text(
        "算了，我想看今年在建的资本类投资项目进展情况", slots, history
    )
    print(f"  [MT20] R3:")
    _print_interactions(cap, "R3")
    _print_slots(slots)

    assert slots["analysis_subject"].value is not None
    subject_str = str(slots["analysis_subject"].value).lower()
    assert "投资" in subject_str or "项目" in subject_str or "资本" in subject_str, \
        f"analysis_subject 应切换为投资相关, 实际: {slots['analysis_subject'].value}"
