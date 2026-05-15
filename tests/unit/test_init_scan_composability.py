# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire init . && bonfire scan`` composes cleanly.

The prior ``write_config`` / ``scan`` overwrite-guard fires on
*every* pre-existing ``bonfire.toml`` — including the empty stub that
``bonfire init`` writes one command earlier. The README quickstart
(``bonfire init . && bonfire scan``) therefore exits 1 every time.

The fix introduces a single shared predicate, ``_is_init_stub``,
module-private in ``bonfire.onboard.config_generator``. Both the
CLI fail-fast path (``scan.py`` lines 105-112) and the writer
defense-in-depth (``write_config`` at lines 408-433) consult it so
they cannot drift. A "stub" is byte-for-byte the exact output of
``bonfire init``: ``b"[bonfire]\\n"`` (10 bytes), with only trailing
ASCII whitespace tolerated.

The predicate MUST:
  - return False on symlinks (the broader O_NOFOLLOW story is owned
    by the symlink-reject change);
  - return False on non-regular files (FIFOs, directories);
  - return False on files > 64 bytes (defense-in-depth size gate that
    short-circuits BEFORE any ``read_bytes`` call);
  - return True ONLY for content whose right-stripped form equals
    ``b"[bonfire]"`` — i.e. the exact stub plus optional trailing
    whitespace.

