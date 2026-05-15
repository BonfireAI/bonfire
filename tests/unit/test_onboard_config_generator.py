# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract for ``bonfire.onboard.config_generator`` TOML escaping.

Subject: every TOML writer in
``src/bonfire/onboard/config_generator.py`` emits values via bare
f-strings of the form ``f'... = "{value}"'`` (and inline arrays via
``f'"{item}"'``). The values flow in from:

* the project directory name (``project_path.name``);
* git remote / branch labels;
* CLI-toolchain detection labels;
* MCP server keys (any ``.mcp.json`` planted in a project);
* vault-seed document labels;
* persona-profile values from the front-door conversation;
* claude-memory model / permissions / extensions strings.

None of these inputs are sanitised before splicing. A directory named
``foo"bar`` therefore produces invalid TOML, and an MCP server key
containing a newline plus a fake table header smuggles attacker-chosen
``[bonfire.*]`` tables into the generated config.

The canonical fix already exists in
``src/bonfire/persona/_toml_writer.escape_basic_string`` --- this file
pins the SAME contract for the seven writer functions in
``config_generator.py``:

* ``_format_toml_list`` (used by ``_build_tools``, ``_build_mcp``,
  ``_build_vault``);
* ``_build_header``;
* ``_build_project``;
* ``_build_git``;
* ``_build_claude_memory``;
* ``_build_vault``;
* ``_build_persona``.

The contract every writer must satisfy:

1. Emit a TOML fragment that ``tomllib.loads`` parses without raising
   ``tomllib.TOMLDecodeError``.
2. Round-trip: after parsing, the value retrieved from the parsed table
   is byte-identical to the hostile input.
3. Hostile strings carrying ``[bonfire.malicious]`` / extra keys MUST
   NOT inject new top-level tables or sibling keys; the parsed output is
   structurally identical to the benign-input case.

