"""Tests for the real Claude Code environment scanner.

Spec section 19: never depends on the developer's personal machine —
every test builds its own temporary directory tree.
"""

import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.providers.claude_code_provider import ClaudeCodeEnvironmentProvider
from claude_code_coach.providers.models import Source
from claude_code_coach.providers.redaction import redact_secrets


class TempEnvTestCase(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)
        self.project = self.tmp / "project"
        self.project.mkdir()
        self.fake_home = self.tmp / "home"
        self.fake_home.mkdir()

    def tearDown(self):
        self._tmpdir.cleanup()

    _UNSET = object()

    def _provider(self, project_root=_UNSET):
        root = self.project if project_root is self._UNSET else project_root
        return ClaudeCodeEnvironmentProvider(project_root=root, user_home=self.fake_home)


class TestNoEnvironment(TempEnvTestCase):
    def test_empty_project_and_home_detect_nothing_and_do_not_crash(self):
        snapshot = self._provider().scan()
        self.assertEqual(snapshot.counts, {
            "claude_md": 0, "skills": 0, "agents": 0, "mcp_servers": 0,
        })
        self.assertEqual(snapshot.errors, [])

    def test_no_project_root_configured_still_scans_user_level(self):
        snapshot = self._provider(project_root=None).scan()
        self.assertIsNone(snapshot.project_root)
        self.assertEqual(snapshot.counts["skills"], 0)

    def test_is_available_true_for_real_provider(self):
        self.assertTrue(self._provider().is_available())


class TestFixtureEnvironment(TempEnvTestCase):
    """Mirrors the spec section 21 acceptance scenario fixture tree."""

    def setUp(self):
        super().setUp()
        (self.project / "CLAUDE.md").write_text(
            "Project instructions:\n- Every API change must include tests.\n",
            encoding="utf-8",
        )
        skill_dir = self.project / ".claude" / "skills" / "security-review"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(textwrap.dedent("""\
            ---
            name: security-review
            description: "Review API endpoints for auth, validation and logging."
            ---
            Body.
            """), encoding="utf-8")

        agents_dir = self.project / ".claude" / "agents"
        agents_dir.mkdir(parents=True)
        (agents_dir / "security-auditor.md").write_text(textwrap.dedent("""\
            ---
            name: security-auditor
            description: Investigates security-sensitive changes.
            ---
            Body.
            """), encoding="utf-8")

        (self.project / ".mcp.json").write_text(
            '{"mcpServers": {"local-fs": {"type": "stdio", "command": "npx"}}}',
            encoding="utf-8",
        )

    def test_claude_md_detected(self):
        snapshot = self._provider().scan()
        self.assertEqual(len(snapshot.claude_md), 1)
        self.assertEqual(snapshot.claude_md[0].scope, Source.PROJECT)
        self.assertIn("API change", snapshot.claude_md[0].preview)

    def test_skill_detected(self):
        snapshot = self._provider().scan()
        self.assertEqual(len(snapshot.skills), 1)
        skill = snapshot.skills[0]
        self.assertEqual(skill.name, "security-review")
        self.assertEqual(skill.source, Source.PROJECT)
        self.assertIn("auth", skill.description.lower())

    def test_agent_detected(self):
        snapshot = self._provider().scan()
        self.assertEqual(len(snapshot.agents), 1)
        agent = snapshot.agents[0]
        self.assertEqual(agent.name, "security-auditor")
        self.assertEqual(agent.source, Source.PROJECT)

    def test_mcp_detected_from_project_mcp_json(self):
        snapshot = self._provider().scan()
        self.assertEqual(len(snapshot.mcp_servers), 1)
        server = snapshot.mcp_servers[0]
        self.assertEqual(server.name, "local-fs")
        self.assertEqual(server.server_type, "stdio")

    def test_user_level_skill_also_detected(self):
        user_skill_dir = self.fake_home / ".claude" / "skills" / "my-user-skill"
        user_skill_dir.mkdir(parents=True)
        (user_skill_dir / "SKILL.md").write_text(
            "---\nname: my-user-skill\ndescription: a user skill\n---\nBody\n",
            encoding="utf-8",
        )
        snapshot = self._provider().scan()
        names_sources = {(s.name, s.source) for s in snapshot.skills}
        self.assertIn(("my-user-skill", Source.USER), names_sources)
        self.assertIn(("security-review", Source.PROJECT), names_sources)

    def test_project_mcp_registry_entry_matched_by_normalized_path(self):
        import json
        registry = {
            "projects": {
                str(self.project).replace("\\", "/").upper(): {
                    "mcpServers": {"ruflo": {"type": "stdio", "command": "npx"}},
                    "enabledMcpjsonServers": ["ruflo"],
                }
            }
        }
        (self.fake_home / ".claude.json").write_text(json.dumps(registry), encoding="utf-8")
        snapshot = self._provider().scan()
        names = {s.name for s in snapshot.mcp_servers}
        self.assertIn("ruflo", names)
        ruflo = next(s for s in snapshot.mcp_servers if s.name == "ruflo")
        self.assertTrue(ruflo.enabled)


