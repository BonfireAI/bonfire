# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``[bonfire.tools]`` is operator-local, never project-portable.

Subject: ``bonfire scan`` today stamps a ``[bonfire.tools]`` section into
``bonfire.toml`` derived from the host's ``cli_toolchain`` panel
(``shutil.which(tool)`` per entry in
``bonfire.onboard.scanners.cli_toolchain.TOOLS``). The resulting list
is **per-machine** — different operators have different tool stacks
(``git``, ``python3``, ``node``, ``docker``, …, up to 23 candidates) and
different versions. ``bonfire.toml`` is destined for ``git commit``,
which makes the section:

  * a **privacy leak** — operator tool inventory + version footprint
    persisted into a public repo;
  * an **idempotence/portability defect** — running ``bonfire scan`` on
    two machines produces two byte-different ``bonfire.toml`` files, so
    the project-portable config is silently per-machine.

The fix shape (Anta, dispatch W8.G option a) moves the section to a
SEPARATE file ``.bonfire/tools.local.toml`` that is ``.gitignore``'d at
``bonfire init`` time. ``bonfire.toml`` stays project-portable;
``.bonfire/tools.local.toml`` stays per-machine, never committed.

This file pins six contracts:

  1. ``generate_config`` MUST NOT include a ``[bonfire.tools]`` section
     in the main ``config_toml`` string.

  2. ``write_config`` MUST emit ``.bonfire/tools.local.toml`` next to
     ``bonfire.toml`` when the scan results carry ``cli_toolchain``
     events, and that file MUST carry the tool inventory in a
     ``[bonfire.tools]`` table.

  3. ``bonfire init`` MUST add a ``.gitignore`` entry covering
     ``.bonfire/tools.local.toml`` (the simplest sufficient cover is the
     directory itself, ``.bonfire/``, but a narrower entry that names
     the file directly is equally acceptable).

  4. The reader API ``load_tools_config(project_path)`` (new module
     surface owned by the Warrior) MUST prefer
     ``.bonfire/tools.local.toml`` when present and fall back to an
     empty mapping when absent — never read tools from
     ``bonfire.toml``.

  5. Backward-compat: a legacy ``bonfire.toml`` that still carries
     ``[bonfire.tools]`` (pre-migration) MUST be silently ignored by
     the reader when a ``.bonfire/tools.local.toml`` exists. The legacy
     section is harmlessly orphaned — no warning, no migration, no
     surprise mutation (per W8.G dispatch option (i)).

  6. No-leak regression canary: NO scan invocation, regardless of host
     context, ever writes ``[bonfire.tools]`` into ``bonfire.toml``.
     Exercised end-to-end through ``write_config``.

Cross-lane note (OL-3): W8.F edits ``_is_init_stub`` in the same file
(``src/bonfire/onboard/config_generator.py``) but in a different
region. These tests do NOT depend on ``_is_init_stub`` widening — when
they need a "stub-like" pre-existing ``bonfire.toml`` they use the
exact current byte form ``b"[bonfire]\\n"`` so the predicate's
narrow-or-wide direction is irrelevant.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from bonfire.onboard.config_generator import (
    _build_tools,
    generate_config,
    write_config,
)
from bonfire.onboard.protocol import ScanUpdate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


# The exact byte string ``bonfire init`` writes today. Used wherever a
# pre-existing ``bonfire.toml`` is needed so ``_is_init_stub`` recognises
# it regardless of W8.F's stub-predicate widening direction.
EXPECTED_INIT_BYTES = b"[bonfire]\n"

# A canonical fake cli_toolchain panel: the bare tool names emitted by
# ``cli_toolchain.scan`` (``ScanUpdate.label == tool``, ``value ==
# version``). Mirrors the real scanner's emission shape.
_FAKE_TOOLS: list[tuple[str, str]] = [
    ("git", "2.43.0"),
    ("python3", "3.12.3"),
    ("node", "20.11.1"),
    ("docker", "25.0.3"),
    ("ruff", "0.4.1"),
]


def _scan(panel: str, label: str, value: str, detail: str = "") -> ScanUpdate:
    return ScanUpdate(panel=panel, label=label, value=value, detail=detail)


