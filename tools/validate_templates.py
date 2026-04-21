"""Template governance: discover real API schemas and validate templates.

Runs every data_fetch task declared in a JSON plan template against the mock
server, then cross-checks every ``params.config`` field reference
(x_field / y_field / category_field / value_field / series_by / filter keys,
series.target / series.actual / series.label, left_y.source + y_field + series_by,
right_y.source + y_field + series_by) against the real response columns and
distinct categorical values.

Usage::

    uv run python tools/validate_templates.py
    uv run python tools/validate_templates.py --template throughput_analyst_monthly_review
    uv run python tools/validate_templates.py --fix        # auto-patch when unambiguous

The report is printed to stdout as a deterministic, stable table so diffing
between runs surfaces regressions.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from unittest.mock import patch
from urllib.parse import urlparse

import httpx
import pandas as pd

# Make ``backend.*`` and ``mock_server.*`` importable when invoked as a script
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.agent.execution import execute_plan
from backend.models.schemas import TaskItem
from backend.skills.loader import load_all_skills

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
load_all_skills()

TEMPLATES_DIR = ROOT / "backend" / "agent" / "plan_templates"


# ---------------------------------------------------------------------------
# Mock-server gateway patch (shared with test_json_template_execution)
# ---------------------------------------------------------------------------

def _mock_gateway():
    from mock_server.mock_server_all import app as mock_app

    transport = httpx.ASGITransport(app=mock_app)
    OrigClient = httpx.AsyncClient

    class _Patched(OrigClient):
        async def get(self, url, **kwargs):
            if "/api/gateway/" in str(url):
                parsed = urlparse(str(url))
                async with OrigClient(transport=transport, base_url="http://testserver") as mc:
                    return await mc.get(parsed.path, **kwargs)
            return await super().get(url, **kwargs)

        async def post(self, url, **kwargs):
            if "/api/gateway/" in str(url):
                parsed = urlparse(str(url))
                async with OrigClient(transport=transport, base_url="http://testserver") as mc:
                    return await mc.post(parsed.path, **kwargs)
            return await super().post(url, **kwargs)

    return patch("backend.skills.data.api_fetch.httpx.AsyncClient", _Patched)


# ---------------------------------------------------------------------------
# Discovery: run every data_fetch task and capture schemas
# ---------------------------------------------------------------------------

@dataclass
class TaskSchema:
    task_id: str
    endpoint_id: str
    columns: list[str]
    rows: int
    distinct: dict[str, set[str]]  # column -> top distinct string values
    status: str
    error: str | None = None


async def discover_schemas(template: dict[str, Any]) -> dict[str, TaskSchema]:
    """Run every data_fetch task in *template* against the mock server and
    return ``task_id -> TaskSchema`` for the successful ones (failed tasks
    also recorded with status='failed' so templates can be blamed cleanly)."""
    fetch_tasks = [t for t in template.get("tasks", []) if t["type"] == "data_fetch"]
    items = [
        TaskItem(
            task_id=t["task_id"],
            type=t["type"],
            name=t["name"],
            skill=t["skill"],
            params=t.get("params", {}),
            depends_on=[],  # drop deps for independent discovery
            estimated_seconds=5,
        )
        for t in fetch_tasks
    ]

    with _mock_gateway():
        statuses, context, _ = await execute_plan(items)

    schemas: dict[str, TaskSchema] = {}
    for t in items:
        out = context.get(t.task_id)
        status = statuses.get(t.task_id, "unknown")
        if not out or status != "done":
            schemas[t.task_id] = TaskSchema(
                task_id=t.task_id,
                endpoint_id=t.params.get("endpoint_id", ""),
                columns=[],
                rows=0,
                distinct={},
                status=status,
                error=(out.error_message if out else "(no output)"),
            )
            continue

        data = out.data
        if isinstance(data, pd.DataFrame) and not data.empty:
            distinct: dict[str, set[str]] = {}
            for col in data.columns:
                if data[col].dtype == "object":
                    vals = data[col].dropna().astype(str).unique()
                    if len(vals) <= 20:
                        distinct[col] = set(vals)
            schemas[t.task_id] = TaskSchema(
                task_id=t.task_id,
                endpoint_id=t.params.get("endpoint_id", ""),
                columns=list(data.columns),
                rows=len(data),
                distinct=distinct,
                status="done",
            )
        else:
            schemas[t.task_id] = TaskSchema(
                task_id=t.task_id,
                endpoint_id=t.params.get("endpoint_id", ""),
                columns=[],
                rows=0,
                distinct={},
                status="done",
                error="non-DataFrame output",
            )
    return schemas


# ---------------------------------------------------------------------------
# Validation: check field references against discovered schemas
# ---------------------------------------------------------------------------

@dataclass
class Finding:
    task_id: str
    path: str         # dotted path within params, e.g. ``config.x_field``
    declared: str     # what the template says
    issue: str        # short error code
    suggestion: str = ""  # best-guess fix, if deterministic


def _upstream_task_ids(task: dict, context_tasks: dict[str, dict]) -> list[str]:
    """Return candidate upstream task ids. Prefer explicit ``depends_on``,
    falling back to ``params.data_refs`` / ``params.source``."""
    out = list(task.get("depends_on") or [])
    p = task.get("params") or {}
    refs = p.get("data_refs") or []
    for r in refs:
        if r not in out and r in context_tasks:
            out.append(r)
    src = (p.get("config") or {}).get("source")
    if src and src not in out and src in context_tasks:
        out.append(src)
    return out


def _columns_available(upstream: list[str], schemas: dict[str, TaskSchema]) -> tuple[set[str], dict[str, set[str]]]:
    """Union of columns and per-column distinct values across upstream tasks."""
    cols: set[str] = set()
    distinct: dict[str, set[str]] = {}
    for tid in upstream:
        s = schemas.get(tid)
        if not s:
            continue
        cols.update(s.columns)
        for k, v in s.distinct.items():
            distinct.setdefault(k, set()).update(v)
    return cols, distinct


def _suggest_column(declared: str, available: set[str]) -> str:
    """Suggest the closest available column name for a declared one."""
    if not declared or not available:
        return ""
    # Normalise: strip case and non-alphanum
    def norm(s: str) -> str:
        return re.sub(r"[^a-z0-9]", "", s.lower())
    nd = norm(declared)
    scored = sorted(
        available,
        key=lambda c: (-_score(nd, norm(c)), c),
    )
    return scored[0] if scored else ""


def _score(a: str, b: str) -> float:
    """Cheap similarity score in [0, 1] based on shared contiguous substrings."""
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    # Character overlap + length-normalised
    common = sum(1 for c in set(a) if c in b)
    base = common / max(len(set(a) | set(b)), 1)
    # Bonus if one contains the other
    if a in b or b in a:
        base += 0.3
    return min(base, 1.0)


def _check_field(
    declared: Any,
    available: set[str],
    task_id: str,
    path: str,
    findings: list[Finding],
    *,
    required: bool = True,
) -> None:
    """Check a single field reference; append Finding if invalid."""
    if not declared:
        if required:
            findings.append(Finding(
                task_id=task_id, path=path, declared="(empty)",
                issue="missing_required",
            ))
        return
    if not isinstance(declared, str):
        return
    if declared in available:
        return
    suggestion = _suggest_column(declared, available)
    findings.append(Finding(
        task_id=task_id, path=path, declared=declared,
        issue="unknown_column",
        suggestion=suggestion,
    ))


def _check_filter(
    filter_dict: dict,
    cols: set[str],
    distinct: dict[str, set[str]],
    task_id: str,
    findings: list[Finding],
) -> None:
    """Filter dict references both keys (must be columns) and values (should
    exist in distinct values for categorical columns)."""
    for k, v in filter_dict.items():
        path = f"config.filter.{k}"
        if k not in cols:
            findings.append(Finding(
                task_id=task_id, path=path, declared=k,
                issue="unknown_filter_column",
                suggestion=_suggest_column(k, cols),
            ))
            continue
        distinct_vals = distinct.get(k, set())
        if distinct_vals and str(v) not in distinct_vals:
            # Suggest by substring match in distinct values
            sug = ""
            for dv in distinct_vals:
                if str(v) in dv or dv in str(v):
                    sug = dv
                    break
            findings.append(Finding(
                task_id=task_id, path=path, declared=str(v),
                issue="unknown_filter_value",
                suggestion=sug,
            ))


def validate_template(
    template: dict[str, Any],
    schemas: dict[str, TaskSchema],
) -> list[Finding]:
    """Walk every analysis / visualization task and check its field refs."""
    findings: list[Finding] = []
    context_tasks = {t["task_id"]: t for t in template.get("tasks", [])}

    # Report data_fetch failures first
    for tid, s in schemas.items():
        if s.status != "done" or s.error:
            findings.append(Finding(
                task_id=tid, path="(data_fetch)",
                declared=s.endpoint_id,
                issue=f"fetch_failed: {s.error or s.status}",
            ))

    for task in template.get("tasks", []):
        if task["type"] not in ("visualization", "analysis"):
            continue
        params = task.get("params") or {}
        cfg = params.get("config") or {}
        upstream = _upstream_task_ids(task, context_tasks)
        cols, distinct = _columns_available(upstream, schemas)

        # Analysis-specific fields
        if task["type"] == "analysis":
            _check_field(params.get("time_column"), cols, task["task_id"],
                         "params.time_column", findings, required=False)
            _check_field(params.get("group_by"), cols, task["task_id"],
                         "params.group_by", findings, required=False)
            for tc in params.get("target_columns") or []:
                _check_field(tc, cols, task["task_id"],
                             f"params.target_columns[{tc}]", findings)

        # Visualization field refs
        if task["type"] == "visualization":
            subtype = cfg.get("chart_type")
            # Single-axis fields
            for key in ("x_field", "category_field", "value_field", "y_field", "time_column", "category_column"):
                val = cfg.get(key) or params.get(key)
                if val:
                    _check_field(val, cols, task["task_id"],
                                 f"config.{key}" if key in cfg else f"params.{key}",
                                 findings, required=False)
            for yf in cfg.get("y_fields") or params.get("value_columns") or []:
                _check_field(yf, cols, task["task_id"],
                             "config.y_fields", findings, required=False)
            series_by = cfg.get("series_by")
            if series_by:
                _check_field(series_by, cols, task["task_id"],
                             "config.series_by", findings, required=False)

            # Dual-axis
            for side in ("left_y", "right_y"):
                spec = cfg.get(side)
                if isinstance(spec, dict):
                    src = spec.get("source")
                    side_cols = set(schemas[src].columns) if src in schemas else cols
                    side_distinct = schemas[src].distinct if src in schemas else distinct
                    if spec.get("y_field"):
                        _check_field(spec["y_field"], side_cols,
                                     task["task_id"], f"config.{side}.y_field", findings)
                    if spec.get("series_by"):
                        _check_field(spec["series_by"], side_cols,
                                     task["task_id"], f"config.{side}.series_by", findings,
                                     required=False)
                    if spec.get("x_field"):
                        _check_field(spec["x_field"], side_cols,
                                     task["task_id"], f"config.{side}.x_field", findings,
                                     required=False)

            # Grouped-bar series target/actual (Txxx.field expressions)
            for i, s in enumerate(cfg.get("series") or []):
                for key in ("target", "actual"):
                    expr = s.get(key) or ""
                    if not expr or "." not in expr:
                        continue
                    ref_task, field_name = expr.split(".", 1)
                    ref_cols = set(schemas[ref_task].columns) if ref_task in schemas else set()
                    if field_name not in ref_cols:
                        findings.append(Finding(
                            task_id=task["task_id"],
                            path=f"config.series[{i}].{key}",
                            declared=expr,
                            issue="unknown_series_field",
                            suggestion=(f"{ref_task}.{_suggest_column(field_name, ref_cols)}"
                                        if ref_cols else ""),
                        ))

            # Filter
            if cfg.get("filter"):
                _check_filter(cfg["filter"], cols, distinct, task["task_id"], findings)

    return findings


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def print_report(template_name: str, findings: list[Finding]) -> int:
    """Print a deterministic report. Returns the number of findings."""
    print(f"\n==== {template_name} ====")
    if not findings:
        print("  ✓ no field-reference issues found")
        return 0
    by_task: dict[str, list[Finding]] = {}
    for f in findings:
        by_task.setdefault(f.task_id, []).append(f)
    for tid in sorted(by_task):
        print(f"  {tid}:")
        for f in by_task[tid]:
            sug = f" -> 建议: {f.suggestion}" if f.suggestion else ""
            print(f"    [{f.issue}] {f.path} = {f.declared!r}{sug}")
    print(f"  总计 {len(findings)} 条问题")
    return len(findings)


# ---------------------------------------------------------------------------
# Auto-fix
# ---------------------------------------------------------------------------

def _apply_fix_to_params(
    params: dict[str, Any],
    finding: Finding,
) -> bool:
    """Patch a single field reference in-place. Returns True if applied."""
    if not finding.suggestion or finding.issue.startswith("fetch_failed"):
        return False

    path_parts = finding.path.split(".")
    # Drill down to parent dict
    node: Any = params
    for p in path_parts[:-1]:
        m = re.match(r"(\w+)\[(\d+)\]", p)
        if m:
            name, idx = m.group(1), int(m.group(2))
            node = node.get(name, [])
            if idx >= len(node):
                return False
            node = node[idx]
        elif p in node:
            node = node[p]
        else:
            return False
    leaf = path_parts[-1]

    # Handle series[i].target style
    m = re.match(r"(\w+)\[(\d+)\]", leaf)
    if m:
        name, idx = m.group(1), int(m.group(2))
        lst = node.get(name)
        if isinstance(lst, list) and idx < len(lst):
            node = lst[idx]
            # suggestion already includes full Tref.field
            # but finding.path tells us which key (target or actual) — not encoded
            # For safety skip this case (handled by series_field fix elsewhere)
        return False

    # Handle filter.<col> — patched by rewriting the whole filter key if column changed
    if leaf in node:
        node[leaf] = finding.suggestion
        return True
    return False


def auto_fix(template: dict[str, Any], findings: list[Finding]) -> int:
    """Apply deterministic fixes to the template in-place. Returns count fixed."""
    task_map = {t["task_id"]: t for t in template.get("tasks", [])}
    fixed = 0

    for f in findings:
        if not f.suggestion:
            continue
        if f.issue not in ("unknown_column", "unknown_filter_column",
                           "unknown_filter_value"):
            continue
        task = task_map.get(f.task_id)
        if not task:
            continue
        params = task.setdefault("params", {})

        # Normalise path: strip leading 'params.' or 'config.'
        path_parts = f.path.split(".")
        cfg = params.setdefault("config", {})

        # Special cases by path
        if f.path == "config.x_field":
            cfg["x_field"] = f.suggestion
            fixed += 1
        elif f.path == "config.category_field":
            cfg["category_field"] = f.suggestion
            fixed += 1
        elif f.path == "config.value_field":
            cfg["value_field"] = f.suggestion
            fixed += 1
        elif f.path == "config.y_field":
            cfg["y_field"] = f.suggestion
            fixed += 1
        elif f.path == "config.series_by":
            cfg["series_by"] = f.suggestion
            fixed += 1
        elif f.path.startswith("config.left_y."):
            sub = f.path.rsplit(".", 1)[-1]
            cfg.setdefault("left_y", {})[sub] = f.suggestion
            fixed += 1
        elif f.path.startswith("config.right_y."):
            sub = f.path.rsplit(".", 1)[-1]
            cfg.setdefault("right_y", {})[sub] = f.suggestion
            fixed += 1
        elif f.path.startswith("config.filter."):
            # Filter: rename key (column) or update value
            old_key = f.path.split(".", 2)[2]
            filt = cfg.setdefault("filter", {})
            if f.issue == "unknown_filter_column":
                if old_key in filt:
                    filt[f.suggestion] = filt.pop(old_key)
                    fixed += 1
            elif f.issue == "unknown_filter_value":
                if old_key in filt:
                    filt[old_key] = f.suggestion
                    fixed += 1
        # Note: series[i].target/actual intentionally not auto-fixed — too
        # tightly coupled to task_id + field name, needs human review.

    return fixed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def _main_one(template_name: str, fix: bool) -> int:
    path = TEMPLATES_DIR / f"{template_name}.json"
    template = json.loads(path.read_text(encoding="utf-8"))

    schemas = await discover_schemas(template)
    findings = validate_template(template, schemas)
    count = print_report(template_name, findings)

    if fix and findings:
        n_fixed = auto_fix(template, findings)
        if n_fixed:
            path.write_text(
                json.dumps(template, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"  ✓ 已自动修复 {n_fixed} 条")
        else:
            print("  ⚠ 无可自动修复项（需要人工处理）")

    return count


async def _main(args: argparse.Namespace) -> int:
    if args.template:
        templates = [args.template]
    else:
        templates = sorted(
            p.stem for p in TEMPLATES_DIR.glob("*.json")
            if not p.stem.startswith("_") and p.stem != "__init__"
        )

    total = 0
    for tpl in templates:
        total += await _main_one(tpl, args.fix)

    print(f"\n==== 汇总 ====")
    print(f"总计 {total} 条问题 across {len(templates)} 个模板")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--template", help="只校验指定模板（不带 .json 后缀）")
    p.add_argument("--fix", action="store_true", help="自动修复可确定性修复的项")
    args = p.parse_args()
    sys.exit(asyncio.run(_main(args)))
