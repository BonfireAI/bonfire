# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests for ``bonfire.integrations.loader`` — ISM v1 two-tier discovery.

Locks the ``ISMLoader`` class:

* ``__init__(builtin_dir, user_dir)`` — two-tier directory discovery.
* :meth:`ISMLoader.load(name)` — total. Returns ``ISMDocument`` or
  ``None`` on missing/malformed/invalid; logs WARNING on failure.
* :meth:`ISMLoader.validate(name)` — strict. Raises
  :class:`ISMSchemaError` describing the first violation.
* :meth:`ISMLoader.available()` — deduplicated, sorted list of names.

User-dir wins on name collision. Files must end in ``.ism.md``.

Spec: ``docs/specs/ism-v1.md`` §7, §8.

These tests must FAIL with ``ModuleNotFoundError`` until the Warrior ships
``src/bonfire/integrations/loader.py``. That is the correct RED state.

Tests use ``tmp_path`` fixtures — no real ``.bonfire/integrations/`` is touched.
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003 — runtime constructor type

import pytest

# ---------------------------------------------------------------------------
# Helpers — synthesize ISM files on disk
# ---------------------------------------------------------------------------


def _frontmatter(name: str, *, display_name: str = "GitHub", category: str = "forge") -> str:
    """Build a schema-valid ISM frontmatter+body string for ``name``."""
    return (
        "---\n"
        "ism_version: 1\n"
        f"name: {name}\n"
        f"display_name: {display_name}\n"
        f"category: {category}\n"
        f"summary: Reference adapter for {name}.\n"
        "provides:\n"
        "  - pr.open\n"
        "detection:\n"
        "  - kind: command\n"
        "    command: gh\n"
        "---\n"
        f"# {display_name}\n\nBody for {name}.\n"
    )


def _write_ism(directory: Path, name: str, content: str) -> Path:
    """Write *content* to ``{directory}/{name}.ism.md`` and return the path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{name}.ism.md"
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def builtin_dir(tmp_path: Path) -> Path:
    d = tmp_path / "builtin"
    d.mkdir()
    return d


@pytest.fixture()
def user_dir(tmp_path: Path) -> Path:
    d = tmp_path / "user"
    d.mkdir()
    return d


@pytest.fixture()
def loader(builtin_dir: Path, user_dir: Path):
    from bonfire.integrations.loader import ISMLoader

    return ISMLoader(builtin_dir=builtin_dir, user_dir=user_dir)


# ===========================================================================
# load() — total, never raises
# ===========================================================================


class TestISMLoaderLoad:
    """``load(name)`` returns an ISMDocument or None — never raises."""

    def test_load_finds_builtin_by_name(self, loader, builtin_dir: Path) -> None:
        """A valid github ISM in builtin_dir is discoverable by name."""
        from bonfire.integrations.document import ISMDocument

        _write_ism(builtin_dir, "github", _frontmatter("github"))
        doc = loader.load("github")
        assert isinstance(doc, ISMDocument)
        assert doc.name == "github"

    def test_load_user_dir_overrides_builtin(
        self, loader, builtin_dir: Path, user_dir: Path
    ) -> None:
        """User-dir copy wins on name collision."""
        _write_ism(builtin_dir, "github", _frontmatter("github", display_name="GH-Builtin"))
        _write_ism(user_dir, "github", _frontmatter("github", display_name="GH-User"))
        doc = loader.load("github")
        assert doc is not None
        assert doc.display_name == "GH-User"

    def test_load_returns_none_when_name_missing(self, loader) -> None:
        """Unknown name returns None; total method, never raises."""
        assert loader.load("nonexistent") is None

    def test_load_returns_none_when_yaml_malformed(
        self,
        loader,
        builtin_dir: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Malformed YAML in frontmatter returns None and logs WARNING."""
        bad = (
            "---\n"
            "ism_version: 1\n"
            "name: github\n"
            "display_name: [unbalanced\n"  # invalid YAML
            "---\n"
            "# body\n"
        )
        _write_ism(builtin_dir, "github", bad)
        with caplog.at_level(logging.WARNING):
            result = loader.load("github")
        assert result is None
        assert any("github" in r.message for r in caplog.records)

    def test_load_returns_none_when_required_field_missing(self, loader, builtin_dir: Path) -> None:
        """A schema violation (missing ``provides``) returns None."""
        bad = (
            "---\n"
            "ism_version: 1\n"
            "name: github\n"
            "display_name: GitHub\n"
            "category: forge\n"
            "summary: Forge.\n"
            "detection:\n"
            "  - kind: command\n"
            "    command: gh\n"
            "---\n"
            "# body\n"
        )
        _write_ism(builtin_dir, "github", bad)
        assert loader.load("github") is None

    def test_load_returns_none_when_no_frontmatter(self, loader, builtin_dir: Path) -> None:
        """A markdown file without ``---`` delimiters returns None."""
        _write_ism(builtin_dir, "github", "# Just a markdown body, no frontmatter\n")
        assert loader.load("github") is None

    def test_load_does_not_raise_on_any_failure(self, loader, builtin_dir: Path) -> None:
        """``load()`` is total — every failure mode returns None silently."""
        # Each of these is a different failure mode; all must coexist as None.
        _write_ism(builtin_dir, "broken-yaml", "---\nname: [bad\n---\nbody\n")
        _write_ism(builtin_dir, "no-fm", "no frontmatter at all\n")
        for name in ("missing-name", "broken-yaml", "no-fm"):
            loader.load(name)  # must not raise


