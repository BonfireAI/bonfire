# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: the tool can load the config the tool wrote.

The onboarding path a stranger follows after ``pip install`` is
``bonfire init .`` then ``bonfire scan`` then ``bonfire persona set
<name>``. Every step writes to the same ``bonfire.toml``, and the
runtime has to be able to read it back afterwards.

Why this file exists rather than another emitter test
-----------------------------------------------------
``tests/unit/test_onboard_config_generator.py`` already checks that each
section builder emits *parseable TOML*, by parsing the builder's own
fragment in isolation. That is a strictly weaker contract than "the
runtime can load the whole file", and the gap between the two is where
the defect lived: ``_build_persona`` emitted a ``[bonfire.persona]``
sub-table while ``PipelineConfig.persona`` is a ``str``, so every
generated config parsed as TOML and then failed
:class:`~bonfire.models.config.BonfireSettings` validation.

So these tests deliberately do **not** hand-write the expected TOML.
They call the real generator, hand its bytes to the real writer, and
load the result with the real settings class. A fixture of what we
believe the generator emits cannot catch a generator that emits
something else.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app
from bonfire.models.config import BonfireSettings
from bonfire.onboard.config_generator import generate_config, write_config

if TYPE_CHECKING:
    from pathlib import Path

runner = CliRunner()

# The exact key set ``bonfire.onboard.conversation`` writes into
# ``profile``. Sourced from the conversation module's own assignments, so
# this stays a description of the real onboarding answers rather than an
# invented shape.
CONVERSATION_PROFILE = {
    "companion_mode": "friend",
    "goal_visibility": "horizon",
    "energy_type": "bonfire",
    "attention_topology": "many_tabs",
    "uncertainty_orientation": "just_go",
}


def _write_scan_config(project: Path) -> Path:
    """Generate and write a ``bonfire.toml`` the way ``scan`` does."""
    generated = generate_config(
        scan_results=[],
        profile=CONVERSATION_PROFILE,
        project_name="demo",
    )
    return write_config(generated.config_toml, project)


