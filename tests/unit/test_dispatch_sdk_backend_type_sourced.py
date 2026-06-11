"""RED tests for BON-1407 §Defect-1 — sdk_backend error construction is TYPE-SOURCED.

Phase 3 of the failure-architecture epic makes dispatch error construction
flow through the typed ``BonfireError`` taxonomy + ``ErrorDetail.from_exception``
instead of hand-typed bare-string ``ErrorDetail(error_type="...")`` literals.

This is a **behavior-preserving** refactor: the observable
``ErrorDetail.error_type`` strings on the rate-limit and agent-error paths MUST
stay byte-identical (``"RateLimitError"`` / ``"AgentError"``). What changes is
the *source* of those strings — they come from the typed exception's class
name, not a string literal — and the *consequence* that the structured
``ErrorDetail`` is now self-describing: it carries a populated ``traceback``
the way ``from_exception`` produces (the same triage payload the generic
exception path already carries, per ``test_dispatch_sdk_backend.py`` ::
``test_error_detail_captures_traceback``).

Why ``traceback`` is the type-sourced signature
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
The current ``main`` constructs these two ``ErrorDetail`` instances as bare
strings with NO traceback (``src/bonfire/dispatch/sdk_backend.py:159-164`` and
``:176-185``), so ``error.traceback is None``. A type-sourced construction
that raises the typed ``BonfireError`` subclass and routes it through
``ErrorDetail.from_exception`` populates ``traceback`` (``errors.py:190``,
``envelope.py:from_exception``). Asserting the traceback is populated
distinguishes the typed path from the bare-string path WITHOUT dictating the
exact construction mechanism, and pins that these two failure modes now speak
the one self-describing vocabulary (the Elegance Law).

These tests FAIL on current code because ``error.traceback is None`` on both
the rate-limit-rejected path and the ``is_error=True`` path. They are NOT
import errors — the module imports fine; the assertions are about the shape
of the produced ``ErrorDetail``.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bonfire.models.envelope import TaskStatus

# Real SDK types for ``spec=`` so the backend's ``isinstance`` checks match.
try:
    from claude_agent_sdk.types import (  # type: ignore[import-untyped]
        AssistantMessage as _AssistantMessage,
    )
    from claude_agent_sdk.types import (
        RateLimitEvent as _RateLimitEvent,  # type: ignore[import-untyped]
    )
    from claude_agent_sdk.types import (
        ResultMessage as _ResultMessage,  # type: ignore[import-untyped]
    )

    _HAS_SDK_TYPES = True
except ImportError:  # pragma: no cover
    _AssistantMessage = None  # type: ignore[assignment,misc]
    _ResultMessage = None  # type: ignore[assignment,misc]
    _RateLimitEvent = None  # type: ignore[assignment,misc]
    _HAS_SDK_TYPES = False


from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
from bonfire.models.envelope import Envelope
from bonfire.protocols import DispatchOptions


def _mock_assistant_message(text: str) -> MagicMock:
    block = MagicMock()
    block.text = text
    msg = MagicMock(spec=_AssistantMessage) if _HAS_SDK_TYPES else MagicMock()
    msg.content = [block]
    return msg


def _mock_result_message(
    *,
    total_cost_usd: float | None = 0.10,
    duration_ms: int = 5000,
    session_id: str = "sess-1",
    result: str | None = None,
    is_error: bool = False,
    errors: list[str] | None = None,
) -> MagicMock:
    msg = MagicMock(spec=_ResultMessage) if _HAS_SDK_TYPES else MagicMock()
    msg.total_cost_usd = total_cost_usd
    msg.duration_ms = duration_ms
    msg.session_id = session_id
    msg.result = result
    msg.is_error = is_error
    msg.errors = errors
    return msg


def _mock_rate_limit(status: str = "rejected") -> MagicMock:
    msg = MagicMock(spec=_RateLimitEvent) if _HAS_SDK_TYPES else MagicMock()
    msg.status = status
    return msg


def _envelope(task: str = "run something") -> Envelope:
    return Envelope(task=task, agent_name="scout", model="claude-sonnet")


def _options(model: str = "claude-sonnet") -> DispatchOptions:
    return DispatchOptions(
        model=model, max_turns=5, max_budget_usd=1.0, tools=["Read", "Write"], cwd="/tmp/test"
    )


_NEEDS_SDK = pytest.mark.skipif(
    not _HAS_SDK_TYPES,
    reason="claude_agent_sdk types unavailable — SDK message routing cannot be exercised",
)


# ---------------------------------------------------------------------------
# Rate-limit rejection — typed RateLimitError, self-describing ErrorDetail
# ---------------------------------------------------------------------------


@_NEEDS_SDK
class TestRateLimitTypeSourced:
    """``RateLimitEvent(status='rejected')`` produces a typed, self-describing detail."""

    async def test_rate_limit_error_type_preserved(self):
        """Behavior-preserving anchor: the observable error_type stays 'RateLimitError'."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_rate_limit(status="rejected")

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            out = await ClaudeSDKBackend().execute(_envelope(), options=_options())

        assert out.status == TaskStatus.FAILED
        assert out.error is not None
        # The string must not drift — the refactor sources it from the typed
        # class name, which equals the previous literal.
        assert out.error.error_type == "RateLimitError"

    async def test_rate_limit_detail_is_self_describing(self):
        """Type-sourced construction carries a populated traceback (from_exception).

        Bare-string ``ErrorDetail(error_type="RateLimitError", message=...)``
        leaves ``traceback=None`` — this assertion is RED on current ``main``.
        A construction that raises the typed ``RateLimitError`` and routes it
        through ``ErrorDetail.from_exception`` populates the traceback, exactly
        like the generic-exception path already does.
        """

        async def mock_query(*, prompt="", options=None):
            yield _mock_rate_limit(status="rejected")

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            out = await ClaudeSDKBackend().execute(_envelope(), options=_options())

        assert out.error is not None
        assert out.error.traceback is not None, (
            "rate-limit ErrorDetail must be self-describing (typed → from_exception); "
            "bare-string construction leaves traceback=None"
        )

    async def test_rate_limit_message_preserved(self):
        """Behavior-preserving: the human-readable message still mentions the rate limit."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_rate_limit(status="rejected")

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            out = await ClaudeSDKBackend().execute(_envelope(), options=_options())

        assert out.error is not None
        assert "Rate limit" in out.error.message


# ---------------------------------------------------------------------------
# is_error=True — typed AgentError, self-describing ErrorDetail
# ---------------------------------------------------------------------------


@_NEEDS_SDK
class TestAgentErrorTypeSourced:
    """``ResultMessage.is_error=True`` produces a typed, self-describing detail."""

    async def test_agent_error_type_preserved(self):
        """Behavior-preserving anchor: the observable error_type stays 'AgentError'."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("partial output")
            yield _mock_result_message(is_error=True, errors=["tool refused"])

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            out = await ClaudeSDKBackend().execute(_envelope(), options=_options())

        assert out.status == TaskStatus.FAILED
        assert out.error is not None
        assert out.error.error_type == "AgentError"

    async def test_agent_error_detail_is_self_describing(self):
        """Type-sourced construction carries a populated traceback.

        RED on current ``main`` — the ``is_error`` branch builds a bare-string
        ``ErrorDetail(error_type="AgentError", ...)`` with ``traceback=None``.
        """

        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("partial output")
            yield _mock_result_message(is_error=True, errors=["tool refused"])

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            out = await ClaudeSDKBackend().execute(_envelope(), options=_options())

        assert out.error is not None
        assert out.error.traceback is not None, (
            "agent-error ErrorDetail must be self-describing (typed → from_exception); "
            "bare-string construction leaves traceback=None"
        )

    async def test_agent_error_message_preserved(self):
        """Behavior-preserving: the reported error list still flows into the message."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("partial output")
            yield _mock_result_message(is_error=True, errors=["tool refused"])

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            out = await ClaudeSDKBackend().execute(_envelope(), options=_options())

        assert out.error is not None
        assert "tool refused" in out.error.message

    async def test_agent_error_empty_errors_still_self_describing(self):
        """``is_error=True`` with empty ``errors`` still yields a typed, self-describing detail."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_result_message(is_error=True, errors=None, result="unhelpful output")

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            out = await ClaudeSDKBackend().execute(_envelope(), options=_options())

        assert out.status == TaskStatus.FAILED
        assert out.error is not None
        assert out.error.error_type == "AgentError"
        assert out.error.traceback is not None


