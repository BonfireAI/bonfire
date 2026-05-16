# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""BON-1074 — Knight contract for onboard-polish bundle.

Probe N+6 carry-over Bundle 4 (LOW, cosmetic + one regex footgun fix).
Each section below pins a separate work item; all sections must pass
together as the post-Warrior GREEN state.

Work items pinned:

1.  Idempotent ``bonfire init`` stdout — re-runs MUST NOT emit ``Created:``
    for pre-existing artefacts; emit ``Already present:`` instead.

2.  Legacy ``[bonfire.tools]`` migration UX — when ``bonfire init``
    detects a legacy ``[bonfire.tools]`` section in an existing
    ``bonfire.toml``, emit a typer.echo warning instructing the user to
    move it to ``.bonfire/tools.local.toml``. File is NOT auto-modified
    (preserves the "no surprise reads, no mutation" contract pinned by
    ``test_tools_section_is_local.py``).

3.  Unified WS size cap — pick ONE floor (8 KiB, the WS layer cap from
    W9 Lane B) and apply at both the Pydantic ``UserMessage`` validator
    and the websockets ``max_size`` server config. Single source of
    truth = ``MAX_USER_MESSAGE_LEN``.

4.  ``_validate_session_id`` regex tightening — change ``$`` (which
    matches just before a trailing ``\\n``) to ``\\Z`` (true end-of-string)
    so the trailing-newline / log-injection shape is rejected.

5.  Three LOW sub-items:

    5a. ``bonfire cost session <bad-id>`` rejects invalid format at the
        CLI boundary (before loading the analyzer / touching disk),
        not mid-execution.

    5b. ``Unknown record type None`` log spam on legacy ledgers is
        suppressed — at most ONE summary warning per analyzer load,
        not per malformed line.

    5c. ``--conversation-timeout -1`` sentinel renders as a human-readable
        label (``unbounded`` / ``disabled``) in ``--help`` output rather
        than the bare ``-1`` magic number.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from unittest.mock import patch

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from bonfire.cli.app import app
from bonfire.cli.commands.cost import cost_app
from bonfire.models.events import AxiomLoaded, PipelineStarted, _validate_session_id

runner = CliRunner()

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


# ---------------------------------------------------------------------------
# 1. Idempotent ``bonfire init`` stdout
# ---------------------------------------------------------------------------


