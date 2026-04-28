"""Cost analyzer — read-only query layer over the JSONL ledger."""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path

from bonfire.cost.models import (
    DEFAULT_LEDGER_PATH,
    AgentCost,
    DispatchRecord,
    ModelCost,
    PipelineRecord,
    SessionCost,
)

logger = logging.getLogger(__name__)


class CostAnalyzer:
    """Reads the cost ledger and computes aggregations on demand."""

    def __init__(self, ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
        self._ledger_path = Path(ledger_path)

    def _read_records(
        self,
    ) -> tuple[list[DispatchRecord], list[PipelineRecord]]:
        """Read and parse all records from the ledger file."""
        dispatches: list[DispatchRecord] = []
        pipelines: list[PipelineRecord] = []

        if not self._ledger_path.exists():
            return dispatches, pipelines

        with self._ledger_path.open("r", encoding="utf-8") as fh:
            for line_num, line in enumerate(fh, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning("Skipping malformed line %d in %s", line_num, self._ledger_path)
                    continue

                record_type = data.get("type")
                try:
                    if record_type == "dispatch":
                        dispatches.append(DispatchRecord.model_validate(data))
                    elif record_type == "pipeline":
                        pipelines.append(PipelineRecord.model_validate(data))
                    else:
                        logger.warning("Unknown record type %r on line %d", record_type, line_num)
                except (ValueError, KeyError, TypeError):
                    logger.warning(
                        "Skipping invalid record on line %d in %s",
                        line_num,
                        self._ledger_path,
                    )

        return dispatches, pipelines

    def cumulative_cost(self) -> float:
        """Grand total USD across all pipeline records."""
        _, pipelines = self._read_records()
        return sum(p.total_cost_usd for p in pipelines)

    def session_cost(self, session_id: str) -> SessionCost | None:
        """Cost breakdown for a single session."""
        dispatches, pipelines = self._read_records()
        return self._build_session_cost(session_id, dispatches, pipelines)

    @staticmethod
    def _build_session_cost(
        session_id: str,
        dispatches: list[DispatchRecord],
        pipelines: list[PipelineRecord],
    ) -> SessionCost | None:
        """Build a SessionCost from pre-read records."""
        session_dispatches = [d for d in dispatches if d.session_id == session_id]
        session_pipeline = next((p for p in pipelines if p.session_id == session_id), None)

        if not session_dispatches and session_pipeline is None:
            return None

        total = (
            session_pipeline.total_cost_usd
            if session_pipeline
            else sum(d.cost_usd for d in session_dispatches)
        )
        duration = (
            session_pipeline.duration_seconds
            if session_pipeline
            else sum(d.duration_seconds for d in session_dispatches)
        )
        stages = session_pipeline.stages_completed if session_pipeline else 0
        timestamp = (
            session_pipeline.timestamp
            if session_pipeline
            else (session_dispatches[0].timestamp if session_dispatches else 0.0)
        )

        return SessionCost(
            session_id=session_id,
            total_cost_usd=total,
            duration_seconds=duration,
            dispatches=session_dispatches,
            stages_completed=stages,
            timestamp=timestamp,
        )

    def agent_costs(self) -> list[AgentCost]:
        """Cumulative cost per agent, sorted by spend descending."""
        dispatches, _ = self._read_records()

        by_agent: dict[str, list[DispatchRecord]] = defaultdict(list)
        for d in dispatches:
            by_agent[d.agent_name].append(d)

        results = []
        for agent_name, records in by_agent.items():
            total = sum(r.cost_usd for r in records)
            count = len(records)
            results.append(
                AgentCost(
                    agent_name=agent_name,
                    total_cost_usd=total,
                    dispatch_count=count,
                    avg_cost_usd=total / count if count else 0.0,
                )
            )

        results.sort(key=lambda a: a.total_cost_usd, reverse=True)
        return results

    def model_costs(self) -> list[ModelCost]:
        """Cumulative cost per model, sorted by spend descending.

        Records lacking a ``model`` string (legacy or unattributed) are
        grouped under ``model=""``. The empty-string bucket is preserved as
        a visible row so operators can see how much spend predates per-model
        attribution -- silent dropout would mislead post-migration audits.
        """
        dispatches, _ = self._read_records()

        by_model: dict[str, list[DispatchRecord]] = defaultdict(list)
        for d in dispatches:
            by_model[d.model].append(d)

        results = [
            ModelCost(
                model=model_name,
                total_cost_usd=sum(r.cost_usd for r in records),
                dispatch_count=len(records),
                total_duration_seconds=sum(r.duration_seconds for r in records),
            )
            for model_name, records in by_model.items()
        ]
        results.sort(key=lambda m: m.total_cost_usd, reverse=True)
        return results

    def all_sessions(self) -> list[SessionCost]:
        """All sessions with their costs, sorted by timestamp descending.

        Groups dispatches and pipelines by session_id in a single pass each,
        then builds SessionCost objects from the grouped data — O(M) total.
        """
        dispatches, pipelines = self._read_records()

        # Group dispatches by session_id in a single pass
        dispatches_by_session: dict[str, list[DispatchRecord]] = defaultdict(list)
        for d in dispatches:
            dispatches_by_session[d.session_id].append(d)

        # Group pipelines by session_id in a single pass (last write wins
        # — a retried PipelineCompleted event overrides the earlier record).
        pipelines_by_session: dict[str, PipelineRecord] = {}
        for p in pipelines:
            pipelines_by_session[p.session_id] = p

        # Build SessionCost objects from grouped data
        all_session_ids = set(dispatches_by_session) | set(pipelines_by_session)
        sessions = []
        for sid in all_session_ids:
            session_dispatches = dispatches_by_session.get(sid, [])
            session_pipeline = pipelines_by_session.get(sid)

            total = (
                session_pipeline.total_cost_usd
                if session_pipeline
                else sum(d.cost_usd for d in session_dispatches)
            )
            duration = (
                session_pipeline.duration_seconds
                if session_pipeline
                else sum(d.duration_seconds for d in session_dispatches)
            )
            stages = session_pipeline.stages_completed if session_pipeline else 0
            timestamp = (
                session_pipeline.timestamp
                if session_pipeline
                else (session_dispatches[0].timestamp if session_dispatches else 0.0)
            )

            sessions.append(
                SessionCost(
                    session_id=sid,
                    total_cost_usd=total,
                    duration_seconds=duration,
                    dispatches=session_dispatches,
                    stages_completed=stages,
                    timestamp=timestamp,
                )
            )

        sessions.sort(key=lambda s: s.timestamp, reverse=True)
        return sessions

    def all_records(self) -> list[DispatchRecord | PipelineRecord]:
        """All ledger records sorted by timestamp. For export."""
        dispatches, pipelines = self._read_records()
        records: list[DispatchRecord | PipelineRecord] = [*dispatches, *pipelines]
        records.sort(key=lambda r: r.timestamp)
        return records
