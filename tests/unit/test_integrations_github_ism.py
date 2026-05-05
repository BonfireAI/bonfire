# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests for the bundled ``github.ism.md`` reference adapter.

This is the canonical first ISM file shipped with bonfire. It lives at
``src/bonfire/integrations/builtins/github.ism.md`` and serves as the
reference example contributors copy when authoring new adapters.

Locks:

* The file exists at the canonical location.
* ``ISMLoader`` parses it via ``load("github")``.
* The parsed document declares ``category == ISMCategory.FORGE``.
* ``provides`` is a superset of the forge-baseline capabilities
  ``{pr.open, pr.merge, pr.review}``.
* The detection list contains the canonical ``gh`` command probe and the
  canonical ``GITHUB_TOKEN`` env-var probe.
* ``loader.validate("github")`` does not raise.

Spec: ``docs/specs/ism-v1.md`` §9 (worked example — forge).

These tests must FAIL until both the impl modules and the bundled
``github.ism.md`` ship. That is the correct RED state.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Locate the canonical bundled directory.
#
# parents[0] = tests/unit/
# parents[1] = tests/
# parents[2] = bonfire-public/  (repo root)
# ---------------------------------------------------------------------------

BUILTIN_DIR = Path(__file__).resolve().parents[2] / "src" / "bonfire" / "integrations" / "builtins"

GITHUB_ISM = BUILTIN_DIR / "github.ism.md"


# ---------------------------------------------------------------------------
# Fixture — a real ISMLoader pointed at the bundled dir.
# ---------------------------------------------------------------------------


@pytest.fixture()
def loader(tmp_path: Path):
    """Real ISMLoader with the bundled builtin_dir and an empty user_dir."""
    from bonfire.integrations.loader import ISMLoader

    user_dir = tmp_path / "empty-user"
    user_dir.mkdir()
    return ISMLoader(builtin_dir=BUILTIN_DIR, user_dir=user_dir)


# ===========================================================================
# Bundled-file contract
# ===========================================================================


class TestGitHubBundledISM:
    """The bundled ``github.ism.md`` is the canonical reference adapter."""

    def test_github_ism_file_exists_at_canonical_path(self) -> None:
        """``github.ism.md`` ships under ``src/bonfire/integrations/builtins/``."""
        assert GITHUB_ISM.is_file(), f"Expected bundled ISM at {GITHUB_ISM}; not found."

    def test_loader_parses_bundled_github(self, loader) -> None:
        """``loader.load('github')`` returns a non-None ISMDocument."""
        from bonfire.integrations.document import ISMDocument

        doc = loader.load("github")
        assert isinstance(doc, ISMDocument)

    def test_github_category_is_forge(self, loader) -> None:
        """The bundled adapter's category is ``forge``."""
        from bonfire.integrations.document import ISMCategory

        doc = loader.load("github")
        assert doc is not None
        assert doc.category == ISMCategory.FORGE

    def test_github_provides_superset_of_forge_baseline(self, loader) -> None:
        """``provides`` covers at least ``{pr.open, pr.merge, pr.review}``."""
        doc = loader.load("github")
        assert doc is not None
        baseline = {"pr.open", "pr.merge", "pr.review"}
        assert baseline.issubset(set(doc.provides)), (
            f"Expected {baseline} to be a subset of {doc.provides}"
        )

    def test_github_detection_has_gh_command_rule(self, loader) -> None:
        """Detection list contains a ``kind=command`` rule with ``command='gh'``."""
        from bonfire.integrations.document import CommandRule

        doc = loader.load("github")
        assert doc is not None
        command_rules = [r for r in doc.detection if isinstance(r, CommandRule)]
        assert any(r.command == "gh" for r in command_rules), (
            "Expected a CommandRule with command='gh' in github.ism.md detection."
        )

    def test_github_detection_has_github_token_env_var_rule(self, loader) -> None:
        """Detection list contains an ``env_var`` rule with ``name='GITHUB_TOKEN'``."""
        from bonfire.integrations.document import EnvVarRule

        doc = loader.load("github")
        assert doc is not None
        env_rules = [r for r in doc.detection if isinstance(r, EnvVarRule)]
        assert any(r.name == "GITHUB_TOKEN" for r in env_rules), (
            "Expected an EnvVarRule with name='GITHUB_TOKEN' in github.ism.md."
        )

    def test_loader_validate_github_does_not_raise(self, loader) -> None:
        """``loader.validate('github')`` succeeds — bundled file is canon."""
        loader.validate("github")  # must not raise
