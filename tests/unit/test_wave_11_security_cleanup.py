# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Wave 11 Lane B — adversarial contract for read-side TOCTOU + boundary validators.

Six findings from post-Wave-10 Mirror Probe (Scout 1, security axis):

* **H1** — ``mcp_servers._read_servers_from_config`` does a ``stat()`` size cap
  then ``Path.read_text()`` (which follows symlinks) on a worker thread. A
  same-uid attacker can swap the path to a symlink between the resolve and
  the read. Fix: route through ``safe_read_capped_text`` (``O_NOFOLLOW``).

* **H2** — ``SessionPersistence`` interpolates ``session_id`` into the
  filesystem path (``{session_id}.jsonl``) without validation. The class is
  in ``bonfire.session.__all__``; external library consumers passing a
  user-controlled ``session_id`` get unbounded path traversal at the class
  boundary. ``BonfireEvent.session_id`` is validated at the model layer
  but this defense-in-depth gap means the persistence class itself must
  also reject the same shapes. Fix: call ``_validate_session_id`` at the
  top of every public method that takes ``session_id``.

* **M1** — ``onboard.config_generator.load_tools_config`` does an
  ``is_symlink()`` pre-check then ``local_path.open("rb")`` for
  ``tomllib.load``. Same TOCTOU race shape W7.M closed elsewhere. Fix:
  read via ``safe_read_capped_text`` then ``tomllib.loads``.

* **M2** — ``cli/commands/init.py`` has 3 raw ``Path.read_text`` reads
  after ``is_symlink`` pre-checks (``.gitignore`` existing-content scan,
  ``bonfire.toml`` legacy-tools detection, ``.gitignore`` pre-existence
  detection). Fix: route through ``safe_read_capped_text``.

* **M3** — ``cli/commands/persona.py`` has a raw ``Path.read_text``
  after an ``is_symlink`` pre-check (``bonfire.toml`` persona-section
  rewrite). Fix: route through ``safe_read_capped_text``.

* **M4** — ``git/scratch.ScratchWorktreeContext`` uses the public
  ``acquire(prefix=...)`` kwarg in both ``_branch_name()`` and
  ``_worktree_path()`` with no validation. A hostile prefix lands the
  worktree outside ``.bonfire-worktrees/``. Fix: validate ``prefix`` in
  ``acquire()`` — reject ``/``, ``..``, leading ``-``, control chars,
  empty string.

Adversarial path-shape coverage per
``feedback_defense_in_depth_needs_adversarial_tests_2026_05_15``:
``..``, ``//``, case-fold, encoded shapes — exercised through the
symlink-target plant where the canonicalizer applies, and through the
validator regex where the input is a literal string.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# Shared safe-tmp fixture — every test in this file plants symlinks; the
# default ``tmp_path`` fixture renders the test function name into the path,
# and most test names contain "symlink" or "traversal". A path-substring
# assertion like ``"symlink" in stderr`` would false-pass against the path
# itself. ``safe_tmp`` uses ``tempfile.TemporaryDirectory`` with a neutral
# prefix so assertion matches reflect ONLY the implementation's intent.
# ---------------------------------------------------------------------------


@pytest.fixture
def safe_tmp() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="w11b_workdir_") as td:
        yield Path(td)


# ===========================================================================
# H1 — mcp_servers TOCTOU stat-then-read symlink swap
# ===========================================================================


