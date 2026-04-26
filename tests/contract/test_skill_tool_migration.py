"""skill→tool rename completeness check.

Regression for the rollback-prone refactor: any leftover `skill_*` /
`BaseSkill` / `SkillRegistry` identifier in backend or frontend will trip
this test. Real skill (agent_skills SOPs) is whitelisted.

This is a fast, IO-only test (no DB / no network) — just file scans.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

pytestmark = pytest.mark.contract


REPO = Path(__file__).resolve().parent.parent.parent
BACKEND = REPO / "backend"
FRONTEND_SRC = REPO / "frontend" / "src"


# Patterns that MUST NOT appear (any of them would mean the rename is incomplete)
BACKEND_FORBIDDEN_PATTERNS = [
    r"\bBaseSkill\b",
    r"\bSkillInput\b",
    r"\bSkillOutput\b",
    r"\bSkillCategory\b",
    r"\bSkillRegistry\b",
    r"\bregister_skill\b",
    r"\bskill_executor\b",
    r"\bload_all_skills\b",
    r"\bload_extra_skills\b",
    r"\bget_valid_skill_ids\b",
    r"\bget_skills_description\b",
    r"\ballowed_skills\b",
    r"\.skill_ids\b",
    r"\.skills_count\b",
    r"\bget_skill_ids\b",
    r"\bhallucinated skill\b",
    r"\b_summarize_skill_output\b",
    r"\bskill_notes\b",                # table renamed to tool_notes
    r"\bupsert_skill_note\b",
    r"\bget_skill_notes\b",
    r"\brecord_skill_run\b",
    # Tool ids must use tool_ prefix; any literal `skill_<known-tool-name>`
    # identifies a leftover.
    r'"skill_(api_fetch|chart_|desc_analysis|attribution|anomaly|prediction|summary_gen|report_|dashboard|file_parse|web_search|waterfall)',
]

# Real skill (SOP) identifiers — these are intentional and OK.
BACKEND_ALLOWED_PATTERNS_SUBSTRINGS = [
    "agent_skill",      # agent_skills table, get_agent_skill etc.
    "AgentSkill",
    "SKILL.md",
    "/admin/agent-skills",
]

FRONTEND_FORBIDDEN_PATTERNS = [
    r"\bskill_id\b",        # backend-aligned field name
    r"\ballowed_skills\b",
    r"\bskill_feedback\b",
    r"\bsave_skill_notes\b",
    r"\bskills_count\b",
]
FRONTEND_ALLOWED_PATTERNS_SUBSTRINGS = [
    "AgentSkill",
    "agent_skill",
    "agent-skill",
    "SkillsView",
    "SkillDetailDrawer",
    "/admin/skills",       # SOP admin page route
    "admin/skills",
    'agent.技能',
    'Agent.技能',
]


# Files that are intentionally about the real SOP concept — every
# `skill_id` reference inside them is correct.
ALLOWED_FILE_NAMES = {
    "SkillsView.tsx",
    "SkillDetailDrawer.tsx",
}

# Lines in client.ts that touch the agent-skills HTTP shape (skill_id is
# the real PK column there).
ALLOWED_LINE_SUBSTRINGS = [
    "skill_id: string;",        # AgentSkill interface field
    "status: string; skill_id", # agent-skills toggle/delete response
]


def _scan(root: Path, patterns: list[str], allowed_subs: list[str], glob: str) -> list[tuple[Path, int, str]]:
    """Return list of (file, line_no, line) where any forbidden pattern hits
    AND no allow-list substring is on the same line AND the file is not in
    the allow-list of agent-skill admin files."""
    hits = []
    compiled = [re.compile(p) for p in patterns]
    for path in root.rglob(glob):
        if any(seg in path.parts for seg in ("__pycache__", "node_modules", "dist", ".vite")):
            continue
        if path.name.startswith("test_skill_tool_migration"):
            continue  # this very file
        if path.name in ALLOWED_FILE_NAMES:
            continue  # agent-skill admin views
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for i, line in enumerate(text.splitlines(), 1):
            if any(sub in line for sub in allowed_subs):
                continue
            if any(sub in line for sub in ALLOWED_LINE_SUBSTRINGS):
                continue
            for cre in compiled:
                if cre.search(line):
                    hits.append((path.relative_to(REPO), i, line.strip()))
                    break
    return hits


def test_no_legacy_skill_identifiers_in_backend():
    hits = _scan(BACKEND, BACKEND_FORBIDDEN_PATTERNS, BACKEND_ALLOWED_PATTERNS_SUBSTRINGS, "*.py")
    if hits:
        msg = "Legacy skill identifiers found in backend:\n" + "\n".join(
            f"  {h[0]}:{h[1]}  {h[2][:120]}" for h in hits[:20]
        )
        if len(hits) > 20:
            msg += f"\n  ... and {len(hits) - 20} more"
        pytest.fail(msg)


def test_no_legacy_skill_identifiers_in_frontend():
    if not FRONTEND_SRC.exists():
        pytest.skip("frontend/src not present")
    hits_ts = _scan(FRONTEND_SRC, FRONTEND_FORBIDDEN_PATTERNS, FRONTEND_ALLOWED_PATTERNS_SUBSTRINGS, "*.ts")
    hits_tsx = _scan(FRONTEND_SRC, FRONTEND_FORBIDDEN_PATTERNS, FRONTEND_ALLOWED_PATTERNS_SUBSTRINGS, "*.tsx")
    hits = hits_ts + hits_tsx
    if hits:
        msg = "Legacy skill identifiers found in frontend:\n" + "\n".join(
            f"  {h[0]}:{h[1]}  {h[2][:120]}" for h in hits[:20]
        )
        if len(hits) > 20:
            msg += f"\n  ... and {len(hits) - 20} more"
        pytest.fail(msg)


def test_plan_templates_use_tool_field_not_skill():
    """JSON plan templates must use `"tool":` not `"skill":`."""
    template_dir = REPO / "backend" / "agent" / "plan_templates"
    for f in template_dir.glob("*.json"):
        text = f.read_text(encoding="utf-8")
        # `"skill":` would be a leftover from the old field name
        assert '"skill":' not in text, (
            f"{f.name}: still has `\"skill\":` field — should be `\"tool\":`"
        )


def test_employee_yaml_use_tools_field_not_skills():
    """Employee YAMLs must use `tools:` (top-level) not `skills:`."""
    yaml_dir = REPO / "employees"
    for f in yaml_dir.glob("*.yaml"):
        text = f.read_text(encoding="utf-8")
        assert "\nskills:" not in text and not text.startswith("skills:"), (
            f"{f.name}: still has top-level `skills:` field — should be `tools:`"
        )