class TestInitIdempotentStdout:
    """Re-running ``bonfire init`` reports ``Already present:`` for existing artefacts.

    The W9 Lane B work pinned that ``bonfire init`` enumerates every
    artefact it creates in stdout. That pin used the verb ``Created:``
    for every line — but on a re-run the artefacts already exist and the
    line is a lie. BON-1074 wants per-artefact existence detection: each
    line says ``Created:`` when the artefact was actually created this
    run, ``Already present:`` when it pre-existed.

    The W9 Lane B contract (every artefact's name appears in stdout) is
    preserved — only the verb prefix changes.
    """

    def test_fresh_init_emits_created_for_every_artefact(
        self,
        tmp_path: Path,
    ) -> None:
        """Fresh directory → every artefact line uses ``Created:`` prefix."""
        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0, (
            f"init must succeed; got exit_code={result.exit_code}, output={result.output!r}"
        )

        out = _strip_ansi(result.output)
        # All four artefacts under the Created: header on fresh init.
        assert "bonfire.toml" in out
        assert ".bonfire" in out
        assert "agents" in out
        assert ".gitignore" in out
        # No "Already present" lines should appear on a fresh init —
        # nothing pre-existed.
        assert "Already present" not in out, (
            f"fresh init must not report any artefact as 'Already present'; got output={out!r}"
        )

    def test_rerun_emits_already_present_for_each_artefact(
        self,
        tmp_path: Path,
    ) -> None:
        """Re-running init on a fully-initialized dir reports every artefact as already present.

        The artefact names remain in stdout (W9 Lane B reconciliation
        pin), but the verb prefix changes from ``Created:`` to
        ``Already present:`` per line.
        """
        # First run — fresh init.
        first = runner.invoke(app, ["init", str(tmp_path)])
        assert first.exit_code == 0

        # Second run — re-init into the same directory.
        second = runner.invoke(app, ["init", str(tmp_path)])
        assert second.exit_code == 0, (
            f"re-init must succeed; got exit_code={second.exit_code}, output={second.output!r}"
        )

        out = _strip_ansi(second.output)
        # Per-artefact existence: every artefact already exists on disk
        # from the first run, so every line must be "Already present:".
        assert "Already present" in out, (
            f"re-init must emit 'Already present:' for at least one artefact; got output={out!r}"
        )
        # The four artefact names must still appear (W9 Lane B pin).
        assert "bonfire.toml" in out
        assert ".bonfire" in out
        assert "agents" in out
        assert ".gitignore" in out
        # And the "Created:" verb must NOT appear in front of any artefact —
        # nothing was actually created this run. (The literal token "Created"
        # may still appear elsewhere if the implementation keeps a section
        # header for cosmetic symmetry; we assert the per-artefact lines
        # are tagged Already present.)
        for artefact in ("bonfire.toml", ".bonfire", "agents", ".gitignore"):
            # Find the line containing the artefact name and check the verb.
            matching_lines = [ln for ln in out.splitlines() if artefact in ln]
            assert matching_lines, f"re-init stdout must mention {artefact!r}; got output={out!r}"
            assert any("Already present" in ln for ln in matching_lines), (
                f"re-init must tag {artefact!r} as 'Already present:'; "
                f"got matching lines={matching_lines!r}"
            )

    def test_partial_init_emits_mixed_verbs(
        self,
        tmp_path: Path,
    ) -> None:
        """Partially-initialized dir → each artefact tagged per its actual state.

        Pre-create ``bonfire.toml`` and ``.bonfire/`` but leave ``agents/``
        and ``.gitignore`` absent. After ``bonfire init``, the pre-existing
        artefacts must be reported as ``Already present:`` and the newly-
        created ones as ``Created:``.
        """
        # Pre-create two of the four artefacts.
        (tmp_path / "bonfire.toml").write_text("[bonfire]\n")
        (tmp_path / ".bonfire").mkdir()

        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0

        out = _strip_ansi(result.output)

        def line_for(artefact: str) -> str:
            matches = [ln for ln in out.splitlines() if artefact in ln]
            assert matches, f"stdout must mention {artefact!r}; got {out!r}"
            return matches[0]

        assert "Already present" in line_for("bonfire.toml"), (
            f"pre-existing bonfire.toml must be tagged 'Already present:'; "
            f"got line={line_for('bonfire.toml')!r}"
        )
        assert "Already present" in line_for(".bonfire"), (
            f"pre-existing .bonfire/ must be tagged 'Already present:'; "
            f"got line={line_for('.bonfire')!r}"
        )
        assert "Created" in line_for("agents"), (
            f"newly-created agents/ must be tagged 'Created:'; got line={line_for('agents')!r}"
        )
        assert "Created" in line_for(".gitignore"), (
            f"newly-created .gitignore must be tagged 'Created:'; "
            f"got line={line_for('.gitignore')!r}"
        )


# ---------------------------------------------------------------------------
# 2. Legacy ``[bonfire.tools]`` migration UX
# ---------------------------------------------------------------------------


