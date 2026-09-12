"""Workshop Mode 2.0: a structured, offline, lesson-based Claude Code
training course (see docs on Workshop 2.0 for the full curriculum spec).

Curriculum content and progress/quiz logic live in ``claude_code_coach.
workshop`` (Qt-free, independently testable); this file is purely the
rendering layer — course map, lesson panel, quiz UI, and the three small
bespoke interactive widgets (prompt lab, context meter, decision wizard)
the curriculum data tags a handful of lessons with.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QFrame, QHBoxLayout, QLabel, QPushButton, QRadioButton,
    QScrollArea, QTextEdit, QVBoxLayout, QWidget,
)

from claude_code_coach.workshop import LEVELS, engine
from claude_code_coach.workshop.models import Lesson, Level, SourceRef

from . import theme
from .widgets import Panel, SectionHeader, page_header

_SOURCE_COLOR = {
    "official_anthropic": theme.GOOD,
    "claude_code_documented": theme.INFO,
    "community_practice": theme.WARN,
    "coach_heuristic": theme.TEXT_MUTED,
}


def _clear_layout(layout) -> None:
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            # takeAt() only detaches the widget from the LAYOUT's geometry
            # management — it stays a visible, painted child of its parent
            # until deleteLater()'s deferred deletion actually runs on a
            # later event-loop pass. Hiding it immediately closes a real
            # (if normally brief) window where old lesson content could
            # still be on screen, overlapping the freshly-built widgets a
            # rebuild adds into the same region, until that deferred
            # deletion resolves.
            w.hide()
            w.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


def _body_label(text: str, *, muted: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setWordWrap(True)
    color = theme.TEXT_MUTED if muted else theme.TEXT_PRIMARY
    lbl.setStyleSheet(f"color: {color}; font-size: 12.5px;")
    return lbl


def _field_block(heading: str, text: str) -> QWidget | None:
    if not text:
        return None
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(3)
    head = QLabel(heading)
    head.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px; font-weight: 700; "
                        "letter-spacing: 0.5px;")
    layout.addWidget(head)
    layout.addWidget(_body_label(text))
    return box


def _sources_row(sources: tuple[SourceRef, ...]) -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.setSpacing(4)
    head = QLabel("SOURCES")
    head.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px; font-weight: 700; "
                        "letter-spacing: 0.5px;")
    layout.addWidget(head)
    for src in sources:
        color = _SOURCE_COLOR.get(src.source_type.value, theme.TEXT_MUTED)
        row = QHBoxLayout()
        row.setSpacing(8)
        badge = QLabel(src.label)
        badge.setStyleSheet(theme.badge_style(color))
        badge.setObjectName("Badge")
        row.addWidget(badge)
        if src.url:
            link = QLabel(f'<a href="{src.url}">{src.title}</a>')
            link.setOpenExternalLinks(True)
            link.setStyleSheet(f"color: {theme.INFO}; font-size: 11.5px;")
        else:
            link = QLabel(src.title)
            link.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
        row.addWidget(link)
        row.addStretch()
        layout.addLayout(row)
        if src.note:
            note = _body_label(src.note, muted=True)
            note.setStyleSheet(note.styleSheet() + " font-size: 11px;")
            layout.addWidget(note)
    return box


class _CourseMap(QFrame):
    """The left-hand level list — a course map, not the app's own sidebar."""

    def __init__(self, on_select, parent=None):
        super().__init__(parent)
        self._on_select = on_select
        self.setFixedWidth(210)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 8, 0)
        outer.setSpacing(6)
        self._buttons: dict[str, QPushButton] = {}

        head = QLabel("COURSE MAP")
        head.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10px; font-weight: 700; "
                            "letter-spacing: 0.5px;")
        outer.addWidget(head)

        # 21 levels + a certificate row is too tall to fit unscrolled on a
        # shorter screen — this list scrolls on its own rather than forcing
        # the whole page (and so the whole window) taller, the same
        # principle main_window.py's own sidebar nav list already applies.
        scroll = QScrollArea()
        scroll.setObjectName("WorkshopMapScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        content = QWidget()
        # Same fix, same reason as main_window.py's own sidebar nav list
        # (see its _build_sidebar for the full explanation): a bare
        # QScrollArea viewport paints an OS-default background rather than
        # honoring the page's own — give it an explicit objectName + a
        # concrete-color rule in theme.py rather than "transparent" (which
        # was proven not to reliably apply to a viewport in this Qt build).
        content.setObjectName("WorkshopMapContent")
        scroll.viewport().setObjectName("WorkshopMapViewport")
        self._layout = QVBoxLayout(content)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(2)
        scroll.setWidget(content)
        outer.addWidget(scroll, 1)

        for level in LEVELS:
            btn = QPushButton(level.title)
            btn.setObjectName("Secondary")
            btn.setCheckable(True)
            btn.setStyleSheet("text-align: left; padding: 7px 10px; font-size: 11.5px;")
            btn.clicked.connect(lambda checked=False, lvl=level: self._on_select(lvl))
            self._buttons[level.id] = btn
            self._layout.addWidget(btn)

        self._cert_button = QPushButton("🎓  Certificate")
        self._cert_button.setObjectName("Secondary")
        self._cert_button.setCheckable(True)
        self._cert_button.setStyleSheet("text-align: left; padding: 7px 10px; font-size: 11.5px;")
        self._cert_button.clicked.connect(lambda: self._on_select(None))
        self._layout.addWidget(self._cert_button)
        self._layout.addStretch()

    def refresh(self, progress, current_level_id: str | None) -> None:
        glyphs = {"done": "✓ ", "current": "→ ", "upcoming": "○ "}
        for level in LEVELS:
            btn = self._buttons[level.id]
            status = engine.level_status(level, progress)
            btn.setText(f"{glyphs[status]}{level.title}")
            btn.setChecked(level.id == current_level_id)
        complete = engine.is_course_complete(progress)
        self._cert_button.setText("🎓  Certificate" + ("" if complete else " (locked)"))
        self._cert_button.setChecked(current_level_id is None)


class Workshop(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)
        self.progress = engine.load_progress()
        self._current_lesson: Lesson | None = None
        self._quiz_groups: list[QButtonGroup] = []
        self._quiz_result_labels: list[QLabel] = []

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.setSpacing(10)
        outer.addLayout(page_header(
            "Claude Code Workshop",
            "A structured, offline course — not a certification, and not affiliated "
            "with Anthropic beyond citing its public documentation.",
        ))

        # Existing behavior (unchanged): this toggle drives the expanded
        # "why this matters" / "try this" explanations on the Prompt
        # Inspector — kept exactly as it was (short label + separate
        # wrapping detail line: UI stabilization pass, Issue 2 — a
        # QCheckBox's own label can't word-wrap in Qt), just relocated
        # into this page's new layout.
        self.toggle = QCheckBox("Enable Workshop Mode")
        self.toggle.toggled.connect(self._on_toggle)
        outer.addWidget(self.toggle)
        toggle_detail = QLabel(
            "Expanded ‘why this matters’ / ‘try this’ explanations in the Prompt Inspector."
        )
        toggle_detail.setWordWrap(True)
        toggle_detail.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        outer.addWidget(toggle_detail)

        # -- progress bar --------------------------------------------------
        progress_row = QHBoxLayout()
        self._progress_label = QLabel()
        self._progress_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
        progress_row.addWidget(self._progress_label)
        outer.addLayout(progress_row)
        self._progress_bar = _ProgressBar()
        outer.addWidget(self._progress_bar)

        # -- course map + lesson panel --------------------------------------
        body = QHBoxLayout()
        body.setSpacing(18)
        self._course_map = _CourseMap(self._open_level)
        body.addWidget(self._course_map)

        self._lesson_scroll = QScrollArea()
        self._lesson_scroll.setWidgetResizable(True)
        self._lesson_content = QWidget()
        self._lesson_layout = QVBoxLayout(self._lesson_content)
        self._lesson_layout.setSpacing(14)
        self._lesson_scroll.setWidget(self._lesson_content)
        body.addWidget(self._lesson_scroll, 1)
        outer.addLayout(body, 1)

        self.refresh()

    # -- controller hooks --------------------------------------------------
    def refresh(self) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(self.controller.workshop_mode)
        self.toggle.blockSignals(False)
        self._show_lesson(engine.resume_lesson_id(self.progress))

    def _on_toggle(self, checked: bool) -> None:
        self.controller.set_workshop_mode(checked)

    # -- navigation --------------------------------------------------------
    def _open_level(self, level: Level | None) -> None:
        if level is None:
            self._show_certificate()
            return
        done_ids = {l.id for l in level.lessons if self.progress.is_complete(l.id)}
        target = next((l.id for l in level.lessons if l.id not in done_ids), level.lessons[0].id)
        self._show_lesson(target)

    def _show_lesson(self, lesson_id: str) -> None:
        lesson = engine.lesson_by_id(lesson_id)
        if lesson is None:
            self._show_certificate()
            return
        self._current_lesson = lesson
        self.progress.current_lesson_id = lesson.id
        engine.save_progress(self.progress)
        level = engine.level_for_lesson(lesson.id)
        self._course_map.refresh(self.progress, level.id if level else None)
        self._update_progress_bar()
        self._render_lesson(lesson, level)

    def _update_progress_bar(self) -> None:
        pct = engine.percent_complete(self.progress)
        self._progress_bar.set_percent(pct)
        total = len(engine.ALL_LESSONS)
        self._progress_label.setText(
            f"Progress: {pct}%  •  {len(self.progress.completed_lessons)} / {total} lessons"
        )

    # -- lesson rendering ----------------------------------------------------
    def _render_lesson(self, lesson: Lesson, level: Level | None) -> None:
        _clear_layout(self._lesson_layout)
        self._quiz_groups = []
        self._quiz_result_labels = []

        header = QLabel(f"LEVEL {level.id if level else '?'} · {level.title if level else ''}")
        header.setStyleSheet(f"color: {theme.ACCENT}; font-size: 10.5px; font-weight: 700; "
                              "letter-spacing: 0.5px;")
        self._lesson_layout.addWidget(header)

        title = QLabel(lesson.title)
        title.setStyleSheet("font-size: 19px; font-weight: 700;")
        self._lesson_layout.addWidget(title)

        obj = _body_label(lesson.objective, muted=True)
        self._lesson_layout.addWidget(obj)

        panel = Panel()
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(18, 16, 18, 16)
        panel_layout.setSpacing(12)
        for heading, text in (
            ("WHAT", lesson.what), ("WHY", lesson.why), ("EXAMPLE", lesson.example),
            ("WATCH OUT FOR", lesson.bad_approach), ("BETTER APPROACH", lesson.better_approach),
        ):
            block = _field_block(heading, text)
            if block is not None:
                panel_layout.addWidget(block)
        self._lesson_layout.addWidget(panel)

        if lesson.interactive:
            self._lesson_layout.addWidget(SectionHeader("TRY IT"))
            self._lesson_layout.addWidget(self._build_interactive(lesson.interactive))
        elif lesson.try_it:
            self._lesson_layout.addWidget(SectionHeader("TRY IT"))
            self._lesson_layout.addWidget(self._build_try_it(lesson))

        if lesson.quiz:
            self._lesson_layout.addWidget(SectionHeader("QUIZ"))
            self._lesson_layout.addWidget(self._build_quiz(lesson))

        if lesson.takeaway:
            take_panel = Panel()
            take_panel.setStyleSheet(theme.status_border_style(theme.GOOD))
            tl = QVBoxLayout(take_panel)
            tl.setContentsMargins(16, 12, 16, 12)
            head = QLabel("KEY TAKEAWAY")
            head.setStyleSheet(f"color: {theme.GOOD}; font-size: 10px; font-weight: 700; "
                                "letter-spacing: 0.5px;")
            tl.addWidget(head)
            tl.addWidget(_body_label(lesson.takeaway))
            self._lesson_layout.addWidget(take_panel)

        if lesson.sources:
            self._lesson_layout.addWidget(_sources_row(lesson.sources))

        nav_row = QHBoxLayout()
        prev_id = engine.previous_lesson_id(lesson.id)
        next_id = engine.next_lesson_id(lesson.id)
        prev_btn = QPushButton("← Previous")
        prev_btn.setObjectName("Secondary")
        prev_btn.setEnabled(prev_id is not None)
        prev_btn.clicked.connect(lambda: self._show_lesson(prev_id) if prev_id else None)
        nav_row.addWidget(prev_btn)
        nav_row.addStretch()

        if not lesson.quiz:
            # No quiz to gate completion on — reading it is enough.
            self.progress.mark_complete(lesson.id)
            engine.mark_completion_date_if_newly_complete(self.progress)
            engine.save_progress(self.progress)

        next_btn = QPushButton("Next lesson →" if next_id else "Finish course")
        next_btn.clicked.connect(
            lambda: self._show_lesson(next_id) if next_id else self._show_certificate()
        )
        nav_row.addWidget(next_btn)
        self._lesson_layout.addLayout(nav_row)
        self._lesson_layout.addStretch()

    def _build_try_it(self, lesson: Lesson) -> QWidget:
        try_it = lesson.try_it
        box = Panel()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.addWidget(_body_label(try_it.instructions))
        if try_it.related_page:
            btn = QPushButton(try_it.action_label)
            btn.clicked.connect(lambda: self.controller.navigate_to(try_it.related_page))
            row = QHBoxLayout()
            row.addWidget(btn)
            row.addStretch()
            layout.addLayout(row)
        return box

    # -- quiz ----------------------------------------------------------------
    def _build_quiz(self, lesson: Lesson) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)

        for qi, question in enumerate(lesson.quiz):
            qpanel = Panel()
            qlayout = QVBoxLayout(qpanel)
            qlayout.setContentsMargins(16, 12, 16, 12)
            qlayout.setSpacing(6)
            prompt = QLabel(question.prompt)
            prompt.setWordWrap(True)
            prompt.setStyleSheet("font-weight: 600; font-size: 12.5px;")
            qlayout.addWidget(prompt)

            group = QButtonGroup(box)
            group.setExclusive(True)
            for oi, option in enumerate(question.options):
                radio = QRadioButton(option.text)
                radio.setStyleSheet("font-size: 12px;")
                group.addButton(radio, oi)
                qlayout.addWidget(radio)
            self._quiz_groups.append(group)

            result_label = QLabel()
            result_label.setWordWrap(True)
            result_label.setStyleSheet("font-size: 11.5px;")
            result_label.hide()
            self._quiz_result_labels.append(result_label)
            qlayout.addWidget(result_label)

            layout.addWidget(qpanel)

        submit_row = QHBoxLayout()
        submit = QPushButton("Check answers")
        submit.clicked.connect(lambda: self._on_quiz_submit(lesson))
        submit_row.addWidget(submit)
        submit_row.addStretch()
        self._quiz_status = QLabel()
        self._quiz_status.setStyleSheet("font-weight: 600; font-size: 12.5px;")
        submit_row.addWidget(self._quiz_status)
        layout.addLayout(submit_row)
        return box

    def _on_quiz_submit(self, lesson: Lesson) -> None:
        answers: dict[int, int] = {}
        for qi, group in enumerate(self._quiz_groups):
            checked = group.checkedId()
            if checked != -1:
                answers[qi] = checked

        correct, total = engine.score_quiz(lesson, answers)
        for qi, question in enumerate(lesson.quiz):
            label = self._quiz_result_labels[qi]
            chosen = answers.get(qi)
            right = question.correct_index()
            ok = chosen == right
            color = theme.GOOD if ok else theme.BAD
            prefix = "✓ Correct — " if ok else "✗ Not quite — "
            label.setStyleSheet(f"color: {color}; font-size: 11.5px;")
            label.setText(prefix + question.explanation)
            label.show()

        passed = lesson.passes(correct, total)
        self._quiz_status.setStyleSheet(f"color: {theme.GOOD if passed else theme.WARN}; "
                                         "font-weight: 600; font-size: 12.5px;")
        self._quiz_status.setText(f"{correct}/{total} correct" + (" ✓" if passed else ""))

        if passed:
            self.progress.mark_complete(lesson.id)
        self.progress.record_quiz(lesson.id, correct, total)
        engine.mark_completion_date_if_newly_complete(self.progress)
        engine.save_progress(self.progress)
        self._course_map.refresh(self.progress, engine.level_for_lesson(lesson.id).id
                                  if engine.level_for_lesson(lesson.id) else None)
        self._update_progress_bar()

    # -- bespoke interactive widgets ------------------------------------------
    def _build_interactive(self, tag: str) -> QWidget:
        if tag in ("prompt_lab",):
            return _PromptLab(self.controller)
        if tag == "context_meter":
            return _ContextMeter()
        if tag == "decision_wizard":
            return _DecisionWizard()
        return _body_label(f"(unknown interactive widget: {tag})", muted=True)

    # -- certificate -----------------------------------------------------------
    def _show_certificate(self) -> None:
        _clear_layout(self._lesson_layout)
        self._course_map.refresh(self.progress, None)
        self._update_progress_bar()
        summary = engine.completion_summary(self.progress)

        title = QLabel("CLAUDE CODE WORKFLOW COACH")
        title.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 11px; font-weight: 700; "
                             "letter-spacing: 1px;")
        self._lesson_layout.addWidget(title)

        headline = QLabel("Workshop complete" if summary.complete else "Workshop in progress")
        headline.setStyleSheet("font-size: 22px; font-weight: 700;")
        self._lesson_layout.addWidget(headline)

        note = _body_label(
            "This is a workshop completion summary, not an official Anthropic "
            "certification.", muted=True,
        )
        self._lesson_layout.addWidget(note)

        panel = Panel()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(18, 16, 18, 16)
        pl.setSpacing(8)
        pl.addWidget(_body_label(
            f"Modules completed: {summary.modules_completed} / {summary.modules_total}"
        ))
        if summary.score_pct is not None:
            pl.addWidget(_body_label(f"Quiz score: {summary.score_pct}% "
                                      f"({summary.quiz_correct}/{summary.quiz_total})"))
        if self.progress.completion_date:
            pl.addWidget(_body_label(f"Completed on: {self.progress.completion_date}"))

        if summary.complete:
            pl.addWidget(SectionHeader("YOU UNDERSTAND"))
            for line in (
                "Prompt design", "Context management", "Sessions", "Compaction",
                "CLAUDE.md", "Skills", "Agents", "MCP", "Hooks", "Verification",
                "Workflow strategy", "Context/token efficiency",
            ):
                pl.addWidget(_body_label(f"✓ {line}"))
        self._lesson_layout.addWidget(panel)

        if summary.recommended_next:
            pl2 = Panel()
            pl2.setStyleSheet(theme.status_border_style(theme.WARN))
            l2 = QVBoxLayout(pl2)
            l2.setContentsMargins(16, 12, 16, 12)
            l2.addWidget(SectionHeader("RECOMMENDED NEXT LESSONS"))
            for lesson_id in summary.recommended_next[:5]:
                lesson = engine.lesson_by_id(lesson_id)
                if lesson:
                    row = QPushButton(f"Review: {lesson.title}")
                    row.setObjectName("Secondary")
                    row.clicked.connect(lambda checked=False, lid=lesson_id: self._show_lesson(lid))
                    l2.addWidget(row)
            self._lesson_layout.addWidget(pl2)

        if not summary.complete:
            resume = QPushButton("Resume course")
            resume.clicked.connect(lambda: self._show_lesson(engine.resume_lesson_id(self.progress)))
            row = QHBoxLayout()
            row.addWidget(resume)
            row.addStretch()
            self._lesson_layout.addLayout(row)

        self._lesson_layout.addStretch()


