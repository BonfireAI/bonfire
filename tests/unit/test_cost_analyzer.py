"""RED tests for bonfire.cost.analyzer — W5.7 transfer.

CostAnalyzer is a read-only query layer over a JSONL cost ledger. It parses
each line, skips malformed entries, and computes aggregations on demand.

Knight-A innovative lens: push the analyzer through ledger states a happy-
path mirror would never see — empty files, comment-like noise, duplicated
pipelines, BOM-prefixed files, CRLF line endings, interleaved dispatch
and pipeline records across many sessions, and large ledgers. If a ledger
has rotted mid-write, the analyzer MUST degrade gracefully — never crash.
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
# Canonical analyzer suite (mirrored from private v1 with costs→cost rename).
# ---------------------------------------------------------------------------


class TestCostAnalyzer:
    """Baseline mirror of private v1 test_cost_analyzer.py with rename."""

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
# Innovative lens — adversarial ledger states.
#
# Lens rationale: the ledger is an append-only JSONL file on disk. It WILL
# see — over the lifetime of a Bonfire install — partial writes, crashes
# mid-line, blank lines from editor saves, concurrent appenders racing on
# the same inode, decade-wrap timestamps, and lines containing everything
# from UTF-8 BOMs to CR-only endings. The analyzer's job is to quietly
# skip rot, not to crash the ``bonfire status`` command.
# ---------------------------------------------------------------------------


class TestInnovativeAnalyzerEdge:
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
        ledger will hold dispatches without a matching pipeline row. The
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
        last write wins. The analyzer MUST NOT double-count.
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
        stages_completed=0 must NOT be treated as "no pipeline".
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
        """A ledger edited on Windows (or copied through a tool that
        converts line endings) may have CRLF. ``line.strip()`` handles this,
        so records MUST still parse.
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
