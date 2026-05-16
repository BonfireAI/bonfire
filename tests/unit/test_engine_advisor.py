"""Canonical RED — ``bonfire.engine.advisor.VaultAdvisor``.

Synthesized from Knight-A orchestration + Knight-B contract fidelity.

VaultAdvisor is the ONLY advisory channel for v0.1 (compiler interface dropped —
Sage D3). It is fail-open: the pipeline proceeds without advice whenever the
vault is slow, missing, or broken. In v0.1 VaultAdvisor ships against the
``VaultBackend`` Protocol only — there is no default concrete backend.
(Historically ``StageExecutor`` was the lone consumer wiring the advisor; that
class was deleted in Wave 11 Lane E along with the dead stage-execution path.
The advisor itself remains live at ``bonfire.engine.advisor``; engine-side
wiring is parked pending a follow-up ticket.)

Contract locked:
    1. VaultAdvisor is importable from ``bonfire.engine.advisor`` (not __all__).
    2. Constructor: positional ``backend`` + kw-only tunables.
    3. ``check(stage: StageSpec) -> str`` is async; always returns str.
    4. Any backend exception -> ``""`` (fail-open).
    5. Timeout via ``asyncio.wait_for(..., timeout_seconds)`` -> ``""``.
    6. Empty / non-list backend results -> ``""``.
    7. Position-based confidence filtering + ``max_entries`` cap.
    8. Query text: ``f"{stage.name} {stage.agent_name}"``.
    9. ``entry_type="error_pattern"`` kwarg to backend.query.
   10. Markdown output: ``## Known Issues (from vault)`` + bullet list.
"""

from __future__ import annotations

import asyncio
import inspect
from typing import Any
from unittest.mock import AsyncMock

from bonfire.models.plan import StageSpec
from bonfire.protocols import VaultEntry

# ---------------------------------------------------------------------------
# Structural VaultBackend mocks (do NOT depend on a concrete backend impl —
# v0.1 ships no default concrete VaultBackend; the advisor is Protocol-only).
# ---------------------------------------------------------------------------


class _StubVaultBackend:
    """Minimal structural VaultBackend satisfying the protocol shape."""

    def __init__(self, entries: list[VaultEntry] | None = None) -> None:
        self._entries = entries or []

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        entry_type: str | None = None,
    ) -> list[VaultEntry]:
        if entry_type is None:
            matching = self._entries
        else:
            matching = [e for e in self._entries if e.entry_type == entry_type]
        return matching[:limit]

    async def store(self, entry: VaultEntry) -> str:
        self._entries.append(entry)
        return entry.entry_id

    async def exists(self, content_hash: str) -> bool:
        return any(e.content_hash == content_hash for e in self._entries)

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        return [e for e in self._entries if e.source_path == source_path]


class _RaisingVaultBackend(_StubVaultBackend):
    """Backend whose ``query`` raises to exercise the fail-open path."""

    def __init__(self, exc: Exception) -> None:
        super().__init__([])
        self._exc = exc

    async def query(self, *args: Any, **kwargs: Any) -> list[VaultEntry]:
        raise self._exc


class _SlowVaultBackend(_StubVaultBackend):
    """Backend whose ``query`` hangs past the advisor's timeout."""

    def __init__(self, delay_seconds: float = 5.0) -> None:
        super().__init__([])
        self._delay = delay_seconds

    async def query(self, *args: Any, **kwargs: Any) -> list[VaultEntry]:
        await asyncio.sleep(self._delay)
        return []


def _stage(name: str = "scout", agent_name: str = "scout-agent") -> StageSpec:
    return StageSpec(name=name, agent_name=agent_name)


def _entry(content: str, entry_type: str = "error_pattern") -> VaultEntry:
    return VaultEntry(content=content, entry_type=entry_type)


# ===========================================================================
# 1. Imports & class shape
# ===========================================================================


