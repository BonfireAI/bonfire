# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Session state tracking — mutable, in-memory."""

from __future__ import annotations

import time


class SessionState:
    """Mutable session state with cost and duration tracking."""

    def __init__(
        self,
        session_id: str,
        plan_name: str,
        workflow_type: str,
    ) -> None:
        self._session_id = session_id
        self._plan_name = plan_name
        self._workflow_type = workflow_type
        self._is_active = False
        self._total_cost_usd = 0.0
        self._stages_completed = 0
        self._status: str = "pending"
        self._completed_stages: list[str] = []
        self._start_time: float | None = None
        self._end_time: float | None = None

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def plan_name(self) -> str:
        return self._plan_name

    @property
    def workflow_type(self) -> str:
        return self._workflow_type

    @property
    def is_active(self) -> bool:
        return self._is_active

    @property
    def total_cost_usd(self) -> float:
        return self._total_cost_usd

    @property
    def stages_completed(self) -> int:
        return self._stages_completed

    @property
    def duration_seconds(self) -> float | None:
        if self._start_time is None:
            return None
        end = self._end_time if self._end_time is not None else time.monotonic()
        return end - self._start_time

    def start(self) -> None:
        """Mark session as active and record start time."""
        self._is_active = True
        self._start_time = time.monotonic()

    @property
    def status(self) -> str:
        return self._status

    def record_stage(self, stage_name: str, cost_usd: float) -> None:
        """Record a completed stage with its cost."""
        self._completed_stages.append(stage_name)
        self._total_cost_usd += cost_usd
        self._stages_completed += 1

    def end(self, status: str = "completed") -> None:
        """Mark session as inactive and record end time."""
        self._is_active = False
        self._end_time = time.monotonic()
        self._status = status

    def to_dict(self) -> dict:
        """Serialize all fields to a plain dict."""
        return {
            "session_id": self._session_id,
            "plan_name": self._plan_name,
            "workflow_type": self._workflow_type,
            "is_active": self._is_active,
            "total_cost_usd": self._total_cost_usd,
            "stages_completed": self._stages_completed,
            "duration_seconds": self.duration_seconds,
            "status": self._status,
            "completed_stages": list(self._completed_stages),
        }
