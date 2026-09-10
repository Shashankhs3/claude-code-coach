"""Workshop Mode (spec Feature 10): the on/off toggle plus a short reference
covering the concepts it teaches. The central lesson, stated once here
rather than re-derived per warning: you don't need a perfect prompt — you
need the right task, context, capabilities, workflow, and verification.
"""

from __future__ import annotations

from PySide6.QtWidgets import QCheckBox, QLabel, QScrollArea, QVBoxLayout, QWidget

from .widgets import Panel, SectionHeader, page_header

_LESSONS = [
    ("Task clarity", "A clear, well-scoped task lets Claude work efficiently. "
     "\"Fix my project\" gives Claude no starting point; \"fix the login timeout "
     "in src/auth/login.ts\" does."),
    ("Relevant context", "Claude can investigate broad areas when a task genuinely "
     "needs it, but for a narrow bug, naming the affected area reduces unnecessary "
     "exploration and keeps the context window focused on what matters."),
    ("Search-first workflow", "Locating the relevant code first (search/grep/glob) "
     "before reading broadly keeps context smaller and more targeted than reading "
     "many files hoping to find the right one."),
    ("CLAUDE.md", "Persistent project rules (\"every API change needs tests\") belong "
     "in CLAUDE.md once, not repeated in every prompt."),
    ("Skills", "A Skill packages a repeatable, multi-step workflow (like a security "
     "review checklist) so it's performed consistently instead of re-explained "
     "each time."),
    ("Agents", "An Agent is a delegated specialist for independent, substantial "
     "investigation — not something every hard task needs, but useful when work "
     "spans several unrelated areas."),
    ("MCP / external capabilities", "MCP servers give Claude capabilities beyond "
     "file edits (e.g. querying a database or an external service) — worth knowing "
     "what's actually connected before assuming Claude can't do something."),
    ("Long sessions", "A long session focused on one continuous task is healthy. "
     "One that's accumulated several unrelated tasks is where things get noisy."),
    ("Fresh sessions", "Starting fresh for unrelated work avoids carrying over "
     "context that has nothing to do with the next task."),
    ("Parallel work", "Independent workstreams (e.g. backend, database, and "
     "frontend investigations that don't depend on each other) can be split into "
     "parallel sessions or delegated separately, rather than done one after "
     "another in the same context."),
    ("Context management", "Context health is about relevance, not just length — "
     "a long, coherent session isn't a problem; an accumulation of unrelated work is."),
    ("Verification", "After a change, some evidence that it was checked (a test run, "
     "a diff review) is worth having — not because Claude is untrustworthy, but "
     "because verification catches the cases where it wasn't right."),
]


class Workshop(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Workshop Mode",
            "You don't need a perfect prompt. You need the right task, context, "
            "capabilities, workflow, and verification.",
        ))

        self.toggle = QCheckBox(
            "Enable Workshop Mode (expanded 'why this matters' / 'try this' "
            "explanations in the Prompt Inspector)"
        )
        self.toggle.toggled.connect(self._on_toggle)
        outer.addWidget(self.toggle)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setSpacing(14)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        content_layout.addWidget(SectionHeader("CONCEPTS"))
        for title, text in _LESSONS:
            panel = Panel()
            panel_layout = QVBoxLayout(panel)
            panel_layout.setContentsMargins(16, 12, 16, 12)
            heading = QLabel(title)
            heading.setStyleSheet("font-weight: 700; font-size: 13px;")
            body = QLabel(text)
            body.setWordWrap(True)
            body.setStyleSheet("font-size: 12px;")
            panel_layout.addWidget(heading)
            panel_layout.addWidget(body)
            content_layout.addWidget(panel)

        content_layout.addStretch()

        self.refresh()

    def refresh(self) -> None:
        self.toggle.blockSignals(True)
        self.toggle.setChecked(self.controller.workshop_mode)
        self.toggle.blockSignals(False)

    def _on_toggle(self, checked: bool) -> None:
        self.controller.set_workshop_mode(checked)
