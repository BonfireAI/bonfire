# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Vendor-port parity contract for the Verdict envelope family (BON-1240).

The Verdict envelope is the Inquisitor's wire-level output. The
canonical schema lives in ``ishtar/forge/core/verdict.py`` and a
vendor-mirrored copy lives in ``bonfire/protocols.py`` so that
bonfire-public consumers (the Deck, Mirror calibration, downstream
plugins) can read/write Verdicts without a runtime dependency on
the closed-source forge codebase.

Why hardcoded reference sets instead of cross-repo import?
==========================================================

The bonfire-public CI runner does NOT have the ``ishtar`` repo on
PYTHONPATH (it lives in a separate private GitHub org). A test that
imported ``forge.core.verdict`` directly would either:

1. Fail in CI (no ishtar repo) and pass locally (drift goes silent), or
2. Need a ``pytest.skip(...)`` guard that defeats the parity check
   anywhere CI runs -- which is everywhere that matters.

The chosen design: hardcode the field-name / enum-variant reference
sets in this test file, read once from the forge-side source at
test-WRITE time, baked here. If forge-side drifts (e.g., a new
``Verdict`` field lands in ``ishtar/forge/core/verdict.py``) without
a paired update to ``bonfire-public/src/bonfire/protocols.py`` AND
this test, the test fails -- which is the contract we want.

Procedure on schema bump (BON-1240 follow-on):
  1. Update ``ishtar/forge/core/verdict.py`` (forge-side canonical).
  2. Update ``bonfire-public/src/bonfire/protocols.py`` (vendor mirror).
  3. Bump ``SCHEMA_VERSION`` in BOTH files in lockstep.
  4. Update the hardcoded reference sets in this file.
  5. All three changes ship in one PR.
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Hardcoded reference sets — read from forge-side at test-WRITE time
# (ishtar/forge/core/verdict.py, BON-1240 prep merge, SCHEMA_VERSION="1.1")
# ---------------------------------------------------------------------------

EXPECTED_SCHEMA_VERSION = "1.1"

EXPECTED_VERDICT_STATUS_VARIANTS = {"PASS", "CONCERNS", "FAIL"}

EXPECTED_SEVERITY_VARIANTS = {"CRITICAL", "MAJOR", "MINOR", "INFO"}

EXPECTED_FINDING_FIELDS = {
    "severity",
    "title",
    "rationale",
    "artifacts",
    "proposed_action",
    "related_lexicon",
}

EXPECTED_MUSCLE_WRITE_RECEIPT_FIELDS = {
    "key",
    "project",
    "operation",
    "superseded_keys",
}

