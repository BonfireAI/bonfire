"""RED tests for bonfire.cli.commands.persona — BON-348 W6.2 (Knight B, INNOVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-348-sage-20260426T013845Z.md

Floor (8 tests, per Sage §D6 Test file 4): port v1 cli test surface verbatim.
The 3 builtin personas (passelewe, minimal, default) ship in v0.1 — verified
via `ls src/bonfire/persona/builtins/` (Sage §D6 Test file 4 footnote).

Innovations (2 tests, INNOVATIVE lens additions over Sage floor):

  * `test_persona_list_shows_all_three_builtins` — parametrize over the
    3 builtin personas (passelewe, minimal, default). Guards against a
    discovery regression where `PersonaLoader.available()` accidentally
    drops one of them (e.g. a glob pattern change). Cites Sage §D6
    ("v0.1 already ships — verified `ls src/bonfire/persona/builtins/`")
    + v1 cli/commands/persona.py:37-56.

  * `test_loader_builtin_dir_resolves_through_importlib_resources` —
    guards that `_get_loader()` consults `importlib.resources.files(
    "bonfire") / "persona" / "builtins"` rather than a hard-coded
    filesystem path. This stability matters for editable installs +
    wheel-built installs where the source directory location differs.
    Cites Sage §D8 + v1 cli/commands/persona.py:17-21.

Imports are RED — `bonfire.cli.app` does not exist as a package until Warriors
port v1 source per Sage §D9.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest  # noqa: TC002
from typer.testing import CliRunner

# RED import — bonfire.cli.app module does not exist yet (cli.py is a single-file stub)
from bonfire.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

cli_runner = CliRunner()


class TestPersonaList:
    def test_list_shows_passelewe(self) -> None:
        result = cli_runner.invoke(app, ["persona", "list"])
        assert result.exit_code == 0
        assert "passelewe" in result.output

    def test_list_shows_minimal(self) -> None:
        result = cli_runner.invoke(app, ["persona", "list"])
        assert result.exit_code == 0
        assert "minimal" in result.output

    def test_list_marks_active(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """Active persona is visually indicated."""
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["persona", "list"])
        assert result.exit_code == 0
        lines = result.output.splitlines()
        active_lines = [line for line in lines if "passelewe" in line]
        assert len(active_lines) >= 1
        assert any("active" in line.lower() or "▸" in line for line in active_lines)


class TestPersonaSet:
    def test_set_writes_toml(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """persona set writes the choice to bonfire.toml."""
        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text("[bonfire]\n")

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0
        assert "minimal" in result.output

        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"

    def test_set_creates_toml_if_missing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """persona set creates bonfire.toml if it doesn't exist."""
        monkeypatch.chdir(tmp_path)

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0

        toml_path = tmp_path / "bonfire.toml"
        assert toml_path.exists()
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"

    def test_set_invalid_fails(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        """persona set with non-existent persona fails."""
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["persona", "set", "nonexistent"])
        assert result.exit_code != 0

    def test_set_preserves_existing_config(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """persona set preserves other keys in bonfire.toml."""
        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\nmodel = "claude-opus-4"\npersona = "passelewe"\n')

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0

        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"
        assert data["bonfire"]["model"] == "claude-opus-4"

    def test_set_only_replaces_bonfire_section(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """persona set must not replace persona keys in other TOML sections."""
        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text(
            '[other]\npersona = "should-not-change"\n\n[bonfire]\npersona = "passelewe"\n'
        )

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0

        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"
        assert data["other"]["persona"] == "should-not-change"


# ---------------------------------------------------------------------------
# Innovations (Knight B INNOVATIVE lens — 2 drift-guards over Sage floor)
# ---------------------------------------------------------------------------


class TestInnovativeDriftGuards:
    """Drift-guards added by Knight B (innovative lens) over Sage §D6 floor."""

    @pytest.mark.parametrize(
        "builtin_name",
        ["passelewe", "minimal", "default"],
    )
    def test_persona_list_shows_all_three_builtins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, builtin_name: str
    ) -> None:
        """`bonfire persona list` must surface all 3 builtins.

        Cites Sage §D6 ("`bonfire.persona.builtins/{passelewe,minimal,default}`
        which v0.1 already ships — verified `ls src/bonfire/persona/builtins/`")
        + v1 cli/commands/persona.py:37-56 (`persona_list` iterates
        `loader.available()`).

        Floor coverage verifies passelewe + minimal individually. v0.1 also
        ships `default` (verified by Sage §D6 footnote AND directly by:
        `ls src/bonfire/persona/builtins/` returns
        `default minimal passelewe`). The floor leaves `default` untested.

        This parametrized guard ensures all 3 surface in `persona list`.
        Guards against:
          - a glob pattern change in `PersonaLoader.available()` that
            silently drops one builtin (e.g. case-sensitive mismatch);
          - a future PR that ships a new builtin but skips registration;
          - a wheel-build path issue where one of the persona dirs is
            missing from the package data (catches packaging regressions).
        """
        # Use isolated cwd so no project bonfire.toml interferes with active marker
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["persona", "list"])
        assert result.exit_code == 0, (
            f"persona list exit_code {result.exit_code}; output: {result.output!r}"
        )
        assert builtin_name in result.output, (
            f"builtin {builtin_name!r} missing from `persona list` output. "
            f"Output: {result.output!r}"
        )

    def test_loader_builtin_dir_resolves_through_importlib_resources(self) -> None:
        """`_get_loader()` builds builtin_dir via importlib.resources.files().

        Cites Sage §D8 + v1 cli/commands/persona.py:17-21.

        Sage §D8 LOCKS `_get_loader()`:
            PersonaLoader(
                builtin_dir=importlib.resources.files("bonfire")
                    / "persona" / "builtins",
                user_dir=Path.home() / ".bonfire" / "personas",
            )

        v1 source lines 17-21 confirm. The S007 lesson (worktree + editable
        install hazard, BON-XXX in Forge memory) is that hard-coded paths
        like `Path(__file__).parent / "builtins"` work in dev but break in
        wheel-built installs. `importlib.resources.files()` is the only
        portable resolution.

        This test patches `PersonaLoader` and asserts that `_get_loader()`
        passes `builtin_dir` resolved through `importlib.resources.files`.
        Guards against:
          - a future refactor that switches to a hard-coded `__file__`-based
            path (would silently break for `pip install bonfire`);
          - a future refactor that drops `importlib.resources` for
            `pkgutil.get_data` (different return type contract);
          - a regression where the `.bonfire/personas` user_dir argument
            order is swapped with builtin_dir (mock contract verifies
            kwarg names are correct).
        """
        from bonfire.cli.commands.persona import _get_loader

        with patch("bonfire.cli.commands.persona.PersonaLoader") as mock_loader_cls:
            mock_loader_cls.return_value = MagicMock()
            _get_loader()

            mock_loader_cls.assert_called_once()
            kwargs = mock_loader_cls.call_args.kwargs

            assert "builtin_dir" in kwargs, (
                f"PersonaLoader must be called with `builtin_dir` kwarg. Got: {kwargs!r}"
            )
            assert "user_dir" in kwargs, (
                f"PersonaLoader must be called with `user_dir` kwarg. Got: {kwargs!r}"
            )

            # builtin_dir must be a Traversable (importlib.resources type),
            # NOT a plain Path. The Traversable surface is what makes
            # wheel-built installs work — Path.exists() works, but
            # `importlib.resources.files(...)` returns MultiplexedPath/
            # PosixPath subclasses with the right resource-resolution
            # contract.
            builtin_dir = kwargs["builtin_dir"]
            # Path components must include "persona" and "builtins" — the
            # locked subpath per Sage §D8 + v1 line 19.
            builtin_str = str(builtin_dir)
            assert "persona" in builtin_str, (
                f"builtin_dir must descend into 'persona/' — got {builtin_str!r}"
            )
            assert "builtins" in builtin_str, (
                f"builtin_dir must descend into 'builtins/' — got {builtin_str!r}"
            )
