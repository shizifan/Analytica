"""TC-PROBE: 能力边界探测测试（真实 LLM 调用）。

所有测试永远通过，仅记录和打印 LLM 在边界场景下的提取结果。
7 个类别，共 30 条边界场景，围绕真实业务指标设计。
"""
import pytest

from backend.models.schemas import SlotValue, ALL_SLOT_NAMES
from tests.accuracy.conftest import make_empty_slots


# ═══════════════════════════════════════════════════════════════
#  边界场景数据集
#  (user_input, category, case_id)
# ═══════════════════════════════════════════════════════════════

BOUNDARY_DATASET = [
    # ── 1. 歧义输入 (5条) ──────────────────────────────────────
    ("港口情况", "ambiguous", "BP-AMB01"),
    ("上个月的报表", "ambiguous", "BP-AMB02"),
    ("运营数据看看", "ambiguous", "BP-AMB03"),
    ("比去年好吗", "ambiguous", "BP-AMB04"),
    ("最新的", "ambiguous", "BP-AMB05"),

    # ── 2. 复杂时间表达 (6条) ──────────────────────────────────
    ("从去年国庆到今年春节期间的集装箱吞吐量", "complex_time", "BP-TIME01"),
    ("最近两个季度大连港的泊位利用率变化", "complex_time", "BP-TIME02"),
    ("2024年Q3到2025年Q1的散杂货月度趋势", "complex_time", "BP-TIME03"),
    ("上半年和去年同期的吞吐量对比", "complex_time", "BP-TIME04"),
    ("前年全年的投资完成率", "complex_time", "BP-TIME05"),
    ("入冬以来商品车港存量变化", "complex_time", "BP-TIME06"),

    # ── 3. 行业术语 (5条) ──────────────────────────────────────
    ("TEU的外贸内贸比例是多少", "jargon", "BP-JARG01"),
    ("散改集的增速怎么样", "jargon", "BP-JARG02"),
    ("岸桥单机效率和去年同期比", "jargon", "BP-JARG03"),
    ("在泊船舶的平均停泊时长", "jargon", "BP-JARG04"),
    ("各港区堆场翻箱率对比", "jargon", "BP-JARG05"),

    # ── 4. 矛盾/冲突输入 (4条) ────────────────────────────────
    ("快速出一份详细的全港资产分析PPT", "contradictory", "BP-CONT01"),
    ("简单看下所有港区所有业务类型的完整对比", "contradictory", "BP-CONT02"),
    ("不需要图表的趋势分析", "contradictory", "BP-CONT03"),
    ("日度粒度的年度投资完成率报告", "contradictory", "BP-CONT04"),

    # ── 5. 多意图/复合需求 (4条) ──────────────────────────────
    ("先看吞吐量数据再分析原因最后出个PPT发给领导", "multi_intent", "BP-MULT01"),
    ("对比集装箱和散杂货的同时看看客户结构变化", "multi_intent", "BP-MULT02"),
    ("大连港的设备状态和营口港的投资进度放一起看", "multi_intent", "BP-MULT03"),
    ("TEU增了多少，战略客户贡献多少，资产折旧率变化多少", "multi_intent", "BP-MULT04"),

    # ── 6. 混合语言 (3条) ──────────────────────────────────────
    ("Q1的container throughput同比YoY是多少", "mixed_language", "BP-LANG01"),
    ("show me大连port的berth utilization rate", "mixed_language", "BP-LANG02"),
    ("Monthly trend of 散杂货 since last October", "mixed_language", "BP-LANG03"),

    # ── 7. 指代消解/上下文依赖 (3条) ──────────────────────────
    ("它的月度进度怎么样", "reference", "BP-REF01"),
    ("这些客户里信用评级最高的是谁", "reference", "BP-REF02"),
    ("还是上次那个分析，更新一下数据", "reference", "BP-REF03"),
]


# ═══════════════════════════════════════════════════════════════
#  单条参数化探测（永远通过）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.llm_real
@pytest.mark.probe
@pytest.mark.parametrize(
    "user_input,category,case_id",
    BOUNDARY_DATASET,
    ids=[d[2] for d in BOUNDARY_DATASET],
)
async def test_boundary_probe_single(real_engine, user_input, category, case_id):
    """单条边界场景探测 — 永远通过，记录 LLM 的提取能力。"""
    result = await real_engine.extract_slots_from_text(
        text=user_input,
        current_slots=make_empty_slots(),
        conversation_history=[],
    )

    filled = {}
    for k, v in result.items():
        if v.value is not None:
            filled[k] = {
                "value": str(v.value)[:60],
                "source": v.source,
                "confirmed": v.confirmed,
            }

    filled_names = list(filled.keys())
    print(f"\n  [{case_id}] category={category}")
    print(f"    input: {user_input}")
    print(f"    filled_slots ({len(filled_names)}): {filled_names}")
    for k, info in filled.items():
        print(f"      {k}: {info['value']} (source={info['source']})")

    # 永远通过
    assert True


# ═══════════════════════════════════════════════════════════════
#  汇总报告
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.llm_real
@pytest.mark.probe
async def test_boundary_summary(real_engine):
    """能力边界汇总报告 — 按类别统计 LLM 的提取行为。"""
    category_stats = {}

    for user_input, category, case_id in BOUNDARY_DATASET:
        result = await real_engine.extract_slots_from_text(
            text=user_input,
            current_slots=make_empty_slots(),
            conversation_history=[],
        )

        filled_count = sum(1 for v in result.values() if v.value is not None)
        has_subject = result["analysis_subject"].value is not None
        has_time = result["time_range"].value is not None
        has_complexity = result["output_complexity"].value is not None

        stats = category_stats.setdefault(category, [])
        stats.append({
            "case_id": case_id,
            "filled_count": filled_count,
            "has_subject": has_subject,
            "has_time": has_time,
            "has_complexity": has_complexity,
        })

    print(f"\n{'='*60}")
    print(f"  能力边界探测汇总报告")
    print(f"{'='*60}")

    for category, items in sorted(category_stats.items()):
        avg_filled = sum(i["filled_count"] for i in items) / len(items)
        subject_rate = sum(1 for i in items if i["has_subject"]) / len(items)
        time_rate = sum(1 for i in items if i["has_time"]) / len(items)

        print(f"\n  [{category}] ({len(items)} 条)")
        print(f"    avg filled slots: {avg_filled:.1f}")
        print(f"    subject 提取率: {subject_rate:.0%}")
        print(f"    time_range 提取率: {time_rate:.0%}")

        for item in items:
            print(f"      {item['case_id']}: {item['filled_count']} slots filled "
                  f"(subject={'Y' if item['has_subject'] else 'N'}, "
                  f"time={'Y' if item['has_time'] else 'N'}, "
                  f"complexity={'Y' if item['has_complexity'] else 'N'})")

    print(f"\n{'='*60}")

    # 永远通过
    assert True
