# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Extension point protocols for Bonfire's pluggable architecture.

This module defines the four core protocols that third-party code (and Bonfire's
own default backends) must satisfy.  Every protocol is ``@runtime_checkable``
so the composition root can verify conformance at registration time.

Two supporting value types -- :class:`DispatchOptions` and :class:`VaultEntry` --
travel alongside the protocols as structured data that crosses protocol
boundaries.

Design constraints
~~~~~~~~~~~~~~~~~~
*   All protocols are ``@runtime_checkable``.
*   No ABCs.  ``typing.Protocol`` gives structural subtyping.
*   Only ``bonfire.models`` may be imported (via TYPE_CHECKING).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

# Pydantic requires the runtime type for validation — keep this import
# outside of TYPE_CHECKING.
from bonfire.dispatch.security_hooks import SecurityHooksConfig

if TYPE_CHECKING:
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import GateContext, GateResult, StageSpec

__all__ = [
    "AgentBackend",
    "DispatchOptions",
    "QualityGate",
    "StageHandler",
    "VaultBackend",
    "VaultEntry",
]

# ---------------------------------------------------------------------------
# Supporting value types
# ---------------------------------------------------------------------------


def _vault_entry_id() -> str:
    return uuid4().hex[:12]


class DispatchOptions(BaseModel):
    """Tuning knobs passed alongside every agent dispatch.

    Every field has a sensible default so callers only specify what they want
    to override.  Frozen to prevent accidental mutation after dispatch.
    """

    model_config = ConfigDict(frozen=True)

    model: str = ""
    max_turns: int = 10
    max_budget_usd: float = 0.0

    # Cognitive extensions
    thinking_depth: Literal["minimal", "standard", "thorough", "ultrathink"] = "standard"
    cognitive_mode: str = ""

    # Agent isolation
    tools: list[str] = Field(default_factory=list)
    cwd: str = ""
    permission_mode: str = "default"
    role: str = Field(default="", strict=True)

    # Security hook policy
    security_hooks: SecurityHooksConfig = Field(default_factory=SecurityHooksConfig)


class VaultEntry(BaseModel):
    """A single record stored in or retrieved from the Vault.

    ``entry_id`` is auto-generated when omitted so callers creating new
    entries don't need to supply one.  Provenance, dedup, and semantic-search
    fields round out the schema.
    """

    model_config = ConfigDict(frozen=True)

    # Identity
    entry_id: str = Field(default_factory=_vault_entry_id)
    content: str
    entry_type: str

    # Provenance
    source_path: str = ""
    project_name: str = ""
    scanned_at: str = ""
    git_hash: str = ""

    # Dedup + search
    content_hash: str = ""
    tags: list[str] = Field(default_factory=list)

    # Extensible
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class AgentBackend(Protocol):
    """Contract for LLM agent execution backends.

    Bonfire ships a default Claude-SDK backend, but any provider that speaks
    envelope-in, envelope-out can be plugged in.
    """

    async def execute(
        self,
        envelope: Envelope,
        *,
        options: DispatchOptions,
    ) -> Envelope:
        """Run a single agent turn and return the enriched envelope."""
        ...

    async def health_check(self) -> bool:
        """Return ``True`` if the backend is reachable and ready."""
        ...


@runtime_checkable
class VaultBackend(Protocol):
    """Contract for persistent knowledge storage.

    The Vault is Bonfire's long-term memory: scout reports, code artifacts,
    session logs, and anything the pipeline wants to remember across runs.
    Embedding is handled internally by the backend -- callers pass text,
    never vectors.
    """

    async def store(self, entry: VaultEntry) -> str:
        """Persist *entry* and return its ``entry_id``."""
        ...

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        entry_type: str | None = None,
    ) -> list[VaultEntry]:
        """Retrieve up to *limit* entries matching *query*.

        If *entry_type* is given, only entries of that type are returned.
        """
        ...

    async def exists(self, content_hash: str) -> bool:
        """Return ``True`` if an entry with *content_hash* is already stored."""
        ...

    async def get_by_source(self, source_path: str) -> list[VaultEntry]:
        """Return all entries originating from *source_path*."""
        ...


@runtime_checkable
class QualityGate(Protocol):
    """Contract for pass/fail quality checks between pipeline stages.

    Gates inspect an envelope after a stage completes and decide whether
    the pipeline should proceed, retry, or abort.
    """

    async def evaluate(
        self,
        envelope: Envelope,
        context: GateContext,
    ) -> GateResult:
        """Evaluate the envelope against this gate's criteria."""
        ...


@runtime_checkable
class StageHandler(Protocol):
    """Contract for custom pipeline stage logic.

    Most stages dispatch to an :class:`AgentBackend`, but some need bespoke
    orchestration -- parallel fan-out, human-in-the-loop, external APIs.
    """

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Execute the stage and return the resulting envelope."""
        ...
