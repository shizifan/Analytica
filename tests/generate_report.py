"""独立报告生成脚本 — 运行所有真实 LLM 场景并输出精简 Markdown 报告。

用法:
    uv run python tests/generate_report.py

输出:
    reports/phase1_test_report.md
"""
from __future__ import annotations

import asyncio
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# 将项目根目录加入 sys.path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from langchain_openai import ChatOpenAI

from backend.agent.perception import SlotFillingEngine
from backend.models.schemas import SlotValue, ALL_SLOT_NAMES
from tests.helpers.capturing_llm import CapturingLLM, LLMInteraction


# ═══════════════════════════════════════════════════════════════
#  中文标签映射
# ═══════════════════════════════════════════════════════════════

SLOT_LABELS = {
    "analysis_subject": "分析对象",
    "time_range": "时间范围",
    "output_complexity": "输出复杂度",
    "output_format": "输出格式",
    "attribution_needed": "归因分析",
    "predictive_needed": "预测分析",
    "time_granularity": "时间粒度",
    "domain": "领域",
    "domain_glossary": "领域术语",
}

SOURCE_LABELS = {
    "user_input": "用户输入",
    "inferred": "推断",
    "memory": "记忆",
    "memory_low_confidence": "记忆(低)",
    "default": "默认",
    "history": "历史",
}


def _slot_label(name: str) -> str:
    return SLOT_LABELS.get(name, name)


def _source_label(source: str) -> str:
    return SOURCE_LABELS.get(source, source)


# ═══════════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class RoundRecord:
    """单轮交互记录。"""
    round_num: int
    user_input: str
    action: str  # "extract" | "clarify" | "bypass"
    llm_response: str = ""  # LLM 提取结果 JSON (cleaned)
    clarification_question: str | None = None
    slots_snapshot: dict[str, dict] = field(default_factory=dict)


@dataclass
class ScenarioResult:
    """单个场景完整结果。"""
    scenario_id: str
    description: str
    category: str  # "multi_turn" | "boundary"
    domain_tag: str = ""
    rounds: list[RoundRecord] = field(default_factory=list)
    final_slots: dict[str, dict] = field(default_factory=dict)
    has_clarification: bool = False
    elapsed_sec: float = 0.0
    error: str | None = None


def make_empty_slots():
    return {name: SlotValue(value=None, source="default", confirmed=False)
            for name in ALL_SLOT_NAMES}


def slots_to_dict(slots: dict[str, SlotValue]) -> dict[str, dict]:
    result = {}
    for k, v in slots.items():
        if v.value is not None:
            result[k] = {
                "value": str(v.value)[:120],
                "source": v.source,
                "confirmed": v.confirmed,
            }
    return result


def _format_value(val: str, maxlen: int = 60) -> str:
    """缩短显示值。"""
    val = val.replace("\n", " ").strip()
    return val[:maxlen] + "..." if len(val) > maxlen else val


# ═══════════════════════════════════════════════════════════════
#  多轮对话场景定义
# ═══════════════════════════════════════════════════════════════

