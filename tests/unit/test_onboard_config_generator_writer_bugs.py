# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract pins for two ``config_generator`` writer bugs.

Bug 1 — ``[bonfire.git] remote`` writer/scanner label mismatch
==============================================================
``src/bonfire/onboard/scanners/git_state.py`` emits remote events with
``label=<remote_name>`` (e.g. ``"origin"``, ``"upstream"``) and
``value=<sanitised-url>``. The original
``src/bonfire/onboard/config_generator.py:_build_git`` looked for
``label == "remote"`` — which the scanner NEVER emits — so the
``[bonfire.git] remote`` line silently dropped out of every generated
``bonfire.toml``.

The fix is writer-side: ``_build_git`` ignores the known non-remote labels
(``repository``, ``branch``, ``branches``, ``working tree``, ``last
commit``) and picks the remote event whose label is ``"origin"`` (or, if
no ``origin``, the first remote in scan order). Error-event values
(``value == "error"``) are skipped too — a failed git-remote call must
not become a TOML value.

Bug 2 — ``[bonfire.claude_memory]`` sentinel-string-as-value
=============================================================
The claude_memory scanner emits **redaction sentinels** for ``model``,
``permissions``, and ``extensions`` — strings that describe presence /
structure, never the literal value (see
``src/bonfire/onboard/scanners/claude_memory.py`` lines 86-99 for the
privacy posture). Concrete sentinels:

* ``model = "set"``
* ``permissions = "3 keys"`` (or ``"1 key"``, etc.)
* ``extensions = "3 enabled"``

The original ``_build_claude_memory`` stamped these into the user's
``bonfire.toml`` as literal TOML values (``model = "set"``,
``permissions = "3 keys"``). The result is unreadable noise that looks
like real config.

