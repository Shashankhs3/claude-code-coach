"""Integrations (MCP) page: shows DETECTED MCP servers on their own, since
spec Feature 18 explicitly wants "external capability" kept distinct from
Skills/Agents/CLAUDE.md rather than folded into one generic list.
"""

from __future__ import annotations

from PySide6.QtWidgets import QScrollArea, QVBoxLayout, QWidget

from .environment import DetectedItemCard
from .widgets import EmptyState, page_header


class Integrations(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Integrations",
            "MCP servers actually detected in your Claude Code configuration — "
            "external capabilities beyond file edits.",
        ))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(10)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.refresh()

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def refresh(self) -> None:
        self._clear(self.content_layout)
        snapshot = self.controller.environment_snapshot
        servers = snapshot.mcp_servers if snapshot else []

        if not servers:
            self.content_layout.addWidget(EmptyState(
                "No MCP servers detected. Scan on the Environment page after "
                "selecting a project folder."
            ))
        else:
            for mcp in servers:
                source = mcp.source.value if hasattr(mcp.source, "value") else str(mcp.source)
                enabled_note = (
                    "enabled" if mcp.enabled is True else
                    "disabled" if mcp.enabled is False else "status unknown"
                )
                self.content_layout.addWidget(DetectedItemCard(
                    mcp.name, f"Type: {mcp.server_type}", source, "", extra=enabled_note,
                ))

        self.content_layout.addStretch()