class _ProgressBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self._pct = 0
        self.setStyleSheet(
            f"background: {theme.BORDER}; border-radius: 4px;"
        )

    def set_percent(self, pct: int) -> None:
        self._pct = max(0, min(100, pct))
        self.setStyleSheet(
            f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            f"stop:0 {theme.ACCENT}, stop:{max(self._pct / 100, 0.001)} {theme.ACCENT}, "
            f"stop:{min(self._pct / 100 + 0.001, 1)} {theme.BORDER}, stop:1 {theme.BORDER}); "
            "border-radius: 4px;"
        )


class _PromptLab(QWidget):
    """Lessons 1.3 and 18.1: real, deterministic analyzer output on a
    prompt the learner types themselves — never an LLM grading the prompt,
    and nothing here is saved to prompt history."""

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.input = QTextEdit()
        self.input.setPlaceholderText("Type a real task prompt…")
        self.input.setMaximumHeight(90)
        layout.addWidget(self.input)

        row = QHBoxLayout()
        analyze_btn = QPushButton("Analyze")
        analyze_btn.clicked.connect(self._on_analyze)
        row.addWidget(analyze_btn)
        row.addStretch()
        layout.addLayout(row)

        self.result_panel = Panel()
        self.result_layout = QVBoxLayout(self.result_panel)
        self.result_layout.setContentsMargins(14, 12, 14, 12)
        self.result_layout.setSpacing(8)
        self._placeholder = _body_label("Results appear here after you analyze a prompt.",
                                         muted=True)
        self.result_layout.addWidget(self._placeholder)
        layout.addWidget(self.result_panel)

    def _on_analyze(self) -> None:
        text = self.input.toPlainText().strip()
        _clear_layout(self.result_layout)
        if not text:
            self.result_layout.addWidget(_body_label("Type a prompt above first.", muted=True))
            return

        analysis = self.controller.analyze(text)
        suggestion = self.controller.suggest_prompt(text, analysis)

        self.result_layout.addWidget(_field_block("ORIGINAL", text))
        if analysis.good:
            self.result_layout.addWidget(_field_block("STRENGTHS", "\n".join(
                f"• {g}" for g in analysis.good
            )))
        if analysis.warnings:
            self.result_layout.addWidget(_field_block("WHAT'S MISSING", "\n".join(
                f"• {w}" for w in analysis.warnings
            )))
        opportunity_lines = [
            f"• {o.message} ({o.kind}, {o.confidence} confidence)" for o in analysis.opportunities
        ]
        if opportunity_lines:
            self.result_layout.addWidget(_field_block("POSSIBLE OPPORTUNITIES",
                                                        "\n".join(opportunity_lines)))
        if suggestion.suggested_text:
            self.result_layout.addWidget(_field_block("SUGGESTED VERSION", suggestion.suggested_text))
        self.result_layout.addWidget(_field_block("WHY", suggestion.message))


