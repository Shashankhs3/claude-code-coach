from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QMainWindow, QPushButton, QStackedWidget,
    QVBoxLayout, QWidget,
)

from claude_code_coach.database import APP_DIR

from . import theme
from .agent_creator import AgentCreator
from .agents import Agents
from .approach_advisor import ApproachAdvisor
from .context import Context
from .controller import CoachController
from .dashboard import Dashboard
from .environment import Environment
from .habits import Habits
from .history import History
from .inspector import Inspector
from .mcp_page import Integrations
from .runtime import Runtime
from .settings import Settings
from .skill_creator import SkillCreator
from .skills import Skills
from .usage import Usage
from .workshop import Workshop

# Grouped navigation (spec Feature 11): (group_header_or_None, label, page_class).
# Existing V4 pages are kept, not removed — Runtime is relabeled "Sessions"
# here (same page/class, enriched with V5 session-coherence/verification
# signals) since that's what it now is; nothing about it was deleted.
NAV = (
    (None, "Dashboard", Dashboard),
    ("WORK", "Prompt Inspector", Inspector),
    ("WORK", "Approach Advisor", ApproachAdvisor),
    ("WORK", "Sessions", Runtime),
    ("WORK", "Prompt History", History),
    ("WORK", "Context", Context),
    ("CAPABILITIES", "Skills", Skills),
    ("CAPABILITIES", "Skill Creator", SkillCreator),
    ("CAPABILITIES", "Agents", Agents),
    ("CAPABILITIES", "Agent Creator", AgentCreator),
    ("CAPABILITIES", "Integrations", Integrations),
    ("CAPABILITIES", "Environment", Environment),
    ("LEARNING", "Habits", Habits),
    ("LEARNING", "Usage", Usage),
    ("LEARNING", "Workshop Mode", Workshop),
    (None, "Settings", Settings),
)

PAGES = tuple((label, cls) for _group, label, cls in NAV)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Claude Code Coach")
        self.resize(1320, 840)

        self.controller = CoachController()
        self.controller.set_navigation_callback(self.navigate_to_label)

        central = QWidget()
        self.setCentralWidget(central)

        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        sidebar = self._build_sidebar()
        root.addWidget(sidebar)

        self.stack = QStackedWidget()
        self.pages = []
        for _label, page_cls in PAGES:
            page = page_cls(self.controller)
            self.stack.addWidget(page)
            self.pages.append(page)

        root.addWidget(self.stack)

        for i, button in enumerate(self.nav_buttons):
            button.clicked.connect(lambda checked=False, idx=i: self._navigate(idx))
        self._navigate(0)

    def _build_sidebar(self) -> QFrame:
        sidebar = QFrame()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(220)

        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        logo = QLabel("CLAUDE CODE\nCOACH")
        logo.setObjectName("Logo")
        layout.addWidget(logo)

        sub = QLabel("WORKFLOW COACH")
        sub.setObjectName("LogoSub")
        layout.addWidget(sub)

        self.nav_buttons: list[QPushButton] = []
        current_group = None
        for group, label, _cls in NAV:
            if group != current_group and group is not None:
                header = QLabel(group)
                header.setStyleSheet(
                    f"color: {theme.TEXT_ON_DARK_MUTED}; font-size: 10px; font-weight: 700; "
                    f"letter-spacing: 1px; padding: 14px 16px 4px 16px; background: transparent;"
                )
                layout.addWidget(header)
            current_group = group

            button = QPushButton(label)
            button.setObjectName("NavButton")
            button.setCheckable(True)
            button.setAutoExclusive(True)
            layout.addWidget(button)
            self.nav_buttons.append(button)

        layout.addStretch()

        privacy = QLabel(f"● LOCAL ONLY\n\nStored in:\n{APP_DIR}")
        privacy.setObjectName("Privacy")
        privacy.setWordWrap(True)
        layout.addWidget(privacy)

        return sidebar

    def _navigate(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        self.nav_buttons[index].setChecked(True)
        page = self.pages[index]
        refresh = getattr(page, "refresh", None)
        if callable(refresh):
            refresh()

    def navigate_to_label(self, label: str) -> None:
        for i, (page_label, _cls) in enumerate(PAGES):
            if page_label == label:
                self._navigate(i)
                return