The fix is writer-side, option A: emit the sentinels as TOML **comments**
inside the ``[bonfire.claude_memory]`` section rather than quoted values.
The section keeps its diagnostic value (the user sees that Claude Code
config was detected) without polluting the config with synthetic strings.
Real numeric values (memory-type counts) stay as actual TOML keys.
"""

from __future__ import annotations

import tomllib

from bonfire.onboard.config_generator import (
    _build_claude_memory,
    _build_git,
    _sanitize_toml_comment,
    generate_config,
)
from bonfire.onboard.protocol import ScanUpdate


def _scan(panel: str, label: str, value: str, detail: str = "") -> ScanUpdate:
    return ScanUpdate(panel=panel, label=label, value=value, detail=detail)


# ===========================================================================
# Bug 1 — [bonfire.git] remote field populated from scanner-shaped events
# ===========================================================================


class TestGitRemoteWriterMatchesScannerShape:
    """``_build_git`` must read remote URLs from the scanner's per-name events."""

    def test_remote_field_populated_from_origin_event(self) -> None:
        """Scanner emits label='origin' value=<url>; writer surfaces it as remote=."""
        scans = [
            _scan("git_state", "repository", "initialized"),
            _scan("git_state", "branch", "main"),
            _scan("git_state", "origin", "github.com/BonfireAI/bonfire"),
            _scan("git_state", "working tree", "clean"),
        ]
        result = _build_git(scans)
        assert result is not None, "git section should be built when scans present"
        fragment, _ = result
        parsed = tomllib.loads(fragment)
        git = parsed.get("bonfire", {}).get("git", {})
        assert git.get("remote") == "github.com/BonfireAI/bonfire", (
            f"_build_git must emit remote=<origin-url>; got git table: {git!r}\n"
            f"Raw fragment:\n{fragment}"
        )
        # Sanity: branch still works (regression guard on the parallel field).
        assert git.get("branch") == "main"

    def test_remote_field_prefers_origin_over_other_remotes(self) -> None:
        """When both origin and upstream are present, remote = origin's URL."""
        scans = [
            _scan("git_state", "repository", "initialized"),
            _scan("git_state", "upstream", "github.com/upstream-org/repo"),
            _scan("git_state", "origin", "github.com/me/repo"),
        ]
        result = _build_git(scans)
        assert result is not None
        fragment, _ = result
        parsed = tomllib.loads(fragment)
        git = parsed.get("bonfire", {}).get("git", {})
        assert git.get("remote") == "github.com/me/repo", (
            f"_build_git must prefer origin over upstream; got: {git!r}"
        )

    def test_remote_field_falls_back_to_first_when_no_origin(self) -> None:
        """If origin is absent, pick the first remote in scan order."""
        scans = [
            _scan("git_state", "repository", "initialized"),
            _scan("git_state", "fork", "github.com/fork/repo"),
            _scan("git_state", "upstream", "github.com/upstream/repo"),
        ]
        result = _build_git(scans)
        assert result is not None
        fragment, _ = result
        parsed = tomllib.loads(fragment)
        git = parsed.get("bonfire", {}).get("git", {})
        # First non-known-label remote-shaped scan in order is "fork".
        assert git.get("remote") == "github.com/fork/repo", (
            f"_build_git must fall back to first remote when no origin; got: {git!r}"
        )

    def test_remote_field_absent_when_no_remotes_scanned(self) -> None:
        """No remote events -> the ``remote = ...`` line is absent."""
        scans = [
            _scan("git_state", "repository", "initialized"),
            _scan("git_state", "branch", "main"),
            _scan("git_state", "working tree", "clean"),
        ]
        result = _build_git(scans)
        assert result is not None
        fragment, _ = result
        # The legitimate output preserves the section header but
        # omits the ``remote`` key entirely.
        assert "remote = " not in fragment, (
            f"_build_git must not emit ``remote = ...`` when no remote scans; "
            f"fragment was:\n{fragment}"
        )
        parsed = tomllib.loads(fragment)
        git = parsed.get("bonfire", {}).get("git", {})
        assert "remote" not in git

    def test_remote_field_skips_error_value_events(self) -> None:
        """An error event for ``remotes`` must not flow into ``remote = "error"``."""
        scans = [
            _scan("git_state", "repository", "initialized"),
            # An error event named "remotes" (the bulk-command failure path).
            _scan("git_state", "remotes", "error", "git remote failed (rc=128)"),
        ]
        result = _build_git(scans)
        assert result is not None
        fragment, _ = result
        # Neither the literal ``"error"`` nor the failed-command detail
        # should land in the emitted TOML as a value of ``remote =``.
        assert 'remote = "error"' not in fragment, "error event must not become a TOML remote value"
        parsed = tomllib.loads(fragment)
        git = parsed.get("bonfire", {}).get("git", {})
        assert "remote" not in git

    def test_remote_field_skips_known_non_remote_labels(self) -> None:
        """Labels like ``branches`` (the count) must not be mistaken for a remote."""
        scans = [
            _scan("git_state", "repository", "initialized"),
            _scan("git_state", "branch", "main"),
            _scan("git_state", "branches", "3"),  # count, not a remote
            _scan("git_state", "last commit", "2026-05-15 12:00:00 -0700"),
            _scan("git_state", "working tree", "clean"),
            # No remote events at all.
        ]
        result = _build_git(scans)
        assert result is not None
        fragment, _ = result
        parsed = tomllib.loads(fragment)
        git = parsed.get("bonfire", {}).get("git", {})
        assert "remote" not in git, (
            f"_build_git must not promote ``branches`` or ``last commit`` to "
            f"a remote value; got: {git!r}"
        )


# ===========================================================================
# Bug 2 — [bonfire.claude_memory] no sentinel strings as TOML values
# ===========================================================================


