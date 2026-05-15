"""RED contract for SDK backend traceback redaction.

Subject: ``bonfire.dispatch.sdk_backend.ClaudeSDKBackend.execute`` catches
all exceptions in ``_do_execute`` and stores the full
``traceback.format_exc()`` into ``ErrorDetail.traceback``. Python
tracebacks include local-frame ``repr`` — which in this context
includes the envelope's ``task`` (the prompt; often containing user
secrets), ``ClaudeAgentOptions`` (which carries env-derived values),
and other local variables. These are persisted as JSONL via
``SessionPersistence.append_event``, leaking sensitive data into
on-disk logs.

This file pins down:

  1. **Default redaction**: the captured ``error.traceback`` MUST NOT
     contain any literal substring from the envelope's ``task``. A
     short single-frame summary (or ``None``) is acceptable.
  2. **Debug opt-in**: setting ``BONFIRE_DEBUG_TRACEBACKS=1`` in env
     restores the full multi-frame traceback.
  3. **error_type and message** still populate correctly in both
     modes — the redaction only affects the ``traceback`` field.

The Warrior chooses the redaction shape (``None`` vs single-frame
summary); the contract is "the prompt is not in the traceback by
default".
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
    if _IMPORT_ERROR is not None:  # pragma: no cover
        pytest.fail(f"bonfire.dispatch.sdk_backend not importable: {_IMPORT_ERROR}")


_SECRET = "secret-token-XYZ"  # nosec — intentional test fixture
_TASK_WITH_SECRET = f"Use this credential: {_SECRET} and process the request."


def _envelope_with_secret() -> Envelope:
    return Envelope(
        task=_TASK_WITH_SECRET,
        agent_name="warrior-agent",
        model="claude-opus-4-7",
    )


class _FakeClaudeAgentOptions:
    """Stand-in for ``ClaudeAgentOptions`` — captures kwargs verbatim."""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


async def _raising_query(*, prompt: str = "", options: Any = None):  # type: ignore[no-untyped-def]
    """Async generator that raises with a generic message before yielding."""
    raise RuntimeError("backend crash for redaction test")
    if False:  # pragma: no cover — keeps the function an async generator
        yield None


# ---------------------------------------------------------------------------
# 1. Default redaction — prompt MUST NOT appear in the captured traceback.
# ---------------------------------------------------------------------------


class TestDefaultRedaction:
    """By default, the prompt is not in the persisted traceback."""

    async def test_default_traceback_does_not_contain_prompt_text(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Default behavior: the literal prompt text MUST NOT be in error.traceback."""
        monkeypatch.delenv("BONFIRE_DEBUG_TRACEBACKS", raising=False)

        with (
            patch(
                "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
                _FakeClaudeAgentOptions,
            ),
            patch("bonfire.dispatch.sdk_backend.query", _raising_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])
            result = await backend.execute(_envelope_with_secret(), options=options)

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        tb = result.error.traceback or ""
        assert _SECRET not in tb, (
            f"Secret token leaked into the default error.traceback. "
            f"This is the redaction contract. traceback={tb!r}"
        )
        assert _TASK_WITH_SECRET not in tb, (
            f"Full prompt body leaked into the default error.traceback. traceback={tb!r}"
        )

    async def test_default_traceback_is_short_or_none(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Default traceback is ``None`` or a short single-frame summary.

        Single-frame summary heuristic: at most a handful of lines —
        the multi-frame ``traceback.format_exc()`` output is dozens of
        lines on real frames. We pin "small" rather than an exact line
        count so the Warrior can pick the summary format.
        """
        monkeypatch.delenv("BONFIRE_DEBUG_TRACEBACKS", raising=False)

        with (
            patch(
                "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
                _FakeClaudeAgentOptions,
            ),
            patch("bonfire.dispatch.sdk_backend.query", _raising_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])
            result = await backend.execute(_envelope_with_secret(), options=options)

        assert result.error is not None
        tb = result.error.traceback
        if tb is None:
            return  # ``None`` is the most aggressive redaction shape.
        # Otherwise, the summary should be short — far less than the
        # full multi-frame traceback.format_exc() output, which is
        # typically 15+ lines on a non-trivial frame stack.
        line_count = tb.count("\n") + 1
        assert line_count <= 4, (
            f"Default traceback should be a short single-frame summary "
            f"(<= 4 lines) or None. Got {line_count} lines: {tb!r}"
        )


# ---------------------------------------------------------------------------
# 2. Debug opt-in — multi-frame traceback restored.
# ---------------------------------------------------------------------------


class TestDebugOptIn:
    """``BONFIRE_DEBUG_TRACEBACKS=1`` restores the full traceback."""

    async def test_debug_env_var_restores_full_traceback(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With debug env set, traceback is multi-frame text."""
        monkeypatch.setenv("BONFIRE_DEBUG_TRACEBACKS", "1")

        with (
            patch(
                "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
                _FakeClaudeAgentOptions,
            ),
            patch("bonfire.dispatch.sdk_backend.query", _raising_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])
            result = await backend.execute(_envelope_with_secret(), options=options)

        assert result.error is not None
        tb = result.error.traceback
        assert tb is not None, "debug mode must produce a traceback string"
        # Traceback formatting always starts with "Traceback (most recent call last):"
        assert "Traceback" in tb, f"Debug-mode traceback should be standard format. Got: {tb!r}"
        # And it should span multiple frames (lots of lines).
        line_count = tb.count("\n") + 1
        assert line_count >= 5, (
            f"Debug-mode traceback should be multi-frame. Got {line_count} lines: {tb!r}"
        )


# ---------------------------------------------------------------------------
# 3. error_type and message still populated in BOTH modes.
# ---------------------------------------------------------------------------


class TestErrorTypeAndMessagePreserved:
    """The structural error fields stay populated regardless of mode."""

    async def test_default_mode_populates_error_type_and_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``error_type`` is the exception class name; ``message`` is its str()."""
        monkeypatch.delenv("BONFIRE_DEBUG_TRACEBACKS", raising=False)

        with (
            patch(
                "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
                _FakeClaudeAgentOptions,
            ),
            patch("bonfire.dispatch.sdk_backend.query", _raising_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])
            result = await backend.execute(_envelope_with_secret(), options=options)

        assert result.error is not None
        assert result.error.error_type == "RuntimeError"
        assert result.error.message == "backend crash for redaction test"

    async def test_debug_mode_populates_error_type_and_message(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Same identity contract under debug mode."""
        monkeypatch.setenv("BONFIRE_DEBUG_TRACEBACKS", "1")

        with (
            patch(
                "bonfire.dispatch.sdk_backend.ClaudeAgentOptions",
                _FakeClaudeAgentOptions,
            ),
            patch("bonfire.dispatch.sdk_backend.query", _raising_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(tools=["Read"])
            result = await backend.execute(_envelope_with_secret(), options=options)

        assert result.error is not None
        assert result.error.error_type == "RuntimeError"
        assert result.error.message == "backend crash for redaction test"
