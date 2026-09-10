"""Deterministic, template-based Skill creation (spec Feature 3).

Never writes without an explicit, separate confirmation step from the
caller (validate -> preview -> save is always three distinct calls); an
existing Skill is a warning, never a silent overwrite.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..providers.redaction import redact_secrets
from .atomic_write import write_text_atomic
from .models import NAME_PATTERN, SkillDraft, ValidationResult

_NAME_RE = re.compile(NAME_PATTERN)


def skill_path(project_root: str | Path, name: str) -> Path:
    return Path(project_root) / ".claude" / "skills" / name / "SKILL.md"


def existing_skill_names(project_root: str | Path) -> set[str]:
    skills_dir = Path(project_root) / ".claude" / "skills"
    if not skills_dir.is_dir():
        return set()
    try:
        return {p.name for p in skills_dir.iterdir() if (p / "SKILL.md").is_file()}
    except OSError:
        return set()


def validate_skill_draft(draft: SkillDraft, project_root: str | Path | None = None) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    name = (draft.name or "").strip()
    if not name:
        errors.append("Skill name is required.")
    elif not _NAME_RE.match(name):
        errors.append(
            "Skill name must be lowercase kebab-case (letters, digits, hyphens; "
            "e.g. 'security-review')."
        )

    if not (draft.purpose or "").strip():
        errors.append("Purpose is required.")
    if not (draft.when_to_use or "").strip():
        errors.append("'When should this Skill be used?' is required.")
    if not (draft.workflow or "").strip():
        errors.append("Workflow is required.")

    already_exists = False
    if not errors and project_root:
        if skill_path(project_root, name).exists():
            already_exists = True
            warnings.append(
                f"A Skill named '{name}' already exists. Saving will overwrite it — "
                f"review the preview carefully."
            )

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings,
                             already_exists=already_exists)


def render_skill_md(draft: SkillDraft) -> str:
    description = f"{draft.purpose.strip()} Use when: {draft.when_to_use.strip()}"
    description = description.replace('"', "'")

    def section(title: str, body: str) -> str:
        return f"## {title}\n\n{body.strip() if body and body.strip() else '(none specified)'}\n"

    body = "\n".join([
        "---",
        f"name: {draft.name.strip()}",
        f'description: "{description}"',
        "---",
        "",
        f"# {draft.name.strip().replace('-', ' ').title()}",
        "",
        section("Purpose", draft.purpose),
        section("When to Use", draft.when_to_use),
        section("Workflow", draft.workflow),
        section("Rules", draft.rules),
        section("Constraints", draft.constraints),
        section("Avoid", draft.avoid),
        section("Expected Output", draft.expected_output),
        section("Examples", draft.examples),
    ])
    return redact_secrets(body)


def save_skill(project_root: str | Path, draft: SkillDraft, *, overwrite: bool = False) -> dict:
    validation = validate_skill_draft(draft, project_root)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))

    path = skill_path(project_root, draft.name.strip())
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"A Skill named '{draft.name}' already exists at {path}. "
            f"Pass overwrite=True after explicit user confirmation."
        )

    content = render_skill_md(draft)
    write_text_atomic(path, content)
    return {"path": str(path), "overwritten": path.exists() and overwrite}
