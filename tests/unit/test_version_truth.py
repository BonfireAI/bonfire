# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Guard: every place this project states its version states the same one.

A version-truth guard existed once. ``scripts/check_tag_version.py``
(added 2026-06-10) compared a pushed git tag against
``pyproject.toml``'s ``project.version`` and was wired into
``release.yml``. It was not reverted -- it was dropped as collateral on
2026-06-22 by the reconcile merge that made ``main``'s tree identical to
the published v1.0.1 product tree, because the guard only ever lived on
main's engineering line. The ``release.yml`` step went with the file.

This guard is deliberately not a re-creation of that one. The old check
ran only when a tag was pushed and compared only two values, so the
declared version, the version the CLI prints and the CHANGELOG could
disagree for months on ``main`` without anything noticing. This runs on
every push and compares four sources, each read by its own mechanism:

1. ``pyproject.toml``'s ``project.version`` -- what gets built.
2. What ``bonfire --version`` prints -- what a user is told.
3. ``bonfire.__version__``'s literal fallback -- used when the package
   is imported without being installed, and therefore the value most
   able to rot unnoticed.
4. The newest release heading in ``CHANGELOG.md`` -- what the release
   notes claim.

What this guard does NOT establish
-----------------------------------
That the declared version is *available* -- i.e. not already published
to PyPI under different contents. These four sources agreeing at
``1.0.1`` is exactly the situation on ``main`` today while ``main``
carries commits the published ``1.0.1`` does not. Detecting that needs
release state this test has no access to, and choosing the next number
is a release-policy call, not a test's.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from typer.testing import CliRunner

from bonfire.cli.app import app

REPO_ROOT = Path(__file__).resolve().parents[2]

runner = CliRunner()

# ``## [1.0.1] — 2026-05-17``. The separator is an em dash in this file
# and the date is optional, so anchor only on the bracketed version.
_CHANGELOG_HEADING = re.compile(r"^##\s*\[(?P<version>[^\]]+)\]", re.MULTILINE)

# ``__version__ = "1.0.1"`` in the ImportError fallback branch.
_FALLBACK_LITERAL = re.compile(r'^\s*__version__\s*=\s*"(?P<version>[^"]+)"', re.MULTILINE)


def _declared_version() -> str:
    """``project.version`` from ``pyproject.toml``."""
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _printed_version() -> str:
    """The version ``bonfire --version`` shows a user.

    Parsed out of the real command's output rather than read from
    ``bonfire.__version__``, because the contract is about what the CLI
    tells someone, and the two are only equal as long as nobody changes
    the callback.
    """
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0, f"'bonfire --version' failed: {result.output!r}"
    printed = result.output.strip()
    assert printed.startswith("bonfire "), (
        f"'bonfire --version' output shape changed; got {printed!r}"
    )
    return printed.removeprefix("bonfire ").strip()


def _fallback_literal_version() -> str:
    """The hard-coded ``__version__`` used when the dist is not installed."""
    source = (REPO_ROOT / "src" / "bonfire" / "__init__.py").read_text()
    match = _FALLBACK_LITERAL.search(source)
    assert match is not None, (
        "no literal __version__ assignment found in src/bonfire/__init__.py; "
        "if the fallback was removed, delete this source from the guard"
    )
    return match.group("version")


def _latest_changelog_version() -> str:
    """The newest ``## [x.y.z]`` heading in ``CHANGELOG.md``.

    ``[Unreleased]`` is skipped: it is a staging area, not a claim about
    what the current build is.
    """
    text = (REPO_ROOT / "CHANGELOG.md").read_text()
    for match in _CHANGELOG_HEADING.finditer(text):
        version = match.group("version").strip()
        if version.lower() != "unreleased":
            return version
    raise AssertionError("CHANGELOG.md has no released version heading of the form '## [x.y.z]'")


class TestVersionTruth:
    """All four statements of the version agree, or CI goes red."""

    def test_cli_prints_the_declared_version(self) -> None:
        declared = _declared_version()
        printed = _printed_version()
        assert printed == declared, (
            f"'bonfire --version' prints {printed!r} but pyproject.toml declares "
            f"{declared!r}. The CLI reads installed distribution metadata, so this "
            "usually means the working tree was bumped without reinstalling "
            "(`pip install -e '.[dev]'`) -- or that a build would ship a version "
            "different from the one it announces."
        )

    def test_import_fallback_matches_the_declared_version(self) -> None:
        declared = _declared_version()
        fallback = _fallback_literal_version()
        assert fallback == declared, (
            f"src/bonfire/__init__.py falls back to __version__ = {fallback!r} but "
            f"pyproject.toml declares {declared!r}. The fallback is only reached when "
            "the package is imported without being installed, so it rots silently "
            "until someone in that situation is told the wrong version."
        )

    def test_changelog_documents_the_declared_version(self) -> None:
        declared = _declared_version()
        logged = _latest_changelog_version()
        assert logged == declared, (
            f"CHANGELOG.md's newest release heading is [{logged}] but pyproject.toml "
            f"declares {declared!r}. Either the version was bumped without release "
            "notes, or notes were written for a version that was never declared."
        )
