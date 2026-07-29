# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: the WIDTH of the ``.gitignore`` that ``bonfire init`` seeds.

This module owns ONE contract, graded in both directions.

  * No UNDER-coverage (the control rod). Every operator-local path the
    seed exists to cover MUST be ignored by the seeded ``.gitignore``
    itself: the per-machine ``.bonfire/tools.local.toml`` written by
    ``bonfire scan``, and the knowledge-backend store at
    ``.bonfire/vault`` in BOTH on-disk shapes that one path can take.
    Without this direction the whole class is satisfied by a seed that
    covers nothing at all.
  * No OVER-coverage. The committable sub-paths under ``.bonfire/`` MUST
    stay stageable: ``sessions/`` handoffs (operators commit these so the
    next session picks up the thread), ``context.json`` (portable project
    config) and the opt-in ``costs.jsonl`` ledger. A bare ``.bonfire/``
    line is the obvious way to get this wrong, so it is also named
    directly, and the seeded ``.bonfire`` entries are pinned as a closed
    set — a THIRD distinct path would fail here even if it were narrow.

Why the store needs two probes. ``bonfire.knowledge.get_vault_backend``
documents one default ``vault_path`` for every backend,
``.bonfire/vault``. The LanceDB backend turns that path into a DIRECTORY
(a vector index built from the operator's own source). The SQLite backend
hands the same string to ``sqlite3.connect``, which creates a REGULAR
FILE whose ``vault_entries.content`` column holds that source as
cleartext — strictly worse to leak than embeddings. A trailing-slash
(directory-only) pattern covers the first shape and NOT the second, and
``git check-ignore``'s verdict on such a pattern depends on what is on
disk, so this module materialises the file shape rather than trusting a
name.

Preventive, not the closing of a live leak. ``get_vault_backend`` has no
production caller today: ``engine/composition.py`` documents the ingest
consumer as deliberately not wired, and ``VaultConfig`` carries only
``session_dir`` and ``context_file``, so no ``bonfire.toml`` key selects
a backend. This pin is what makes the store safe to enable — it does not
report that anything is leaking now.

Split out of ``test_tools_section_is_local.py`` (which keeps Pins #1-#8,
including the init-coverage and idempotence pins) so that one contract
owns one file.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

# The exact set of non-comment ``.bonfire`` entries ``bonfire init`` is
# allowed to seed. Written as LITERAL strings on purpose: importing
# ``_GITIGNORE_LINES`` from ``init.py`` would make the closed-world
# assertion below true by construction — the gate would then grade
# nothing at all, no matter what init seeds.
_EXPECTED_SEEDED_BONFIRE_ENTRIES = {".bonfire/tools.local.toml", ".bonfire/vault"}

# Blanket spellings that would cover every committable sub-path at once.
_BLANKET_SPELLINGS = {".bonfire", ".bonfire/", ".bonfire/*", ".bonfire/**"}

# Neutralise the contributor's and the CI runner's own git configuration
# for EVERY git subprocess this module runs. ``git check-ignore`` reports
# matches from ``core.excludesFile`` as well as from the repo's
# ``.gitignore``, so a global excludes carrying ``*.json``, ``*.md`` or
# ``.bonfire/`` would otherwise decide this test's verdict on a file
# ``bonfire init`` never wrote. ``tests/conftest.py`` scrubs ``BONFIRE_*``
# only; nothing else does this. Residual: git's XDG fallback
# (``~/.config/git/ignore``) is not disabled by these two variables, which
# is why every assertion below attributes the match to a SOURCE rather
# than merely asking whether one exists.
_GIT_ENV = {
    **os.environ,
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _run_init(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Run ``bonfire init .`` inside *tmp_path* and require a clean exit.

    So no pin can mistake a crashed init for a narrow gitignore. This is a
    verbatim twin of the helper in ``test_tools_section_is_local.py``:
    sharing it would need either a third helper module or a
    ``tests/conftest.py`` fixture, and a new import surface is a worse
    trade than six duplicated lines whose meaning is fixed by the
    assertion text they carry.
    """
    from typer.testing import CliRunner

    from bonfire.cli.app import app

    monkeypatch.chdir(tmp_path)
    result = CliRunner().invoke(app, ["init", "."])
    assert result.exit_code == 0, (
        f"bonfire init must succeed in {tmp_path}; got exit_code={result.exit_code}, "
        f"output={result.output!r}"
    )


def _ignored_by(repo: Path, rel_path: str) -> str:
    """Return the ``source:line:pattern`` that ignores *rel_path*, or ``""``.

    ``git check-ignore -v`` rather than ``-q``: the quiet form answers only
    "something matched", which cannot tell the seeded ``.gitignore`` from an
    unrelated global excludes file, and both directions below need the
    source.

    Exit statuses: 0 one or more patterns matched, 1 none did, 128 a fatal
    error (not a repo, bad option, unreadable index). Folding 128 into
    ``""`` — "not ignored" — would make every must-NOT-be-ignored assertion
    pass on a void while looking green, so the status is asserted first and
    a fatal git error is a loud red instead of an alibi.
    """
    check = subprocess.run(
        ["git", "check-ignore", "-v", rel_path],
        cwd=repo,
        capture_output=True,
        text=True,
        env=_GIT_ENV,
    )
    assert check.returncode in (0, 1), (
        f"git check-ignore could not answer for {rel_path!r} in {repo}: "
        f"returncode={check.returncode} (0=ignored, 1=not ignored; anything "
        f"else is a fatal git error, never a verdict). "
        f"stderr={check.stderr!r} stdout={check.stdout!r}"
    )
    return check.stdout.strip() if check.returncode == 0 else ""


class TestInitGitignoreCoversOperatorStateAndNothingElse:
    """``bonfire init``'s seeded ``.gitignore`` is exactly as wide as it needs.

    Graded by real ``git check-ignore`` against a real repository, so the
    contract is git's own pattern semantics rather than this test's idea of
    them.
    """

    def test_seeded_gitignore_covers_operator_state_without_over_covering(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``git check-ignore`` grades both directions against a real repo."""
        _run_init(tmp_path, monkeypatch)

        gitignore_path = tmp_path / ".gitignore"

        # The skip below fires ONLY when git is absent or cannot create a
        # repo at all — never as a way to absorb a real gitignore failure,
        # and the reason names which of the two it was.
        try:
            subprocess.run(
                ["git", "init", "-q"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
                env=_GIT_ENV,
            )
        except (FileNotFoundError, subprocess.CalledProcessError) as exc:
            pytest.skip(f"git unavailable, cannot grade gitignore semantics: {exc!r}")

        # Materialise the SQLite shape: a REGULAR FILE at .bonfire/vault,
        # exactly what ``sqlite3.connect(".bonfire/vault")`` produces. This
        # is not decoration — a directory-only pattern's verdict DEPENDS on
        # the on-disk shape (git will not apply a trailing-slash pattern to
        # something it cannot see is a directory), so probing the name alone
        # would grade a different question than the one operators face.
        (tmp_path / ".bonfire" / "vault").write_bytes(b"")

        committable_paths = [
            ".bonfire/sessions/handoff.md",
            ".bonfire/context.json",
            ".bonfire/costs.jsonl",
            # ``.bonfire/vault/seed.md`` was asserted committable here until
            # it was measured: nothing under ``src/`` ever writes a
            # ``seed.md`` and the string appeared in exactly one place in the
            # whole repository — this assertion. It guarded a phantom. The
            # vault is operator content either way, so the path moved to
            # ``ignored_paths`` below.
        ]
        ignored_paths = [
            # Per-machine tool inventory written by ``bonfire scan``.
            ".bonfire/tools.local.toml",
            # The store's TWO shapes. The bare path is the SQLite shape
            # (materialised above as a regular file); the nested paths are
            # the LanceDB directory shape. Together they separate FILE from
            # DIRECTORY, which is the distinction a trailing slash gets
            # wrong. ``some-index.idx`` is deliberately synthetic — no code
            # in this repo writes that name; it is here so the pattern is
            # shown to cover ARBITRARY nesting under the directory, not one
            # known filename.
            ".bonfire/vault",
            ".bonfire/vault/vault_v2.lance/data/0.lance",
            ".bonfire/vault/some-index.idx",
        ]
        # Non-vacuity: an empty list makes its loop below pass while grading
        # nothing, which is how this whole class goes quiet.
        assert committable_paths, "committable_paths is empty: over-coverage check is vacuous"
        assert ignored_paths, "ignored_paths is empty: the coverage control rod is vacuous"

        body = gitignore_path.read_text()

        # Direction 2 first: the control rod. Attribution to ``.gitignore:``
        # is what keeps an unrelated pattern in someone's global excludes
        # (say ``*.lance``) from satisfying it over a seed covering nothing.
        for rel_path in ignored_paths:
            match = _ignored_by(tmp_path, rel_path)
            assert match.startswith(".gitignore:"), (
                f"bonfire init's .gitignore at {gitignore_path} UNDER-covers: "
                f"{rel_path!r} is not ignored by the SEEDED .gitignore, so "
                f"`git add` would stage the operator's own content. "
                f"check-ignore said {match!r} (empty = no pattern matched; a "
                f"non-.gitignore source means some other excludes file, not "
                f"the seed, would have to do the job). Gitignore body:\n{body}"
            )

        # Direction 1: no over-coverage. The verdict is about the SEEDED
        # file, so only a ``.gitignore:``-sourced match is an accusation
        # against ``bonfire init``. A foreign source is collected and
        # reported separately, at the very end, so that a contributor's own
        # excludes can never (a) be mistaken for bonfire over-covering, nor
        # (b) pre-empt bonfire's verdict.
        foreign_matches: list[str] = []
        for rel_path in committable_paths:
            match = _ignored_by(tmp_path, rel_path)
            assert not match.startswith(".gitignore:"), (
                f"bonfire init's .gitignore at {gitignore_path} OVER-covers: "
                f"{rel_path!r} is matched by {match!r} but must remain "
                f"stageable. Gitignore body:\n{body}"
            )
            if match:
                foreign_matches.append(f"{rel_path} <- {match}")

        seeded = [
            line.strip()
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        # Blanket cover, named directly. The committable loop already rules
        # it out, but asserting it by name makes the FAILURE readable
        # instead of leaving the reader to infer which pattern was too wide.
        blanket = _BLANKET_SPELLINGS & set(seeded)
        assert not blanket, (
            f"bonfire init seeded a blanket .bonfire cover {sorted(blanket)!r} in "
            f"{gitignore_path}, which ignores every committable sub-path under it. "
            f"Seeded entries: {seeded!r}. Gitignore body:\n{body}"
        )

        # Closed-world width. The probe lists above are finite samples, so
        # on their own they cannot see a THIRD seeded path (``.bonfire/cache/``,
        # ``.bonfire/tmp*``) that no sample happens to touch. Set equality
        # against a literal expectation is the width bound: a new seeded
        # entry fails here and has to be argued for, and a dropped entry
        # fails here too.
        seeded_bonfire = {line for line in seeded if ".bonfire" in line}
        assert seeded_bonfire == _EXPECTED_SEEDED_BONFIRE_ENTRIES, (
            f"the set of .bonfire entries bonfire init seeds into "
            f"{gitignore_path} changed. Expected exactly "
            f"{sorted(_EXPECTED_SEEDED_BONFIRE_ENTRIES)!r}; got "
            f"{sorted(seeded_bonfire)!r} (added "
            f"{sorted(seeded_bonfire - _EXPECTED_SEEDED_BONFIRE_ENTRIES)!r}, "
            f"missing {sorted(_EXPECTED_SEEDED_BONFIRE_ENTRIES - seeded_bonfire)!r}). "
            f"Every seeded path must be operator-local AND must not cover a "
            f"committable sibling; if this change is correct, update the "
            f"expectation here deliberately. Gitignore body:\n{body}"
        )

        # Environment signal, deliberately last and deliberately worded so
        # it can never be read as an accusation against ``bonfire init``.
        assert not foreign_matches, (
            f"THIS IS NOT A BONFIRE DEFECT: bonfire init's seed graded clean "
            f"above. Some OTHER excludes source on this machine ignores a "
            f"path bonfire deliberately leaves committable: {foreign_matches!r}. "
            f"GIT_CONFIG_GLOBAL and GIT_CONFIG_SYSTEM are already pointed at "
            f"{os.devnull} for this test, so the likely source is git's XDG "
            f"fallback (~/.config/git/ignore) or .git/info/exclude. Fix the "
            f"environment, or neutralise that source here too — do not widen "
            f"or narrow the seed to satisfy it."
        )
