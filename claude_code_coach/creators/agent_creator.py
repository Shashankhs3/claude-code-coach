"""Deterministic, template-based Agent creation (spec Feature 4).

Format note: this uses the SAME frontmatter convention (`name:`/`description:`
+ markdown body) V3.1's environment scanner already confirmed real by
parsing actual Claude Code Agent files this way (see
providers/claude_code_provider.py, grounded against a real installation,
not assumed). No additional/experimental frontmatter fields (tool
restrictions, activation triggers, etc.) are emitted, since those could not
be independently verified — Claude Code dispatches subagents by matching
the `description` against the task, which this generator leans on instead
of inventing an explicit activation mechanism.
"""

from __future__ import annotations

import re
from pathlib import Path

from ..providers.redaction import redact_secrets
from .atomic_write import write_text_atomic
from .models import AgentDraft, NAME_PATTERN, ValidationResult

_NAME_RE = re.compile(NAME_PATTERN)


def agent_path(project_root: str | Path, name: str) -> Path:
    return Path(project_root) / ".claude" / "agents" / f"{name}.md"


def existing_agent_names(project_root: str | Path) -> set[str]:
    agents_dir = Path(project_root) / ".claude" / "agents"
    if not agents_dir.is_dir():
        return set()
    try:
        return {p.stem for p in agents_dir.glob("*.md")}
    except OSError:
        return set()


def validate_agent_draft(draft: AgentDraft, project_root: str | Path | None = None) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    name = (draft.name or "").strip()
    if not name:
        errors.append("Agent name is required.")
    elif not _NAME_RE.match(name):
        errors.append(
            "Agent name must be lowercase kebab-case (letters, digits, hyphens; "
            "e.g. 'test-investigator')."
        )

    if not (draft.purpose or "").strip():
        errors.append("Purpose is required.")
    if not (draft.role or "").strip():
        errors.append("Role is required.")
    if not (draft.responsibilities or "").strip():
        errors.append("Responsibilities are required.")

    already_exists = False
    if not errors and project_root:
        if agent_path(project_root, name).exists():
            already_exists = True
            warnings.append(
                f"An Agent named '{name}' already exists. Saving will overwrite it — "
                f"review the preview carefully."
            )

    return ValidationResult(ok=not errors, errors=errors, warnings=warnings,
                             already_exists=already_exists)


def render_agent_md(draft: AgentDraft) -> str:
    description = f"{draft.purpose.strip()} Role: {draft.role.strip()}".replace('"', "'")

    def section(title: str, body: str) -> str:
        return f"## {title}\n\n{body.strip() if body and body.strip() else '(none specified)'}\n"

    modify_line = (
        "May modify source files."
        if draft.may_modify_source
        else "Read-only — must NOT modify source files."
    )

    body = "\n".join([
        "---",
        f"name: {draft.name.strip()}",
        f'description: "{description}"',
        "---",
        "",
        f"# {draft.name.strip().replace('-', ' ').title()}",
        "",
        section("Purpose", draft.purpose),
        section("Role", draft.role),
        section("Responsibilities", draft.responsibilities),
        section("Investigation Instructions", draft.investigation_instructions),
        section("Allowed Actions", draft.allowed_actions),
        section("Restrictions", (draft.restrictions or "") + f"\n\n{modify_line}"),
        section("Expected Output", draft.expected_output),
        section("Verification Requirements", draft.verification_requirements),
    ])
    return redact_secrets(body)


def save_agent(project_root: str | Path, draft: AgentDraft, *, overwrite: bool = False) -> dict:
    validation = validate_agent_draft(draft, project_root)
    if not validation.ok:
        raise ValueError("; ".join(validation.errors))

    path = agent_path(project_root, draft.name.strip())
    if path.exists() and not overwrite:
        raise FileExistsError(
            f"An Agent named '{draft.name}' already exists at {path}. "
            f"Pass overwrite=True after explicit user confirmation."
        )

    content = render_agent_md(draft)
    write_text_atomic(path, content)
    return {"path": str(path), "overwritten": path.exists() and overwrite}