The Warrior will likely add a ``_escape_toml_value`` helper to
``config_generator.py`` (or import ``escape_basic_string`` from
``persona/_toml_writer``). This file does not pre-stub the helper ---
the location of the fix is the Warrior's call.
"""

from __future__ import annotations

import tomllib

import pytest

from bonfire.onboard.config_generator import (
    _build_claude_memory,
    _build_git,
    _build_header,
    _build_mcp,
    _build_persona,
    _build_project,
    _build_tools,
    _build_vault,
    _format_toml_list,
    generate_config,
)
from bonfire.onboard.protocol import ScanUpdate

# ---------------------------------------------------------------------------
# Hostile payloads
# ---------------------------------------------------------------------------
#
# Each payload is a string a real-world data source could deliver to a
# config_generator writer:
#
#   * ``"`` --- e.g. a directory named ``foo"bar`` on Linux/macOS;
#   * ``\`` --- e.g. a Windows-style detail or a regex-y label;
#   * ``\n`` --- the smuggling vector that injects fake tables;
#   * the literal table-header sequence --- the same vector as above but
#     with the malicious shape made explicit.

_HOSTILE_PAYLOADS = [
    pytest.param('foo"bar', id="double-quote"),
    pytest.param("foo\\bar", id="backslash"),
    pytest.param("foo\nbar", id="newline"),
    pytest.param('attacker\n[bonfire.malicious]\nfoo = "bar"', id="table-smuggle"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_or_fail(fragment: str, *, writer_name: str, payload: str) -> dict:
    """Parse *fragment* as TOML; fail with diagnostics on TOMLDecodeError."""
    try:
        return tomllib.loads(fragment)
    except tomllib.TOMLDecodeError as exc:
        pytest.fail(
            f"{writer_name} produced invalid TOML for payload {payload!r}. "
            f"Raw fragment:\n{fragment}\n\nError: {exc}"
        )


def _scan(panel: str, label: str, value: str) -> ScanUpdate:
    return ScanUpdate(panel=panel, label=label, value=value)


# ---------------------------------------------------------------------------
# 1. ``_format_toml_list`` --- inline arrays
# ---------------------------------------------------------------------------


class TestFormatTomlList:
    """``_format_toml_list`` emits ``[\"item\", ...]`` for tool/MCP/vault lists."""

    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    def test_inline_array_is_valid_toml(self, payload: str) -> None:
        """The emitted array must parse cleanly inside a synthetic key."""
        fragment = f"items = {_format_toml_list([payload])}"
        parsed = _parse_or_fail(fragment, writer_name="_format_toml_list", payload=payload)
        assert parsed == {"items": [payload]}, (
            f"_format_toml_list lost or mutated payload {payload!r}. Got parsed={parsed!r}"
        )

    def test_multiple_items_each_escaped(self) -> None:
        """Mixed-hostile multi-item array round-trips element-by-element."""
        items = ['a"b', "c\\d", "e\nf"]
        fragment = f"items = {_format_toml_list(items)}"
        parsed = _parse_or_fail(fragment, writer_name="_format_toml_list", payload=str(items))
        assert parsed == {"items": items}, (
            f"_format_toml_list mangled multi-item array. Got parsed={parsed!r}"
        )


# ---------------------------------------------------------------------------
# 2. ``_build_header`` --- ``[bonfire]`` with ``name``
# ---------------------------------------------------------------------------


class TestBuildHeader:
    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    def test_header_is_valid_toml(self, payload: str) -> None:
        fragment, _ = _build_header(payload)
        parsed = _parse_or_fail(fragment, writer_name="_build_header", payload=payload)
        assert parsed.get("bonfire", {}).get("name") == payload, (
            f"_build_header lost name {payload!r}; parsed={parsed!r}"
        )

    def test_header_does_not_smuggle_top_level_tables(self) -> None:
        """A name carrying ``\\n[bonfire.malicious]`` MUST NOT inject a sibling table."""
        payload = 'evil\n[bonfire.malicious]\nfoo = "bar"'
        fragment, _ = _build_header(payload)
        parsed = _parse_or_fail(fragment, writer_name="_build_header", payload=payload)
        # The legitimate output has exactly one top-level table: bonfire,
        # which contains exactly one key: name. No malicious sub-table.
        assert parsed == {"bonfire": {"name": payload}}, (
            f"_build_header smuggled extra structure for {payload!r}. Parsed: {parsed!r}"
        )


# ---------------------------------------------------------------------------
# 3. ``_build_persona`` --- ``[bonfire.persona]``
# ---------------------------------------------------------------------------


class TestBuildPersona:
    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    def test_persona_value_round_trips(self, payload: str) -> None:
        profile = {"companion_mode": payload}
        result = _build_persona(profile)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_persona", payload=payload)
        persona = parsed.get("bonfire", {}).get("persona", {})
        assert persona == {"companion_mode": payload}, (
            f"_build_persona lost or smuggled payload {payload!r}. "
            f"Parsed persona table: {persona!r}"
        )


# ---------------------------------------------------------------------------
# 4. ``_build_project`` --- ``[bonfire.project]``
# ---------------------------------------------------------------------------


class TestBuildProject:
    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    @pytest.mark.parametrize("label", ["language", "framework", "test_framework"])
    def test_project_scan_value_round_trips(self, payload: str, label: str) -> None:
        scans = [_scan("project_structure", label, payload)]
        result = _build_project(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_project", payload=payload)
        # The emitted key in TOML uses ``primary_language`` for ``language``.
        toml_key = {"language": "primary_language"}.get(label, label)
        project = parsed.get("bonfire", {}).get("project", {})
        assert project.get(toml_key) == payload, (
            f"_build_project lost {label}={payload!r}. Parsed project: {project!r}"
        )

    def test_project_name_with_quote_does_not_inject_table(self) -> None:
        """Directory name ``foo\"bar`` flowing through ``_build_project`` stays a value."""
        scans = [_scan("project_structure", "language", 'foo"bar')]
        result = _build_project(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_project", payload='foo"bar')
        assert parsed == {"bonfire": {"project": {"primary_language": 'foo"bar'}}}, (
            f"_build_project produced extra structure for quote payload. Parsed: {parsed!r}"
        )


# ---------------------------------------------------------------------------
# 5. ``_build_git`` --- ``[bonfire.git]``
# ---------------------------------------------------------------------------


class TestBuildGit:
    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    @pytest.mark.parametrize("label", ["remote", "branch"])
    def test_git_scan_value_round_trips(self, payload: str, label: str) -> None:
        scans = [_scan("git_state", label, payload)]
        result = _build_git(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_git", payload=payload)
        git = parsed.get("bonfire", {}).get("git", {})
        assert git.get(label) == payload, (
            f"_build_git lost {label}={payload!r}. Parsed git: {git!r}"
        )


# ---------------------------------------------------------------------------
# 6. ``_build_claude_memory`` --- ``[bonfire.claude_memory]``
# ---------------------------------------------------------------------------


class TestBuildClaudeMemory:
    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    @pytest.mark.parametrize("label", ["model", "permissions", "extensions"])
    def test_claude_memory_value_round_trips(self, payload: str, label: str) -> None:
        scans = [_scan("claude_memory", label, payload)]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_claude_memory", payload=payload)
        cm = parsed.get("bonfire", {}).get("claude_memory", {})
        assert cm.get(label) == payload, (
            f"_build_claude_memory lost {label}={payload!r}. Parsed: {cm!r}"
        )


# ---------------------------------------------------------------------------
# 7. ``_build_vault`` --- ``[bonfire.vault]``
# ---------------------------------------------------------------------------


class TestBuildVault:
    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    def test_vault_seed_document_round_trips(self, payload: str) -> None:
        scans = [_scan("vault_seed", payload, "ignored")]
        result = _build_vault(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_vault", payload=payload)
        seeds = parsed.get("bonfire", {}).get("vault", {}).get("seed_documents")
        assert seeds == [payload], (
            f"_build_vault lost seed-document label {payload!r}. Parsed seeds: {seeds!r}"
        )


# ---------------------------------------------------------------------------
# 8. Adjacent writers that route through ``_format_toml_list``
# ---------------------------------------------------------------------------
#
# ``_build_tools`` and ``_build_mcp`` are not in the dispatch's named-7
# but inherit the bug via ``_format_toml_list``. They are pinned here
# because the warrior's fix touches the same surface and the contract
# must hold for them too. The MCP case is the canonical
# table-smuggling attack vector (a hostile ``.mcp.json`` key).


class TestBuildToolsViaList:
    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    def test_tools_label_round_trips(self, payload: str) -> None:
        scans = [_scan("cli_toolchain", payload, "ignored")]
        result = _build_tools(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_tools", payload=payload)
        detected = parsed.get("bonfire", {}).get("tools", {}).get("detected")
        assert detected == [payload], (
            f"_build_tools lost tool label {payload!r}. Parsed: {detected!r}"
        )


class TestBuildMcpServerKeyInjection:
    """MCP server keys come from ``.mcp.json``; an attacker-planted key MUST NOT smuggle."""

    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    def test_mcp_server_key_round_trips(self, payload: str) -> None:
        scans = [_scan("mcp_servers", payload, "ignored")]
        result = _build_mcp(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_mcp", payload=payload)
        servers = parsed.get("bonfire", {}).get("mcp", {}).get("servers")
        assert servers == [payload], (
            f"_build_mcp lost server name {payload!r}. Parsed servers: {servers!r}"
        )

    def test_hostile_mcp_key_does_not_inject_bonfire_subtable(self) -> None:
        """The canonical ``.mcp.json`` table-smuggling attack must be neutralised."""
        hostile_key = 'attacker"\n[bonfire.malicious]\nfoo = "bar"'
        scans = [_scan("mcp_servers", hostile_key, "ignored")]
        result = _build_mcp(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_mcp", payload=hostile_key)
        # The only legitimate parsed shape is exactly one [bonfire.mcp]
        # table containing a single ``servers`` list with the hostile
        # key preserved as a value. No ``[bonfire.malicious]`` table.
        assert parsed == {"bonfire": {"mcp": {"servers": [hostile_key]}}}, (
            f"_build_mcp injected extra structure for hostile key: {parsed!r}"
        )


# ---------------------------------------------------------------------------
# 9. End-to-end ``generate_config`` round-trip
# ---------------------------------------------------------------------------


class TestGenerateConfigEndToEnd:
    """The public entry point must produce valid TOML regardless of hostile inputs."""

    def test_generate_config_full_round_trip_with_hostile_inputs(self) -> None:
        """Every writer reached at once with hostile payloads; output parses + round-trips."""
        hostile = 'evil"\n[bonfire.malicious]\nx = "y"'
        scans = [
            _scan("project_structure", "language", hostile),
            _scan("project_structure", "framework", hostile),
            _scan("cli_toolchain", hostile, "ignored"),
            _scan("git_state", "remote", hostile),
            _scan("git_state", "branch", hostile),
            _scan("claude_memory", "model", hostile),
            _scan("claude_memory", "permissions", hostile),
            _scan("mcp_servers", hostile, "ignored"),
            _scan("vault_seed", hostile, "ignored"),
        ]
        profile = {"companion_mode": hostile}
        result = generate_config(scans, profile, project_name=hostile)

        # Pin 1: emitted TOML parses cleanly.
        try:
            parsed = tomllib.loads(result.config_toml)
        except tomllib.TOMLDecodeError as exc:
            pytest.fail(
                f"generate_config produced invalid TOML. Raw:\n{result.config_toml}\n\nError: {exc}"
            )

        # Pin 2: top-level keys are exactly {bonfire}; nothing smuggled.
        assert set(parsed.keys()) == {"bonfire"}, (
            f"generate_config smuggled extra top-level tables: {set(parsed.keys())!r}"
        )

        # Pin 3: ``[bonfire]`` sub-tables are exactly the seven legitimate
        # ones --- no ``malicious`` sibling.
        bonfire = parsed["bonfire"]
        expected_subtables = {
            "persona",
            "project",
            "tools",
            "git",
            "claude_memory",
            "mcp",
            "vault",
        }
        sub_tables = {k for k, v in bonfire.items() if isinstance(v, dict)}
        assert sub_tables == expected_subtables, (
            f"generate_config smuggled or dropped a [bonfire.*] sub-table. "
            f"Got: {sub_tables!r}; expected: {expected_subtables!r}"
        )

        # Pin 4: round-trip preservation on every hostile value the
        # writers consumed.
        assert bonfire["name"] == hostile
        assert bonfire["persona"]["companion_mode"] == hostile
        assert bonfire["project"]["primary_language"] == hostile
        assert bonfire["project"]["framework"] == hostile
        assert bonfire["tools"]["detected"] == [hostile]
        assert bonfire["git"]["remote"] == hostile
        assert bonfire["git"]["branch"] == hostile
        assert bonfire["claude_memory"]["model"] == hostile
        assert bonfire["claude_memory"]["permissions"] == hostile
        assert bonfire["mcp"]["servers"] == [hostile]
        assert bonfire["vault"]["seed_documents"] == [hostile]
