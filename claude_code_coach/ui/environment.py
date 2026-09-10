"""Environment page: real, read-only Claude Code environment discovery.

Everything shown here is either DETECTED (found on disk right now) or
explicitly reported as unscanned/unavailable — nothing is invented. See
providers/claude_code_provider.py for exactly what gets scanned.
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from . import theme
from .widgets import Badge, EmptyState, Panel, SectionHeader, StatCard, page_header


class DetectedItemCard(Panel):
    def __init__(self, title: str, subtitle: str, source: str, modified: str,
                 extra: str = "", parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(4)

        top = QHBoxLayout()
        name = QLabel(title)
        name.setStyleSheet(f"font-size: 13.5px; font-weight: 700; color: {theme.TEXT_PRIMARY};")
        top.addWidget(name)
        top.addStretch()
        top.addWidget(Badge("DETECTED", theme.GOOD))
        if source:
            top.addWidget(Badge(source.upper(), theme.INFO))
        layout.addLayout(top)

        if subtitle:
            sub = QLabel(subtitle)
            sub.setWordWrap(True)
            sub.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
            layout.addWidget(sub)

        meta_bits = []
        if modified:
            meta_bits.append(f"Modified {modified}")
        if extra:
            meta_bits.append(extra)
        if meta_bits:
            meta = QLabel("  •  ".join(meta_bits))
            meta.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10.5px;")
            layout.addWidget(meta)


class Environment(QWidget):
    def __init__(self, controller):
        super().__init__()
        self.controller = controller
        self.controller.register(self)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 22, 28, 22)
        outer.addLayout(page_header(
            "Environment",
            "Real, read-only discovery of your local Claude Code setup — CLAUDE.md, "
            "Skills, Agents, and MCP config. Nothing here is fabricated.",
        ))

        status_row = QHBoxLayout()
        self.scan_button = QPushButton("Scan Again")
        self.scan_button.clicked.connect(self._on_scan_clicked)
        self.choose_root_button = QPushButton("Choose Project Folder")
        self.choose_root_button.setObjectName("Secondary")
        self.choose_root_button.clicked.connect(self._on_choose_root)
        self.status_label = QLabel("")
        self.status_label.setStyleSheet(f"color: {theme.TEXT_MUTED}; font-size: 11.5px;")
        status_row.addWidget(self.scan_button)
        status_row.addWidget(self.choose_root_button)
        status_row.addWidget(self.status_label)
        status_row.addStretch()
        outer.addLayout(status_row)

        self.privacy_label = QLabel("🔒  Local filesystem only — read-only, no network calls.")
        self.privacy_label.setStyleSheet(f"color: {theme.TEXT_FAINT}; font-size: 10.5px; padding-bottom: 4px;")
        outer.addWidget(self.privacy_label)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        self.content_layout = QVBoxLayout(content)
        self.content_layout.setSpacing(16)
        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.summary_cards = QHBoxLayout()
        self.summary_cards.setSpacing(14)
        self.content_layout.addLayout(self.summary_cards)

        self.error_panel_holder = QVBoxLayout()
        self.content_layout.addLayout(self.error_panel_holder)

        self.claude_md_header = SectionHeader("CLAUDE.MD")
        self.content_layout.addWidget(self.claude_md_header)
        self.claude_md_layout = QVBoxLayout()
        self.claude_md_layout.setSpacing(8)
        self.content_layout.addLayout(self.claude_md_layout)

        self.skills_header = SectionHeader("SKILLS")
        self.content_layout.addWidget(self.skills_header)
        self.skills_layout = QVBoxLayout()
        self.skills_layout.setSpacing(8)
        self.content_layout.addLayout(self.skills_layout)

        self.agents_header = SectionHeader("AGENTS")
        self.content_layout.addWidget(self.agents_header)
        self.agents_layout = QVBoxLayout()
        self.agents_layout.setSpacing(8)
        self.content_layout.addLayout(self.agents_layout)

        self.mcp_header = SectionHeader("MCP / PLUGINS")
        self.content_layout.addWidget(self.mcp_header)
        self.mcp_layout = QVBoxLayout()
        self.mcp_layout.setSpacing(8)
        self.content_layout.addLayout(self.mcp_layout)

        self.content_layout.addStretch()

        self.refresh()

    def _clear(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def refresh(self) -> None:
        snapshot = self.controller.environment_snapshot
        root = self.controller.environment.project_root

        if self.controller.is_scanning():
            self.status_label.setText("Scanning Claude Code environment…")
        elif snapshot is None:
            root_note = f" Project root: {root}" if root else " No project folder selected."
            self.status_label.setText("Never scanned." + root_note)
        else:
            self.status_label.setText(f"Last scanned: {snapshot.scanned_at}")

        self._clear(self.summary_cards)
        counts = snapshot.counts if snapshot else {"claude_md": 0, "skills": 0, "agents": 0, "mcp_servers": 0}
        self.summary_cards.addWidget(StatCard("CLAUDE.MD", str(counts["claude_md"]), "detected"))
        self.summary_cards.addWidget(StatCard("SKILLS", str(counts["skills"]), "detected"))
        self.summary_cards.addWidget(StatCard("AGENTS", str(counts["agents"]), "detected"))
        self.summary_cards.addWidget(StatCard("MCP / PLUGINS", str(counts["mcp_servers"]), "detected"))

        self._clear(self.error_panel_holder)
        if snapshot and snapshot.errors:
            panel = Panel()
            player = QVBoxLayout(panel)
            player.setContentsMargins(14, 10, 14, 10)
            player.addWidget(SectionHeader("SCAN WARNINGS"))
            for err in snapshot.errors:
                lbl = QLabel(f"⚠ {err}")
                lbl.setWordWrap(True)
                lbl.setStyleSheet(f"color: {theme.WARN}; font-size: 11.5px;")
                player.addWidget(lbl)
            self.error_panel_holder.addWidget(panel)

        self._clear(self.claude_md_layout)
        if not snapshot or not snapshot.claude_md:
            self.claude_md_layout.addWidget(EmptyState("No CLAUDE.md detected."))
        else:
            for doc in snapshot.claude_md:
                scope = doc.scope.value if hasattr(doc.scope, "value") else str(doc.scope)
                self.claude_md_layout.addWidget(DetectedItemCard(
                    doc.path, doc.preview[:200], scope, doc.modified,
                    extra=f"{doc.size_bytes} bytes",
                ))

        self._clear(self.skills_layout)
        if not snapshot or not snapshot.skills:
            self.skills_layout.addWidget(EmptyState("No Skills detected."))
        else:
            for skill in snapshot.skills:
                source = skill.source.value if hasattr(skill.source, "value") else str(skill.source)
                self.skills_layout.addWidget(DetectedItemCard(
                    skill.name, skill.description, source, skill.modified,
                ))

        self._clear(self.agents_layout)
        if not snapshot or not snapshot.agents:
            self.agents_layout.addWidget(EmptyState("No Agents detected."))
        else:
            for agent in snapshot.agents:
                source = agent.source.value if hasattr(agent.source, "value") else str(agent.source)
                self.agents_layout.addWidget(DetectedItemCard(
                    agent.name, agent.description, source, agent.modified,
                ))

        self._clear(self.mcp_layout)
        if not snapshot or not snapshot.mcp_servers:
            self.mcp_layout.addWidget(EmptyState("No MCP servers/plugins detected."))
        else:
            for mcp in snapshot.mcp_servers:
                source = mcp.source.value if hasattr(mcp.source, "value") else str(mcp.source)
                enabled_note = (
                    "enabled" if mcp.enabled is True else
                    "disabled" if mcp.enabled is False else "status unknown"
                )
                self.mcp_layout.addWidget(DetectedItemCard(
                    mcp.name, f"Type: {mcp.server_type}", source, "",
                    extra=enabled_note,
                ))

    def _on_scan_clicked(self) -> None:
        self.scan_button.setEnabled(False)
        self.status_label.setText("Scanning Claude Code environment…")
        started = self.controller.scan_environment_async(
            on_done=self._on_scan_done, on_error=self._on_scan_error
        )
        if not started:
            self.scan_button.setEnabled(True)

    def _on_scan_done(self, snapshot) -> None:
        self.scan_button.setEnabled(True)
        counts = snapshot.counts
        self.status_label.setText(
            f"Scan complete — {counts['skills']} Skills, {counts['agents']} Agents, "
            f"{counts['mcp_servers']} MCP entries, {counts['claude_md']} CLAUDE.md detected."
        )
        self.controller.refresh_all()

    def _on_scan_error(self, message: str) -> None:
        self.scan_button.setEnabled(True)
        self.status_label.setText(f"Scan failed: {message}")

    def _on_choose_root(self) -> None:
        current = self.controller.environment.project_root
        start_dir = str(current) if current else ""
        folder = QFileDialog.getExistingDirectory(self, "Choose Project Folder", start_dir)
        if not folder:
            return
        self.controller.set_project_root(folder)
        self.refresh()
