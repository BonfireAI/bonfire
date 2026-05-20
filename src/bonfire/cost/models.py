# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Cost ledger models — records and aggregation results."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DEFAULT_LEDGER_PATH: Path = Path.home() / ".bonfire" / "cost" / "cost_ledger.jsonl"


class DispatchRecord(BaseModel):
    """One agent dispatch with its cost.

    ``status`` discriminates success (``"completed"``) from failure
    (``"failed"``) rows. Defaults to ``"completed"`` so pre-Scout-2
    ledger rows on disk (written before the failure-path consumer was
    wired) parse cleanly under the new schema — history-is-sacred.

    Mirror N+7 Scout-2 (HIGH-1): ``CostLedgerConsumer`` now persists
    ``DispatchFailed`` rows alongside ``DispatchCompleted``, so
    downstream ``CostAnalyzer.agent_costs()`` / ``model_costs()``
    no longer undercount failure-path spend.
    """

    type: Literal["dispatch"] = "dispatch"
    timestamp: float
    session_id: str
    agent_name: str
    cost_usd: float
    duration_seconds: float
    model: str = ""
    status: Literal["completed", "failed"] = "completed"


class PipelineRecord(BaseModel):
    """One pipeline completion with total cost."""

    type: Literal["pipeline"] = "pipeline"
    timestamp: float
    session_id: str
    total_cost_usd: float
    duration_seconds: float
    stages_completed: int


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
