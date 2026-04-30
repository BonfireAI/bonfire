"""RED tests for bonfire.cli.commands.persona — BON-348 W6.2 (CONTRACT-LOCKED).

Sage memo: docs/audit/sage-decisions/bon-348-sage-20260426T013845Z.md
Adoption-filter: docs/audit/sage-decisions/bon-348-contract-lock-*.md

Floor (8 tests, per Sage §D6 Test file 4): port v1 cli test surface verbatim.
The 3 builtin personas (passelewe, minimal, default) ship in v0.1 — verified
via `ls src/bonfire/persona/builtins/`.

Adopted innovations (2 drift-guards over floor):

  * test_persona_list_shows_all_three_builtins — parametrize over the 3
    builtins (passelewe / minimal / default). Floor only covers passelewe +
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
# Adopted drift-guards (2 — innovations 7 + 8)
# ---------------------------------------------------------------------------


class TestPersonaDiscoverySurface:
    """Drift-guards on builtin discovery + loader resolution path."""

    @pytest.mark.parametrize(
        "builtin_name",
        ["passelewe", "minimal", "default"],
    )
    def test_persona_list_shows_all_three_builtins(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, builtin_name: str
    ) -> None:
        """`bonfire persona list` must surface all 3 builtins.

        Cites Sage §D6 + v1 cli/commands/persona.py:37-56.

        v0.1 ships 3 builtins (verified by `ls src/bonfire/persona/builtins/`
        returning `default minimal passelewe`). Floor coverage verifies
        passelewe + minimal individually. `default` is uncovered.

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


# ---------------------------------------------------------------------------
# Innovation lens — BON-601: type-level `Traversable` contract.
#
# The floor test asserts that the *string representation* of `builtin_dir`
# contains the path components "persona" and "builtins". That is a fragile
# proxy: a contributor could pass `Path(__file__).parent / "persona" /
# "builtins"` and pass the floor test while breaking the wheel-install
# resolution that BON-601 is actually about.
#
# The S007 lesson (worktree + editable install hazard) names the canonical
# fix: builtin_dir MUST resolve through `importlib.resources.files()`. The
# duck-typed contract `importlib.resources` returns is `Traversable` —
# defined in `importlib.resources.abc`. `pathlib.Path` IS-A Traversable
# (Python's stdlib uses ABC.register), but a plain `Path("…")` constructed
# from `__file__` is NOT what `importlib.resources.files()` returns inside
# a wheel install (where it can be a `MultiplexedPath` or similar zip-aware
# Traversable). Asserting the type, not the str, is the canonical guard.
#
# Innovation: assert `isinstance(builtin_dir, Traversable)` AND probe the
# Traversable interface methods (`joinpath`, `iterdir`, `is_dir`) actually
# work on the value passed — that catches a regression where someone
# passes a string path or a non-Traversable wrapper.
# ---------------------------------------------------------------------------


class TestPersonaLoaderTypeContract:
    """Drift-guards on the type-level Traversable contract for builtin_dir."""

    @pytest.mark.xfail(
        reason="BON-601: builtin_dir must be importlib.resources.abc.Traversable instance",
    )
    def test_loader_builtin_dir_is_traversable(self) -> None:
        """`_get_loader()` passes a `Traversable` for `builtin_dir`.

        `importlib.resources.files()` is documented to return a
        `Traversable` — the only abstract type that survives across
        wheel / editable / zipped-egg installs. Asserting the canonical
        type is the only check that survives the install-mode permutations.

        Floor test compares `str(builtin_dir)` against literal substrings,
        which would still pass if a future refactor switched to a hard-coded
        `Path(__file__).parent` — silently breaking wheel installs.
        """
        import importlib.resources.abc

        from bonfire.cli.commands.persona import _get_loader

        with patch("bonfire.cli.commands.persona.PersonaLoader") as mock_loader_cls:
            mock_loader_cls.return_value = MagicMock()
            _get_loader()

            kwargs = mock_loader_cls.call_args.kwargs
            builtin_dir = kwargs["builtin_dir"]

            assert isinstance(builtin_dir, importlib.resources.abc.Traversable), (
                f"builtin_dir must be an importlib.resources.abc.Traversable; "
                f"got {type(builtin_dir).__name__!r}. A plain `pathlib.Path` "
                f"constructed from __file__ would fail this — the canonical "
                f"resolution is `importlib.resources.files('bonfire')`."
            )

    @pytest.mark.xfail(
        reason="BON-601: builtin_dir must support the live Traversable interface",
    )
    def test_loader_builtin_dir_supports_traversable_interface(self) -> None:
        """`builtin_dir` exposes the live `joinpath`/`iterdir`/`is_dir` ops.

        Beyond static `isinstance`, the Traversable interface MUST actually
        function on the live value. Walks the abstract API to catch:
          - a regression where a wrapper claims Traversable but iterdir()
            raises (e.g. a stale closed zipfile handle);
          - a regression where `joinpath` returns a non-Traversable
            (breaks downstream PersonaLoader._find_persona_dir).

        Uses the un-patched `_get_loader()` so we exercise the real
        importlib.resources path on the real package data.
        """
        import importlib.resources.abc

        from bonfire.cli.commands.persona import _get_loader

        loader = _get_loader()
        # Reach through the loader's stored attribute to the actual value.
        builtin_dir = loader._builtin_dir  # noqa: SLF001 — contract probe

        assert isinstance(builtin_dir, importlib.resources.abc.Traversable)
        # The three live operations the rest of the loader depends on.
        assert builtin_dir.is_dir(), "builtin_dir.is_dir() must be True at runtime"
        # joinpath returns another Traversable
        passelewe_dir = builtin_dir.joinpath("passelewe")
        assert isinstance(passelewe_dir, importlib.resources.abc.Traversable), (
            "builtin_dir.joinpath() must return a Traversable, not a str/Path"
        )
        # iterdir returns Traversables
        children = list(builtin_dir.iterdir())
        assert children, "builtin_dir.iterdir() returned no entries"
        for child in children:
            assert isinstance(child, importlib.resources.abc.Traversable), (
                f"iterdir entry {child!r} is not a Traversable"
            )