def _fake_tool_scans() -> list[ScanUpdate]:
    """Build a representative ``cli_toolchain`` scan-result list."""
    return [_scan("cli_toolchain", name, ver) for name, ver in _FAKE_TOOLS]


def _load_tools_reader():
    """Lazy-import the (new) reader so its absence fails per-test cleanly.

    The Warrior adds ``load_tools_config`` to
    ``bonfire.onboard.config_generator`` (or a sibling module they
    choose; the Knight defers placement so long as the import path
    ``from bonfire.onboard.config_generator import load_tools_config``
    works). RED state today: the symbol does not exist.
    """
    from bonfire.onboard import config_generator

    try:
        return config_generator.load_tools_config
    except AttributeError as exc:
        raise ImportError(
            "cannot import name 'load_tools_config' from "
            "'bonfire.onboard.config_generator' — the reader API for the "
            "operator-local tools file has not been implemented yet"
        ) from exc


# ---------------------------------------------------------------------------
# Pin #1 — ``generate_config`` omits ``[bonfire.tools]`` from main TOML.
# ---------------------------------------------------------------------------


class TestGenerateConfigOmitsToolsSection:
    """``generate_config`` MUST NOT route ``cli_toolchain`` scans into the
    main ``bonfire.toml`` payload — the section must be excluded so the
    project-portable config stays project-portable.
    """

    def test_main_toml_has_no_tools_subtable(self) -> None:
        """Parsed ``config_toml`` MUST NOT carry a ``[bonfire.tools]`` table.

        Construct ``generate_config`` with a non-empty ``cli_toolchain``
        panel; parse the resulting ``config_toml``; assert the
        ``bonfire`` table has no ``tools`` sub-table key.
        """
        result = generate_config(
            scan_results=_fake_tool_scans(),
            profile={},
            project_name="demo-project",
        )

        parsed = tomllib.loads(result.config_toml)
        bonfire = parsed.get("bonfire", {})
        assert "tools" not in bonfire, (
            "generate_config leaked the cli_toolchain panel into the "
            "project-portable bonfire.toml; the [bonfire.tools] table is "
            f"operator-local and must move to .bonfire/tools.local.toml. "
            f"Got bonfire keys: {sorted(bonfire.keys())!r}"
        )

    def test_main_toml_string_has_no_tools_header(self) -> None:
        """Raw ``config_toml`` string MUST NOT contain ``[bonfire.tools]``.

        Belt-and-suspenders to the parsed-shape check: a commented-out
        header would slip past TOML parsing but still leak host names if
        the section line itself ever carries a comment containing
        operator paths. The raw string must not contain the table
        header at all.
        """
        result = generate_config(
            scan_results=_fake_tool_scans(),
            profile={},
            project_name="demo-project",
        )
        assert "[bonfire.tools]" not in result.config_toml, (
            "generate_config emitted the literal table header "
            "'[bonfire.tools]' into the project-portable bonfire.toml. "
            f"Raw config_toml:\n{result.config_toml}"
        )

    def test_tools_annotation_does_not_promise_main_toml(self) -> None:
        """``annotations`` MUST NOT advertise a ``tools.detected`` key
        sourced into the main TOML when the new layout puts it in a
        sibling file. The Warrior may either drop the annotation
        entirely, OR re-key it (e.g. ``tools_local.detected``) — either
        is acceptable. What is NOT acceptable: keeping
        ``tools.detected`` while moving the value out of the main TOML
        (the annotation would then lie about where the data lives).
        """
        result = generate_config(
            scan_results=_fake_tool_scans(),
            profile={},
            project_name="demo-project",
        )
        # The illegal state: ``tools.detected`` is still in annotations
        # AND the main TOML has no ``[bonfire.tools]`` to satisfy it.
        parsed = tomllib.loads(result.config_toml)
        bonfire = parsed.get("bonfire", {})
        if "tools" not in bonfire and "tools.detected" in result.annotations:
            pytest.fail(
                "annotations advertises 'tools.detected' but the main "
                "TOML carries no [bonfire.tools] table — the annotation "
                f"contradicts the layout. annotations={result.annotations!r}"
            )


# ---------------------------------------------------------------------------
# Pin #2 — ``write_config`` emits ``.bonfire/tools.local.toml`` sibling.
# ---------------------------------------------------------------------------


