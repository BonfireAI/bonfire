"""BON-341 RED — Knight B (conservative) — bonfire.scan.decision_recorder.

Covers ``DecisionRecorder`` (no class rename) per Sage D8.2 / D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations

from pathlib import Path

from bonfire.scan.decision_recorder import DecisionRecorder


class TestDecisionRecorder:
    def test_class_name_is_decision_recorder(self):
        assert DecisionRecorder.__name__ == "DecisionRecorder"

    def test_scan_markdown_returns_vault_entries_with_decision_record_type(
        self, tmp_path: Path
    ):
        (tmp_path / "DECISION.md").write_text(
            "# Decision: use sqlite\n\n"
            "We USE sqlite NOT postgres for local dev.\n"
        )
        recorder = DecisionRecorder(tmp_path)
        entries = recorder.scan()
        assert len(entries) >= 1
        # entry_type string is UNCHANGED per Sage D9.8 red line #9.
        assert all(e.entry_type == "decision_record" for e in entries)

    def test_detects_use_not_pattern(self, tmp_path: Path):
        (tmp_path / "DECISION.md").write_text(
            "# Title\n\nWe USE sqlite NOT postgres because it is simpler.\n"
        )
        recorder = DecisionRecorder(tmp_path)
        entries = recorder.scan()
        assert len(entries) >= 1
        joined = " ".join(e.content.lower() for e in entries)
        assert "sqlite" in joined or "postgres" in joined

    def test_detects_adr_accepted_section(self, tmp_path: Path):
        (tmp_path / "ADR-001.md").write_text(
            "# ADR-001: pick datastore\n\n"
            "## Status\nAccepted\n\n"
            "## Decision\nWe will use sqlite.\n"
        )
        recorder = DecisionRecorder(tmp_path)
        entries = recorder.scan()
        assert len(entries) >= 1

    def test_extracts_rejected_alternatives(self, tmp_path: Path):
        (tmp_path / "adr.md").write_text(
            "# ADR: datastore choice\n\n"
            "## Rejected\n- postgres — too heavy\n- mysql — licensing concerns\n"
        )
        recorder = DecisionRecorder(tmp_path)
        entries = recorder.scan()
        assert len(entries) >= 1