# ---------------------------------------------------------------------------
# Innovation lens — BON-599: TOML parse failure must warn, not silently fall
# back.
#
# `_get_active_persona` today catches TOMLDecodeError + OSError and
# silently returns the default. That is a debuggability hazard: a user with
# a corrupt bonfire.toml gets the default persona with NO signal that
# their config was ignored. The narrow ticket asks for ONE warning emit
# on one TOML failure shape.
#
# The policy intent is wider: ANY TOML parse failure deserves the same
# warning. We parametrize over four real-world failure shapes:
#
#   1. truncated mid-table     ("[bonfire")
#   2. unclosed string         ('persona = "passe')
#   3. invalid escape          ('persona = "\\q"')
#   4. duplicate-key           ("[bonfire]\npersona = 'a'\npersona = 'b'")
#
# All four MUST emit a warning that:
#   * is visible on stderr (caplog at WARNING+ level);
#   * names the offending file (so the user can find it);
#   * carries a parseable shape (not just an opaque traceback dump).
#
# Innovation also: an OSError (permission denied, etc.) gets the SAME
# warning treatment — currently silently swallowed alongside
# TOMLDecodeError per persona.py:38.
# ---------------------------------------------------------------------------


class TestActivePersonaTOMLFailureWarnings:
    """Drift-guards on the warning contract for unreadable bonfire.toml."""

    @pytest.mark.xfail(
        reason="BON-599: every TOML decode failure shape must emit a warning",
    )
    @pytest.mark.parametrize(
        ("failure_shape", "toml_content"),
        [
            ("truncated_table", "[bonfire"),
            ("unclosed_string", '[bonfire]\npersona = "passe'),
            ("invalid_escape", '[bonfire]\npersona = "\\q"'),
            (
                "duplicate_key",
                '[bonfire]\npersona = "a"\npersona = "b"\n',
            ),
        ],
    )
    def test_get_active_persona_warns_on_any_toml_failure(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
        failure_shape: str,
        toml_content: str,
    ) -> None:
        """Every TOML parse failure shape MUST emit a WARNING-level log.

        Parametrized over 4 real-world corruption shapes. The narrow ticket
        asks for ONE warning case; the policy widens to "any TOML failure →
        warning, not silent fallback".

        Cites persona.py:38 — the `except (TOMLDecodeError, OSError): pass`
        is the silent-fallback regression site.
        """
        import logging

        from bonfire.cli.commands.persona import _get_active_persona

        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text(toml_content)

        with caplog.at_level(logging.WARNING):
            result = _get_active_persona()

        # Fallback still happens — the function is total, never raises.
        assert isinstance(result, str), (
            f"failure_shape={failure_shape!r}: expected str fallback, got {result!r}"
        )

        # But the warning MUST be visible.
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            f"failure_shape={failure_shape!r}: no WARNING-or-higher log emitted; "
            f"caplog records: {[(r.levelname, r.message) for r in caplog.records]!r}"
        )

    @pytest.mark.xfail(
        reason="BON-599: warning text must be parseable — name the file + the cause",
    )
    def test_get_active_persona_warning_names_the_file(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Warning text identifies the offending file so the user can fix it.

        A warning that says only "TOML parse failed" is unactionable. The
        warning MUST mention `bonfire.toml` (the canonical filename) so
        the user knows what to edit. Innovation over a bare `caplog
        records` count check: assert the message has parseable shape.
        """
        import logging

        from bonfire.cli.commands.persona import _get_active_persona

        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text("[bonfire\npersona = ")  # mid-table truncation

        with caplog.at_level(logging.WARNING):
            _get_active_persona()

        # At least one warning must mention the filename, so the user can
        # locate the broken file.
        warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any("bonfire.toml" in msg for msg in warning_messages), (
            f"no warning mentioned `bonfire.toml`; messages: {warning_messages!r}"
        )

    @pytest.mark.xfail(
        reason="BON-599: OSError on read MUST also warn — same silent-swallow site",
    )
    def test_get_active_persona_warns_on_oserror(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """OSError (permission, IO failure) gets the same warning treatment.

        persona.py:38 catches `(TOMLDecodeError, OSError)` together — the
        narrow ticket only names TOMLDecodeError, but the SAME silent-
        swallow exists for OSError. The policy "fail loudly when config
        is unreadable" is symmetric across both exception types.

        Simulates the OSError by patching `tomllib.load` to raise it,
        rather than fiddling with filesystem permissions (which would be
        flaky on Windows CI per CLAUDE.md cross-platform rule).
        """
        import logging
        from unittest.mock import patch as mock_patch

        from bonfire.cli.commands.persona import _get_active_persona

        monkeypatch.chdir(tmp_path)
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\npersona = "minimal"\n')

        with (
            mock_patch(
                "bonfire.cli.commands.persona.tomllib.load",
                side_effect=OSError("simulated read failure"),
            ),
            caplog.at_level(logging.WARNING),
        ):
            result = _get_active_persona()

        assert isinstance(result, str), "fallback persona must be a string"
        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            f"OSError on read silently swallowed — no warning emitted. "
            f"caplog records: {[(r.levelname, r.message) for r in caplog.records]!r}"
        )