class TestH1McpServersReadRefusesSymlink:
    """``_read_servers_from_config`` must refuse a symlink at the resolved path.

    The threat: ``_safe_resolve_config_path`` returns either the original
    path (when not a symlink) or the resolved target (when the symlink
    target lies under the project write-floor). If the path is rewritten
    to a symlink between the resolve and the read, the unbounded
    ``Path.read_text`` follows it.

    We force the failure mode by patching ``_safe_resolve_config_path``
    to return a symlink path directly — simulating the TOCTOU race outcome
    deterministically without needing a kernel race window.

    Implementation contract: the read path MUST use a helper that opens
    with ``O_NOFOLLOW`` so the kernel refuses the symlink at ``open(2)``.
    """

    def test_module_imports_safe_read_helper(self) -> None:
        """``mcp_servers`` MUST use ``safe_read_capped_text`` at the read
        site so the ``O_NOFOLLOW`` defense closes the TOCTOU window
        between the resolve and the read.
        """
        from bonfire.onboard.scanners import mcp_servers

        source = Path(mcp_servers.__file__).read_text()
        assert "safe_read_capped_text" in source, (
            "mcp_servers must use safe_read_capped_text at the post-"
            "resolve read site (W11 H1 TOCTOU gap)."
        )

    def test_symlink_at_resolved_path_skipped(self, safe_tmp: Path) -> None:
        """Symlink at the read target -> empty result, no follow."""
        from bonfire.onboard.scanners import mcp_servers

        # Plant a regular target + a symlink pointing at it. The
        # _safe_resolve_config_path return is patched below so the symlink
        # is the literal value handed to the read helper, exercising the
        # post-resolve TOCTOU race shape.
        project = safe_tmp / "project"
        project.mkdir()
        target = project / "real.json"
        target.write_text(json.dumps({"mcpServers": {"x": {"command": "y"}}}))
        link = project / ".mcp.json"
        link.symlink_to(target)

        config = mcp_servers._ClientConfig(
            client_name="Test",
            path=link,
            scope="project",
        )

        async def _drive() -> list[tuple[str, dict]]:
            # Patch _safe_resolve_config_path to return the symlink itself,
            # simulating the TOCTOU race outcome (resolve returned a path
            # that the attacker then swapped to a symlink before read).
            with patch.object(mcp_servers, "_safe_resolve_config_path", return_value=link):
                return await mcp_servers._read_servers_from_config(
                    config, home_dir=safe_tmp, project_path=project
                )

        result = asyncio.run(_drive())
        # The defense-in-depth read MUST refuse the symlink. The reader
        # already swallows OSError into "skip" so the empty list is the
        # observable contract.
        assert result == []

    def test_symlink_refusal_caught_by_oserror_swallow(self, safe_tmp: Path) -> None:
        """``safe_read_capped_text`` raises FileExistsError; reader treats as skip.

        The existing reader's ``except (json.JSONDecodeError, OSError)``
        clause covers ``FileExistsError`` (subclass of ``OSError``). The
        contract: a symlink-at-read MUST NOT crash the scanner, MUST
        return the empty list, and MUST NOT leak the symlink target's
        bytes into the scan result.
        """
        from bonfire.onboard.scanners import mcp_servers

        project = safe_tmp / "project"
        project.mkdir()
        # Target carries a sentinel string we will assert is NOT in any
        # ScanUpdate the patched reader could surface.
        target = project / "secret.json"
        target.write_text(json.dumps({"mcpServers": {"leaked": {"command": "SHOULD_NOT_LEAK"}}}))
        link = project / ".mcp.json"
        link.symlink_to(target)

        config = mcp_servers._ClientConfig(
            client_name="Test",
            path=link,
            scope="project",
        )

        async def _drive() -> list[tuple[str, dict]]:
            with patch.object(mcp_servers, "_safe_resolve_config_path", return_value=link):
                return await mcp_servers._read_servers_from_config(
                    config, home_dir=safe_tmp, project_path=project
                )

        result = asyncio.run(_drive())
        # The empty list proves the bytes never reached json.loads.
        assert result == []


# ===========================================================================
# H2 — SessionPersistence boundary validation of session_id
# ===========================================================================


_ADVERSARIAL_SESSION_IDS = [
    "..",  # parent-traversal
    "../../etc/passwd",  # POSIX traversal
    "..\\..\\Windows",  # Windows-shape traversal
    "foo/bar",  # forward-slash separator
    "foo\\bar",  # backslash separator
    "/abs/path",  # absolute POSIX
    "C:\\path",  # absolute Windows
    "foo\x00bar",  # null-byte truncation
    "foo\nbar",  # newline injection
    "foo bar",  # space (outside allow-list)
    "a" * 65,  # over 64-char cap
    "foo.bar",  # dot (no extension smuggling)
    "//etc/passwd",  # double-slash adversarial
    "/Etc/Passwd",  # case-fold variant
    "%2e%2e%2fetc",  # URL-encoded ../etc
]