class TestImports:
    """VaultAdvisor is importable from the advisor submodule."""

    def test_importable_from_advisor_module(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        assert VaultAdvisor is not None

    def test_advisor_is_a_class(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        assert isinstance(VaultAdvisor, type)


# ===========================================================================
# 2. Constructor signature — positional backend + kw-only tunables
# ===========================================================================


class TestConstructor:
    """Constructor: positional ``backend`` + kw-only config (V1 advisor.py 24-33)."""

    def test_accepts_backend_positional(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        adv = VaultAdvisor(_StubVaultBackend())
        assert adv is not None

    def test_tunables_are_keyword_only(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        sig = inspect.signature(VaultAdvisor.__init__)
        params = list(sig.parameters.values())
        # skip self (index 0) + backend (index 1); remainder kw-only
        for p in params[2:]:
            assert p.kind == inspect.Parameter.KEYWORD_ONLY

    def test_accepts_timeout_seconds(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        adv = VaultAdvisor(_StubVaultBackend(), timeout_seconds=0.05)
        assert adv is not None

    def test_accepts_confidence_threshold(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        adv = VaultAdvisor(_StubVaultBackend(), confidence_threshold=0.5)
        assert adv is not None

    def test_accepts_max_entries(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        adv = VaultAdvisor(_StubVaultBackend(), max_entries=5)
        assert adv is not None

    def test_accepts_decay_sessions(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        adv = VaultAdvisor(_StubVaultBackend(), decay_sessions=7)
        assert adv is not None

    def test_accepts_current_session_id(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        adv = VaultAdvisor(_StubVaultBackend(), current_session_id="sid-1")
        assert adv is not None

    def test_accepts_all_kwargs_at_once(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        adv = VaultAdvisor(
            _StubVaultBackend(),
            timeout_seconds=0.5,
            confidence_threshold=0.8,
            max_entries=5,
            decay_sessions=10,
            current_session_id="sess-42",
        )
        assert adv is not None


# ===========================================================================
# 3. check() signature
# ===========================================================================


class TestCheckSignature:
    """``check(stage: StageSpec) -> str`` is async (V1 line 41)."""

    def test_check_is_async(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        assert inspect.iscoroutinefunction(VaultAdvisor.check)

    def test_check_accepts_stage(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        sig = inspect.signature(VaultAdvisor.check)
        assert "stage" in sig.parameters


# ===========================================================================
# 4. Return-type contract
# ===========================================================================


class TestReturnType:
    """``check()`` always returns ``str`` — never None, never bytes, never list."""

    async def test_empty_vault_returns_str(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(_StubVaultBackend())
        result = await advisor.check(_stage())
        assert isinstance(result, str)

    async def test_empty_vault_returns_empty_string(self) -> None:
        """No entries -> exactly ``""``, not whitespace."""
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(_StubVaultBackend())
        result = await advisor.check(_stage())
        assert result == ""

    async def test_populated_vault_returns_non_empty_str(self) -> None:
        """Above-threshold entry is surfaced in markdown output."""
        from bonfire.engine.advisor import VaultAdvisor

        backend = _StubVaultBackend([_entry("flaky test X")])
        advisor = VaultAdvisor(backend, max_entries=1, confidence_threshold=0.0)
        result = await advisor.check(_stage())
        assert "flaky test X" in result


# ===========================================================================
# 5. Fail-open: exceptions swallowed
# ===========================================================================


class TestFailOpen:
    """Any backend exception -> ``""``. The pipeline NEVER crashes over vault."""

    async def test_runtime_error_returns_empty(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(_RaisingVaultBackend(RuntimeError("vault down")))
        result = await advisor.check(_stage())
        assert result == ""

    async def test_value_error_returns_empty(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(_RaisingVaultBackend(ValueError("bad query")))
        result = await advisor.check(_stage())
        assert result == ""

    async def test_custom_exception_returns_empty(self) -> None:
        """Even exotic exceptions are swallowed (V1 BLE001 catch-all)."""
        from bonfire.engine.advisor import VaultAdvisor

        class _WeirdError(Exception):
            pass

        advisor = VaultAdvisor(_RaisingVaultBackend(_WeirdError("oops")))
        result = await advisor.check(_stage())
        assert result == ""

    async def test_check_does_not_propagate_exception(self) -> None:
        """check() MUST NOT raise — catch-all is required."""
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(_RaisingVaultBackend(RuntimeError("boom")))
        # If this raises, the test fails.
        await advisor.check(_stage())


# ===========================================================================
# 6. Timeout enforcement (via asyncio.wait_for)
# ===========================================================================


class TestTimeout:
    """Slow backend past ``timeout_seconds`` -> ``""``."""

    async def test_slow_backend_times_out_and_returns_empty(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(
            _SlowVaultBackend(delay_seconds=0.5),
            timeout_seconds=0.05,
        )
        result = await advisor.check(_stage())
        assert result == ""

    async def test_timeout_does_not_raise(self) -> None:
        """TimeoutError must NOT propagate."""
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(
            _SlowVaultBackend(delay_seconds=0.5),
            timeout_seconds=0.02,
        )
        await advisor.check(_stage())


# ===========================================================================
# 7. Query construction — exact call shape to backend.query
# ===========================================================================


class TestQueryConstruction:
    """check() calls backend.query with the documented args (V1 lines 47-55)."""

    async def test_query_text_is_stage_name_plus_agent_name(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        backend = _StubVaultBackend()
        backend.query = AsyncMock(return_value=[])  # type: ignore[method-assign]

        advisor = VaultAdvisor(backend)
        await advisor.check(_stage(name="scout", agent_name="researcher"))

        backend.query.assert_called_once()
        args, _ = backend.query.call_args
        # V1: query text is the positional first argument.
        assert args[0] == "scout researcher"

    async def test_query_filters_by_error_pattern(self) -> None:
        """entry_type kwarg must be 'error_pattern' (V1 line 52)."""
        from bonfire.engine.advisor import VaultAdvisor

        backend = _StubVaultBackend()
        backend.query = AsyncMock(return_value=[])  # type: ignore[method-assign]

        advisor = VaultAdvisor(backend)
        await advisor.check(_stage())

        kwargs = backend.query.call_args.kwargs
        assert kwargs.get("entry_type") == "error_pattern"


# ===========================================================================
# 8. Confidence filtering and max_entries cap
# ===========================================================================


class TestConfidenceFiltering:
    """Position-based confidence drops low-ranked entries (V1 lines 63-72)."""

    async def test_max_entries_caps_output(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        entries = [_entry(f"pattern-{i}") for i in range(10)]
        advisor = VaultAdvisor(
            _StubVaultBackend(entries),
            max_entries=2,
            confidence_threshold=0.0,
        )
        result = await advisor.check(_stage())
        # Only the first two entries appear.
        assert "pattern-0" in result
        assert "pattern-1" in result
        assert "pattern-5" not in result

    async def test_high_confidence_threshold_drops_all(self) -> None:
        """Threshold of 1.01 exceeds any position-based confidence -> ``""``."""
        from bonfire.engine.advisor import VaultAdvisor

        entries = [_entry(f"pat-{i}") for i in range(5)]
        advisor = VaultAdvisor(
            _StubVaultBackend(entries),
            confidence_threshold=1.01,
        )
        result = await advisor.check(_stage())
        assert result == ""


# ===========================================================================
# 9. Output formatting — load-bearing for downstream ContextBuilder
# ===========================================================================


class TestOutputFormat:
    """Markdown shape: heading + bullet list (V1 lines 77-78)."""

    async def test_non_empty_output_has_known_issues_heading(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(
            _StubVaultBackend([_entry("flaky subprocess")]),
            confidence_threshold=0.0,
            max_entries=1,
        )
        result = await advisor.check(_stage())
        assert "Known Issues" in result

    async def test_entries_rendered_as_markdown_bullets(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        advisor = VaultAdvisor(
            _StubVaultBackend([_entry("A"), _entry("B")]),
            confidence_threshold=0.0,
            max_entries=2,
        )
        result = await advisor.check(_stage())
        assert "- A" in result
        assert "- B" in result


# ===========================================================================
# 10. Degenerate payloads — non-list, empty list
# ===========================================================================


class TestDegeneratePayloads:
    """Backends returning weird shapes must not crash the advisor (V1 lines 60-61)."""

    async def test_non_list_return_returns_empty(self) -> None:
        """If backend.query returns something other than a list, fail-open."""
        from bonfire.engine.advisor import VaultAdvisor

        backend = _StubVaultBackend()
        backend.query = AsyncMock(return_value=None)  # type: ignore[method-assign]

        advisor = VaultAdvisor(backend)
        result = await advisor.check(_stage())
        assert result == ""

    async def test_empty_list_returns_empty(self) -> None:
        from bonfire.engine.advisor import VaultAdvisor

        backend = _StubVaultBackend()
        backend.query = AsyncMock(return_value=[])  # type: ignore[method-assign]

        advisor = VaultAdvisor(backend)
        result = await advisor.check(_stage())
        assert result == ""
