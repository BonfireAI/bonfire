# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""ClaudeSDKBackend — wraps ``claude_agent_sdk.query()`` for agent execution.

Implements the ``AgentBackend`` protocol defined in ``bonfire.protocols``.
The backend NEVER raises — all exceptions become FAILED envelopes with
structured ``ErrorDetail``.

Two-method pattern: ``execute()`` wraps ``_do_execute()``, outer catches
everything.
"""

from __future__ import annotations

import logging
import os
import traceback as tb_module
from contextlib import aclosing
from typing import TYPE_CHECKING, Any

from bonfire.dispatch.security_hooks import _build_security_hooks_dict
from bonfire.models.envelope import Envelope, ErrorDetail

if TYPE_CHECKING:
    from collections.abc import Callable

    from bonfire.events.bus import EventBus
    from bonfire.protocols import DispatchOptions

# Deferred SDK import so tests work without SDK installed.
# Tests patch "bonfire.dispatch.sdk_backend.query".
try:
    from claude_agent_sdk import ClaudeAgentOptions, query  # type: ignore[import-untyped]
    from claude_agent_sdk.types import (  # type: ignore[import-untyped]
        AssistantMessage,
        HookMatcher,
        RateLimitEvent,
        ResultMessage,
    )
except ImportError:
    query = None  # type: ignore[assignment]
    ClaudeAgentOptions = None  # type: ignore[assignment,misc]
    AssistantMessage = None  # type: ignore[assignment]
    ResultMessage = None  # type: ignore[assignment]
    RateLimitEvent = None  # type: ignore[assignment]
    HookMatcher = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Traceback redaction
#
# Python tracebacks include local-frame ``repr`` data — for the SDK
# backend that means the envelope's ``task`` (the user prompt, often
# containing secrets) and the ``ClaudeAgentOptions`` (env-derived
# values). Persisting the full traceback to JSONL leaks those into
# on-disk logs. The default redaction emits a short single-frame
# summary; setting ``BONFIRE_DEBUG_TRACEBACKS=1`` restores the full
# multi-frame traceback for local debugging.
# ---------------------------------------------------------------------------

_TRACEBACK_DEBUG_ENV = "BONFIRE_DEBUG_TRACEBACKS"


def _summarise_traceback(exc: BaseException) -> str | None:
    """Return a single-line summary of *exc*'s deepest frame, or ``None``."""
    tb = exc.__traceback__
    if tb is None:
        return None
    while tb.tb_next is not None:
        tb = tb.tb_next
    frame = tb.tb_frame
    return f"{frame.f_code.co_filename}:{tb.tb_lineno}: {type(exc).__name__}: {exc}"


def _format_error_traceback(exc: BaseException) -> str | None:
    """Format *exc*'s traceback per the redaction policy.

    Returns the full ``traceback.format_exc()`` output if the
    ``BONFIRE_DEBUG_TRACEBACKS=1`` env var is set; otherwise returns a
    short single-frame summary (or ``None`` if no traceback exists).
    """
    if os.environ.get(_TRACEBACK_DEBUG_ENV) == "1":
        return tb_module.format_exc()
    return _summarise_traceback(exc)


def _map_thinking(depth: str) -> tuple[dict[str, Any], str]:
    """Map ``thinking_depth`` to SDK thinking config and effort level."""
    mapping: dict[str, tuple[dict[str, Any], str]] = {
        "minimal": ({"type": "disabled"}, "low"),
        "standard": ({"type": "adaptive"}, "medium"),
        "thorough": ({"type": "adaptive"}, "high"),
        "ultrathink": ({"type": "enabled", "budget_tokens": 10000}, "max"),
    }
    return mapping.get(depth, ({"type": "adaptive"}, "medium"))