# ===========================================================================
# validate() — strict, raises ISMSchemaError
# ===========================================================================


class TestISMLoaderValidate:
    """``validate(name)`` raises ISMSchemaError on any failure."""

    def test_validate_raises_when_missing(self, loader) -> None:
        """Unknown name raises ISMSchemaError."""
        from bonfire.integrations.document import ISMSchemaError

        with pytest.raises(ISMSchemaError):
            loader.validate("nonexistent")

    def test_validate_raises_when_yaml_malformed(self, loader, builtin_dir: Path) -> None:
        """Malformed YAML raises ISMSchemaError."""
        from bonfire.integrations.document import ISMSchemaError

        _write_ism(
            builtin_dir,
            "github",
            "---\nism_version: 1\nname: [bad\n---\nbody\n",
        )
        with pytest.raises(ISMSchemaError):
            loader.validate("github")

    def test_validate_raises_when_schema_violation(self, loader, builtin_dir: Path) -> None:
        """Schema violation (empty provides) raises ISMSchemaError."""
        from bonfire.integrations.document import ISMSchemaError

        bad = (
            "---\n"
            "ism_version: 1\n"
            "name: github\n"
            "display_name: GitHub\n"
            "category: forge\n"
            "summary: Forge.\n"
            "provides: []\n"
            "detection:\n"
            "  - kind: command\n"
            "    command: gh\n"
            "---\n"
            "# body\n"
        )
        _write_ism(builtin_dir, "github", bad)
        with pytest.raises(ISMSchemaError):
            loader.validate("github")


# ===========================================================================
# available() — deduplicated, sorted union
# ===========================================================================


class TestISMLoaderAvailable:
    """``available()`` returns the deduplicated, sorted union of both dirs."""

    def test_available_returns_sorted_deduplicated_names(
        self, loader, builtin_dir: Path, user_dir: Path
    ) -> None:
        """Both dirs contribute, dedup, alphabetic order."""
        _write_ism(builtin_dir, "zeta", _frontmatter("zeta"))
        _write_ism(builtin_dir, "alpha", _frontmatter("alpha"))
        _write_ism(builtin_dir, "shared", _frontmatter("shared"))
        _write_ism(user_dir, "shared", _frontmatter("shared"))
        _write_ism(user_dir, "mu", _frontmatter("mu"))
        names = loader.available()
        assert names == ["alpha", "mu", "shared", "zeta"]


# ===========================================================================
# File extension discipline — only ``*.ism.md`` is visible
# ===========================================================================


class TestExtensionDiscipline:
    """Only files ending in ``.ism.md`` are seen by the loader."""

    def test_loader_only_sees_files_with_ism_md_extension(self, loader, builtin_dir: Path) -> None:
        """A plain ``.md`` file (no ``.ism.md``) is invisible to the loader."""
        # Bare-`.md` file with otherwise-valid ISM content.
        (builtin_dir / "github.md").write_text(_frontmatter("github"))
        assert loader.load("github") is None
        assert "github" not in loader.available()


# ===========================================================================
# Slug guard — reject path-traversal and other non-slug names
# ===========================================================================


class TestNameSlugGuard:
    """The loader rejects any ``name`` that is not a valid slug.

    Names matching ``^[a-z][a-z0-9_-]*$`` are accepted; anything else
    (path-traversal sequences, absolute paths, uppercase, etc.) returns
    ``None`` from :meth:`load` and raises
    :class:`ISMSchemaError` from :meth:`validate`.
    """

    def test_load_rejects_path_traversal_name(
        self, loader, tmp_path: Path, builtin_dir: Path, user_dir: Path
    ) -> None:
        """``../secret`` cannot escape configured directories."""
        # Place a target file OUTSIDE the loader's configured dirs.
        # Both user_dir and builtin_dir are children of tmp_path; a name
        # of "../secret" would resolve to ``tmp_path/secret.ism.md``.
        outside = tmp_path / "secret.ism.md"
        outside.write_text(_frontmatter("secret"))
        # Sanity: confirm the would-be traversal target really exists.
        assert outside.is_file()
        # Loader rejects the slug; never reads the outside file.
        assert loader.load("../secret") is None

    def test_load_rejects_absolute_path_name(self, loader) -> None:
        """An absolute path as a name is rejected as a non-slug."""
        assert loader.load("/etc/passwd") is None

    def test_load_rejects_uppercase_name(self, loader) -> None:
        """Names with uppercase letters are not valid slugs."""
        assert loader.load("GitHub") is None

    def test_validate_raises_on_invalid_slug_name(self, loader) -> None:
        """``validate`` raises :class:`ISMSchemaError` on a non-slug name."""
        from bonfire.integrations.document import ISMSchemaError

        with pytest.raises(ISMSchemaError):
            loader.validate("../secret")
