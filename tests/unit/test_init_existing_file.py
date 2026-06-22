# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire init`` tailors its error when the target exists as a
non-directory, instead of leaking a raw Python ``FileExistsError`` traceback.

Every other operator-controlled write path in ``init.py`` (the symlinked
``bonfire.toml`` branch and the symlinked ``.gitignore`` branch) emits a
``typer.echo(..., err=True)`` + ``raise typer.Exit(code=1)``. The
``target.mkdir(parents=True, exist_ok=True)`` call previously did not — when
the operator pointed ``bonfire init`` at a path that exists as a regular
file, ``mkdir`` would raise ``FileExistsError`` and the traceback would
escape Typer to the terminal. The fix adds a guarded pre-check that mirrors
the existing symlink branches.

The dir-existing path (idempotent re-init into an existing empty directory)
must keep working.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from bonfire.cli.app import app

runner = CliRunner()


def test_init_refuses_existing_regular_file(tmp_path: Path) -> None:
    """``bonfire init <regular-file>`` exits 1 with a tailored message.

    Plant a regular file at ``tmp_path/blocker``, invoke ``bonfire init``
    against that path, assert the CLI exits non-zero and emits a clear
    message naming the path. The legacy behavior was a raw
    ``FileExistsError`` traceback — the assertion on the message body
    pins that the typer-echo branch fires.
    """
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory")

    result = runner.invoke(app, ["init", str(blocker)])

    assert result.exit_code == 1, (
        f"init must exit 1 when target is a regular file; "
        f"got exit_code={result.exit_code}, output={result.output!r}"
    )
    # CliRunner merges stderr into ``output`` by default; assert the
    # tailored message appears so we know the typer.echo branch ran
    # rather than a raw FileExistsError traceback leaking out.
    assert "exists and is not a directory" in result.output, (
        f"init must emit a tailored 'not a directory' message; got output={result.output!r}"
    )
    # Defense-in-depth: a leaked Python traceback would name the
    # exception class. The tailored branch must NOT raise FileExistsError.
    assert "FileExistsError" not in result.output, (
        f"init must not leak a raw FileExistsError traceback; got output={result.output!r}"
    )
    # The blocker file itself must not be touched.
    assert blocker.read_text() == "not a directory", (
        "init must not modify the blocker file when refusing"
    )


def test_init_succeeds_on_existing_empty_directory(tmp_path: Path) -> None:
    """``bonfire init <existing-empty-dir>`` still works (idempotent).

    The fix must NOT regress the existing-empty-directory path: that's
    the common idempotent re-init case (``mkdir(exist_ok=True)`` is
    intentional). Plant an empty directory, invoke ``bonfire init``
    against it, assert exit_code == 0 and the standard artefacts land.
    """
    target = tmp_path / "fresh_project"
    target.mkdir()
    assert target.is_dir() and not any(target.iterdir())

    result = runner.invoke(app, ["init", str(target)])

    assert result.exit_code == 0, (
        f"init must succeed on an existing empty directory; "
        f"got exit_code={result.exit_code}, output={result.output!r}"
    )
    # The standard init artefacts must all land.
    assert (target / "bonfire.toml").is_file(), "init must create bonfire.toml"
    assert (target / ".bonfire").is_dir(), "init must create .bonfire/"
    assert (target / "agents").is_dir(), "init must create agents/"
    assert (target / ".gitignore").is_file(), "init must create .gitignore"