EXPECTED_VERDICT_FIELDS = {
    # Core judgment
    "status",
    "rationale",
    "findings",
    "muscle_writes",
    # Provenance
    "run_id",
    "pipeline_summary",
    "inquisitor_started_at",
    "inquisitor_completed_at",
    "cost_usd",
    # Failure-mode
    "default_concerns",
    "diagnostic",
    # BON-972 (truncation provenance)
    "chain_truncated",
    # BON-980 (bookend-payload truncation)
    "chain_truncated_bookend",
    # BON-984 (Loremaster bracket-seam observability)
    "loremaster_dispatched",
    "loremaster_report",
    "loremaster_dispatch_failed",
    "loremaster_dispatch_diagnostic",
    # Probe 4 R8 (audit-trail flags)
    "flags",
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


# ---------------------------------------------------------------------------
# Enum parity
# ---------------------------------------------------------------------------


def test_verdict_status_variants() -> None:
    from bonfire.protocols import VerdictStatus

    actual = {member.name for member in VerdictStatus}
    assert actual == EXPECTED_VERDICT_STATUS_VARIANTS, (
        f"VerdictStatus drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_VERDICT_STATUS_VARIANTS}"
    )


def test_verdict_status_values_match_names() -> None:
    """StrEnum: each member's .value must equal its .name."""
    from bonfire.protocols import VerdictStatus

    for member in VerdictStatus:
        assert member.value == member.name


def test_severity_variants() -> None:
    from bonfire.protocols import Severity

    actual = {member.name for member in Severity}
    assert actual == EXPECTED_SEVERITY_VARIANTS, (
        f"Severity drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_SEVERITY_VARIANTS}"
    )


def test_severity_values_match_names() -> None:
    from bonfire.protocols import Severity

    for member in Severity:
        assert member.value == member.name


# ---------------------------------------------------------------------------
# Pydantic model field parity
# ---------------------------------------------------------------------------


def test_finding_fields() -> None:
    from bonfire.protocols import Finding

    actual = set(Finding.model_fields.keys())
    assert actual == EXPECTED_FINDING_FIELDS, (
        f"Finding field drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_FINDING_FIELDS}"
    )


def test_muscle_write_receipt_fields() -> None:
    from bonfire.protocols import MuscleWriteReceipt

    actual = set(MuscleWriteReceipt.model_fields.keys())
    assert actual == EXPECTED_MUSCLE_WRITE_RECEIPT_FIELDS, (
        f"MuscleWriteReceipt field drift: bonfire-public has {actual}, "
        f"expected {EXPECTED_MUSCLE_WRITE_RECEIPT_FIELDS}"
    )


def test_verdict_fields() -> None:
    from bonfire.protocols import Verdict

    actual = set(Verdict.model_fields.keys())
    assert actual == EXPECTED_VERDICT_FIELDS, (
        f"Verdict field drift: bonfire-public has {actual}, expected "
        f"{EXPECTED_VERDICT_FIELDS}. Diff (public-only): "
        f"{actual - EXPECTED_VERDICT_FIELDS}; "
        f"diff (forge-only): {EXPECTED_VERDICT_FIELDS - actual}"
    )


# ---------------------------------------------------------------------------
# Re-export contract — `from bonfire import ...` must work
# ---------------------------------------------------------------------------


def test_root_package_reexports() -> None:
    """The five envelope classes + SCHEMA_VERSION re-export from bonfire root."""
    from bonfire import (
        SCHEMA_VERSION,
        Finding,
        MuscleWriteReceipt,
        Severity,
        Verdict,
        VerdictStatus,
    )

    # Sanity: same objects as bonfire.protocols, not stand-ins.
    from bonfire import protocols as _p

    assert Verdict is _p.Verdict
    assert VerdictStatus is _p.VerdictStatus
    assert Severity is _p.Severity
    assert Finding is _p.Finding
    assert MuscleWriteReceipt is _p.MuscleWriteReceipt
    assert SCHEMA_VERSION == _p.SCHEMA_VERSION


# ---------------------------------------------------------------------------
# Smoke construction — round-trip a minimal Verdict
# ---------------------------------------------------------------------------


def test_minimal_verdict_roundtrips() -> None:
    """A minimal Verdict can be constructed, serialized, and rebuilt."""
    from bonfire.protocols import Verdict, VerdictStatus

    v = Verdict(
        status=VerdictStatus.PASS,
        rationale="smoke",
        run_id="r-0001",
        pipeline_summary="scout->steward, 2 stages, 0 sage-bounces",
        inquisitor_started_at="2026-05-21T00:00:00Z",
        inquisitor_completed_at="2026-05-21T00:00:01Z",
        cost_usd=0.0,
    )

    blob = v.model_dump_json()
    rebuilt = Verdict.model_validate_json(blob)

    assert rebuilt.status == VerdictStatus.PASS
    assert rebuilt.findings == []
    assert rebuilt.muscle_writes == []
    assert rebuilt.default_concerns is False
    assert rebuilt.chain_truncated is False
    assert rebuilt.chain_truncated_bookend is False
    assert rebuilt.loremaster_dispatched is False
    assert rebuilt.loremaster_report is None
    assert rebuilt.loremaster_dispatch_failed is False
    assert rebuilt.loremaster_dispatch_diagnostic is None
    assert rebuilt.flags == []


def test_finding_severity_typed() -> None:
    """A Finding's severity must accept a Severity enum, reject garbage."""
    from bonfire.protocols import Finding, Severity

    ok = Finding(
        severity=Severity.MAJOR,
        title="x",
        rationale="y",
    )
    assert ok.severity == Severity.MAJOR

    with pytest.raises(Exception):  # pydantic ValidationError
        Finding(severity="NOPE", title="x", rationale="y")  # type: ignore[arg-type]
