# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract tests — BON-1043 explicit ``trust_project_settings`` TOML key.

The W5.E gate at ``bonfire.dispatch.sdk_backend._resolve_setting_sources``
landed file-presence trust: any cwd containing a ``bonfire.toml`` was
automatically opted-in to project-settings ingestion. Probe N+3 Scout 1
HIGH 4 flagged this as a security gap — a malicious clone whose
``bonfire.toml`` ships an empty ``[bonfire]`` table would silently lift the
attacker-controlled ``CLAUDE.md`` and ``.claude/settings.json`` into the
dispatched agent's system prompt.

BON-1043 closes the gap by requiring an EXPLICIT TOML opt-in key:

    [bonfire]
    trust_project_settings = true

File presence alone is NOT enough. The env override
``BONFIRE_TRUST_PROJECT_SETTINGS=1`` remains as the operator escape hatch.

Truth table the Warrior must satisfy:

| cwd                                                  | trust_project_settings? | env var | result          |
|------------------------------------------------------|-------------------------|---------|-----------------|
| ``""`` / ``None`` (dogfood)                          | n/a                     | n/a     | ``["project"]`` |
| ``<dir with bonfire.toml, key=true>``                | true                    | unset   | ``["project"]`` |
| ``<dir with bonfire.toml, key=false>``               | false                   | unset   | ``[]``          |
| ``<dir with bonfire.toml, key missing>``             | (absent)                | unset   | ``[]``          |
| ``<dir with bonfire.toml, [bonfire] table missing>`` | n/a                     | unset   | ``[]``          |
| ``<dir with bonfire.toml, malformed TOML>``          | n/a                     | unset   | ``[]``          |
| ``<foreign dir, no bonfire.toml>``                   | n/a                     | unset   | ``[]``          |
| ``<foreign dir>``                                    | n/a                     | ``"1"`` | ``["project"]`` |
| ``<dir with key=false but env="1">``                 | false                   | ``"1"`` | ``["project"]`` |

The env-override stays STRICT-``"1"`` (no normalization). The TOML key
must be a literal boolean ``true``; ``"true"``/``"1"``/``1`` strings or
integers are NOT honored (parser-strict to keep the contract unambiguous).
"""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _scrub_trust_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``BONFIRE_TRUST_PROJECT_SETTINGS`` is unset at test start."""
    monkeypatch.delenv("BONFIRE_TRUST_PROJECT_SETTINGS", raising=False)


# ---------------------------------------------------------------------------
# 1. bonfire.toml WITHOUT the key → BLOCKED
# ---------------------------------------------------------------------------


class TestBonfireTomlWithoutKeyBlocks:
    """Mere file presence is NOT enough; the explicit opt-in key is required."""

    def test_empty_bonfire_toml_blocks(self, tmp_path: Path) -> None:
        """``bonfire.toml`` exists but is empty → ``[]``.

        Old (BON-1013) behavior trusted file presence alone. The BON-1043
        contract tightens this: empty file does NOT signal opt-in.
        """
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("")
        (tmp_path / "CLAUDE.md").write_text("# Foreign instructions\n")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], (
            "Empty ``bonfire.toml`` MUST NOT trust; explicit "
            f"``trust_project_settings = true`` is required. Got {result!r}."
        )

    def test_bonfire_table_without_key_blocks(self, tmp_path: Path) -> None:
        """``[bonfire]`` table present but key missing → ``[]``.

        This is the canonical attack: hostile clone ships a ``bonfire.toml``
        with an empty ``[bonfire]`` table, hoping file-presence trust kicks in.
        """
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("[bonfire]\n")
        (tmp_path / "CLAUDE.md").write_text("# Foreign instructions\n")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], (
            "``[bonfire]`` table without ``trust_project_settings = true`` "
            f"MUST resolve to ``[]``. Got {result!r}."
        )

    def test_bonfire_toml_with_other_keys_but_no_trust_blocks(
        self,
        tmp_path: Path,
    ) -> None:
        """Real-world ``bonfire.toml`` with unrelated keys → ``[]``.

        Common case: the user has scoped Bonfire model/budget settings but
        has not opted into trusting their project-level CLAUDE.md ingestion.
        """
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        toml = '[bonfire]\nmodel = "claude-sonnet-4-6"\nmax_turns = 5\nmax_budget_usd = 2.0\n'
        (tmp_path / "bonfire.toml").write_text(toml)
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], (
            "Unrelated ``[bonfire]`` keys MUST NOT imply trust; "
            f"only the explicit ``trust_project_settings = true`` opts in. Got {result!r}."
        )

    def test_no_bonfire_table_blocks(self, tmp_path: Path) -> None:
        """``bonfire.toml`` with no ``[bonfire]`` table at all → ``[]``."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text('[memory]\nsession_dir = ".bonfire/sessions"\n')
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], f"Missing ``[bonfire]`` table MUST default-deny. Got {result!r}."


# ---------------------------------------------------------------------------
# 2. bonfire.toml WITH the explicit key → LOADED
# ---------------------------------------------------------------------------


class TestExplicitKeyLoads:
    """``[bonfire].trust_project_settings = true`` is the only valid TOML opt-in."""

    def test_explicit_true_loads(self, tmp_path: Path) -> None:
        """``trust_project_settings = true`` → ``["project"]``."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("[bonfire]\ntrust_project_settings = true\n")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == ["project"], (
            "Explicit ``[bonfire].trust_project_settings = true`` MUST "
            f"return ``['project']``. Got {result!r}."
        )

    def test_explicit_true_with_other_keys_loads(self, tmp_path: Path) -> None:
        """Explicit opt-in alongside other settings → ``["project"]``."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        toml = (
            '[bonfire]\nmodel = "claude-opus-4-7"\ntrust_project_settings = true\nmax_turns = 10\n'
        )
        (tmp_path / "bonfire.toml").write_text(toml)
        result = _resolve_setting_sources(str(tmp_path))
        assert result == ["project"], (
            f"Explicit opt-in MUST be honored alongside other keys. Got {result!r}."
        )


# ---------------------------------------------------------------------------
# 3. bonfire.toml WITH key = false → BLOCKED
# ---------------------------------------------------------------------------


class TestExplicitFalseBlocks:
    """Explicit ``false`` MUST block (no fallback to file-presence trust)."""

    def test_explicit_false_blocks(self, tmp_path: Path) -> None:
        """``trust_project_settings = false`` → ``[]``."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("[bonfire]\ntrust_project_settings = false\n")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], (
            f"Explicit ``trust_project_settings = false`` MUST resolve to ``[]``. Got {result!r}."
        )


