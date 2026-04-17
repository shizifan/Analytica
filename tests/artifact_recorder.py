"""E2E Test Artifact Recorder.

Extracts and persists artifacts produced by employee E2E tests:
- Markdown report with perception/planning/execution details
- Generated files: HTML, DOCX, PPTX
- ECharts charts wrapped in standalone HTML

Directory structure:
    reports/e2e_artifacts/{timestamp}/{employee_id}/{query_type}/
        report.md
        {task_id}.html / .docx / .pptx
        chart_{task_id}.html
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("test.artifact_recorder")

PROJECT_ROOT = Path(__file__).parent.parent
ARTIFACTS_BASE = PROJECT_ROOT / "reports" / "e2e_artifacts"

_RUN_TIMESTAMP: str | None = None

CHART_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh">
<head>
  <meta charset="utf-8">
  <title>{title}</title>
  <script src="https://cdn.jsdelivr.net/npm/echarts@5/dist/echarts.min.js"></script>
  <style>
    body {{ margin: 0; padding: 20px; background: #fff; }}
    #chart {{ width: 100%; height: 600px; }}
  </style>
</head>
<body>
  <div id="chart"></div>
  <script>
    var chart = echarts.init(document.getElementById('chart'));
    chart.setOption({option_json});
    window.addEventListener('resize', function() {{ chart.resize(); }});
  </script>
</body>
</html>
"""


def _get_run_timestamp() -> str:
    global _RUN_TIMESTAMP
    if _RUN_TIMESTAMP is None:
        _RUN_TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
    return _RUN_TIMESTAMP


def _get_run_dir() -> Path:
    return ARTIFACTS_BASE / _get_run_timestamp()


# ── File artifact extraction ────────────────────────────────


def _save_file_artifact(
    output_dir: Path, task_id: str, output: Any,
) -> str | None:
    """Save a file-type SkillOutput to disk. Returns filename or None."""
    fmt = output.metadata.get("format", "")
    data = output.data

    if data is None:
        logger.warning("[%s] output_type=file but data is None", task_id)
        return None

    if fmt == "html":
        if not isinstance(data, str):
            logger.warning("[%s] HTML data is not str: %s", task_id, type(data))
            return None
        filename = f"{task_id}.html"
        (output_dir / filename).write_text(data, encoding="utf-8")
        return filename

    if fmt in ("docx", "pptx"):
        if not isinstance(data, (bytes, bytearray)):
            logger.warning("[%s] %s data is not bytes: %s", task_id, fmt, type(data))
            return None
        filename = f"{task_id}.{fmt}"
        (output_dir / filename).write_bytes(data)
        return filename

    # Unknown format — save as binary if bytes, skip otherwise
    if isinstance(data, (bytes, bytearray)):
        filename = f"{task_id}.bin"
        (output_dir / filename).write_bytes(data)
        return filename

    logger.warning("[%s] Unknown file format '%s', skipping", task_id, fmt)
    return None


def _save_chart_artifact(
    output_dir: Path, task_id: str, output: Any,
) -> str | None:
    """Wrap ECharts JSON in standalone HTML. Returns filename or None."""
    data = output.data
    if not isinstance(data, dict):
        logger.warning("[%s] chart data is not dict: %s", task_id, type(data))
        return None

    title_obj = data.get("title", {})
    if isinstance(title_obj, dict):
        title = title_obj.get("text", f"Chart {task_id}")
    else:
        title = f"Chart {task_id}"

    option_json = json.dumps(data, ensure_ascii=False, default=str)
    html = CHART_HTML_TEMPLATE.format(title=title, option_json=option_json)

    filename = f"chart_{task_id}.html"
    (output_dir / filename).write_text(html, encoding="utf-8")
    return filename


# ── Markdown report generation ──────────────────────────────


def _render_slots_table(intent: dict) -> str:
    """Render structured_intent slots as Markdown table."""
    slots = intent.get("slots", {})
    if not slots:
        return "_No slots extracted_\n"

    lines = ["| Slot | Value | Source |", "|------|-------|--------|"]
    for name, val in slots.items():
        if isinstance(val, dict):
            v = val.get("value", str(val))
            src = val.get("source", val.get("evidence", "-"))
        else:
            v = str(val)
            src = "-"
        lines.append(f"| {name} | {v} | {src} |")
    return "\n".join(lines) + "\n"


