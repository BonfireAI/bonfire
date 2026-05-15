"""RED contract for persona TOML write-site escaping.

Subject: ``bonfire.cli.commands.persona.persona_set`` writes the chosen
persona name into ``bonfire.toml`` at three sites using bare f-strings::

    f'persona = "{name}"'
    f'[bonfire]\\npersona = "{name}"'
    f'\\n[bonfire]\\npersona = "{name}"\\n'

A persona directory whose name contains ``"``, ``\\n``, or
``[malicious]`` corrupts the resulting TOML or sneaks an attacker-chosen
top-level table in.

This file pins down the contract that every write path through
``persona set`` produces a ``bonfire.toml`` whose ``[bonfire].persona``
key:

  1. Parses cleanly with ``tomllib.load`` (no
     ``tomllib.TOMLDecodeError``).
  2. Has the literal hostile name as the value of ``[bonfire].persona``.
  3. Does NOT silently inject extra top-level tables that the hostile
     name was attempting to smuggle in.

The Warrior will route all three write sites through a shared TOML
writer (likely ``tomli_w`` once added to deps, or a tiny
``persona/_toml_writer.py`` helper). The contract pins the
parseable-output side of the fix; the location of the writer is the
Warrior's call.

A ``PersonaLoader.available`` monkeypatch supplies the hostile names
without requiring real persona directories on disk — the ``persona
set`` command rejects unknown names, so the test must make the hostile
names appear "available" first.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

cli_runner = CliRunner()


# Hostile persona-name candidates. Each is a directory name a user could
# (in theory) create under ``~/.bonfire/personas/`` that produces broken
# TOML through f-string interpolation.
#
# The current eager-f-string writer corrupts the output for every entry
# below; a structured TOML writer escapes them all.
_HOSTILE_NAMES = [
    # Literal double-quote — closes the value and reopens it as garbage.
    'evil"name',
    # Backslash-quote — TOML parser treats this as an escape.
    'evil\\"name',
    # Newline followed by a fake table header — smuggles in a new table.
    "evil\n[malicious]\nkey = 1",
    # Newline + a key=value pair that would shadow another field.
    'evil\nmodel = "hijacked"',
    # CR + LF combo — same risk on platforms that round-trip CRLFs.
    "evil\r\n[crlf-injection]",
    # Bare ``[malicious]`` substring — relies on f-string's lack of quoting.
    "[malicious]",
]


def _patch_available_with(monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
    """Make ``PersonaLoader.available()`` return *names* so ``persona set`` accepts them.

    The CLI's ``persona set`` rejects unknown names before reaching the
    TOML writer, so the test has to fake the discovery surface for the
    hostile names. The loader itself is not exercised here — only the
    CLI's f-string write path.
    """

    def _fake_available(self):  # noqa: ANN001 — pytest monkeypatch contract
        return list(names)

    monkeypatch.setattr(
        "bonfire.persona.loader.PersonaLoader.available",
        _fake_available,
    )


def _assert_clean_toml_with_persona(toml_path: Path, expected_name: str) -> dict:
    """Assert *toml_path* parses cleanly and ``[bonfire].persona == expected_name``."""
    raw_bytes = toml_path.read_bytes()
    try:
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as exc:
        pytest.fail(
            f"bonfire.toml failed to parse after `persona set {expected_name!r}`. "
            f"This is the bare-f-string corruption the contract pins. "
            f"Raw bytes: {raw_bytes!r}; error: {exc}"
        )

    bonfire_section = data.get("bonfire")
    assert isinstance(bonfire_section, dict), (
        f"`[bonfire]` table missing or non-table after write. "
        f"Parsed data: {data!r}; raw bytes: {raw_bytes!r}"
    )

    actual = bonfire_section.get("persona")
    assert actual == expected_name, (
        f"`[bonfire].persona` should equal the literal name {expected_name!r}, "
        f"got {actual!r}. Raw bytes: {raw_bytes!r}"
    )
    return data


class TestHostileNameNewToml:
    """Write site #1 — ``bonfire.toml`` does not exist before ``persona set``."""

    @pytest.mark.parametrize("hostile_name", _HOSTILE_NAMES)
    def test_set_writes_parseable_toml_when_file_missing(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        hostile_name: str,
    ) -> None:
        """Hostile name + no prior bonfire.toml → parseable output with literal value."""
        monkeypatch.chdir(tmp_path)
        _patch_available_with(monkeypatch, [hostile_name])

        result = cli_runner.invoke(app, ["persona", "set", hostile_name])
        assert result.exit_code == 0, (
            f"persona set exit_code {result.exit_code}; output: {result.output!r}"
        )

        toml_path = tmp_path / "bonfire.toml"
        assert toml_path.exists(), "persona set must have created bonfire.toml"
        _assert_clean_toml_with_persona(toml_path, hostile_name)


class TestHostileNameExistingBonfireTableNoPersona:
    """Write site #2 — ``[bonfire]`` exists with no ``persona`` key yet."""

    @pytest.mark.parametrize("hostile_name", _HOSTILE_NAMES)
    def test_set_appends_persona_into_existing_bonfire_table(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        hostile_name: str,
    ) -> None:
        """Hostile name added to existing ``[bonfire]`` table → parseable + isolated."""
        monkeypatch.chdir(tmp_path)
        _patch_available_with(monkeypatch, [hostile_name])

        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\nmodel = "claude-opus-4"\n')

        result = cli_runner.invoke(app, ["persona", "set", hostile_name])
        assert result.exit_code == 0, (
            f"persona set exit_code {result.exit_code}; output: {result.output!r}"
        )

        data = _assert_clean_toml_with_persona(toml_path, hostile_name)
        # The pre-existing model key MUST be preserved unmodified.
        assert data["bonfire"].get("model") == "claude-opus-4", (
            f"existing `[bonfire].model` was clobbered by hostile-name write. Parsed: {data!r}"
        )
        # A hostile name carrying ``[malicious]`` or shadow keys MUST NOT
        # smuggle in new top-level tables.
        assert set(data.keys()) == {"bonfire"}, (
            f"Hostile name {hostile_name!r} smuggled extra top-level table(s) "
            f"into bonfire.toml. Parsed: {data!r}"
        )


class TestHostileNameExistingBonfirePersonaKey:
    """Write site #3 — ``[bonfire].persona`` already exists and is being rewritten."""

    @pytest.mark.parametrize("hostile_name", _HOSTILE_NAMES)
    def test_set_rewrites_existing_persona_key_cleanly(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        hostile_name: str,
    ) -> None:
        """Hostile name overwriting existing persona key → parseable + literal value."""
        monkeypatch.chdir(tmp_path)
        _patch_available_with(monkeypatch, [hostile_name])

        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\npersona = "falcor"\nmodel = "claude-opus-4"\n')

        result = cli_runner.invoke(app, ["persona", "set", hostile_name])
        assert result.exit_code == 0, (
            f"persona set exit_code {result.exit_code}; output: {result.output!r}"
        )

        data = _assert_clean_toml_with_persona(toml_path, hostile_name)
        assert data["bonfire"].get("model") == "claude-opus-4", (
            f"existing `[bonfire].model` was clobbered by hostile-name rewrite. Parsed: {data!r}"
        )
        assert set(data.keys()) == {"bonfire"}, (
            f"Hostile name {hostile_name!r} smuggled extra top-level table(s) "
            f"into bonfire.toml on rewrite. Parsed: {data!r}"
        )