MULTI_TURN_SCENARIOS = [
    # ── 生产运营域 ────────────────────────────────────────────
    {
        "id": "MT01", "desc": "大连港区月度吞吐量精确查询", "domain": "生产",
        "rounds": [
            {"input": "大连港区今年3月份的货物吞吐量完成了多少"},
        ],
    },
    {
        "id": "MT02", "desc": "TEU完成率+归因分析", "domain": "生产",
        "rounds": [
            {"input": "今年集装箱TEU目标完成率为什么不及预期", "clarify_slots": ["time_range"]},
            {"input": "截止到6月底的数据"},
        ],
    },
    {
        "id": "MT03", "desc": "泊位利用率跨区对比", "domain": "生产",
        "rounds": [
            {"input": "对比一下四个港区上个月的泊位利用率", "clarify_slots": ["time_range"]},
            {"input": "2026年3月的"},
        ],
    },
    {
        "id": "MT04", "desc": "船舶效率趋势+公司过滤", "domain": "生产",
        "rounds": [
            {"input": "中远海运最近三个月的船舶作业效率表现怎么样", "clarify_slots": ["output_complexity"]},
            {"input": "给我画个趋势图看看"},
        ],
    },
    {
        "id": "MT05", "desc": "港存库容+业务类型过滤", "domain": "生产",
        "rounds": [
            {"input": "营口港区散杂货的港存库容情况怎么样", "clarify_slots": ["time_range"]},
            {"input": "看最新的就行，这个月的"},
        ],
    },
    # ── 市场商务域 ────────────────────────────────────────────
    {
        "id": "MT06", "desc": "月度同比分析", "domain": "市场",
        "rounds": [
            {"input": "这个月全港吞吐量和去年同月比增长了多少"},
        ],
    },
    {
        "id": "MT07", "desc": "重点企业TOP-N排名", "domain": "市场",
        "rounds": [
            {"input": "今年累计集装箱板块前十大重点企业的贡献排名", "clarify_slots": ["time_range"]},
            {"input": "对，看今年1到6月的累计数据"},
        ],
    },
    {
        "id": "MT08", "desc": "四大板块结构占比", "domain": "市场",
        "rounds": [
            {"input": "一季度四大货类的吞吐量结构占比变化情况", "clarify_slots": ["output_complexity"]},
            {"input": "做成图文分析就行"},
        ],
    },
    # ── 客户管理域 ────────────────────────────────────────────
    {
        "id": "MT09", "desc": "战略客户吞吐+收入", "domain": "客户",
        "rounds": [
            {"input": "中远海运集装箱运输今年上半年的吞吐量和营收贡献情况", "clarify_slots": ["output_complexity"]},
            {"input": "做个简单的表格就行"},
        ],
    },
    {
        "id": "MT10", "desc": "信用评级分布", "domain": "客户",
        "rounds": [
            {"input": "港口客户的信用评级分布是什么样的，AAA级客户有多少个"},
        ],
    },
    {
        "id": "MT11", "desc": "货类贡献TOP-N", "domain": "客户",
        "rounds": [
            {"input": "上个月散粮品类的客户贡献TOP5是哪些企业", "clarify_slots": ["output_complexity"]},
            {"input": "看月度数据就行，不是累计的"},
        ],
    },
    # ── 资产管理域 ────────────────────────────────────────────
    {
        "id": "MT12", "desc": "固定资产概况+区域", "domain": "资产",
        "rounds": [
            {"input": "营口港区去年的固定资产总量和折旧率是多少", "clarify_slots": ["output_complexity"]},
            {"input": "就看数字，简单表格"},
        ],
    },
    {
        "id": "MT13", "desc": "设备状态", "domain": "资产",
        "rounds": [
            {"input": "今年港口设备的正常运行率和报废率分别是多少"},
            {"input": "全港的，不分港区"},
        ],
    },
    # ── 投资管理域 ────────────────────────────────────────────
    {
        "id": "MT14", "desc": "资本类计划执行率", "domain": "投资",
        "rounds": [
            {"input": "今年资本类投资项目的计划完成率怎么样", "clarify_slots": ["output_complexity"]},
            {"input": "全港的数据，按月看进度趋势"},
        ],
    },
    {
        "id": "MT15", "desc": "月度进度计划vs实际", "domain": "投资",
        "rounds": [
            {"input": "帮我拉一下1到6月的全港投资月度进度，看计划和实际完成额的对比"},
        ],
    },
    # ── 跨域 & 综合 ──────────────────────────────────────────
    {
        "id": "MT16", "desc": "生产+市场占比趋势+归因", "domain": "跨域",
        "rounds": [
            {"input": "大连港区集装箱在全港吞吐量的市场占比是多少，最近半年的趋势",
             "clarify_slots": ["output_complexity", "attribution_needed"]},
            {"input": "出个图文分析，需要归因分析下占比变化的原因"},
        ],
    },
    {
        "id": "MT17", "desc": "三域年度报告(3轮)", "domain": "综合",
        "rounds": [
            {"input": "帮我做一份2025年度港口经营分析报告",
             "clarify_slots": ["output_format", "attribution_needed"]},
            {"input": "PPT格式，涵盖生产运营、市场和投资三个板块",
             "clarify_slots": ["predictive_needed"]},
            {"input": "要归因分析，不需要预测"},
        ],
    },
    # ── 修正 & 特殊场景 ──────────────────────────────────────
    {
        "id": "MT18", "desc": "用户修正主体+区域", "domain": "生产",
        "rounds": [
            {"input": "看看大连港区上个月的油化品库存"},
            {"input": "不对，我要看散杂货的，而且改成营口港区"},
        ],
    },
    {
        "id": "MT19", "desc": "否定式退回取消归因", "domain": "生产",
        "rounds": [
            {"input": "分析一下上个月各港区吞吐量下降的原因"},
            {"input": "归因就不需要了，直接给我一个对比数据表就行"},
        ],
    },
    {
        "id": "MT20", "desc": "Bypass+主题切换(3轮)", "domain": "投资",
        "rounds": [
            {"input": "看看港口运营数据", "bypass": False},
            {"input": "按你理解执行", "bypass": True},
            {"input": "算了，我想看今年在建的资本类投资项目进展情况"},
        ],
    },
]