def _render_plan_table(plan: dict) -> str:
    """Render analysis_plan tasks as Markdown table."""
    tasks = plan.get("tasks", [])
    if not tasks:
        return "_No tasks in plan_\n"

    lines = ["| # | Task ID | Type | Skill | Name |",
             "|---|---------|------|-------|------|"]
    for i, t in enumerate(tasks, 1):
        tid = t.get("task_id", "?")
        ttype = t.get("type", "?")
        skill = t.get("skill", "-")
        name = t.get("name", "-")
        lines.append(f"| {i} | {tid} | {ttype} | {skill} | {name} |")
    return "\n".join(lines) + "\n"


def _render_task_content(
    task_id: str, output: Any, saved_files: dict[str, str],
) -> str:
    """Render per-task execution detail for Markdown."""
    status_icon = "done" if output.status == "success" else output.status
    lines = [
        f"- **Skill**: `{output.skill_id}`",
        f"- **Status**: {status_icon}",
        f"- **Output Type**: `{output.output_type}`",
    ]

    if output.status == "failed":
        lines.append(f"- **Error**: {output.error_message or 'Unknown error'}")
        return "\n".join(lines)

    otype = output.output_type
    data = output.data

    if otype == "text" and isinstance(data, str):
        truncated = data[:800] + ("..." if len(data) > 800 else "")
        lines.append(f"- **Content**:\n\n> {truncated}\n")

    elif otype == "json" and isinstance(data, dict):
        narrative = data.get("narrative", "")
        if narrative:
            truncated = narrative[:800] + ("..." if len(narrative) > 800 else "")
            lines.append(f"- **Narrative**:\n\n> {truncated}\n")
        else:
            keys = list(data.keys())
            lines.append(f"- **JSON Keys**: {keys}")

    elif otype == "dataframe":
        meta = output.metadata
        rows = meta.get("rows", "?")
        cols = meta.get("columns", [])
        endpoint = meta.get("endpoint", "")
        query_params = meta.get("query_params", {})

        if endpoint:
            lines.append(f"- **API**: `{endpoint}`")
        if query_params:
            params_str = ", ".join(f"{k}={v}" for k, v in query_params.items())
            lines.append(f"- **Params**: {params_str}")

        lines.append(f"- **DataFrame**: {rows} rows x {len(cols)} columns")
        if cols:
            lines.append(f"- **Columns**: {', '.join(str(c) for c in cols[:15])}")

        # Data preview (truncate at 100 rows)
        df = output.data
        if df is not None:
            import pandas as pd
            if isinstance(df, pd.DataFrame) and not df.empty:
                preview_n = min(len(df), 100)
                preview_df = df.head(preview_n)
                truncated_note = f" (showing {preview_n}/{len(df)})" if len(df) > 100 else ""
                lines.append(f"\n**Data Preview**{truncated_note}:\n")
                # Manual markdown table (no tabulate dependency)
                col_names = list(preview_df.columns)
                lines.append("| " + " | ".join(str(c) for c in col_names) + " |")
                lines.append("| " + " | ".join("---" for _ in col_names) + " |")
                for _, row in preview_df.iterrows():
                    lines.append("| " + " | ".join(str(row[c]) for c in col_names) + " |")

    elif otype == "chart":
        fname = saved_files.get(task_id)
        if fname:
            lines.append(f"- **Chart**: [{fname}](./{fname})")
        else:
            lines.append("- **Chart**: (save failed)")

    elif otype == "file":
        fname = saved_files.get(task_id)
        fmt = output.metadata.get("format", "?")
        size = output.metadata.get("file_size_bytes", "")
        size_str = f" ({size} bytes)" if size else ""
        if fname:
            lines.append(f"- **File**: [{fname}](./{fname}) [{fmt}]{size_str}")
        else:
            lines.append(f"- **File**: (save failed) [{fmt}]")

    else:
        lines.append(f"- **Data type**: {type(data).__name__}")

    return "\n".join(lines)


