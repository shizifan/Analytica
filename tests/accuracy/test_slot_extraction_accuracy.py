"""TC-ACC: Slot 提取准确率参数化测试（真实 LLM 调用）。

文件：tests/accuracy/test_slot_extraction_accuracy.py
标记：@pytest.mark.llm_real
目标：>= 85% 的精确槽提取准确率（按槽位命中数/总槽位数计算）

数据集覆盖 5 大业务领域 x 多种场景复杂度（共 ~35 条）。
合理性槽（domain, time_granularity, attribution_needed, predictive_needed）单独统计打印，不参与 assert。
"""
import pytest

from backend.models.schemas import SlotValue, ALL_SLOT_NAMES
from tests.accuracy.conftest import (
    VALID_DOMAINS,
    is_domain_reasonable,
    is_granularity_reasonable,
    make_empty_slots,
)


# ═══════════════════════════════════════════════════════════════
#  准确率测试数据集 v2：覆盖 5 大业务领域
#  expected_slots 为我们 SlotFillingEngine 可提取的标准槽位
# ═══════════════════════════════════════════════════════════════

ACCURACY_DATASET = [
    # ── 生产运营域（Production Operations）──────────────────
    # 核心期望：analysis_subject + time_range（必填槽 LLM 必须提取）
    # output_complexity 仅在有明确语义线索时期望（如"趋势分析"→chart_text, "报告"→full_report）
    # domain/time_granularity 为 inferable(priority=99)，由引擎默认逻辑填充，不纳入 LLM 提取期望
    (
        "上个月各业务线的吞吐量是多少？",
        {
            "time_range": True,
            "analysis_subject": True,
        },
        "A1-生产-板块吞吐量",
    ),
    (
        "现在各港区泊位占用率如何？",
        {
            "analysis_subject": True,
        },
        "A2-生产-泊位占用率",
    ),
    (
        "集装箱吞吐量今年目标是多少TEU，完成率怎样？",
        {
            "analysis_subject": True,
            "time_range": True,
        },
        "A5-生产-目标完成率",
    ),
    (
        "最近一个月港存压力怎样？",
        {
            "time_range": True,
            "analysis_subject": True,
        },
        "A6-生产-港存压力",
    ),
    (
        "分析一下今年Q1港口集装箱吞吐量的变化趋势，以及背后的主要驱动因素",
        {
            "time_range": True,
            "analysis_subject": True,
            "output_complexity": "chart_text",  # "趋势+归因" 有明确语义线索
        },
        "B1-生产-趋势归因",
    ),
    (
        "今年吞吐量月度趋势如何，和去年比有什么变化？",
        {
            "time_range": True,
            "analysis_subject": True,
        },
        "A7-生产-月度同比",
    ),
    # ── 市场商务域（Market & Commerce）──────────────────────
    (
        "今年散杂货市场表现如何，和去年比怎样？",
        {
            "analysis_subject": True,
            "time_range": True,
        },
        "B2-市场-散杂货对比",
    ),
    (
        "本月市场完成多少，和去年同期比差多少？",
        {
            "time_range": True,
            "analysis_subject": True,
        },
        "A8-市场-同期对比",
    ),
    (
        "各港区之间吞吐量差异是否在扩大？",
        {
            "analysis_subject": True,
        },
        "A9-市场-港区差异",
    ),
    (
        "各业务板块结构如何，集装箱占整体比重是多少？",
        {
            "analysis_subject": True,
        },
        "A10-市场-板块占比",
    ),
    (
        "今年商品车吞吐量为什么增速这么快？",
        {
            "analysis_subject": True,
            "time_range": True,
            "output_complexity": "chart_text",  # "为什么" 有归因语义线索
        },
        "B6-市场-商品车归因",
    ),
    # ── 客户管理域（Customer Management）───────────────────
    (
        "战略客户有多少家？",
        {
            "analysis_subject": True,
        },
        "A11-客户-数量",
    ),
    (
        "战略客户贡献趋势是否稳定，有没有流失风险？",
        {
            "analysis_subject": True,
        },
        "B3-客户-贡献风险",
    ),
    (
        "客户信用状况整体健康吗？",
        {
            "analysis_subject": True,
        },
        "B8-客户-信用健康",
    ),
    # ── 资产管理域（Asset Management）──────────────────────
    (
        "全港资产净值是多少？",
        {
            "analysis_subject": True,
        },
        "A12-资产-净值",
    ),
    (
        "设备资产状况如何，今年投了多少钱更新设备？",
        {
            "analysis_subject": True,
            "time_range": True,
        },
        "B4-资产-设备投资",
    ),
    # ── 投资管理域（Investment Management）─────────────────
    (
        "今年投资计划完成了多少？",
        {
            "time_range": True,
            "analysis_subject": True,
        },
        "A13-投资-完成率",
    ),
    (
        "今年有哪些大项目在推进？",
        {
            "time_range": True,
            "analysis_subject": True,
        },
        "A14-投资-项目列表",
    ),
    (
        "投资完成进度是否符合年初节奏安排？",
        {
            "time_range": True,
            "analysis_subject": True,
        },
        "B7-投资-进度节奏",
    ),
    # ── 跨域复合场景 ────────────────────────────────────────
    (
        "帮我生成3月份港口经营分析月报，要PPT格式，包含生产、市场、投资三个维度",
        {
            "time_range": True,
            "output_complexity": "full_report",  # "月报+PPT" 有明确报告语义
            "output_format": "pptx",
            "analysis_subject": True,
        },
        "C2-跨域-月度经营月报",
    ),
    # ═════════════════════════════════════════════════════════
    #  新增样本：覆盖 inferable 槽位
    # ═════════════════════════════════════════════════════════
    # ── 粒度明确（time_granularity）──────────────────────────
    (
        "按月统计今年各港区泊位利用率",
        {
            "analysis_subject": True,
            "time_range": True,
            "time_granularity": {"_reasonable": "monthly"},
        },
        "D1-粒度-按月统计",
    ),
    (
        "这周每天到港船舶数量有多少",
        {
            "analysis_subject": True,
            "time_range": True,
            "time_granularity": {"_reasonable": "daily"},
        },
        "D2-粒度-每天",
    ),
    (
        "按季度看各业务板块吞吐量变化",
        {
            "analysis_subject": True,
            "time_granularity": {"_reasonable": "quarterly"},
        },
        "D3-粒度-按季度",
    ),
    # ── 归因线索（attribution_needed）────────────────────────
    (
        "本季度集装箱吞吐量下滑的原因是什么",
        {
            "analysis_subject": True,
            "time_range": True,
            "output_complexity": "chart_text",
            "attribution_needed": True,
        },
        "D4-归因-吞吐量下滑",
    ),
    (
        "战略客户流失原因分析",
        {
            "analysis_subject": True,
            "attribution_needed": True,
        },
        "D5-归因-客户流失",
    ),
    # ── 预测线索（predictive_needed）─────────────────────────
    (
        "做一份含预测的Q1港口综合运营报告",
        {
            "analysis_subject": True,
            "time_range": True,
            "output_complexity": "full_report",
            "predictive_needed": True,
        },
        "D6-预测-综合报告",
    ),
    # ── 域推断（domain）—— 合理性判断 ────────────────────────
    (
        "港口设备老化率有多高",
        {
            "analysis_subject": True,
            "domain": {"_reasonable": {"asset"}},
        },
        "D7-域-设备老化",
    ),
    (
        "在建工程项目汇总",
        {
            "analysis_subject": True,
            "domain": {"_reasonable": {"invest", "asset"}},
        },
        "D8-域-在建工程",
    ),
    (
        "客户信用评级分布情况",
        {
            "analysis_subject": True,
            "domain": {"_reasonable": {"customer"}},
        },
        "D9-域-客户信用",
    ),
    # ── 跨域样本（domain 多值合理）───────────────────────────
    (
        "吞吐量和市场占有率之间有什么关系",
        {
            "analysis_subject": True,
            "domain": {"_reasonable": {"production", "market"}},
        },
        "D10-跨域-吞吐量市场",
    ),
    (
        "客户增长带动了哪些投资项目",
        {
            "analysis_subject": True,
            "domain": {"_reasonable": {"customer", "invest"}},
        },
        "D11-跨域-客户投资",
    ),
    # ── 复合：粒度+域+归因 ──────────────────────────────────
    (
        "按月分析今年生产线设备故障趋势及原因",
        {
            "analysis_subject": True,
            "time_range": True,
            "time_granularity": {"_reasonable": "monthly"},
            "attribution_needed": True,
            "domain": {"_reasonable": {"production", "asset"}},
        },
        "D12-复合-设备故障归因",
    ),
    (
        "做一份上半年客户经营分析报告，PPT格式，含归因和预测",
        {
            "analysis_subject": True,
            "time_range": True,
            "output_complexity": "full_report",
            "output_format": "pptx",
            "attribution_needed": True,
            "predictive_needed": True,
        },
        "D13-复合-客户报告全槽",
    ),
    (
        "年度各港区散杂货吞吐量对比分析",
        {
            "analysis_subject": True,
            "time_granularity": {"_reasonable": "yearly"},
            "domain": {"_reasonable": {"production", "market"}},
        },
        "D14-复合-年度散杂货",
    ),
    (
        "最近三个月每日集装箱吞吐量波动情况",
        {
            "analysis_subject": True,
            "time_range": True,
            "time_granularity": {"_reasonable": "daily"},
        },
        "D15-复合-日粒度波动",
    ),
]


