# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Vendor-port parity contract for the BracketPassReport envelope.

The BracketPassReport is the orchestrator's single return shape for one
bracket pass: it carries the embedded Inquisitor ``Verdict``, the optional
Artificer ``ArtificerReport``, the branch the orchestrator took, and the
advisory failure-mode flag mirrors. The canonical schema lives forge-side
and a vendor-mirrored copy lives in ``bonfire/protocols.py`` so
bonfire-public consumers (the Deck, Mirror calibration, downstream
plugins) can read/write BracketPassReports without a runtime dependency on
the closed-source forge codebase.

This port co-lands the ArtificerReport family (ProbeFinding,
AxiomVariantReceipt, ValidationOutcome, ArtificerReport) because
BracketPassReport embeds ``artificer_report: ArtificerReport | None`` by
typed reference — structural equivalence requires the embedded type to be
present, not relaxed.

Why hardcoded reference sets instead of cross-repo import?
==========================================================

Same rationale as ``tests/test_verdict_parity.py``: the bonfire-public CI
runner does NOT have the ``ishtar`` repo on PYTHONPATH (it lives in a
separate private GitHub org). A test that imported the forge-side module
directly would either fail in CI (no ishtar repo) while passing locally
(drift goes silent), or need a ``pytest.skip(...)`` guard that defeats the
parity check everywhere CI runs.

The chosen design: hardcode the field-name reference sets in this test
file, read once from the forge-side source at test-WRITE time, baked here.
If forge-side drifts without a paired update to
``bonfire-public/src/bonfire/protocols.py`` AND this test, the test fails
— which is the contract we want.

Procedure on schema bump:
  1. Update the forge-side canonical modules.
  2. Update ``bonfire-public/src/bonfire/protocols.py`` (vendor mirror).
  3. Bump ``SCHEMA_VERSION`` in both files in lockstep.
  4. Update the hardcoded reference sets in this file.
  5. All changes ship in one PR.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Hardcoded reference sets — read from forge-side at test-WRITE time
# (forge core bracket_pass_report.py + artificer_report.py, SCHEMA_VERSION="1.1")
# ---------------------------------------------------------------------------

EXPECTED_SCHEMA_VERSION = "1.1"

EXPECTED_BRACKET_PASS_REPORT_FIELDS = {
    "schema_version",
    "run_id",
    "verdict",
    "artificer_report",
    "branched_status",
    "default_concerns",
    "loremaster_dispatched",
    "loremaster_dispatch_failed",
}

EXPECTED_PROBE_FINDING_FIELDS = {
    "probe_kind",
    "summary",
    "evidence",
    "cost_usd",
    "truncated",
    "truncation_diagnostic",
}

EXPECTED_AXIOM_VARIANT_RECEIPT_FIELDS = {
    "cadre_slot",
    "axiom_path",
    "domain_scope",
    "forged_at",
    "supersedes",
}

EXPECTED_VALIDATION_OUTCOME_FIELDS = {
    "pass_rate",
    "sample_count",
    "threshold",
    "iterations",
    "inquisitor_run_ids",
}

EXPECTED_ARTIFICER_REPORT_FIELDS = {
    "domain_name",
    "probes",
    "variants_forged",
    "validation",
    "ratified",
    "run_id",
    "started_at",
    "completed_at",
    "cost_usd",
    "default_unratified",
    "diagnostic",
}


# ---------------------------------------------------------------------------
# SCHEMA_VERSION pin
# ---------------------------------------------------------------------------


def test_schema_version_pinned() -> None:
    """bonfire.protocols.SCHEMA_VERSION must match forge-side exactly."""
    from bonfire.protocols import SCHEMA_VERSION

    assert SCHEMA_VERSION == EXPECTED_SCHEMA_VERSION, (
        f"SCHEMA_VERSION drift: bonfire-public has {SCHEMA_VERSION!r}, "
        f"forge-side has {EXPECTED_SCHEMA_VERSION!r}. Bump in lockstep."
    )


