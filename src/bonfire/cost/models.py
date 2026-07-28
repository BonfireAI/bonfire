# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Cost ledger models — records and aggregation results."""

from __future__ import annotations

import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DEFAULT_LEDGER_PATH: Path = Path.home() / ".bonfire" / "cost" / "cost_ledger.jsonl"

#: Environment override naming the ledger file, honoured by BOTH ends.
LEDGER_PATH_ENV: str = "BONFIRE_COST_LEDGER_PATH"


def resolve_ledger_path() -> Path:
    """Return the ledger file this process should use.

    ``BONFIRE_COST_LEDGER_PATH`` wins; otherwise the home-directory default.

    This exists because the two ends of the ledger disagreed. ``bonfire cost``
    read the environment override; the writer took its path as a constructor
    default and never looked, so an operator who set the variable got a
    correctly-named file nobody wrote and a correctly-written file nobody
    read. Resolving both ends here makes the variable one knob rather than
    half of one.

    Read at call time, not at import: the writer is constructed inside a run,
    and freezing the answer at import would make the override depend on when
    the module happened to be first imported.

    The default deliberately stays under ``Path.home()``. It is a *cumulative*
    ledger — ``bonfire cost`` answers "Built by Bonfire for $X" across every
    project on the machine — so relocating the default per-target would
    silently fragment that history and orphan the ledgers users already have.
    """
    override = os.environ.get(LEDGER_PATH_ENV)
    return Path(override) if override else DEFAULT_LEDGER_PATH


class DispatchRecord(BaseModel):
    """One agent dispatch with its cost."""

    type: Literal["dispatch"] = "dispatch"
    timestamp: float
    session_id: str
    agent_name: str
    cost_usd: float
    duration_seconds: float
    model: str = ""


class PipelineRecord(BaseModel):
    """One pipeline run with total cost, and how that run ENDED.

    ``outcome`` exists because a halt and a completion used to write
    byte-identical rows apart from ``timestamp``. A run that died in
    the builder and a run that finished one stage both landed as
    ``stages_completed=1``, so ``bonfire cost`` — the operator's record
    of what they were charged and why — could report spend but could
    not say whether the money bought a finished run or a crash.

    ``failed_stage`` and ``error_message`` carry the reason across from
    ``PipelineFailed`` rather than being re-derived, so the ledger
    states the cause that actually occurred instead of an inferred one.

    Migration: the default is ``"unknown"``, NOT ``"completed"``. Rows
    written before this field existed genuinely do not record how the
    run ended, and defaulting them to success would fabricate exactly
    the history this defect corrupted. ``CostAnalyzer`` does not list
    ``outcome`` in ``_PIPELINE_REQUIRED_FIELDS``, so those rows keep
    validating and keep aggregating unchanged; they simply decline to
    claim an outcome nobody recorded.
    """

    type: Literal["pipeline"] = "pipeline"
    timestamp: float
    session_id: str
    total_cost_usd: float
    duration_seconds: float
    stages_completed: int
    outcome: Literal["completed", "failed", "unknown"] = "unknown"
    failed_stage: str | None = None
    error_message: str | None = None


class SessionCost(BaseModel):
    """Aggregated cost for a single session."""

    session_id: str
    total_cost_usd: float
    duration_seconds: float
    dispatches: list[DispatchRecord]
    stages_completed: int
    timestamp: float

    @property
    def date(self) -> str:
        """ISO date string (YYYY-MM-DD) derived from timestamp."""
        return datetime.fromtimestamp(self.timestamp, tz=UTC).strftime("%Y-%m-%d")


class AgentCost(BaseModel):
    """Cumulative cost for one agent across all sessions."""

    agent_name: str
    total_cost_usd: float
    dispatch_count: int
    avg_cost_usd: float


class ModelCost(BaseModel):
    """Cumulative cost for one model across all sessions."""

    model: str
    total_cost_usd: float
    dispatch_count: int
    total_duration_seconds: float