# ── 精确槽 vs 合理性槽分类 ────────────────────────────────────
PRECISE_SLOTS = {"analysis_subject", "time_range", "output_complexity", "output_format"}
REASONABLE_SLOTS = {"domain", "time_granularity", "attribution_needed", "predictive_needed"}


def _is_reasonable_slot(key: str, expected_value) -> bool:
    """判断该期望值是否属于合理性判断类型。"""
    if isinstance(expected_value, dict) and "_reasonable" in expected_value:
        return True
    if key in REASONABLE_SLOTS:
        return True
    return False


def _slot_hit(actual_slots: dict[str, SlotValue], key: str, expected_value) -> bool:
    """检查单个槽位是否命中。

    expected_value:
      - True: 只要 value 不为 None 即命中
      - str: value 的字符串表示中包含 expected_value（不区分大小写）
      - dict {"_reasonable": set}: domain 合理性判断
      - dict {"_reasonable": str}: granularity 合理性判断
    """
    sv = actual_slots.get(key)
    if sv is None or sv.value is None:
        return False
    if expected_value is True:
        return True
    # 合理性判断
    if isinstance(expected_value, dict) and "_reasonable" in expected_value:
        hint = expected_value["_reasonable"]
        if isinstance(hint, set):
            # domain 合理性
            return is_domain_reasonable(sv.value, hint) == "REASONABLE"
        elif isinstance(hint, str):
            # granularity 合理性
            return is_granularity_reasonable(sv.value, hint)
        return False
    # 字符串匹配（宽松）
    actual_str = str(sv.value).lower()
    expected_str = str(expected_value).lower()
    return expected_str in actual_str or actual_str in expected_str


