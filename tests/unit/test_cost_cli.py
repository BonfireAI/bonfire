"""RED tests for bonfire.cli.commands.cost — BON-348 W6.2 (CONTRACT-LOCKED).

Sage memo: docs/audit/sage-decisions/bon-348-sage-20260426T013845Z.md
Adoption-filter: docs/audit/sage-decisions/bon-348-contract-lock-*.md

Floor (6 tests, per Sage §D6 Test file 3): port v1 cli test surface verbatim
modulo §D3 row 4 cross-module rename — `bonfire.costs.models → bonfire.cost.models`
(plural → singular per ADR-001 §Module Renames row 5).

Adopted innovations (2 drift-guards over floor):

  * test_export_json_dispatch_schema_fields_present — parametrize over the
    DispatchRecord schema fields (type/timestamp/session_id/agent_name/cost_usd
    /duration_seconds). Guards against silent shape drift in record export.
    Cites Sage §D8 + v1 cli/commands/cost.py:90-95 + v0.1 cost/models.py:14-22.

  * test_summary_output_is_deterministic — invoking `bonfire cost` twice on
    the same ledger must produce byte-identical output. Within-process
    determinism guard. Cites Sage §D8 + v1 cli/commands/cost.py:24-47.

Imports are RED — `bonfire.cli.commands.cost` does not exist as a package
until Warriors port v1 source per Sage §D9.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

if TYPE_CHECKING:
    from pathlib import Path

# RED imports — bonfire.cli.commands.cost does not exist yet (cli.py is a single-file stub)
from bonfire.cli.commands.cost import cost_app

# Cross-module import-path rename per Sage §D3 row 4 (ADR-001 §Module Renames row 5):
# v1: from bonfire.costs.models import DispatchRecord, PipelineRecord
# v0.1: from bonfire.cost.models import DispatchRecord, PipelineRecord
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
    def test_summary_shows_cumulative_total(
        self, ledger_path: Path, sample_records: list
    ) -> None:
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


# ---------------------------------------------------------------------------
# Adopted drift-guards (2 — innovations 5 + 6)
# ---------------------------------------------------------------------------


class TestExportSchemaStability:
    """Drift-guards on the export-emitted record shape + summary determinism."""

    @pytest.mark.parametrize(
        "field_name",
        [
            "type",
            "timestamp",
            "session_id",
            "agent_name",
            "cost_usd",
            "duration_seconds",
        ],
    )
    def test_export_json_dispatch_schema_fields_present(
        self,
        ledger_path: Path,
        sample_records: list,
        field_name: str,
    ) -> None:
        """`bonfire cost export` JSON must include every DispatchRecord field.

        Cites Sage §D8 + v1 cli/commands/cost.py:90-95 + v0.1 cost/models.py:14-22.

        Sage §D8 LOCKS the export emit:
            typer.echo(json.dumps([r.model_dump() for r in records], indent=2))

        v1 source line 95 confirms `r.model_dump()` — full Pydantic dump,
        ALL fields. The floor test only asserts `len(data) == 3` and
        `isinstance(data, list)` — would still pass if a future PR
        removed `duration_seconds` from `DispatchRecord` or renamed
        `cost_usd` to `cost`.

        v0.1 cost/models.py:14-22 declares DispatchRecord with EXACTLY these
        6 fields (including the discriminator `type: Literal["dispatch"]`).

        all_records() returns dispatches sorted by timestamp ascending; the
        fixture's first DispatchRecord (scout, t=1000.0) lands at index 0.
        Guard the DispatchRecord shape via index 0.
        """
        import json

        _write_records(ledger_path, sample_records)
        result = runner.invoke(cost_app, ["export"], catch_exceptions=False)
        assert result.exit_code == 0
        data = json.loads(result.output)

        # Index 0 is the first DispatchRecord (scout, $0.09)
        dispatch_dump = data[0]
        assert field_name in dispatch_dump, (
            f"DispatchRecord export JSON missing field {field_name!r}. "
            f"Got keys: {sorted(dispatch_dump.keys())}"
        )

    def test_summary_output_is_deterministic(
        self, ledger_path: Path, sample_records: list
    ) -> None:
        """Invoking `bonfire cost` twice on the same ledger yields identical output.

        Cites Sage §D8 + v1 cli/commands/cost.py:24-47.

        Sage §D8 LOCKS `cost_summary` callback semantics:
            - prints `f"Built by Bonfire for ${total:.2f}"`
            - then up to 5 recent sessions

        v0.1 analyzer.all_sessions() uses set-union for session_ids then sorts
        by timestamp descending. Within-process determinism is guaranteed by
        stable hashing + total-order sort. The floor test only checks "$0.13"
        is present — would still pass if session ordering jittered between
        runs in a multi-session ledger.

        Determinism matters for:
          - golden-output tests downstream (e.g. snapshot tests);
          - documentation that asserts a specific output shape;
          - user trust (same input → same output is a CLI invariant).
        """
        _write_records(ledger_path, sample_records)
        result1 = runner.invoke(cost_app, [], catch_exceptions=False)
        result2 = runner.invoke(cost_app, [], catch_exceptions=False)
        assert result1.exit_code == 0, f"first invoke exit_code: {result1.exit_code}"
        assert result2.exit_code == 0, f"second invoke exit_code: {result2.exit_code}"
        assert result1.output == result2.output, (
            f"cost summary output differs between invocations.\n"
            f"First:\n{result1.output!r}\n\n"
            f"Second:\n{result2.output!r}"
        )
