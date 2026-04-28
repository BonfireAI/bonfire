"""Cost ledger models — records and aggregation results."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

DEFAULT_LEDGER_PATH: Path = Path.home() / ".bonfire" / "cost" / "cost_ledger.jsonl"


class DispatchRecord(BaseModel):
    """One agent dispatch with its cost."""

    type: Literal["dispatch"] = "dispatch"
    timestamp: float
    session_id: str
    agent_name: str
    cost_usd: float
    duration_seconds: float
    # Per-model attribution. Default keeps legacy JSONL rows parseable;
    # the empty-string bucket is preserved (visible) by ``model_costs()``.
    model: str = ""


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
    """Cumulative cost for one model across all sessions.

    Mirrors ``AgentCost`` shape (name-key + total + count + secondary).
    The secondary metric is total burn-time, not average -- average is
    derivable as ``total_cost_usd / dispatch_count`` while burn-time per
    model is operationally interesting in its own right.
    """

    model: str
    total_cost_usd: float
    dispatch_count: int
    total_duration_seconds: float