class TestH2SessionPersistenceValidatesSessionId:
    """Every public method on ``SessionPersistence`` that takes ``session_id``
    must reject path-traversal shapes at the class boundary — the same
    contract ``_validate_session_id`` enforces on ``BonfireEvent``.
    """

    @pytest.mark.parametrize("bad_id", _ADVERSARIAL_SESSION_IDS)
    def test_read_events_rejects(self, safe_tmp: Path, bad_id: str) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=safe_tmp)
        with pytest.raises(ValueError, match="session_id"):
            p.read_events(bad_id)

    @pytest.mark.parametrize("bad_id", _ADVERSARIAL_SESSION_IDS)
    def test_session_exists_rejects(self, safe_tmp: Path, bad_id: str) -> None:
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=safe_tmp)
        with pytest.raises(ValueError, match="session_id"):
            p.session_exists(bad_id)

    @pytest.mark.parametrize("bad_id", _ADVERSARIAL_SESSION_IDS)
    def test_append_event_rejects(self, safe_tmp: Path, bad_id: str) -> None:
        """``append_event`` takes a separate ``session_id`` argument plus the
        event; the class-boundary defense must reject the kwarg even when
        the event happens to carry a valid session_id of its own.
        """
        from bonfire.models.events import SessionStarted
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=safe_tmp)
        # Use a valid session_id INSIDE the event so the model-layer
        # validator passes; the class-boundary validator on the kwarg
        # is what we are exercising.
        event = SessionStarted(session_id="valid", sequence=0, task="t", workflow="w")
        with pytest.raises(ValueError, match="session_id"):
            p.append_event(bad_id, event)

    def test_empty_session_id_rejected_at_persistence_boundary(self, safe_tmp: Path) -> None:
        """``BonfireEvent.session_id == ""`` is the outside-session sentinel
        (allowed by the model validator for ``AxiomLoaded``). At the
        persistence boundary, empty ``session_id`` would produce
        ``.jsonl`` as the filename — a write to the parent directory's
        ``.jsonl`` — which is meaningless. Persistence rejects empty
        explicitly even though the model allows it.
        """
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=safe_tmp)
        with pytest.raises(ValueError, match="session_id"):
            p.read_events("")

    @pytest.mark.parametrize(
        "good_id",
        ["sess-1", "abcdef012345", "session_under_attack", "a", "a" * 64],
    )
    def test_legitimate_session_id_still_works(self, safe_tmp: Path, good_id: str) -> None:
        """Positive path: valid session_id shapes still round-trip cleanly."""
        from bonfire.models.events import SessionStarted
        from bonfire.session import SessionPersistence

        p = SessionPersistence(session_dir=safe_tmp)
        event = SessionStarted(session_id=good_id, sequence=0, task="t", workflow="w")
        p.append_event(good_id, event)
        assert p.session_exists(good_id)
        events = p.read_events(good_id)
        assert len(events) == 1


# ===========================================================================
# M1 — config_generator.load_tools_config TOCTOU
# ===========================================================================


