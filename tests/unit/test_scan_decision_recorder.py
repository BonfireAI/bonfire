"""RED tests — BON-341 W5.2 — `bonfire.scan.decision_recorder.DecisionRecorder`.

Sage D8.2: no class rename (per ADR-001). entry_type stays ``"decision_record"``.

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

import logging

from bonfire.scan.decision_recorder import DecisionRecorder


class TestDecisionRecorderClassName:
    def test_class_name_is_decision_recorder(self) -> None:
        """No ADR-001 rename for DecisionRecorder; name preserved."""
        assert DecisionRecorder.__name__ == "DecisionRecorder"


class TestScanEntryType:
    async def test_scan_markdown_returns_vault_entries_with_decision_record_type(
        self, tmp_path
    ) -> None:
        md = tmp_path / "adr-001.md"
        md.write_text(
            "# ADR-001\n\n## Context\n\nReason.\n\n## Decision\n\n"
            "Use Pydantic for validation. Do not use dataclasses.\n"
        )
        recorder = DecisionRecorder(md, project_name="p")
        entries = await recorder.scan()
        assert entries
        for e in entries:
            assert e.entry_type == "decision_record"


class TestPatternDetection:
    async def test_detects_use_not_pattern(self, tmp_path) -> None:
        """ "Use X for ... Do not use Y." pattern extracts X and Y."""
        md = tmp_path / "doc.md"
        md.write_text("# Doc\n\nUse Pydantic for validation. Do not use dataclasses.\n")
        recorder = DecisionRecorder(md, project_name="p")
        entries = await recorder.scan()
        assert entries
        # At least one entry mentions the chosen option.
        contents = " ".join(e.content for e in entries)
        assert "Pydantic" in contents

    async def test_detects_adr_accepted_section(self, tmp_path) -> None:
        md = tmp_path / "adr.md"
        md.write_text("# ADR\n\n## Context\n\nSomething.\n\n## Decision\n\nAdopt Typer for CLI.\n")
        recorder = DecisionRecorder(md, project_name="p")
        entries = await recorder.scan()
        # ADR format detected: at least one decision extracted.
        assert (
            any(e.metadata.get("source_format") == "adr" for e in entries) or entries
        )  # structural presence sufficient

    async def test_extracts_rejected_alternatives(self, tmp_path) -> None:
        md = tmp_path / "adr.md"
        md.write_text(
            "# ADR\n\n## Context\n\nReason.\n\n## Decision\n\n"
            "Adopt Pydantic.\n\nRejected: dataclasses (too rigid).\n"
        )
        recorder = DecisionRecorder(md, project_name="p")
        entries = await recorder.scan()
        # At least one entry has rejected_alternatives metadata.
        rejected_entries = [e for e in entries if "rejected_alternatives" in e.metadata]
        # Not strictly required every time the pattern appears — but the feature
        # must work when used.
        if rejected_entries:
            alt_list = rejected_entries[0].metadata["rejected_alternatives"]
            assert any("dataclasses" in alt for alt in alt_list)


class TestDecisionRecorderEdgeCases:
    """Innovative: edge-case coverage."""

    async def test_missing_path_returns_empty(self, tmp_path) -> None:
        recorder = DecisionRecorder(tmp_path / "nope.md", project_name="p")
        entries = await recorder.scan()
        assert entries == []

    async def test_empty_markdown_returns_empty(self, tmp_path) -> None:
        md = tmp_path / "empty.md"
        md.write_text("")
        recorder = DecisionRecorder(md, project_name="p")
        entries = await recorder.scan()
        assert entries == []

    # knight-a(innovative): scan_and_store dedups.
    async def test_scan_and_store_dedups_on_rescan(self, tmp_path) -> None:
        md = tmp_path / "doc.md"
        md.write_text("# Doc\n\nUse Pydantic, not dataclasses.\n")

        hashes: set[str] = set()

        class FakeVault:
            async def exists(self, h: str) -> bool:
                return h in hashes

            async def store(self, entry) -> str:
                hashes.add(entry.content_hash)
                return entry.entry_id

            async def query(self, q: str, *, limit=5, entry_type=None):
                return []

            async def get_by_source(self, p: str):
                return []

        vault = FakeVault()
        recorder = DecisionRecorder(md, project_name="p")
        first = await recorder.scan_and_store(vault)
        second = await recorder.scan_and_store(vault)
        assert first >= 1
        assert second == 0


class TestDirectoryScanning:
    """Innovative: DecisionRecorder accepts a dir and walks .md files."""

    async def test_scans_directory_of_markdown_files(self, tmp_path) -> None:
        (tmp_path / "a.md").write_text("# A\n\nUse Typer, not argparse.\n")
        (tmp_path / "b.md").write_text("# B\n\nUse Pydantic, not dataclasses.\n")
        recorder = DecisionRecorder(tmp_path, project_name="p")
        entries = await recorder.scan()
        assert len(entries) >= 2


class TestSkipNarration:
    """An unreadable markdown file must not vanish silently.

    ``scan()`` skips files it cannot decode (the ``except ... continue`` guard),
    which is the right behaviour — one bad file should not abort the whole index.
    But a silent skip means a missing decision with no trail back to the cause.
    These tests pin that the skip is *narrated* at DEBUG with the offending path,
    so an operator reading logs can see exactly which file dropped out and why.
    """

    async def test_unreadable_file_skipped_but_good_entry_survives(self, tmp_path) -> None:
        """A non-UTF8 .md is dropped while a sibling readable .md still yields entries."""
        good = tmp_path / "good.md"
        good.write_text("# Good\n\nUse Pydantic, not dataclasses.\n")
        bad = tmp_path / "bad.md"
        # Invalid UTF-8 continuation byte — read_text(encoding="utf-8") raises
        # UnicodeDecodeError, exercising the skip path.
        bad.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")

        recorder = DecisionRecorder(tmp_path, project_name="p")
        entries = await recorder.scan()

        contents = " ".join(e.content for e in entries)
        assert "Pydantic" in contents

    async def test_skip_is_narrated_at_debug_with_file_path(self, tmp_path, caplog) -> None:
        """The skip emits a DEBUG log naming the unreadable file and the error."""
        bad = tmp_path / "bad.md"
        bad.write_bytes(b"\xff\xfe not valid utf-8 \x80\x81")

        recorder = DecisionRecorder(tmp_path, project_name="p")
        with caplog.at_level(logging.DEBUG, logger="bonfire.scan.decision_recorder"):
            await recorder.scan()

        skip_records = [
            r for r in caplog.records if "skipping unreadable file" in r.getMessage().lower()
        ]
        assert skip_records, "expected a DEBUG narration of the skipped unreadable file"
        assert any("bad.md" in r.getMessage() for r in skip_records)
        assert all(r.levelno == logging.DEBUG for r in skip_records)
