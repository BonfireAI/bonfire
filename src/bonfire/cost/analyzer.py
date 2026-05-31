# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

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
    """Reads the cost ledger and computes aggregations on demand.

    Memoizes the parsed-record tuple on the instance, invalidated by a
    *signature* of the ledger file: its mtime, inode, and size taken
    together. Multiple aggregation methods called on the same analyzer
    instance share one read — the default ``bonfire cost`` callback
    (``cumulative_cost`` + ``all_sessions``) previously paid the parse cost
    twice per invocation; post-memoization it pays once.

    Why the signature is a triple, not just the mtime: atomic file
    replacement (``mv``/``rename`` of a temp file over the ledger, restoring
    a backup with ``cp -p``/``rsync --times``, extracting an archive) can
    land the *same* mtime the cache last saw — either by writing within the
    same filesystem-timestamp tick or by deliberately stamping the old mtime
    back on. An mtime-only key would then serve stale cost data indefinitely,
    silently mis-reporting spend. Pairing mtime with the inode number (which
    a rename/replace changes) and the file size (which an in-place rewrite to
    a different length changes) catches those cases that the mtime alone
    misses.
    """

    # Sentinel signature for "ledger file does not exist." Distinct from any
    # real (st_mtime_ns, st_ino, st_size) triple — the -1 mtime component can
    # never collide with a valid os.stat().st_mtime_ns (which is
    # non-negative). When the file later appears, this sentinel won't match
    # the real signature, so the next _read_records() call invalidates and
    # re-reads.
    _SIGNATURE_MISSING = (-1, -1, -1)

    def __init__(self, ledger_path: Path = DEFAULT_LEDGER_PATH) -> None:
        self._ledger_path = Path(ledger_path)
        # Cached parsed records + the file signature they were read at. Both
        # are set together in _read_records(); a None cache means "never read."
        self._cache: tuple[list[DispatchRecord], list[PipelineRecord]] | None = None
        self._cache_signature: tuple[int, int, int] = self._SIGNATURE_MISSING

    def _current_ledger_signature(self) -> tuple[int, int, int]:
        """Return the ledger's ``(mtime_ns, inode, size)`` signature.

        Returns ``_SIGNATURE_MISSING`` if the file is absent. The three fields
        together detect every change the cache must react to: an append or
        edit advances ``st_mtime_ns``; an atomic rename/replace allocates a new
        ``st_ino``; an in-place rewrite to a different length changes
        ``st_size`` — covering the same-mtime hazards a bare mtime key misses.
        """
        try:
            stat = self._ledger_path.stat()
        except FileNotFoundError:
            return self._SIGNATURE_MISSING
        return (stat.st_mtime_ns, stat.st_ino, stat.st_size)

    def _read_records(
        self,
    ) -> tuple[list[DispatchRecord], list[PipelineRecord]]:
        """Read and parse all records from the ledger file.

        Memoized per instance with signature-based invalidation: if the
        ledger file's ``(mtime_ns, inode, size)`` signature matches the cached
        value, the cached tuple is returned as-is (identity-equal to the prior
        call's result). Any change to any component of the signature — an
        mtime advance from an append, a new inode from an atomic replacement,
        or a size change from an in-place rewrite, including the file
        appearing after a previous missing-file read — triggers a fresh parse.
        """
        current_signature = self._current_ledger_signature()
        if self._cache is not None and current_signature == self._cache_signature:
            return self._cache

        dispatches: list[DispatchRecord] = []
        pipelines: list[PipelineRecord] = []

        if current_signature == self._SIGNATURE_MISSING:
            # File doesn't exist — cache the empty result keyed by the
            # missing-sentinel so a follow-up call without file creation
            # still hits cache.
            self._cache = (dispatches, pipelines)
            self._cache_signature = self._SIGNATURE_MISSING
            return self._cache

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

        # Cache populated tuple keyed by the signature we observed at read
        # time. If any component (mtime, inode, or size) differs between this
        # call and the next, the signature check at the top of _read_records
        # will invalidate.
        self._cache = (dispatches, pipelines)
        self._cache_signature = current_signature
        return self._cache

    def cumulative_cost(self) -> float:
        """Grand total USD across the whole ledger.

        Every completed pipeline contributes its summary total. On top of
        that, any *orphan* session — one that emitted dispatches but never a
        PipelineCompleted summary, because its pipeline crashed mid-run
        (Ctrl-C, or a contributor driving the engine directly) — contributes
        the sum of its dispatch costs. Without the orphan term this headline
        figure (e.g. "Built by Bonfire for $X") would silently under-count
        real spend, which is a trust number we must not under-report.

        A session that has a pipeline summary is counted only once, via that
        summary; its dispatch rows are not re-added, so this stays additive
        and non-breaking for the common completed-pipeline case.
        """
        dispatches, pipelines = self._read_records()

        sessions_with_pipeline = {p.session_id for p in pipelines}
        pipeline_total = sum(p.total_cost_usd for p in pipelines)
        orphan_total = sum(
            d.cost_usd for d in dispatches if d.session_id not in sessions_with_pipeline
        )
        return pipeline_total + orphan_total

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

        Records lacking a model string (legacy or unattributed) are grouped
        under model="". Empty-string is preserved as a visible bucket --
        operators want to see how much spend predates per-model attribution.
        """
        dispatches, _ = self._read_records()

        by_model: dict[str, list[DispatchRecord]] = defaultdict(list)
        for d in dispatches:
            by_model[d.model].append(d)

        results: list[ModelCost] = []
        for model_name, records in by_model.items():
            total = sum(r.cost_usd for r in records)
            count = len(records)
            duration = sum(r.duration_seconds for r in records)
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
