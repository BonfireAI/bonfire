# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight RED tests — config_generator TOML escape + overwrite guard.

Two hazards in ``src/bonfire/onboard/config_generator.py``:

1. **TOML escape discipline.** Every section builder formats values as
   ``f'"{value}"'`` directly into the TOML output (11 sites: project
   name, persona keys/values, language, framework, test_framework, git
   remote, git branch, model, permissions, extensions, plus every item
   in the tools/MCP/vault inline arrays). If any of those values
   contains ``"`` or ``\\``, the resulting TOML is malformed — and
   with crafted input, an attacker could inject a fake key. Scanner-
   derived inputs are partly constrained (enum-like conversation
   profile), but git branch names are unconstrained ASCII and
   ``TechScanner`` emits category/technology strings from dependency
   parsing where escape characters are plausible.

2. **Overwrite-clobber.** ``write_config`` writes ``bonfire.toml`` to
   the project root with no existence check. A returning operator who
   edited their config and re-runs ``bonfire scan`` to refresh detected
   tools loses their hand-edits silently. ``bonfire init`` is correctly
   defensive (``if not toml_path.exists()``); the asymmetry is internal.

This Knight pins:

- A ``_toml_escape`` helper exists, exported (or used internally) to
  escape ``\\`` and ``"`` for TOML basic-string values.
- ``generate_config`` round-trips values containing ``"`` and ``\\``
  through ``tomllib.loads`` without producing malformed TOML — verified
  for project_name, persona values, git branch, and inline-array
  members (tools / mcp / vault).
- ``write_config`` defaults to safe (``overwrite=False``) and raises
  ``FileExistsError`` if ``bonfire.toml`` already exists at the target
  path. Pass ``overwrite=True`` to opt back into the legacy
  clobber-behavior.
- The front-door flow (``flow.py`` caller) explicitly passes
  ``overwrite=True`` so current ``bonfire scan`` UX is preserved
  pending a separate CLI ``--force`` flag wire-up (out of scope here).

Out of scope (filed for follow-up PR):

- Wiring a ``--force`` CLI flag into ``bonfire scan`` so the
  front-door path honors ``overwrite=False`` by default. Requires
  changes to ``cli/commands/scan.py`` + ``onboard/server.py`` +
  threading the flag through ``onboard/flow.py``. Larger scope.
- In-place merge of hand-edited ``bonfire.toml`` with re-scanned values.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from bonfire.onboard.config_generator import (
    generate_config,
    write_config,
)
from bonfire.onboard.protocol import ScanUpdate


def _parse_toml(toml_str: str) -> dict:
    """Helper — parse a TOML string via the stdlib parser."""
    return tomllib.loads(toml_str)


# ---------------------------------------------------------------------------
# TOML escape — values containing structural characters round-trip cleanly
# ---------------------------------------------------------------------------


class TestTomlEscapeProjectName:
    """Project name in the [bonfire] header must escape ``"`` and ``\\``."""

    def test_project_name_with_double_quote_round_trips(self) -> None:
        result = generate_config(
            scan_results=[],
            profile={},
            project_name='weird"project',
        )
        parsed = _parse_toml(result.config_toml)
        assert parsed["bonfire"]["name"] == 'weird"project', (
            f"Project name with double-quote did not round-trip; got TOML:\n{result.config_toml}"
        )

    def test_project_name_with_backslash_round_trips(self) -> None:
        result = generate_config(
            scan_results=[],
            profile={},
            project_name="back\\slash",
        )
        parsed = _parse_toml(result.config_toml)
        assert parsed["bonfire"]["name"] == "back\\slash"


class TestTomlEscapePersonaValues:
    """Persona key/value pairs in [bonfire.persona] must escape ``"`` and ``\\``."""

    def test_persona_value_with_double_quote_round_trips(self) -> None:
        result = generate_config(
            scan_results=[],
            profile={"companion_mode": 'friend"with"quotes'},
        )
        parsed = _parse_toml(result.config_toml)
        assert parsed["bonfire"]["persona"]["companion_mode"] == 'friend"with"quotes'


class TestTomlEscapeGitBranch:
    """Git branch name (unconstrained ASCII) must escape ``"`` and ``\\``."""

    def test_git_branch_with_double_quote_round_trips(self) -> None:
        scan = ScanUpdate(
            panel="git_state",
            label="branch",
            value='weird"branch-name',
        )
        result = generate_config(scan_results=[scan], profile={}, project_name="proj")
        parsed = _parse_toml(result.config_toml)
        assert parsed["bonfire"]["git"]["branch"] == 'weird"branch-name'


