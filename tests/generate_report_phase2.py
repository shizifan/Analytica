"""独立报告生成脚本 — 运行规划层准确率场景并输出精简 Markdown 报告。

用法:
    uv run python tests/generate_report_phase2.py

输出:
    reports/phase2_test_report.md
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

from backend.agent.planning import PlanningEngine
from backend.agent.endpoints import ENDPOINT_REGISTRY, MCODE_TO_ENDPOINT
from tests.helpers.capturing_llm import CapturingLLM
from tests.accuracy.test_planning_accuracy import (
    PLANNING_ACCURACY_DATASET,
    SCENARIO_IDS,
    validate_plan,
    _extract_endpoints_from_plan,
    _extract_skills_from_plan,
)


# ═══════════════════════════════════════════════════════════════
#  中文映射
# ═══════════════════════════════════════════════════════════════

CATEGORY_LABELS = {
    "A": "单API查询",
    "B": "多API图文",
    "C": "多域报告",
    "D": "歧义消除",
}

DOMAIN_LABELS = {
    "production": "生产运营",
    "market": "市场商务",
    "customer": "客户管理",
    "asset": "资产管理",
    "invest": "投资管理",
}


def _categorize(scenario_id: str) -> str:
    """从场景 ID 提取类别标签。"""
    prefix = scenario_id[0].upper()
    return CATEGORY_LABELS.get(prefix, prefix)


def _endpoint_mcode(ep_name: str) -> str:
    """从端点名获取 M-code。"""
    info = ENDPOINT_REGISTRY.get(ep_name, {})
    return info.get("id", "?")


# ═══════════════════════════════════════════════════════════════
#  数据结构
# ═══════════════════════════════════════════════════════════════

@dataclass
class PlanScenarioResult:
    """单个规划场景结果。"""
    scenario_id: str
    category: str
    analysis_subject: str
    intent: dict
    plan_dict: dict | None = None
    endpoints_used: set[str] = field(default_factory=set)
    skills_used: set[str] = field(default_factory=set)
    task_count: int = 0
    passed: bool = False
    fail_reason: str = ""
    elapsed_sec: float = 0.0
    error: str | None = None


# ═══════════════════════════════════════════════════════════════
#  执行引擎
# ═══════════════════════════════════════════════════════════════

async def run_planning_scenario(
    engine: PlanningEngine,
    cap: CapturingLLM,
    intent: dict,
    rules: dict,
    scenario_id: str,
) -> PlanScenarioResult:
    """执行单个规划场景。"""
    result = PlanScenarioResult(
        scenario_id=scenario_id,
        category=_categorize(scenario_id),
        analysis_subject=intent.get("analysis_subject", ""),
        intent=intent,
    )
    cap.clear()
    t0 = time.time()

    try:
        plan = await engine.generate_plan(intent)
        plan_dict = plan.model_dump()
        result.plan_dict = plan_dict
        result.endpoints_used = _extract_endpoints_from_plan(plan_dict)
        result.skills_used = _extract_skills_from_plan(plan_dict)
        result.task_count = len(plan_dict.get("tasks", []))
        passed, reason = validate_plan(plan_dict, rules)
        result.passed = passed
        result.fail_reason = reason
    except Exception as e:
        result.error = str(e)

    result.elapsed_sec = time.time() - t0
    return result


# ═══════════════════════════════════════════════════════════════
#  Markdown 报告生成
# ═══════════════════════════════════════════════════════════════

def generate_markdown(results: list[PlanScenarioResult], total_elapsed: float) -> str:
    lines: list[str] = []
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    passed_count = sum(1 for r in results if r.passed)
    total = len(results)
    accuracy = passed_count / total if total else 0
    error_count = sum(1 for r in results if r.error)

    # ── 标题 ─────────────────────────────────────────────────
    lines.append("# Phase 2 规划层测试报告")
    lines.append("")
    lines.append(f"> 生成时间: {now_str}  ")
    lines.append(f"> 总耗时: {total_elapsed:.1f}s  ")
    lines.append(f"> 准确率: {passed_count}/{total} = {accuracy:.0%}  ")
    if error_count:
        lines.append(f"> 异常场景: {error_count} 个")
    lines.append("")

    # ── 1. 分类统计 ──────────────────────────────────────────
    lines.append("## 1. 分类统计")
    lines.append("")
    lines.append("| 类别 | 场景数 | 通过 | 失败 | 通过率 | 平均耗时 |")
    lines.append("|---|---|---|---|---|---|")

    by_cat: dict[str, list[PlanScenarioResult]] = defaultdict(list)
    for r in results:
        by_cat[r.category].append(r)

    for cat in ["单API查询", "多API图文", "多域报告", "歧义消除"]:
        items = by_cat.get(cat, [])
        if not items:
            continue
        n = len(items)
        ok = sum(1 for r in items if r.passed)
        fail = n - ok
        rate = ok / n if n else 0
        avg_time = sum(r.elapsed_sec for r in items) / n
        lines.append(f"| {cat} | {n} | {ok} | {fail} | {rate:.0%} | {avg_time:.1f}s |")
    lines.append("")

    # ── 2. 端点覆盖 ──────────────────────────────────────────
    lines.append("## 2. 端点覆盖 (27个)")
    lines.append("")
    lines.append("| 端点 | M-code | 使用次数 | 通过场景 | 域 |")
    lines.append("|---|---|---|---|---|")

    # 统计每个端点被使用的次数和通过次数
    ep_usage: dict[str, int] = defaultdict(int)
    ep_pass: dict[str, int] = defaultdict(int)
    for r in results:
        for ep in r.endpoints_used:
            ep_usage[ep] += 1
            if r.passed:
                ep_pass[ep] += 1

    for ep_name, info in ENDPOINT_REGISTRY.items():
        mcode = info["id"]
        domain = DOMAIN_LABELS.get(info["domain"], info["domain"])
        usage = ep_usage.get(ep_name, 0)
        passed_n = ep_pass.get(ep_name, 0)
        mark = "" if usage > 0 else " **零覆盖**"
        lines.append(f"| {ep_name} | {mcode} | {usage} | {passed_n} | {domain}{mark} |")
    lines.append("")

    covered = sum(1 for ep in ENDPOINT_REGISTRY if ep_usage.get(ep, 0) > 0)
    lines.append(f"**端点覆盖率: {covered}/27 = {covered/27:.0%}**")
    lines.append("")

    # ── 3. 技能使用统计 ──────────────────────────────────────
    lines.append("## 3. 技能使用统计")
    lines.append("")
    skill_usage: dict[str, int] = defaultdict(int)
    for r in results:
        for sk in r.skills_used:
            skill_usage[sk] += 1

    if skill_usage:
        lines.append("| 技能 | 使用次数 |")
        lines.append("|---|---|")
        for sk, cnt in sorted(skill_usage.items(), key=lambda x: -x[1]):
            lines.append(f"| {sk} | {cnt} |")
    else:
        lines.append("*无技能使用记录*")
    lines.append("")

    # ── 4. 场景详情 ──────────────────────────────────────────
    lines.append("---")
    lines.append("## 4. 场景详情")
    lines.append("")

    for r in results:
        status = "✅通过" if r.passed else ("❌异常" if r.error else "❌失败")
        lines.append(f"### {r.scenario_id}: {r.analysis_subject}")
        lines.append(f"类别: {r.category} | 耗时: {r.elapsed_sec:.1f}s | 结果: {status}")
        lines.append("")

        if r.error:
            lines.append(f"**异常**: `{r.error[:200]}`")
            lines.append("")
            continue

        # 意图摘要
        intent_parts = []
        for k in ["domain", "output_format", "time_range", "cargo_type", "analysis_type"]:
            if k in r.intent:
                intent_parts.append(f"{k}={r.intent[k]}")
        if intent_parts:
            lines.append(f"意图: {', '.join(intent_parts)}")
            lines.append("")

        # 任务表
        if r.plan_dict and r.plan_dict.get("tasks"):
            lines.append("| 任务 | 技能 | 端点 | 依赖 |")
            lines.append("|---|---|---|---|")
            for t in r.plan_dict["tasks"]:
                tid = t.get("task_id", "?")
                skill = t.get("skill", "-")
                ep = t.get("params", {}).get("endpoint_id", "")
                ep_display = f"{ep}({_endpoint_mcode(ep)})" if ep else "-"
                deps = ", ".join(t.get("depends_on", [])) or "-"
                lines.append(f"| {tid} | {skill} | {ep_display} | {deps} |")
            lines.append("")

        # 验证结果
        checks = []
        if r.plan_dict:
            checks.append(f"任务数{r.task_count}")
        if r.passed:
            checks.append("全部规则通过")
        elif r.fail_reason:
            checks.append(f"失败: {r.fail_reason}")
        if checks:
            lines.append(f"验证: {' | '.join(checks)}")
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
    engine = PlanningEngine(llm=cap, llm_timeout=120.0, max_retries=3)

    total_t0 = time.time()

    print(f"=== 开始规划层准确率测试 ({len(PLANNING_ACCURACY_DATASET)} 个场景) ===")
    results: list[PlanScenarioResult] = []

    for i, ((intent, rules), scenario_id) in enumerate(
        zip(PLANNING_ACCURACY_DATASET, SCENARIO_IDS)
    ):
        subj = intent.get("analysis_subject", "?")[:30]
        print(f"  [{i+1}/{len(PLANNING_ACCURACY_DATASET)}] {scenario_id}: {subj} ...", end=" ", flush=True)
        res = await run_planning_scenario(engine, cap, intent, rules, scenario_id)
        status = "PASS" if res.passed else ("ERROR" if res.error else "FAIL")
        print(f"{status} ({res.elapsed_sec:.1f}s)")
        results.append(res)

    total_elapsed = time.time() - total_t0

    passed = sum(1 for r in results if r.passed)
    print(f"\n=== 全部完成，总耗时 {total_elapsed:.1f}s ===")
    print(f"准确率: {passed}/{len(results)} = {passed/len(results):.0%}")

    # ── 生成报告 ─────────────────────────────────────────────
    report_md = generate_markdown(results, total_elapsed)
    report_path = ROOT / "reports" / "phase2_test_report.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_md, encoding="utf-8")
    print(f"\n报告已写入: {report_path}")
    print(f"报告行数: {len(report_md.splitlines())}")


if __name__ == "__main__":
    asyncio.run(main())