def _build_report_markdown(
    employee_id: str,
    query_type: str,
    user_message: str,
    state: dict,
    task_statuses: dict[str, str],
    execution_context: dict[str, Any],
    needs_replan: bool,
    saved_files: dict[str, str],
) -> str:
    """Generate the complete report.md content."""
    timestamp = _get_run_timestamp()
    intent = state.get("structured_intent") or {}
    plan = state.get("analysis_plan") or {}
    messages = state.get("messages", [])

    total = len(task_statuses)
    success_count = sum(1 for v in task_statuses.values() if v == "done")
    failed_count = total - success_count

    sections = []

    # Header
    sections.append(f"# {employee_id} / {query_type}\n")
    sections.append(f"**Timestamp**: {timestamp}\n")

    # 1. User query
    sections.append("## 1. User Query\n")
    sections.append(f"> {user_message}\n")

    # 2. Perception results
    sections.append("## 2. Perception Results\n")
    if intent:
        goal = intent.get("analysis_goal", "-")
        sections.append(f"**Analysis Goal**: {goal}\n")
        sections.append("### Extracted Slots\n")
        sections.append(_render_slots_table(intent))
    else:
        sections.append("_Perception did not produce structured_intent_\n")

    # 3. Analysis plan
    sections.append("## 3. Analysis Plan\n")
    if plan:
        sections.append(f"**Title**: {plan.get('title', '-')}\n")
        sections.append(f"**Task Count**: {len(plan.get('tasks', []))}\n")
        est = plan.get("estimated_duration", 0)
        if est:
            sections.append(f"**Estimated Duration**: {est}s\n")
        sections.append("### Task List\n")
        sections.append(_render_plan_table(plan))
    else:
        sections.append("_No analysis plan produced_\n")

    # 4. Execution results
    sections.append("## 4. Execution Results\n")
    sections.append("### Overall Statistics\n")
    sections.append(f"- **Total Tasks**: {total}\n")
    sections.append(f"- **Succeeded**: {success_count}\n")
    sections.append(f"- **Failed**: {failed_count}\n")
    sections.append(f"- **Needs Replan**: {needs_replan}\n")

    sections.append("### Per-Task Details\n")
    for task_id, status in task_statuses.items():
        task_name = task_id
        # Try to find task name from plan
        for t in plan.get("tasks", []):
            if t.get("task_id") == task_id:
                task_name = t.get("name", task_id)
                break

        sections.append(f"#### Task: {task_id} -- {task_name}\n")
        if task_id in execution_context:
            output = execution_context[task_id]
            sections.append(_render_task_content(task_id, output, saved_files))
        else:
            sections.append(f"- **Status**: {status}\n- _No output in context_")
        sections.append("")

    # 5. Generated files
    if saved_files:
        sections.append("## 5. Generated Files\n")
        sections.append("| File | Type | Size |")
        sections.append("|------|------|------|")
        for tid, fname in saved_files.items():
            fpath = _get_run_dir() / employee_id / query_type / fname
            size = fpath.stat().st_size if fpath.exists() else "?"
            ext = Path(fname).suffix.lstrip(".")
            sections.append(f"| [{fname}](./{fname}) | {ext} | {size} bytes |")
        sections.append("")

    # 6. Conversation messages
    sections.append("## 6. Conversation Messages\n")
    for msg in messages:
        role = msg.get("role", "?")
        content = msg.get("content", "")
        if isinstance(content, str):
            truncated = content[:1500] + ("..." if len(content) > 1500 else "")
        else:
            truncated = str(content)[:1500]
        sections.append(f"**{role}**:\n\n{truncated}\n")
        sections.append("---\n")

    return "\n".join(sections)


# ── Public API ──────────────────────────────────────────────


def record_test_artifacts(
    employee_id: str,
    query_type: str,
    user_message: str,
    state: dict,
    task_statuses: dict[str, str],
    execution_context: dict[str, Any],
    needs_replan: bool,
) -> Path:
    """Record all test artifacts to disk.

    Creates:
        reports/e2e_artifacts/{timestamp}/{employee_id}/{query_type}/
            report.md
            {task_id}.html / .docx / .pptx
            chart_{task_id}.html

    Returns the output directory path.
    """
    output_dir = _get_run_dir() / employee_id / query_type
    output_dir.mkdir(parents=True, exist_ok=True)

    saved_files: dict[str, str] = {}

    # Extract file artifacts from execution_context
    for task_id, output in execution_context.items():
        try:
            otype = getattr(output, "output_type", None)
            if otype is None:
                continue

            if otype == "file":
                fname = _save_file_artifact(output_dir, task_id, output)
                if fname:
                    saved_files[task_id] = fname

            elif otype == "chart":
                fname = _save_chart_artifact(output_dir, task_id, output)
                if fname:
                    saved_files[task_id] = fname

        except Exception as e:
            logger.warning("Failed to save artifact for %s: %s", task_id, e)

    # Generate Markdown report
    report_md = _build_report_markdown(
        employee_id=employee_id,
        query_type=query_type,
        user_message=user_message,
        state=state,
        task_statuses=task_statuses,
        execution_context=execution_context,
        needs_replan=needs_replan,
        saved_files=saved_files,
    )
    (output_dir / "report.md").write_text(report_md, encoding="utf-8")

    logger.info(
        "Artifacts saved: %s (%d files + report.md)",
        output_dir, len(saved_files),
    )
    return output_dir