The integration smoke at the bottom (test #14) is the long-term
defense against the regression that motivated this change: ``init``
then ``scan`` must compose end-to-end. Test #15 pins that a user
customization between the two commands is preserved.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app
from bonfire.onboard.config_generator import write_config

runner = CliRunner()


def _load_predicate():
    """Lazy-import ``_is_init_stub`` so RED-phase predicate tests fail
    per-test (with a clear ImportError naming the missing symbol) rather
    than collapsing the entire module at collection time. The pre-existing
    overwrite-guard smoke tests (#11, #13, #15) do NOT depend on the
    predicate and must remain PASS today.

    The implementation adds ``_is_init_stub`` as a module-private helper
    next to ``write_config`` in ``bonfire.onboard.config_generator``.
    """
    from bonfire.onboard import config_generator

    try:
        return config_generator._is_init_stub
    except AttributeError as exc:
        raise ImportError(
            "cannot import name '_is_init_stub' from "
            "'bonfire.onboard.config_generator' — the predicate has "
            "not been implemented yet"
        ) from exc


# The exact byte string ``bonfire init`` writes today (init.py line 22).
# Pinned here so test #1 fails CI the day someone changes init's output
# without updating ``INIT_STUB_BYTES`` in config_generator.
EXPECTED_INIT_BYTES = b"[bonfire]\n"


# ---------------------------------------------------------------------------
# Predicate tests (#1 - #9) — drive ``_is_init_stub`` directly.
# ---------------------------------------------------------------------------


@pytest.fixture
def _is_init_stub():
    """Resolve the predicate once per test.

    RED state today: ``_load_predicate`` raises ImportError naming the
    missing symbol. Each predicate test thus fails at the fixture-resolve
    step, with a clear "predicate doesn't exist yet" message.
    """
    return _load_predicate()


class TestIsInitStubPredicate:
    """``_is_init_stub`` distinguishes init's exact stub from anything else."""

    def test_is_init_stub_matches_exact_init_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _is_init_stub,
    ) -> None:
        """#1 — Predicate returns True for the file ``bonfire init`` actually writes.

        Run ``bonfire init .`` via CliRunner into a clean tmp_path, then
        assert ``_is_init_stub`` agrees that the resulting ``bonfire.toml``
        IS a stub. This is the load-bearing pin: the predicate must
        stay synchronized with init's real output, byte for byte.
        """
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(app, ["init", "."])
        assert result.exit_code == 0, (
            f"init must succeed; got exit_code={result.exit_code}, output={result.output!r}"
        )

        toml_path = tmp_path / "bonfire.toml"
        assert toml_path.exists(), "init must have created bonfire.toml"

        # Sanity: init's byte output matches the constant we pin against.
        assert toml_path.read_bytes() == EXPECTED_INIT_BYTES, (
            f"init's byte output drifted from b'[bonfire]\\n'; got "
            f"{toml_path.read_bytes()!r}. Update INIT_STUB_BYTES in "
            f"config_generator AND this test."
        )

        assert _is_init_stub(toml_path) is True, (
            "predicate must recognize init's exact byte-for-byte output as a stub"
        )

    def test_is_init_stub_tolerates_trailing_newline(
        self, tmp_path: Path, _is_init_stub
    ) -> None:
        """#2 — Predicate tolerates an editor adding a trailing newline / CRLF.

        Two benign normalizations: a Windows checkout adding ``\\r\\n``
        and an editor that appends a final newline. Neither is a user
        customization; both must read as stub.
        """
        toml_path = tmp_path / "bonfire.toml"

        toml_path.write_bytes(b"[bonfire]\n\n")
        assert _is_init_stub(toml_path) is True, (
            "predicate must tolerate an extra trailing newline (editor convention)"
        )

        toml_path.write_bytes(b"[bonfire]\n\r\n")
        assert _is_init_stub(toml_path) is True, (
            "predicate must tolerate trailing CRLF (Windows checkout)"
        )

        toml_path.write_bytes(b"[bonfire]\n   \t  \n")
        assert _is_init_stub(toml_path) is True, (
            "predicate must tolerate trailing ASCII whitespace"
        )

    def test_is_init_stub_rejects_one_added_key(
        self, tmp_path: Path, _is_init_stub
    ) -> None:
        """#3 — A single added key means the user has customized; NOT a stub.

        Headline test: one ``name = "demo"`` line is enough to fall out
        of the stub-overwrite exception and back into the overwrite guard.
        """
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(b'[bonfire]\nname = "demo"\n')

        assert _is_init_stub(toml_path) is False, (
            "predicate must refuse a stub-plus-one-key file as user-customized"
        )

    def test_is_init_stub_rejects_added_comment(
        self, tmp_path: Path, _is_init_stub
    ) -> None:
        """#4 — A leading comment is a user customization; NOT a stub.

        Same intent as #3, but the customization is a comment line the
        user pasted above the section header.
        """
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(b"# hand-tuned\n[bonfire]\n")

        assert _is_init_stub(toml_path) is False, (
            "predicate must refuse a leading-comment file as user-customized"
        )

    def test_is_init_stub_rejects_added_section(
        self, tmp_path: Path, _is_init_stub
    ) -> None:
        """#5 — A second section means past the stub stage; NOT a stub."""
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(b'[bonfire]\n[bonfire.git]\nremote = "origin"\n')

        assert _is_init_stub(toml_path) is False, (
            "predicate must refuse a file with an additional subsection"
        )

    def test_is_init_stub_rejects_oversize_file(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        _is_init_stub,
    ) -> None:
        """#6 — Predicate rejects files > 64 bytes WITHOUT reading them whole.

        Defense-in-depth: a malicious or adversarial input must not be
        slurped via ``read_bytes`` to check stub-ness. The size gate fires
        on ``stat()``, BEFORE any byte read. We instrument ``read_bytes``
        on the Path object to assert it's never called for an oversize
        file.
        """
        toml_path = tmp_path / "bonfire.toml"
        # 1 MiB file starting with the stub bytes; whole-file slurp would
        # be a real cost on adversarial input.
        payload = EXPECTED_INIT_BYTES + b"x" * (1024 * 1024 - len(EXPECTED_INIT_BYTES))
        toml_path.write_bytes(payload)
        assert toml_path.stat().st_size > 64

        # Instrument Path.read_bytes class-wide; if the size gate fires
        # first, the predicate never reaches it. (Patching the unbound
        # method on the class catches both ``path.read_bytes()`` and
        # any direct ``Path.read_bytes(path)`` form.)
        called = {"count": 0}
        original_read_bytes = Path.read_bytes

        def tracking_read_bytes(self: Path) -> bytes:
            called["count"] += 1
            return original_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", tracking_read_bytes)

        result = _is_init_stub(toml_path)

        assert result is False, (
            "predicate must refuse a > 64-byte file regardless of leading bytes"
        )
        assert called["count"] == 0, (
            f"size gate must short-circuit BEFORE read_bytes; "
            f"got read_bytes call count = {called['count']}"
        )

    def test_is_init_stub_refuses_to_follow_symlinks(
        self, tmp_path: Path, _is_init_stub
    ) -> None:
        """#7 — Symlinks return False even when the target is byte-perfect.

        The broader O_NOFOLLOW write-defense story is owned by the
        symlink-reject change. This predicate MUST NOT widen the attack
        surface by following symlinks. Pin: even when the symlink target
        contains the exact stub bytes, the predicate refuses.
        """
        # Real stub file lives in tmp_path; the bonfire.toml path is a
        # symlink to it. Both endpoints stay under tmp_path — never
        # point a symlink at a real system file.
        real_target = tmp_path / "real_stub.toml"
        real_target.write_bytes(EXPECTED_INIT_BYTES)

        link_path = tmp_path / "bonfire.toml"
        link_path.symlink_to(real_target)

        # Sanity: the symlink resolves to byte-perfect content.
        assert link_path.read_bytes() == EXPECTED_INIT_BYTES
        assert link_path.is_symlink()

        assert _is_init_stub(link_path) is False, (
            "predicate must refuse symlinks even when the target is the exact stub"
        )

    def test_is_init_stub_refuses_dangling_symlink(
        self, tmp_path: Path, _is_init_stub
    ) -> None:
        """#8 — A dangling symlink returns False without raising.

        Pairs with the O_NOFOLLOW work in the adjacent symlink-reject
        change — the predicate must not probe a broken target.
        ``is_symlink`` returns True even when the target is missing,
        so the short-circuit fires first.
        """
        nonexistent_target = tmp_path / "does_not_exist.toml"
        link_path = tmp_path / "bonfire.toml"
        link_path.symlink_to(nonexistent_target)

        assert link_path.is_symlink()
        assert not nonexistent_target.exists()

        # Must NOT raise (no FileNotFoundError, no OSError leaking out).
        assert _is_init_stub(link_path) is False, (
            "predicate must refuse a dangling symlink without raising"
        )

    def test_is_init_stub_refuses_non_regular_file(
        self, tmp_path: Path, _is_init_stub
    ) -> None:
        """#9 — Directory at the bonfire.toml path returns False, no raise.

        A directory entry where a regular file is expected must be
        refused cleanly (no IsADirectoryError leak). The S_ISREG check
        catches this and any FIFOs / device nodes.
        """
        dir_at_toml_path = tmp_path / "bonfire.toml"
        dir_at_toml_path.mkdir()

        assert dir_at_toml_path.is_dir()

        # Must NOT raise (no IsADirectoryError, no OSError leaking out).
        assert _is_init_stub(dir_at_toml_path) is False, (
            "predicate must refuse a directory at the target path without raising"
        )


