"""RED soft-pin for ``ToolPolicy`` Protocol docstring drift — W5.G.

Mirror Probe N+1 finding S1.10 (docstring half):

The ``ToolPolicy`` Protocol class-docstring at
``src/bonfire/dispatch/tool_policy.py:27-36`` asserts:

    "An empty list means 'no tools permitted' (the SDK interprets
    allowed_tools=[] combined with permission_mode='dontAsk' as deny-all)."

But PR #72 flipped ``DispatchOptions.permission_mode`` default from ``"dontAsk"``
to ``"default"``. Empty ``allowed_tools`` + ``permission_mode="default"`` is
NOT deny-all in the SDK — it would prompt. The parenthetical describes a
configuration callers no longer reach by default.

This is a soft-pin against re-drift: the docstring must not mention
``"dontAsk"`` while the default permission_mode is ``"default"``. The Warrior
will rewrite the parenthetical; this test prevents future drift from silently
re-introducing the contradiction.
"""

from __future__ import annotations

import inspect

from bonfire.dispatch.tool_policy import ToolPolicy


class TestToolPolicyDocstringMatchesDefaultPermissionMode:
    """``ToolPolicy`` Protocol docstring must not cite the stale ``dontAsk`` claim."""

    def test_docstring_does_not_reference_dont_ask(self) -> None:
        """After the PR #72 default flip, the ``dontAsk`` parenthetical is wrong."""
        doc = inspect.getdoc(ToolPolicy) or ""
        assert "dontAsk" not in doc, (
            f"ToolPolicy Protocol docstring still cites the stale 'dontAsk' "
            f"claim. Since DispatchOptions.permission_mode default flipped to "
            f"'default' in PR #72, empty allowed_tools + permission_mode='default' "
            f"is NOT deny-all in the SDK. Rewrite the parenthetical.\n"
            f"Current docstring:\n{doc}"
        )
