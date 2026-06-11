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
quality gate's wire-level output (the synthesis/judgment stage result),
vendor-mirrored from the canonical schema. The module-level constant
:data:`SCHEMA_VERSION` MUST match the
forge-side string in lockstep; the parity test
``tests/test_verdict_parity.py`` enforces this.

Design constraints
~~~~~~~~~~~~~~~~~~
*   All protocols are ``@runtime_checkable``.
*   No ABCs.  ``typing.Protocol`` gives structural subtyping.
*   Cross-package model imports (``bonfire.models``) stay under
    ``TYPE_CHECKING``, so importing this module does not drag the models
    package in at runtime.
*   One acknowledged exception to that layering rule: ``SecurityHooksConfig``
    is imported from ``bonfire.dispatch.security_hooks`` at module (runtime)
    scope, NOT under ``TYPE_CHECKING``. Pydantic needs the concrete runtime
    type to validate the ``DispatchOptions.security_hooks`` field, so the
    import cannot be deferred. This is intentional and means extension authors
    who import ``bonfire.protocols`` also pull in ``bonfire.dispatch``; the
    "only ``bonfire.models``" claim is qualified by this single carve-out.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Pydantic requires the runtime type for validation — keep this import
# outside of TYPE_CHECKING.
from bonfire.dispatch.security_hooks import SecurityHooksConfig

if TYPE_CHECKING:
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import GateContext, GateResult, StageSpec

