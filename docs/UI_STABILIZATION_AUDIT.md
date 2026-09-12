# UI Stabilization Audit

Investigated by running the real application (PySide6, `QT_QPA_PLATFORM=offscreen`,
so it renders for real without a physical display), measuring real Qt
`minimumSizeHint()`/`sizeHint()` values on the real widget tree, forcing Qt's
QSS parser to log to stderr (`QT_FORCE_STDERR_LOGGING=1`), and grabbing real
pixmaps of the real running app. Nothing below is guessed from reading code
alone unless explicitly marked "not reproduced."

No code changed before this file existed.

---

## Issue 1 — Desktop window goes behind the Windows taskbar (maximized)

**Root cause (confirmed):** `claude_code_coach/ui/main_window.py` never calls
`showMaximized()`/`showFullScreen()` and sets no custom window flags — the
window is a completely standard `QMainWindow`, so Windows' own work-area
handling normally applies with zero app code needed. The real bug is
upstream of that: **`MainWindow`'s *minimum* size is too large.**
`QStackedWidget` (which hosts all 16 pages) reports its own
`minimumSizeHint()` as the **maximum** minimum-size-hint across *every*
page it holds — by Qt design, so switching pages never needs a resize.
Measured on the real app: `MainWindow.minimumSizeHint() == QSize(1836, 846)`
— driven mostly by `Settings` (`(1616, 789)`, see Issue 2) and, to a lesser
extent, `Sessions` (`(1486, 266)`). Because Qt can never size a window below
its `minimumSize`, a "maximized" window is forced to be at least 846px
tall — taller than the *available* work area on many real displays once the
taskbar and DPI scaling are accounted for — so its bottom edge is pushed
under the taskbar. This is a minimum-size propagation bug, not a
maximize/fullscreen bug.

**Affected components:** `ui/main_window.py` (aggregation point via
`QStackedWidget`), `ui/settings.py` (dominant contributor), `ui/runtime.py`
(secondary contributor), `ui/workshop.py`, `ui/dashboard.py`.

