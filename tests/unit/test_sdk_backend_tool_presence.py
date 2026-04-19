"""CANONICAL RED — BON-337 (Sage-merged) — SDK belt-and-suspenders.

Merged from Knight-A (adversarial) and Knight-B (conservative contract).
The Warrior modifies ``src/bonfire/dispatch/sdk_backend.py`` to add exactly
one new kwarg to the existing ``ClaudeAgentOptions(...)`` call, immediately
before the pre-existing ``allowed_tools=options.tools``:

    tools=list(options.tools),          # NEW — PRESENCE layer
    allowed_tools=options.tools,        # UNCHANGED — APPROVAL layer

Sage decisions asserted (BON-337 unified Sage doc, 2026-04-18):
    D7: TWO kwargs on ``ClaudeAgentOptions(...)``:
        - ``tools=list(options.tools)`` — PRESENCE layer (SDK removes tool
          from Claude's tool context entirely when list is empty).
        - ``allowed_tools=options.tools`` — APPROVAL layer (skips prompt).
        For ``tools=[]`` + ``permission_mode='dontAsk'`` the SDK yields
        deterministic deny-all.
        ``tools=list(options.tools)`` MUST produce a FRESH list each call.
    D7 footer: ``options.role`` is NOT consumed by ``sdk_backend.py`` in
        BON-337 — that's BON-338 territory.
    §6 open #1: ``disallowed_tools`` is DEFERRED — BON-337 does NOT ship it.

Knight-A adversarial tests elevated to mandatory:
    fresh-list identity across repeat calls; adversarial tool content
    (whitespace, unicode, duplicates, large lists, case preservation);
    existing-kwargs-preserved (model, max_turns, setting_sources, stderr);
    empty-tools kill-switch semantics.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.protocols import DispatchOptions

try:
    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    ClaudeSDKBackend = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module() -> None:
    """Fail every test while ``bonfire.dispatch.sdk_backend`` is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.sdk_backend not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Helpers — capture ``ClaudeAgentOptions`` kwargs; stub async query()
# ---------------------------------------------------------------------------


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
# 1. PRESENCE + APPROVAL layers both set (Sage D7 baseline)
# ===========================================================================


class TestBothKwargsSet:
    """Sage D7 — BOTH ``tools`` and ``allowed_tools`` must land on ``ClaudeAgentOptions``."""

    async def test_tools_kwarg_present_and_equals_options_tools(self) -> None:
        """Sage D7 — PRESENCE layer ``tools=`` MUST be set."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(
                model="claude-opus-4-7",
                tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
                role="warrior",
            )
            await backend.execute(_envelope(), options=options)

        assert "tools" in captured
        assert list(captured["tools"]) == [
            "Read", "Write", "Edit", "Bash", "Grep", "Glob",
        ]

    async def test_allowed_tools_kwarg_remains_unchanged(self) -> None:
        """Sage D7 — APPROVAL layer ``allowed_tools=`` MUST remain (belt-and-suspenders)."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(
                model="claude-opus-4-7",
                tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
            )
            await backend.execute(_envelope(), options=options)

        assert list(captured["allowed_tools"]) == [
            "Read", "Write", "Edit", "Bash", "Grep", "Glob",
        ]

    async def test_tools_and_allowed_tools_have_equal_content(self) -> None:
        """Sage D7 — both kwargs carry the same tool names."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read", "Grep"])
            await backend.execute(_envelope(), options=options)

        assert list(captured["tools"]) == list(captured["allowed_tools"])

    async def test_tools_kwarg_is_a_list(self) -> None:
        """Sage D7 — ``tools=list(options.tools)`` MUST produce a plain list."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read", "Write"])
            await backend.execute(_envelope(), options=options)

        assert type(captured["tools"]) is list


# ===========================================================================
# 2. PRESENCE layer is a FRESH list each call (Sage D7 ``list(options.tools)``)
# ===========================================================================


class TestPresenceListIsFresh:
    """Sage D7 — ``tools=list(options.tools)`` MUST yield a fresh list each call."""

    async def test_two_executions_produce_independent_tools_lists(self) -> None:
        """Running twice in sequence captures two fresh lists (by identity)."""
        snapshots: list[dict[str, Any]] = []

        class _RecorderOptions:
            def __init__(self, **kwargs: Any) -> None:
                # Snapshot the raw kwargs dict — values stored by reference.
                snapshots.append(dict(kwargs))

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", _RecorderOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read", "Write"])
            await backend.execute(_envelope(), options=options)
            await backend.execute(_envelope(), options=options)

        assert len(snapshots) == 2
        t0 = snapshots[0]["tools"]
        t1 = snapshots[1]["tools"]
        assert t0 == t1
        # ``list(options.tools)`` produces a distinct list object each call.
        assert t0 is not t1


# ===========================================================================
# 3. Empty tools = SDK hard kill-switch (Scout-1/337 §1 / §6)
# ===========================================================================