class TestM1LoadToolsConfigRefusesSymlink:
    """``load_tools_config`` must read via ``safe_read_capped_text`` so the
    ``O_NOFOLLOW`` defense closes the TOCTOU window between the
    ``is_symlink()`` pre-check and the bytes read.

    The pre-check alone produces the observable "returns ``{}``" behavior
    today, so a pure end-to-end test cannot distinguish "pre-check
    refuses" from "defense-in-depth refuses". The contract this test
    pins is at the implementation layer: the module MUST import and call
    ``safe_read_capped_text`` (or pass through it) at the read site.
    """

    def test_module_imports_safe_read_helper(self) -> None:
        """``config_generator`` MUST import ``safe_read_capped_text`` from
        ``bonfire._safe_read`` — the defense-in-depth read primitive.
        """
        from bonfire.onboard import config_generator

        # The helper must be accessible at the module level so the read
        # site can call it. Either re-exported by name or referenced via
        # the source module — either shape satisfies the contract.
        source = Path(config_generator.__file__).read_text()
        assert "safe_read_capped_text" in source, (
            "config_generator must use safe_read_capped_text at the "
            "tools.local.toml read site (W11 defense-in-depth gap)."
        )

    def test_symlink_at_tools_local_skipped(self, safe_tmp: Path) -> None:
        from bonfire.onboard.config_generator import load_tools_config

        project = safe_tmp / "project"
        bonfire_dir = project / ".bonfire"
        bonfire_dir.mkdir(parents=True)

        # Plant attacker target outside the project + symlink to it.
        target = safe_tmp / "secret.toml"
        target.write_text('[bonfire.tools]\ndetected = ["LEAKED"]\n')
        link = bonfire_dir / "tools.local.toml"
        link.symlink_to(target)

        result = load_tools_config(project)
        # Refusal returns {} (matches the "absent" path so the operator
        # cannot distinguish via return value — this is the metadata
        # side-channel close documented in the reader).
        assert result == {}

    def test_symlink_refusal_does_not_leak_target_bytes(self, safe_tmp: Path) -> None:
        """A symlinked tools.local.toml MUST NOT surface the target's bytes
        in the return value — not via key, not via value, not via raise.
        """
        from bonfire.onboard.config_generator import load_tools_config

        project = safe_tmp / "project"
        bonfire_dir = project / ".bonfire"
        bonfire_dir.mkdir(parents=True)

        target = safe_tmp / "decoy.toml"
        target.write_text('[bonfire.tools]\ndetected = ["DO_NOT_LEAK"]\n')
        link = bonfire_dir / "tools.local.toml"
        link.symlink_to(target)

        result = load_tools_config(project)
        # No leakage at any depth.
        as_str = json.dumps(result, default=str)
        assert "DO_NOT_LEAK" not in as_str

    def test_legitimate_tools_local_still_loads(self, safe_tmp: Path) -> None:
        """Positive path: a regular (non-symlink) tools.local.toml still
        parses through the safe-read primitive.
        """
        from bonfire.onboard.config_generator import load_tools_config

        project = safe_tmp / "project"
        bonfire_dir = project / ".bonfire"
        bonfire_dir.mkdir(parents=True)
        toml_path = bonfire_dir / "tools.local.toml"
        toml_path.write_text('[bonfire.tools]\ndetected = ["git", "python3"]\n')

        result = load_tools_config(project)
        assert result == {"detected": ["git", "python3"]}


# ===========================================================================
# M2 — cli/commands/init.py 3 raw reads after is_symlink
# ===========================================================================


