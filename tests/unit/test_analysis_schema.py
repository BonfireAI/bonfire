"""RED tests for bonfire.analysis.models — BON-347 W6.1 (CONTRACT-LOCKED).

ProjectAnalysis schema-version v2 contract.

Port of v1 ``test_wave2c_project_study_schema.py`` with class rename
``ProjectStudy → ProjectAnalysis`` per ADR-001.

Amendment A10: a v1 cache blob must fail to load under the new schema
so that Wave 2b cache reads fall back to a fresh scan instead of
silently returning a study with missing enrichment fields.

Sage decision log: docs/audit/sage-decisions/bon-347-contract-lock-20260426T000357Z.md
Authority cite:    docs/audit/sage-decisions/bon-347-sage-20260425T230115Z.md

Floor (2 tests, per Sage §D6 Row 2): port v1 cartographer schema-version test
surface verbatim. The JSON field name ``study_schema_version`` is unchanged per
Sage §D3.

Innovations adopted from Knight B (2 tests, drift-guards):
  * ``test_schema_version_default_int_type`` — assert
    ``ProjectAnalysis.model_fields["study_schema_version"].annotation is int``
    (NOT ``Literal[2]``). Cites Sage §D4 (study_schema_version: int =
    Field(default=2)) + v1 ``models.py:200``.
  * ``test_v1_blob_rejection_message_format`` — parametrized sweep (0/1/99) over
    wrong-version values; asserts each raises ValidationError AND the validator's
    EXACT f-string phrase ``f"study_schema_version must be 2, got {v}"`` is in
    the error. Cites Sage §D4 (validator body lock) + v1 ``models.py:212-220``.
    [MERGE: assertion tightened from Knight B's substring digit check to the
    exact phrase, to actually pin the ``{v}`` placeholder against Pydantic's
    ambient input_value reporting — see contract-lock log.]

Imports are RED — ``bonfire.analysis.models`` does not exist until Warriors port
v1 ``bonfire/src/bonfire/project/cartographer/models.py`` per Sage §D9.
"""

from __future__ import annotations

import gzip
import json

import pytest
from pydantic import ValidationError

from bonfire.analysis.models import ProjectAnalysis


def test_project_analysis_schema_version_defaults_to_2():
    # Build a minimal valid study via a direct dict round-trip so we
    # don't have to hand-roll StudyMetadata; the default int literal is
    # what we care about.
    from bonfire.analysis.models import ProjectAnalysis

    # Probe the field default without instantiation — avoids having to
    # hand-build a full StudyMetadata just to assert a default.
    field = ProjectAnalysis.model_fields["study_schema_version"]
    assert field.default == 2


def _v1_blob(*, version: int = 1) -> bytes:
    """Construct a raw gzip-wrapped JSON payload with ``study_schema_version=version``.

    Everything else in the payload is shaped to be otherwise-valid under
    the v2 schema so the ONLY thing that should trip validation is the
    version field itself (once v2 enforces it).
    """
    payload = {
        "study_schema_version": version,
        "metadata": {
            "workspace_id": "ws-1",
            "project_root": "/tmp/proj",
            "scanned_at": "2026-01-01T00:00:00",
            "git_sha": None,
            "structural_only": True,
            "file_count": 0,
            "node_count_total": 0,
            "node_count_projected": 0,
            "budget_tokens": 1024,
            "budget_used": 0,
            "budget_tolerance": 0.15,
            "language_counts": {},
            "skipped_files": [],
            "cartographer_version": "0.0.0",
            "tree_sitter_language_pack_version": "0.0.0",
            "tiktoken_version": "0.0.0",
            "networkx_version": "0.0.0",
            "fingerprint": "deadbeef",
            "elapsed_ms_parse": 0,
            "elapsed_ms_rank": 0,
            "elapsed_ms_project": 0,
        },
        "nodes": [],
        "rendered_map": "",
    }
    return gzip.compress(json.dumps(payload).encode("utf-8"))


def test_v1_cache_blob_raises_validation_error_from_bytes():
    blob = _v1_blob()
    with pytest.raises(ValidationError):
        ProjectAnalysis.from_bytes(blob)


# ─── Innovations (drift-guards adopted from Knight B per contract-lock) ────


class TestSchemaInnovations:
    """Drift-guards over Sage-locked schema-version contracts.

    Each test cites Sage memo section + v1 source line range it guards.
    """

    def test_schema_version_default_int_type(self) -> None:
        """Drift-guard: study_schema_version annotation is plain ``int``,
        NOT a narrowed ``Literal[2]`` or ``Annotated[int, ...]``.

        A ``Literal[2]`` narrowing would shift the v1-blob rejection error
        path from the ``_require_v2_schema`` ValueError (raised inside the
        validator at the model layer) to a Pydantic TYPE-coercion error
        (raised before the validator runs). Wave 2b cache fall-back
        semantics expect the validator-shape ValidationError; a type
        narrowing would silently change the error path even though both
        are still ``ValidationError`` subclasses — observable via the
        error message format and the validator-vs-typecoercion error
        location reported by Pydantic.

        Cites Sage §D4 "ProjectAnalysis — LOCKED — study_schema_version:
        int = Field(default=2)" + Sage §D3 "study_schema_version field
        name STAYS verbatim".

        Guards v1 source line:
        bonfire/src/bonfire/project/cartographer/models.py:200
        (``study_schema_version: int = Field(default=2)``).
        """
        field = ProjectAnalysis.model_fields["study_schema_version"]
        assert field.annotation is int

    @pytest.mark.parametrize("wrong_version", [0, 1, 99])
    def test_v1_blob_rejection_message_format(self, wrong_version: int) -> None:
        """Drift-guard: the validator's error message embeds the actual
        wrong value via the ``{v}`` f-string placeholder.

        Sweeps a small set of wrong-version values (0, 1, 99) and confirms
        for each:
          1. ``ProjectAnalysis.from_bytes(blob)`` raises ``ValidationError``.
          2. The error message contains the validator's EXACT phrase
             ``f"study_schema_version must be 2, got {wrong_version}"`` so
             dropping ``{v}`` from the f-string is caught (a substring digit
             check would pass spuriously because Pydantic's ValidationError
             representation also embeds ``input_value=<v>`` ambient).

        A refactor that drops ``{v}`` (e.g. switches to a static
        ``"study_schema_version must be 2"``) would silently lose the
        version diagnostic when Wave 2b's cache layer logs the rejection;
        the exact-phrase substring check fires immediately on that drift.

        Cites Sage §D4 "ProjectAnalysis — LOCKED — _require_v2_schema
        validator body" (the f-string format
        ``f"study_schema_version must be 2, got {v}"``).

        Guards v1 source line range:
        bonfire/src/bonfire/project/cartographer/models.py:212-220
        (validator body 215-219; raise ValueError line 219 with f-string).
        """
        blob = _v1_blob(version=wrong_version)
        with pytest.raises(ValidationError) as excinfo:
            ProjectAnalysis.from_bytes(blob)
        expected_phrase = f"study_schema_version must be 2, got {wrong_version}"
        assert expected_phrase in str(excinfo.value)