class TestWriteConfigEmitsLocalToolsFile:
    """``write_config`` MUST persist ``cli_toolchain`` data to a sibling
    operator-local file at ``.bonfire/tools.local.toml`` so the data is
    available locally without polluting the project-portable
    ``bonfire.toml``.
    """

    def test_local_tools_file_created_when_tools_scans_present(
        self,
        tmp_path: Path,
    ) -> None:
        """After ``write_config``, ``.bonfire/tools.local.toml`` exists
        and parses as TOML.
        """
        config = generate_config(
            scan_results=_fake_tool_scans(),
            profile={},
            project_name="demo-project",
        )
        # ``write_config`` is the canonical entry point — it owns the
        # full disk-side handoff (main TOML + any sibling files). The
        # Warrior's fix may pass the scan_results through ConfigGenerated
        # or via a new write_config kwarg; the Knight does NOT pin the
        # internal threading shape. What is pinned: by the time
        # write_config returns, the sibling file exists on disk.
        write_config(config.config_toml, tmp_path)

        local_path = tmp_path / ".bonfire" / "tools.local.toml"
        assert local_path.exists(), (
            f"write_config did not create the operator-local tools file at "
            f"{local_path}. Existing tree under tmp_path: "
            f"{sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))!r}"
        )
        assert local_path.is_file(), (
            f".bonfire/tools.local.toml exists but is not a regular file: {local_path.stat()!r}"
        )

        # Parses cleanly.
        with local_path.open("rb") as fh:
            data = tomllib.load(fh)

        # Carries the tool inventory under [bonfire.tools].
        bonfire = data.get("bonfire", {})
        assert isinstance(bonfire, dict), (
            f"[bonfire] table missing from tools.local.toml; got: {data!r}"
        )
        tools = bonfire.get("tools")
        assert isinstance(tools, dict), (
            f"[bonfire.tools] table missing from tools.local.toml; got bonfire={bonfire!r}"
        )

        # The detected list contains every scanned tool name.
        detected = tools.get("detected")
        expected_names = {name for name, _ in _FAKE_TOOLS}
        assert isinstance(detected, list), (
            f"[bonfire.tools].detected must be a list; got {detected!r}"
        )
        assert set(detected) == expected_names, (
            f"[bonfire.tools].detected dropped or added tools. "
            f"Expected {expected_names!r}; got {set(detected)!r}"
        )

    def test_local_tools_file_not_created_when_no_tools_scans(
        self,
        tmp_path: Path,
    ) -> None:
        """No ``cli_toolchain`` events → no sibling file (don't write
        empty noise to the user's tree)."""
        # Note: at least one non-tool scan to exercise generate_config
        # past its empty-input short-circuits.
        non_tool_scans = [_scan("project_structure", "language", "python")]
        config = generate_config(
            scan_results=non_tool_scans,
            profile={},
            project_name="demo-project",
        )
        write_config(config.config_toml, tmp_path)

        local_path = tmp_path / ".bonfire" / "tools.local.toml"
        assert not local_path.exists(), (
            f"write_config created tools.local.toml at {local_path} even "
            f"though no cli_toolchain scans were emitted; the sibling "
            f"file must be conditional on the presence of tool data"
        )


# ---------------------------------------------------------------------------
# Pin #3 — ``bonfire init`` gitignores the operator-local tools file.
# ---------------------------------------------------------------------------