def test_bracket_pass_report_schema_version_pin() -> None:
    """The Literal pin on schema_version must equal the module constant."""
    from bonfire.protocols import SCHEMA_VERSION, BracketPassReport

    field = BracketPassReport.model_fields["schema_version"]
    assert field.default == "1.1"
    assert field.default == SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Pydantic model field parity
# ---------------------------------------------------------------------------


def test_bracket_pass_report_fields() -> None:
    from bonfire.protocols import BracketPassReport

    actual = set(BracketPassReport.model_fields.keys())
    assert actual == EXPECTED_BRACKET_PASS_REPORT_FIELDS, (
        f"BracketPassReport field drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_BRACKET_PASS_REPORT_FIELDS}. Diff (public-only): "
        f"{actual - EXPECTED_BRACKET_PASS_REPORT_FIELDS}; "
        f"diff (forge-only): {EXPECTED_BRACKET_PASS_REPORT_FIELDS - actual}"
    )


def test_probe_finding_fields() -> None:
    from bonfire.protocols import ProbeFinding

    actual = set(ProbeFinding.model_fields.keys())
    assert actual == EXPECTED_PROBE_FINDING_FIELDS, (
        f"ProbeFinding field drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_PROBE_FINDING_FIELDS}"
    )


def test_axiom_variant_receipt_fields() -> None:
    from bonfire.protocols import AxiomVariantReceipt

    actual = set(AxiomVariantReceipt.model_fields.keys())
    assert actual == EXPECTED_AXIOM_VARIANT_RECEIPT_FIELDS, (
        f"AxiomVariantReceipt field drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_AXIOM_VARIANT_RECEIPT_FIELDS}"
    )


def test_validation_outcome_fields() -> None:
    from bonfire.protocols import ValidationOutcome

    actual = set(ValidationOutcome.model_fields.keys())
    assert actual == EXPECTED_VALIDATION_OUTCOME_FIELDS, (
        f"ValidationOutcome field drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_VALIDATION_OUTCOME_FIELDS}"
    )


def test_artificer_report_fields() -> None:
    from bonfire.protocols import ArtificerReport

    actual = set(ArtificerReport.model_fields.keys())
    assert actual == EXPECTED_ARTIFICER_REPORT_FIELDS, (
        f"ArtificerReport field drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_ARTIFICER_REPORT_FIELDS}"
    )


# ---------------------------------------------------------------------------
# branched_status is the typed VerdictStatus enum
# ---------------------------------------------------------------------------


def test_branched_status_is_verdict_status_enum() -> None:
    from bonfire.protocols import BracketPassReport, VerdictStatus

    field = BracketPassReport.model_fields["branched_status"]
    assert field.annotation is VerdictStatus


# ---------------------------------------------------------------------------
# Re-export contract — `from bonfire import ...` must work
# ---------------------------------------------------------------------------


def test_root_package_reexports() -> None:
    """The ported envelope classes re-export from the bonfire root package."""
    from bonfire import (
        ArtificerReport,
        AxiomVariantReceipt,
        BracketPassReport,
        ProbeFinding,
        ValidationOutcome,
    )
    from bonfire import protocols as _p

    # Sanity: same objects as bonfire.protocols, not stand-ins.
    assert BracketPassReport is _p.BracketPassReport
    assert ArtificerReport is _p.ArtificerReport
    assert ProbeFinding is _p.ProbeFinding
    assert AxiomVariantReceipt is _p.AxiomVariantReceipt
    assert ValidationOutcome is _p.ValidationOutcome


def test_protocols_submodule_import() -> None:
    """`from bonfire.protocols import BracketPassReport` must work."""
    from bonfire.protocols import BracketPassReport

    assert BracketPassReport.__name__ == "BracketPassReport"


