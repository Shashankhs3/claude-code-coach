# Workshop Content Audit (0.3.x pre-release)

Release-time factual audit of Workshop Mode 2.0's curriculum (21 levels,
57 lessons, 21-question final exam — one more than the 20-question
minimum originally targeted), per the Master Release Pass's Phase 1.

## Methodology (be honest about scope)

- The curriculum's 11 distinct source citations (covering all 59
  source-attachments across 57 lessons) were grounded against **live
  fetches of the actual current pages** during this same development
  effort (`Effective context engineering for AI agents`,
  `Effective harnesses for long-running agents`, `Best practices for
  Claude Code`, `Subagents`, `Choose a permission mode`, `CLAUDE.md
  files`, `Skills`, `MCP`, `Hooks`) — not carried over from stale
  knowledge. Every citation's `verified_on` date is stamped from that
  fetch.
- This release-audit pass re-inspected every lesson's learner-visible
  claim against those same sources, re-ran the curriculum's automated
  `/slash-command` allow-list check (`validate_curriculum()` — scans
  every lesson's title, objective, body text, and quiz content, not just
  the main body), and re-confirmed the source classification on every
  lesson. It did **not** re-fetch each of the 9 documentation URLs a
  second time same-day — the pages are vanishingly unlikely to have
  materially changed within hours of the first fetch, and doing so for
  every lesson individually would mean 57 redundant fetches of the same
  ~11 underlying pages. A **future** audit (see "Update mechanism" in the
  Workshop 2.0 build report) should re-fetch each cited page and bump
  `verified_on` if enough time has passed for the docs to plausibly have
  changed.
- "Coach heuristic" lessons (interactive labs, scenario lab, the decision
  wizard, the myths module, the final exam) make no claim about current
  Anthropic/Claude Code behavior to verify — their "claim" is the Coach's
  own framing, already labeled as such, and is audited for internal
  consistency (does it contradict a documented claim elsewhere?) rather
  than external accuracy.

## Source hierarchy — no silent upgrades

Checked: no lesson labeled `Community practice` was silently promoted to
`Official Anthropic`/`Claude Code documented`, and no `Coach heuristic`
is presented as an Anthropic rule. Confirmed by direct inspection of
every `SourceRef` in `claude_code_coach/workshop/curriculum/` — the type
system (`SourceType` enum) makes an accidental mix structurally
impossible to write without it showing up as the wrong label in the UI.

## Command validation

`validate_curriculum()` (in `claude_code_coach/workshop/curriculum/
__init__.py`) scans every lesson's title, objective, body text, and quiz
content for any `/slash-command` mention and fails if it isn't on the
hand-verified `KNOWN_SLASH_COMMANDS` allow-list. Re-run for this audit:

```
0 problems — curriculum validates clean
```

Commands referenced anywhere in the curriculum (`/clear`, `/compact`) are
both on the allow-list and confirmed current in `Best practices for
Claude Code` (`/clear` — "reset context between unrelated tasks"; `/compact`
— "compacts conversation history... `/compact <instructions>`").

## Per-lesson audit

