# Claude Code Coach (V5)

A local-first Windows desktop **Claude Code Workflow Coach**: not a prompt
checker, but something closer to "given what I'm trying to accomplish, how
should I actually work with Claude Code?" — prompt scoping, deterministic
prompt rewriting, a Recommended Approach advisor spanning prompt/environment/
runtime evidence, Skill/Agent creation with explicit-confirmation file
writes, session-coherence and verification coaching, and everything V4/V3.1
already did (real environment discovery, real Claude Code hook telemetry).
Built with Python + PySide6 + SQLite. Fully offline, deterministic, no AI API.

> The in-app "Context Efficiency Score" is a **local coaching heuristic**.
> It is not an official Anthropic/Claude metric and it does not measure
> actual token savings. See [Known limitations](#known-limitations).

## Quick start (Windows)

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

Data is stored locally at `%USERPROFILE%\.claude_code_coach\coach.db`. Nothing
is ever sent to a network API — see the Settings page in-app.

On first run, open **Environment** and use **Choose Project Folder** to point
it at a real project, then **Scan Again** — otherwise it only has your
user-level (`~/.claude`) Skills/Agents/CLAUDE.md to look at.

Runtime coaching (V4) is **off until you turn it on**: open **Sessions** →
**Install Runtime Hooks…** to register this app's hook command in a
`settings.json` of your choosing. Nothing is captured before that.

The Skill/Agent Creators (V5) never write a file until you explicitly press
**Save to Project** — pick a project folder first (Environment or Settings).

### Prefer a standalone build (no Python required)?

```powershell
.\packaging\build.ps1
```

Builds `dist\ClaudeCodeCoach\ClaudeCodeCoach.exe` — same icon as the VS Code
extension, no Python install needed to run it. See [packaging/README.md](packaging/README.md)
for what it produces and why the Runtime Hooks feature needed a real code
change (not just a build-script trick) to keep working once packaged.

## What's new in V5: Workflow Coach

V4 answered "what is Claude Code doing right now?" V5 answers "given what
I'm trying to accomplish, what's the best way to work with Claude Code?" —
without ever pretending to know something it can't actually observe, and
without calling an external AI API to get there (every suggestion below is
regex/rule-based and fully explainable).

### Feature 1 — Suggested Prompt engine (`analyzer/prompt_rewriter.py`)

Deterministic, local-only. Classifies a prompt into one of six buckets
(`good` / `underspecified` / `overly_prescriptive` / `broad_justified` /
`broad_inefficient` / `informational`) and, only when a rewrite would
actually help, assembles one from facts *extracted from the prompt itself*
(`analyzer/prompt_extractor.py` — files, function names, constraints,
error descriptions, expected behavior, requested output) plus neutral
template language (`analyzer/prompt_templates.py`) for whatever's missing.
Nothing is invented: `"Fix my project."` never gets a fabricated file name
or root cause — see `tests/test_v5.py::TestPromptSuggestionsExtraction::
test_no_facts_invented_for_vague_prompt`.

### Feature 2 — Approach Advisor (`integration/approach_advisor.py`)

The "three independent evidence sources" principle (V4 spec section 33),
now assembled into one report: prompt evidence (task type, scope), real
environment evidence (DETECTED Skills/Agents/CLAUDE.md/MCP — reusing V3.1's
`environment_matching`), and real runtime evidence (verification/context
signals from the live session, when enabled). An existing DETECTED
resource always outranks an INFERRED candidate for the same kind of work —
never "consider creating a Skill" when one already exists. Its own page
(**Approach Advisor**) gives a focused "describe the task, get the
recommendation" tool; the Prompt Inspector shows the same advisor inline
alongside prompt quality, kept as a clearly separate section (never merged
into one score).

### Feature 3/4 — Skill Creator / Agent Creator (`creators/`)

Deterministic, template-based, file-writing held to a higher bar than
everything else in the app (same discipline as V4's `hook_installer.py`):
atomic writes, kebab-case name validation, a duplicate name is a *warning*
requiring explicit overwrite confirmation (never silent), secrets in any
field are redacted before ever being written or previewed, and nothing
touches disk before **Generate Preview → Save to Project**. In-progress
form data survives navigating away (persisted as a single-row draft, spec
Feature 16) and is cleared on a successful save. After saving, the
Environment scanner is re-run automatically so the new Skill/Agent shows
up as DETECTED immediately — verified live: see "Real GUI verification"
below. Agent files use the exact same frontmatter convention (`name:`/
`description:` + markdown body) V3.1 already confirmed real by parsing
actual Claude Code Agent files this way — no invented activation/tool-
restriction fields.

### Feature 5 — Repeated workflow → Skill/Agent creation

The Skills/Agents pages' existing INFERRED-candidate cards now carry a
**Create Skill**/**Create Agent** button that pre-fills a new draft from
the candidate's own evidence (its reason + example prompts) and navigates
to the corresponding Creator. If a candidate's examples already
text-match a DETECTED resource, the button is replaced with a note
pointing at the existing one instead — the create-vs-use-existing
distinction is enforced at the same matching layer Feature 2 uses, not
duplicated logic.

### Feature 6/8 — Session coherence & Context Health (`runtime/runtime_analyzer.py`)

`session_coherence()` computes a 0-100 Context Health percentage from real
runtime events: it does **not** penalize a session for being long — only
for actual task switches (consecutive prompts with low token overlap *and*
different task types) and `PreCompact` events. A long, single-focus
session scores the same as a short one; a short session that's already
switched topics twice scores worse than a long, coherent one. Shown on the
Context page (when a runtime session is active) and folded into the
Approach Advisor's recommendations.

### Feature 7 — Parallel Work Advisor

`prompt_extractor.py` detects "across A, B and C" / "in A, B, and C" style
enumerations in a single prompt (spec's own example: "...across backend,
database and frontend") and — only when there's no sequential connector
("then", "once that's done") suggesting a dependency — surfaces a
`parallel_work` recommendation in the Approach Advisor. Never triggered by
merely mentioning multiple files.

### Feature 9 — Verification Coach (`runtime_analyzer.verification_signal`)

After the last file edit in a session, checks whether a test-like Bash
command (`pytest`, `npm run`, `go test`, ...) or a subagent run followed it.
Phrased exactly as the spec requires — **"No verification evidence
observed"**, never "you didn't test it" — since the app genuinely cannot
know whether verification happened outside what it can observe (e.g. in a
separate terminal).

### Feature 10 — Workshop Mode (`ui/workshop.py`, `ui/workshop_lessons.py`)

A settings toggle plus a reference page covering the twelve concepts the
spec lists (task clarity through verification). When on, the Inspector's
warnings/opportunities each get an expanded "WHY THIS MATTERS" / "TRY
THIS" block pulled from a small lookup table keyed by the *actual*
dimension/opportunity kind — not fuzzy-matched from free text.

### Features 11/12/13 — Navigation, Dashboard, Inspector

Sidebar reorganized into Dashboard / **WORK** (Inspector, Approach Advisor,
Sessions, Prompt History, Context) / **CAPABILITIES** (Skills, Skill
Creator, Agents, Agent Creator, Integrations, Environment) / **LEARNING**
(Habits, Workshop Mode) / Settings — every V4 page kept, none removed
("Runtime" is relabeled "Sessions" in the sidebar since that's what it now
is, same class, enriched). Dashboard gets a capped-at-3 **Recommendations**
section combining the live runtime session's top signals with the most
recently analyzed prompt's Approach Advisor output. The Inspector gets
Suggested Prompt / Recommended Approach / Session-Context sections, each
independently readable, never collapsed into the prompt-quality score.

### Feature 14 — Copy Suggestion workflow

**Copy Suggested Prompt** (clipboard) and **Use as New Prompt** (replaces
the editor text and re-triggers live analysis) — both disabled when there's
no suggestion to act on. Nothing is ever sent anywhere automatically.

## What's new in V4: real-time runtime coaching

V3.1 could tell you what Skills/Agents/CLAUDE.md exist. It had no idea what
Claude Code was actually *doing*. V4 adds that, through the one mechanism
Claude Code actually, documentedly exposes for this: **hooks**.

### Source and scope (spec section 1 — no invented event names)

Before writing any of this, I fetched Claude Code's current hooks reference
(`code.claude.com/docs/en/hooks`) and cross-checked it against this
project's own real, already-configured `~/.claude/settings.json` (which,
independent of anything I wrote, already had `Stop`, `PermissionRequest`,
`PreToolUse`, `UserPromptSubmit`, and `SubagentStop` hooks configured for
an unrelated notifier tool) and `~/.claude.json` (the real, observed
location of project-scoped MCP server registrations). The fetched reference
listed many more event types than that — some quite exotic (worktree
events, model-switch events, task events, elicitation events) — that I have
no independent way to verify are accurate, since that fetch is summarized
by a small model rather than being the raw page text. Rather than wire up
names I can't cross-check, **V4 only implements the core, high-confidence
event set**:

`SessionStart`, `SessionEnd`, `UserPromptSubmit`, `PreToolUse`,
`PostToolUse`, `Stop`, `SubagentStop`, `PreCompact`, `Notification`,
`PermissionRequest`.

Anything else Claude Code might fire is simply not wired up — never
silently pretended to work. An unrecognized event name that does arrive is
tagged `RuntimeEventType.UNKNOWN` and safely ignored, not guessed at.

### How it actually works

1. **Runtime → Install Runtime Hooks…** writes this app's hook command into
   a `settings.json` you choose (project or user level) — a JSON merge that
   only ever *appends* to each event's hook list, never touches any
   existing hook, and writes atomically (temp file + rename) so a crash
   mid-write can't corrupt your real, working Claude Code configuration.
   **Remove Runtime Hooks** reverses it, matching only entries whose
   command+args are byte-for-byte what this app would have written.
2. When Claude Code later fires one of those events for real, it invokes
   `runtime/hook_receiver.py` with the event's JSON on stdin. This script
   is deliberately tiny and defensive: it **always exits 0** and **never
   prints anything to stdout** (several events treat hook stdout as a
   blocking/context-injecting decision — this script must never disrupt a
   real Claude Code session), wrapping everything in a bare `except
   Exception: pass`. It appends one normalized line to
   `~/.claude_code_coach/runtime_events/<session_id>.jsonl` and returns.
3. The running desktop app polls that directory (`runtime/event_source.py`):
   each poll atomically renames a session's file aside, drains it into
   SQLite, and deletes it — so a concurrent hook invocation lands in a
   freshly recreated file (nothing lost), and there's no in-memory "read
   offset" that an app restart would reset to zero and cause duplicate
   ingestion (an actual bug caught and fixed during development — see
   `runtime/event_source.py`'s docstring).
4. `runtime/runtime_analyzer.py` turns stored events into `RuntimeSignal`s,
   each carrying `evidence` (spec section 29) so a verdict is always
   explainable — never a bare "something's wrong."

### Privacy: what's captured vs. what isn't (spec section 22)

**Prompt/response text is never stored by default.** Only derived,
non-reversible signals are kept: word counts, a bag-of-tokens (for
similarity clustering — no original sentence, no word order), and the
existing V3 analyzer's task classification (task type, scope status,
breadth level) computed once at ingest time. Turn on **Settings → "Store
prompt/response text"** to keep the real text (also redacted through the
same secret-scrubber V3.1 uses for CLAUDE.md/Skill previews).

File paths and Bash commands *are* captured as operational metadata (spec
section 22 explicitly prefers "filename, extension, operation, timestamp,
counts" over full content) — always passed through the same
`providers/redaction.py` secret-masking used everywhere else in the app.
MCP/tool *results* (e.g. a command's full stdout) are never captured
unless content-collection is explicitly on, and even then are truncated
and redacted.

### Runtime coaching signals

Every signal is deliberately conservative — see
`tests/runtime_benchmark.json` (30 fixture sequences) for the adversarial
cases this was tuned against:

- **`broad_exploration`** — many files read before any search/narrowing
  step. Only flagged when the *task itself* also looks narrow (scope
  clear, not a review/security-review/research task) — a legitimately
  broad task (a security audit, a comparative research question) reading
  many files is never penalized just for its file count.
- **`search_first_good`** — a search/locate step happened before reading,
  with a reasonable number of reads afterward.
- **`context_growth`** — one or more `PreCompact` events occurred in the
  session.
- **`agent_delegation_opportunity`** — an investigation/debugging task
  touched several independent directories without ever using a subagent.
  Always phrased as "possible," never "you should have delegated this."
- **`repeated_workflow_no_skill`** / **`skill_underused`** — the *same*
  tri-state distinction from V3.1, now driven by real prompts across real
  sessions instead of only prompts you paste into the Inspector: a
  recurring workflow either has no matching DETECTED Skill (candidate) or
  does (in which case the coaching is "use the Skill you already have,"
  not "consider creating one" — spec section 33's worked example).
- **`claude_md_repetition`** — a prompt heavily restates an existing
  CLAUDE.md line. Requires ≥6 words and ≥50% token overlap with an actual
  CLAUDE.md line, specifically so it doesn't fire on ordinary short
  clarifications (spec section 9/13).

**What this version deliberately does not attempt**: judging whether a
small number of reads were *individually* irrelevant (that needs file
content/semantic understanding this app doesn't have), or detecting
"repeated searches for the same thing" as its own signal. Both are listed
explicitly in [Known limitations](#known-limitations) rather than faked
with a low-confidence guess.

### Runtime UI

- **Runtime** (new page): connection state (`● LIVE` / `● CONNECTED (idle)`
  / `○ CONFIGURED (no events yet)` / `○ NOT CONFIGURED` / `○ PAUSED`),
  current-session stat cards, coaching signal cards (each with what
  happened / why it matters / what to try — spec section 19), a recent-
  events timeline, and the Install/Remove Hooks controls.
- **Dashboard** gets a compact Runtime card mirroring the connection state
  and the top coaching signal.
- **Settings** gets the content-collection toggle and a retention dropdown
  (7/30/90 days/Forever) — purging is applied immediately when changed.
- **Prompt quality vs. runtime/session health stay visually separate**
  (spec section 14/18): the Inspector's score is unaffected by anything on
  the Runtime page, and Runtime never produces a single combined score —
  only labeled component signals.

## What's new in V3.1: real environment awareness

V3 could only analyze a pasted prompt in isolation. V3.1 adds a second,
independent axis: **what does your Claude Code setup actually contain**, and
does a given prompt relate to it. Nothing here is invented — every claim is
either a real file found on disk right now, or explicitly labeled as the
coach's own inferred opportunity signal. These are never allowed to collapse
into one message (spec sections 10/11/22):

| State | Meaning | Shown as |
|---|---|---|
| **DETECTED** | An actual Skill/Agent/CLAUDE.md/MCP entry found on disk | `✓ DETECTED — security-review` |
| **POSSIBLE** | A prompt looks related to a DETECTED resource (confidence-rated) | `(high confidence match)` / `(medium confidence match)` |
| **INFERRED** | No real resource found, but history/pattern suggests one would help (the original V3 signal) | `🔧 INFERRED — ...consider creating one.` |
| **UNKNOWN / none** | Neither — or discovery failed for a specific item | omitted, or listed under "Scan warnings" |

### What actually gets scanned

Grounded against a real Claude Code installation before writing the scanner
(not guessed) — see `providers/claude_code_provider.py` for the exact,
commented location list. In short:

- **Project-scoped** (a folder you choose on the Environment/Settings page):
  `CLAUDE.md`, `.claude/skills/*/SKILL.md`, `.claude/agents/*.md`,
  `.mcp.json`, plus each parent directory up to your home folder (Claude
  Code reads ancestor `CLAUDE.md` files too).
- **User-scoped** (`~/.claude`, configurable): `CLAUDE.md`, `skills/*/SKILL.md`,
  `agents/*.md`, `settings.json`, and — the real, currently-observed
  location for project-scoped MCP servers registered via `claude mcp add` —
  `~/.claude.json`'s `projects["<your project path>"].mcpServers` (only that
  one project's entry is ever read out of that file; the rest of it, which
  holds account/session data, is never touched).

The scanner is **strictly read-only**: it never executes a Skill/Agent/MCP
command, never connects to an MCP server, and never writes to any Claude
Code configuration file. Scanning always runs on a background `QThread`
(`ui/env_worker.py`) so the UI never freezes, and the whole scan is wrapped
so a bad file or a permission error becomes a warning in the snapshot, never
a crash.

### Secrets never reach the UI

Anything read from a config file (a CLAUDE.md preview, a Skill/Agent
description) is passed through `providers/redaction.py` first, which masks
`key=value`/`key: value` assignments whose key looks like an API key,
token, password, or similar (`API_KEY=super-secret-value` →
`API_KEY=[REDACTED]`), plus bare bearer tokens and common vendor token
prefixes (`sk-`, `ghp_`, `xox*-`, `AIza`). MCP server `env`/args are never
even extracted from config — only `name`, `type`, and enabled/disabled
state are stored. Covered by `tests/test_environment_provider.py::TestSecretRedaction`.

### Where this shows up in the UI

- **Environment** (new page): CLAUDE.md/Skills/Agents/MCP counts, one card
  per detected item, scan warnings, **Scan Again**, and **Choose Project
  Folder**.
- **Prompt Inspector**: Live Coach gets a new "ENVIRONMENT" section —
  `✓ DETECTED Skill — security-review (high confidence match)` when a
  scanned Skill looks relevant, `🔧 INFERRED` when it's only a
  history-based signal, a matching note for Agents the same way, and a
  "this looks like it already exists in CLAUDE.md" note when a prompt
  closely restates an existing project rule (deliberately conservative —
  spec section 9 — so it won't fire on a short, normal clarification).
- **Skills / Agents pages**: each now has two sections — *Existing
  (DETECTED)*, straight from the last scan, and *Candidates (INFERRED)*,
  the original V3 history-clustering signal — never merged.
- **Settings**: project-folder picker, "scan on startup" toggle, both
  persisted in a small `app_settings` key/value table.

### Matching is conservative on purpose

`integration/environment_matching.py` requires real term overlap between the
prompt and the resource's own name/description (Jaccard-style, reusing the
same stdlib tokenizer as V3's history clustering — no embeddings, no new
dependency) before calling anything "existing," and needs a much higher
overlap to say "high confidence" than "medium." An existing DETECTED match
always wins over the INFERRED signal if both would otherwise fire — a real
resource is not a "maybe."

## Architecture

```
claude_code_coach/
    app.py                  # QApplication + MainWindow bootstrap
    database/
        db.py                # sqlite3 access layer, safe_score(), export/import,
                              # environment-snapshot + app_settings persistence
        migrations.py        # schema_version tracking + legacy-DB migration
    analyzer/                # UNCHANGED IN V3.1 — still provider-independent
        lexicon.py           # shared regex/keyword signals
        task_classifier.py   # classifies a prompt's task type (11 types)
        prompt_analyzer.py   # per-dimension evaluation (goal/scope/.../output)
        scoring.py           # task-type-aware weighted scoring -> 0-100
        opportunities.py     # single-prompt Skill/Agent/CLAUDE.md/context signals
        models.py            # DimensionResult / Opportunity / AnalysisResult
    analytics/               # UNCHANGED IN V3.1
        patterns.py          # cross-history clustering -> Skill/Agent/CLAUDE.md candidates
        habits.py            # per-dimension trend %s, "today" stats
    providers/                       # V3.1: real, read-only environment discovery
        interfaces.py                # EnvironmentProvider/SessionProvider/HookProvider/
                                      # ContextTelemetryProvider abstractions + Null impls
        claude_code_provider.py      # the real scanner (see "what gets scanned" above)
        models.py                    # SkillInfo/AgentInfo/ClaudeMdInfo/McpServerInfo/
                                      # EnvironmentSnapshot/Source/Provenance
        redaction.py                 # secret masking for anything read from disk
    integration/                     # sits ABOVE analyzer+providers+runtime, depends on all three
        environment_matching.py      # prompt <-> real-environment correlation (existing/
                                      # candidate/none tri-state; never in analyzer/ itself,
                                      # which must stay provider-independent)
        approach_advisor.py          # V5: Recommended Approach — synthesizes prompt +
                                      # environment + runtime evidence into one report
        approach_models.py           # ApproachRecommendation / ApproachReport
    runtime/                         # V4: real Claude Code hook-event observation
        models.py                    # RuntimeEvent/RuntimeSignal/ConnectionState/SessionSummary
        hook_receiver.py             # THE command Claude Code actually invokes — see below
        event_source.py              # drains the receiver's JSONL files (HookFileEventSource)
        event_store.py               # thin wrapper over database.db's runtime_* functions
        event_parser.py              # raw hook JSON -> RuntimeEvent (privacy-first: see below)
        runtime_analyzer.py          # events -> RuntimeSignal, evidence-carrying, conservative;
                                      # V5 adds session_coherence() (Context Health) and
                                      # verification_signal()
        hook_installer.py            # the ONLY code that writes to a real settings.json
        runtime_coach.py             # orchestrator the UI controller talks to
    creators/                        # V5: deterministic Skill/Agent file generation
        models.py                    # SkillDraft / AgentDraft / ValidationResult
        skill_creator.py             # validate/render/save a SKILL.md, duplicate-safe
        agent_creator.py             # validate/render/save an Agent .md, duplicate-safe
        atomic_write.py              # same temp-file+os.replace pattern as hook_installer.py
    ui/
        main_window.py, dashboard.py, inspector.py, runtime.py (labeled "Sessions"),
        approach_advisor.py, skill_creator.py, agent_creator.py, mcp_page.py
        (labeled "Integrations"), workshop.py, workshop_lessons.py,
        history.py, habits.py, skills.py, agents.py, context.py, environment.py,
        settings.py, widgets.py, theme.py,
        controller.py         # shared app-state/refresh-all glue + async env scanning +
                               # runtime polling/install/uninstall + Creator/Approach/
                               # Workshop wiring + cross-page navigation callback
        env_worker.py          # QThread worker so environment scanning never blocks the UI
main.py                       # entry point: python main.py
tests/
    test_analyzer.py, test_scoring.py, test_database.py, test_patterns.py,
    test_gui.py,
    test_environment_provider.py    # scanner: fixtures, secrets, broken files, permissions
    test_environment_matching.py    # existing/candidate/none tri-state for Skills+Agents
    test_runtime.py                 # parser, receiver subprocess, drain semantics,
                                     # hook_installer safety, DB/migration, RuntimeCoach.status()
    test_v5.py                      # prompt suggestions, Approach Advisor, session coherence/
                                     # verification, Skill/Agent Creator safety (73 cases)
    benchmark_prompts.json, run_benchmark.py
    runtime_benchmark.json, run_runtime_benchmark.py   # 30 fixture event sequences
```

### Why this shape

- **`analyzer` stays pure and provider-independent**, exactly as in V3 —
  `analyze_prompt(text) -> AnalysisResult` still has no idea whether an
  environment was ever scanned, and its score doesn't change based on one.
  The new environment-matching logic lives in a separate `integration/`
  package specifically *because* it needs both `analyzer` and `providers`
  types — putting it inside `analyzer/` would have made "the analyzer must
  remain independent" (spec section 15) false.
- **Task classification gates which dimensions are scored** — unchanged
  from V3: a "not applicable" dimension contributes neutral weight, never a
  penalty ("missing information ≠ automatically bad", spec section 3/27).
- **`analytics.patterns` still requires repetition** before an INFERRED
  Skill/Agent candidate appears — that's completely separate from, and
  unaffected by, whether a DETECTED resource also exists.
- **`database.migrations`** bumped `CURRENT_SCHEMA_VERSION` to 3 and added
  `environment_scans` (a single-row "latest scan" summary, like
  `schema_version`) plus four `*_metadata` tables and `app_settings` — all
  created idempotently regardless of whether the DB started at the V2
  prototype layout, V3's layout, or fresh. Metadata only: no file contents,
  no MCP args/env, ever stored.
- **`ClaudeCodeEnvironmentProvider` takes `project_root`/`user_home` as
  constructor parameters**, never hard-coded paths (spec section 19) — the
  app defaults `user_home` to `Path.home()` but `project_root` starts as
  `None` until you choose one, and every scanner test builds its own
  `tempfile.TemporaryDirectory()` tree.
- **`runtime/` depends on nothing the rest of the app doesn't already have**
  (`analyzer` for task classification at ingest time, `analytics.patterns`
  for the same Jaccard clustering V3 uses, `providers.redaction` for the
  same secret-masking) — no new third-party dependency for hook handling,
  file draining, or JSON parsing.
- **`hook_installer.py` is the one place in the whole app that writes to a
  real Claude Code config file**, and it's held to a higher bar than the
  read-only V3.1 scanner: atomic writes, additive-only merges, and a
  malformed existing file raises instead of ever being silently
  overwritten. It is never invoked automatically — only from an explicit,
  confirmed button press on the Runtime page.
- **`database.migrations` bumped `CURRENT_SCHEMA_VERSION` to 4** and added
  `runtime_events`/`runtime_sessions` — created idempotently regardless of
  which prior version the database started at (tested going from the
  unversioned V2 layout straight to V4). Coaching *signals* are always
  recomputed from stored events on demand, never persisted — the same
  "don't cache what's cheap to recompute and easy to go stale" choice V3
  already made for Skill/Agent candidates.
- **A same-process gotcha this caught**: `database.db.APP_DIR` is computed
  once at module import time, so tests overriding `db.DB_PATH` alone (the
  existing, established pattern in this codebase) would NOT have isolated
  the runtime event directory — every runtime-aware controller/UI path
  derives it from `db.DB_PATH.parent` instead, specifically so existing
  test isolation continues to work without every test file needing to know
  about a second global to patch.
- **`approach_advisor.py` lives in `integration/`, not `analyzer/` or
  `runtime/`**, because it's the one place that genuinely needs all three
  layers (prompt, environment, runtime) at once — putting it anywhere else
  would have made one of those layers depend on another, breaking
  "environment/runtime integration stays separate from core deterministic
  analysis" (spec Feature 17/rule 18).
- **`creators/` never imports Qt.** `SkillDraft`/`AgentDraft` validation,
  rendering, and saving are pure functions the UI pages call — fully
  testable (and tested — `tests/test_v5.py`) without constructing a single
  widget, same discipline as `analyzer/` and `runtime/`.
- **`database.migrations` bumped `CURRENT_SCHEMA_VERSION` to 5** and added
  two single-row draft tables (`skill_creator_draft`, `agent_creator_draft`)
  — the only new persistence V5 needed, since Approach Advisor / session
  coherence / verification are all recomputed on demand from data V3.1/V4
  already store, matching the "prefer deriving over persisting redundant
  signals" instruction (spec Feature 16).
- **A confidence-hardcoding bug this caught during test-writing**:
  `approach_advisor.py`'s early draft hardcoded `level="high"` for every
  existing-Skill recommendation and `level="medium"` for every
  existing-Agent one, regardless of the underlying match's actual
  confidence — so a medium-confidence match could outrank a genuinely
  high-confidence one from a different resource. An adversarial test
  (`test_report_top_respects_level_ordering`) caught this; fixed by
  deriving `level` from `ResourceMatch.confidence` directly.

## Test results (this build)

Environment note: only Python 3.10.9 was available in the build environment
(spec asks for 3.11+; no internet access to install one here). The code only
uses 3.10-safe syntax, so it will also run unmodified on 3.11+.

```
python -m compileall .                  -> clean, no errors
python -m unittest discover -s tests    -> 242 tests, all passing
                                            (157 from V3/V3.1/V4 + 73 new V5
                                            pure-logic cases in test_v5.py +
                                            12 new V5-specific GUI cases)
python tests/run_benchmark.py           -> 58/58 rating-band matches,
                                            27/27 task-type matches,
                                            58/58 opportunity-flag matches
                                            (unchanged from V3 — confirms the
                                            analyzer really wasn't touched)
python tests/run_runtime_benchmark.py   -> 30/30 fixture sequences matched
                                            expectations (good search-first,
                                            broad-exploration at two
                                            confidence levels, justified-broad
                                            audits correctly NOT flagged,
                                            context growth, agent-delegation,
                                            CLAUDE.md repetition, repeated-
                                            instructions incl. the existing-
                                            Skill-vs-candidate tri-state)
```

`tests/test_v5.py`'s 73 cases cover every category spec Feature 19 asks for:
prompt suggestions (vague/good/informational/broad-justified/broad-narrow/
extraction of files-constraints-expected-behavior/overly-prescriptive/
unicode), Approach Advisor (existing & inferred Skill/Agent, relevant &
irrelevant MCP, CLAUDE.md repetition, no environment, conflicting signals
where an existing resource must outrank an inferred one), session coherence
(healthy long session, unrelated task switch, continuous investigation,
compaction, length-alone-doesn't-lower-health), verification (test command
observed, no evidence, unrelated command, investigation-only task,
documentation task), and Creator safety (duplicate name, malformed name,
empty required fields, explicit save, preview-without-save writes nothing,
secret redaction, atomic-write cleanliness).

`test_runtime.py` additionally invokes the real `hook_receiver.py` as a
**subprocess with stdin piped in**, exactly as Claude Code would — not a
mocked call — and asserts it always exits 0 (including on malformed JSON
and empty stdin, since a nonzero exit or stdout content could disrupt a
real Claude Code session) and never writes outside an isolated fake
`USERPROFILE`/`HOME`.

`test_gui.py` constructs `MainWindow` and every individual page (now
including **Environment**) under the Qt `offscreen` platform, confirming
every `QWidget` subclass calls `super().__init__()` before creating child
Qt objects, and that the V3.1 acceptance scenario (spec section 21 — a
temp `project/CLAUDE.md` + `.claude/skills/security-review/SKILL.md` +
`.claude/agents/security-auditor.md`, scanned, then a matching prompt typed
into the Inspector) is also exercised as `TestIndividualPages.test_environment_page_after_sync_scan`.

**I also launched the real GUI** (not the offscreen test harness) via
`python main.py`, drove it with actual mouse clicks and keyboard input
(Win32 `PrintWindow`/`SendKeys`, not a mock), and watched it live: typing
"Fix my project." into the Prompt Inspector produced the Live Coach's
20/100 POOR verdict with vague-goal feedback in real time, exactly as
specified. That real run caught one bug this suite's `offscreen`-only tests
had missed — see below.

### A real bug the manual GUI run caught

`QSplitter`'s default vertical size policy is `Preferred`, not `Expanding`
(`QScrollArea`'s is `Expanding`). Every page built on `QScrollArea`
(Dashboard, Skills, Agents, Context, Habits) rendered its header tightly by
construction; **Inspector and History**, both built on a bare `QSplitter`,
let their title/subtitle labels balloon to absorb leftover vertical space
instead of the splitter absorbing it — a large, ugly gap under the page
title that no `offscreen` unit test caught, because the test suite checked
"does it construct" and "is the score right," not "does it look right."
Fixed by explicitly setting `splitter.setSizePolicy(Expanding, Expanding)`
in both files. Full test suite re-run afterward: still 118/118 at the time.

The benchmark (`tests/benchmark_prompts.json`, 58 cases) remains a
diagnostic tool, not a hidden hard-coded answer key — small enough to read
end-to-end and re-tune as the heuristics evolve (spec section 26).

### V4: real bugs found before they shipped

Two, both caught by writing and running actual verification rather than
trusting the design on paper:

1. **A classifier false positive.** `REPETITIVE_TRIGGER`'s bare `"for
   every"` alternative (added in V3 for `"For every PR, ..."`) also matched
   `"...report ... for every finding."` in a security-review prompt,
   misclassifying it as `repetitive_workflow`. Caught by the runtime
   benchmark's adversarial "justified broad" case, not by the V3 benchmark
   (which had no `"for every <non-PR-noun>"` case). Fixed by requiring
   `"for every"` to be followed by a specific recurring-unit noun (pr,
   pull request, commit, release, endpoint, deployment, merge); re-ran
   both the V3 benchmark (58/58 still) and full suite (no regressions)
   before moving on.
2. **The same `db.APP_DIR`-is-stale-at-import-time class of bug V3.1 didn't
   have a reason to hit.** `ui/controller.py`'s default runtime event
   source was built from `db.APP_DIR`, a module-level constant computed
   once when `database.db` is first imported — completely unaffected by
   the existing test pattern of overriding `db.DB_PATH` per test. Every
   GUI/runtime test that didn't explicitly construct its own isolated
   `HookFileEventSource` would have pointed at the **real**
   `~/.claude_code_coach/runtime_events/` directory. Caught before writing
   the GUI tests (by tracing through exactly what a Dashboard refresh
   would touch), confirmed empirically (the real directory didn't exist
   yet, so no damage occurred), and fixed by deriving the path from
   `db.DB_PATH.parent` everywhere in the same-process runtime code instead.

I also launched the real GUI a second time for V4 (separate from the V3.1
run above), isolated to a throwaway `USERPROFILE`/`HOME`, and visually
confirmed the Runtime page — new, so not covered by the earlier layout-bug
fix — renders cleanly (it's built on `QScrollArea`, so it wasn't at risk of
the `QSplitter` issue). Verified afterward that the real
`~/.claude_code_coach/coach.db` was untouched by comparing its
last-modified timestamp against the run.

## Manual acceptance test (V3.1, spec section 21)

1. `python main.py` — app opens on Dashboard (light theme).
2. Environment → **Choose Project Folder** → a folder containing
   `CLAUDE.md`, `.claude/skills/<name>/SKILL.md`,
   `.claude/agents/<name>.md` → **Scan Again**. Counts update; each item
   appears as a card labeled `✓ DETECTED`.
3. Prompt Inspector → type a prompt related to a detected Skill/Agent (e.g.
   "Review this API for authentication, authorization, validation and
   security issues.") → the Live Coach's ENVIRONMENT section shows
   `✓ DETECTED Skill — <name> (... confidence match)`.
4. Skills/Agents pages show that same item under "Existing (DETECTED)."
5. Settings → **Clear All Local Data** → environment snapshot and prompt
   history both reset; the chosen project folder/scan-on-startup
   preference is kept (it's configuration, not collected data).
6. Close and restart — no traceback; the last scan's metadata is still
   there until you scan again.

This flow is encoded as `tests/test_gui.py::TestIndividualPages.test_environment_page_after_sync_scan`
and the full V3 flow remains `TestFullAcceptanceFlow`.

## Manual acceptance test (V4, spec section 36)

1. `python main.py` — Dashboard, Inspector, Skills/Agents/Environment all
   still work exactly as in V3.1.
2. Runtime page opens: `○ NOT CONFIGURED`, no session data, no signals —
   correct, since nothing is installed yet.
3. **Install Runtime Hooks…**, pick a `settings.json` (project or user
   level) → confirm. State becomes `○ CONFIGURED (no events yet)`.
4. Use Claude Code for real in that project (or, to verify the pipe itself
   without a live CLI session, pipe a real hook JSON payload into
   `python claude_code_coach/runtime/hook_receiver.py` by hand). Runtime
   events appear; state becomes `● LIVE`; current-session stats populate.
5. A coaching signal appears when the evidence actually supports one (e.g.
   `broad_exploration` after many unsearched reads on a narrowly-scoped
   prompt) — not before.
6. End the session (`SessionEnd`, or close Claude Code) — the session's
   `ended` flag is set; it remains visible in history.
7. Restart the app — session history persists; the schema migration from
   any prior version is idempotent.
8. Settings → confirm "store prompt/response text" defaults off, and the
   retention dropdown actually purges events older than the chosen window.
9. Settings → **Clear All Local Data** — runtime events/sessions are wiped;
   the hook installation itself and your preferences are not (they're
   configuration, not collected data) — use **Remove Runtime Hooks** on the
   Runtime page separately to actually uninstall.

I ran this exact sequence — install → real hook events via a real
`hook_receiver.py` subprocess invocation → LIVE state → a genuine
`broad_exploration` signal → session end → restart-equivalent migration
check → Clear All Local Data → uninstall — end-to-end against a scratch
project and an isolated fake home (never the real `~/.claude/settings.json`
or `~/.claude_code_coach/`), encoded as `tests/test_runtime.py` and the
runtime benchmark runner; the full walkthrough script itself was exploratory
and isn't checked in, since the unit tests already cover each step in
isolation.

## Manual acceptance test (V5)

Ran the V5 spec's "Final Acceptance Demo" scenario live, in the real GUI
(not the offscreen harness), isolated to a throwaway `USERPROFILE`/`HOME`:

1. `python main.py` → Prompt Inspector → typed `Fix my project.` — Live
   Coach showed **20/100 POOR**, task type `implementation`, all four
   IMPROVEMENTS bullets, and the Suggested Prompt panel produced the exact
   canonical rewrite ("Investigate the issue in the project and identify
   the root cause before making changes. / Limit changes to what is
   necessary... / Run the relevant tests..."). Recommended Approach showed
   "A normal Claude Code session/prompt looks appropriate here."
2. Replaced it with the spec's second example prompt (the detailed
   login-investigation one) — score **85/100 GOOD**, four GOOD HABITS
   checks, one IMPROVEMENTS line (missing done-when), Suggested Prompt
   correctly said "Clear task. No major rewrite recommended." and **both
   Copy/Use buttons were disabled** (nothing to act on) — confirms the UI
   only ever offers those buttons when there's an actual suggestion.
3. Skill Creator: filled in a `security-review` draft, **Generate
   Preview** rendered the correct SKILL.md text live, **Save to Project**
   wrote the real file to `.claude/skills/security-review/SKILL.md` (read
   back from disk afterward and confirmed byte-for-byte correct
   frontmatter/body), and the Skills page's automatic post-save re-scan
   picked it up immediately, showing it under "Existing Skills (DETECTED)"
   with `DETECTED`/`PROJECT` badges — closing the full create → detect
   loop live, not just at the unit-test level.
4. Workshop Mode page rendered all twelve concept cards cleanly, scrolled
   correctly.
5. Closed and restarted the app against the same (populated) fake home —
   clean relaunch, window responsive, no traceback.
6. Confirmed throughout that the real `~/.claude_code_coach/coach.db` was
   never touched (compared its last-modified timestamp against the whole
   session).

The independent-work ("investigate why the test suite is slow across
backend, database and frontend") and verification-missing scenarios from
the same demo script are covered by `tests/test_v5.py`
(`TestApproachAdvisor`, `TestVerificationSignal`) and by the interactive
Approach Advisor GUI test (`test_gui.py::test_approach_advisor_page`)
rather than re-driven a second time through native OS dialogs live —
Skill/Agent Creator's blocking confirmation dialogs were already exercised
live in step 3 above; a second full pass through the same native-dialog
flow would have repeated verification already covered without adding new
information.

### Real bugs test-writing caught before this shipped (V5)

1. **A pre-existing V3 classifier false positive**, actually found while
   building the *V4* runtime benchmark — see the V4 section above
   (`REPETITIVE_TRIGGER`'s bare `"for every"`).
2. **`approach_advisor.py` hardcoded confidence levels** (`"high"` for
   every existing-Skill recommendation, `"medium"` for every existing-Agent
   one) instead of deriving them from the actual match confidence — caught
   by `test_report_top_respects_level_ordering` asserting a genuinely
   high-confidence match ranked above a medium one; the hardcoded version
   would have shown the wrong one first whenever a weaker Agent match
   happened to exist alongside a stronger Skill match. Fixed by reading
   `ResourceMatch.confidence` directly.
3. **A Windows-only test-timing race**, not a production bug: two GUI tests
   that save a Skill/Agent into a `tempfile.TemporaryDirectory()` and then
   let the `with` block clean it up immediately hit `PermissionError` on
   Windows, because `save_skill_file()`/`save_agent_file()` kick off an
   async environment re-scan on a background `QThread` that could still be
   reading the very directory being deleted. Fixed in the tests by waiting
   for `controller.is_scanning()` to clear before the temp directory exits
   scope — not a bug real usage would hit (nobody deletes their own project
   directory mid-scan), but worth noting since it's exactly the kind of
   thing that only surfaces by actually running tests against a real
   filesystem instead of mocking it away.

## Known limitations

- **Heuristic, not semantic (prompt analysis).** Unchanged from V3 — the
  analyzer is regex/keyword-signal based. The benchmark exists to measure
  and improve this over time, not to claim it's solved.
- **Environment discovery covers the documented, observed conventions**
  (project/user `CLAUDE.md`, `.claude/skills`, `.claude/agents`, `.mcp.json`,
  and the `~/.claude.json` project MCP registry) but not every possible
  Claude Code configuration shape — e.g. marketplace-installed plugins
  aren't scanned in this version (no such directory convention was found to
  ground an implementation against), and a project registered under a
  differently-cased or differently-slashed path than the one you select in
  the app may not match (path normalization is best-effort, not guaranteed;
  a miss here means "not detected," never a fabricated result).
- **Matching is prompt-vs-resource text overlap**, not semantic
  understanding — a Skill whose description shares no real vocabulary with
  a relevant prompt won't be matched, by design (conservative over clever).
- **`SessionProvider`/`HookProvider`/`ContextTelemetryProvider` (the V3.1
  interfaces) remain unimplemented stubs** — V4's real hook-event telemetry
  was built as its own `runtime/` package instead, since it needed a
  richer model (events, sessions, evidence-carrying signals) than those
  three thin interfaces offered. The Context page still uses locally
  recorded prompt-history statistics, clearly labeled as such; it does not
  yet draw on the new runtime event data.
- **Only 10 hook events are supported**, deliberately (see "Source and
  scope" above) — anything else Claude Code's real hooks system might fire
  is tagged `UNKNOWN` and ignored, not guessed at.
- **No "irrelevant read" or "repeated identical search" detection.** The
  runtime analyzer can count reads/searches and know the task's declared
  scope, but it has no way to judge whether an individual read was
  *actually* relevant to the task — that would need file-content semantic
  understanding this app doesn't have. Documented explicitly in
  `tests/runtime_benchmark.json` cases 11/12 rather than faked with a
  low-confidence guess.
- **Runtime polling is timer-based (every 3s while the Runtime page is
  open), not push-based** — there's no OS-level file-watch, so a burst of
  events can take up to ~3 seconds to appear in the UI. Acceptable for a
  coaching tool, not for anything latency-sensitive.
- **The hook-installer only targets one `settings.json` at a time** — if
  you work across multiple projects, you install (and, if you want it
  gone, remove) hooks per project/user file separately; there's no
  "install everywhere" sweep, by design (each write is a deliberate,
  visible action).
- **Prompt suggestions are template assembly, not rewriting in the AI
  sense.** `prompt_rewriter.py` only ever splices in facts it extracted
  from your own prompt text plus fixed neutral phrasing — it will never
  produce a more fluent rewrite than "Investigate X, focusing on Y.
  Z. Implement the minimal fix... Done when...", by design (no AI API).
- **Session coherence's task-switch detection uses the same path-sensitive
  tokenizer as V3's history clustering** (a full file path like
  `src/auth/login.ts` is one token). A single real task whose prompts
  reference the file at different path depths (`src/auth/` then
  `src/auth/login.ts`) can register lower token overlap than the task
  actually has, occasionally reading as more "switchy" than it is — see
  the tokenizer note in `tests/test_v5.py::TestSessionCoherence
  ::test_healthy_long_session_no_warning`.
- **The parallel-work / independent-areas detector is a single regex
  pattern** (`"across/in/for/spanning A, B and C"`) — a prompt that
  describes genuinely independent workstreams without that exact
  enumeration shape won't trigger it. Conservative by construction (never
  invents independence that isn't textually stated), at the cost of
  missing some phrasings.
- **The Approach Advisor's MCP relevance check is a single name-token
  overlap** between the prompt and each detected server's *name* — it has
  no idea what an MCP server actually does beyond its name, since this app
  never connects to one (by design). A server named `database` will surface
  for a prompt mentioning "database"; a server with an opaque name won't
  surface for a semantically related prompt that doesn't happen to share
  a word with it.
- **Skill/Agent Creator drafts are single-slot** (one in-progress Skill
  draft, one in-progress Agent draft) — starting a second draft (e.g. from
  a different candidate's "Create Skill" button) overwrites the first
  unsaved one. Saved Skills/Agents are of course unaffected.
- **Environment discovery covers the documented, observed conventions**
  (project/user `CLAUDE.md`, `.claude/skills`, `.claude/agents`, `.mcp.json`,
  and the `~/.claude.json` project MCP registry) but not every possible
  Claude Code configuration shape — e.g. marketplace-installed plugins
  aren't scanned in this version (no such directory convention was found to
  ground an implementation against), and a project registered under a
  differently-cased or differently-slashed path than the one you select in
  the app may not match (path normalization is best-effort, not guaranteed;
  a miss here means "not detected," never a fabricated result).
- **Matching is prompt-vs-resource text overlap**, not semantic
  understanding — a Skill whose description shares no real vocabulary with
  a relevant prompt won't be matched, by design (conservative over clever).
- **Environment scanning is on-demand/on-startup only**, never continuous —
  by design (spec section 12): no filesystem watching.
- **Clustering is O(n²)** over prompt/event history (plain Jaccard
  similarity, no ML dependency). Fine for realistic local history sizes;
  would need indexing for much larger histories.
- **Dev/test Python version was 3.10.9**, not 3.11+ (no available 3.11+
  interpreter or internet access in the build environment). No 3.11-only
  syntax is used.
- **GUI visual correctness isn't unit-tested** — three real, functioning
  bugs across three versions (the V3.1 `QSplitter` sizing issue, the V4
  `REPETITIVE_TRIGGER` false positive, and V5's hardcoded confidence
  levels) were only caught by actually running verification, not by the
  automated `offscreen` suite passing. "242/242 passing" is real, but it
  is not by itself proof nothing else like this remains.

## Claude Code capabilities this app actually relies on

Stated plainly, since the spec is explicit that no capability may be
assumed without grounding it:

- **Hooks**: the 10 event types listed under "What's new in V4" — grounded
  against `code.claude.com/docs/en/hooks` *and* this machine's own
  pre-existing `~/.claude/settings.json`, which already had 5 of them
  configured for an unrelated tool before this app touched anything.
- **File-based configuration layout**: `CLAUDE.md` at a project root and
  ancestor directories, `~/.claude/CLAUDE.md`; `.claude/skills/<name>/
  SKILL.md` and `.claude/agents/<name>.md` with `name:`/`description:`
  YAML-ish frontmatter — grounded by having the environment scanner
  actually parse a real Skill installed on the build machine
  (`ui-ux-pro-max`) successfully.
- **MCP server registration**: `.mcp.json` (`{"mcpServers": {...}}`) at a
  project root, and `~/.claude.json`'s `projects["<path>"].mcpServers` —
  grounded by finding and parsing a real entry (`ruflo`) already present
  in this machine's own `~/.claude.json`.
- **Nothing else.** No token counts, no context-window size, no plugin/
  marketplace format, no MCP server *capabilities* (this app never
  connects to one) — all explicitly out of scope rather than guessed at.

## Assumptions made

- That the fetched hooks documentation page, while summarized by a small
  model rather than read verbatim, was accurate for the 10 core events
  this app implements — mitigated by cross-checking every one of them
  against this machine's real, independently-existing configuration
  rather than trusting the fetch alone.
- That Agent `.md` files use the same frontmatter convention as Skill
  `SKILL.md` files (`name:`/`description:` + body) — grounded in the V3.1
  scanner's own working parser for that shape, not newly assumed for V5;
  no Agent file existed on the build machine to parse directly, so this
  is inference from the Skill format's confirmed shape plus general
  Claude Code convention, not a direct observation.
- That a kebab-case name (`^[a-z][a-z0-9]*(-[a-z0-9]+)*$`) is a safe,
  portable choice for both Skill and Agent identifiers — matches every
  real example in the spec and the one real Skill directory name observed
  (`ui-ux-pro-max`).
- That "the project folder you've selected in this app" is the right place
  to write new Skills/Agents — there's no way for this offline desktop app
  to know which folder a real Claude Code session considers its project
  root beyond what you've told it (Environment/Settings page).
