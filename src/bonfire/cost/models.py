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