class _ContextMeter(QWidget):
    """Lesson 2.2: mark simulated files relevant/unrelated for a fixed
    illustrative task and see how that choice affects a simple context
    meter. Entirely local/simulated — no real repository is scanned."""

    _TASK = "Fix the login timeout in the authentication flow."
    _FILES = (
        ("src/auth/login.ts", True),
        ("src/auth/session.test.ts", True),
        ("src/billing/invoice_pdf.py", False),
        ("src/marketing/landing_page.tsx", False),
        ("src/auth/token_refresh.ts", True),
        ("docs/onboarding_slides.md", False),
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(_field_block("TASK", self._TASK))

        self._boxes: list[tuple[QCheckBox, bool]] = []
        for path, actually_relevant in self._FILES:
            cb = QCheckBox(path)
            cb.setStyleSheet("font-size: 12px;")
            cb.toggled.connect(self._recompute)
            layout.addWidget(cb)
            self._boxes.append((cb, actually_relevant))

        self._meter = _ProgressBar()
        layout.addWidget(self._meter)
        self._verdict = _body_label("Mark which files you'd actually ask Claude to read.")
        layout.addWidget(self._verdict)
        self._recompute()

    def _recompute(self) -> None:
        marked = [b for b, _ in self._boxes if b.isChecked()]
        correct_relevant = sum(1 for r in self._FILES if r[1])
        pct = round(100 * len(marked) / len(self._boxes)) if self._boxes else 0
        self._meter.set_percent(pct)

        false_positives = sum(1 for b, relevant in self._boxes if b.isChecked() and not relevant)
        missed = sum(1 for b, relevant in self._boxes if relevant and not b.isChecked())
        if not marked:
            msg = "Nothing marked yet."
        elif false_positives == 0 and missed == 0:
            msg = ("Exactly the relevant files, no more — this task only needed "
                   f"{correct_relevant} of {len(self._boxes)}.")
        else:
            parts = []
            if false_positives:
                parts.append(f"{false_positives} unrelated file(s) marked relevant")
            if missed:
                parts.append(f"{missed} relevant file(s) left unmarked")
            msg = "; ".join(parts) + " — extra context here doesn't serve this narrow task."
        self._verdict.setText(msg)


class _DecisionWizard(QWidget):
    """Level 19: the capability decision tree, walked interactively.
    Not mechanically absolute — the result always says so."""

    _STEPS = {
        "one_task": (
            "Is this one specific, scoped task?",
            "repeatable", "independent",
        ),
        "repeatable": (
            "Will you repeat this exact workflow again?",
            ("result", "Skill candidate", "Package it as a Skill so you don't re-explain "
             "this workflow every time."),
            ("result", "Prompt", "Handle it directly — a one-off task doesn't need more "
             "than a good prompt."),
        ),
        "independent": (
            "Is it an independent investigation that doesn't need your main context "
            "continuously?",
            ("result", "Agent candidate", "Delegate it — an isolated investigation is a "
             "good fit for a subagent."),
            "stable_rule",
        ),
        "stable_rule": (
            "Is this a stable rule that should always apply to the project?",
            ("result", "CLAUDE.md", "A persistent, always-loaded instruction is the right "
             "home for a standing project rule."),
            "external",
        ),
        "external": (
            "Does it need a capability outside your files and shell — an external system?",
            ("result", "MCP", "Connect the external capability through MCP."),
            "noisy",
        ),
        "noisy": (
            "Is your context getting noisy right now?",
            "continue_or_new",
            ("result", "Direct prompt", "None of the above triggered — a direct prompt is "
             "probably enough."),
        ),
        "continue_or_new": (
            "Are you continuing the SAME task, or starting a NEW one?",
            ("result", "Compact", "Keep going with less noise — the task is the same."),
            ("result", "Fresh session", "Start clean — the old context doesn't serve a new task."),
        ),
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(10)
        self._question = QLabel()
        self._question.setWordWrap(True)
        self._question.setStyleSheet("font-weight: 600; font-size: 13px;")
        self._layout.addWidget(self._question)

        btn_row = QHBoxLayout()
        self._yes = QPushButton("Yes")
        self._no = QPushButton("No")
        self._yes.clicked.connect(lambda: self._answer(True))
        self._no.clicked.connect(lambda: self._answer(False))
        btn_row.addWidget(self._yes)
        btn_row.addWidget(self._no)
        btn_row.addStretch()
        self._layout.addLayout(btn_row)

        self._result_panel = Panel()
        self._result_layout = QVBoxLayout(self._result_panel)
        self._result_layout.setContentsMargins(16, 12, 16, 12)
        self._result_panel.hide()
        self._layout.addWidget(self._result_panel)

        restart = QPushButton("Start over")
        restart.setObjectName("Secondary")
        restart.clicked.connect(self._restart)
        self._layout.addWidget(restart)

        self._restart()

    def _restart(self) -> None:
        self._step = "one_task"
        self._result_panel.hide()
        self._question.show()
        self._yes.show()
        self._no.show()
        self._render_step()

    def _render_step(self) -> None:
        question, *_ = self._STEPS[self._step]
        self._question.setText(question)

    def _answer(self, yes: bool) -> None:
        _, on_yes, on_no = self._STEPS[self._step]
        outcome = on_yes if yes else on_no
        if isinstance(outcome, tuple):
            self._show_result(*outcome[1:])
        else:
            self._step = outcome
            self._render_step()

    def _show_result(self, label: str, explanation: str) -> None:
        self._question.hide()
        self._yes.hide()
        self._no.hide()
        _clear_layout(self._result_layout)
        head = QLabel(f"→ {label}")
        head.setStyleSheet(f"color: {theme.ACCENT}; font-size: 15px; font-weight: 700;")
        self._result_layout.addWidget(head)
        self._result_layout.addWidget(_body_label(explanation))
        self._result_layout.addWidget(_body_label(
            "A starting heuristic, not a verdict — override it when your own judgment "
            "says otherwise.", muted=True,
        ))
        self._result_panel.show()
