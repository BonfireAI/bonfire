"""RED tests for bonfire.analysis.models — BON-347 W6.1 (Knight A, CONSERVATIVE lens).

Project-analysis model contracts — port of v1 cartographer model RED tests.

Combines model-shape assertions from v1 ``test_cartographer_projector.py`` with
the BON-294 Wave 2c.1 enrichment-field RED tests from
``test_wave2c_ranked_node.py``.

Sage decision log: ``docs/audit/sage-decisions/bon-347-sage-20260425T230115Z.md``
Floor: 14 test definitions / 19 parametrize cells (per Sage §D6 Row 1).

No innovations — verbatim v1 port per ``feedback_conservative_wins_execution.md``.
Class rename ``ProjectStudy → ProjectAnalysis`` applied per ADR-001 §Class Renames.
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

# ─── Test fixture helpers (verbatim from v1 test_cartographer_projector.py:132-174) ──


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


# ─── Wave 2c.1 RankedNode kwargs (verbatim from v1 test_wave2c_ranked_node.py:14-25) ──

BASE_NODE_KWARGS = dict(
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


# ─── ProjectAnalysis / RankedNode / StudyMetadata contracts ────────────────


class TestProjectAnalysisContract:
    """ACs: ProjectAnalysis frozen, extra=forbid, study_schema_version default,
    nodes is a tuple, rendered_map is str, metadata is StudyMetadata."""

    def test_project_analysis_is_frozen(self):
        md = _valid_study_metadata()
        node = _valid_ranked_node()
        study = ProjectAnalysis(metadata=md, nodes=(node,), rendered_map="x")
        with pytest.raises(ValidationError):
            study.nodes = ()  # type: ignore[misc]

    def test_project_analysis_extra_forbid(self):
        md = _valid_study_metadata()
        with pytest.raises(ValidationError):
            ProjectAnalysis(
                metadata=md,
                nodes=(),
                rendered_map="",
                unknown_field="nope",  # type: ignore[call-arg]
            )

    def test_project_analysis_schema_version_default_is_two(self):
        md = _valid_study_metadata()
        study = ProjectAnalysis(metadata=md, nodes=(), rendered_map="")
        assert study.study_schema_version == 2

    def test_project_analysis_nodes_is_tuple(self):
        md = _valid_study_metadata()
        study = ProjectAnalysis(metadata=md, nodes=(_valid_ranked_node(),), rendered_map="")
        assert isinstance(study.nodes, tuple)


class TestRankedNodeContract:
    def test_ranked_node_is_frozen(self):
        n = _valid_ranked_node()
        with pytest.raises(ValidationError):
            n.snippet = "mutated"  # type: ignore[misc]


class TestStudyMetadataContract:
    def test_metadata_is_frozen(self):
        md = _valid_study_metadata()
        with pytest.raises(ValidationError):
            md.file_count = 99  # type: ignore[misc]


# ─── BON-294 Wave 2c.1 enrichment delta (verbatim from v1 test_wave2c_ranked_node.py:28-94) ──


def test_ranked_node_summary_defaults_to_none():
    node = RankedNode(**BASE_NODE_KWARGS)
    assert node.summary is None


def test_ranked_node_summary_source_defaults_to_none_literal():
    node = RankedNode(**BASE_NODE_KWARGS)
    assert node.summary_source == "none"


def test_ranked_node_summary_max_length_500_raises():
    with pytest.raises(ValidationError):
        RankedNode(
            **BASE_NODE_KWARGS,
            summary="x" * 501,
            summary_source="docstring",
        )


def test_ranked_node_summary_strip_validator_empty_becomes_none():
    node = RankedNode(
        **BASE_NODE_KWARGS,
        summary="   ",
        summary_source="none",
    )
    assert node.summary is None


def test_ranked_node_cross_field_none_forces_source_none():
    with pytest.raises((ValidationError, ValueError)):
        RankedNode(
            **BASE_NODE_KWARGS,
            summary=None,
            summary_source="docstring",
        )


def test_ranked_node_cross_field_populated_forbids_source_none():
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
def test_ranked_node_summary_source_literal_accepts_valid(source):
    summary = None if source == "none" else "hello"
    node = RankedNode(
        **BASE_NODE_KWARGS,
        summary=summary,
        summary_source=source,
    )
    assert node.summary_source == source


def test_ranked_node_summary_source_literal_rejects_invalid():
    with pytest.raises(ValidationError):
        RankedNode(
            **BASE_NODE_KWARGS,
            summary="hello",
            summary_source="not_a_source",
        )
