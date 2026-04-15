"""TC-DOM: Domain 推断合理性报告测试（真实 LLM 调用）。

纯报告模式 — 单条测试永远通过，仅记录 REASONABLE/UNEXPECTED/NOT_INFERRED。
汇总测试输出分域统计报告，不使用 assert 失败。

数据集 25 条：每个 domain 至少 4 条 + 5 条跨域/模糊场景。
"""
import pytest

from backend.models.schemas import SlotValue, ALL_SLOT_NAMES
from tests.accuracy.conftest import VALID_DOMAINS, is_domain_reasonable, make_empty_slots


# ═══════════════════════════════════════════════════════════════
#  Domain 推断数据集
#  (user_input, acceptable_domains: set, case_id)
# ═══════════════════════════════════════════════════════════════

DOMAIN_DATASET = [
    # ── production (生产运营) ────────────────────────────────
    (
        "上个月集装箱吞吐量是多少",
        {"production"},
        "DOM-P01-集装箱吞吐量",
    ),
    (
        "各港区泊位占用率如何",
        {"production"},
        "DOM-P02-泊位占用率",
    ),
    (
        "今年散杂货作业量完成了多少",
        {"production"},
        "DOM-P03-散杂货作业量",
    ),
    (
        "港口吞吐量月度趋势如何",
        {"production"},
        "DOM-P04-月度趋势",
    ),
    (
        "港存压力大不大",
        {"production"},
        "DOM-P05-港存压力",
    ),
    # ── market (市场商务) ────────────────────────────────────
    (
        "今年市场份额增长了吗",
        {"market"},
        "DOM-M01-市场份额",
    ),
    (
        "各业务板块市场表现排名",
        {"market"},
        "DOM-M02-板块排名",
    ),
    (
        "商品车市场增速怎么样",
        {"market"},
        "DOM-M03-商品车增速",
    ),
    (
        "竞争对手的市场占有率变化",
        {"market"},
        "DOM-M04-竞争对手",
    ),
    # ── customer (客户管理) ──────────────────────────────────
    (
        "战略客户有多少家",
        {"customer"},
        "DOM-C01-客户数量",
    ),
    (
        "客户信用评级分布如何",
        {"customer"},
        "DOM-C02-信用评级",
    ),
    (
        "客户流失风险高不高",
        {"customer"},
        "DOM-C03-流失风险",
    ),
    (
        "大客户贡献占比是多少",
        {"customer"},
        "DOM-C04-大客户贡献",
    ),
    # ── asset (资产管理) ─────────────────────────────────────
    (
        "全港资产净值是多少",
        {"asset"},
        "DOM-A01-资产净值",
    ),
    (
        "设备老化率有多高",
        {"asset"},
        "DOM-A02-设备老化",
    ),
    (
        "今年设备更新投入多少",
        {"asset"},
        "DOM-A03-设备更新",
    ),
    (
        "固定资产折旧情况",
        {"asset"},
        "DOM-A04-固定资产折旧",
    ),
    # ── invest (投资管理) ────────────────────────────────────
    (
        "今年投资计划执行进度",
        {"invest"},
        "DOM-I01-投资进度",
    ),
    (
        "在建工程项目有哪些",
        {"invest", "asset"},
        "DOM-I02-在建工程",
    ),
    (
        "投资回报率怎么样",
        {"invest"},
        "DOM-I03-投资回报",
    ),
    (
        "重大项目推进情况",
        {"invest"},
        "DOM-I04-重大项目",
    ),
    # ── 跨域/模糊场景 ───────────────────────────────────────
    (
        "吞吐量和市场占有率之间的关系",
        {"production", "market"},
        "DOM-X01-吞吐量与市场",
    ),
    (
        "客户增长带来了哪些投资机会",
        {"customer", "invest"},
        "DOM-X02-客户与投资",
    ),
    (
        "帮我看看整体经营情况",
        VALID_DOMAINS,  # 模糊场景，任何 domain 都合理
        "DOM-X03-整体经营",
    ),
    (
        "做一份综合分析报告",
        VALID_DOMAINS,
        "DOM-X04-综合报告",
    ),
]


# ═══════════════════════════════════════════════════════════════
#  单条参数化测试（永远通过，仅记录结果）
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.llm_real
@pytest.mark.parametrize(
    "user_input,acceptable_domains,case_id",
    DOMAIN_DATASET,
    ids=[d[2] for d in DOMAIN_DATASET],
)
async def test_domain_inference_single(real_engine, user_input, acceptable_domains, case_id):
    """单条 domain 推断测试 — 永远通过，记录合理性。"""
    result = await real_engine.extract_slots_from_text(
        text=user_input,
        current_slots=make_empty_slots(),
        conversation_history=[],
    )

    domain_sv = result.get("domain")
    actual_domain = domain_sv.value if domain_sv else None
    status = is_domain_reasonable(actual_domain, acceptable_domains)

    filled = {k: str(v.value)[:40] for k, v in result.items() if v.value is not None}
    print(f"\n  [{case_id}] domain={actual_domain}, status={status}")
    print(f"    acceptable={acceptable_domains}")
    print(f"    all_filled={filled}")

    # 永远通过 — 纯报告
    assert True


# ═══════════════════════════════════════════════════════════════
#  汇总报告
# ═══════════════════════════════════════════════════════════════

@pytest.mark.asyncio
@pytest.mark.llm_real
async def test_domain_inference_report(real_engine):
    """Domain 推断汇总报告 — 输出分域统计，不 assert 失败。"""
    results = []

    for user_input, acceptable_domains, case_id in DOMAIN_DATASET:
        result = await real_engine.extract_slots_from_text(
            text=user_input,
            current_slots=make_empty_slots(),
            conversation_history=[],
        )
        domain_sv = result.get("domain")
        actual_domain = domain_sv.value if domain_sv else None
        status = is_domain_reasonable(actual_domain, acceptable_domains)
        results.append((case_id, actual_domain, acceptable_domains, status))

    # 统计
    total = len(results)
    reasonable = sum(1 for _, _, _, s in results if s == "REASONABLE")
    unexpected = sum(1 for _, _, _, s in results if s == "UNEXPECTED")
    not_inferred = sum(1 for _, _, _, s in results if s == "NOT_INFERRED")

    print(f"\n{'='*60}")
    print(f"  Domain 推断汇总报告")
    print(f"  总计: {total}")
    print(f"  REASONABLE:   {reasonable} ({reasonable/total:.0%})")
    print(f"  UNEXPECTED:   {unexpected} ({unexpected/total:.0%})")
    print(f"  NOT_INFERRED: {not_inferred} ({not_inferred/total:.0%})")
    print(f"{'='*60}")

    # 按域分组统计
    domain_groups = {}
    for case_id, actual, acceptable, status in results:
        # 用第一个可接受域分组
        group = sorted(acceptable)[0] if len(acceptable) <= 2 else "cross_domain"
        domain_groups.setdefault(group, []).append((case_id, status))

    for group, items in sorted(domain_groups.items()):
        r_count = sum(1 for _, s in items if s == "REASONABLE")
        print(f"  [{group}] {r_count}/{len(items)} reasonable")
        for cid, s in items:
            print(f"    {s:14s} {cid}")

    print(f"{'='*60}")

    # 不 assert 失败
    assert True