class TestLegacyBonfireToolsMigrationWarning:
    """``bonfire init`` warns when it sees a legacy ``[bonfire.tools]`` section.

    The legacy section was demoted to ``.bonfire/tools.local.toml`` in
    W8.G. ``load_tools_config`` "silently orphans" any pre-migration
    section in ``bonfire.toml`` (no warning, no mutation — pinned by
    ``test_tools_section_is_local.py``). That silent behaviour is correct
    for the reader, but the operator needs SOME nudge to move the section
    or they'll never know.

    Solution: ``bonfire init`` (the natural surface where an operator
    re-touches the project) emits a typer.echo warning when it sees the
    legacy section. The file is NOT auto-modified — the reader contract
    survives untouched.
    """

    def test_init_warns_on_legacy_bonfire_tools_section(
        self,
        tmp_path: Path,
    ) -> None:
        """Pre-existing bonfire.toml with [bonfire.tools] → warning in stderr."""
        legacy_toml = (
            '[bonfire]\nname = "legacy-project"\n\n[bonfire.tools]\ndetected = ["git", "python3"]\n'
        )
        (tmp_path / "bonfire.toml").write_text(legacy_toml)

        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0, (
            f"init must succeed even when legacy [bonfire.tools] is present; "
            f"got exit_code={result.exit_code}, output={result.output!r}"
        )

        out = _strip_ansi(result.output)
        # The warning must surface BOTH the legacy section name AND the
        # destination filename so the operator knows the migration target.
        # ``[bonfire.tools]`` may render with or without surrounding
        # backticks — substring match on the bare token is sufficient.
        assert "bonfire.tools" in out.lower() or "[bonfire.tools]" in out, (
            f"warning must mention the legacy section name; got output={out!r}"
        )
        assert "tools.local.toml" in out, (
            f"warning must name the migration target file; got output={out!r}"
        )

    def test_init_does_not_mutate_legacy_bonfire_toml(
        self,
        tmp_path: Path,
    ) -> None:
        """The warning is informational only — the file is left untouched.

        Pins the "no auto-migration" contract: ``bonfire init`` MUST
        leave the existing ``bonfire.toml`` byte-for-byte identical.
        Auto-mutation is risky (user may have hand-tuned other sections)
        and the W8.G reader already orphans the legacy section harmlessly.
        """
        legacy_toml = (
            '[bonfire]\nname = "legacy-project"\n\n[bonfire.tools]\ndetected = ["git", "python3"]\n'
        )
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text(legacy_toml)
        before = toml_path.read_bytes()

        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0

        after = toml_path.read_bytes()
        assert before == after, (
            f"init must NOT mutate the existing bonfire.toml when warning "
            f"about a legacy [bonfire.tools] section; before={before!r}, after={after!r}"
        )

    def test_init_does_not_warn_on_clean_bonfire_toml(
        self,
        tmp_path: Path,
    ) -> None:
        """A bonfire.toml without [bonfire.tools] → no migration warning.

        Negative control — the warning fires ONLY when the legacy
        section is actually present.
        """
        clean_toml = '[bonfire]\nname = "clean-project"\n'
        (tmp_path / "bonfire.toml").write_text(clean_toml)

        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0

        out = _strip_ansi(result.output)
        # The migration warning contains the literal phrase "legacy
        # [bonfire.tools]" — match on that to avoid false positives from
        # the (legitimate) ``.bonfire/tools.local.toml`` mention in the
        # .gitignore line of the success block.
        lowered = out.lower()
        assert "legacy [bonfire.tools]" not in lowered, (
            f"warning must NOT fire when [bonfire.tools] is absent; got output={out!r}"
        )
        # Defense-in-depth: the warning prefix word ``Warning:`` (init's
        # own warning copy) must not appear either.
        assert "warning:" not in lowered, (
            f"no warning line should fire on clean bonfire.toml; got output={out!r}"
        )


# ---------------------------------------------------------------------------
# 3. Unified WS size cap
# ---------------------------------------------------------------------------