class TestInitGitignoresLocalToolsFile:
    """``bonfire init`` MUST seed a ``.gitignore`` entry that prevents
    ``.bonfire/tools.local.toml`` from ever being staged. The simplest
    sufficient cover is the directory ``.bonfire/`` itself; a narrower
    entry naming the file directly is equally acceptable. The Knight
    accepts any pattern that matches the operator-local file under
    standard git semantics.
    """

    def test_init_creates_gitignore_covering_tools_local_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``bonfire init`` adds an entry to ``.gitignore`` matching
        ``.bonfire/tools.local.toml``.
        """
        from typer.testing import CliRunner

        from bonfire.cli.app import app

        runner = CliRunner()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "."])
        assert result.exit_code == 0, (
            f"init must succeed; got exit_code={result.exit_code}, output={result.output!r}"
        )

        gitignore_path = tmp_path / ".gitignore"
        assert gitignore_path.exists(), (
            f"bonfire init did not create a .gitignore at {gitignore_path}. "
            f"Existing tree: "
            f"{sorted(p.relative_to(tmp_path).as_posix() for p in tmp_path.rglob('*'))!r}"
        )

        body = gitignore_path.read_text()
        lines = [
            line.strip()
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]

        # Accept any line that, under standard gitignore semantics,
        # matches ``.bonfire/tools.local.toml``. The set of acceptable
        # patterns includes:
        #   * ``.bonfire/`` (cover the whole operator-local dir)
        #   * ``.bonfire/tools.local.toml`` (cover the specific file)
        #   * ``.bonfire/*`` (cover dir contents)
        #   * ``tools.local.toml`` (filename-only — narrower but still covers)
        acceptable = {
            ".bonfire/",
            ".bonfire",
            ".bonfire/*",
            ".bonfire/**",
            ".bonfire/tools.local.toml",
            "tools.local.toml",
        }
        matched = [line for line in lines if line in acceptable]
        assert matched, (
            f".gitignore at {gitignore_path} does NOT contain any entry that "
            f"covers .bonfire/tools.local.toml. Accepted patterns: "
            f"{sorted(acceptable)!r}. Got entries: {lines!r}. Raw body:\n{body}"
        )

    def test_init_gitignore_idempotent_does_not_duplicate(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Running ``bonfire init`` twice (re-init) MUST NOT duplicate the
        ``.bonfire/`` entry in ``.gitignore``. ``bonfire init`` is
        idempotent (per ``init.py``'s ``if not toml_path.exists()`` and
        ``mkdir(exist_ok=True)``); the gitignore seeding must follow the
        same rule — re-running must not append a second copy of the
        same line.
        """
        from typer.testing import CliRunner

        from bonfire.cli.app import app

        runner = CliRunner()
        monkeypatch.chdir(tmp_path)

        result1 = runner.invoke(app, ["init", "."])
        assert result1.exit_code == 0
        result2 = runner.invoke(app, ["init", "."])
        assert result2.exit_code == 0

        gitignore_path = tmp_path / ".gitignore"
        assert gitignore_path.exists()
        body = gitignore_path.read_text()
        lines = [line.strip() for line in body.splitlines()]

        # Count how many gitignore lines mention the .bonfire token.
        bonfire_lines = [line for line in lines if ".bonfire" in line and not line.startswith("#")]
        assert len(bonfire_lines) <= 1, (
            f"bonfire init duplicated .bonfire-related .gitignore entries on "
            f"re-init. Got {len(bonfire_lines)} matching lines: "
            f"{bonfire_lines!r}. Full body:\n{body}"
        )


# ---------------------------------------------------------------------------
# Pin #4 — Reader API consults ``.bonfire/tools.local.toml``.
# ---------------------------------------------------------------------------


