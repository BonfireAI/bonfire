# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Regression tests for ``bonfire handoff`` honesty (W5.F).

The handoff command is a v0.1 stub that performs no work. The Day-1 release-day
contract is that the stub must NOT lie about doing work it did not do. These
tests guard the honest copy: invocation reports the absence-of-state, and the
``--help`` surface continues to work for discoverability.
"""

from __future__ import annotations

from typer.testing import CliRunner

from bonfire.cli.app import app

runner = CliRunner()


class TestHandoffHonesty:
    """The handoff stub must not claim to have done work it did not do."""

    def test_handoff_invocation_output_is_truthful(self) -> None:
        """`bonfire handoff` must not lie about generating anything."""
        result = runner.invoke(app, ["handoff"])
        assert result.exit_code == 0
        output_lower = result.output.lower()
        # MUST NOT claim work was done.
        assert "generated" not in output_lower, (
            f"handoff stub must not claim 'generated'; got: {result.output!r}"
        )
        # MUST signal absence-of-state. Any of these honest markers is fine.
        honest_markers = ("not", "no session", "stub", "unimplemented")
        assert any(marker in output_lower for marker in honest_markers), (
            f"handoff stub must signal absence-of-state; got: {result.output!r}"
        )

    def test_handoff_help_still_exits_zero(self) -> None:
        """`bonfire handoff --help` must continue to work."""
        result = runner.invoke(app, ["handoff", "--help"])
        assert result.exit_code == 0


# ---------------------------------------------------------------------------
# Stub commands must label themselves as stubs in ``bonfire --help``
# ---------------------------------------------------------------------------


class TestStubCommandLabeling:
    """``bonfire status / resume / handoff`` are v0.1 stubs.

    They must:
      1. STILL be registered (discoverability -- users can find them).
      2. NOT lie in ``bonfire --help`` -- the short-help string must signal
         that the command is a stub. Pre-fix, the help strings were active-
         voice promises ("Show current Bonfire session status.") which
         misled users into expecting working behavior.
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

    def _help_command_lines(self, command: str) -> list[str]:
        """Return ``bonfire --help`` lines that mention *command* as a name.

        Typer's rich-box rendering wraps each subcommand row with box-drawing
        characters (e.g. ``│ status   ...`` ). Strip surrounding whitespace +
        leading box chars before matching on a word-boundary command name.
        """
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0, (
            f"--help should exit zero; got {result.exit_code}: {result.output!r}"
        )
        matched: list[str] = []
        for raw in result.output.splitlines():
            # Strip whitespace + Typer box-drawing chars from the left so we
            # can anchor on the command name itself.
            stripped = raw.lstrip(" \t│|┃║").rstrip()
            # Match the command at start, followed by whitespace (so we do
            # not match ``status-foo`` or similar).
            if stripped.startswith(command + " ") or stripped == command:
                matched.append(raw)
        return matched

    def test_top_level_help_marks_status_as_stub(self) -> None:
        """``bonfire --help`` short-help for ``status`` flags it as a stub."""
        lines = self._help_command_lines("status")
        assert lines, "`status` not listed in --help output"
        joined = "\n".join(lines).lower()
        assert "stub" in joined, f"status help line must mark the command as a stub; got: {lines!r}"

    def test_top_level_help_marks_resume_as_stub(self) -> None:
        lines = self._help_command_lines("resume")
        assert lines, "`resume` not listed in --help output"
        joined = "\n".join(lines).lower()
        assert "stub" in joined, f"resume help line must mark the command as a stub; got: {lines!r}"

    def test_top_level_help_marks_handoff_as_stub(self) -> None:
        lines = self._help_command_lines("handoff")
        assert lines, "`handoff` not listed in --help output"
        joined = "\n".join(lines).lower()
        assert "stub" in joined, (
            f"handoff help line must mark the command as a stub; got: {lines!r}"
        )