class TestEmptyToolsKillSwitch:
    """Sage D7 / Scout-1 §6 — ``tools=[]`` is the SDK's hard kill-switch."""

    async def test_empty_tools_reaches_presence_layer(self) -> None:
        """Empty list is passed verbatim to PRESENCE layer — not "default preset"."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=[])
            await backend.execute(_envelope(), options=options)

        assert "tools" in captured
        assert list(captured["tools"]) == []

    async def test_empty_tools_reaches_approval_layer(self) -> None:
        """Sage D7 — empty ``allowed_tools`` preserved alongside empty ``tools``."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=[])
            await backend.execute(_envelope(), options=options)

        assert list(captured["allowed_tools"]) == []

    async def test_permission_mode_dontAsk_default_preserved(self) -> None:
        """Sage D7 — ``permission_mode='dontAsk'`` default + empty ``tools`` = deny-all."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=[])
            await backend.execute(_envelope(), options=options)

        assert captured.get("permission_mode") == "dontAsk"


# ===========================================================================
# 4. ``disallowed_tools`` DEFERRED (Sage §6 open #1)
# ===========================================================================


class TestDisallowedToolsNotSet:
    """Sage §6 — ``disallowed_tools`` is DEFERRED, NOT shipped in BON-337."""

    async def test_disallowed_tools_not_in_kwargs(self) -> None:
        """BON-337 MUST NOT introduce ``disallowed_tools`` kwarg."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read", "Write"])
            await backend.execute(_envelope(), options=options)

        assert "disallowed_tools" not in captured


# ===========================================================================
# 5. Existing kwargs preserved — tools addition doesn't clobber anything
# ===========================================================================


class TestExistingKwargsPreserved:
    """Adding ``tools=`` MUST NOT remove or alter other kwargs."""

    async def test_model_kwarg_preserved(self) -> None:
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(model="claude-opus-4-7", tools=["Read"])
            await backend.execute(_envelope(), options=options)

        assert captured.get("model") == "claude-opus-4-7"

    async def test_max_turns_preserved(self) -> None:
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(max_turns=7, tools=["Read"])
            await backend.execute(_envelope(), options=options)

        assert captured.get("max_turns") == 7

    async def test_setting_sources_preserved(self) -> None:
        """The hardcoded ``setting_sources=["project"]`` MUST remain."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])
            await backend.execute(_envelope(), options=options)

        assert captured.get("setting_sources") == ["project"]

    async def test_stderr_callback_preserved(self) -> None:
        """The stderr lambda MUST remain (crash-recovery triage)."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])
            await backend.execute(_envelope(), options=options)

        assert "stderr" in captured
        assert callable(captured["stderr"])


# ===========================================================================
# 6. Adversarial tool-list contents propagate verbatim
# ===========================================================================


class TestAdversarialToolListContent:
    """Whatever is in ``options.tools`` MUST propagate verbatim to BOTH layers."""

    async def test_tool_names_with_whitespace_propagate(self) -> None:
        """Whitespace in tool names is preserved (SDK matches literally)."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read ", " Write", "Edit\t"])
            await backend.execute(_envelope(), options=options)

        assert list(captured["tools"]) == ["Read ", " Write", "Edit\t"]

    async def test_unicode_tool_names_propagate(self) -> None:
        """Unicode tool names propagate to both layers."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["读取", "Write"])
            await backend.execute(_envelope(), options=options)

        assert list(captured["tools"]) == ["读取", "Write"]

    async def test_duplicate_tool_names_propagate_verbatim(self) -> None:
        """Duplicates in incoming list are NOT deduplicated by sdk_backend."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read", "Read", "Write"])
            await backend.execute(_envelope(), options=options)

        assert list(captured["tools"]) == ["Read", "Read", "Write"]

    async def test_very_large_tool_list_propagates(self) -> None:
        """100-tool list propagates without truncation."""
        captured, FakeOptions = _make_capture()
        tool_list = [f"Tool{i}" for i in range(100)]

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=tool_list)
            await backend.execute(_envelope(), options=options)

        assert list(captured["tools"]) == tool_list
        assert len(list(captured["tools"])) == 100

    async def test_tool_case_preserved(self) -> None:
        """Scout-1 §6 — tool names are case-sensitive; no auto-case-fold."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["read", "BASH", "WrItE"])
            await backend.execute(_envelope(), options=options)

        assert list(captured["tools"]) == ["read", "BASH", "WrItE"]


# ===========================================================================
# 7. ``options.role`` NOT consumed by sdk_backend in BON-337 (D7 footer)
# ===========================================================================


class TestRoleNotConsumedBySdkBackend:
    """Sage D7 footer — ``options.role`` propagates but is NOT forwarded by
    ``sdk_backend`` in BON-337. BON-338 will consume it via ``hooks=``."""

    async def test_role_kwarg_not_passed_to_claude_agent_options(self) -> None:
        """``role=`` MUST NOT appear in the ``ClaudeAgentOptions`` call in BON-337."""
        captured, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(
                model="claude-opus-4-7",
                tools=["Read"],
                role="warrior",
            )
            await backend.execute(_envelope(), options=options)

        assert "role" not in captured


# ===========================================================================
# 8. SDK backend ``execute()`` semantics still sane with ``tools=`` kwarg
# ===========================================================================


class TestSdkBackendSemanticsIntact:
    """Adding ``tools=`` kwarg MUST NOT change ``execute()`` semantics."""

    async def test_execute_returns_envelope(self) -> None:
        """Baseline — ``execute`` still returns an ``Envelope``, not a raise."""
        _, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])
            result = await backend.execute(_envelope(), options=options)

        assert isinstance(result, Envelope)

    async def test_zero_tools_execute_still_completes_without_crash(self) -> None:
        """``tools=[]`` + empty query stream → no exception leak."""
        _, FakeOptions = _make_capture()

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=[])
            result = await backend.execute(_envelope(), options=options)

        assert isinstance(result, Envelope)
        assert result.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)
