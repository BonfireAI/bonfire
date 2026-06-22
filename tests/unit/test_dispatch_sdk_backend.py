"""RED tests for ``bonfire.dispatch.sdk_backend`` — W3.2 Claude SDK backend.

Canonical Sage synthesis of Knight-A (resilience) + Knight-B (fidelity).
``ClaudeSDKBackend`` wraps ``claude_agent_sdk.query()`` behind Bonfire's
``AgentBackend`` protocol. It is the single exit point from Bonfire's
world into the Claude Agent SDK, and the ONLY backend allowed to raise
inside its internal body — the outer ``execute()`` converts every
exception into a FAILED envelope with structured ``ErrorDetail``.

Invariants locked
~~~~~~~~~~~~~~~~~
* **Never raises.** Any exception from the SDK query generator becomes a
  FAILED envelope with ``ErrorDetail.error_type`` = exception class name.
* **Traceback captured.** ``ErrorDetail.traceback`` is populated on
  exception (crash-recovery triage depends on it).
* **Rate-limit rejection.** ``RateLimitEvent(status='rejected')`` →
  ``error_type='RateLimitError'`` (triggers terminal-no-retry in runner).
* **Rate-limit warning.** ``allowed_warning`` status is log-only — must
  NOT fail the dispatch.
* **``is_error=True`` on ResultMessage** → ``error_type='AgentError'``.
* **Text accumulation.** Multiple ``AssistantMessage`` text blocks
  concatenate in order; falls back to ``ResultMessage.result`` when no
  assistant text seen.
* **Cost from ResultMessage.** ``total_cost_usd`` flows to envelope
  ``cost_usd``. ``None`` becomes ``0.0``.
* **Duration + session_id in metadata.** ``duration_ms / 1000`` and
  ``session_id`` land in ``envelope.metadata``.
* **``on_stream`` callback.** Assistant-text chunks invoke the optional
  callback exactly once per block; ``on_stream=None`` is safe.
* **``_map_thinking``.** Maps ``thinking_depth`` Literal → ``(config, effort)``.
* **health_check.** Returns ``True`` when SDK ``query`` is a callable,
  ``False`` when module-level ``query`` symbol is ``None`` (import failed).
* **Protocol conformance.** ``isinstance(backend, AgentBackend)`` at runtime.
* **``compiler=None`` constructor.** Default is no-compiler (public v0.1
  does not ship the prompt compiler yet).

Mock strategy: SDK message types are patched via ``unittest.mock.patch`` so
tests run without the real SDK installed. When the SDK IS installed,
``spec=`` is used on MagicMocks so ``isinstance`` matches the real types.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.protocols import AgentBackend, DispatchOptions

# Try importing real SDK types for ``spec=`` mocking (isinstance compat).
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
except ImportError:
    _AssistantMessage = None  # type: ignore[assignment,misc]
    _ResultMessage = None  # type: ignore[assignment,misc]
    _RateLimitEvent = None  # type: ignore[assignment,misc]
    _HAS_SDK_TYPES = False


try:
    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend, _map_thinking
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    ClaudeSDKBackend = None  # type: ignore[assignment,misc]
    _map_thinking = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test while bonfire.dispatch.sdk_backend is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.sdk_backend not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# SDK mock helpers
# ---------------------------------------------------------------------------


def _mock_assistant_message(text: str) -> MagicMock:
    """Mimic ``claude_agent_sdk.types.AssistantMessage`` with one text block."""
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


# ---------------------------------------------------------------------------
# Imports + protocol conformance
# ---------------------------------------------------------------------------


class TestSDKBackendImports:
    """Canonical and convenience imports resolve."""

    def test_import_claude_sdk_backend(self):
        from bonfire.dispatch.sdk_backend import ClaudeSDKBackend as _CSB

        assert _CSB is not None

    def test_import_map_thinking(self):
        from bonfire.dispatch.sdk_backend import _map_thinking as _fn

        assert _fn is not None

    def test_construct_with_no_args(self):
        backend = ClaudeSDKBackend()
        assert backend is not None

    def test_construct_with_none_compiler(self):
        """``compiler=None`` is the public v0.1 default — no prompt compiler yet."""
        backend = ClaudeSDKBackend(compiler=None)
        assert backend is not None


class TestSDKBackendProtocol:
    """The SDK backend must satisfy ``AgentBackend`` (``@runtime_checkable``)."""

    def test_satisfies_agent_backend_protocol(self):
        backend = ClaudeSDKBackend()
        assert isinstance(backend, AgentBackend)


# ---------------------------------------------------------------------------
# Never-raise contract
# ---------------------------------------------------------------------------


class TestNeverRaises:
    """Every exception from the SDK must become a FAILED envelope."""

    async def test_generic_exception_becomes_failed_envelope(self):
        async def mock_query(*, prompt="", options=None):
            raise RuntimeError("pipe closed")
            yield  # pragma: no cover — unreachable

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            result = await backend.execute(_envelope(), options=_options())

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert "pipe closed" in result.error.message

    async def test_error_detail_captures_exception_class_name(self):
        """``error_type`` must be the exception's class ``__name__`` — not ``str(exc)``."""

        class MyCustomError(Exception):
            pass

        async def mock_query(*, prompt="", options=None):
            raise MyCustomError("whatever")
            yield  # pragma: no cover

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            result = await backend.execute(_envelope(), options=_options())

        assert result.error is not None
        assert result.error.error_type == "MyCustomError"

    async def test_error_detail_captures_traceback(self):
        """A traceback string must be attached for crash-recovery triage."""

        async def mock_query(*, prompt="", options=None):
            raise ValueError("deep inside")
            yield  # pragma: no cover

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            result = await backend.execute(_envelope(), options=_options())

        assert result.error is not None
        assert result.error.traceback is not None
        assert "ValueError" in result.error.traceback