class TestSecretRedaction(TempEnvTestCase):
    def test_redact_secrets_function(self):
        text = "API_KEY=super-secret-value\nOther line."
        redacted = redact_secrets(text)
        self.assertNotIn("super-secret-value", redacted)
        self.assertIn("[REDACTED]", redacted)

    def test_claude_md_secret_never_reaches_preview(self):
        (self.project / "CLAUDE.md").write_text(
            "Rules.\nAPI_KEY=super-secret-value\ntoken: abcdef1234567890\n",
            encoding="utf-8",
        )
        snapshot = self._provider().scan()
        preview = snapshot.claude_md[0].preview
        self.assertNotIn("super-secret-value", preview)
        self.assertNotIn("abcdef1234567890", preview)

    def test_skill_description_secret_never_reaches_model(self):
        skill_dir = self.project / ".claude" / "skills" / "leaky-skill"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(
            '---\nname: leaky-skill\ndescription: "uses password=hunter2hunter2 internally"\n---\nBody\n',
            encoding="utf-8",
        )
        snapshot = self._provider().scan()
        skill = next(s for s in snapshot.skills if s.name == "leaky-skill")
        self.assertNotIn("hunter2hunter2", skill.description)


class TestBrokenFiles(TempEnvTestCase):
    def test_malformed_skill_frontmatter_does_not_crash(self):
        skill_dir = self.project / ".claude" / "skills" / "broken"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("not frontmatter at all, just text", encoding="utf-8")
        snapshot = self._provider().scan()
        self.assertEqual(snapshot.errors, [])
        self.assertEqual(len(snapshot.skills), 1)
        self.assertEqual(snapshot.skills[0].name, "broken")  # falls back to dir name

    def test_malformed_mcp_json_does_not_crash(self):
        (self.project / ".mcp.json").write_text("{not valid json", encoding="utf-8")
        snapshot = self._provider().scan()
        self.assertEqual(snapshot.mcp_servers, [])
        self.assertEqual(snapshot.errors, [])

    def test_empty_skill_file_does_not_crash(self):
        skill_dir = self.project / ".claude" / "skills" / "empty"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text("", encoding="utf-8")
        snapshot = self._provider().scan()
        self.assertEqual(len(snapshot.skills), 1)

    def test_non_utf8_bytes_do_not_crash(self):
        skill_dir = self.project / ".claude" / "skills" / "binary-ish"
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_bytes(b"\xff\xfe---\nname: x\n---\n\xff body")
        snapshot = self._provider().scan()
        self.assertEqual(len(snapshot.skills), 1)
        self.assertEqual(snapshot.errors, [])


class TestPermissionErrors(TempEnvTestCase):
    def test_unreadable_file_is_reported_not_raised(self):
        skill_dir = self.project / ".claude" / "skills" / "denied"
        skill_dir.mkdir(parents=True)
        skill_md = skill_dir / "SKILL.md"
        skill_md.write_text("---\nname: denied\n---\nBody\n", encoding="utf-8")

        provider = self._provider()
        original_read_text = Path.read_text

        def _raise_for_target(self_path, *args, **kwargs):
            if self_path == skill_md:
                raise PermissionError("Access is denied")
            return original_read_text(self_path, *args, **kwargs)

        Path.read_text = _raise_for_target
        try:
            snapshot = provider.scan()
        finally:
            Path.read_text = original_read_text

        # Must not raise; the unreadable skill still appears (falls back to
        # the directory name) with no crash anywhere in the scan.
        self.assertEqual(len(snapshot.skills), 1)
        self.assertEqual(snapshot.skills[0].name, "denied")


if __name__ == "__main__":
    unittest.main()
