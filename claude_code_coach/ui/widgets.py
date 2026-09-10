"""Small reusable UI components shared across pages.

IMPORTANT (spec section 8): every QWidget subclass here calls
``super().__init__(parent)`` as the very first statement, before creating
any child Qt object (QLabel, QTimer, layouts, etc.).
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame, QHBoxLayout, QLabel, QProgressBar, QPushButton, QVBoxLayout, QWidget,
)

from . import theme


class StatCard(QFrame):
    def __init__(self, title: str, value: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("Card")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        self._title = QLabel(title)
        self._title.setObjectName("CardTitle")
        self._value = QLabel(value)
        self._value.setObjectName("CardValue")
        self._subtitle = QLabel(subtitle)
        self._subtitle.setObjectName("CardSubtitle")
        self._subtitle.setWordWrap(True)

        layout.addWidget(self._title)
        layout.addWidget(self._value)
        layout.addWidget(self._subtitle)

    def set_value(self, value: str, subtitle: str | None = None) -> None:
        self._value.setText(value)
        if subtitle is not None:
            self._subtitle.setText(subtitle)


class Badge(QLabel):
    def __init__(self, text: str, color: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("Badge")
        self.setStyleSheet(theme.badge_style(color))


def confidence_color(confidence: str) -> str:
    return {"high": theme.GOOD, "medium": theme.WARN, "low": theme.TEXT_MUTED}.get(
        confidence, theme.INFO
    )


class ScorePill(QWidget):
    """A compact score + rating readout, used by Live Coach and history detail."""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        self.value_label = QLabel("--")
        self.value_label.setObjectName("ScoreValue")

        right = QVBoxLayout()
        right.setSpacing(2)
        self.rating_label = QLabel("")
        self.rating_label.setObjectName("RatingLabel")
        self.of_label = QLabel("/ 100")
        self.of_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        right.addWidget(self.rating_label)
        right.addWidget(self.of_label)

        layout.addWidget(self.value_label)
        layout.addLayout(right)
        layout.addStretch()

    def set_score(self, score: int | None, rating: str) -> None:
        color = theme.rating_color(rating) if rating else theme.TEXT_MUTED
        self.value_label.setText(str(score) if score is not None else "--")
        self.value_label.setStyleSheet(f"color: {color};")
        self.rating_label.setText(rating or "")
        self.rating_label.setStyleSheet(f"color: {color};")


class PercentBar(QWidget):
    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(3)

        top = QHBoxLayout()
        self.label = QLabel(label)
        self.label.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12px;")
        self.value = QLabel("--")
        self.value.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11px;")
        top.addWidget(self.label)
        top.addStretch()
        top.addWidget(self.value)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        self.bar.setFixedHeight(8)

        layout.addLayout(top)
        layout.addWidget(self.bar)

    def set_percent(self, pct: int | None, sample_size: int = 0) -> None:
        if pct is None:
            self.bar.setValue(0)
            self.value.setText("no data")
            return
        self.bar.setValue(int(pct))
        suffix = f" ({sample_size})" if sample_size else ""
        self.value.setText(f"{pct}%{suffix}")


class SectionHeader(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("SectionHeader")


class EmptyState(QLabel):
    def __init__(self, text: str, parent=None):
        super().__init__(text, parent)
        self.setObjectName("EmptyState")
        self.setWordWrap(True)
        self.setAlignment(Qt.AlignCenter)


class Panel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Panel")


class CandidateCard(Panel):
    """Card used by Skills/Agents/CLAUDE.md pages to show one detected candidate."""

    def __init__(self, candidate: dict, icon: str, parent=None,
                 on_create=None, create_label: str = ""):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(6)

        top = QHBoxLayout()
        title = QLabel(f"{icon}  {candidate['name']}")
        title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {theme.TEXT_PRIMARY};")
        top.addWidget(title)
        top.addStretch()
        top.addWidget(Badge(
            candidate["confidence"].upper(), confidence_color(candidate["confidence"])
        ))
        layout.addLayout(top)

        occ = QLabel(f"Used {candidate['occurrences']} time(s)")
        occ.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
        layout.addWidget(occ)

        reason = QLabel(f"Reason: {candidate['reason']}")
        reason.setWordWrap(True)
        reason.setStyleSheet(f"color: {theme.TEXT_PRIMARY}; font-size: 12.5px;")
        layout.addWidget(reason)

        for example in candidate.get("examples", []):
            ex = QLabel(f"“{example}”")
            ex.setWordWrap(True)
            ex.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px; padding-left: 8px;")
            layout.addWidget(ex)

        if on_create:
            button_row = QHBoxLayout()
            button_row.addStretch()
            create_btn = QPushButton(create_label or "Create")
            create_btn.setObjectName("Secondary")
            create_btn.clicked.connect(lambda: on_create(candidate))
            button_row.addWidget(create_btn)
            layout.addLayout(button_row)


def page_header(title: str, subtitle: str = "") -> QVBoxLayout:
    layout = QVBoxLayout()
    layout.setSpacing(2)
    t = QLabel(title)
    t.setObjectName("PageTitle")
    layout.addWidget(t)
    if subtitle:
        s = QLabel(subtitle)
        s.setObjectName("PageSubtitle")
        s.setWordWrap(True)
        layout.addWidget(s)
    return layout