# ═══════════════════════════════════════════════════════════════
#  边界探测场景
# ═══════════════════════════════════════════════════════════════

BOUNDARY_DATASET = [
    ("港口情况", "歧义输入", "BP-AMB01"),
    ("上个月的报表", "歧义输入", "BP-AMB02"),
    ("运营数据看看", "歧义输入", "BP-AMB03"),
    ("比去年好吗", "歧义输入", "BP-AMB04"),
    ("最新的", "歧义输入", "BP-AMB05"),

    ("从去年国庆到今年春节期间的集装箱吞吐量", "复杂时间", "BP-TIME01"),
    ("最近两个季度大连港的泊位利用率变化", "复杂时间", "BP-TIME02"),
    ("2024年Q3到2025年Q1的散杂货月度趋势", "复杂时间", "BP-TIME03"),
    ("上半年和去年同期的吞吐量对比", "复杂时间", "BP-TIME04"),
    ("前年全年的投资完成率", "复杂时间", "BP-TIME05"),
    ("入冬以来商品车港存量变化", "复杂时间", "BP-TIME06"),

    ("TEU的外贸内贸比例是多少", "行业术语", "BP-JARG01"),
    ("散改集的增速怎么样", "行业术语", "BP-JARG02"),
    ("岸桥单机效率和去年同期比", "行业术语", "BP-JARG03"),
    ("在泊船舶的平均停泊时长", "行业术语", "BP-JARG04"),
    ("各港区堆场翻箱率对比", "行业术语", "BP-JARG05"),

    ("快速出一份详细的全港资产分析PPT", "矛盾输入", "BP-CONT01"),
    ("简单看下所有港区所有业务类型的完整对比", "矛盾输入", "BP-CONT02"),
    ("不需要图表的趋势分析", "矛盾输入", "BP-CONT03"),
    ("日度粒度的年度投资完成率报告", "矛盾输入", "BP-CONT04"),

    ("先看吞吐量数据再分析原因最后出个PPT发给领导", "多意图", "BP-MULT01"),
    ("对比集装箱和散杂货的同时看看客户结构变化", "多意图", "BP-MULT02"),
    ("大连港的设备状态和营口港的投资进度放一起看", "多意图", "BP-MULT03"),
    ("TEU增了多少，战略客户贡献多少，资产折旧率变化多少", "多意图", "BP-MULT04"),

    ("Q1的container throughput同比YoY是多少", "混合语言", "BP-LANG01"),
    ("show me大连port的berth utilization rate", "混合语言", "BP-LANG02"),
    ("Monthly trend of 散杂货 since last October", "混合语言", "BP-LANG03"),

    ("它的月度进度怎么样", "指代消解", "BP-REF01"),
    ("这些客户里信用评级最高的是谁", "指代消解", "BP-REF02"),
    ("还是上次那个分析，更新一下数据", "指代消解", "BP-REF03"),
]


# ═══════════════════════════════════════════════════════════════
#  执行引擎
# ═══════════════════════════════════════════════════════════════

