# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Extension point protocols for Bonfire's pluggable architecture.

This module defines the four core protocols that third-party code (and Bonfire's
own default backends) must satisfy.  Every protocol is ``@runtime_checkable``
so the composition root can verify conformance at registration time.

Two supporting value types -- :class:`DispatchOptions` and :class:`VaultEntry` --
travel alongside the protocols as structured data that crosses protocol
boundaries.

The Verdict envelope family (:class:`Verdict`, :class:`VerdictStatus`,
:class:`Severity`, :class:`Finding`, :class:`MuscleWriteReceipt`) is the
Inquisitor's wire-level output, vendor-mirrored from the canonical forge-side
schema. The module-level constant :data:`SCHEMA_VERSION` MUST match the
forge-side string in lockstep; the parity test
``tests/test_verdict_parity.py`` enforces this.

Design constraints
~~~~~~~~~~~~~~~~~~
*   All protocols are ``@runtime_checkable``.
*   No ABCs.  ``typing.Protocol`` gives structural subtyping.
*   Only ``bonfire.models`` may be imported (via TYPE_CHECKING).
"""

from __future__ import annotations

from enum import StrEnum
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
    "ContextAtom",
    "DispatchOptions",
    "Finding",
    "MuscleWriteReceipt",
    "QualityGate",
    "RetrievalProvider",
    "SCHEMA_VERSION",
    "Severity",
    "StageHandler",
    "VaultBackend",
    "VaultEntry",
    "Verdict",
    "VerdictStatus",
]


# ---------------------------------------------------------------------------
# Verdict envelope family (vendor-port from forge-side)
# ---------------------------------------------------------------------------

SCHEMA_VERSION = "1.1"
"""Verdict family schema version pin.

MUST match the string in ``ishtar/forge/core/verdict.py``. The parity
test ``tests/test_verdict_parity.py`` enforces lockstep equality at CI
time. Bump in lockstep on any additive shape change to
:class:`Verdict` / :class:`VerdictStatus` / :class:`Severity` /
:class:`Finding` / :class:`MuscleWriteReceipt`.
"""


class Severity(StrEnum):
    """Aligned with the Sage REVIEW taxonomy."""

    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"
    INFO = "INFO"


class VerdictStatus(StrEnum):
    """Tiered output of the Inquisitor's judgment."""

    PASS = "PASS"
    CONCERNS = "CONCERNS"
    FAIL = "FAIL"


class Finding(BaseModel):
    """A single concern or defect surfaced by the Inquisitor.

    Consumed by Linear ticket templating (the ``proposed_action`` field
    drives the auto-file body) and the Deck dashboard's CONCERNS panels.
    """

    model_config = ConfigDict(use_enum_values=False)

    severity: Severity = Field(description="Severity per Sage REVIEW taxonomy")
    title: str = Field(description="Short label, ticket-title-shaped")
    rationale: str = Field(description="One-paragraph WHY")
    artifacts: list[str] = Field(
        default_factory=list, description="File paths / output IDs implicated"
    )
    proposed_action: str | None = Field(
        default=None,
        description="For downstream auto-Linear-templating; None if no obvious action",
    )
    related_lexicon: list[str] = Field(
        default_factory=list,
        description="Keys of relevant prior Lexicon entries",
    )


class MuscleWriteReceipt(BaseModel):
    """Provenance for a single muscle-memory write made by this verdict.

    Lets Mirror calibration trace verdicts → writes → impact on next
    Architect's read.
    """

    model_config = ConfigDict(use_enum_values=False)

    key: str
    project: str
    operation: Literal["write", "supersede", "skip-existing"]
    superseded_keys: list[str] = Field(
        default_factory=list,
        description="Keys superseded by this write (operation=='supersede')",
    )