def _split_expected(expected: dict) -> tuple[dict, dict]:
    """将 expected_slots 拆分为精确槽和合理性槽。"""
    precise = {}
    reasonable = {}
    for k, v in expected.items():
        if _is_reasonable_slot(k, v):
            reasonable[k] = v
        else:
            precise[k] = v
    return precise, reasonable


def slot_hit_rate(actual_slots: dict[str, SlotValue], expected: dict) -> float:
    """计算槽位命中率：命中数 / 期望槽位总数"""
    if not expected:
        return 1.0
    hits = sum(1 for k, v in expected.items() if _slot_hit(actual_slots, k, v))
    return hits / len(expected)


def precise_slot_hit_rate(actual_slots: dict[str, SlotValue], expected: dict) -> float:
    """仅计算精确槽的命中率。"""
    precise, _ = _split_expected(expected)
    return slot_hit_rate(actual_slots, precise)


# ═══════════════════════════════════════════════════════════════
#  单条输入参数化测试
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.llm_real
@pytest.mark.parametrize(
    "user_input,expected_slots,case_id",
    ACCURACY_DATASET,
    ids=[d[2] for d in ACCURACY_DATASET],
)
async def test_slot_extraction_per_input(real_engine, user_input, expected_slots, case_id):
    """单条输入的 Slot 提取验证。

    精确槽命中率 >= 0.5（部分提取也算有效，追问机制补全）。
    合理性槽仅打印，不 assert。
    """
    result = await real_engine.extract_slots_from_text(
        text=user_input,
        current_slots=make_empty_slots(),
        conversation_history=[],
    )

    precise, reasonable = _split_expected(expected_slots)
    precise_rate = slot_hit_rate(result, precise) if precise else 1.0
    filled = {k: str(v.value)[:50] for k, v in result.items() if v.value is not None}

    print(f"\n  [{case_id}] 精确槽命中率: {precise_rate:.0%}")
    print(f"  输入: {user_input}")
    print(f"  期望精确槽: {list(precise.keys())}")
    print(f"  实际: {filled}")

    # 打印合理性槽结果（不 assert）
    if reasonable:
        for rk, rv in reasonable.items():
            sv = result.get(rk)
            actual_val = sv.value if sv else None
            hit = _slot_hit(result, rk, rv)
            status = "HIT" if hit else ("MISS" if actual_val is None else "UNEXPECTED")
            print(f"  [合理性] {rk}: actual={actual_val}, status={status}")

    assert precise_rate >= 0.5, (
        f"[{case_id}] 输入「{user_input}」精确槽命中率 {precise_rate:.0%} < 50%\n"
        f"期望: {precise}\n实际: {filled}"
    )