async def run_multi_turn_scenario(
    engine: SlotFillingEngine,
    cap: CapturingLLM,
    scenario: dict,
) -> ScenarioResult:
    """执行单个多轮对话场景。"""
    result = ScenarioResult(
        scenario_id=scenario["id"],
        description=scenario["desc"],
        category="multi_turn",
        domain_tag=scenario.get("domain", ""),
    )
    t0 = time.time()

    try:
        slots = make_empty_slots()
        history: list[dict[str, str]] = []

        for rnd_idx, rnd in enumerate(scenario["rounds"]):
            rnd_num = rnd_idx + 1
            user_input = rnd["input"]
            is_bypass = rnd.get("bypass", False)
            clarify_slots = rnd.get("clarify_slots", [])

            cap.clear()

            if is_bypass:
                await engine.handle_bypass(user_input, slots)
                cap.pop_all()
                record = RoundRecord(
                    round_num=rnd_num,
                    user_input=user_input,
                    action="bypass",
                    llm_response="(bypass触发，默认填充)",
                    slots_snapshot=slots_to_dict(slots),
                )
                result.rounds.append(record)
                history.extend([
                    {"role": "user", "content": user_input},
                    {"role": "assistant", "content": "好的，按我的理解为您分析。"},
                ])
            else:
                slots = await engine.extract_slots_from_text(user_input, slots, history)
                extract_ixns = cap.pop_all()

                # 提取 LLM 返回的 JSON
                llm_resp = ""
                if extract_ixns:
                    llm_resp = extract_ixns[0].cleaned_response

                # 追问
                clarify_q = None
                if clarify_slots:
                    result.has_clarification = True
                    if len(clarify_slots) == 1:
                        clarify_q = await engine.generate_clarification_question(
                            clarify_slots[0], slots
                        )
                    else:
                        clarify_q = await engine.generate_multi_slot_clarification(
                            clarify_slots, slots
                        )
                    cap.pop_all()  # 清空追问的 LLM 交互

                record = RoundRecord(
                    round_num=rnd_num,
                    user_input=user_input,
                    action="extract",
                    llm_response=llm_resp,
                    clarification_question=clarify_q,
                    slots_snapshot=slots_to_dict(slots),
                )
                result.rounds.append(record)

                history.append({"role": "user", "content": user_input})
                if clarify_q:
                    history.append({"role": "assistant", "content": clarify_q})
                else:
                    history.append({"role": "assistant", "content": "好的，已理解。"})

        result.final_slots = slots_to_dict(slots)

    except Exception as e:
        result.error = str(e)

    result.elapsed_sec = time.time() - t0
    return result


async def run_boundary_probe(
    engine: SlotFillingEngine,
    cap: CapturingLLM,
    user_input: str,
    category: str,
    case_id: str,
) -> ScenarioResult:
    """执行单个边界探测场景。"""
    result = ScenarioResult(
        scenario_id=case_id,
        description=user_input,
        category="boundary",
        domain_tag=category,
    )
    t0 = time.time()

    try:
        cap.clear()
        slots = make_empty_slots()
        slots = await engine.extract_slots_from_text(user_input, slots, [])
        ixns = cap.pop_all()

        llm_resp = ixns[0].cleaned_response if ixns else ""

        record = RoundRecord(
            round_num=1,
            user_input=user_input,
            action="extract",
            llm_response=llm_resp,
            slots_snapshot=slots_to_dict(slots),
        )
        result.rounds.append(record)
        result.final_slots = slots_to_dict(slots)

    except Exception as e:
        result.error = str(e)

    result.elapsed_sec = time.time() - t0
    return result


# ═══════════════════════════════════════════════════════════════
#  Markdown 报告生成 — 精简版
# ═══════════════════════════════════════════════════════════════

def _compute_delta(prev: dict[str, dict], curr: dict[str, dict]) -> dict[str, dict]:
    """计算两轮之间的槽位变更 (新增 + 修改)。"""
    delta = {}
    for k, v in curr.items():
        if k not in prev:
            delta[k] = v
        elif prev[k]["value"] != v["value"]:
            delta[k] = v
    return delta


def _compact_value(val: str, maxlen: int = 50) -> str:
    """紧凑显示值。"""
    val = val.replace("\n", " ").strip()
    return val[:maxlen] + ".." if len(val) > maxlen else val


def _compact_llm_json(raw: str, maxlen: int = 200) -> str:
    """紧凑显示 LLM 返回的 JSON。"""
    s = raw.replace("\n", " ").replace("  ", " ").strip()
    return s[:maxlen] + ".." if len(s) > maxlen else s


