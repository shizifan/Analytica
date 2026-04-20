from __future__ import annotations
import json
from pathlib import Path
from backend.models.schemas import AnalysisPlan, TaskItem

TEMPLATE_DIR = Path(__file__).parent

TEMPLATE_REGISTRY: dict[str, str] = {
    "throughput_analyst": "throughput_analyst_monthly_review.json",
    "customer_insight":   "customer_insight_strategic_contribution.json",
    "asset_investment":   "asset_investment_equipment_ops.json",
}

def _load_raw(employee_id: str) -> dict:
    filename = TEMPLATE_REGISTRY.get(employee_id)
    if not filename:
        raise ValueError(f"No template for employee: {employee_id}")
    return json.loads((TEMPLATE_DIR / filename).read_text(encoding="utf-8"))

def load_template(employee_id: str) -> AnalysisPlan:
    raw = _load_raw(employee_id)
    tasks = [
        TaskItem(
            task_id=t["task_id"], type=t["type"], name=t["name"],
            description=t.get("description", ""), depends_on=t.get("depends_on", []),
            skill=t["skill"], params=t.get("params", {}),
            estimated_seconds=t.get("estimated_seconds", 10),
            status=t.get("status", "pending"), output_ref=t.get("output_ref", ""),
        )
        for t in raw.get("tasks", [])
    ]
    return AnalysisPlan(
        plan_id=raw.get("plan_id", f"tpl-{employee_id}"),
        version=raw.get("version", 1),
        title=raw.get("title", ""),
        analysis_goal=raw.get("analysis_goal", ""),
        estimated_duration=raw.get("estimated_duration", 180),
        tasks=tasks,
        report_structure=raw.get("report_structure"),
        revision_log=raw.get("revision_log", []),
    )

def get_template_meta(employee_id: str) -> dict:
    return _load_raw(employee_id).get("_meta", {})

def match_template(employee_id: str, raw_query: str, complexity: str) -> AnalysisPlan | None:
    if complexity != "full_report" or employee_id not in TEMPLATE_REGISTRY:
        return None
    keywords = get_template_meta(employee_id).get("trigger_keywords", [])
    if any(kw in raw_query for kw in keywords):
        return load_template(employee_id)
    return None

def get_template_skeleton(employee_id: str) -> str:
    raw = _load_raw(employee_id)
    tasks = raw.get("tasks", [])
    sections = raw.get("report_structure", {}).get("sections", [])
    lines = [f"模板标题: {raw.get('title', '')}", f"任务数: {len(tasks)}", "", "任务链:"]
    for t in tasks:
        deps = ", ".join(t.get("depends_on", [])) or "—"
        ep = t.get("params", {}).get("endpoint_id", "")
        lines.append(
            f"  {t['task_id']} | {t['type']:12s} | {t['skill']:25s} | [{deps}] | {t['name']}"
            + (f" (API:{ep})" if ep else "")
        )
    if sections:
        lines += ["", "章节结构:"]
        for s in sections:
            lines.append(f"  {s['name']} → [{', '.join(s.get('task_refs', []))}]")
    return "\n".join(lines)