class TestLoadToolsConfigReader:
    """``load_tools_config(project_path)`` is the new reader API.

    The Knight does NOT pin a specific return-type shape beyond
    "mapping-like with a ``detected`` key when the file exists". The
    Warrior may return a TypedDict, a plain ``dict``, or a small
    dataclass — what the tests pin is the behaviour, not the type.
    """

    def test_load_tools_config_reads_local_file_when_present(
        self,
        tmp_path: Path,
    ) -> None:
        """Reader returns the local file's content under the standard key."""
        load_tools_config = _load_tools_reader()

        # Seed the operator-local file directly (don't depend on
        # write_config here — this test is for the reader half).
        local_dir = tmp_path / ".bonfire"
        local_dir.mkdir()
        local_path = local_dir / "tools.local.toml"
        local_path.write_text('[bonfire.tools]\ndetected = ["git", "python3", "node"]\n')

        result = load_tools_config(tmp_path)

        # Reader exposes the parsed ``[bonfire.tools]`` content. The
        # Knight accepts either:
        #   * the full parsed dict ``{"detected": [...]}``, OR
        #   * a mapping-like with at least a ``detected`` key.
        detected = result.get("detected") if hasattr(result, "get") else None
        assert detected is not None, (
            f"load_tools_config returned {result!r}; expected a mapping "
            f"with a 'detected' key reflecting tools.local.toml content"
        )
        assert set(detected) == {"git", "python3", "node"}, (
            f"load_tools_config did not surface the local file's 'detected' list; got {detected!r}"
        )

    def test_load_tools_config_returns_empty_when_local_file_absent(
        self,
        tmp_path: Path,
    ) -> None:
        """Missing ``.bonfire/tools.local.toml`` → reader returns an
        empty/default mapping (no crash, no exception, no fall-through
        to ``bonfire.toml``).
        """
        load_tools_config = _load_tools_reader()

        # No .bonfire/, no bonfire.toml — pristine directory.
        result = load_tools_config(tmp_path)

        # Accepted shapes for "nothing detected":
        #   * empty mapping ``{}``
        #   * mapping with ``detected: []``
        if hasattr(result, "get"):
            detected = result.get("detected", [])
            assert detected == [] or detected is None, (
                f"load_tools_config returned non-empty detected list when "
                f"no local file is present: {detected!r}"
            )
        else:
            pytest.fail(
                f"load_tools_config returned a non-mapping value {result!r} "
                f"on the empty-tree path; expected a dict-like with "
                f"`.get('detected', [])` ergonomics"
            )

    def test_load_tools_config_ignores_bonfire_toml_tools_section(
        self,
        tmp_path: Path,
    ) -> None:
        """Reader must NEVER fall back to ``bonfire.toml[bonfire.tools]``.

        Even when ``bonfire.toml`` carries a (legacy or hand-tuned)
        ``[bonfire.tools]`` section AND the operator-local file is
        absent, the reader returns empty. The bonfire.toml section is
        orphaned by design — no surprise reads.
        """
        load_tools_config = _load_tools_reader()

        # Legacy ``[bonfire.tools]`` in the main TOML, no local file.
        (tmp_path / "bonfire.toml").write_text(
            "[bonfire]\n"
            'name = "legacy-project"\n'
            "\n"
            "[bonfire.tools]\n"
            'detected = ["legacy-leaked-git", "legacy-leaked-node"]\n'
        )

        result = load_tools_config(tmp_path)
        if hasattr(result, "get"):
            detected = result.get("detected", [])
            assert detected == [] or detected is None, (
                f"load_tools_config fell back to bonfire.toml's legacy "
                f"[bonfire.tools] section: got {detected!r}. The reader "
                f"must ONLY consult .bonfire/tools.local.toml (option "
                f"(i) per W8.G dispatch)."
            )


# ---------------------------------------------------------------------------
# Pin #5 — Backward-compat: local file wins; bonfire.toml section orphaned.
# ---------------------------------------------------------------------------


class TestBackwardCompatLocalFileWins:
    """A pre-migration ``bonfire.toml`` with ``[bonfire.tools]`` and a
    new ``.bonfire/tools.local.toml`` both present → the LOCAL file wins.
    The main-TOML section is harmlessly orphaned (no warning, no
    migration, no mutation — per W8.G dispatch option (i)).
    """

    def test_local_file_wins_over_legacy_bonfire_toml_section(
        self,
        tmp_path: Path,
    ) -> None:
        load_tools_config = _load_tools_reader()

        # Legacy bonfire.toml WITH a [bonfire.tools] section.
        (tmp_path / "bonfire.toml").write_text(
            "[bonfire]\n"
            'name = "legacy-project"\n'
            "\n"
            "[bonfire.tools]\n"
            'detected = ["LEGACY-VALUE-MUST-NOT-WIN"]\n'
        )

        # New operator-local file.
        local_dir = tmp_path / ".bonfire"
        local_dir.mkdir()
        (local_dir / "tools.local.toml").write_text(
            '[bonfire.tools]\ndetected = ["new-local-value"]\n'
        )

        result = load_tools_config(tmp_path)
        detected = result.get("detected") if hasattr(result, "get") else None
        assert detected == ["new-local-value"], (
            f"load_tools_config did not prefer the operator-local file "
            f"over the legacy bonfire.toml section. Got {detected!r}; "
            f"expected ['new-local-value']."
        )

    def test_legacy_bonfire_toml_section_is_not_mutated(
        self,
        tmp_path: Path,
    ) -> None:
        """The reader is read-only — calling it MUST NOT migrate or
        rewrite the legacy ``bonfire.toml``. The legacy section stays
        byte-identical after a read (no surprise mutations per option
        (i)).
        """
        load_tools_config = _load_tools_reader()

        original_bonfire_toml = (
            '[bonfire]\nname = "legacy-project"\n\n[bonfire.tools]\ndetected = ["LEGACY-VALUE"]\n'
        )
        bonfire_toml_path = tmp_path / "bonfire.toml"
        bonfire_toml_path.write_text(original_bonfire_toml)

        local_dir = tmp_path / ".bonfire"
        local_dir.mkdir()
        (local_dir / "tools.local.toml").write_text(
            '[bonfire.tools]\ndetected = ["new-local-value"]\n'
        )

        # Read.
        load_tools_config(tmp_path)

        # bonfire.toml unchanged byte-for-byte.
        assert bonfire_toml_path.read_text() == original_bonfire_toml, (
            "load_tools_config mutated the legacy bonfire.toml; the reader "
            "must be read-only (option (i): no migration, no rewrite)"
        )


