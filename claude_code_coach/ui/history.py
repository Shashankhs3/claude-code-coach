from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QSizePolicy, QSplitter,
    QTextEdit, QVBoxLayout, QWidget,
)

from . import theme
from .widgets import EmptyState, page_header


class History(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header("Prompt History", "Every prompt you've analyzed, stored locally."))

        splitter = QSplitter(Qt.Horizontal)
        # See inspector.py: QSplitter defaults to Preferred vertically, which
        # would otherwise let the header labels balloon into empty space.
        splitter.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._show_item)

        self.detail = QTextEdit()
        self.detail.setReadOnly(True)

        splitter.addWidget(self.list)
        splitter.addWidget(self.detail)
        splitter.setSizes([380, 700])

        outer.addWidget(splitter)

        self.refresh()

    def refresh(self) -> None:
        self.list.clear()
        rows = self.controller.history()

        if not rows:
            self.detail.setPlainText("")
            placeholder = QListWidgetItem("No prompts analyzed yet.")
            placeholder.setFlags(Qt.NoItemFlags)
            self.list.addItem(placeholder)
            return

        for row in rows:
            preview = row["prompt"].replace("\n", " ").strip()[:70]
            item = QListWidgetItem(f'{row["score"]:>3}  {row["rating"]:<18} {preview}')
            item.setData(Qt.UserRole, row["id"])
            self.list.addItem(item)

        self.list.setCurrentRow(0)

    def _show_item(self, current, previous) -> None:
        if not current:
            self.detail.setPlainText("")
            return
        row_id = current.data(Qt.UserRole)
        if row_id is None:
            self.detail.setPlainText("")
            return

        row = self.controller.get(row_id)
        if not row:
            self.detail.setPlainText("")
            return

        lines = [
            f"Score: {row['score']}/100   Rating: {row['rating']}   Task type: {row['task_type']}",
            f"Time: {row['timestamp']}",
            "",
            "PROMPT",
            "──────",
            row["prompt"],
            "",
        ]

        if row["good"]:
            lines.append("GOOD HABITS")
            lines.extend(f"✓ {x}" for x in row["good"])
            lines.append("")
        if row["warnings"]:
            lines.append("IMPROVEMENTS")
            lines.extend(f"⚠ {x}" for x in row["warnings"])
            lines.append("")
        if row["opportunities"]:
            lines.append("OPPORTUNITIES")
            for o in row["opportunities"]:
                lines.append(f"→ [{o.get('kind', '?')}] {o.get('message', '')}")

        self.detail.setPlainText("\n".join(lines))