class TestGeneratedConfigLoads:
    """What ``bonfire scan`` writes, ``BonfireSettings`` must load."""

    def test_generated_config_is_valid_toml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Floor: the generated file parses. This passed before the fix too."""
        monkeypatch.chdir(tmp_path)
        path = _write_scan_config(tmp_path)
        tomllib.loads(path.read_text())

    def test_generated_config_loads_through_the_real_settings_class(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The contract the fragment tests could not see.

        ``BonfireSettings()`` reads ``bonfire.toml`` relative to the
        process cwd, so this must run inside *tmp_path*.
        """
        monkeypatch.chdir(tmp_path)
        _write_scan_config(tmp_path)

        settings = BonfireSettings()

        assert isinstance(settings.bonfire.persona, str), (
            "bonfire.persona must stay the persona NAME. A generator that "
            "writes a table there makes every generated config unloadable."
        )

    def test_the_conversation_answers_survive_the_round_trip(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The onboarding answers are readable back, not merely written.

        Without this, moving the section anywhere the model does not
        declare would satisfy the test above while silently discarding
        everything the user said during onboarding.
        """
        monkeypatch.chdir(tmp_path)
        _write_scan_config(tmp_path)

        settings = BonfireSettings()

        assert settings.bonfire.profile == CONVERSATION_PROFILE, (
            f"the onboarding profile must load back intact; got {settings.bonfire.profile!r}"
        )


class TestDocumentedCommandOrderComposes:
    """``init`` -> ``scan`` -> ``persona set`` -> the runtime loads it."""

    def test_full_round_trip_leaves_a_loadable_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The headline contract of this file."""
        result_init = runner.invoke(app, ["init", str(tmp_path)])
        assert result_init.exit_code == 0, result_init.output

        monkeypatch.chdir(tmp_path)
        path = _write_scan_config(tmp_path)

        result_set = runner.invoke(app, ["persona", "set", "minimal"])
        assert result_set.exit_code == 0, (
            f"persona set failed after scan; output={result_set.output!r}"
        )

        # Parse first so a TOML break is reported as a TOML break rather
        # than as a pydantic error three frames deeper.
        tomllib.loads(path.read_text())
        settings = BonfireSettings()

        assert settings.bonfire.persona == "minimal", (
            f"persona set did not take effect; got {settings.bonfire.persona!r}"
        )
        assert settings.bonfire.profile == CONVERSATION_PROFILE, (
            f"persona set destroyed the onboarding answers; got {settings.bonfire.profile!r}"
        )

    def test_persona_list_reports_what_persona_set_wrote(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``persona list`` must agree with the file on disk."""
        monkeypatch.chdir(tmp_path)
        _write_scan_config(tmp_path)
        runner.invoke(app, ["persona", "set", "minimal"])

        result = runner.invoke(app, ["persona", "list"])

        assert result.exit_code == 0, result.output
        assert "▸ minimal (active)" in result.output, (
            f"persona list disagrees with bonfire.toml; output={result.output!r}"
        )


class TestLegacyConfigsStillLoad:
    """Configs written by ``bonfire scan`` on 1.0.1 must not stay dead.

    The broken emitter shipped to PyPI, so these files exist outside
    this repo. Fixing only the generator would leave everyone who
    already onboarded holding a config the runtime refuses.
    """

    def test_legacy_persona_table_is_relocated_on_load(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        (tmp_path / "bonfire.toml").write_text(
            "[bonfire]\n"
            'name = "demo"\n'
            "\n"
            "[bonfire.persona]\n"
            'companion_mode = "friend"\n'
            'energy_type = "bonfire"\n'
        )

        settings = BonfireSettings()

        assert settings.bonfire.profile == {
            "companion_mode": "friend",
            "energy_type": "bonfire",
        }, f"legacy onboarding answers were dropped; got {settings.bonfire.profile!r}"
        assert settings.bonfire.persona == "falcor", (
            "with no persona name in the file the default applies; got "
            f"{settings.bonfire.persona!r}"
        )

    def test_an_explicit_profile_beats_the_legacy_table(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Migrations must never overwrite a value the user actually set."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "bonfire.toml").write_text(
            "[bonfire]\n"
            "\n"
            "[bonfire.persona]\n"
            'companion_mode = "stale"\n'
            "\n"
            "[bonfire.profile]\n"
            'companion_mode = "current"\n'
        )

        settings = BonfireSettings()

        assert settings.bonfire.profile == {"companion_mode": "current"}, (
            f"the legacy table clobbered an explicit profile; got {settings.bonfire.profile!r}"
        )

    def test_a_persona_name_string_is_left_alone(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The migration must only fire on the table shape, never on a name."""
        monkeypatch.chdir(tmp_path)
        (tmp_path / "bonfire.toml").write_text('[bonfire]\npersona = "minimal"\n')

        settings = BonfireSettings()

        assert settings.bonfire.persona == "minimal"
        assert settings.bonfire.profile == {}


class TestUnwritableConfigFailsLoudly:
    """A command that cannot do its job exits non-zero and says so.

    The pre-fix ``persona set`` rewrote ``bonfire.toml`` with a regex and
    never checked the result, so a config it could not handle became a
    corrupt file reported as ``Persona set to: <name>`` with exit 0.
    Silent corruption is the more serious half of that defect: the exit
    code is what a script or CI step reads.
    """

    def test_persona_set_refuses_rather_than_writing_broken_toml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A legacy config with the old sub-table must not be corrupted.

        Configs in this shape are already on disk for anyone who ran
        ``bonfire scan`` on 1.0.1, so this path is reachable by real
        users and not merely hypothetical.
        """
        monkeypatch.chdir(tmp_path)
        legacy = tmp_path / "bonfire.toml"
        original = (
            "[bonfire]\n"
            "# Project identity\n"
            'name = "demo"\n'
            "\n"
            "[bonfire.persona]\n"
            "# Derived from conversation\n"
            'companion_mode = "friend"\n'
        )
        legacy.write_text(original)

        result = runner.invoke(app, ["persona", "set", "minimal"])

        assert result.exit_code != 0, (
            "persona set reported success on a config it could not rewrite; "
            f"output={result.output!r}"
        )
        assert legacy.read_text() == original, (
            "persona set must leave the file untouched when it refuses"
        )
        # The refusal has to be actionable, not just non-zero.
        assert "bonfire.persona" in result.output, (
            f"the refusal must name what blocked it; output={result.output!r}"
        )

    def test_persona_list_does_not_invent_an_active_persona(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unreadable config must not be reported as a known state.

        ``_get_active_persona`` used to swallow the decode error and
        return the default, so ``persona list`` printed
        ``falcor (active)`` while also printing that it could not read
        the file — two contradictory claims, exit 0.
        """
        monkeypatch.chdir(tmp_path)
        (tmp_path / "bonfire.toml").write_text(
            '[bonfire]\npersona = "x"\n[bonfire.persona]\na = "b"\n'
        )

        result = runner.invoke(app, ["persona", "list"])

        assert "(active)" not in result.output, (
            "persona list marked a persona active from an unreadable config; "
            f"output={result.output!r}"
        )
        assert result.exit_code != 0, (
            f"persona list exited 0 on an unreadable config; output={result.output!r}"
        )
