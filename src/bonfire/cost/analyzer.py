# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Cost analyzer -- read-only query layer over the JSONL ledger.

Reads the ledger at most once per :class:`CostAnalyzer` instance and caches
both the parsed raw dicts and (lazily) the validated Pydantic records.

* The cache invalidates when the ledger's ``(mtime, size)`` signature changes,
  so an append between calls is observed without forcing every call to re-read.
* Read-only aggregations (:py:meth:`cumulative_cost`, :py:meth:`agent_costs`,
  :py:meth:`model_costs`) work directly off the raw dicts and avoid the
  per-record Pydantic ``model_validate`` cost on long ledgers.
* Methods that return typed models (:py:meth:`session_cost`,
  :py:meth:`all_sessions`, :py:meth:`all_records`) lazily validate, with the
  result memoized for the cache lifetime.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

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
        # Cache signature: (mtime, size). ``None`` means cache is empty.
        self._cache_signature: tuple[float, int] | None = None
        # Raw parsed dicts split by record type. Survive across calls until
        # the ledger's (mtime, size) changes.
        self._raw_dispatches: list[dict[str, Any]] = []
        self._raw_pipelines: list[dict[str, Any]] = []
        # Lazily computed validated record lists. Reset whenever the raw
        # cache reloads.
        self._validated_dispatches: list[DispatchRecord] | None = None
        self._validated_pipelines: list[PipelineRecord] | None = None

    # Required field-name sets for each record type. Used by the raw-dict
    # aggregation paths to skip schema-invalid lines without invoking the
    # per-record Pydantic ``model_validate`` cost.
    _DISPATCH_REQUIRED_FIELDS = (
        "timestamp",
        "session_id",
        "agent_name",
        "cost_usd",
        "duration_seconds",
    )
    _DISPATCH_NUMERIC_FIELDS = ("timestamp", "cost_usd", "duration_seconds")
    _PIPELINE_REQUIRED_FIELDS = (
        "timestamp",
        "session_id",
        "total_cost_usd",
        "duration_seconds",
        "stages_completed",
    )
    _PIPELINE_NUMERIC_FIELDS = (
        "timestamp",
        "total_cost_usd",
        "duration_seconds",
        "stages_completed",
    )

    @staticmethod
    def _is_floatable(value: Any) -> bool:
        """True iff ``float(value)`` would succeed.

        The raw-dict aggregation paths call ``float()`` on these fields; a
        non-numeric value (e.g. a malformed ledger row with ``cost_usd: null``
        or ``"n/a"``) would otherwise raise and crash the whole aggregation.
        Skipping such rows matches the prior ``model_validate``-then-skip
        behaviour without paying Pydantic on the hot path.
        """
        try:
            float(value)
        except (TypeError, ValueError):
            return False
        return True

    @classmethod
    def _dispatch_is_valid(cls, data: dict[str, Any]) -> bool:
        """Cheap schema check: required ``DispatchRecord`` fields are present
        and numeric fields are float-coercible.

        Mirrors the prior ``model_validate``-then-skip behaviour for callers
        that aggregate off the raw dicts. Same skip semantics, no Pydantic
        cost on the hot path.
        """
        if not all(field in data for field in cls._DISPATCH_REQUIRED_FIELDS):
            return False
        return all(cls._is_floatable(data[field]) for field in cls._DISPATCH_NUMERIC_FIELDS)

    @classmethod
    def _pipeline_is_valid(cls, data: dict[str, Any]) -> bool:
        """Cheap schema check: required ``PipelineRecord`` fields are present
        and numeric fields are float-coercible."""
        if not all(field in data for field in cls._PIPELINE_REQUIRED_FIELDS):
            return False
        return all(cls._is_floatable(data[field]) for field in cls._PIPELINE_NUMERIC_FIELDS)

    def _current_signature(self) -> tuple[float, int] | None:
        """Return ``(mtime, size)`` for the ledger, or ``None`` if absent.

        Uses ``stat()`` (not ``open``) so the open-count tests stay honest --
        the cache check itself never opens the file.
        """
        try:
            st = self._ledger_path.stat()
        except FileNotFoundError:
            return None
        return (st.st_mtime, st.st_size)

    def _load_if_needed(self) -> None:
        """Read the ledger if it has changed since the last load.

        Caches parsed dicts under ``_raw_dispatches`` / ``_raw_pipelines`` and
        invalidates the validated-record memos so the next typed-access call
        rebuilds them.
        """
        sig = self._current_signature()
        if sig is None:
            # Ledger is missing -- clear any prior cache.
            if (
                self._cache_signature is not None
                or self._raw_dispatches
                or self._raw_pipelines
                or self._validated_dispatches is not None
                or self._validated_pipelines is not None
            ):
                self._cache_signature = None
                self._raw_dispatches = []
                self._raw_pipelines = []
                self._validated_dispatches = None
                self._validated_pipelines = None
            return
        if self._cache_signature == sig:
            return

        raw_dispatches: list[dict[str, Any]] = []
        raw_pipelines: list[dict[str, Any]] = []
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
                if record_type == "dispatch":
                    raw_dispatches.append(data)
                elif record_type == "pipeline":
                    raw_pipelines.append(data)
                else:
                    logger.warning("Unknown record type %r on line %d", record_type, line_num)

        self._raw_dispatches = raw_dispatches
        self._raw_pipelines = raw_pipelines
        self._cache_signature = sig
        # The newly-loaded raw cache invalidates any prior validated memos.
        self._validated_dispatches = None
        self._validated_pipelines = None

    def _validated_dispatch_records(self) -> list[DispatchRecord]:
        """Lazily validate the cached raw dispatch dicts.

        Invalid records (those that fail Pydantic validation) are skipped
        with a warning -- the read-side has always been forgiving of legacy
        or malformed rows. The memo lives for the lifetime of the current
        ``_cache_signature``.
        """
        if self._validated_dispatches is not None:
            return self._validated_dispatches
        validated: list[DispatchRecord] = []
        for idx, data in enumerate(self._raw_dispatches, 1):
            try:
                validated.append(DispatchRecord.model_validate(data))
            except (ValueError, KeyError, TypeError):
                logger.warning("Skipping invalid dispatch record %d in %s", idx, self._ledger_path)
        self._validated_dispatches = validated
        return validated

    def _validated_pipeline_records(self) -> list[PipelineRecord]:
        """Lazily validate the cached raw pipeline dicts."""
        if self._validated_pipelines is not None:
            return self._validated_pipelines
        validated: list[PipelineRecord] = []
        for idx, data in enumerate(self._raw_pipelines, 1):
            try:
                validated.append(PipelineRecord.model_validate(data))
            except (ValueError, KeyError, TypeError):
                logger.warning("Skipping invalid pipeline record %d in %s", idx, self._ledger_path)
        self._validated_pipelines = validated
        return validated

    def cumulative_cost(self) -> float:
        """Grand total USD across all pipeline records.

        Aggregates directly off the raw cached dicts -- the field is a flat
        ``float`` and does not require Pydantic validation per record. Lines
        missing any required ``PipelineRecord`` field are skipped (matching
        the prior ``model_validate``-then-skip behaviour).
        """
        self._load_if_needed()
        return sum(
            float(r["total_cost_usd"]) for r in self._raw_pipelines if self._pipeline_is_valid(r)
        )

    def session_cost(self, session_id: str) -> SessionCost | None:
        """Cost breakdown for a single session."""
        self._load_if_needed()
        dispatches = self._validated_dispatch_records()
        pipelines = self._validated_pipeline_records()
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
        """Cumulative cost per agent, sorted by spend descending.

        Aggregates off the raw cached dicts -- avoids per-record Pydantic
        validation on the read-only hot path. Lines missing any required
        ``DispatchRecord`` field are skipped.
        """
        self._load_if_needed()

        by_agent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for d in self._raw_dispatches:
            if not self._dispatch_is_valid(d):
                continue
            agent_name = str(d["agent_name"])
            by_agent[agent_name].append(d)

        results: list[AgentCost] = []
        for agent_name, records in by_agent.items():
            total = sum(float(r["cost_usd"]) for r in records)
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

        Records lacking a model string (legacy or unattributed) are grouped
        under model="". Empty-string is preserved as a visible bucket --
        operators want to see how much spend predates per-model attribution.

        Aggregates off the raw cached dicts -- avoids per-record Pydantic
        validation on the read-only hot path.
        """
        self._load_if_needed()

        by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for d in self._raw_dispatches:
            if not self._dispatch_is_valid(d):
                continue
            model_name = str(d.get("model", ""))
            by_model[model_name].append(d)

        results: list[ModelCost] = []
        for model_name, records in by_model.items():
            total = sum(float(r["cost_usd"]) for r in records)
            count = len(records)
            duration = sum(float(r["duration_seconds"]) for r in records)
            results.append(
                ModelCost(
                    model=model_name,
                    total_cost_usd=total,
                    dispatch_count=count,
                    total_duration_seconds=duration,
                )
            )

        results.sort(key=lambda m: m.total_cost_usd, reverse=True)
        return results

    def all_sessions(self) -> list[SessionCost]:
        """All sessions with their costs, sorted by timestamp descending.

        Groups dispatches and pipelines by session_id in a single pass each,
        then builds SessionCost objects from the grouped data -- O(M) total.
        """
        self._load_if_needed()
        dispatches = self._validated_dispatch_records()
        pipelines = self._validated_pipeline_records()

        # Group dispatches by session_id in a single pass
        dispatches_by_session: dict[str, list[DispatchRecord]] = defaultdict(list)
        for d in dispatches:
            dispatches_by_session[d.session_id].append(d)

        # Group pipelines by session_id in a single pass (last write wins
        # -- a retried PipelineCompleted event overrides the earlier record).
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
        self._load_if_needed()
        dispatches = self._validated_dispatch_records()
        pipelines = self._validated_pipeline_records()
        records: list[DispatchRecord | PipelineRecord] = [*dispatches, *pipelines]
        records.sort(key=lambda r: r.timestamp)
        return records