# ---------------------------------------------------------------------------
# Smoke construction — round-trip a minimal BracketPassReport
# ---------------------------------------------------------------------------


def test_minimal_bracket_pass_report_roundtrips() -> None:
    """A minimal BracketPassReport can be built, serialized, and rebuilt."""
    from bonfire.protocols import BracketPassReport, Verdict, VerdictStatus

    verdict = Verdict(
        status=VerdictStatus.PASS,
        rationale="smoke",
        run_id="r-0001",
        pipeline_summary="scout->steward, 2 stages, 0 sage-bounces",
        inquisitor_started_at="2026-05-21T00:00:00Z",
        inquisitor_completed_at="2026-05-21T00:00:01Z",
        cost_usd=0.0,
    )

    report = BracketPassReport(
        run_id="bp-0001",
        verdict=verdict,
        branched_status=VerdictStatus.PASS,
    )

    blob = report.model_dump_json()
    rebuilt = BracketPassReport.model_validate_json(blob)

    assert rebuilt.schema_version == "1.1"
    assert rebuilt.branched_status == VerdictStatus.PASS
    assert rebuilt.artificer_report is None
    assert rebuilt.default_concerns is False
    assert rebuilt.loremaster_dispatched is False
    assert rebuilt.loremaster_dispatch_failed is False


def test_schema_version_mismatch_raises() -> None:
    """A mismatched schema_version is rejected at the envelope edge."""
    from bonfire.protocols import BracketPassReport, Verdict, VerdictStatus

    verdict = Verdict(
        status=VerdictStatus.PASS,
        rationale="smoke",
        run_id="r-0002",
        pipeline_summary="scout->steward, 2 stages, 0 sage-bounces",
        inquisitor_started_at="2026-05-21T00:00:00Z",
        inquisitor_completed_at="2026-05-21T00:00:01Z",
        cost_usd=0.0,
    )

    with pytest.raises(Exception):  # pydantic ValidationError
        BracketPassReport(
            schema_version="9.9",  # type: ignore[arg-type]
            run_id="bp-0002",
            verdict=verdict,
            branched_status=VerdictStatus.PASS,
        )


# ---------------------------------------------------------------------------
# ArtificerReport family smoke — minimal construction round-trip
# ---------------------------------------------------------------------------


def test_minimal_artificer_report_roundtrips() -> None:
    from bonfire.protocols import (
        ArtificerReport,
        AxiomVariantReceipt,
        ProbeFinding,
        ValidationOutcome,
    )

    report = ArtificerReport(
        domain_name="candy-store",
        probes=[
            ProbeFinding(
                probe_kind="domain-shape",
                summary="structural read",
                evidence=["artifact-1"],
                cost_usd=0.01,
            )
        ],
        variants_forged=[
            AxiomVariantReceipt(
                cadre_slot="scout",
                axiom_path="lexicon/key",
                domain_scope="candy-store",
                forged_at="2026-05-21T00:00:00Z",
            )
        ],
        validation=ValidationOutcome(
            pass_rate=0.9,
            sample_count=10,
            iterations=1,
        ),
        ratified=True,
        run_id="ar-0001",
        started_at="2026-05-21T00:00:00Z",
        completed_at="2026-05-21T00:01:00Z",
        cost_usd=0.5,
    )

    blob = report.model_dump_json()
    rebuilt = ArtificerReport.model_validate_json(blob)

    assert rebuilt.ratified is True
    assert rebuilt.default_unratified is False
    assert rebuilt.validation.threshold == 0.8


def test_validation_outcome_clamps_unit_interval() -> None:
    """pass_rate / threshold clamp to [0.0, 1.0] per the forge-side rule."""
    from bonfire.protocols import ValidationOutcome

    out = ValidationOutcome(
        pass_rate=1.5,
        sample_count=3,
        threshold=-0.2,
        iterations=1,
    )
    assert out.pass_rate == 1.0
    assert out.threshold == 0.0