# ---------------------------------------------------------------------------
# Success path — text accumulation, cost, metadata
# ---------------------------------------------------------------------------


class TestSuccessPath:
    """Normal completion — assistant text, cost, metadata."""

    async def test_single_assistant_message_text_captured(self):
        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("hello world")
            yield _mock_result_message(total_cost_usd=0.05)

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.status == TaskStatus.COMPLETED
        assert out.result == "hello world"
        assert out.cost_usd == pytest.approx(0.05)

    async def test_text_blocks_accumulate_in_order(self):
        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("one ")
            yield _mock_assistant_message("two ")
            yield _mock_assistant_message("three")
            yield _mock_result_message(total_cost_usd=0.02)

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.result == "one two three"

    async def test_none_cost_becomes_zero(self):
        """SDK's ``total_cost_usd`` can be ``None`` — must default to 0.0."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("ok")
            yield _mock_result_message(total_cost_usd=None)

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.cost_usd == 0.0
        assert out.status == TaskStatus.COMPLETED

    async def test_empty_text_falls_back_to_result_message_text(self):
        """No AssistantMessage content — fall back to ``ResultMessage.result``."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_result_message(total_cost_usd=0.01, result="fallback content")

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.result == "fallback content"
        assert out.status == TaskStatus.COMPLETED

    async def test_duration_and_session_id_in_metadata(self):
        """``duration_ms / 1000`` and ``session_id`` land in envelope metadata."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("done")
            yield _mock_result_message(total_cost_usd=0.42, duration_ms=3500, session_id="s-99")

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.cost_usd == pytest.approx(0.42)
        assert out.metadata["duration_seconds"] == pytest.approx(3.5)
        assert out.metadata["session_id"] == "s-99"


# ---------------------------------------------------------------------------
# Rate-limit handling
# ---------------------------------------------------------------------------


class TestRateLimit:
    """RateLimitEvent(status='rejected') → RateLimitError FAILED envelope."""

    async def test_rate_limit_rejected_becomes_failed(self):
        async def mock_query(*, prompt="", options=None):
            yield _mock_rate_limit(status="rejected")

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.status == TaskStatus.FAILED
        assert out.error is not None
        assert out.error.error_type == "RateLimitError"
        assert "Rate limit" in out.error.message

    async def test_rate_limit_warning_does_not_fail(self):
        """``allowed_warning`` status is a log-only event — must NOT fail."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_rate_limit(status="allowed_warning")
            yield _mock_assistant_message("ok")
            yield _mock_result_message(total_cost_usd=0.01)

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# is_error=True on ResultMessage
# ---------------------------------------------------------------------------