class TestM2InitReadsRefuseSymlinks:
    """``bonfire init`` performs 3 raw reads after ``is_symlink`` pre-checks.
    Each MUST route through a defense-in-depth helper so a TOCTOU race
    cannot smuggle a symlinked path past the pre-check.

    Read sites (per Wave 11 audit):
      1. ``gitignore_path.read_text()`` in ``_ensure_gitignore_entry``
         — existing-content scan for idempotent append.
      2. ``toml_path.read_text(encoding="utf-8")`` in
         ``_has_legacy_tools_section`` — legacy-section detection.
      3. ``gitignore_path.read_text()`` in ``init`` — pre-existence
         line detection for stdout reporting.

    The pre-checks already produce the visible "abort" behavior; the
    TOCTOU gap is invisible end-to-end. We pin the implementation
    contract by source-grep — the module MUST reference
    ``safe_read_capped_text`` at every post-check read site. The
    integration tests then verify the operator-facing behavior is
    preserved.
    """

    def test_module_imports_safe_read_helper(self) -> None:
        """``init`` module MUST import ``safe_read_capped_text`` and call
        it at the 3 read sites (per W11 audit). A source-grep is the
        cheapest invariant that distinguishes "raw read_text after
        is_symlink pre-check" (defect) from "safe-read after pre-check"
        (defense-in-depth).
        """
        from bonfire.cli.commands import init as init_mod

        source = Path(init_mod.__file__).read_text()
        assert "safe_read_capped_text" in source, (
            "init.py must use safe_read_capped_text at the 3 post-is_symlink "
            "read sites (W11 defense-in-depth gap)."
        )
        # Raw ``.read_text()`` MUST NOT appear at the 3 protected sites.
        # We can't easily AST-grep without overkill — pin the absence of
        # the raw call shape at module-level (the only legitimate
        # post-fix uses must go through the safe-read helper).
        assert ".read_text(" not in source, (
            "init.py must not call raw Path.read_text() at the post-"
            "is_symlink read sites; route through safe_read_capped_text."
        )

    def test_ensure_gitignore_entry_refuses_symlinked_existing(self, safe_tmp: Path) -> None:
        """When ``.gitignore`` exists AND is a symlink, the pre-check
        rejects with ``typer.Exit``. This pins the surface visible to
        operators: a symlinked .gitignore aborts init cleanly.
        """
        import typer

        from bonfire.cli.commands.init import _ensure_gitignore_entry

        # Plant a regular target + symlinked .gitignore pointing at it.
        target = safe_tmp / "regular.txt"
        target.write_text("decoy\n")
        link = safe_tmp / ".gitignore"
        link.symlink_to(target)

        with pytest.raises(typer.Exit):
            _ensure_gitignore_entry(safe_tmp, ".bonfire/tools.local.toml")

    def test_has_legacy_tools_section_refuses_symlink(self, safe_tmp: Path) -> None:
        """``_has_legacy_tools_section`` already short-circuits on symlinks
        (returns False) but the post-check ``read_text`` is the defense-in-
        depth gap. Pin the current contract: symlink at toml_path returns
        False, never reads the target.
        """
        from bonfire.cli.commands.init import _has_legacy_tools_section

        target = safe_tmp / "real.toml"
        target.write_text("[bonfire.tools]\ndetected = []\n")
        link = safe_tmp / "bonfire.toml"
        link.symlink_to(target)

        # Pre-check refuses; even if it were bypassed, the safe-read
        # helper enforces the same refusal via O_NOFOLLOW.
        assert _has_legacy_tools_section(link) is False

    def test_init_aborts_on_symlinked_gitignore(self, safe_tmp: Path) -> None:
        """Integration: ``bonfire init`` aborts when ``.gitignore`` exists
        as a symlink at the target directory. Combines the read-site
        defense with the existing CLI surface contract.
        """
        from typer.testing import CliRunner

        from bonfire.cli.app import app

        target_dir = safe_tmp / "proj"
        target_dir.mkdir()
        decoy = safe_tmp / "decoy.txt"
        decoy.write_text("not the real gitignore\n")
        (target_dir / ".gitignore").symlink_to(decoy)

        runner = CliRunner()
        result = runner.invoke(app, ["init", str(target_dir)])
        assert result.exit_code == 1
        assert "symlink" in result.output.lower()

    def test_init_aborts_on_symlinked_bonfire_toml(self, safe_tmp: Path) -> None:
        """A symlinked bonfire.toml triggers the existing refusal branch
        in init.py. The legacy-tools detection runs BEFORE that refusal,
        so the safe-read on toml_path must also not follow the symlink.
        """
        from typer.testing import CliRunner

        from bonfire.cli.app import app

        target_dir = safe_tmp / "proj"
        target_dir.mkdir()
        decoy = safe_tmp / "decoy.toml"
        decoy.write_text("[bonfire.tools]\ndetected = []\n")
        (target_dir / "bonfire.toml").symlink_to(decoy)

        runner = CliRunner()
        result = runner.invoke(app, ["init", str(target_dir)])
        # init refuses symlinked bonfire.toml; whichever symlink branch
        # fires (legacy-detect read OR final write-guard), the contract
        # is: exit_code != 0 and "symlink" in output.
        assert result.exit_code == 1
        assert "symlink" in result.output.lower()


# ===========================================================================
# M3 — cli/commands/persona.py raw read after is_symlink
# ===========================================================================


class TestM3PersonaReadRefusesSymlink:
    """``persona set`` reads bonfire.toml content (echoed back through
    ``re.sub`` into the subsequent ``safe_write_text``). The pre-check on
    line 97 catches the symlink today; the post-check ``read_text`` is the
    defense-in-depth gap. Pin the current refusal AND require it to flow
    through the safe-read helper.
    """

    def test_module_imports_safe_read_helper(self) -> None:
        """``persona`` command module MUST use ``safe_read_capped_text`` at
        the post-is_symlink read site.
        """
        from bonfire.cli.commands import persona as persona_mod

        source = Path(persona_mod.__file__).read_text()
        assert "safe_read_capped_text" in source, (
            "persona.py must use safe_read_capped_text at the post-"
            "is_symlink read site (W11 defense-in-depth gap)."
        )
        # Raw ``.read_text(`` at the post-check site must be gone. The
        # only remaining read on bonfire.toml is via ``open("rb")`` inside
        # ``_get_active_persona`` (a separate function with its own
        # symlink handling) — count its occurrences directly.
        # After fix: 0 occurrences of ``.read_text(`` at module level.
        assert ".read_text(" not in source, (
            "persona.py must not call raw Path.read_text() at the post-"
            "is_symlink read site; route through safe_read_capped_text."
        )

    def test_persona_set_aborts_on_symlinked_toml(self, safe_tmp: Path) -> None:
        """Integration: ``persona set`` exits non-zero on symlinked toml."""
        from typer.testing import CliRunner

        from bonfire.cli.app import app

        # Run in a tmp cwd so ``Path.cwd() / 'bonfire.toml'`` resolves
        # against our planted symlink.
        decoy = safe_tmp / "decoy.toml"
        decoy.write_text('[bonfire]\npersona = "decoy"\n')
        link = safe_tmp / "bonfire.toml"
        link.symlink_to(decoy)

        runner = CliRunner()

        # ``CliRunner`` doesn't override cwd; patch ``Path.cwd``.
        with patch(
            "bonfire.cli.commands.persona.Path.cwd",
            return_value=safe_tmp,
        ):
            result = runner.invoke(app, ["persona", "set", "falcor"])
        assert result.exit_code == 1
        assert "symlink" in result.output.lower()