**Proposed fix:** eliminate the oversized per-page minimum-size hints at
their source (Issue 2/3's fixes) rather than touching window-creation code
at all — once no page's minimum size hint is absurd, `QStackedWidget`'s
existing (correct, intentional) aggregation behavior stops being a problem.
No `showMaximized()`/geometry/screen code needs to change.

**Risk:** low — no window-management code is touched; the fix is entirely
about not feeding `QStackedWidget` an oversized number in the first place.

---

## Issue 2 — Desktop Settings controls clipped

**Root cause (confirmed):** two independent, compounding defects on the
Settings page:

1. **Two `QCheckBox` labels are long, full sentences.** Unlike `QLabel`,
   `QCheckBox`/`QRadioButton` text **cannot word-wrap in Qt** — there is no
   `setWordWrap()` on `QAbstractButton`. A long label forces the checkbox's
   (and therefore the whole page's) minimum width to fit the *entire*
   sentence on one line. Measured: `collect_content_checkbox` → **1522px**,
   `pause_coaching_checkbox` → **1314px** (the latter added in the Phase 4E
   pass). `scan_startup_checkbox` also uses this pattern but stays
   moderate (690px).
2. **Settings has no `QScrollArea`** — every other page with meaningfully
   tall content (`Runtime`/`Sessions`, `Workshop Mode`) already wraps its
   content in one; Settings stacks five full panels directly in one
   `QVBoxLayout`, so its entire natural height (789px) becomes an
   unshrinkable minimum, with nowhere to scroll if a real screen is
   shorter than that.

Together: Settings' `minimumSizeHint()` is `(1616, 789)` — nothing in that
page can be displayed smaller than that, so on any window narrower/shorter
than that, its controls are truly clipped, not just visually cramped.

**Affected components:** `ui/settings.py`.

**Proposed fix:** shorten both checkbox labels to a short imperative phrase
and move the explanatory sentence into a separate, properly
`setWordWrap(True)` `QLabel` underneath (the same visual information stays
present, just in a widget that can actually wrap); wrap the page's content
in a `QScrollArea`, mirroring `ui/runtime.py`'s existing, already-correct
pattern exactly.

**Risk:** low — purely additive widget restructuring within one page;
no controller/business logic touched.

---

## Issue 3 — Excessive grey backgrounds on ordinary Desktop labels

**Root cause (confirmed, visually).** `ui/theme.py`'s global stylesheet
rule:

```css
QWidget { background: #f5f6f8; color: #1a1d23; font-size: 13px; }
```

Once *any* app-wide `QStyleSheet` is active, Qt switches every matching
widget to the stylesheet-driven paint path — so this one broad rule makes
**every plain `QLabel` (and every other bare `QWidget`) paint its own
opaque background rectangle**, not just the intended page/window
background. Against the page itself (`#f5f6f8`) this is invisible: the
label's own background matches its surroundings. But inside a white
`#Card`/`#Panel` (`background: #ffffff`), each label paints a *visibly
different*, slightly grey rectangle behind just its own text — exactly the
"grey box behind every value" pattern reported. Rendered and confirmed
directly (`.tmp_shots/before_dashboard.png`, produced during this audit):
every StatCard's title/value/subtitle line, and every plain info line
inside a Settings/Database panel, has its own distinct grey rectangle
against the surrounding white card.

**Affected components:** `ui/theme.py` (the shared, app-wide stylesheet —
this is the "one common cause" the brief asks to find, not a per-widget
issue).

**Proposed fix:** remove `background` from the blanket `QWidget {}` rule
(keep `color`/`font-size`, which are correct and desired everywhere).
Every purpose-built container that *should* have a visible surface already
has its own explicit, correctly-scoped rule (`QMainWindow`, `#Sidebar`,
`#Card`, `#Panel`, inputs, etc.) — removing the blanket rule does not
remove any intended background, only the accidental one painted behind
plain text.

**Risk:** low-medium — broad rule, but the removal only *stops* an
unintended paint; every widget that is supposed to have a background
already declares one via a specific selector. Verified after the fix (see
Final Report) by re-rendering the same screenshot.

---

## Issue 4 — "Unknown property cursor" repeated many times

**This is a Desktop (Qt) defect, not a VS Code Webview defect** — the
brief's assumption that this originates in the extension does not match
the evidence. Investigated both sides:

- **VS Code**: `grep cursor` across `vscode-extension/src/` finds exactly
  two occurrences, both `style="cursor:pointer; ..."` inside real HTML
  `<summary>` elements rendered by a real Chromium-based Webview — valid,
  correctly-formatted CSS, fully supported by the renderer. This cannot
  produce any diagnostic.
- **Desktop**: `ui/theme.py`'s QSS has **four** `cursor: pointer;`
  declarations (`#NavButton`, `QPushButton`, `QCheckBox, QRadioButton`,
  `QComboBox`). **Qt Style Sheets do not support the CSS `cursor`
  property at all** — it must be set via `QWidget.setCursor()` in code.
  Confirmed by forcing Qt's own logging to stderr and constructing three
  widgets under the real app stylesheet:

  ```text
  $ QT_FORCE_STDERR_LOGGING=1 python -c "... app.setStyleSheet(theme.STYLESHEET) ..."
  Unknown property cursor
  Unknown property cursor
  ... (11 times for 3 widgets + the stylesheet's own rule matches)
  ```

  With dozens of buttons/checkboxes/combo boxes across 16 real pages, this
  reproduces "many times" exactly as reported. (Qt's own `qWarning()`
  output on Windows goes to the OS debugger channel by default, not the
  visible console, unless `QT_FORCE_STDERR_LOGGING=1` is set or a debugger
  is attached — which is almost certainly why this was seen intermittently
  rather than on every run.)

**Affected components:** `ui/theme.py` only.

**Proposed fix:** remove all four invalid `cursor: pointer;` QSS
declarations. Restore the intended pointer-cursor UX (the stylesheet's own
docstring calls this out as a deliberate feature) via one small, shared
Qt event filter (`ui/widgets.py`) installed once on the `QApplication` in
`app.py` — sets `Qt.PointingHandCursor` on hover for
`QPushButton`/`QCheckBox`/`QRadioButton`/`QComboBox`, restoring the same
UX through a Qt-supported mechanism instead of invalid QSS. One shared
fix, not per-widget patches.

**Risk:** low — one small, well-scoped, purely additive `QObject` event
filter; no business logic.

---

## Issue 5 — VS Code Webview "excessive grey background"

**Investigated; not reproduced in code.** `coachPanel.ts`'s `<style>`
block has exactly one `background` rule, deliberately scoped to
`.coaching-card` (the intentional "Current Coaching"/"Approach"
recommendation card) — there is no `div{background}`, `*{background}`, or
any other broad selector. `.row` (used for every label/value line — the
webview's equivalent of the Desktop's plain info lines) declares no
background at all. Unlike Issue 4/3, this file does not contain the class
of defect the brief describes.

Most likely explanation: the screenshots that motivated this issue were
the *Desktop* ones (Issue 3), or the webview's default body background
(VS Code automatically applies `var(--vscode-editor-background)` to every
webview's `<body>` unless overridden — correct, theme-following behavior,
not an accidental fill).

**Proposed fix:** none — no defect found. Documenting this explicitly
rather than inventing a change, per the "do not touch working code" rule.

**Risk:** n/a.

---

## Issue 6/8/19 — Webview clipping, long text/paths/IDs, narrow-panel responsiveness

**Root cause (confirmed).** `.row { display: flex; justify-content:
space-between; gap: 1em; }` is used for every label/value line, including
ones that can hold an arbitrarily long, unbreakable string — a Windows
path (`Workspace`), a session UUID (`Session ID`), a Skill path. Flex items
default to `min-width: auto`, meaning a long unbroken string will **not**
wrap and instead forces the row (and the whole page) wider, causing
horizontal clipping exactly when the sidebar/panel is narrow (Issues 6, 8,
19 are three symptoms of this one cause). Nothing in the stylesheet sets
`overflow-wrap`/`min-width: 0` anywhere.

Everything else checked for Issue 6 is already correct: no fixed heights,
no `overflow: hidden`, no nested scroll containers — the panel is already
one natural, single scrolling HTML document (the Webview host provides the
only scrollbar), matching "prefer one clear vertical scrolling region."

**Affected components:** `coachPanel.ts`'s `<style>` block.

**Proposed fix:** add `overflow-wrap: anywhere;` to `body` (inherited
everywhere, including inside `.row`, `.coaching-body`, `.prompt-quote`,
etc.) plus `min-width: 0` on `.row > *` so flex children can actually
shrink. `overflow-wrap: anywhere` (not `break-word`) is used deliberately
— it is the one that also reduces the *intrinsic minimum content size* used
for flex-item sizing, which `break-word` does not do.

**Risk:** low — two additive CSS rules; no HTML structure changes.

---

## Issue 7 — VS Code panel actions must remain visible

**Investigated; not reproduced.** `.actions a` are plain inline `<a>`
elements inside a plain block `<div class="actions">` — no
`white-space: nowrap`, `overflow: hidden`, or fixed width anywhere that
could hide them. Inline elements wrap onto new lines at the container's
edge by default. Already correct.

**Proposed fix:** none needed.

---

## Issue 9 — "Close" tooltip

**Investigated; not reproduced as a bug.** No code anywhere in this
repository creates a widget/button/tooltip with the text "Close" (checked
via `grep` across `ui/` and `vscode-extension/src/`). This is Scenario A
from the brief: the native OS/Qt title-bar tooltip that appears on hovering
the window's own close button — chrome the OS draws, not something this
app's code controls or can control.

**Proposed fix:** none. Do not disable tooltips.

---

## Issue 10/11 — Cross-client consistency, status bar/panel consistency

**Investigated; already correct, pre-existing from Phase 4E.**
`deriveCoachStatus()` (`coaching.ts`) is the single function both the
status bar and the panel key off of, fed by the *same* `/api/v1/session`
response (including the Phase 4E `primary_signal`/`coaching_paused`
fields) — the exact "status bar says Ready while panel shows a warning"
bug is already structurally prevented. Desktop and VS Code already share
the same vocabulary (Ready/Attention/Offline/Paused; Current
Coaching/Approach/Session/Verification/Environment section names). No
semantic change is needed or made here — purely a presentation pass, per
the brief.

---

## Issue 12 — Session presentation

**Already correct** (implemented in the prior session-titles phase):
Desktop's Runtime page and VS Code's panel both show the title as the
primary heading and the UUID as smaller, secondary text with a full-value
tooltip. No change needed.

---

## Issue 13 — Context Health wording

**Already correct.** `ui/context.py` and `coachPanel.ts` both carry
"Local coaching heuristic — not an official Anthropic metric" verbatim
next to the number. No fake token counts anywhere. No change needed.

---

## Issue 14 — Notification UX

**Not touched.** `coaching.ts`'s `shouldNotify()`/dedup logic is unchanged
by this pass (verified: no edits to `coaching.ts`, `coachingState.ts` in
this stage). Documented here only to confirm the CRITICAL RULE was
respected.

---

## Issue 16 — Desktop Dashboard content

**Reviewed.** Dashboard already includes Recommendations, Today's
Coaching, Habit Trends, Opportunities, and a Runtime/backend readout
section (verified by reading `ui/dashboard.py` in full). Two of its labels
(`Current session: ...`, the CLAUDE.md-candidate/context-management lines)
are missing `setWordWrap(True)` — the same defect class as Issue 2/3,
found at widths 856/715/598px during the same inventory pass. Fixed
alongside Issue 2 (same root-cause class), not as a separate redesign.

---

## Issue 17/18 — Responsive resize / DPI scaling

**Measured directly.** Before any fix, requesting `window.resize(1400,
900)` on the real app was silently overridden by Qt to `1836×900` — Qt
will never honor a resize below `minimumSize()`. This is the same root
cause as Issue 1, not a separate DPI-specific bug: PySide6/Qt 6.11 already
declares Per-Monitor-V2 DPI awareness automatically (no manual
`SetProcessDpiAwareness`/`AA_EnableHighDpiScaling` call exists anywhere in
this codebase, and none is needed on Qt 6). DPI scaling makes the *same*
oversized-minimum-size bug worse (fewer effective logical pixels available
at 125%/150%), it does not introduce a new one. Fixing Issues 1–3
directly fixes 17/18 as a side effect — re-measured after the fix (see
Final Report).

**Proposed fix:** none beyond Issues 1–3's fixes. No pixel-specific hacks,
no hardcoded screen sizes — matching the brief's explicit instruction.

---

## Issue 20 — Dynamic refresh stability

**Investigated; already correct on both sides.**

- **VS Code**: the panel is created with `enableScripts: false` — there is
  no injected JavaScript anywhere, so there is no mechanism by which a
  refresh could duplicate event handlers or leak DOM state. Every refresh
  fully replaces `webview.html`; every "action" is a native VS Code
  `command:` URI, handled by the host, not by page script.
- **Desktop**: `ui/runtime.py`'s `_clear()` helper (used for
  `session_cards`/`signals_layout` on every 3s poll tick) removes and
  `deleteLater()`s every child widget before rebuilding — the correct Qt
  pattern; no leak, no duplication.

**Proposed fix:** none needed.

---

## Issue 21 — Light/dark themes, not color-alone

**Investigated.**

- **VS Code**: every color in `coachPanel.ts`'s CSS is a
  `var(--vscode-*, fallback)` — it already follows the editor's
  light/dark/high-contrast theme automatically, and state is always paired
  with text/an icon (badges say "Ready"/"Offline" in words; coaching cards
  carry an icon + a written level via `Badge`), never color alone. Already
  correct; unaffected by this pass.
- **Desktop**: ships one fixed, deliberately-chosen light theme with a
  dark sidebar accent (`ui/theme.py`'s own docstring). It does not follow
  the Windows OS dark-mode setting. This is a **pre-existing design
  choice**, not a defect this pass introduced — building OS-dark-mode
  support would be a new theming *feature*, explicitly out of scope for a
  stabilization pass ("do not add new features"). Documented honestly as a
  known limitation rather than silently left unmentioned.

**Proposed fix:** none (Desktop dark-mode following is out of scope by the
brief's own rules).

---

## Issue 22 — Accessibility

**Reviewed, not deeply re-audited** (would require a real screen
reader/keyboard-only pass on a real interactive desktop, unavailable in
this environment). What was checked from code: every state indicator
pairs color with text/an icon (Issue 21); all interactive Qt widgets
(`QPushButton`, `QCheckBox`, `QComboBox`) are native, keyboard-focusable
Qt widgets by default (no custom-drawn, non-focusable controls anywhere);
`QToolTip` styling exists and is used on Desktop; the VS Code panel's
links are real `<a href="command:...">` elements, natively
keyboard-accessible in a Webview. No regressions introduced by this pass'
fixes (none of them touch focus order, tab order, or keyboard bindings).

---

## Issue 23 — Functional regression risk

Every fix identified above is either (a) removing an invalid/unintended
style rule, (b) adding `setWordWrap`/a `QScrollArea` (purely visual,
additive), (c) shortening a checkbox's on-screen label while keeping its
`toggled` signal, connected slot, and setting-persistence logic completely
unchanged, or (d) two additive CSS rules in the Webview. None change a
controller method, an API contract, a database column, or a signal's
`kind`/`level`/wiring. Full regression suite run after implementation (see
Final Report).

---

## Summary table

| Issue | Root cause | Files | Risk |
|---|---|---|---|
| 1 (taskbar overlap) | `QStackedWidget` aggregates worst-case page minimum size; Settings/Sessions/Workshop feed it oversized hints | `main_window.py` (no change — fixed at the source) | low |
| 2 (Settings clipped) | Un-wrappable long `QCheckBox` text + missing `QScrollArea` | `settings.py` | low |
| 3 (grey boxes) | Blanket `QWidget{background}` QSS rule | `theme.py` | low-medium |
| 4 (cursor warnings) | Invalid `cursor` property in QSS (Desktop, not VS Code) | `theme.py`, new filter in `widgets.py`, `app.py` | low |
| 5 (VS Code grey bg) | Not reproduced — no defect found | — | n/a |
| 6/8/19 (webview clipping/long text) | Flex rows with no `overflow-wrap`/`min-width:0` | `coachPanel.ts` | low |
| 7 (actions hidden) | Not reproduced | — | n/a |
| 9 (Close tooltip) | Not reproduced — native OS chrome | — | n/a |
| 16 (Dashboard labels) | Same class as Issue 2/3 (missing `setWordWrap`) | `dashboard.py` | low |
| 17/18 (resize/DPI) | Same as Issue 1 | (fixed via 1–3) | low |
| 10/11/12/13/14/20/21/22 | Verified already correct / out of scope | — | n/a |