# ---------------------------------------------------------------------------
# No bare-string ErrorDetail(error_type=...) literals remain in sdk_backend
# ---------------------------------------------------------------------------


class TestNoBareStringErrorTypeLiteralsInSdkBackend:
    """Mechanism proof: the source no longer hand-types these error_type strings.

    The defect is that ``error_type`` is a bare string literal passed to
    ``ErrorDetail(...)``. After the fix the values come from the typed
    taxonomy / ``from_exception``. We assert no ``ErrorDetail(...)`` call in
    ``sdk_backend.py`` carries a bare ``error_type="RateLimitError"`` /
    ``error_type="AgentError"`` literal anymore. This is a structural read of
    the source on disk — it FAILS on current ``main`` (both literals present)
    and passes once construction is type-sourced.
    """

    def _source(self) -> str:
        import bonfire.dispatch.sdk_backend as mod

        path = mod.__file__
        assert path is not None
        with open(path, encoding="utf-8") as fh:
            return fh.read()

    def test_no_bare_rate_limit_error_type_literal(self):
        src = self._source()
        assert 'error_type="RateLimitError"' not in src, (
            "sdk_backend still constructs ErrorDetail with a bare-string "
            'error_type="RateLimitError" — Phase 3 sources it from the typed '
            "RateLimitError class / ErrorDetail.from_exception"
        )

    def test_no_bare_agent_error_type_literal(self):
        src = self._source()
        assert 'error_type="AgentError"' not in src, (
            "sdk_backend still constructs ErrorDetail with a bare-string "
            'error_type="AgentError" — Phase 3 sources it from the typed '
            "AgentError class / ErrorDetail.from_exception"
        )