# ===========================================================================
# M4 — git/scratch.ScratchWorktreeContext prefix validation
# ===========================================================================


@pytest.fixture()
def _tmp_git_repo(safe_tmp: Path) -> Path:
    """Minimal git repo with one commit on master (mirrors test_scratch_worktree)."""

    def _run(*cmd: str) -> None:
        subprocess.run(cmd, cwd=str(safe_tmp), check=True, capture_output=True)

    _run("git", "init", "-b", "master")
    _run("git", "config", "user.email", "test@test.com")
    _run("git", "config", "user.name", "Test")
    (safe_tmp / "README.md").write_text("# scratch test\n")
    _run("git", "add", ".")
    _run("git", "commit", "-m", "initial")
    return safe_tmp


class TestM4ScratchWorktreePrefixValidation:
    """``ScratchWorktreeFactory.acquire(prefix=...)`` must reject hostile
    prefixes. Current code interpolates ``prefix`` into both the branch
    name (``bonfire/{prefix}-pr-...``) and the path
    (``<repo>/.bonfire-worktrees/{prefix}/...``) without validation.

    Hostile shapes (must reject):
      - ``"../escape"`` — parent-traversal lands outside ``.bonfire-worktrees/``
      - ``"foo/bar"`` — separator carves an arbitrary subdir + breaks branch
      - ``"-leading-dash"`` — git-flag injection on later ``git`` calls
      - ``""`` — empty string produces a ``bonfire/-pr-...`` branch + a
        ``.bonfire-worktrees//pr-...`` path (degenerate but still bad)
      - ``"foo\\0bar"`` — null byte truncates downstream calls
      - ``"foo\\nbar"`` — newline injection
      - ``"foo bar"`` — space is shell-meaningful in some downstream uses

    Legitimate shapes (must accept):
      - ``"preflight"`` (the default)
      - ``"valid-prefix"`` with hyphens and underscores
    """

    @pytest.mark.parametrize(
        "bad_prefix",
        [
            "../escape",
            "..",
            "foo/bar",
            "/abs",
            "-leading-dash",
            "",
            "foo\x00bar",
            "foo\nbar",
            "foo bar",
            "..foo",
            "foo/../bar",
            ".",
            "foo\\bar",  # backslash separator (Windows-shape)
        ],
    )
    def test_acquire_rejects_hostile_prefix(self, _tmp_git_repo: Path, bad_prefix: str) -> None:
        from bonfire.git.scratch import ScratchWorktreeFactory

        factory = ScratchWorktreeFactory(repo_path=_tmp_git_repo)
        with pytest.raises(ValueError, match="prefix"):
            factory.acquire(base_ref="master", pr_number=1, prefix=bad_prefix)

    @pytest.mark.parametrize(
        "good_prefix",
        ["preflight", "valid-prefix", "valid_prefix", "scratch1", "a"],
    )
    def test_acquire_accepts_legitimate_prefix(self, _tmp_git_repo: Path, good_prefix: str) -> None:
        """The validator must NOT reject the default ``preflight`` prefix
        or any reasonable identifier-shape replacement.
        """
        from bonfire.git.scratch import ScratchWorktreeFactory

        factory = ScratchWorktreeFactory(repo_path=_tmp_git_repo)
        # No raise — return a context manager.
        ctx = factory.acquire(base_ref="master", pr_number=1, prefix=good_prefix)
        assert hasattr(ctx, "__aenter__")
