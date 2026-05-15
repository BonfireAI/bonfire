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