class TestUnifiedWebSocketSizeCap:
    """The Pydantic and websockets caps share a single value (8 KiB).

    Pre-BON-1074 state: ``MAX_USER_MESSAGE_LEN`` (4 KiB) at the Pydantic
    layer, ``_WS_MAX_FRAME_BYTES`` (8 KiB) at the websockets layer. Two
    numbers, two reasons, drift risk. Bundle 4 unifies on the larger
    value (8 KiB) since W9 Lane B already wired
    ``MessageTooLargeError`` at that boundary.
    """

    def test_pydantic_cap_equals_ws_max_frame_bytes(self) -> None:
        """Single source of truth: both layers cite the same byte value."""
        from bonfire.onboard.protocol import MAX_USER_MESSAGE_LEN
        from bonfire.onboard.server import _WS_MAX_FRAME_BYTES

        assert MAX_USER_MESSAGE_LEN == _WS_MAX_FRAME_BYTES, (
            f"WS cap drift: MAX_USER_MESSAGE_LEN={MAX_USER_MESSAGE_LEN}, "
            f"_WS_MAX_FRAME_BYTES={_WS_MAX_FRAME_BYTES}. The two caps must "
            f"share one value (BON-1074 unification)."
        )

    def test_unified_cap_is_8_kib(self) -> None:
        """The unified cap is exactly 8192 bytes (BON-1074 ratification).

        Locks the chosen value so a future widener or shrinker has to
        defend the change with a fresh DOS bracket.
        """
        from bonfire.onboard.protocol import MAX_USER_MESSAGE_LEN

        assert MAX_USER_MESSAGE_LEN == 8192, (
            f"BON-1074 fixes the unified cap at 8192 bytes; got {MAX_USER_MESSAGE_LEN}"
        )


# ---------------------------------------------------------------------------
# 4. ``_validate_session_id`` regex tightening (``$`` -> ``\\Z``)
# ---------------------------------------------------------------------------


class TestSessionIdRegexRejectsTrailingNewline:
    """The pre-BON-1074 regex used ``$`` which matches just before a trailing
    ``\\n``. A session_id of ``abc\\n`` would slip through validation and
    interpolate into filesystem paths with the newline preserved — a
    log-injection / display-corruption shape.

    The fix swaps ``$`` for ``\\Z`` (true end-of-string). Existing
    ``test_session_id_path_traversal_reject.py`` already pins ``foo\\nbar``
    and ``foo\\x00bar``; this test adds the missing ``abc\\n`` shape that
    the prior regex allowed.
    """

    @pytest.mark.parametrize(
        "good_id",
        [
            "abc",
            "abcdef012345",
            "sess-1",
            "ses_001",
            "a" * 64,
        ],
    )
    def test_legitimate_ids_still_accepted(self, good_id: str) -> None:
        """Tightening MUST NOT regress the legitimate shapes."""
        assert _validate_session_id(good_id) == good_id

    @pytest.mark.parametrize(
        "bad_id",
        [
            "abc\n",  # trailing single LF — the footgun the old regex allowed
            "abc\n\n",  # multiple trailing newlines
        ],
    )
    def test_trailing_newline_rejected(self, bad_id: str) -> None:
        """``abc\\n`` (and similar trailing-newline shapes) MUST raise.

        These are exactly the shapes the old ``$`` regex allowed through
        — the BON-1074 ``\\Z`` swap closes the footgun.
        """
        with pytest.raises(ValueError):
            _validate_session_id(bad_id)

    def test_pipeline_started_rejects_trailing_newline_session_id(self) -> None:
        """End-to-end: model-construction also rejects trailing-newline ids."""
        with pytest.raises(ValidationError):
            PipelineStarted(
                session_id="abc\n",
                sequence=0,
                plan_name="p",
                budget_usd=1.0,
            )

    def test_axiom_loaded_default_empty_still_works(self) -> None:
        """Regression canary: empty-string sentinel branch is preserved."""
        event = AxiomLoaded(role="knight", axiom_version="v1")
        assert event.session_id == ""


# ---------------------------------------------------------------------------
# 5a. ``bonfire cost session`` early validation at CLI boundary
# ---------------------------------------------------------------------------