def generate_markdown(
    mt_results: list[ScenarioResult],
    bd_results: list[ScenarioResult],
    total_elapsed: float,
) -> str:
    lines: list[str] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 标题 ─────────────────────────────────────────────────
    lines.append("# Phase 1 感知层测试报告")
    lines.append("")
    lines.append(f"> 生成时间: {now_str}  ")
    lines.append(f"> 总耗时: {total_elapsed:.1f}s  ")
    lines.append(f"> 多轮场景: {len(mt_results)} 个 | 边界探测: {len(bd_results)} 个")
    lines.append("")

    # ── 1. 汇总 ──────────────────────────────────────────────
    lines.append("## 1. 汇总")
    lines.append("")

    # 多轮汇总表
    mt_ok = sum(1 for r in mt_results if r.error is None)
    mt_clarify = sum(1 for r in mt_results if r.has_clarification)
    lines.append(f"**多轮对话**: 成功 {mt_ok}/{len(mt_results)} | 追问 {mt_clarify}/{len(mt_results)}")
    lines.append("")
    lines.append("| ID | 域 | 场景 | 轮次 | 追问 | 耗时 | 填充槽数 |")
    lines.append("|---|---|---|---|---|---|---|")
    for r in mt_results:
        clarify = "Y" if r.has_clarification else "-"
        status = f"{r.elapsed_sec:.1f}s" if r.error is None else "ERROR"
        filled = len(r.final_slots)
        lines.append(f"| {r.scenario_id} | {r.domain_tag} | {r.description} | {len(r.rounds)} | {clarify} | {status} | {filled} |")
    lines.append("")

    # 边界汇总表
    bd_ok = sum(1 for r in bd_results if r.error is None)
    bd_filled_avg = 0.0
    if bd_ok > 0:
        bd_filled_avg = sum(len(r.final_slots) for r in bd_results if r.error is None) / bd_ok

    lines.append(f"**边界探测**: 成功 {bd_ok}/{len(bd_results)} | 平均填充 {bd_filled_avg:.1f} 个槽")
    lines.append("")

    by_cat: dict[str, list[ScenarioResult]] = defaultdict(list)
    for r in bd_results:
        by_cat[r.domain_tag].append(r)

    lines.append("| 类别 | 条数 | 平均填充 | 主体提取率 | 时间提取率 |")
    lines.append("|---|---|---|---|---|")
    for cat, items in by_cat.items():
        n = len(items)
        avg_fill = sum(len(r.final_slots) for r in items) / n
        sub_rate = sum(1 for r in items if "analysis_subject" in r.final_slots) / n
        time_rate = sum(1 for r in items if "time_range" in r.final_slots) / n
        lines.append(f"| {cat} | {n} | {avg_fill:.1f} | {sub_rate:.0%} | {time_rate:.0%} |")
    lines.append("")

    # ── 2. 多轮对话详情 ─────────────────────────────────────
    lines.append("---")
    lines.append("## 2. 多轮对话详情")
    lines.append("")

    for res in mt_results:
        lines.append(f"### {res.scenario_id}: {res.description}")
        lines.append("")
        if res.error:
            lines.append(f"**ERROR**: `{res.error}`")
            lines.append("")
            continue

        clarify_tag = f"追问{sum(1 for r in res.rounds if r.clarification_question)}次" if res.has_clarification else "无追问"
        lines.append(f"{len(res.rounds)}轮 | {res.elapsed_sec:.1f}s | {clarify_tag} | 域:{res.domain_tag}")
        lines.append("")

        prev_snapshot: dict[str, dict] = {}

        for rnd in res.rounds:
            lines.append(f"**R{rnd.round_num}** 用户: {rnd.user_input}")

            # LLM 提取结果 (精简 JSON)
            if rnd.llm_response and rnd.action == "extract":
                lines.append(f"  LLM提取: `{_compact_llm_json(rnd.llm_response)}`")

            # 追问
            if rnd.clarification_question:
                lines.append(f"  追问: {rnd.clarification_question}")

            # Delta 槽位表
            delta = _compute_delta(prev_snapshot, rnd.slots_snapshot)
            if delta:
                lines.append("")
                lines.append("| 本轮变更 | 值 | 来源 |")
                lines.append("|---|---|---|")
                for k, info in delta.items():
                    label = _slot_label(k)
                    val = _compact_value(info["value"])
                    src = _source_label(info["source"])
                    lines.append(f"| {label} | {val} | {src} |")

            lines.append("")
            prev_snapshot = dict(rnd.slots_snapshot)

        # 最终槽位
        if res.final_slots:
            lines.append("**最终槽位**:")
            lines.append("")
            lines.append("| 槽位 | 值 | 来源 | 确认 |")
            lines.append("|---|---|---|---|")
            for k, info in res.final_slots.items():
                label = _slot_label(k)
                val = _compact_value(info["value"])
                src = _source_label(info["source"])
                conf = "Y" if info["confirmed"] else ""
                lines.append(f"| {label} | {val} | {src} | {conf} |")
            lines.append("")

        lines.append("---")
        lines.append("")

    # ── 3. 边界探测详情 ─────────────────────────────────────
    lines.append("## 3. 边界探测详情")
    lines.append("")

    for cat, items in by_cat.items():
        lines.append(f"### {cat} ({len(items)}条)")
        lines.append("")

        # 表头：ID | 输入 | 填充数 | 各主要槽位
        lines.append("| ID | 输入 | 填充 | 分析对象 | 时间范围 | 复杂度 | 领域 | LLM提取摘要 |")
        lines.append("|---|---|---|---|---|---|---|---|")

        for res in items:
            if res.error:
                lines.append(f"| {res.scenario_id} | {res.description} | ERR | - | - | - | - | `{res.error[:30]}` |")
                continue

            filled = len(res.final_slots)
            subj = _compact_value(res.final_slots.get("analysis_subject", {}).get("value", "-"), 20)
            tr = _compact_value(res.final_slots.get("time_range", {}).get("value", "-"), 20)
            oc = res.final_slots.get("output_complexity", {}).get("value", "-")
            dom = res.final_slots.get("domain", {}).get("value", "-")

            # LLM 提取摘要
            llm_summary = ""
            if res.rounds and res.rounds[0].llm_response:
                llm_summary = _compact_llm_json(res.rounds[0].llm_response, 60)

            lines.append(f"| {res.scenario_id} | {res.description} | {filled} | {subj} | {tr} | {oc} | {dom} | `{llm_summary}` |")

        lines.append("")
        lines.append("---")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

