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
pins the SAME contract for the writer functions in
``config_generator.py`` that still emit into the project-portable
``bonfire.toml``:

* ``_format_toml_list`` (used by ``_build_mcp``, ``_build_vault``, and
  by the operator-local ``_split_tools_local`` materialiser);
* ``_build_header``;
* ``_build_project``;
* ``_build_git``;
* ``_build_claude_memory``;
* ``_build_vault``;
* ``_build_persona``.

(``_build_tools`` is no longer covered here — per W8.G it returns
``None`` unconditionally and the tool inventory now flows to
``.bonfire/tools.local.toml`` via a sentinel comment; that contract
is pinned in ``test_tools_section_is_local.py``.)

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
from pathlib import Path

import pytest

from bonfire.onboard.config_generator import (
    _build_claude_memory,
    _build_git,
    _build_header,
    _build_mcp,
    _build_persona,
    _build_project,
    _build_vault,
    _format_toml_list,
    generate_config,
    write_config,
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
    """``_build_claude_memory`` must produce parseable TOML even under hostile
    inputs.

    The original contract round-tripped sentinel values (``model``,
    ``permissions``, ``extensions``) as TOML strings — but the
    ``claude_memory`` scanner emits **redaction sentinels** for those
    labels (per its privacy posture), so stamping them as TOML values
    produced unreadable noise like ``model = "set"``. The new contract:
    sentinel labels are surfaced as TOML comments, not values; hostile
    payloads must still parse cleanly and MUST NOT smuggle extra
    structure.
    """

    @pytest.mark.parametrize("payload", _HOSTILE_PAYLOADS)
    @pytest.mark.parametrize("label", ["model", "permissions", "extensions"])
    def test_claude_memory_hostile_payload_does_not_break_toml(
        self, payload: str, label: str
    ) -> None:
        """Hostile sentinel payloads still produce parseable TOML with no smuggling."""
        scans = [_scan("claude_memory", label, payload)]
        result = _build_claude_memory(scans)
        assert result is not None
        fragment, _ = result
        parsed = _parse_or_fail(fragment, writer_name="_build_claude_memory", payload=payload)
        # Contract: sentinel labels are NOT emitted as TOML values
        # (regardless of hostile content). The section parses cleanly
        # with no smuggled sibling tables.
        bonfire = parsed.get("bonfire", {})
        assert set(bonfire.keys()) == {"claude_memory"} or bonfire == {}, (
            f"_build_claude_memory smuggled extra top-level keys for "
            f"{label}={payload!r}; got: {bonfire!r}"
        )
        cm = bonfire.get("claude_memory", {})
        assert label not in cm, (
            f"sentinel label {label!r} must not be emitted as a TOML value; "
            f"parsed section: {cm!r}\nFragment:\n{fragment}"
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
# 8. Adjacent writer that routes through ``_format_toml_list``
# ---------------------------------------------------------------------------
#
# ``_build_mcp`` is not in the dispatch's named-7 but inherits the bug
# via ``_format_toml_list``. It is pinned here because the warrior's
# fix touches the same surface and the contract must hold for it too.
# The MCP case is the canonical table-smuggling attack vector (a
# hostile ``.mcp.json`` key).
#
# Note: ``_build_tools`` is intentionally NOT covered here — under
# W8.G it returns ``None`` unconditionally and routes the operator-local
# tool inventory to ``.bonfire/tools.local.toml`` instead. The
# sanitization-coverage assertion for that flow lives in
# ``TestGenerateConfigEndToEnd`` below (it exercises
# ``_build_tools_sentinel`` + ``_split_tools_local`` end-to-end via
# ``write_config``). The full operator-local contract is pinned in
# ``test_tools_section_is_local.py``.


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

    def test_generate_config_full_round_trip_with_hostile_inputs(
        self,
        tmp_path: Path,
    ) -> None:
        """Every writer reached at once with hostile payloads; outputs parse + round-trip.

        Under W8.G, ``cli_toolchain`` scans no longer land in the
        project-portable ``bonfire.toml`` — they route through
        ``_build_tools_sentinel`` (which strips comma/CR/LF defensively)
        to a sentinel comment that ``write_config`` extracts into
        ``.bonfire/tools.local.toml`` (via ``_split_tools_local`` +
        ``_format_toml_list``). This test exercises BOTH halves of the
        sanitization coverage:

          * the main ``bonfire.toml`` must contain NO ``[bonfire.tools]``
            section (and parse cleanly under hostile inputs across every
            other writer);
          * the operator-local ``.bonfire/tools.local.toml`` sibling must
            be written, parse cleanly, and surface the hostile tool name
            as a sanitized list entry (comma/CR/LF stripped, but the rest
            preserved verbatim through ``escape_basic_string``).
        """
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

        # Pin 1: emitted TOML parses cleanly (the cli_toolchain sentinel
        # is a valid TOML comment line, so tomllib parses with or
        # without it present).
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

        # Pin 3: ``[bonfire]`` sub-tables are exactly the six legitimate
        # ones for the project-portable TOML --- ``tools`` is GONE
        # (W8.G: operator-local), and no ``malicious`` sibling slipped
        # in via the hostile inputs.
        bonfire = parsed["bonfire"]
        expected_subtables = {
            "persona",
            "project",
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
        # Defense-in-depth: explicitly assert no ``tools`` key under
        # ``[bonfire]`` at all (covers both sub-table and scalar shapes).
        assert "tools" not in bonfire, (
            f"generate_config leaked cli_toolchain data into the "
            f"project-portable bonfire.toml under hostile inputs; "
            f"bonfire keys: {sorted(bonfire.keys())!r}"
        )

        # Pin 4: round-trip preservation on every hostile value the
        # writers consumed AS A TOML VALUE (excluding the cli_toolchain
        # flow, which is asserted separately against the sibling file
        # below).
        assert bonfire["name"] == hostile
        assert bonfire["persona"]["companion_mode"] == hostile
        assert bonfire["project"]["primary_language"] == hostile
        assert bonfire["project"]["framework"] == hostile
        assert bonfire["git"]["remote"] == hostile
        assert bonfire["git"]["branch"] == hostile
        # ``claude_memory.model`` / ``claude_memory.permissions`` are
        # sentinel labels — surfaced as TOML comments, not values. The
        # parsed section MUST NOT carry them as keys (no smuggling), but
        # there is nothing to round-trip as a value either.
        assert "model" not in bonfire["claude_memory"]
        assert "permissions" not in bonfire["claude_memory"]
        assert bonfire["mcp"]["servers"] == [hostile]
        assert bonfire["vault"]["seed_documents"] == [hostile]

        # Pin 5: cli_toolchain sanitization — the hostile tool name
        # flows through ``_build_tools_sentinel`` (which strips
        # comma/CR/LF) into the sentinel comment, and ``write_config``
        # materialises ``.bonfire/tools.local.toml`` via
        # ``_split_tools_local`` + ``_format_toml_list``. Both halves
        # MUST produce valid TOML; the on-disk sibling MUST surface
        # the sanitized name without smuggling structure.
        write_config(result.config_toml, tmp_path)

        # The main bonfire.toml lands without a [bonfire.tools] section
        # even after the on-disk write.
        on_disk_main = (tmp_path / "bonfire.toml").read_text()
        assert "[bonfire.tools]" not in on_disk_main, (
            f"write_config leaked [bonfire.tools] into bonfire.toml "
            f"under hostile inputs:\n{on_disk_main}"
        )

        # The operator-local sibling exists and parses cleanly.
        local_path = tmp_path / ".bonfire" / "tools.local.toml"
        assert local_path.exists(), (
            f"write_config did not emit the operator-local tools sibling "
            f"at {local_path} for hostile cli_toolchain input; tree: "
            f"{sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))!r}"
        )
        try:
            with local_path.open("rb") as fh:
                local_data = tomllib.load(fh)
        except tomllib.TOMLDecodeError as exc:
            pytest.fail(
                f".bonfire/tools.local.toml is not valid TOML under hostile "
                f"input. Raw:\n{local_path.read_text()}\n\nError: {exc}"
            )

        # The hostile name flows through two sanitization layers:
        #   1. ``_build_tools_sentinel`` strips comma/CR/LF defensively
        #      (so the single-line sentinel wire format survives).
        #   2. ``_format_toml_list`` runs ``escape_basic_string`` on each
        #      name (so the on-disk TOML stays valid).
        # The expected sibling content is exactly the hostile name with
        # CR/LF removed (commas were not in the payload).
        expected_sanitized = hostile.replace("\r", "").replace("\n", "")
        detected = local_data.get("bonfire", {}).get("tools", {}).get("detected")
        assert detected == [expected_sanitized], (
            f"tools.local.toml lost or mangled the sanitized hostile tool "
            f"name. Expected [{expected_sanitized!r}]; got {detected!r}"
        )
        # No smuggled top-level table from the hostile newline payload.
        assert set(local_data.keys()) == {"bonfire"}, (
            f"tools.local.toml smuggled extra top-level tables under "
            f"hostile input: {set(local_data.keys())!r}"
        )
        assert set(local_data["bonfire"].keys()) == {"tools"}, (
            f"tools.local.toml smuggled extra [bonfire.*] sub-tables "
            f"under hostile input: {set(local_data['bonfire'].keys())!r}"
        )