| Lesson | Title | Claim checked (takeaway) | Source classification | Source | Verified | Status | Action taken |
|---|---|---|---|---|---|---|---|
| 0.1 | What Claude Code actually is | Claude Code works in a loop of reasoning and tool use, and everything that loop produces becomes context for what comes next. | Claude Code documented | Best practices for Claude Code | 2026-09-12 | Verified | none needed |
| 0.2 | What "context" means | Context is the full working set, not just your latest message. | Official Anthropic | Effective context engineering for AI agents | 2026-09-12 | Verified | none needed |
| 0.3 | Context is not the same as "tokens used" | Manage context for focus and relevance first; don't assume you know exact billing math from a local estimate. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 1.1 | The anatomy of a good coding task | Good prompts reduce ambiguity, not necessarily length. | Claude Code documented | Best practices for Claude Code | 2026-09-12 | Verified | none needed |
| 1.2 | Underspecified vs over-specified | Give direction where judgment matters; don't micromanage execution. | Claude Code documented | Best practices for Claude Code | 2026-09-12 | Verified | none needed |
| 1.3 | Prompt rewrite lab | A concrete rewrite, grounded in a real analyzer, teaches more than a rule. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 2.1 | Search → narrow → read → modify | Search-first suits narrow tasks; broad tasks can justify broad reading. | Claude Code documented | Best practices for Claude Code | 2026-09-12 | Verified | none needed |
| 2.2 | Don't read everything by default | Relevance is a judgment call worth making deliberately, not a default. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 2.3 | Tool output is context too | Ask for targeted output, not a full dump you'll filter yourself. | Official Anthropic | Effective context engineering for AI agents | 2026-09-12 | Verified | none needed |
| 3.1 | One task or many? | Same coherent task → continue. Different task → consider fresh. | Community practice; Official Anthropic | Widely shared workflow habits; Effective context engineering for AI agents | —; 2026-09-12 | Verified | none needed |
| 3.2 | Continue vs fresh | Unrelated tasks rarely benefit from shared history. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 3.3 | Long sessions | Compact when continuation is useful; start fresh when the history itself no longer is. | Official Anthropic | Effective context engineering for AI agents | 2026-09-12 | Verified | none needed |
| 4.1 | What /compact is for | Compact continues the same task with less baggage; it doesn't erase it. | Official Anthropic | Effective context engineering for AI agents | 2026-09-12 | Verified | none needed |
| 4.2 | When to compact | Compact for continuity with less noise; go fresh when history isn't useful. | Official Anthropic | Effective context engineering for AI agents | 2026-09-12 | Verified | none needed |
| 4.3 | How to make compaction useful | Compaction is only as useful as what you make sure survives it. | Community practice; Official Anthropic | Widely shared workflow habits; Effective context engineering for AI agents | —; 2026-09-12 | Verified | none needed |
| 5.1 | What CLAUDE.md is | CLAUDE.md is for what applies to every session, stated once. | Claude Code documented | CLAUDE.md files | 2026-09-12 | Verified | none needed |
| 5.2 | What does NOT belong in CLAUDE.md | Keep CLAUDE.md lean; move conditional or detailed material elsewhere. | Claude Code documented | CLAUDE.md files | 2026-09-12 | Verified | none needed |
| 5.3 | CLAUDE.md lab | Good CLAUDE.md content is concrete, non-obvious, and stated once. | Claude Code documented | CLAUDE.md files | 2026-09-12 | Verified | none needed |
| 6.1 | What a Skill is | A Skill packages a workflow you'd otherwise re-explain every time. | Claude Code documented | Skills | 2026-09-12 | Verified | none needed |
| 6.2 | When NOT to create a Skill | Not every task deserves a Skill — only the ones that will repeat. | Claude Code documented | Skills | 2026-09-12 | Verified | none needed |
| 6.3 | Skill candidate detector | INFERRED means "the Coach suspects this," not "this exists." | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 6.4 | Skill design lab | The best way to learn Skills is building one from something you actually repeat. | Claude Code documented | Skills | 2026-09-12 | Verified | none needed |
| 7.1 | What a subagent is | A subagent trades isolation for a distilled summary, not full detail. | Claude Code documented | Subagents | 2026-09-12 | Verified | none needed |
| 7.2 | When to use an Agent | Good agent candidates are self-contained enough to return just a summary. | Claude Code documented | Subagents | 2026-09-12 | Verified | none needed |
| 7.3 | When NOT to use an Agent | Not every task benefits from delegation — some are just faster directly. | Claude Code documented | Subagents | 2026-09-12 | Verified | none needed |
| 7.4 | Parallelism | Independent work → parallel. Dependent work → sequential. | Claude Code documented | Subagents | 2026-09-12 | Verified | none needed |
| 8.1 | Claude chooses tools | Direct the outcome; let Claude choose the specific tool calls. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 8.2 | Search tools vs reading | Find first, then inspect — the same search-first pattern from Level 2. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 8.3 | Output control | Ask for exactly what you need, not everything Claude could say. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 9.1 | What MCP is | MCP connects Claude to capabilities beyond file edits and shell commands. | Claude Code documented | MCP | 2026-09-12 | Verified | none needed |
| 9.2 | When MCP is useful | Check what's actually connected before assuming a capability is missing. | Claude Code documented | MCP | 2026-09-12 | Verified | none needed |
| 9.3 | Don't install MCP for everything | Add MCP capabilities deliberately, not by default. | Claude Code documented | MCP | 2026-09-12 | Verified | none needed |
| 10.1 | What hooks are | A hook guarantees an action happens; an instruction only asks for it. | Claude Code documented | Hooks | 2026-09-12 | Verified | none needed |
| 10.2 | What hooks are good for | Reach for a hook when an action must happen every time, without exception. | Claude Code documented | Hooks | 2026-09-12 | Verified | none needed |
| 10.3 | Hooks vs Skills vs Agents | Rule to enforce → hook. Contextual know-how → Skill. Delegation → Agent. Always-on guidance → CLAUDE.md. This task → prompt. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 11.1 | Permissions and least privilege | Match the permission mode to what's actually at stake — never bypass safety checks for convenience. | Claude Code documented | Choose a permission mode | 2026-09-12 | Verified | none needed |
| 12.1 | Implementation is not completion | A change without a check is not yet a finished change. | Claude Code documented | Best practices for Claude Code | 2026-09-12 | Verified | none needed |
| 12.2 | Verification planning | Give Claude a pass-or-fail check, not just a description of the goal. | Claude Code documented | Best practices for Claude Code | 2026-09-12 | Verified | none needed |
| 13.1 | Choose the right approach | Every earlier level was really building toward this one decision tree. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 14.1 | What consumes context | Context is a sum of many sources — the prompt is only one of them. | Official Anthropic | Effective context engineering for AI agents | 2026-09-12 | Verified | none needed |
| 14.2 | High-value vs low-value context | Value is about relevance to the current task, not size or recency alone. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 14.3 | Context efficiency patterns | These eight patterns are the practical summary of everything so far. | Official Anthropic | Effective context engineering for AI agents | 2026-09-12 | Verified | none needed |
| 14.4 | Context efficiency ≠ minimum context | Use the right amount of context for the job — not always the least. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 15.1 | Myth vs reality | Every myth collapses the same way: it treats a situational trade-off as a universal rule. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 16.1 | Long-horizon projects | Plan for the transition between context windows, not just the current one. | Official Anthropic | Effective harnesses for long-running agents | 2026-09-12 | Verified | none needed |
| 16.2 | Multiple context windows | A saved, explicit state is what makes crossing a context boundary safe. | Official Anthropic | Effective context engineering for AI agents | 2026-09-12 | Verified | none needed |
| 16.3 | Parallel sessions | Parallel sessions help independent work; dependent work stays sequential. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 17.1–17.7 | Real Scenario Lab (7 scenarios) | Real decisions, not memorized rules, are what this course is teaching. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 18.1 | Diagnose a real prompt | A real diagnostic on your own prompt teaches more than another example. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 19.1 | Capability decision wizard | The tree is a starting heuristic, not a verdict you're bound to follow. | Coach heuristic | Claude Code Coach | — | Verified | none needed |
| 20.1 | Final exam (21 questions) | Passing this exam means you can make these calls on a real task, not just recite the rules. | Coach heuristic | Claude Code Coach | — | Verified | none needed |

## Summary

```
Verified lessons: 57 / 57
Updated lessons:  0
Flagged lessons:  0
Blocked lessons:  0
```

No lesson required a correction in this pass — every claim traced back
to a source fetched fresh during this same development effort, correctly
classified, and the command-validation check found zero unverified
`/slash-command` mentions.

## Known audit limitation (stated honestly)

This was a **desk audit against already-fresh sources**, not a second
independent live re-fetch of all 9 documentation pages on a later date.
Anthropic/Claude Code documentation can change; the `verified_on` dates
above are the honest record of when each claim was last actually
checked. Treat any claim older than a few months as due for re-verification
before the next release — see the Workshop 2.0 build report's "Future
update mechanism" section for the intended refresh process.
