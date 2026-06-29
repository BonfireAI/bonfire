# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Discoverability + honest-labeling tests for the session-lifecycle verbs.

The empty-store / document-rendering honesty contracts live in
``test_session_lifecycle_cli.py``; this file pins what that one cannot reach
from the rendered help surface: the verbs stay registered AND no longer
mislabel themselves as stubs now that they do real work.
"""

from __future__ import annotations

from bonfire.cli.app import app

# ---------------------------------------------------------------------------
# The session-lifecycle commands are real now (not stubs) — they must stay
# discoverable AND must NOT mislabel themselves as stubs in ``bonfire --help``.
# ---------------------------------------------------------------------------


class TestStubCommandLabeling:
    """``bonfire status / resume / handoff`` are real session-lifecycle verbs.

    They must:
      1. STILL be registered (discoverability -- users can find them).
      2. NOT call themselves stubs in ``bonfire --help`` -- they do real work
         now, so the prior "(stub -- implementation lands in 0.1.x)" labels
         would be the lie. The help text must describe the real behaviour.
    """

    def test_status_command_still_registered(self) -> None:
        """``bonfire status`` is in the registry (discoverable)."""
        names = {
            (c.name or (c.callback.__name__ if c.callback else None))
            for c in app.registered_commands
        }
        assert "status" in names

    def test_resume_command_still_registered(self) -> None:
        names = {
            (c.name or (c.callback.__name__ if c.callback else None))
            for c in app.registered_commands
        }
        assert "resume" in names

    def test_handoff_command_still_registered(self) -> None:
        names = {
            (c.name or (c.callback.__name__ if c.callback else None))
            for c in app.registered_commands
        }
        assert "handoff" in names

    def _command_help_text(self, command: str) -> str:
        """Return the registered ``help=`` (or callback docstring) for *command*.

        Uses ``app.registered_commands`` introspection rather than parsing
        rendered ``--help`` output. Rich-box rendering varies by terminal
        width and rendering mode; the registry is the stable source of truth.
        """
        for c in app.registered_commands:
            name = c.name or (c.callback.__name__ if c.callback else None)
            if name == command:
                return c.help or (c.callback.__doc__ if c.callback else None) or ""
        return ""

    def test_top_level_help_does_not_mislabel_status_as_stub(self) -> None:
        """``status`` is real now; its help must not call it a stub."""
        help_text = self._command_help_text("status").lower()
        assert "stub" not in help_text, (
            f"status help text must not call the real command a stub; got: {help_text!r}"
        )

    def test_top_level_help_does_not_mislabel_resume_as_stub(self) -> None:
        help_text = self._command_help_text("resume").lower()
        assert "stub" not in help_text, (
            f"resume help text must not call the real command a stub; got: {help_text!r}"
        )

    def test_top_level_help_does_not_mislabel_handoff_as_stub(self) -> None:
        help_text = self._command_help_text("handoff").lower()
        assert "stub" not in help_text, (
            f"handoff help text must not call the real command a stub; got: {help_text!r}"
        )
