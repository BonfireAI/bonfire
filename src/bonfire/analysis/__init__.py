# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Project analysis — Pydantic shapes + fingerprint for code-graph studies."""

from bonfire.analysis.fingerprint import compute_study_fingerprint
from bonfire.analysis.models import (
    CartographerBudget,
    GapFinding,
    NodeId,
    NodeKind,
    ProjectAnalysis,
    RankedNode,
    RelPath,
    StudyMetadata,
)

__all__ = [
    "CartographerBudget",
    "GapFinding",
    "NodeId",
    "NodeKind",
    "ProjectAnalysis",
    "RankedNode",
    "RelPath",
    "StudyMetadata",
    "compute_study_fingerprint",
]
