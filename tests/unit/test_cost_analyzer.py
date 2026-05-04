"""RED tests for bonfire.cost.analyzer — W5.7 transfer.

CostAnalyzer is a read-only query layer over a JSONL cost ledger. It parses
each line, skips malformed entries, and computes aggregations on demand.

Canonical dedupe of two Knight lenses with the `costs` -> `cost` rename
applied: every import resolves to ``bonfire.cost.*`` (singular). Baseline
class mirrors private v1. ``TestAnalyzerEdge`` covers adversarial ledger
states — blank lines, truncated writes, unknown record types, interleaved
sessions, duplicate pipeline records, and large-file parsing — because the
ledger WILL see these states across a real install.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from bonfire.cost.analyzer import CostAnalyzer
from bonfire.cost.models import DispatchRecord, PipelineRecord

if TYPE_CHECKING:
    from pathlib import Path


def _write_records(path: Path, records: list[DispatchRecord | PipelineRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(r.model_dump_json() + "\n")


@pytest.fixture
def ledger_path(tmp_path: Path) -> Path:
    return tmp_path / "cost_ledger.jsonl"


@pytest.fixture
def sample_records() -> list[DispatchRecord | PipelineRecord]:
    return [
        DispatchRecord(
            timestamp=1000.0,
            session_id="ses_001",
            agent_name="scout",
            cost_usd=0.09,
            duration_seconds=20.0,
        ),
        DispatchRecord(
            timestamp=1001.0,
            session_id="ses_001",
            agent_name="warrior",
            cost_usd=0.04,
            duration_seconds=30.0,
        ),
        PipelineRecord(
            timestamp=1002.0,
            session_id="ses_001",
            total_cost_usd=0.13,
            duration_seconds=54.3,
            stages_completed=2,
        ),
        DispatchRecord(
            timestamp=2000.0,
            session_id="ses_002",
            agent_name="scout",
            cost_usd=0.15,
            duration_seconds=25.0,
        ),
        DispatchRecord(
            timestamp=2001.0,
            session_id="ses_002",
            agent_name="warrior",
            cost_usd=0.06,
            duration_seconds=35.0,
        ),
        DispatchRecord(
            timestamp=2002.0,
            session_id="ses_002",
            agent_name="wizard",
            cost_usd=0.20,
            duration_seconds=40.0,
        ),
        PipelineRecord(
            timestamp=2003.0,
            session_id="ses_002",
            total_cost_usd=0.41,
            duration_seconds=82.1,
            stages_completed=3,
        ),
    ]


# ---------------------------------------------------------------------------
# Canonical analyzer suite — mirror of private v1 with `costs` -> `cost` rename.
# ---------------------------------------------------------------------------


class TestCostAnalyzer:
    def test_cumulative_cost_sums_pipeline_records(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == pytest.approx(0.54)

    def test_cumulative_cost_empty_ledger(self, ledger_path: Path) -> None:
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == 0.0

    def test_cumulative_cost_no_file(self, tmp_path: Path) -> None:
        analyzer = CostAnalyzer(ledger_path=tmp_path / "nonexistent.jsonl")
        assert analyzer.cumulative_cost() == 0.0

    def test_session_cost_returns_dispatches_and_total(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        session = analyzer.session_cost("ses_001")
        assert session is not None
        assert session.total_cost_usd == pytest.approx(0.13)
        assert session.duration_seconds == pytest.approx(54.3)
        assert len(session.dispatches) == 2
        assert session.dispatches[0].agent_name == "scout"
        assert session.dispatches[1].agent_name == "warrior"

    def test_session_cost_unknown_session_returns_none(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.session_cost("ses_999") is None

    def test_agent_costs_sorted_by_spend_descending(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        agents = analyzer.agent_costs()
        assert len(agents) == 3
        # scout: 0.09 + 0.15 = 0.24, warrior: 0.04 + 0.06 = 0.10, wizard: 0.20
        assert agents[0].agent_name == "scout"
        assert agents[0].total_cost_usd == pytest.approx(0.24)
        assert agents[0].dispatch_count == 2
        assert agents[0].avg_cost_usd == pytest.approx(0.12)
        assert agents[1].agent_name == "wizard"
        assert agents[1].total_cost_usd == pytest.approx(0.20)
        assert agents[2].agent_name == "warrior"

    def test_agent_costs_empty_ledger(self, ledger_path: Path) -> None:
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.agent_costs() == []

    def test_all_sessions_sorted_by_timestamp_descending(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        sessions = analyzer.all_sessions()
        assert len(sessions) == 2
        assert sessions[0].session_id == "ses_002"
        assert sessions[1].session_id == "ses_001"

    def test_all_sessions_empty_ledger(self, ledger_path: Path) -> None:
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.all_sessions() == []

    def test_all_sessions_returns_correct_data_for_multiple_sessions(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        sessions = analyzer.all_sessions()

        assert len(sessions) == 2

        # ses_002 first (higher timestamp)
        s2 = sessions[0]
        assert s2.session_id == "ses_002"
        assert s2.total_cost_usd == pytest.approx(0.41)
        assert s2.duration_seconds == pytest.approx(82.1)
        assert s2.stages_completed == 3
        assert len(s2.dispatches) == 3

        # ses_001 second
        s1 = sessions[1]
        assert s1.session_id == "ses_001"
        assert s1.total_cost_usd == pytest.approx(0.13)
        assert s1.duration_seconds == pytest.approx(54.3)
        assert s1.stages_completed == 2
        assert len(s1.dispatches) == 2

    def test_all_records_sorted_by_timestamp_ascending(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        _write_records(ledger_path, sample_records)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        records = analyzer.all_records()
        assert len(records) == 7
        timestamps = [r.timestamp for r in records]
        assert timestamps == sorted(timestamps)

    def test_skips_malformed_lines(self, ledger_path: Path) -> None:
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as fh:
            fh.write(
                '{"type":"dispatch","timestamp":1000.0,"session_id":"s1",'
                '"agent_name":"a","cost_usd":0.1,"duration_seconds":5.0}\n'
            )
            fh.write("NOT VALID JSON\n")
            fh.write(
                '{"type":"pipeline","timestamp":1001.0,"session_id":"s1",'
                '"total_cost_usd":0.1,"duration_seconds":5.0,"stages_completed":1}\n'
            )
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == pytest.approx(0.1)
        sessions = analyzer.all_sessions()
        assert len(sessions) == 1


# ---------------------------------------------------------------------------
# Adversarial ledger states.
#
# The ledger is an append-only JSONL file on disk. It WILL see — over the
# lifetime of a real install — partial writes, crashes mid-line, blank
# lines from editor saves, concurrent appenders racing on the same inode,
# CR-only endings, and foreign record types from newer writers. The
# analyzer's job is to quietly skip rot, not to crash ``bonfire status``.
# ---------------------------------------------------------------------------


class TestAnalyzerEdge:
    def test_blank_lines_are_skipped(self, ledger_path: Path) -> None:
        """Blank lines can appear from editor autosave or a crash between
        ``write(json)`` and ``write('\\n')`` producing a buffer flush at
        boundary. Must not count as a record.
        """
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as fh:
            fh.write("\n")
            fh.write(
                '{"type":"dispatch","timestamp":1.0,"session_id":"s","agent_name":"a",'
                '"cost_usd":0.5,"duration_seconds":1.0}\n'
            )
            fh.write("\n\n")
            fh.write(
                '{"type":"pipeline","timestamp":2.0,"session_id":"s","total_cost_usd":0.5,'
                '"duration_seconds":1.0,"stages_completed":1}\n'
            )
            fh.write("   \n")  # whitespace-only
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == pytest.approx(0.5)

    def test_truncated_final_line_is_skipped(self, ledger_path: Path) -> None:
        """A crash mid-append leaves a half-written last line with no
        trailing newline. Must not corrupt the earlier records.
        """
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as fh:
            fh.write(
                '{"type":"dispatch","timestamp":1.0,"session_id":"s","agent_name":"a",'
                '"cost_usd":0.1,"duration_seconds":1.0}\n'
            )
            # Half-written: no closing brace, no newline.
            fh.write('{"type":"dispatch","timestamp":2.0,"session_id":"s","agent_name"')
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == pytest.approx(0.0)  # no pipeline rows
        agents = analyzer.agent_costs()
        assert len(agents) == 1
        assert agents[0].total_cost_usd == pytest.approx(0.1)

    def test_unknown_record_type_is_skipped(self, ledger_path: Path) -> None:
        """A future schema version might add type='tool_call'. The analyzer
        MUST skip it, not raise, so v0.1 tooling keeps working alongside
        newer writers on the same host.
        """
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as fh:
            fh.write('{"type":"tool_call","foo":"bar"}\n')
            fh.write(
                '{"type":"dispatch","timestamp":1.0,"session_id":"s","agent_name":"a",'
                '"cost_usd":0.1,"duration_seconds":1.0}\n'
            )
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        sessions = analyzer.all_sessions()
        assert len(sessions) == 1

    def test_record_missing_required_fields_is_skipped(self, ledger_path: Path) -> None:
        """A JSON-valid but schema-invalid line (e.g. missing cost_usd) MUST
        be skipped via ValidationError, not crash ``all_records``.
        """
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as fh:
            fh.write('{"type":"dispatch","timestamp":1.0,"session_id":"s","agent_name":"a"}\n')
            fh.write(
                '{"type":"dispatch","timestamp":2.0,"session_id":"s","agent_name":"b",'
                '"cost_usd":0.2,"duration_seconds":1.0}\n'
            )
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        agents = analyzer.agent_costs()
        assert len(agents) == 1
        assert agents[0].agent_name == "b"

    def test_single_dispatch_no_pipeline_still_yields_session(self, ledger_path: Path) -> None:
        """If a pipeline crashes before emitting PipelineCompleted, the
        ledger holds dispatches without a matching pipeline row. The
        session MUST still show up with dispatch-derived totals.
        """
        rec = DispatchRecord(
            timestamp=100.0,
            session_id="ses_orphan",
            agent_name="scout",
            cost_usd=0.07,
            duration_seconds=12.0,
        )
        _write_records(ledger_path, [rec])
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        sessions = analyzer.all_sessions()
        assert len(sessions) == 1
        assert sessions[0].session_id == "ses_orphan"
        assert sessions[0].total_cost_usd == pytest.approx(0.07)
        assert sessions[0].duration_seconds == pytest.approx(12.0)
        assert sessions[0].stages_completed == 0
        assert sessions[0].timestamp == pytest.approx(100.0)

    def test_duplicate_pipeline_record_last_write_wins(self, ledger_path: Path) -> None:
        """Two PipelineCompleted events can appear for one session id if a
        consumer retries. ``all_sessions`` dedupes by session_id (dict key);
        last write wins. The analyzer MUST NOT double-count sessions.

        ``cumulative_cost`` uses ``sum`` over every pipeline row, so the
        naive total reflects both writes; dedup happens in ``all_sessions``.
        """
        recs = [
            PipelineRecord(
                timestamp=1.0,
                session_id="ses_dup",
                total_cost_usd=0.10,
                duration_seconds=1.0,
                stages_completed=1,
            ),
            PipelineRecord(
                timestamp=2.0,
                session_id="ses_dup",
                total_cost_usd=0.25,
                duration_seconds=5.0,
                stages_completed=3,
            ),
        ]
        _write_records(ledger_path, recs)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        assert analyzer.cumulative_cost() == pytest.approx(0.35)
        sessions = analyzer.all_sessions()
        assert len(sessions) == 1
        # Dict keyed by session_id — last write wins (0.25, 3 stages).
        assert sessions[0].total_cost_usd == pytest.approx(0.25)
        assert sessions[0].stages_completed == 3

    def test_interleaved_sessions_parse_correctly(self, ledger_path: Path) -> None:
        """Parallel pipelines append concurrently, interleaving their
        records. Grouping MUST be by session_id, not by file position.
        """
        recs: list[DispatchRecord | PipelineRecord] = [
            DispatchRecord(
                timestamp=1.0,
                session_id="A",
                agent_name="scout",
                cost_usd=0.1,
                duration_seconds=1.0,
            ),
            DispatchRecord(
                timestamp=1.1,
                session_id="B",
                agent_name="scout",
                cost_usd=0.2,
                duration_seconds=1.0,
            ),
            DispatchRecord(
                timestamp=1.2,
                session_id="A",
                agent_name="knight",
                cost_usd=0.3,
                duration_seconds=1.0,
            ),
            DispatchRecord(
                timestamp=1.3,
                session_id="B",
                agent_name="knight",
                cost_usd=0.4,
                duration_seconds=1.0,
            ),
        ]
        _write_records(ledger_path, recs)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        sessions = {s.session_id: s for s in analyzer.all_sessions()}
        assert set(sessions) == {"A", "B"}
        assert sessions["A"].total_cost_usd == pytest.approx(0.4)
        assert sessions["B"].total_cost_usd == pytest.approx(0.6)

    def test_agent_costs_avg_handles_single_dispatch(self, ledger_path: Path) -> None:
        """One dispatch for an agent means avg == total. Off-by-one division
        bugs show up here.
        """
        rec = DispatchRecord(
            timestamp=1.0,
            session_id="s",
            agent_name="solo",
            cost_usd=0.25,
            duration_seconds=1.0,
        )
        _write_records(ledger_path, [rec])
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        agents = analyzer.agent_costs()
        assert len(agents) == 1
        assert agents[0].dispatch_count == 1
        assert agents[0].total_cost_usd == pytest.approx(0.25)
        assert agents[0].avg_cost_usd == pytest.approx(0.25)

    def test_large_ledger_parses_without_error(self, ledger_path: Path) -> None:
        """Ten thousand records is a realistic few-months ledger. Parser MUST
        not blow up on it (O(N) read, no O(N^2) quadratic grouping).
        """
        n = 10_000
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as fh:
            for i in range(n):
                rec = DispatchRecord(
                    timestamp=float(i),
                    session_id=f"ses_{i % 50}",  # 50 sessions, 200 dispatches each
                    agent_name=f"agent_{i % 5}",
                    cost_usd=0.01,
                    duration_seconds=1.0,
                )
                fh.write(rec.model_dump_json() + "\n")
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        agents = analyzer.agent_costs()
        assert len(agents) == 5
        assert sum(a.dispatch_count for a in agents) == n
        sessions = analyzer.all_sessions()
        assert len(sessions) == 50

    def test_zero_stages_pipeline_is_preserved(self, ledger_path: Path) -> None:
        """A pipeline aborted at stage 0 still emits a PipelineCompleted.
        ``stages_completed=0`` must NOT be treated as "no pipeline".
        """
        rec = PipelineRecord(
            timestamp=5.0,
            session_id="ses_aborted",
            total_cost_usd=0.0,
            duration_seconds=0.5,
            stages_completed=0,
        )
        _write_records(ledger_path, [rec])
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        sessions = analyzer.all_sessions()
        assert len(sessions) == 1
        assert sessions[0].stages_completed == 0
        assert sessions[0].session_id == "ses_aborted"

    def test_crlf_line_endings_are_tolerated(self, ledger_path: Path) -> None:
        """A ledger edited on Windows (or copied through a tool that converts
        line endings) may have CRLF. ``line.strip()`` handles this, so
        records MUST still parse.
        """
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("wb") as fh:
            fh.write(
                b'{"type":"dispatch","timestamp":1.0,"session_id":"s","agent_name":"a",'
                b'"cost_usd":0.1,"duration_seconds":1.0}\r\n'
            )
            fh.write(
                b'{"type":"dispatch","timestamp":2.0,"session_id":"s","agent_name":"b",'
                b'"cost_usd":0.2,"duration_seconds":1.0}\r\n'
            )
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        agents = analyzer.agent_costs()
        assert {a.agent_name for a in agents} == {"a", "b"}


# ---------------------------------------------------------------------------
# BON-351 — CostAnalyzer.model_costs() per-model aggregator (D8)
#
# Sixth public method on the analyzer. Mirrors agent_costs() in shape:
# group-by, sort-descending-by-spend, return list[ModelCost]. The empty-
# string bucket IS preserved so operators can see how much spend predates
# per-model attribution (legacy ledger rows).
# ---------------------------------------------------------------------------


class TestModelCosts:
    """RED tests for BON-351 D8 — ``model_costs() -> list[ModelCost]``."""

    def test_empty_ledger_returns_empty_list(self, tmp_path: Path) -> None:
        """Sage memo D8 — a missing or empty ledger produces an empty list,
        never raises. Mirrors the agent_costs() empty-state contract.
        """
        analyzer = CostAnalyzer(ledger_path=tmp_path / "absent.jsonl")
        assert analyzer.model_costs() == []

    def test_groups_records_by_model(self, ledger_path: Path) -> None:
        """Sage memo D8 — records sharing a model string collapse into one
        ModelCost entry. Different model strings => different entries.
        """
        from bonfire.cost.models import ModelCost

        recs = [
            DispatchRecord(
                timestamp=1.0,
                session_id="s",
                agent_name="a",
                cost_usd=0.10,
                duration_seconds=1.0,
                model="claude-opus-4-7",
            ),
            DispatchRecord(
                timestamp=2.0,
                session_id="s",
                agent_name="b",
                cost_usd=0.05,
                duration_seconds=2.0,
                model="claude-opus-4-7",
            ),
            DispatchRecord(
                timestamp=3.0,
                session_id="s",
                agent_name="c",
                cost_usd=0.20,
                duration_seconds=3.0,
                model="claude-haiku-4-5",
            ),
        ]
        _write_records(ledger_path, recs)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        results = analyzer.model_costs()
        assert len(results) == 2
        assert all(isinstance(r, ModelCost) for r in results)
        models_to_records = {r.model: r for r in results}
        assert set(models_to_records) == {"claude-opus-4-7", "claude-haiku-4-5"}

    def test_sort_descending_by_cost(self, ledger_path: Path) -> None:
        """Sage memo D8 — sort key is ``total_cost_usd``, descending. Same
        comparator as ``agent_costs()`` (analyzer.py:135) — consistent UX.
        """
        recs = [
            DispatchRecord(
                timestamp=1.0,
                session_id="s",
                agent_name="a",
                cost_usd=0.05,
                duration_seconds=1.0,
                model="cheap-model",
            ),
            DispatchRecord(
                timestamp=2.0,
                session_id="s",
                agent_name="b",
                cost_usd=0.50,
                duration_seconds=1.0,
                model="expensive-model",
            ),
            DispatchRecord(
                timestamp=3.0,
                session_id="s",
                agent_name="c",
                cost_usd=0.25,
                duration_seconds=1.0,
                model="medium-model",
            ),
        ]
        _write_records(ledger_path, recs)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        results = analyzer.model_costs()
        models_in_order = [r.model for r in results]
        assert models_in_order == ["expensive-model", "medium-model", "cheap-model"]

    def test_legacy_empty_model_grouped_visible(self, ledger_path: Path) -> None:
        """Sage memo D8 — legacy rows (model="") MUST appear as their own
        bucket, not be silently dropped. Operators want to see how much
        unattributed/legacy spend exists alongside the attributed spend.
        """
        recs = [
            DispatchRecord(
                timestamp=1.0,
                session_id="s",
                agent_name="legacy-a",
                cost_usd=0.30,
                duration_seconds=1.0,
                # model defaults to ""
            ),
            DispatchRecord(
                timestamp=2.0,
                session_id="s",
                agent_name="modern-b",
                cost_usd=0.10,
                duration_seconds=1.0,
                model="claude-opus-4-7",
            ),
        ]
        _write_records(ledger_path, recs)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        results = analyzer.model_costs()
        assert len(results) == 2
        models = {r.model for r in results}
        assert "" in models
        assert "claude-opus-4-7" in models

    def test_dispatch_count_correct(self, ledger_path: Path) -> None:
        """Sage memo D8 — ``dispatch_count`` reflects the number of records
        sharing the same model string. Off-by-one bugs surface here.
        """
        recs = [
            DispatchRecord(
                timestamp=float(i),
                session_id="s",
                agent_name=f"a{i}",
                cost_usd=0.01,
                duration_seconds=1.0,
                model="solo-model" if i == 0 else "shared-model",
            )
            for i in range(5)
        ]
        _write_records(ledger_path, recs)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        results = analyzer.model_costs()
        counts = {r.model: r.dispatch_count for r in results}
        assert counts["solo-model"] == 1
        assert counts["shared-model"] == 4

    def test_total_duration_summed(self, ledger_path: Path) -> None:
        """Sage memo D8 — ``total_duration_seconds`` is summed across the
        records sharing a model string. This is the per-model burn-time
        operators care about.
        """
        recs = [
            DispatchRecord(
                timestamp=1.0,
                session_id="s",
                agent_name="a",
                cost_usd=0.01,
                duration_seconds=12.5,
                model="claude-opus-4-7",
            ),
            DispatchRecord(
                timestamp=2.0,
                session_id="s",
                agent_name="b",
                cost_usd=0.02,
                duration_seconds=7.5,
                model="claude-opus-4-7",
            ),
        ]
        _write_records(ledger_path, recs)
        analyzer = CostAnalyzer(ledger_path=ledger_path)
        results = analyzer.model_costs()
        assert len(results) == 1
        assert results[0].total_duration_seconds == pytest.approx(20.0)


# ---------------------------------------------------------------------------
# BON-351 Knight B — innovation surface for model_costs() resilience.
#
# Sage memo D8 (analyzer per-model aggregator) + D5 (DispatchRecord.model
# field migration with empty-string-as-legacy bucket). Knight A locks the
# spine: empty ledger, basic grouping, sort, legacy bucket existence,
# dispatch_count, total_duration. Knight B locks the corners that the
# spine wouldn't think to cover:
#
#   1. PATHOLOGICAL CORPUS: 10_000 dispatch records spread across 5 models
#      with deterministic ranking.  This guards against an O(N^2) regression
#      in the group-by path AND verifies the descending-sort is stable
#      enough to put a clear cost-leader first.  Sage D8 line 482 calls
#      this out as the Knight B innovation case.
#
#   2. MIXED LEGACY-AND-NEW IN ONE FILE: a real ledger file in production
#      will have rows persisted BEFORE BON-351 (no `model` field) and rows
#      persisted AFTER BON-351 (with `model`) interleaved on disk.  This
#      test writes both shapes to the same file and asserts the analyzer
#      groups legacy rows under "" while still bucketing the new rows by
#      their model strings -- per Sage D5 (legacy-jsonl-row backward
#      compat) and D8 (empty-string-as-visible-bucket).
#
#   3. SORT STABILITY FOR TIED COSTS: when two models have the SAME total
#      cost, the descending sort by total_cost_usd is technically a tie.
#      Sage D8 line 443 specifies `results.sort(key=lambda m: m.total_cost_usd,
#      reverse=True)` -- Python's sort is stable, so insertion order wins
#      on ties.  This test pins that stability so a future "optimization"
#      to a comparator-based sort can't silently scramble tied buckets.
# ---------------------------------------------------------------------------


class TestModelCostsResilience:
    """BON-351 D8 + D5 resilience corners — innovation surface."""

    def test_pathological_corpus_groups_correctly_and_sorts(self, ledger_path: Path) -> None:
        """10_000 records across 5 models — sort + count + sum are correct.

        Locks Sage D8 (model_costs aggregator) at scale. Without an O(N)
        group-by, this test would dominate the suite runtime; with the
        spec'd dict-based group, it stays fast.

        Cost layout (deterministic):
            claude-opus-4-7   -> 4000 records * 0.04 = 160.00
            claude-sonnet-4-6 -> 3000 records * 0.03 =  90.00
            claude-haiku-4-5  -> 2000 records * 0.02 =  40.00
            claude-extra-1    ->  900 records * 0.05 =  45.00
            claude-extra-2    ->  100 records * 0.10 =  10.00

        Sorted descending:
            opus (160) > sonnet (90) > extra-1 (45) > haiku (40) > extra-2 (10)
        """
        from bonfire.cost.models import ModelCost  # noqa: F401 — RED until BON-351

        n_total = 10_000
        layout: list[tuple[str, int, float]] = [
            ("claude-opus-4-7", 4000, 0.04),
            ("claude-sonnet-4-6", 3000, 0.03),
            ("claude-haiku-4-5", 2000, 0.02),
            ("claude-extra-1", 900, 0.05),
            ("claude-extra-2", 100, 0.10),
        ]
        assert sum(count for _, count, _ in layout) == n_total

        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        ts = 0.0
        with ledger_path.open("w", encoding="utf-8") as fh:
            for model_name, count, cost in layout:
                for _ in range(count):
                    rec = DispatchRecord(
                        timestamp=ts,
                        session_id=f"ses_{int(ts) % 50}",
                        agent_name="agent",
                        cost_usd=cost,
                        duration_seconds=1.0,
                        model=model_name,
                    )
                    fh.write(rec.model_dump_json() + "\n")
                    ts += 1.0

        analyzer = CostAnalyzer(ledger_path=ledger_path)
        results = analyzer.model_costs()

        assert len(results) == 5
        assert sum(m.dispatch_count for m in results) == n_total

        # Descending by total_cost_usd.
        names = [m.model for m in results]
        assert names == [
            "claude-opus-4-7",
            "claude-sonnet-4-6",
            "claude-extra-1",
            "claude-haiku-4-5",
            "claude-extra-2",
        ]
        # Spot-check totals.
        by_name = {m.model: m for m in results}
        assert by_name["claude-opus-4-7"].total_cost_usd == pytest.approx(160.0)
        assert by_name["claude-opus-4-7"].dispatch_count == 4000
        assert by_name["claude-haiku-4-5"].total_cost_usd == pytest.approx(40.0)
        assert by_name["claude-extra-2"].dispatch_count == 100

    def test_mixed_legacy_and_new_rows_round_trip(self, ledger_path: Path) -> None:
        """Legacy rows (no `model` field) coexist with new rows in one file.

        Locks Sage D5 (DispatchRecord backward compat) AND D8 (legacy bucket
        preserved as visible "" key). Real-world ledgers will have both
        shapes interleaved across the BON-351 deployment boundary.
        """
        from bonfire.cost.models import ModelCost  # noqa: F401 — RED until BON-351

        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        with ledger_path.open("w", encoding="utf-8") as fh:
            # 3 LEGACY rows -- pre-BON-351 shape, no `model` key.
            fh.write(
                '{"type":"dispatch","timestamp":1.0,"session_id":"s","agent_name":"a",'
                '"cost_usd":0.50,"duration_seconds":1.0}\n'
            )
            fh.write(
                '{"type":"dispatch","timestamp":2.0,"session_id":"s","agent_name":"a",'
                '"cost_usd":0.25,"duration_seconds":1.0}\n'
            )
            fh.write(
                '{"type":"dispatch","timestamp":3.0,"session_id":"s","agent_name":"a",'
                '"cost_usd":0.10,"duration_seconds":1.0}\n'
            )
            # 2 NEW rows -- post-BON-351 shape, with `model`.
            new_a = DispatchRecord(
                timestamp=4.0,
                session_id="s",
                agent_name="a",
                cost_usd=0.30,
                duration_seconds=2.0,
                model="claude-opus-4-7",
            )
            new_b = DispatchRecord(
                timestamp=5.0,
                session_id="s",
                agent_name="b",
                cost_usd=0.20,
                duration_seconds=1.5,
                model="claude-haiku-4-5",
            )
            fh.write(new_a.model_dump_json() + "\n")
            fh.write(new_b.model_dump_json() + "\n")

        analyzer = CostAnalyzer(ledger_path=ledger_path)
        results = analyzer.model_costs()

        # Three buckets: "", opus, haiku.
        by_name = {m.model: m for m in results}
        assert set(by_name) == {"", "claude-opus-4-7", "claude-haiku-4-5"}

        # Legacy bucket is preserved as a visible "" key with summed cost.
        legacy = by_name[""]
        assert legacy.dispatch_count == 3
        assert legacy.total_cost_usd == pytest.approx(0.85)

        # New rows attributed to their model strings.
        assert by_name["claude-opus-4-7"].dispatch_count == 1
        assert by_name["claude-opus-4-7"].total_cost_usd == pytest.approx(0.30)
        assert by_name["claude-haiku-4-5"].dispatch_count == 1
        assert by_name["claude-haiku-4-5"].total_cost_usd == pytest.approx(0.20)

        # Sort descending by cost: legacy (0.85) > opus (0.30) > haiku (0.20).
        assert [m.model for m in results] == [
            "",
            "claude-opus-4-7",
            "claude-haiku-4-5",
        ]

    def test_sort_stability_on_tied_costs(self, ledger_path: Path) -> None:
        """Tied costs keep insertion order — Python's sort is stable.

        Locks Sage D8 line 443 (`results.sort(key=..., reverse=True)`). A
        future refactor to a custom comparator could silently break tie
        ordering; this test pins the behavior.

        Three models with identical total cost (0.20 each), inserted in a
        fixed order (model_alpha first, model_beta second, model_gamma
        third). Stable sort means the output preserves that order.
        """
        from bonfire.cost.models import ModelCost  # noqa: F401 — RED until BON-351

        recs = [
            DispatchRecord(
                timestamp=1.0,
                session_id="s",
                agent_name="a",
                cost_usd=0.10,
                duration_seconds=1.0,
                model="model_alpha",
            ),
            DispatchRecord(
                timestamp=2.0,
                session_id="s",
                agent_name="a",
                cost_usd=0.10,
                duration_seconds=1.0,
                model="model_alpha",
            ),
            DispatchRecord(
                timestamp=3.0,
                session_id="s",
                agent_name="b",
                cost_usd=0.20,
                duration_seconds=1.0,
                model="model_beta",
            ),
            DispatchRecord(
                timestamp=4.0,
                session_id="s",
                agent_name="c",
                cost_usd=0.05,
                duration_seconds=1.0,
                model="model_gamma",
            ),
            DispatchRecord(
                timestamp=5.0,
                session_id="s",
                agent_name="c",
                cost_usd=0.15,
                duration_seconds=1.0,
                model="model_gamma",
            ),
        ]
        _write_records(ledger_path, recs)

        analyzer = CostAnalyzer(ledger_path=ledger_path)
        results = analyzer.model_costs()

        # All three buckets total 0.20; stable sort preserves insertion order.
        assert len(results) == 3
        assert all(m.total_cost_usd == pytest.approx(0.20) for m in results)
        assert [m.model for m in results] == ["model_alpha", "model_beta", "model_gamma"]