class TestCostSessionEarlyValidation:
    """``bonfire cost session <bad-id>`` rejects path-traversal shapes
    BEFORE loading the analyzer / touching the ledger.

    Pre-BON-1074: an invalid session_id (e.g. ``../../etc/passwd``)
    would flow through the analyzer, possibly opening the ledger file,
    before the not-found exit path. The fix moves the validator to the
    CLI boundary so the rejection happens before any I/O.
    """

    def test_cli_rejects_path_traversal_session_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``cost session ../../etc/passwd`` exits non-zero with a clear message,
        and the analyzer/ledger is NEVER touched.
        """
        # Point the analyzer at a tmp ledger path; the validator must
        # fire BEFORE the analyzer is built, so this path is never read.
        ledger_path = tmp_path / "cost_ledger.jsonl"
        monkeypatch.setenv("BONFIRE_COST_LEDGER_PATH", str(ledger_path))

        # Patch CostAnalyzer's constructor to detect any instantiation —
        # the early-validation contract says we never get there.
        with patch("bonfire.cli.commands.cost.CostAnalyzer") as mock_analyzer:
            result = runner.invoke(
                cost_app,
                ["session", "../../etc/passwd"],
                catch_exceptions=False,
            )

        assert result.exit_code != 0, (
            f"cost session with invalid id must exit non-zero; "
            f"got exit_code={result.exit_code}, output={result.output!r}"
        )
        (
            mock_analyzer.assert_not_called(),
            (
                f"CostAnalyzer must NOT be constructed when the session_id "
                f"is invalid; got call_count={mock_analyzer.call_count}"
            ),
        )

    def test_cli_accepts_legitimate_session_id_format(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A legitimate-format session_id (even if not in the ledger) reaches
        the analyzer (where it then exits 1 as 'not found').

        Negative control — the early validator must NOT over-tighten and
        block legitimate ids.
        """
        ledger_path = tmp_path / "cost_ledger.jsonl"
        # Write an empty file so the analyzer loads cleanly but finds nothing.
        ledger_path.write_text("")
        monkeypatch.setenv("BONFIRE_COST_LEDGER_PATH", str(ledger_path))

        result = runner.invoke(
            cost_app,
            ["session", "ses_999"],
            catch_exceptions=False,
        )
        # Exit 1 expected (session not found) — but the analyzer WAS
        # consulted; the validator did not block this legitimate format.
        assert result.exit_code == 1, (
            f"legitimate-format session id must reach analyzer (exit 1 = not found); "
            f"got exit_code={result.exit_code}, output={result.output!r}"
        )
        assert "not found" in result.output.lower(), (
            f"legitimate-format session id must reach the analyzer's not-found path; "
            f"got output={result.output!r}"
        )


# ---------------------------------------------------------------------------
# 5b. Suppress ``Unknown record type None`` log spam
# ---------------------------------------------------------------------------