# ---------------------------------------------------------------------------
# Pin #6 — No-leak regression canary.
# ---------------------------------------------------------------------------


class TestNoLeakInvariant:
    """Defense-in-depth regression canary: NO code path inside the
    generator/writer MAY route ``cli_toolchain`` data into
    ``bonfire.toml``, regardless of host context or flags.
    """

    def test_build_tools_returns_none_or_empty_string(self) -> None:
        """``_build_tools`` MUST NOT emit any non-empty TOML fragment.

        The Warrior's fix may either:
          * make ``_build_tools`` return ``None`` unconditionally
            (so the orchestrator skips it), OR
          * remove ``_build_tools`` and any call site entirely.

        Either shape satisfies this canary: calling ``_build_tools``
        with a non-empty ``cli_toolchain`` panel produces no TOML
        text that would land in ``bonfire.toml``.
        """
        scans = [_scan("cli_toolchain", name, ver) for name, ver in _FAKE_TOOLS]
        result = _build_tools(scans)

        # Acceptable shapes:
        #   * None — orchestrator skips the section entirely.
        #   * ("", {}) — empty fragment + empty annotations (also a skip).
        if result is None:
            return
        text, _annotations = result
        assert "[bonfire.tools]" not in text, (
            "_build_tools still emits a [bonfire.tools] TOML fragment; "
            "the canary catches a regression of the operator-local move. "
            f"Got fragment:\n{text}"
        )
        # And the text overall must not carry any tool names (no
        # comment-only leak path either).
        for tool_name, _ver in _FAKE_TOOLS:
            assert tool_name not in text, (
                f"_build_tools emitted tool name {tool_name!r} into the "
                f"main-TOML fragment text; the operator-local move forbids "
                f"any tool-data leakage into bonfire.toml. Got:\n{text}"
            )

    def test_write_config_main_toml_never_carries_tools_table(
        self,
        tmp_path: Path,
    ) -> None:
        """End-to-end: after ``write_config`` runs, the on-disk
        ``bonfire.toml`` MUST NOT contain a ``[bonfire.tools]`` table —
        every host context, every panel composition, no exceptions.
        """
        # Maximally-rich scan input: every panel populated, including
        # cli_toolchain. The on-disk bonfire.toml must STILL be free of
        # any [bonfire.tools] table.
        scans = [
            _scan("project_structure", "language", "python"),
            _scan("project_structure", "framework", "fastapi"),
            *(_scan("cli_toolchain", name, ver) for name, ver in _FAKE_TOOLS),
            _scan("git_state", "branch", "main"),
            _scan("mcp_servers", "claude_ai_Linear", "x"),
            _scan("vault_seed", "README.md", "x"),
        ]
        config = generate_config(
            scan_results=scans,
            profile={"companion_mode": "thoughtful"},
            project_name="demo",
        )
        write_config(config.config_toml, tmp_path)

        bonfire_toml = tmp_path / "bonfire.toml"
        body = bonfire_toml.read_text()
        assert "[bonfire.tools]" not in body, (
            f"write_config wrote a [bonfire.tools] table into the "
            f"project-portable bonfire.toml. Full file body:\n{body}"
        )
        parsed = tomllib.loads(body)
        assert "tools" not in parsed.get("bonfire", {}), (
            f"Parsed bonfire.toml carries a tools sub-table: {parsed['bonfire']!r}"
        )


