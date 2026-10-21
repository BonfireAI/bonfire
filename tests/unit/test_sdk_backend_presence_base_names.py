# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: the SDK backend's PRESENCE list (``tools=``) holds base built-in names.

PRESENCE = base names (text before the first ``(``), no ``mcp__`` entries, no
empty names, de-duplicated in first-seen order. APPROVAL (``allowed_tools=``)
keeps the caller's grant verbatim.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
from bonfire.models.envelope import Envelope
from bonfire.protocols import DispatchOptions


def _make_capture() -> tuple[dict[str, Any], type]:
    """Return ``(captured_kwargs_dict, FakeClaudeAgentOptions)`` pair."""
    captured: dict[str, Any] = {}

    class _FakeClaudeAgentOptions:
        """Mimics SDK's ``ClaudeAgentOptions`` — captures every kwarg."""

        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)

    return captured, _FakeClaudeAgentOptions


async def _empty_query(*, prompt: str = "", options: Any = None):  # type: ignore[no-untyped-def]
    """Async-gen that yields nothing — closes immediately."""
    if False:  # pragma: no cover
        yield None


def _envelope(agent: str = "warrior-agent") -> Envelope:
    return Envelope(task="do work", agent_name=agent, model="claude-opus-4-7")


# ===========================================================================
# PRESENCE layer holds BUILT-IN BASE names only
# ===========================================================================
#
# The CLI's ``tools=`` flag accepts only built-in tool names. A permission
# pattern such as ``Bash(git status)`` passed there silently DROPS the tool
# (measured against the bundled CLI), and ``mcp__*`` names are not governed by
# that flag at all. The PRESENCE layer therefore derives base names; the
# APPROVAL layer keeps the caller's grant exactly.


async def _capture_for(tools: list[str]) -> dict[str, Any]:
    """Run one execute() with ``tools`` and return the captured option kwargs."""
    captured, FakeOptions = _make_capture()
    with (
        patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
        patch("bonfire.dispatch.sdk_backend.query", _empty_query),
    ):
        backend = ClaudeSDKBackend()
        await backend.execute(_envelope(), options=DispatchOptions(tools=tools))
    return captured


class TestPresenceLayerBaseNames:
    """``tools=`` = de-duplicated built-in base names; ``allowed_tools=`` = verbatim grant."""

    async def test_permission_patterns_reduce_to_base_names(self) -> None:
        """``Bash(...)`` patterns become ``Bash`` once; approval keeps all patterns."""
        grant = ["Read", "Bash(git diff:*)", "Bash(pytest:*)", "Edit"]
        captured = await _capture_for(list(grant))

        assert list(captured["tools"]) == ["Read", "Bash", "Edit"], (
            f"from {len(grant)} granted entries expected 3 base names; got {captured['tools']!r}"
        )
        assert list(captured["allowed_tools"]) == grant

    async def test_mcp_entries_excluded_from_presence_kept_in_approval(self) -> None:
        """``mcp__*`` names are not built-ins: absent from ``tools=``, kept in approval."""
        grant = ["Read", "mcp__lexicon__memory_read"]
        captured = await _capture_for(list(grant))

        assert list(captured["tools"]) == ["Read"], (
            f"from {len(grant)} granted entries expected only 'Read'; got {captured['tools']!r}"
        )
        assert list(captured["allowed_tools"]) == grant

    async def test_pattern_only_custom_policy_grant_keeps_the_tool_present(self) -> None:
        """A policy granting only a pattern must not silently empty the PRESENCE layer."""
        grant = ["Bash(git status)"]
        captured = await _capture_for(list(grant))

        assert list(captured["tools"]) == ["Bash"], (
            f"pattern-only grant of {len(grant)} entry must expose 'Bash', "
            f"not drop it; got {captured['tools']!r}"
        )
        assert list(captured["allowed_tools"]) == grant

    async def test_duplicate_tool_names_dedup_in_presence_kept_in_approval(self) -> None:
        """PRESENCE de-duplicates in first-seen order; APPROVAL keeps duplicates."""
        # Old pin (test_duplicate_tool_names_propagate_verbatim): duplicates reached
        # tools= verbatim. Changed because tools= now holds de-duplicated base names.
        captured, FakeOptions = _make_capture()
        incoming = ["Read", "Read", "Write", "Read"]

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=incoming)
            await backend.execute(_envelope(), options=options)

        assert list(captured["tools"]) == ["Read", "Write"], (
            f"tools= must be de-duplicated in first-seen order from {len(incoming)} entries; "
            f"got {captured['tools']!r}"
        )
        assert list(captured["allowed_tools"]) == incoming