class TestClaudeMemorySentinelsNotEmittedAsValues:
    """Sentinels (``"set"``, ``"3 keys"``, ``"3 enabled"``) MUST NOT appear as
    TOML string values inside ``[bonfire.claude_memory]``.

    They are diagnostic / redaction markers from the scanner. The section
    keeps its existence (so the user sees Claude Code was detected) but
    sentinels are emitted as TOML comments, not as quoted values.
    """

    def test_model_sentinel_not_emitted_as_toml_value(self) -> None:
        """``model = "set"`` MUST NOT appear in the rendered section."""
        scans = [_scan("claude_memory", "model", "set")]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result

        parsed = tomllib.loads(fragment)
        cm = parsed.get("bonfire", {}).get("claude_memory", {})
        assert cm.get("model") != "set", (
            f'sentinel ``"set"`` must not be stamped as model = ; '
            f"section parsed as: {cm!r}\nFragment:\n{fragment}"
        )
        # Either absent entirely, or surfaced as a comment.
        assert "model" not in cm, f"sentinel model must not appear as a TOML key; got: {cm!r}"

    def test_permissions_sentinel_not_emitted_as_toml_value(self) -> None:
        """``permissions = "3 keys"`` MUST NOT appear in the rendered section."""
        scans = [_scan("claude_memory", "permissions", "3 keys", detail="env, deny")]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result

        parsed = tomllib.loads(fragment)
        cm = parsed.get("bonfire", {}).get("claude_memory", {})
        assert cm.get("permissions") != "3 keys", (
            f'sentinel ``"3 keys"`` must not be stamped as permissions = ; '
            f"section parsed as: {cm!r}\nFragment:\n{fragment}"
        )
        assert "permissions" not in cm, (
            f"sentinel permissions must not appear as a TOML key; got: {cm!r}"
        )

    def test_extensions_sentinel_not_emitted_as_toml_value(self) -> None:
        """``extensions = "3 enabled"`` MUST NOT appear in the rendered section."""
        scans = [_scan("claude_memory", "extensions", "3 enabled")]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result

        parsed = tomllib.loads(fragment)
        cm = parsed.get("bonfire", {}).get("claude_memory", {})
        assert cm.get("extensions") != "3 enabled", (
            f'sentinel ``"3 enabled"`` must not be stamped as extensions = ; '
            f"section parsed as: {cm!r}\nFragment:\n{fragment}"
        )
        assert "extensions" not in cm

    def test_memory_count_keys_still_emitted_as_real_toml_values(self) -> None:
        """Memory counts (``feedback_memories = 5``) are REAL data — keep them."""
        scans = [
            _scan("claude_memory", "feedback memories", "5"),
            _scan("claude_memory", "project memories", "3"),
        ]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result
        parsed = tomllib.loads(fragment)
        cm = parsed.get("bonfire", {}).get("claude_memory", {})
        assert cm.get("feedback_memories") == 5, (
            f"memory-type counts MUST stay as real TOML values; got: {cm!r}"
        )
        assert cm.get("project_memories") == 3

    def test_sentinels_still_visible_as_comments_in_section(self) -> None:
        """Day-1 signal preserved: sentinels surface as TOML comments.

        The user opening the generated ``bonfire.toml`` should still see
        SOME trace that Claude Code was detected. The chosen rendering is
        a TOML comment line inside ``[bonfire.claude_memory]``.
        """
        scans = [
            _scan("claude_memory", "model", "set"),
            _scan("claude_memory", "permissions", "3 keys"),
        ]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result
        # The section header is still present.
        assert "[bonfire.claude_memory]" in fragment
        # Both sentinel labels survive as informational text in comments.
        # We require the literal label tokens to appear inside a comment
        # line so the reader can still discover "yes, model was set."
        comment_lines = [
            line.strip() for line in fragment.splitlines() if line.strip().startswith("#")
        ]
        joined_comments = " ".join(comment_lines).lower()
        assert "model" in joined_comments, (
            "model sentinel must surface as a comment so the section retains its diagnostic value"
        )
        assert "permissions" in joined_comments

    def test_section_with_only_sentinels_does_not_break_toml(self) -> None:
        """A section reduced to header + comments must still be valid TOML."""
        scans = [
            _scan("claude_memory", "model", "set"),
            _scan("claude_memory", "permissions", "3 keys"),
            _scan("claude_memory", "extensions", "3 enabled"),
        ]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result
        parsed = tomllib.loads(fragment)
        # The section may parse as an empty table (only comments inside),
        # but the TOML must still parse cleanly.
        cm = parsed.get("bonfire", {}).get("claude_memory", {})
        assert cm == {} or all(
            not isinstance(v, str) or v not in {"set", "3 keys", "3 enabled"} for v in cm.values()
        ), (
            f"sentinel strings must not appear as values anywhere in "
            f"[bonfire.claude_memory]; got: {cm!r}"
        )


# ===========================================================================
# End-to-end: generate_config still produces parseable TOML with the fixes
# ===========================================================================


class TestGenerateConfigEndToEndAfterFixes:
    """Both fixes hold under the full ``generate_config`` pipeline."""

    def test_full_pipeline_with_realistic_git_and_claude_memory_scans(self) -> None:
        scans = [
            # git_state (scanner-shaped emissions)
            _scan("git_state", "repository", "initialized"),
            _scan("git_state", "branch", "main"),
            _scan("git_state", "origin", "github.com/BonfireAI/bonfire"),
            _scan("git_state", "working tree", "clean"),
            # claude_memory (scanner-shaped sentinels)
            _scan("claude_memory", "Claude Code", "installed"),
            _scan("claude_memory", "model", "set"),
            _scan("claude_memory", "permissions", "3 keys", detail="env, deny"),
            _scan("claude_memory", "feedback memories", "5"),
        ]
        result = generate_config(scans, profile={}, project_name="demo")
        parsed = tomllib.loads(result.config_toml)
        bonfire = parsed.get("bonfire", {})

        # Bug 1: remote is populated.
        assert bonfire.get("git", {}).get("remote") == "github.com/BonfireAI/bonfire"
        assert bonfire.get("git", {}).get("branch") == "main"

        # Bug 2: sentinels are NOT stamped as values.
        cm = bonfire.get("claude_memory", {})
        assert cm.get("model") != "set"
        assert cm.get("permissions") != "3 keys"
        assert "model" not in cm
        assert "permissions" not in cm
        # Real numeric data preserved.
        assert cm.get("feedback_memories") == 5


