"""RED tests for bonfire.cli.commands.cost — BON-348 W6.2 (Knight A, CONSERVATIVE lens). Floor: 6 tests per Sage §D6 Row 3. Verbatim v1 port with bonfire.costs → bonfire.cost rename. No innovations."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from pathlib import Path
from typer.testing import CliRunner

from bonfire.cli.commands.cost import cost_app
from bonfire.cost.models import DispatchRecord, PipelineRecord

runner = CliRunner()


def _write_records(path: Path, records: list[DispatchRecord | PipelineRecord]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(r.model_dump_json() + "\n")


@pytest.fixture
def ledger_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "cost_ledger.jsonl"
    monkeypatch.setenv("BONFIRE_COST_LEDGER_PATH", str(path))
    return path


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
    ]


class TestCostSummary:
    def test_summary_shows_cumulative_total(self, ledger_path: Path, sample_records: list) -> None:
        _write_records(ledger_path, sample_records)
        result = runner.invoke(cost_app, [], catch_exceptions=False)
        assert result.exit_code == 0
        assert "$0.13" in result.output
        assert "Built by Bonfire" in result.output

    def test_summary_empty_ledger(self, ledger_path: Path) -> None:
        result = runner.invoke(cost_app, [], catch_exceptions=False)
        assert result.exit_code == 0
        assert "$0.00" in result.output


class TestCostSession:
    def test_session_drilldown(self, ledger_path: Path, sample_records: list) -> None:
        _write_records(ledger_path, sample_records)
        result = runner.invoke(cost_app, ["session", "ses_001"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "ses_001" in result.output
        assert "scout" in result.output
        assert "warrior" in result.output
        assert "$0.09" in result.output

    def test_session_not_found(self, ledger_path: Path, sample_records: list) -> None:
        _write_records(ledger_path, sample_records)
        result = runner.invoke(cost_app, ["session", "ses_999"], catch_exceptions=False)
        assert result.exit_code == 1


class TestCostAgents:
    def test_agent_summary(self, ledger_path: Path, sample_records: list) -> None:
        _write_records(ledger_path, sample_records)
        result = runner.invoke(cost_app, ["agents"], catch_exceptions=False)
        assert result.exit_code == 0
        assert "scout" in result.output
        assert "warrior" in result.output
        assert "1 dispatch" in result.output


class TestCostExport:
    def test_export_json(self, ledger_path: Path, sample_records: list) -> None:
        import json

        _write_records(ledger_path, sample_records)
        result = runner.invoke(cost_app, ["export"], catch_exceptions=False)
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert isinstance(data, list)
        assert len(data) == 3