# ---------------------------------------------------------------------------
# Writer / CLI integration (#10 - #13) — predicate plumbed into write_config
# and into the scan CLI fail-fast guard.
# ---------------------------------------------------------------------------


class TestWriteConfigOverwriteStub:
    """``write_config`` overwrites the init stub; preserves user content."""

    def test_write_config_overwrites_init_stub(self, tmp_path: Path) -> None:
        """#10 — write_config replaces an exact init stub with the new TOML.

        Place the byte-for-byte stub at the target; call ``write_config``;
        assert the file now contains the new content and NO FileExistsError
        was raised.
        """
        target = tmp_path / "bonfire.toml"
        target.write_bytes(EXPECTED_INIT_BYTES)

        new_toml = '[bonfire]\nname = "from-scan"\n'

        # Must NOT raise — stub is OK to overwrite.
        result = write_config(new_toml, tmp_path)

        assert result == target
        assert target.read_text() == new_toml, (
            "write_config must overwrite the init stub with the new content"
        )

    def test_write_config_refuses_overwrite_when_user_customized(
        self, tmp_path: Path
    ) -> None:
        """#11 — Prior overwrite guard preserved for user-customized content.

        This pin mirrors ``test_write_config_existing_bonfire_toml_raises``
        in ``test_scan_overwrite_guard.py``. The stub-only exception
        introduced here must NOT widen into a broader overwrite path.

        EXPECTED STATE TODAY: this passes — write_config already raises
        FileExistsError on any existing file. Smoke-check that the
        prior guard survives this change.
        """
        existing = tmp_path / "bonfire.toml"
        original = '# hand-tuned\n[bonfire]\nname = "keep-me"\n'
        existing.write_text(original)

        new_content = '[bonfire]\nname = "overwritten"\n'

        with pytest.raises(FileExistsError):
            write_config(new_content, tmp_path)

        # Existing content untouched.
        assert existing.read_text() == original, (
            "write_config must not modify the user-customized bonfire.toml when refusing"
        )

    def test_scan_cli_overwrites_init_stub(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """#12 — ``bonfire scan`` proceeds past the guard when only a stub exists.

        Write the exact init stub in tmp_path, chdir there, invoke
        ``bonfire scan --no-browser`` with ``_run_scan`` mocked. Assert
        exit_code == 0 AND mock_run IS called (scan proceeded into the
        server flow rather than fail-fast'ing on the stub).
        """
        existing = tmp_path / "bonfire.toml"
        existing.write_bytes(EXPECTED_INIT_BYTES)
        monkeypatch.chdir(tmp_path)

        with patch(
            "bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code == 0, (
            f"scan must succeed when only an init stub is present; "
            f"got exit_code={result.exit_code}, output={result.output!r}"
        )
        assert mock_run.called, (
            "scan must proceed into _run_scan when bonfire.toml is just the init stub"
        )

    def test_scan_cli_refuses_when_user_customized_toml(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """#13 — User-customized bonfire.toml still triggers the fail-fast guard.

        Mirrors ``test_scan_with_existing_bonfire_toml_exits_nonzero`` in
        ``test_scan_overwrite_guard.py``. This change must NOT regress
        the prior fail-fast surface for the user-customized case.

        EXPECTED STATE TODAY: this passes — the existing guard catches
        every non-empty exists() case, including user-customized.
        """
        existing = tmp_path / "bonfire.toml"
        original = '# hand-tuned\n[bonfire]\nname = "keep-me"\n'
        existing.write_text(original)
        monkeypatch.chdir(tmp_path)

        with patch(
            "bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = None
            result = runner.invoke(app, ["scan", "--no-browser"])

        assert result.exit_code != 0, (
            f"scan must exit non-zero when bonfire.toml is user-customized; "
            f"got exit_code={result.exit_code}, output={result.output!r}"
        )
        assert not mock_run.called, (
            "scan must fail BEFORE _run_scan when bonfire.toml is user-customized"
        )
        assert existing.read_text() == original


# ---------------------------------------------------------------------------
# Integration smoke (#14, #15) — the README quickstart, end to end.
# ---------------------------------------------------------------------------


class TestQuickstartIntegration:
    """``bonfire init . && bonfire scan`` is the README's day-1 contract.

    This is THE regression-pin against the overwrite-guard defect family.
    If a future write-side guard ever fires on init's own output, test #14
    catches it before the README breaks.
    """

    def test_quickstart_full_flow_init_then_scan(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """#14 — README quickstart composes: init then scan, both exit 0.

        Clean tmp_path → ``bonfire init <tmp_path>`` (stub created, exit 0)
        → chdir to tmp_path → ``bonfire scan --no-browser`` (proceeds
        past the guard, exit 0). The pin against the overwrite-guard regression.
        """
        # Step 1: init. Pass tmp_path explicitly so we don't depend on
        # cwd here; the init command writes to its argument target.
        result_init = runner.invoke(app, ["init", str(tmp_path)])
        assert result_init.exit_code == 0, (
            f"init must succeed; got exit_code={result_init.exit_code}, "
            f"output={result_init.output!r}"
        )

        toml_path = tmp_path / "bonfire.toml"
        assert toml_path.exists(), "init must have created bonfire.toml"
        assert toml_path.read_bytes() == EXPECTED_INIT_BYTES, (
            "init must have written the exact stub bytes"
        )

        # Step 2: scan. chdir so scan's cwd-based bonfire.toml lookup
        # finds the stub. Mock _run_scan so we don't bind a real socket.
        monkeypatch.chdir(tmp_path)
        with patch(
            "bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = None
            result_scan = runner.invoke(app, ["scan", "--no-browser"])

        assert result_scan.exit_code == 0, (
            f"scan must succeed after init (README quickstart); "
            f"got exit_code={result_scan.exit_code}, output={result_scan.output!r}, "
            f"stderr={result_scan.stderr if result_scan.stderr_bytes else ''!r}"
        )
        assert mock_run.called, (
            "scan must proceed into _run_scan after init's stub — the init-stub contract"
        )

    def test_quickstart_full_flow_preserves_user_edits_after_init(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """#15 — User edits between init and scan are preserved.

        ``init`` writes the stub. User adds a key. ``scan`` MUST exit 1
        — the stub-only exception does not regress into a broad
        overwrite. The prior overwrite guard fires on the customized file.

        EXPECTED STATE TODAY: this passes — the existing guard catches
        every non-empty exists() case, which includes "stub plus one
        user-added key". Smoke-check that this change does not regress it.
        """
        # Step 1: init.
        result_init = runner.invoke(app, ["init", str(tmp_path)])
        assert result_init.exit_code == 0

        # Step 2: user hand-edits the stub.
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(b'[bonfire]\nname = "hand-tuned"\n')

        # Step 3: scan must refuse — file is no longer a stub.
        monkeypatch.chdir(tmp_path)
        with patch(
            "bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = None
            result_scan = runner.invoke(app, ["scan", "--no-browser"])

        assert result_scan.exit_code != 0, (
            f"scan must refuse when the user has edited the stub; "
            f"got exit_code={result_scan.exit_code}, output={result_scan.output!r}"
        )
        assert not mock_run.called, (
            "scan must fail BEFORE _run_scan when the stub has been customized"
        )
        # User edit preserved byte-for-byte.
        assert toml_path.read_bytes() == b'[bonfire]\nname = "hand-tuned"\n', (
            "scan must not modify a user-customized bonfire.toml on the refuse path"
        )
