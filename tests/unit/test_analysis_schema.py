"""RED tests for bonfire.analysis.models schema-version contract — BON-347 W6.1 (Knight B, INNOVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-347-sage-20260425T230115Z.md

Floor (2 tests, per Sage §D6 Row 2): port v1 cartographer ``test_wave2c_project_study_schema.py``
verbatim with class rename ``ProjectStudy → ProjectAnalysis`` per ADR-001.
The FIELD name ``study_schema_version`` is unchanged per Sage §D3 (the
v1 cache-blob fixture embeds the literal ``"study_schema_version": 1``
inside the gzipped JSON payload — invariant).

Innovations (2 tests, INNOVATIVE lens additions over Sage floor):

  * ``test_schema_version_default_int_type`` — assert
    ``ProjectAnalysis.model_fields["study_schema_version"].annotation is int``
    (NOT ``Literal[2]``). Drift-guards against type narrowing: a refactor
    that "tightens" the field to ``Literal[2]`` would break the v1-blob
    rejection contract because Pydantic would reject ``study_schema_version=1``
    at TYPE-coercion time (TypeError-shape) instead of at the
    ``_require_v2_schema`` validator (ValueError-shape ValidationError),
    breaking Wave 2b cache fall-back semantics that pin the validator's
    error path. Cites Sage §D4 "ProjectAnalysis — LOCKED — study_schema_version:
    int = Field(default=2)" + Sage §D3 "study_schema_version field name
    STAYS verbatim". Guards v1 source line range:
    bonfire/src/bonfire/project/cartographer/models.py:200 (field decl) +
    models.py:212-220 (validator body).

  * ``test_v1_blob_rejection_message_format`` — parametrized sweep over
    wrong-version values (0, 1, 99); for each, assert that loading the
    crafted v1-shape blob via ``from_bytes`` raises ``ValidationError``
    AND that the error message contains the actual wrong value present
    in the payload. Drift-guards the ``_require_v2_schema`` validator's
    f-string error format (``f"study_schema_version must be 2, got {v}"``)
    — a refactor that drops ``{v}`` from the message would silently lose
    diagnostic value when Wave 2b cache logs the rejection. Cites
    Sage §D4 "ProjectAnalysis — LOCKED — _require_v2_schema validator body".
    Guards v1 source line range:
    bonfire/src/bonfire/project/cartographer/models.py:212-220
    (validator body lines 215-219; raise ValueError line 219).

Imports are RED — ``bonfire.analysis.models`` does not exist until Warriors
port v1 ``bonfire/src/bonfire/project/cartographer/models.py`` per Sage §D9.
"""

from __future__ import annotations

import gzip
import json

import pytest
from pydantic import ValidationError

from bonfire.analysis.models import ProjectAnalysis


# ─── Floor (Sage §D6 Row 2) — verbatim v1 with class rename ──────────────


def test_project_analysis_schema_version_defaults_to_2() -> None:
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


def test_v1_cache_blob_raises_validation_error_from_bytes() -> None:
    blob = _v1_blob()
    with pytest.raises(ValidationError):
        ProjectAnalysis.from_bytes(blob)


# ─── Innovations (INNOVATIVE lens — 2 drift-guards) ─────────────────────


class TestSchemaInnovations:
    """Innovative-lens drift-guards over Sage-locked schema-version contracts.

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
          2. The error message contains the actual ``wrong_version`` value
             so log output stays diagnostic.

        A refactor that drops ``{v}`` (e.g. switches to a static
        ``"study_schema_version must be 2"``) would silently lose the
        version diagnostic when Wave 2b's cache layer logs the rejection.

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
        assert str(wrong_version) in str(excinfo.value)
