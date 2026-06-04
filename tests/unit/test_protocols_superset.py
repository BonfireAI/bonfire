# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pin the protocols.py superset: the verify/Mirror vocabulary and the
retrieval seam are appended on top of the retained v0.1 core, and the
v0.1 protocols survive intact (strict superset).

Standalone by construction: this module imports only ``bonfire.protocols``
(plus pydantic for the ValidationError check). No engine / dispatch /
retrieval-package dependency, so it collects and runs in isolation.
"""

from __future__ import annotations

import bonfire.protocols as p
from bonfire.protocols import (
    ArtificerReport,
    AxiomVariantReceipt,
    BracketPassReport,
    ContextAtom,
    Finding,
    MuscleWriteReceipt,
    ProbeFinding,
    RetrievalProvider,
    Severity,
    ValidationOutcome,
    Verdict,
    VerdictStatus,
)

# ---------------------------------------------------------------------------
# Strict superset: every retained v0.1 protocol / value type is still present
# ---------------------------------------------------------------------------

V01_RETAINED = (
    "AgentBackend",
    "DispatchOptions",
    "QualityGate",
    "StageHandler",
    "VaultBackend",
    "VaultEntry",
)

APPENDED_NAMES = (
    "SCHEMA_VERSION",
    "Severity",
    "VerdictStatus",
    "Finding",
    "MuscleWriteReceipt",
    "Verdict",
    "ProbeFinding",
    "AxiomVariantReceipt",
    "ValidationOutcome",
    "ArtificerReport",
    "BracketPassReport",
    "ContextAtom",
    "RetrievalProvider",
)


def test_v01_retained_core_is_a_strict_subset_present_on_module():
    """Every v0.1 retained name still resolves on bonfire.protocols and is
    still exported via __all__ (no retained contract dropped by the append)."""
    for name in V01_RETAINED:
        assert hasattr(p, name), f"v0.1 protocol {name!r} was dropped from the module"
        assert name in p.__all__, f"v0.1 protocol {name!r} was dropped from __all__"


def test_appended_superset_names_all_importable_and_exported():
    """Every appended class/constant resolves and is exported via __all__."""
    for name in APPENDED_NAMES:
        assert hasattr(p, name), f"appended symbol {name!r} not importable from bonfire.protocols"
        assert name in p.__all__, f"appended symbol {name!r} missing from __all__"


def test_all_is_a_proper_superset_of_v01():
    """__all__ contains the v0.1 set plus the appended set, with no removals."""
    exported = set(p.__all__)
    assert set(V01_RETAINED) <= exported
    assert set(APPENDED_NAMES) <= exported


def test_schema_version_pin():
    assert p.SCHEMA_VERSION == "1.1"


# ---------------------------------------------------------------------------
# Instantiation: a Finding and a Verdict round-trip cleanly
# ---------------------------------------------------------------------------


def test_finding_instantiates():
    finding = Finding(
        severity=Severity.MAJOR,
        title="Untyped failure swallowed",
        rationale="A bare except hid the real error.",
    )
    assert finding.severity is Severity.MAJOR
    assert finding.proposed_action is None
    assert finding.artifacts == []


def test_verdict_instantiates_with_finding():
    verdict = Verdict(
        status=VerdictStatus.CONCERNS,
        rationale="One major concern surfaced.",
        findings=[
            Finding(
                severity=Severity.MAJOR,
                title="t",
                rationale="r",
            )
        ],
        run_id="run-123",
        pipeline_summary="scout->knight->steward, 3 stages, 0 sage-bounces",
        inquisitor_started_at="2026-06-04T00:00:00Z",
        inquisitor_completed_at="2026-06-04T00:01:00Z",
        cost_usd=0.42,
    )
    assert verdict.status is VerdictStatus.CONCERNS
    assert len(verdict.findings) == 1
    assert verdict.default_concerns is False


def test_severity_and_verdictstatus_are_strenums():
    assert Severity.CRITICAL == "CRITICAL"
    assert VerdictStatus.PASS == "PASS"


def test_validation_outcome_clamps_unit_interval():
    """The field_validator import the append needed is exercised here."""
    outcome = ValidationOutcome(pass_rate=1.5, sample_count=10, threshold=-0.2, iterations=1)
    assert outcome.pass_rate == 1.0
    assert outcome.threshold == 0.0


def test_artificer_and_bracket_pass_report_assemble():
    report = ArtificerReport(
        domain_name="payments",
        probes=[
            ProbeFinding(
                probe_kind="domain-shape",
                summary="s",
                evidence=["/e"],
                cost_usd=0.01,
            )
        ],
        variants_forged=[
            AxiomVariantReceipt(
                cadre_slot="scout",
                axiom_path="axioms/scout/payments",
                domain_scope="payments",
                forged_at="2026-06-04T00:00:00Z",
            )
        ],
        validation=ValidationOutcome(pass_rate=0.9, sample_count=10, iterations=1),
        ratified=True,
        run_id="adapt-1",
        started_at="2026-06-04T00:00:00Z",
        completed_at="2026-06-04T00:05:00Z",
        cost_usd=1.23,
    )
    assert report.ratified is True

    verdict = Verdict(
        status=VerdictStatus.PASS,
        rationale="clean",
        run_id="run-1",
        pipeline_summary="scout->steward, 2 stages, 0 sage-bounces",
        inquisitor_started_at="2026-06-04T00:00:00Z",
        inquisitor_completed_at="2026-06-04T00:00:30Z",
        cost_usd=0.1,
    )
    bracket = BracketPassReport(
        run_id="bracket-1",
        verdict=verdict,
        artificer_report=report,
        branched_status=VerdictStatus.PASS,
    )
    assert bracket.schema_version == "1.1"
    assert bracket.branched_status is VerdictStatus.PASS
    assert bracket.artificer_report is report


def test_muscle_write_receipt_instantiates():
    receipt = MuscleWriteReceipt(key="k", project="proj", operation="write")
    assert receipt.superseded_keys == []


# ---------------------------------------------------------------------------
# Retrieval seam: ContextAtom + the @runtime_checkable RetrievalProvider
# ---------------------------------------------------------------------------


def test_context_atom_instantiates():
    atom = ContextAtom(key="k", body="b", source_path="/p", score=0.5)
    assert atom.score == 0.5


def test_retrieval_provider_is_runtime_checkable_against_a_duck():
    """@runtime_checkable means a duck object with a matching async retrieve
    passes isinstance without nominal inheritance."""

    class DuckProvider:
        async def retrieve(
            self,
            *,
            query: str,
            seed_keys: list[str] | None = None,
            token_budget: int = 4000,
        ) -> list[ContextAtom]:
            return []

    assert isinstance(DuckProvider(), RetrievalProvider)


async def test_retrieval_provider_structural_call():
    class DuckProvider:
        async def retrieve(
            self,
            *,
            query: str,
            seed_keys: list[str] | None = None,
            token_budget: int = 4000,
        ) -> list[ContextAtom]:
            return [ContextAtom(key="a", body="b", source_path="/a", score=1.0)]

    provider: RetrievalProvider = DuckProvider()
    out = await provider.retrieve(query="q")
    assert len(out) == 1
    assert out[0].key == "a"