class TestAgentError:
    """``ResultMessage.is_error=True`` → AgentError FAILED envelope."""

    async def test_is_error_becomes_agent_error(self):
        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("partial output")
            yield _mock_result_message(is_error=True, errors=["tool refused"])

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.status == TaskStatus.FAILED
        assert out.error is not None
        assert out.error.error_type == "AgentError"
        assert "tool refused" in out.error.message

    async def test_is_error_with_no_error_list_still_fails(self):
        """``is_error=True`` but empty ``errors`` — fall back to a useful message."""

        async def mock_query(*, prompt="", options=None):
            yield _mock_result_message(is_error=True, errors=None, result="unhelpful output")

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options())

        assert out.status == TaskStatus.FAILED
        assert out.error is not None
        assert out.error.error_type == "AgentError"


# ---------------------------------------------------------------------------
# on_stream callback
# ---------------------------------------------------------------------------


class TestOnStream:
    """Optional ``on_stream`` callback fires per AssistantMessage text block."""

    async def test_on_stream_invoked_per_text_block(self):
        collected: list[str] = []

        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("alpha")
            yield _mock_assistant_message("beta")
            yield _mock_result_message(total_cost_usd=0.01)

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            await backend.execute(_envelope(), options=_options(), on_stream=collected.append)

        assert collected == ["alpha", "beta"]

    async def test_on_stream_none_does_not_crash(self):
        async def mock_query(*, prompt="", options=None):
            yield _mock_assistant_message("content")
            yield _mock_result_message(total_cost_usd=0.01)

        with patch("bonfire.dispatch.sdk_backend.query", side_effect=mock_query):
            backend = ClaudeSDKBackend()
            out = await backend.execute(_envelope(), options=_options(), on_stream=None)

        assert out.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """health_check reflects whether the SDK ``query`` symbol was imported."""

    async def test_health_check_true_when_sdk_importable(self):
        """When ``query`` is a valid callable, ``health_check`` is ``True``."""
        backend = ClaudeSDKBackend()
        with patch("bonfire.dispatch.sdk_backend.query", lambda **_kw: None):
            assert await backend.health_check() is True

    async def test_health_check_false_when_sdk_missing(self):
        """When ``query`` is ``None`` (import failed), ``health_check`` is ``False``."""
        backend = ClaudeSDKBackend()
        with patch("bonfire.dispatch.sdk_backend.query", None):
            assert await backend.health_check() is False


# ---------------------------------------------------------------------------
# _map_thinking — thinking_depth → (config, effort)
# ---------------------------------------------------------------------------


class TestMapThinking:
    """``_map_thinking`` maps ``thinking_depth`` to SDK thinking config + effort."""

    def test_minimal(self):
        config, effort = _map_thinking("minimal")
        assert config == {"type": "disabled"}
        assert effort == "low"

    def test_standard(self):
        config, effort = _map_thinking("standard")
        assert config == {"type": "adaptive"}
        assert effort == "medium"

    def test_thorough(self):
        config, effort = _map_thinking("thorough")
        assert config == {"type": "adaptive"}
        assert effort == "high"

    def test_ultrathink(self):
        config, effort = _map_thinking("ultrathink")
        assert config == {"type": "enabled", "budget_tokens": 10000}
        assert effort == "max"

    def test_unknown_defaults_to_standard(self):
        """Unknown depth strings fall back to the ``standard`` mapping."""
        config, effort = _map_thinking("bogus")
        assert config == {"type": "adaptive"}
        assert effort == "medium"

    def test_returns_tuple_of_dict_and_str(self):
        """Shape contract: ``(dict, str)``."""
        config, effort = _map_thinking("standard")
        assert isinstance(config, dict)
        assert isinstance(effort, str)