__all__ = [
    "AgentBackend",
    "ArtificerReport",
    "AxiomVariantReceipt",
    "BracketPassReport",
    "ContextAtom",
    "DispatchOptions",
    "Finding",
    "MuscleWriteReceipt",
    "ProbeFinding",
    "QualityGate",
    "RetrievalProvider",
    "SCHEMA_VERSION",
    "Severity",
    "StageHandler",
    "ValidationOutcome",
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
    """Tiered status of a quality verdict (PASS / CONCERNS / FAIL)."""

    PASS = "PASS"  # noqa: S105 — enum wire value, not a credential (registered exemption)
    CONCERNS = "CONCERNS"
    FAIL = "FAIL"


class Finding(BaseModel):
    """A single concern or defect surfaced by the quality gate.

    Consumed by ticket templating (the ``proposed_action`` field
    drives the auto-file body) and downstream review surfaces.
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
    """The complete quality-verdict output.

    Wire-level object. Persisted as part of the run record. Read by the
    runtime (effectuate / hold / terminate), visualization consumers, and
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

    # Loremaster bracket-seam observability fields. The judgment-stage→
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
            "True iff the verdict handler attempted to dispatch the "
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
            "swallowed by the verdict handler) but the failure is "
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
# ArtificerReport envelope family (vendor-port from forge-side)
# ---------------------------------------------------------------------------
#
# The Artificer report is the domain-adaptation stage's wire-level output:
# it captures one domain-adaptation run — the probe findings from the
# three-orthogonal-probes characterization, the per-role axiom variants the
# run forged, the validation run that gated ratification, and the
# ratification verdict. It is carried by typed reference inside
# :class:`BracketPassReport` (``artificer_report``), so the public package
# co-ports it alongside that envelope rather than relaxing the embedded
# type. The four classes (ProbeFinding, AxiomVariantReceipt,
# ValidationOutcome, ArtificerReport) share the module-level
# :data:`SCHEMA_VERSION` pin with the Verdict family.


class ProbeFinding(BaseModel):
    """A single probe's output from the three-orthogonal-probes characterization.

    Three probes run in parallel against a new domain: ``domain-shape``
    (what the domain looks like structurally), ``failure-mode`` (where it
    tends to break), and ``success-pattern`` (what good output looks like).
    Each probe emits one ``ProbeFinding``; they collate into per-role axiom
    variants.

    The ``truncated`` flag mirrors the Verdict's ``chain_truncated``
    pattern: the probe shipped a finding, but the parallel harness clipped
    its runtime against the budget ceiling.
    """

    model_config = ConfigDict(use_enum_values=False)

    probe_kind: Literal["domain-shape", "failure-mode", "success-pattern"] = Field(
        description="Which of the three probes produced this finding"
    )
    summary: str = Field(description="One-paragraph characterization of the probe result")
    evidence: list[str] = Field(description="Artifact paths or snippet IDs supporting the summary")
    cost_usd: float = Field(description="What this probe cost")
    truncated: bool = Field(
        default=False,
        description=(
            "True iff the parallel harness clipped this probe's runtime "
            "against the budget ceiling (mirrors Verdict.chain_truncated)"
        ),
    )
    truncation_diagnostic: str | None = Field(
        default=None,
        description="One-sentence reason populated when ``truncated=True``",
    )


class AxiomVariantReceipt(BaseModel):
    """Provenance for a single per-role axiom variant the adaptation run forged.

    One variant is written per role slot per domain. The ``supersedes``
    list captures the knowledge keys this variant replaces (supersession,
    not deletion).
    """

    model_config = ConfigDict(use_enum_values=False)

    cadre_slot: str = Field(description="One of the role slot names (scout, knight, ...)")
    axiom_path: str = Field(description="Knowledge key the variant was written under")
    domain_scope: str = Field(description="The domain identifier this variant adapts to")
    forged_at: str = Field(description="ISO-8601 UTC timestamp of the forge")
    supersedes: list[str] = Field(
        default_factory=list,
        description=(
            "Knowledge keys this variant supersedes; empty when the variant "
            "is the first for its (cadre_slot, domain) pair"
        ),
    )


class ValidationOutcome(BaseModel):
    """The validation run that gates ratification.

    ``threshold`` defaults to 0.8. ``pass_rate`` and ``threshold`` are
    clamped to ``[0.0, 1.0]`` at the envelope layer (cost has no upper
    bound; pass-rate does).

    ``inquisitor_run_ids`` carries the judgment-stage run IDs that
    contributed to this rate; empty when validation rides on an eyeball
    rubric.
    """

    model_config = ConfigDict(use_enum_values=False)

    pass_rate: float = Field(
        description="Fraction of validation samples that passed (clamped to [0.0, 1.0])"
    )
    sample_count: int = Field(
        ge=0,
        description="Number of validation samples evaluated",
    )
    threshold: float = Field(
        default=0.8,
        description=("Pass-rate threshold for ratification (default 0.8; clamped to [0.0, 1.0])"),
    )
    iterations: int = Field(
        ge=1,
        description="How many validation passes ran (must be >= 1)",
    )
    inquisitor_run_ids: list[str] = Field(
        default_factory=list,
        description=(
            "Judgment-stage run IDs that contributed to this pass-rate; "
            "empty when validation rides on an eyeball rubric"
        ),
    )

    @field_validator("pass_rate", "threshold")
    @classmethod
    def _clamp_unit_interval(cls, v: float) -> float:
        """Clamp pass_rate / threshold to ``[0.0, 1.0]``."""
        if v < 0.0:
            return 0.0
        if v > 1.0:
            return 1.0
        return v


class ArtificerReport(BaseModel):
    """The complete output of one domain-adaptation run.

    Wire-level object. Persisted as part of the run record. Read by
    cross-domain calibration analytics and the Deck (ratification surface).

    ``ratified`` is the canonical discriminator for downstream consumers
    that ask "did this domain ratify". The handler is responsible for
    enforcing ``ratified == (pass_rate >= threshold and not
    default_unratified)``; the envelope stores both so calibration can
    detect handler-side drift.
    """

    model_config = ConfigDict(use_enum_values=False)

    domain_name: str = Field(description="The domain this adaptation run targets")
    probes: list[ProbeFinding] = Field(
        description=(
            "Probe findings from the three-orthogonal-probes characterization; "
            "expected length 3 but the envelope tolerates any length"
        )
    )
    variants_forged: list[AxiomVariantReceipt] = Field(
        description="Per-role-slot axiom variants this run forged"
    )
    validation: ValidationOutcome = Field(description="The validation run that gated ratification")
    ratified: bool = Field(description="Whether the domain ratified this pass")

    # Provenance
    run_id: str = Field(description="Unique identifier for this adaptation run")
    started_at: str = Field(description="ISO-8601 UTC timestamp the run began")
    completed_at: str = Field(description="ISO-8601 UTC timestamp the run ended")
    cost_usd: float = Field(description="What this adaptation run cost")

    # Failure-mode
    default_unratified: bool = Field(
        default=False,
        description=(
            "True iff unratified via fallback path (crash / timeout / etc.); "
            "mirrors Verdict.default_concerns"
        ),
    )
    diagnostic: str | None = Field(
        default=None,
        description=(
            "One-sentence reason; populated when ``default_unratified=True`` "
            "(the envelope does not require this — the handler enforces it)"
        ),
    )


# ---------------------------------------------------------------------------
# BracketPassReport envelope (vendor-port from forge-side)
# ---------------------------------------------------------------------------


class BracketPassReport(BaseModel):
    """The orchestrator's bracket-pass summary.

    The single return shape for one bracket pass. Carries:

    - The judgment-stage typed :class:`Verdict` (always present when the
      bracket fires).
    - The optional domain-adaptation :class:`ArtificerReport` (None when
      adaptation did not fire — a clean PASS without a new domain set).
    - The branch the orchestrator took (PASS / CONCERNS / FAIL) on
      ``branched_status``.
    - Advisory flag mirrors of the embedded Verdict's failure-mode fields
      (``default_concerns`` / ``loremaster_dispatched`` /
      ``loremaster_dispatch_failed``) so calibration can disaggregate
      bracket-pass-level failure modes without re-walking the embedded
      envelopes.

    ``use_enum_values=False`` keeps ``branched_status`` a typed
    :class:`VerdictStatus` on the wire. ``schema_version`` is pinned via
    ``Literal['1.1']`` so a mismatched version raises ``ValidationError``
    synchronously at the envelope edge.
    """

    model_config = ConfigDict(
        use_enum_values=False,
        extra="ignore",
        frozen=True,
    )

    schema_version: Literal["1.1"] = Field(
        default=SCHEMA_VERSION,
        description=(
            "Schema version pin. BracketPassReport locks at v1.1. Mismatched "
            "versions raise ValidationError at the envelope edge."
        ),
    )
    run_id: str = Field(
        description=(
            "Orchestrator-side run identifier for this bracket pass. Distinct "
            "from the embedded ``Verdict.run_id``."
        )
    )
    verdict: Verdict = Field(
        description=(
            "The judgment-stage verdict. Always present when the bracket "
            "fires — a synthesized default-CONCERNS Verdict surfaces when the "
            "judgment handler returns None or raises."
        )
    )
    artificer_report: ArtificerReport | None = Field(
        default=None,
        description=(
            "The domain-adaptation report if adaptation fired this pass; None "
            "when it was not dispatched (clean PASS + no new domain)."
        ),
    )
    branched_status: VerdictStatus = Field(
        description=(
            "The branch the orchestrator took on Verdict.status. Canonical "
            "discriminator for downstream effectuate/hold/terminate consumers."
        )
    )

    # ------------------------------------------------------------------
    # Advisory flag mirrors of the embedded Verdict's failure-mode fields
    # ------------------------------------------------------------------
    # These ride along the BracketPassReport so calibration can
    # disaggregate bracket-pass-level failure modes without re-walking the
    # embedded Verdict. The embedded Verdict remains canonical; these are
    # advisory mirrors set by the orchestrator at construction time.

    default_concerns: bool = Field(
        default=False,
        description=(
            "True iff the embedded Verdict came from the fallback synthesis "
            "path. Advisory mirror of Verdict.default_concerns."
        ),
    )
    loremaster_dispatched: bool = Field(
        default=False,
        description=(
            "True iff the judgment handler attempted Loremaster dispatch. "
            "Advisory mirror of Verdict.loremaster_dispatched."
        ),
    )
    loremaster_dispatch_failed: bool = Field(
        default=False,
        description=(
            "True iff the Loremaster dispatch raised an exception. "
            "Advisory mirror of Verdict.loremaster_dispatch_failed."
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