# ---------------------------------------------------------------------------
# 4. Type-strictness: only literal boolean ``true`` opts in
# ---------------------------------------------------------------------------


class TestTypeStrictness:
    """The opt-in must be a literal TOML boolean — strings/ints do NOT trust.

    Keeps the contract unambiguous. A future contributor templating values
    from CI ("trust = ${BUILD_TRUST}") would otherwise risk silent opt-in.
    """

    @pytest.mark.parametrize(
        "value_literal",
        [
            '"true"',
            '"yes"',
            '"1"',
            "1",  # int, not bool
            '"True"',
        ],
    )
    def test_non_boolean_true_does_not_trust(
        self,
        tmp_path: Path,
        value_literal: str,
    ) -> None:
        """Non-bool truthy values do NOT trust."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text(
            f"[bonfire]\ntrust_project_settings = {value_literal}\n"
        )
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], (
            f"Non-bool ``trust_project_settings = {value_literal}`` MUST NOT "
            f"trust (parser-strict). Got {result!r}."
        )


# ---------------------------------------------------------------------------
# 5. Malformed TOML — fail-safe (deny)
# ---------------------------------------------------------------------------


class TestMalformedTomlDenies:
    """Unparseable ``bonfire.toml`` MUST NOT trust (fail-safe).

    An attacker producing deliberately malformed TOML must not cause an
    exception that takes down the dispatcher OR silently fall through to
    file-presence trust. The resolver returns ``[]`` and lets the caller
    surface a real config error elsewhere if needed.
    """

    def test_malformed_toml_blocks(self, tmp_path: Path) -> None:
        """Garbage TOML → ``[]`` (deny, do not raise)."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("this is not = = valid toml [[[\n")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], f"Malformed TOML MUST default-deny without raising. Got {result!r}."


# ---------------------------------------------------------------------------
# 6. Env-override escape hatch preserved
# ---------------------------------------------------------------------------


class TestEnvOverridePreserved:
    """``BONFIRE_TRUST_PROJECT_SETTINGS=1`` still trusts regardless of TOML state."""

    def test_env_override_loads_when_key_missing(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Env=``"1"`` + ``bonfire.toml`` without key → ``["project"]``."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("[bonfire]\n")
        monkeypatch.setenv("BONFIRE_TRUST_PROJECT_SETTINGS", "1")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == ["project"], (
            f"Env override MUST trust even when TOML key is missing. Got {result!r}."
        )

    def test_env_override_loads_when_key_false(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Env=``"1"`` beats ``trust_project_settings = false``.

        The env override is the operator's explicit acknowledgement; it
        out-prioritizes the TOML's stated default. This is symmetric with
        the existing BON-1013 contract where env trumps file-absence.
        """
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("[bonfire]\ntrust_project_settings = false\n")
        monkeypatch.setenv("BONFIRE_TRUST_PROJECT_SETTINGS", "1")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == ["project"], (
            f"Env override MUST trust even when TOML key explicitly disables. Got {result!r}."
        )

    def test_env_override_loads_without_bonfire_toml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Env=``"1"`` works even without a ``bonfire.toml`` at all (preserves BON-1013)."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "CLAUDE.md").write_text("# Foreign\n")
        monkeypatch.setenv("BONFIRE_TRUST_PROJECT_SETTINGS", "1")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == ["project"], f"Env override MUST trust foreign repos. Got {result!r}."


# ---------------------------------------------------------------------------
# 7. Empty cwd path (dogfood) unaffected
# ---------------------------------------------------------------------------


class TestEmptyCwdUnaffected:
    """Empty cwd remains the dogfood path → ``["project"]`` (BON-1013 preserved)."""

    def test_empty_string_cwd(self) -> None:
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        assert _resolve_setting_sources("") == ["project"]

    def test_none_cwd(self) -> None:
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        assert _resolve_setting_sources(None) == ["project"]
