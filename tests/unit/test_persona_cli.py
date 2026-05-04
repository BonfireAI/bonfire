"""RED tests for bonfire.cli.commands.persona — BON-348 W6.2 (CONTRACT-LOCKED).

Sage memo: docs/audit/sage-decisions/bon-348-sage-20260426T013845Z.md
Adoption-filter: docs/audit/sage-decisions/bon-348-contract-lock-*.md

Floor (8 tests, per Sage §D6 Test file 4): port v1 cli test surface verbatim.
The 3 builtin personas (falcor, minimal, default) ship in v0.1 — verified
via `ls src/bonfire/persona/builtins/`.

Adopted innovations (2 drift-guards over floor):

  * test_persona_list_shows_all_three_builtins — parametrize over the 3
    builtins (falcor / minimal / default). Floor only covers falcor +
    minimal individually; `default` was uncovered. Cites Sage §D6 +
    v1 cli/commands/persona.py:37-56.

  * test_loader_builtin_dir_resolves_through_importlib_resources — patches
    PersonaLoader and asserts `_get_loader()` passes builtin_dir resolved
    through `importlib.resources.files("bonfire") / "persona" / "builtins"`.
    Verifies the wheel-install / S007 worktree-editable-install lesson is
    encoded. v0.1 PersonaLoader.__init__ accepts (builtin_dir, user_dir)
    kwargs (verified). Cites Sage §D8 + v1 cli/commands/persona.py:17-21.

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
    def test_list_shows_falcor(self) -> None:
        result = cli_runner.invoke(app, ["persona", "list"])
        assert result.exit_code == 0
        assert "falcor" in result.output

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
        active_lines = [line for line in lines if "falcor" in line]
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
        toml_path.write_text('[bonfire]\nmodel = "claude-opus-4"\npersona = "falcor"\n')

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
            '[other]\npersona = "should-not-change"\n\n[bonfire]\npersona = "falcor"\n'
        )

        result = cli_runner.invoke(app, ["persona", "set", "minimal"])
        assert result.exit_code == 0

        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == "minimal"
        assert data["other"]["persona"] == "should-not-change"


# ---------------------------------------------------------------------------
# Adopted drift-guards (2 — innovations 7 + 8)
# ---------------------------------------------------------------------------


class TestPersonaDiscoverySurface:
    """Drift-guards on builtin discovery + loader resolution path."""

    @pytest.mark.parametrize(
        "builtin_name",
        ["falcor", "minimal", "default"],
    )
    def test_persona_list_shows_all_three_builtins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, builtin_name: str
    ) -> None:
        """`bonfire persona list` must surface all 3 builtins.

        Cites Sage §D6 + v1 cli/commands/persona.py:37-56.

        v0.1 ships 3 builtins (verified by `ls src/bonfire/persona/builtins/`
        returning `default minimal falcor`). Floor coverage verifies
        falcor + minimal individually. `default` is uncovered.

        Guards against:
          - a glob pattern change in `PersonaLoader.available()` that silently
            drops one builtin (e.g. case-sensitive mismatch);
          - a future PR that ships a new builtin but skips registration;
          - a wheel-build path issue where one of the persona dirs is missing
            from package data (catches packaging regressions).
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

        v0.1 PersonaLoader.__init__ signature: (builtin_dir: Path, user_dir: Path).

        The S007 lesson (worktree + editable install hazard) is that hard-coded
        paths like `Path(__file__).parent / "builtins"` work in dev but break
        in wheel-built installs. `importlib.resources.files()` is the only
        portable resolution.

        Patches `PersonaLoader` and asserts `_get_loader()` passes builtin_dir
        resolved through `importlib.resources.files`. Guards against:
          - a future refactor that switches to a hard-coded `__file__`-based
            path (would silently break for `pip install bonfire`);
          - a future refactor that drops `importlib.resources` for
            `pkgutil.get_data` (different return type contract);
          - a regression where the `.bonfire/personas` user_dir argument
            order is swapped with builtin_dir (mock contract verifies kwarg
            names are correct).
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

            # builtin_dir must be the result of importlib.resources.files(...)
            # path traversal — its str() representation will contain both
            # "persona" and "builtins" path components, locked per Sage §D8 +
            # v1 line 19.
            builtin_dir = kwargs["builtin_dir"]
            builtin_str = str(builtin_dir)
            assert "persona" in builtin_str, (
                f"builtin_dir must descend into 'persona/' — got {builtin_str!r}"
            )
            assert "builtins" in builtin_str, (
                f"builtin_dir must descend into 'builtins/' — got {builtin_str!r}"
            )

    def test_loader_builtin_dir_resolved_via_importlib_resources_files_call(self) -> None:
        """`_get_loader()` MUST invoke `importlib.resources.files('bonfire')`.

        Strengthens the substring-presence assertion in
        `test_loader_builtin_dir_resolves_through_importlib_resources`. The
        substring check `"persona" in str(builtin_dir)` would pass for a
        hardcoded `Path(__file__).parent.parent / "persona" / "builtins"`
        construction, but that would silently break `pip install bonfire-ai`
        wheel deployments where __file__ may be inside a zip.

        The unambiguous signal is at the CALL SITE: `importlib.resources.files`
        must actually be invoked with "bonfire" as the package argument. A
        hardcoded `__file__`-based construction would never call it.

        Note: at runtime `importlib.resources.files()` for regular (non-zip)
        packages on Python 3.12 returns a `PosixPath` subclass, so a
        type-level "not a Path" check would falsely fail; the call-site
        invocation is the only deterministic strengthening.
        """
        from bonfire.cli.commands.persona import _get_loader

        with (
            patch("bonfire.cli.commands.persona.importlib.resources.files") as mock_files,
            patch("bonfire.cli.commands.persona.PersonaLoader") as mock_loader_cls,
        ):
            mock_loader_cls.return_value = MagicMock()
            mock_files.return_value = MagicMock()  # supports `/` chaining
            _get_loader()

            mock_files.assert_called_once_with("bonfire")


class TestPersonaTomlFallbackWarning:
    """`_get_active_persona` must surface a warning when bonfire.toml fails to parse.

    Today the function silently catches `tomllib.TOMLDecodeError` and falls
    back to the default. A user with a corrupted bonfire.toml sees the
    active marker on the wrong persona with no signal that anything is
    wrong. The fix: emit a stderr warning before fallback.
    """

    def test_get_active_persona_emits_warning_on_toml_decode_error(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        """Malformed bonfire.toml must emit a stderr warning before default-fallback."""
        from bonfire.cli.commands.persona import _get_active_persona

        monkeypatch.chdir(tmp_path)
        # Write a malformed TOML file
        (tmp_path / "bonfire.toml").write_text("this is not = valid [toml")

        result = _get_active_persona()

        captured = capsys.readouterr()
        assert "Warning" in captured.err, (
            f"_get_active_persona must emit a stderr warning when TOML fails to parse; "
            f"got stderr={captured.err!r}"
        )
        assert "bonfire.toml" in captured.err, (
            f"warning must name the file; got stderr={captured.err!r}"
        )
        # Default fallback still applies
        assert result == "falcor"
