"""RED tests for bonfire.analysis.models — BON-347 W6.1 (Knight A, CONSERVATIVE lens).

ProjectAnalysis schema-version v2 contract.

Port of v1 ``test_wave2c_project_study_schema.py`` with class rename
``ProjectStudy → ProjectAnalysis`` per ADR-001.

Amendment A10: a v1 cache blob must fail to load under the new schema
so that Wave 2b cache reads fall back to a fresh scan instead of
silently returning a study with missing enrichment fields.

Sage decision log: ``docs/audit/sage-decisions/bon-347-sage-20260425T230115Z.md``
Floor: 2 test definitions / 2 parametrize cells (per Sage §D6 Row 2).

No innovations — verbatim v1 port per ``feedback_conservative_wins_execution.md``.
The JSON field name ``study_schema_version`` is unchanged per Sage §D3.
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


def _v1_blob() -> bytes:
    """Construct a raw gzip-wrapped JSON payload with study_schema_version=1.

    Everything else in the payload is shaped to be otherwise-valid under
    the v2 schema so the ONLY thing that should trip validation is the
    version field itself (once v2 enforces it).
    """
    payload = {
        "study_schema_version": 1,
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