async def main():
    api_base = os.environ.get("QWEN_API_BASE")
    api_key = os.environ.get("QWEN_API_KEY")
    model = os.environ.get("QWEN_MODEL", "Qwen3-235B")
    if not api_base or not api_key:
        print("ERROR: QWEN_API_BASE/QWEN_API_KEY 未设置")
        sys.exit(1)

    real_llm = ChatOpenAI(
        base_url=api_base,
        api_key=api_key,
        model=model,
        temperature=0.1,
        request_timeout=120,
    )
    cap = CapturingLLM(real_llm)
    engine = SlotFillingEngine(llm=cap, max_clarification_rounds=3, llm_timeout=120.0)

    total_t0 = time.time()

    # ── 执行多轮场景 ────────────────────────────────────────
    print(f"=== 开始多轮对话场景 ({len(MULTI_TURN_SCENARIOS)} 个) ===")
    mt_results: list[ScenarioResult] = []
    for i, scenario in enumerate(MULTI_TURN_SCENARIOS):
        sid = scenario["id"]
        print(f"  [{i+1}/{len(MULTI_TURN_SCENARIOS)}] {sid}: {scenario['desc']} ...", end=" ", flush=True)
        res = await run_multi_turn_scenario(engine, cap, scenario)
        status = "OK" if res.error is None else f"ERROR: {res.error[:50]}"
        print(f"{status} ({res.elapsed_sec:.1f}s)")
        mt_results.append(res)

    # ── 执行边界探测 ────────────────────────────────────────
    print(f"\n=== 开始边界探测 ({len(BOUNDARY_DATASET)} 个) ===")
    bd_results: list[ScenarioResult] = []
    for i, (user_input, category, case_id) in enumerate(BOUNDARY_DATASET):
        print(f"  [{i+1}/{len(BOUNDARY_DATASET)}] {case_id}: {user_input[:20]} ...", end=" ", flush=True)
        res = await run_boundary_probe(engine, cap, user_input, category, case_id)
        status = "OK" if res.error is None else f"ERROR: {res.error[:50]}"
        print(f"{status} ({res.elapsed_sec:.1f}s)")
        bd_results.append(res)

    total_elapsed = time.time() - total_t0
    print(f"\n=== 全部完成，总耗时 {total_elapsed:.1f}s ===")

    # ── 生成报告 ─────────────────────────────────────────────
    report_md = generate_markdown(mt_results, bd_results, total_elapsed)
    report_path = ROOT / "reports" / "phase1_test_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\n报告已写入: {report_path}")
    print(f"报告行数: {len(report_md.splitlines())}")


if __name__ == "__main__":
    asyncio.run(main())
