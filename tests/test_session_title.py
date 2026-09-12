"""Tests for the deterministic Session Title generator (runtime/session_title.py).

No AI/LLM is involved anywhere here — every case exercises a fixed regex/
string rule, so each assertion should be explainable by the rule that
produced it (see the module docstring).
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from claude_code_coach.runtime import session_title
from claude_code_coach.runtime.models import RuntimeEvent, RuntimeEventType as T


def _prompt_event(content=None, metadata=None, session_id="s1"):
    return RuntimeEvent(
        id=None, received_at="2026-01-01T00:00:00", session_id=session_id,
        event_type=T.USER_PROMPT_SUBMIT, metadata=metadata or {}, content=content,
    )


def _other_event(event_type=T.PRE_TOOL_USE, session_id="s1"):
    return RuntimeEvent(
        id=None, received_at="2026-01-01T00:00:00", session_id=session_id,
        event_type=event_type, metadata={}, content=None,
    )


class TestTitleFromPromptText(unittest.TestCase):
    """Tier 1: real prompt text, only ever present when the user opted into
    `runtime_collect_content` (event_parser.py)."""

    def test_normal_prompt(self):
        events = [_prompt_event(content="Fix the Dashboard warning shown when the Coach service reconnects.")]
        title = session_title.title_for_session(events)
        self.assertTrue(title.startswith("Fix"))
        self.assertNotIn("\n", title)
        self.assertLessEqual(len(title.split()), session_title.MAX_TITLE_WORDS)

    def test_long_prompt_is_capped(self):
        long_prompt = "Please " + " ".join(f"word{i}" for i in range(50)) + "."
        title = session_title.title_for_session([_prompt_event(content=long_prompt)])
        self.assertLessEqual(len(title.split()), session_title.MAX_TITLE_WORDS)
        self.assertLessEqual(len(title), session_title.MAX_TITLE_CHARS)

    def test_empty_prompt_falls_back(self):
        events = [_prompt_event(content="   ", metadata={"task_type": "implementation"})]
        title = session_title.title_for_session(events)
        # Empty content tier fails silently -> falls through to task_type tier.
        self.assertEqual(title, "Implementation session")

    def test_multiline_prompt_uses_first_meaningful_line(self):
        prompt = "\n\n  Fix the login redirect bug.\n\nMore details below:\n- step one\n- step two"
        title = session_title.title_for_session([_prompt_event(content=prompt)])
        self.assertEqual(title, "Fix the login redirect bug")

    def test_prompt_containing_code_block_is_stripped(self):
        prompt = "Fix this function:\n```python\ndef broken():\n    return 1/0\n```"
        title = session_title.title_for_session([_prompt_event(content=prompt)])
        self.assertNotIn("```", title)
        self.assertNotIn("def broken", title)
        self.assertEqual(title, "Fix this function")

    def test_prompt_containing_paths_is_preserved_but_bounded(self):
        prompt = "Fix the bug in src/auth/login_handler.py that breaks token refresh."
        title = session_title.title_for_session([_prompt_event(content=prompt)])
        self.assertTrue(title.startswith("Fix"))
        self.assertLessEqual(len(title.split()), session_title.MAX_TITLE_WORDS)

    def test_prompt_containing_sensitive_looking_text_is_redacted(self):
        prompt = "Rotate the API_KEY=sk-abcdefghijklmnopqrstuvwx in our deploy script."
        title = session_title.title_for_session([_prompt_event(content=prompt)])
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwx", title)

    def test_task_style_prompt_strips_boilerplate(self):
        prompt = "Could you please help me add validation to the login form?"
        title = session_title.title_for_session([_prompt_event(content=prompt)])
        self.assertFalse(title.lower().startswith("could you"))
        self.assertFalse(title.lower().startswith("help me"))

    def test_question_style_prompt_is_still_a_short_clause(self):
        prompt = "Why is the login test failing after the recent auth change?"
        title = session_title.title_for_session([_prompt_event(content=prompt)])
        self.assertLessEqual(len(title.split()), session_title.MAX_TITLE_WORDS)
        self.assertFalse(title.endswith("?"))

    def test_code_only_content_falls_back_to_task_type(self):
        prompt = "```\nx = {1: 2, 3: 4}\n```"
        title = session_title.title_for_session(
            [_prompt_event(content=prompt, metadata={"task_type": "debugging"})]
        )
        self.assertEqual(title, "Debugging session")


class TestTitleFromTaskType(unittest.TestCase):
    """Tier 2: content collection is off by default (event_parser.py) — this
    is the tier almost every real session hits."""

    def test_falls_back_to_task_type_when_no_content(self):
        events = [_prompt_event(content=None, metadata={"task_type": "debugging"})]
        self.assertEqual(session_title.title_for_session(events), "Debugging session")

    def test_unknown_task_type_falls_back_to_untitled(self):
        events = [_prompt_event(content=None, metadata={"task_type": "not_a_real_type"})]
        self.assertEqual(session_title.title_for_session(events), session_title.FALLBACK_TITLE)


class TestTitleFallback(unittest.TestCase):
    def test_no_prompt_events_yet(self):
        events = [_other_event(T.SESSION_START)]
        self.assertEqual(session_title.title_for_session(events), session_title.FALLBACK_TITLE)

    def test_empty_event_list(self):
        self.assertEqual(session_title.title_for_session([]), session_title.FALLBACK_TITLE)


class TestTitleStability(unittest.TestCase):
    """Spec section 12: a title is derived once from the first prompt and
    must not silently change as more prompts arrive in the same session."""

    def test_title_ignores_later_prompts(self):
        events = [
            _prompt_event(content="Fix the Dashboard warning."),
            _prompt_event(content="Now also refactor the whole auth module."),
        ]
        self.assertEqual(session_title.title_for_session(events), "Fix the Dashboard warning")


class TestSessionIsolation(unittest.TestCase):
    """Spec section 14 (session traversal): deriving session A's title must
    never be influenced by session B's events, even when both lists are
    handled in the same process."""

    def test_two_sessions_get_independent_titles(self):
        session_a_events = [_prompt_event(content="Fix the Dashboard warning.", session_id="a")]
        session_b_events = [_prompt_event(content="Investigate the login test failure.", session_id="b")]

        title_a = session_title.title_for_session(session_a_events)
        title_b = session_title.title_for_session(session_b_events)

        self.assertNotEqual(title_a, title_b)
        self.assertTrue(title_a.startswith("Fix"))
        self.assertTrue(title_b.startswith("Investigate"))


if __name__ == "__main__":
    unittest.main()