# ---------------------------------------------------------------------------
# Pin #7 — Defense-in-depth: reader refuses symlinks at the local file path.
# ---------------------------------------------------------------------------


class TestLoadToolsConfigRefusesSymlinks:
    """The reader MUST NOT follow a symlink at
    ``.bonfire/tools.local.toml``. Same defect class as the W7.M
    write-side guards — a planted symlink would otherwise let an
    attacker exfiltrate an operator-readable file's bytes through the
    reader's return value or any downstream consumer.

    The reader short-circuits to ``{}`` so the caller can't even
    distinguish "symlink present" from "file absent" — closing the
    metadata side-channel too.
    """

    def test_load_tools_config_refuses_symlink_at_local_path(
        self,
        tmp_path: Path,
    ) -> None:
        """A symlink at ``.bonfire/tools.local.toml`` MUST be refused
        (return ``{}``) without opening or parsing the target.
        """
        load_tools_config = _load_tools_reader()

        # Plant a real TOML file with sensitive-looking content as the
        # symlink target. If the reader follows the symlink it will
        # parse this file and surface its content under ``detected``.
        decoy = tmp_path / "decoy.toml"
        decoy.write_text('[bonfire.tools]\ndetected = ["SENSITIVE-MUST-NOT-LEAK"]\n')

        local_dir = tmp_path / ".bonfire"
        local_dir.mkdir()
        local_path = local_dir / "tools.local.toml"
        local_path.symlink_to(decoy)

        result = load_tools_config(tmp_path)

        # The defense surface: reader returns the empty mapping, NEVER
        # the symlink target's content.
        detected = result.get("detected") if hasattr(result, "get") else None
        assert detected in (None, []), (
            f"load_tools_config followed a symlink at .bonfire/tools.local.toml "
            f"and surfaced the target's content. Got detected={detected!r}; "
            f"expected None/[] (symlink-refusal returns empty mapping)."
        )

    def test_load_tools_config_refuses_dangling_symlink(
        self,
        tmp_path: Path,
    ) -> None:
        """A dangling symlink at the local path MUST also be refused —
        the ``is_symlink`` check is metadata-only and must catch the
        dangling case before any open(2) attempt that would raise
        FileNotFoundError and confuse the caller.
        """
        load_tools_config = _load_tools_reader()

        local_dir = tmp_path / ".bonfire"
        local_dir.mkdir()
        local_path = local_dir / "tools.local.toml"
        local_path.symlink_to(tmp_path / "does-not-exist.toml")

        # No exception, returns empty mapping.
        result = load_tools_config(tmp_path)
        detected = result.get("detected") if hasattr(result, "get") else None
        assert detected in (None, []), (
            f"dangling-symlink case returned non-empty detected={detected!r}"
        )


# ---------------------------------------------------------------------------
# Pin #8 — Defense-in-depth: sentinel-line label whitelist.
# ---------------------------------------------------------------------------


