# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Agent execution with retry, timeout, and tier gating.

This package owns the seam between Bonfire's stages and the underlying
LLM runtimes. It ships two interchangeable :class:`AgentBackend`
implementations — :class:`ClaudeSDKBackend` (the default, talking to
the official Claude Agent SDK with the pre-exec security hook wired
in) and :class:`PydanticAIBackend` (a Pydantic-AI-based alternative
for callers who prefer that ecosystem).

Both backends are driven through :func:`execute_with_retry`, which
applies the bounded retry/timeout policy. :class:`TierGate` is the
no-op stub for the per-tier dispatch contract — every check returns
``True`` in v0.1; quota enforcement is a future concern.

Trust-Triangle user-facing config types are re-exported here for
discoverability: :class:`ToolPolicy` / :class:`DefaultToolPolicy`
(W4.1 — per-role tool allow-lists) and :class:`SecurityHooksConfig`
(W4.2 — pre-exec security hook policy).
"""

from bonfire.dispatch.pydantic_ai_backend import PydanticAIBackend
from bonfire.dispatch.result import DispatchResult
from bonfire.dispatch.runner import execute_with_retry
from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
from bonfire.dispatch.security_hooks import SecurityHooksConfig
from bonfire.dispatch.tier import TierGate
from bonfire.dispatch.tool_policy import DefaultToolPolicy, ToolPolicy

__all__ = [
    "ClaudeSDKBackend",
    "DefaultToolPolicy",
    "DispatchResult",
    "PydanticAIBackend",
    "SecurityHooksConfig",
    "TierGate",
    "ToolPolicy",
    "execute_with_retry",
]
