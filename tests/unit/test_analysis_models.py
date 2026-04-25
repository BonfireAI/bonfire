"""RED tests for bonfire.analysis.models — BON-347 W6.1 (Knight B, INNOVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-347-sage-20260425T230115Z.md

Floor (14 tests, per Sage §D6 Row 1): port v1 cartographer model-layer test
surface verbatim. Combines salvaged contract tests from v1
``test_cartographer_projector.py`` (6 tests, with `ProjectStudy → ProjectAnalysis`
rename in test method names per Sage §D3) with the BON-294 Wave 2c.1
``test_wave2c_ranked_node.py`` body (8 tests verbatim — RankedNode unchanged).

Innovations (2 tests, INNOVATIVE lens additions over Sage floor):

  * ``test_project_analysis_field_order_stable`` — assert
    ``ProjectAnalysis.model_fields.keys()`` is the verbatim 5-tuple ordering
    locked by Sage. Drift-guards against accidental field reordering inside
    the model body (Pydantic preserves declaration order for both schema
    export AND json serialization). Cites Sage §D4 "ProjectAnalysis — LOCKED"
    + Sage §D8 "Class definition ORDER is fixed" + v1 source
    ``bonfire/src/bonfire/project/cartographer/models.py:200-210`` (field
    declarations 200-210: study_schema_version, metadata, nodes, rendered_map,
    gaps).

  * ``test_project_analysis_bytes_stable_through_json_roundtrip`` — assert
    ``ProjectAnalysis(...).to_bytes()`` then ``from_bytes`` reconstructs an
    equal model. Drift-guards the gzip+JSON envelope contract: the two-byte
    gzip magic header (``\\x1f\\x8b``) lets cache layers sniff the envelope
    without deserialising, and ``from_bytes`` must invert ``to_bytes`` for any
    shape constructible from valid inputs. Analogous to the BON-344 Innovation
    2 byte-stability pattern. Cites Sage §D4 "ProjectAnalysis — LOCKED"
    (to_bytes/from_bytes signatures) + v1 source
    ``bonfire/src/bonfire/project/cartographer/models.py:222-246`` (to_bytes
    body 222-234, from_bytes body 236-246).

Imports are RED — ``bonfire.analysis.models`` does not exist until Warriors
port v1 ``bonfire/src/bonfire/project/cartographer/models.py`` per Sage §D9.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from bonfire.analysis.models import (
    ProjectAnalysis,
    RankedNode,
    StudyMetadata,
)

# ─── Test fixture helpers (Sage §D6 — copy verbatim from v1) ─────────────


def _valid_study_metadata(**overrides: Any) -> StudyMetadata:
    defaults: dict[str, Any] = dict(
        workspace_id="ws-1",
        project_root=Path("/tmp/fake"),
        scanned_at=datetime.datetime(2026, 4, 14, 0, 0, 0),
        git_sha=None,
        structural_only=False,
        file_count=1,
        node_count_total=1,
        node_count_projected=1,
        budget_tokens=1024,
        budget_used=100,
        budget_tolerance=0.15,
        language_counts={"python": 1},
        skipped_files=(),
        cartographer_version="0.0.1",
        tree_sitter_language_pack_version="0.0.1",
        tiktoken_version="0.0.1",
        networkx_version="0.0.1",
        fingerprint="fp-1",
        elapsed_ms_parse=1,
        elapsed_ms_rank=1,
        elapsed_ms_project=1,
    )
    defaults.update(overrides)
    return StudyMetadata(**defaults)


def _valid_ranked_node(**overrides: Any) -> RankedNode:
    defaults: dict[str, Any] = dict(
        node_id="a.py::foo",
        kind="function",
        path="a.py",
        line_start=1,
        line_end=3,
        snippet="def foo():\n    return 1\n",
        tokens=5,
        file_rank=0.5,
        symbol_rank=0.3,
        edge_weight_in=0.1,
    )
    defaults.update(overrides)
    return RankedNode(**defaults)


# ─── Floor (Sage §D6 Row 1) — Source A: salvaged from v1 projector tests ─


class TestProjectAnalysisContract:
    """ACs: ProjectAnalysis frozen, extra=forbid, study_schema_version default,
    nodes is a tuple, rendered_map is str, metadata is StudyMetadata."""

    def test_project_analysis_is_frozen(self) -> None:
        md = _valid_study_metadata()
        node = _valid_ranked_node()
        study = ProjectAnalysis(metadata=md, nodes=(node,), rendered_map="x")
        with pytest.raises(ValidationError):
            study.nodes = ()  # type: ignore[misc]

    def test_project_analysis_extra_forbid(self) -> None:
        md = _valid_study_metadata()
        with pytest.raises(ValidationError):
            ProjectAnalysis(
                metadata=md,
                nodes=(),
                rendered_map="",
                unknown_field="nope",  # type: ignore[call-arg]
            )

    def test_project_analysis_schema_version_default_is_two(self) -> None:
        md = _valid_study_metadata()
        study = ProjectAnalysis(metadata=md, nodes=(), rendered_map="")
        assert study.study_schema_version == 2

    def test_project_analysis_nodes_is_tuple(self) -> None:
        md = _valid_study_metadata()
        study = ProjectAnalysis(metadata=md, nodes=(_valid_ranked_node(),), rendered_map="")
        assert isinstance(study.nodes, tuple)


class TestRankedNodeContract:
    def test_ranked_node_is_frozen(self) -> None:
        n = _valid_ranked_node()
        with pytest.raises(ValidationError):
            n.snippet = "mutated"  # type: ignore[misc]


class TestStudyMetadataContract:
    def test_metadata_is_frozen(self) -> None:
        md = _valid_study_metadata()
        with pytest.raises(ValidationError):
            md.file_count = 99  # type: ignore[misc]


# ─── Floor (Sage §D6 Row 1) — Source B: verbatim from v1 wave2c ranked_node ─


BASE_NODE_KWARGS: dict[str, Any] = dict(
    node_id="src/f.py::f",
    kind="function",
    path="src/f.py",
    line_start=1,
    line_end=5,
    snippet="def f(): pass",
    tokens=3,
    file_rank=0.5,
    symbol_rank=0.5,
    edge_weight_in=0.1,
)


def test_ranked_node_summary_defaults_to_none() -> None:
    node = RankedNode(**BASE_NODE_KWARGS)
    assert node.summary is None


def test_ranked_node_summary_source_defaults_to_none_literal() -> None:
    node = RankedNode(**BASE_NODE_KWARGS)
    assert node.summary_source == "none"


def test_ranked_node_summary_max_length_500_raises() -> None:
    with pytest.raises(ValidationError):
        RankedNode(
            **BASE_NODE_KWARGS,
            summary="x" * 501,
            summary_source="docstring",
        )


def test_ranked_node_summary_strip_validator_empty_becomes_none() -> None:
    node = RankedNode(
        **BASE_NODE_KWARGS,
        summary="   ",
        summary_source="none",
    )
    assert node.summary is None


def test_ranked_node_cross_field_none_forces_source_none() -> None:
    with pytest.raises((ValidationError, ValueError)):
        RankedNode(
            **BASE_NODE_KWARGS,
            summary=None,
            summary_source="docstring",
        )


def test_ranked_node_cross_field_populated_forbids_source_none() -> None:
    with pytest.raises((ValidationError, ValueError)):
        RankedNode(
            **BASE_NODE_KWARGS,
            summary="hello",
            summary_source="none",
        )


@pytest.mark.parametrize(
    "source",
    ["docstring", "module_doc", "readme", "git_log", "llm", "none"],
)
def test_ranked_node_summary_source_literal_accepts_valid(source: str) -> None:
    summary = None if source == "none" else "hello"
    node = RankedNode(
        **BASE_NODE_KWARGS,
        summary=summary,
        summary_source=source,
    )
    assert node.summary_source == source


def test_ranked_node_summary_source_literal_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        RankedNode(
            **BASE_NODE_KWARGS,
            summary="hello",
            summary_source="not_a_source",
        )


# ─── Innovations (INNOVATIVE lens — 2 drift-guards) ─────────────────────


class TestProjectAnalysisInnovations:
    """Innovative-lens drift-guards over Sage-locked ProjectAnalysis contracts.

    Each test cites Sage memo section + v1 source line range it guards.
    """

    def test_project_analysis_field_order_stable(self) -> None:
        """Drift-guard: ProjectAnalysis fields declared in EXACT 5-tuple order.

        Pydantic preserves declaration order in both ``model_fields`` and
        ``model_dump_json`` output, which means a future refactor that
        reorders fields silently changes the canonical JSON byte stream
        produced by ``to_bytes`` (Wave 2b cache key seam — §12 C3).

        Cites Sage §D4 "ProjectAnalysis — LOCKED (per v1 models.py:195-246)
        — 5 fields. Field ordering verbatim." + Sage §D8 "Class definition
        ORDER is fixed."

        Guards v1 source line range:
        bonfire/src/bonfire/project/cartographer/models.py:200-210
        (study_schema_version=200, metadata=201, nodes=202, rendered_map=205,
        gaps=210).
        """
        assert tuple(ProjectAnalysis.model_fields.keys()) == (
            "study_schema_version",
            "metadata",
            "nodes",
            "rendered_map",
            "gaps",
        )

    def test_project_analysis_bytes_stable_through_json_roundtrip(self) -> None:
        """Drift-guard: to_bytes/from_bytes is a true inverse pair.

        Builds a minimal valid ProjectAnalysis, serializes via ``to_bytes``
        (gzip-wrapped JSON, two-byte ``\\x1f\\x8b`` magic header), then
        rehydrates via ``from_bytes`` and asserts model equality. Drift-
        guards the Wave 2b cache envelope contract: any change that breaks
        the round-trip silently invalidates every cached study.

        Cites Sage §D4 "ProjectAnalysis — LOCKED — TWO methods (to_bytes,
        from_bytes) + ONE field validator. Both methods carry lazy
        ``import gzip`` with ``# noqa: PLC0415``."

        Guards v1 source line range:
        bonfire/src/bonfire/project/cartographer/models.py:222-246
        (to_bytes body 222-234 with gzip.compress + compresslevel=6;
        from_bytes body 236-246 with gzip.decompress + model_validate_json).

        Analogous to BON-344 Innovation 2 (frozen Pydantic JSON byte-
        stability pattern).
        """
        md = _valid_study_metadata()
        node = _valid_ranked_node()
        original = ProjectAnalysis(metadata=md, nodes=(node,), rendered_map="x")

        blob = original.to_bytes()
        # Two-byte gzip magic header — §D4 to_bytes docstring guarantees this.
        assert blob[:2] == b"\x1f\x8b"

        rehydrated = ProjectAnalysis.from_bytes(blob)
        assert rehydrated == original