class Verdict(BaseModel):
    """The Inquisitor's complete output.

    Wire-level object. Persisted as part of the run record. Read by the
    runtime (effectuate / hold / terminate), the Deck (visualization), and
    Mirror calibration (cross-run analytics).
    """

    model_config = ConfigDict(use_enum_values=False)

    status: VerdictStatus
    rationale: str = Field(description="One-paragraph WHY at verdict level")
    findings: list[Finding] = Field(default_factory=list)
    muscle_writes: list[MuscleWriteReceipt] = Field(default_factory=list)

    # Provenance
    run_id: str = Field(description="Unique identifier for this pipeline run")
    pipeline_summary: str = Field(
        description="One-line: 'scout->knight->...->steward, N stages, K sage-bounces'"
    )
    inquisitor_started_at: str = Field(description="ISO-8601 UTC")
    inquisitor_completed_at: str = Field(description="ISO-8601 UTC")
    cost_usd: float = Field(description="What this judgment cost")

    # Failure-mode
    default_concerns: bool = Field(
        default=False,
        description="True iff CONCERNS via fallback path (crash / timeout / etc.)",
    )
    diagnostic: str | None = Field(
        default=None,
        description="One-sentence reason; populated when default_concerns=True",
    )

    # Prompt-construction provenance — chain-level truncation flag.
    # Set True when the closed envelope chain exceeded ``max_chain_chars``
    # at injection-build time and the handler dropped middle stages to
    # bound the agent's context window. Mirror calibration uses this flag
    # to detect truncation-induced default-CONCERNS at scale; the runtime
    # surfaces it on the Deck so operators can spot pipelines that
    # routinely spill the budget and need staged-summarization upstream.
    chain_truncated: bool = Field(
        default=False,
        description=(
            "True iff the input envelope chain exceeded `max_chain_chars` "
            "and the handler dropped middle stages at injection-build time"
        ),
    )

    # Bookend-payload truncation flag — disaggregated from the chain-
    # level drop-middle path. When bookend stages alone exceed
    # ``max_chain_chars`` (e.g., a 60KB Scout + 40KB Steward on an
    # 80KB budget), the drop-middle strategy keeps both bookends and
    # would surface ``chain_truncated=True`` without ACTUALLY bounding
    # the injection. "Looks bounded, isn't bounded" — worst-kind
    # misleading signal. The handler closes this by truncating the
    # longer bookend's PAYLOAD (head+tail with marker) at injection-
    # build time; the bookend stage itself survives so chain causality
    # is preserved. This flag surfaces the per-payload truncation
    # distinctly from the chain-level drop-middle (``chain_truncated``)
    # so Mirror calibration can disaggregate the two truncation modes.
    chain_truncated_bookend: bool = Field(
        default=False,
        description=(
            "True iff a bookend stage's payload was head+tail truncated "
            "at injection-build time because bookends alone exceeded "
            "`max_chain_chars`"
        ),
    )

    # Loremaster bracket-seam observability fields. The Inquisitor→
    # Loremaster dispatch wiring landed without report-back; Mirror
    # calibration was left blind to bracket-seam failures (e.g., a
    # Lexicon outage trips mid-cluster-walk, the Loremaster surfaces a
    # default-no-promotion report — but the Verdict shows no sign of
    # either the attempt or the failure).
    #
    # These fields close the report-back loop. Backward-compat defaults
    # let existing callers (callers that haven't wired the bracket yet)
    # continue to receive Verdicts shaped the way they always were.
    # ``loremaster_report`` is typed ``Any`` rather than
    # ``LoremasterReport`` to avoid a circular import: the Loremaster
    # handler module already imports from this file (for
    # ``MuscleWriteReceipt``). Downstream consumers (Deck calibration,
    # Mirror analytics) duck-type against the documented
    # LoremasterReport surface.
    loremaster_dispatched: bool = Field(
        default=False,
        description=(
            "True iff the Inquisitor attempted to dispatch the "
            "Loremaster bracket handler this pass "
            "(set even when the dispatch raised an exception)"
        ),
    )
    loremaster_report: Any = Field(
        default=None,
        description=(
            "The LoremasterReport returned by the dispatched bracket "
            "handler, or None when no dispatch attempt was made "
            "(or the dispatch raised an exception). Typed Any to "
            "avoid a circular import with the Loremaster handler."
        ),
    )
    loremaster_dispatch_failed: bool = Field(
        default=False,
        description=(
            "True iff the Loremaster dispatch raised an exception. "
            "The Verdict shape is preserved (the exception is "
            "swallowed by the Inquisitor handler) but the failure is "
            "surfaced here so Mirror calibration can see bracket-seam "
            "outages instead of going blind."
        ),
    )
    loremaster_dispatch_diagnostic: str | None = Field(
        default=None,
        description=(
            "One-sentence reason populated when "
            "``loremaster_dispatch_failed=True``; carries the exception "
            "type + message so the Deck can render the bracket-seam "
            "failure without consulting logs."
        ),
    )

    # Audit-trail flags for situations where the verdict still surfaces
    # parsed agent output but a non-output-gate signal needs to ride
    # along. The canonical first signal is ``"budget_exceeded"``: when
    # the agent's response parses cleanly AND ``budget.add`` raised
    # ``CostCeilingExceeded`` (marginal-overrun), the handler returns
    # the parsed PASS / FAIL / CONCERNS verdict with this flag set
    # rather than discarding the paid-for response to default-CONCERNS.
    # Mirror calibration disaggregates marginal-overruns from genuine
    # parse failures via this field.
    flags: list[str] = Field(
        default_factory=list,
        description=(
            "Audit-trail markers that ride along the verdict without "
            "gating the output. The canonical first entry is "
            "'budget_exceeded': parsed-response + cost ceiling crossed "
            "= audited-overrun PASS, not default-CONCERNS."
        ),
    )


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
    permission_mode: str = "dontAsk"
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


# ---------------------------------------------------------------------------
# Retrieval seam (Wave 1 — Tier 1 retrieval — RetrievalProvider Protocol +
# ContextAtom envelope; see CHANGELOG / commit history for design notes)
# ---------------------------------------------------------------------------


class ContextAtom(BaseModel):
    """One retrieved atom delivered to a prompt or MCP tool consumer.

    Slim by design — body is the markdown content the agent will read; score
    is the provider's confidence (e.g. ripgrep rank or BFS edge-weight roll-up).
    Tier 1 and Tier 2 providers both produce this shape so the consumer is
    tier-agnostic.
    """

    key: str
    body: str
    source_path: str
    score: float
    model_config = ConfigDict(extra="ignore")


@runtime_checkable
class RetrievalProvider(Protocol):
    """Pluggable retrieval — Tier 1 implementations live in bonfire-public;
    Tier 2 implementations (Pantheon) live in bonfire/ and register via the
    optional-import seam in bonfire._discovery.

    Implementations must be keyword-only at the call boundary so future
    parameters land additively without breaking callers.

    All implementations are async to support async VaultBackend delegation and
    Pantheon-tier graph queries.
    """

    async def retrieve(
        self,
        *,
        query: str,
        seed_keys: list[str] | None = None,
        token_budget: int = 4000,
    ) -> list[ContextAtom]: ...
