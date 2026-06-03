"""Version-literal doc-sweep tests — lock the doc-vs-code version contract (BON-890).

The shipped version of ``bonfire-ai`` is the single source of truth in
``pyproject.toml`` (``version = "0.1.0a2"`` at the time of writing). The
README, the CLAUDE.md contributor guide, and ``docs/release-policy.md``
must not advertise a *stale* version literal: a new contributor who lands
on the README and is told they can run subcommands "in v0.1.0a1" on a
project whose only release-status signal is the version string is being
lied to by the docs.

This sweep enforces BON-890's negative-space + positive-space contract:

  1. The PREVIOUS alpha literal ``0.1.0a1`` MUST NOT appear in
     ``README.md``, ``CLAUDE.md``, or ``docs/release-policy.md``.
     (CHANGELOG.md and historical audit scout-reports are *intentional*
     historical records and are out of scope — see the ticket.)
  2. The CURRENT shipped literal ``0.1.0a2`` MUST appear in both
     ``README.md`` and ``CLAUDE.md`` — the docs name the real version.
  3. ``docs/release-policy.md`` MUST carry a release-checklist item that
     names the version-literal grep, so the drift cannot silently recur.
  4. The version is consistent across the four canonical surfaces:
     ``pyproject.toml``, ``src/bonfire/__init__.py`` (editable fallback),
     ``README.md``, and ``CLAUDE.md``.

These tests read files on disk rather than shelling out; no subprocess.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_README = _REPO_ROOT / "README.md"
_CLAUDE = _REPO_ROOT / "CLAUDE.md"
_RELEASE_POLICY = _REPO_ROOT / "docs" / "release-policy.md"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_INIT = _REPO_ROOT / "src" / "bonfire" / "__init__.py"

# The version literals this sweep guards. ``STALE`` is the previous alpha
# that must be gone from the contributor-facing docs; ``SHIPPED`` is the
# current source-of-truth read from pyproject.toml below.
_STALE_LITERAL = "0.1.0a1"

# The doc surfaces that must NOT carry the stale literal. CHANGELOG.md and
# the historical audit scout-reports are deliberately excluded — those are
# intentional historical references (out of scope per BON-890).
_CONTRIBUTOR_DOCS = (_README, _CLAUDE, _RELEASE_POLICY)


def _shipped_version() -> str:
    """The single source of truth: ``version = "..."`` in pyproject.toml."""
    text = _PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match, "Could not find a `version = \"...\"` line in pyproject.toml"
    return match.group(1)


def _offending_lines(path: Path, needle: str) -> list[tuple[int, str]]:
    """Return (lineno, line) for every line in *path* containing *needle*."""
    text = path.read_text(encoding="utf-8")
    return [
        (i, line.rstrip())
        for i, line in enumerate(text.splitlines(), start=1)
        if needle in line
    ]


# ---------------------------------------------------------------------------
# Negative space — stale literal must be gone from contributor docs
# ---------------------------------------------------------------------------


class TestStaleVersionLiteralGone:
    """The previous alpha literal must not survive in contributor-facing docs."""

    def test_no_stale_literal_in_readme(self) -> None:
        offenders = _offending_lines(_README, _STALE_LITERAL)
        assert not offenders, (
            f"Found stale {_STALE_LITERAL!r} references in README.md "
            f"(should name the shipped version):\n"
            + "\n".join(f"  README.md:{n}: {line}" for n, line in offenders)
        )

    def test_no_stale_literal_in_claude_md(self) -> None:
        offenders = _offending_lines(_CLAUDE, _STALE_LITERAL)
        assert not offenders, (
            f"Found stale {_STALE_LITERAL!r} references in CLAUDE.md:\n"
            + "\n".join(f"  CLAUDE.md:{n}: {line}" for n, line in offenders)
        )

    def test_no_stale_literal_in_release_policy(self) -> None:
        offenders = _offending_lines(_RELEASE_POLICY, _STALE_LITERAL)
        assert not offenders, (
            f"Found stale {_STALE_LITERAL!r} references in docs/release-policy.md:\n"
            + "\n".join(f"  release-policy.md:{n}: {line}" for n, line in offenders)
        )


# ---------------------------------------------------------------------------
# Positive space — the shipped literal must be named in README + CLAUDE
# ---------------------------------------------------------------------------


class TestShippedVersionLiteralPresent:
    """The current shipped version must be named in the contributor docs."""

    def test_shipped_literal_in_readme(self) -> None:
        shipped = _shipped_version()
        text = _README.read_text(encoding="utf-8")
        assert shipped in text, (
            f"README.md does not mention the shipped version {shipped!r} "
            f"(from pyproject.toml). The docs must name the real version."
        )

    def test_shipped_literal_in_claude_md(self) -> None:
        shipped = _shipped_version()
        text = _CLAUDE.read_text(encoding="utf-8")
        assert shipped in text, (
            f"CLAUDE.md does not mention the shipped version {shipped!r} "
            f"(from pyproject.toml). The docs must name the real version."
        )


# ---------------------------------------------------------------------------
# The guard rail — release-policy checklist names the version-literal grep
# ---------------------------------------------------------------------------


class TestReleaseChecklistNamesVersionLiteralGrep:
    """``docs/release-policy.md`` must carry a checklist item naming the grep.

    BON-890 acceptance: "before tagging a new alpha, grep README/CLAUDE for
    the previous version literal." This is the structural guard that keeps
    the doc-vs-code drift from silently recurring.
    """

    def test_release_policy_mentions_grep(self) -> None:
        text = _RELEASE_POLICY.read_text(encoding="utf-8")
        assert "grep" in text.lower(), (
            "docs/release-policy.md must name the version-literal grep in a "
            "release-checklist item (BON-890): 'before tagging a new alpha, "
            "grep README/CLAUDE for the previous version literal.'"
        )

    def test_release_policy_checklist_references_readme_and_claude(self) -> None:
        text = _RELEASE_POLICY.read_text(encoding="utf-8").lower()
        assert "readme" in text and "claude" in text, (
            "docs/release-policy.md's version-literal checklist item must "
            "name both README and CLAUDE as the files to grep before tagging."
        )

    def test_release_policy_checklist_item_is_a_list_entry(self) -> None:
        """The grep guidance lives in an actual checklist/list item, not buried prose."""
        text = _RELEASE_POLICY.read_text(encoding="utf-8")
        grep_lines = [
            line
            for line in text.splitlines()
            if "grep" in line.lower()
        ]
        assert grep_lines, "No line in docs/release-policy.md mentions grep."
        assert any(
            line.lstrip().startswith(("-", "*", "1.", "- [ ]"))
            for line in grep_lines
        ), (
            "The version-literal grep guidance must be a list/checklist item "
            f"(starts with '-', '*' or a number). Found grep on: {grep_lines!r}"
        )


# ---------------------------------------------------------------------------
# Cross-surface consistency — one version across the four canonical files
# ---------------------------------------------------------------------------


class TestVersionConsistencyAcrossSurfaces:
    """``0.1.0a2`` (or whatever pyproject says) is consistent everywhere."""

    def test_init_fallback_matches_pyproject(self) -> None:
        """The editable fallback in __init__.py mirrors pyproject's version."""
        shipped = _shipped_version()
        text = _INIT.read_text(encoding="utf-8")
        assert f'__version__ = "{shipped}"' in text, (
            f"src/bonfire/__init__.py editable-fallback __version__ must be "
            f"{shipped!r} to stay in lockstep with pyproject.toml."
        )

    def test_readme_and_claude_match_pyproject(self) -> None:
        """README + CLAUDE name the shipped version and never the stale one."""
        shipped = _shipped_version()
        for path in (_README, _CLAUDE):
            text = path.read_text(encoding="utf-8")
            assert shipped in text, (
                f"{path.name} must name the shipped version {shipped!r}."
            )
            assert _STALE_LITERAL not in text, (
                f"{path.name} must not name the stale version {_STALE_LITERAL!r}."
            )
