"""Agent execution with retry, timeout, and tier gating.

This package owns the seam between Bonfire's stages and the underlying
LLM runtimes. It ships two interchangeable :class:`AgentBackend`
implementations — :class:`ClaudeSDKBackend` (the default, talking to
the official Claude Agent SDK with the pre-exec security hook wired
in) and :class:`PydanticAIBackend` (a Pydantic-AI-based alternative
for callers who prefer that ecosystem).

Both backends are driven through :func:`execute_with_retry`, which
applies the bounded retry/timeout policy, and gated by
:class:`TierGate`, which enforces per-tier dispatch quotas before
calls reach the network.
"""

from bonfire.dispatch.pydantic_ai_backend import PydanticAIBackend
from bonfire.dispatch.result import DispatchResult
from bonfire.dispatch.runner import execute_with_retry
from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
from bonfire.dispatch.tier import TierGate

__all__ = [
    "ClaudeSDKBackend",
    "DispatchResult",
    "PydanticAIBackend",
    "TierGate",
    "execute_with_retry",
]