# ═══════════════════════════════════════════════════════════════
#  整体准确率测试
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_slot_extraction_overall_accuracy(real_engine):
    """数据集整体准确率测试。

    精确槽（analysis_subject, time_range, output_complexity, output_format）assert >= 85%。
    合理性槽（domain, time_granularity, attribution_needed, predictive_needed）仅打印统计报告。
    """
    precise_rates = []
    reasonable_stats = {"total": 0, "hit": 0, "miss": 0, "unexpected": 0}

    for user_input, expected_slots, case_id in ACCURACY_DATASET:
        result = await real_engine.extract_slots_from_text(
            text=user_input,
            current_slots=make_empty_slots(),
            conversation_history=[],
        )

        precise, reasonable = _split_expected(expected_slots)
        p_rate = slot_hit_rate(result, precise) if precise else 1.0
        precise_rates.append((case_id, p_rate))

        # 合理性槽统计
        for rk, rv in reasonable.items():
            reasonable_stats["total"] += 1
            sv = result.get(rk)
            actual_val = sv.value if sv else None
            if _slot_hit(result, rk, rv):
                reasonable_stats["hit"] += 1
            elif actual_val is None:
                reasonable_stats["miss"] += 1
            else:
                reasonable_stats["unexpected"] += 1

    overall_precise = sum(r for _, r in precise_rates) / len(precise_rates)
    below = [(cid, r) for cid, r in precise_rates if r < 0.5]

    print(f"\n{'='*60}")
    print(f"  精确槽整体准确率: {overall_precise:.1%}")
    print(f"  总样本数: {len(precise_rates)}")
    print(f"  低于 50% 的样本 ({len(below)}/{len(precise_rates)}):")
    for cid, r in below:
        print(f"    [{r:.0%}] {cid}")
    print(f"{'='*60}")

    for cid, r in precise_rates:
        status = "PASS" if r >= 0.5 else "FAIL"
        print(f"  [{status}] {cid}: {r:.0%}")

    # 合理性槽报告
    rt = reasonable_stats
    if rt["total"] > 0:
        print(f"\n{'='*60}")
        print(f"  合理性槽统计 (不参与 assert):")
        print(f"  总数: {rt['total']}, 命中: {rt['hit']} ({rt['hit']/rt['total']:.0%}), "
              f"未推断: {rt['miss']}, 意外值: {rt['unexpected']}")
        print(f"{'='*60}")

    assert overall_precise >= 0.85, (
        f"精确槽整体准确率 {overall_precise:.1%} < 85%，需优化 Slot 提取 Prompt"
    )