class TestUnknownRecordTypeSpamSuppression:
    """``CostAnalyzer._load_if_needed`` previously logged
    ``Unknown record type None`` once per malformed line. A legacy ledger
    with N rows missing the ``type`` field produced N warning lines on
    every load — pure noise. BON-1074 aggregates these to at most ONE
    summary warning per load (or downgrades to debug log).
    """

    def test_legacy_ledger_does_not_spam_warnings_per_line(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A legacy ledger with N malformed rows → ≤ 1 ``Unknown record type``
        warning per analyzer load (not N).
        """
        from bonfire.cost.analyzer import CostAnalyzer

        ledger = tmp_path / "legacy_ledger.jsonl"
        # Write 10 legacy rows that lack a ``type`` field. The old code
        # would log "Unknown record type None on line N" ten times; the
        # fix collapses these to one summary line.
        with ledger.open("w", encoding="utf-8") as fh:
            for i in range(10):
                fh.write(
                    json.dumps(
                        {
                            "timestamp": 1000.0 + i,
                            "session_id": "ses_001",
                            "cost_usd": 0.01,
                        }
                    )
                    + "\n"
                )

        analyzer = CostAnalyzer(ledger_path=ledger)
        with caplog.at_level(logging.WARNING, logger="bonfire.cost.analyzer"):
            # Force the load.
            analyzer.cumulative_cost()

        # Count warnings matching the "Unknown record type" prefix.
        unknown_warnings = [
            r
            for r in caplog.records
            if r.levelno >= logging.WARNING and "Unknown record type" in r.getMessage()
        ]
        assert len(unknown_warnings) <= 1, (
            f"BON-1074: at most one 'Unknown record type' warning per load; "
            f"got {len(unknown_warnings)}: {[r.getMessage() for r in unknown_warnings]}"
        )


# ---------------------------------------------------------------------------
# 5c. ``--conversation-timeout -1`` sentinel display string
# ---------------------------------------------------------------------------


class TestConversationTimeoutSentinelDisplay:
    """``--conversation-timeout`` uses ``-1`` internally as a sentinel
    meaning "user did not pass the flag" (library default governs).
    The bare ``-1`` is a magic number; the ``--help`` text should
    surface a human-readable label instead.

    Acceptance: the ``--help`` block for ``bonfire scan`` does NOT
    advertise ``-1.0`` / ``-1`` as the default value; the help string
    explicitly mentions a human-readable hint about the default
    behaviour (the library's 300s default OR the ``0`` opt-out shape).
    """

    def test_scan_help_does_not_advertise_minus_one_sentinel(self) -> None:
        """``bonfire scan --help`` does not show ``-1.0`` / ``-1`` as the
        ``--conversation-timeout`` default.

        Pre-BON-1074: Typer auto-renders ``[default: -1.0]``. The fix
        either pins ``show_default=False`` and writes a human help line,
        or uses a custom default rendering (e.g. ``[default: use library
        default 300s]``).
        """
        result = runner.invoke(app, ["scan", "--help"])
        assert result.exit_code == 0

        plain = _strip_ansi(result.output)
        # Find the conversation-timeout help block.
        assert "--conversation-timeout" in plain, (
            f"`bonfire scan --help` must document --conversation-timeout; got: {plain!r}"
        )

        # The bare ``-1`` / ``-1.0`` sentinel must NOT appear as a default
        # advertised to the user — that's exposing an internal magic number.
        # We bound the search to a window near the --conversation-timeout
        # mention so an unrelated -1 elsewhere doesn't trigger a false
        # positive.
        idx = plain.find("--conversation-timeout")
        window = plain[idx : idx + 600]
        assert "-1.0" not in window and "-1 " not in window and "-1]" not in window, (
            f"--conversation-timeout help window must not advertise the "
            f"-1 sentinel as a default value; got window: {window!r}"
        )

        # The help text must positively describe the default behaviour.
        # Accept any of the documented hints: 300, "default", "disable", etc.
        lowered = window.lower()
        assert any(
            hint in lowered for hint in ("300", "default", "disable", "unbounded", "indefinitely")
        ), (
            f"--conversation-timeout help window must positively describe "
            f"the default / opt-out shape; got window: {window!r}"
        )


# ---------------------------------------------------------------------------
# Composite smoke — every BON-1074 item co-exists on a fresh checkout
# ---------------------------------------------------------------------------


class TestBon1074CompositeSmoke:
    """Smoke check: running ``init`` twice on the same dir with a legacy
    ``[bonfire.tools]`` section exercises items 1 and 2 together cleanly.
    """

    def test_rerun_with_legacy_section_combined_paths(
        self,
        tmp_path: Path,
    ) -> None:
        """Re-init on a legacy-tools-laden, partially-initialized dir.

        Combines: idempotent stdout (item 1) + legacy-tools warning
        (item 2). Both signals must fire on the same invocation.
        """
        legacy = '[bonfire]\nname = "legacy-project"\n\n[bonfire.tools]\ndetected = ["git"]\n'
        (tmp_path / "bonfire.toml").write_text(legacy)

        result = runner.invoke(app, ["init", str(tmp_path)])
        assert result.exit_code == 0, result.output

        out = _strip_ansi(result.output)
        # Idempotent stdout (item 1) — bonfire.toml pre-existed.
        assert "Already present" in out
        # Legacy-tools warning (item 2).
        assert "tools.local.toml" in out