class TestTomlEscapeInlineArrayItems:
    """Items in TOML inline arrays (tools, mcp, vault) must escape ``"`` and ``\\``."""

    def test_tools_list_item_with_double_quote_round_trips(self) -> None:
        # Tool names land in [bonfire.tools].detected as an inline array.
        scan = ScanUpdate(
            panel="cli_toolchain",
            label='tool"with"quotes',
            value="present",
        )
        result = generate_config(scan_results=[scan], profile={}, project_name="proj")
        parsed = _parse_toml(result.config_toml)
        assert 'tool"with"quotes' in parsed["bonfire"]["tools"]["detected"]

    def test_mcp_servers_list_item_with_backslash_round_trips(self) -> None:
        scan = ScanUpdate(
            panel="mcp_servers",
            label="server\\name",
            value="present",
        )
        result = generate_config(scan_results=[scan], profile={}, project_name="proj")
        parsed = _parse_toml(result.config_toml)
        assert "server\\name" in parsed["bonfire"]["mcp"]["servers"]


class TestTomlOutputAlwaysParses:
    """Even with no special characters, the generated TOML is parseable.

    Regression guard — escape introduction must not break the happy path.
    """

    def test_clean_inputs_produce_parseable_toml(self) -> None:
        result = generate_config(
            scan_results=[
                ScanUpdate(panel="git_state", label="remote", value="origin"),
                ScanUpdate(panel="git_state", label="branch", value="main"),
            ],
            profile={"companion_mode": "friend"},
            project_name="clean-name",
        )
        parsed = _parse_toml(result.config_toml)
        assert parsed["bonfire"]["name"] == "clean-name"
        assert parsed["bonfire"]["persona"]["companion_mode"] == "friend"
        assert parsed["bonfire"]["git"]["remote"] == "origin"
        assert parsed["bonfire"]["git"]["branch"] == "main"


# ---------------------------------------------------------------------------
# Overwrite guard — write_config refuses to clobber by default
# ---------------------------------------------------------------------------


class TestWriteConfigOverwriteGuard:
    """``write_config`` defaults to safe; raises on existing file."""

    def test_write_config_new_file_succeeds_with_default(self, tmp_path: Path) -> None:
        """Default (overwrite=False) writes successfully when no prior file exists."""
        written = write_config('[bonfire]\nname = "foo"\n', tmp_path)
        assert written == tmp_path / "bonfire.toml"
        assert written.read_text() == '[bonfire]\nname = "foo"\n'

    def test_write_config_default_refuses_to_overwrite_existing(self, tmp_path: Path) -> None:
        """If the target already exists, default write_config raises FileExistsError.

        Pre-fix bug: write_config silently clobbered. Returning operator's
        hand-edits were lost on every re-scan.
        """
        target = tmp_path / "bonfire.toml"
        target.write_text('# operator hand-edit\n[bonfire]\nname = "preserved"\n')

        with pytest.raises(FileExistsError):
            write_config('[bonfire]\nname = "clobbered"\n', tmp_path)

        # File must be untouched.
        assert "operator hand-edit" in target.read_text()
        assert "clobbered" not in target.read_text()

    def test_write_config_explicit_overwrite_true_clobbers(self, tmp_path: Path) -> None:
        """overwrite=True preserves the legacy clobber-behavior explicitly."""
        target = tmp_path / "bonfire.toml"
        target.write_text('[bonfire]\nname = "old"\n')

        written = write_config(
            '[bonfire]\nname = "new"\n',
            tmp_path,
            overwrite=True,
        )
        assert written == target
        assert "new" in target.read_text()
        assert "old" not in target.read_text()


class TestWriteConfigSignature:
    """The overwrite parameter is keyword-only — discipline guard."""

    def test_overwrite_must_be_keyword_only(self, tmp_path: Path) -> None:
        """Passing overwrite positionally must fail — it's a discipline boundary."""
        target = tmp_path / "bonfire.toml"
        target.write_text("existing\n")
        with pytest.raises(TypeError):
            # Positional overwrite=True should raise; only kwarg form is allowed.
            write_config("new\n", tmp_path, True)  # type: ignore[call-arg]