class ClaudeSDKBackend:
    """Backend that dispatches work through the Claude Agent SDK.

    Implements the ``AgentBackend`` protocol (``bonfire.protocols``).
    All SDK-specific logic is contained here.
    """

    def __init__(
        self,
        *,
        compiler: Any | None = None,
        bus: EventBus | None = None,
    ) -> None:
        self._compiler = compiler
        self._bus = bus

    async def execute(
        self,
        envelope: Envelope,
        *,
        options: DispatchOptions,
        on_stream: Callable[[str], None] | None = None,
    ) -> Envelope:
        """Execute via ``claude_agent_sdk.query()``, returning an Envelope.

        Never raises. All exceptions become FAILED envelopes.
        """
        try:
            return await self._do_execute(envelope, options=options, on_stream=on_stream)
        except Exception as exc:
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    traceback=_format_error_traceback(exc),
                )
            )

    async def _do_execute(
        self,
        envelope: Envelope,
        *,
        options: DispatchOptions,
        on_stream: Callable[[str], None] | None = None,
    ) -> Envelope:
        """Internal execution — may raise; caller catches."""
        # Map thinking depth
        thinking_config, effort_level = _map_thinking(options.thinking_depth)

        # Build SDK options — stderr callback captures CLI diagnostics on crash
        agent_options = ClaudeAgentOptions(
            model=options.model,
            max_turns=options.max_turns,
            max_budget_usd=options.max_budget_usd,
            cwd=options.cwd or None,
            permission_mode=options.permission_mode,
            tools=list(options.tools),
            allowed_tools=options.tools,
            hooks=_build_security_hooks_dict(
                options.security_hooks,
                bus=self._bus,
                envelope=envelope,
            ),
            setting_sources=["project"],
            thinking=thinking_config,
            effort=effort_level,
            stderr=lambda line: logger.warning("[CLI stderr] %s", line),
        )

        # query() is an async generator — iterate, do NOT await.
        # Wrap in aclosing() to ensure cleanup on early return (e.g. rate limit).
        message_stream = query(prompt=envelope.task, options=agent_options)

        text_parts: list[str] = []
        cost_usd: float = 0.0
        duration_seconds: float = 0.0
        session_id: str | None = None
        result_msg_text: str = ""
        is_error: bool = False
        errors: list[str] | None = None

        async with aclosing(message_stream) as stream:
            async for msg in stream:
                if AssistantMessage is not None and isinstance(msg, AssistantMessage):
                    for block in getattr(msg, "content", []):
                        block_text = getattr(block, "text", None)
                        if block_text:
                            text_parts.append(block_text)
                            if on_stream is not None:
                                on_stream(block_text)

                elif ResultMessage is not None and isinstance(msg, ResultMessage):
                    cost_usd = getattr(msg, "total_cost_usd", None) or 0.0
                    duration_ms = getattr(msg, "duration_ms", 0) or 0
                    duration_seconds = duration_ms / 1000.0
                    session_id = getattr(msg, "session_id", None)
                    result_msg_text = getattr(msg, "result", None) or ""
                    is_error = getattr(msg, "is_error", False)
                    errors = getattr(msg, "errors", None)

                elif RateLimitEvent is not None and isinstance(msg, RateLimitEvent):
                    status = getattr(msg, "status", "")
                    if status == "rejected":
                        return envelope.with_error(
                            ErrorDetail(
                                error_type="RateLimitError",
                                message="Rate limit exceeded — request rejected by API",
                            )
                        )
                    elif status == "allowed_warning":
                        logger.warning("Rate limit warning: approaching limit")

        final_text = "".join(text_parts)
        # Fallback: use ResultMessage.result if no text from assistant messages
        if not final_text and result_msg_text:
            final_text = result_msg_text

        # Check is_error flag from ResultMessage
        if is_error:
            error_msgs = [str(e) for e in errors] if errors else []
            return envelope.with_error(
                ErrorDetail(
                    error_type="AgentError",
                    message=(
                        "; ".join(error_msgs)
                        if error_msgs
                        else (final_text or "Agent reported error")
                    ),
                )
            )

        # Success path — set duration + session_id metadata then enrich with result.
        enriched = envelope.with_result(result=final_text, cost_usd=cost_usd)
        return enriched.model_copy(
            update={
                "metadata": {
                    **enriched.metadata,
                    "duration_seconds": duration_seconds,
                    "session_id": session_id,
                },
            },
        )

    async def health_check(self) -> bool:
        """Check if the Claude Agent SDK is available."""
        return query is not None