# ===========================================================================
# MEDIUM 1 — _sanitize_toml_comment strips full control-char range
# ===========================================================================


class TestSanitizeTomlCommentStripsControlChars:
    """``_sanitize_toml_comment`` must strip every byte rejected by TOML 1.0.

    TOML 1.0 rejects U+0000-U+001F and U+007F inside comments. A hostile
    ``~/.claude/settings.json`` with top-level keys containing those bytes
    would flow through ``_scan_settings -> detail -> comment line ->
    tomllib.loads`` and crash. The sanitizer is the chokepoint.

    Tab (U+0009) is preserved (it is the one whitespace character TOML
    allows inside comments).
    """

    def test_nul_byte_stripped(self) -> None:
        """NUL (U+0000) must not survive into a TOML comment."""
        result = _sanitize_toml_comment("before\x00after")
        assert "\x00" not in result, f"NUL must be stripped from comment text; got: {result!r}"
        # And the cleaned line must round-trip through tomllib as a comment.
        tomllib.loads(f"# {result}\n")

    def test_del_char_stripped(self) -> None:
        """DEL (U+007F) must not survive into a TOML comment."""
        result = _sanitize_toml_comment("before\x7fafter")
        assert "\x7f" not in result, f"DEL must be stripped from comment text; got: {result!r}"
        tomllib.loads(f"# {result}\n")

    def test_representative_c0_control_chars_stripped(self) -> None:
        """Other C0 control chars (excluding tab) must be stripped too."""
        # Representative selection across the 0x01-0x1F range; tab (0x09)
        # is whitespace TOML allows and is preserved separately.
        codepoints = [0x01, 0x07, 0x0B, 0x0C, 0x1B, 0x1F]
        for cp in codepoints:
            ch = chr(cp)
            result = _sanitize_toml_comment(f"x{ch}y")
            assert ch not in result, f"control char U+{cp:04X} must be stripped; got: {result!r}"
            # The output must be valid as a TOML comment.
            tomllib.loads(f"# {result}\n")

    def test_tab_preserved(self) -> None:
        """Tab (U+0009) is the one whitespace control char TOML allows."""
        result = _sanitize_toml_comment("a\tb")
        # The cleaned line must still round-trip — tab inside a comment
        # is legal TOML.
        tomllib.loads(f"# {result}\n")
        # And the visible "a" and "b" survive (the sanitizer is allowed
        # to preserve OR strip the tab, but not corrupt the surrounding
        # text).
        assert "a" in result
        assert "b" in result

    def test_newline_still_folded(self) -> None:
        """Regression guard: \\n and \\r still don't smuggle table headers."""
        result = _sanitize_toml_comment("safe\n[evil.section]\nstill")
        assert "\n" not in result, f"newline must be folded out; got: {result!r}"
        assert "\r" not in result
        tomllib.loads(f"# {result}\n")

    def test_full_control_range_round_trip(self) -> None:
        """A string containing every C0 + DEL byte must produce valid TOML."""
        hostile = "x" + "".join(chr(c) for c in range(0x00, 0x20)) + "\x7f" + "y"
        result = _sanitize_toml_comment(hostile)
        # The sanitized output as a comment must parse cleanly.
        parsed = tomllib.loads(f"# {result}\n")
        # No keys — the line is a pure comment.
        assert parsed == {}

    def test_emission_path_with_hostile_detail_round_trips(self) -> None:
        """End-to-end: a ScanUpdate detail full of control chars survives.

        The full ``_build_claude_memory`` -> ``_sanitize_toml_comment`` ->
        ``tomllib.loads`` path must not crash on a hostile detail string.
        """
        hostile_detail = "env\x00deny\x7fextra\x01key"
        scans = [
            _scan(
                "claude_memory",
                "permissions",
                "3 keys",
                detail=hostile_detail,
            )
        ]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result
        # The end-to-end fragment must parse — this is the contract that
        # the previous sanitizer (\r\n-only) failed on hostile input.
        tomllib.loads(fragment)
