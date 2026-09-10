"""Secret redaction for anything read from local configuration files.

Spec section 14: discovered configuration is untrusted local input. If a
file being previewed (CLAUDE.md, SKILL.md, an agent definition) appears to
contain a credential/token/password/API key, the value must never reach the
UI — only ``[REDACTED]``.
"""

from __future__ import annotations

import re

# key = value / key: value / key="value" style secret assignments — matched
# anywhere (not just at line start), since a secret can appear mid-sentence
# in free text like a Skill/Agent description.
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b(?P<key>[\w.-]*"
    r"(?:api[_-]?key|secret|token|password|passwd|access[_-]?key|"
    r"private[_-]?key|client[_-]?secret|auth[_-]?token|bearer)"
    r"[\w.-]*)\s*[:=]\s*(?P<quote>[\"']?)(?P<value>[^\s\"']+)(?P=quote)"
)

# Standalone bearer tokens / long opaque secrets even without a "key=" prefix.
_BEARER = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._-]{8,}\b")
_LONG_OPAQUE_TOKEN = re.compile(r"\b(sk-|ghp_|xox[baprs]-|AIza)[A-Za-z0-9_-]{10,}\b")

MASK = "[REDACTED]"


def redact_secrets(text: str) -> str:
    """Return `text` with anything that looks like a secret value masked."""
    if not text:
        return text

    def _mask_assignment(m: re.Match) -> str:
        return f"{m.group('key')}={MASK}"

    out = _SECRET_ASSIGNMENT.sub(_mask_assignment, text)
    out = _BEARER.sub(f"Bearer {MASK}", out)
    out = _LONG_OPAQUE_TOKEN.sub(MASK, out)
    return out


def redact_mapping_values(mapping: dict) -> dict:
    """Redact every value in a flat dict (e.g. an MCP server's `env` block)."""
    return {k: MASK for k in mapping} if mapping else {}