class TestToolsSentinelLabelWhitelist:
    """``_build_tools_sentinel`` MUST drop hostile or malformed labels
    rather than smuggle them through the single-line wire format. The
    current ``cli_toolchain`` source emits a hard-coded shape, but the
    defense is cheap and closes the wire-format injection surface.
    """

    def test_sentinel_drops_label_with_embedded_newline(self) -> None:
        """A label containing a newline must NOT make it into the
        sentinel — otherwise the comma-separated line collapses across
        what was meant to be a single line, smuggling extra entries.
        """
        from bonfire.onboard.config_generator import _build_tools_sentinel

        scans = [
            _scan("cli_toolchain", "git", "x"),
            _scan("cli_toolchain", "evil\nname", "x"),
            _scan("cli_toolchain", "python3", "x"),
        ]
        sentinel = _build_tools_sentinel(scans)

        assert sentinel is not None, "expected non-None sentinel"
        assert "evil" not in sentinel, (
            f"sentinel carried the hostile newline-bearing label: {sentinel!r}"
        )
        assert "\n" not in sentinel, (
            f"sentinel contains a literal newline; wire format must be single-line: {sentinel!r}"
        )
        # The well-formed labels still made it through.
        assert "git" in sentinel
        assert "python3" in sentinel

    def test_sentinel_drops_label_with_embedded_comma(self) -> None:
        """An embedded comma must be dropped — otherwise the CSV
        decoder on the read side splits one tool name into two synthetic
        entries.
        """
        from bonfire.onboard.config_generator import _build_tools_sentinel

        scans = [
            _scan("cli_toolchain", "git", "x"),
            _scan("cli_toolchain", "fake,smuggled", "x"),
        ]
        sentinel = _build_tools_sentinel(scans)

        assert sentinel is not None
        assert "smuggled" not in sentinel
        assert "fake" not in sentinel, f"sentinel admitted a comma-bearing label; got {sentinel!r}"

    def test_sentinel_drops_uppercase_and_oversize_labels(self) -> None:
        """Labels outside the lowercase-identifier shape are dropped —
        the whitelist is ``^[a-z][a-z0-9_-]{0,32}$``.
        """
        from bonfire.onboard.config_generator import _build_tools_sentinel

        scans = [
            _scan("cli_toolchain", "Git", "x"),  # capital letter
            _scan("cli_toolchain", "x" * 50, "x"),  # too long
            _scan("cli_toolchain", "0bad", "x"),  # leading digit
            _scan("cli_toolchain", "python3", "x"),  # well-formed
        ]
        sentinel = _build_tools_sentinel(scans)

        assert sentinel is not None
        assert "Git" not in sentinel
        assert ("x" * 50) not in sentinel
        assert "0bad" not in sentinel
        assert "python3" in sentinel


# ---------------------------------------------------------------------------
# Pin #9 — Gitignore narrowness: committable sub-paths under .bonfire/
#          must remain stageable by default.
# ---------------------------------------------------------------------------


class TestInitGitignoreDoesNotOverCover:
    """``bonfire init`` must NOT seed a gitignore entry that excludes
    committable sub-paths under ``.bonfire/`` (sessions, context.json,
    vault seed, opt-in cost ledger). Over-broad coverage silently
    breaks workflows that depend on those paths landing in git.
    """

    def test_gitignore_entry_does_not_cover_bonfire_sessions(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After init, the gitignore must NOT match
        ``.bonfire/sessions/2026-05-15-handoff.md`` — operators commit
        session handoffs.
        """
        import subprocess

        from typer.testing import CliRunner

        from bonfire.cli.app import app

        runner = CliRunner()
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "."])
        assert result.exit_code == 0

        # Use git itself to evaluate the gitignore (most authoritative).
        # ``git check-ignore`` returns 0 when path IS ignored, 1 when
        # NOT ignored. We want NOT ignored for these committable paths.
        try:
            subprocess.run(
                ["git", "init", "-q"],
                cwd=tmp_path,
                check=True,
                capture_output=True,
            )
        except (FileNotFoundError, subprocess.CalledProcessError):
            pytest.skip("git not available")

        committable_paths = [
            ".bonfire/sessions/handoff.md",
            ".bonfire/context.json",
            ".bonfire/vault/seed.md",
            ".bonfire/costs.jsonl",
        ]
        for rel_path in committable_paths:
            check = subprocess.run(
                ["git", "check-ignore", "-q", rel_path],
                cwd=tmp_path,
                capture_output=True,
            )
            # Exit code 1 = NOT ignored (good).
            assert check.returncode == 1, (
                f"bonfire init's .gitignore over-covers: {rel_path!r} is "
                f"matched by the seeded entry but should remain stageable. "
                f"Gitignore body:\n{(tmp_path / '.gitignore').read_text()}"
            )

        # Sanity: the operator-local file IS ignored.
        check = subprocess.run(
            ["git", "check-ignore", "-q", ".bonfire/tools.local.toml"],
            cwd=tmp_path,
            capture_output=True,
        )
        assert check.returncode == 0, (
            f"bonfire init's .gitignore did NOT cover the operator-local "
            f"tools.local.toml file. Body:\n{(tmp_path / '.gitignore').read_text()}"
        )
