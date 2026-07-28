# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire init`` refuses hostile path shapes in words, not tracebacks.

``bonfire init`` is the first command a stranger runs after
``pip install bonfire-ai``, and every path it touches is one the operator
controls. Two failure classes on that path escaped as raw Python
exceptions or, worse, as a success claim.

**A permissions problem is an error-handling bug, not a permissions bug.**
Pointing ``bonfire init`` at a read-only directory reached
``safe_write_text`` and let ``PermissionError`` escape Typer to the
terminal as a traceback; the same held for a read-only ``.gitignore`` on
the append path.

**Existence is not shape.** ``Path.exists()`` answers "is there something
here", not "is there a *file* here". A directory named ``bonfire.toml``
satisfied the existence check, so the writer skipped it and the success
block announced ``Already present: bonfire.toml`` with exit code 0 — a
project no Bonfire command can read, reported as ready. The mirror
shapes (a directory at ``.gitignore``, a regular file at ``.bonfire/``
or ``agents/``, a dangling symlink at ``.bonfire/``) each raised a
different raw ``OSError``.

The control test at the bottom pins that the guards did not simply learn
to refuse everything.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from click.testing import Result
from typer.testing import CliRunner

from bonfire.cli.app import app

runner = CliRunner()

# ``chmod`` is advisory for root: a 0o555 directory is still writable by
# uid 0, so the read-only tests would exercise nothing. Skip rather than
# pass vacuously.
_ROOT = hasattr(os, "geteuid") and os.geteuid() == 0
_SKIP_ROOT = pytest.mark.skipif(_ROOT, reason="chmod is advisory for root")


def _assert_refused(result: Result, *, phrases: tuple[str, ...]) -> None:
    """Assert a typed refusal: exit 1, no traceback, no success claim.

    Three independent signals, because each alone can lie. The exit code
    says the shell was told; ``result.exception`` says the command ended
    at the Typer exit rather than at the underlying ``OSError``; the
    output says the operator was given words naming the path and the
    condition, and was NOT also told the project was initialised.
    """
    output = result.output
    exception = result.exception
    assert result.exit_code == 1, f"expected exit 1; got {result.exit_code}, output={output!r}"
    assert "Traceback" not in output, f"init leaked a Python traceback: {output!r}"
    assert not isinstance(exception, OSError), (
        f"init must convert the OS-level failure into a typed refusal; got {exception!r}"
    )
    assert "Initialized Bonfire project" not in output, (
        f"a refused init must not print the success banner: {output!r}"
    )
    assert "Already present" not in output, (
        f"a refused init must not claim an artefact is in place: {output!r}"
    )
    for phrase in phrases:
        assert phrase in output, f"refusal must mention {phrase!r}; got {output!r}"


@_SKIP_ROOT
def test_init_refuses_read_only_target_directory(tmp_path: Path) -> None:
    """A read-only target refuses in words: the failure lands on the first write.

    The directory exists and is a directory, so the target pre-check and
    ``mkdir(exist_ok=True)`` both pass. Pre-fix, the write that follows
    raised ``PermissionError`` straight past Typer.
    """
    target = tmp_path / "readonly"
    target.mkdir()
    target.chmod(0o555)
    try:
        result = runner.invoke(app, ["init", str(target)])
    finally:
        # Restore write permission so pytest's tmp_path cleanup works.
        target.chmod(0o755)

    _assert_refused(result, phrases=("bonfire.toml", "could not write", "Permission denied"))


@_SKIP_ROOT
def test_init_refuses_read_only_gitignore_on_append(tmp_path: Path) -> None:
    """A read-only ``.gitignore`` refuses on the append path.

    Distinct from the case above: the directory is writable, so init
    reaches ``_ensure_gitignore_entry`` and fails inside
    ``safe_append_text``.
    """
    target = tmp_path / "project"
    target.mkdir()
    gitignore = target / ".gitignore"
    gitignore.write_text("# user content\nnode_modules/\n")
    gitignore.chmod(0o444)
    try:
        result = runner.invoke(app, ["init", str(target)])
    finally:
        gitignore.chmod(0o644)

    _assert_refused(result, phrases=(".gitignore", "Permission denied"))
    assert gitignore.read_text() == "# user content\nnode_modules/\n", (
        "a refused append must not modify the operator's .gitignore"
    )


def test_init_refuses_directory_named_bonfire_toml(tmp_path: Path) -> None:
    """A DIRECTORY at ``bonfire.toml`` is refused, not reported as present.

    This is the shape that made init lie: ``exists()`` is True for a
    directory, the ``if not toml_path.exists()`` guard skipped the write,
    and the success block printed ``Already present: bonfire.toml
    (project config)`` with exit code 0.
    """
    target = tmp_path / "project"
    target.mkdir()
    (target / "bonfire.toml").mkdir()

    result = runner.invoke(app, ["init", str(target)])

    _assert_refused(result, phrases=("bonfire.toml", "not a regular file"))
    # The shape gate runs before any mutation: a refused init leaves the
    # directory exactly as it found it.
    assert (target / "bonfire.toml").is_dir(), "init must not touch the blocking directory"
    assert not (target / "agents").exists(), "init must refuse before creating agents/"
    assert not (target / ".gitignore").exists(), "init must refuse before creating .gitignore"


def test_init_refuses_directory_named_gitignore(tmp_path: Path) -> None:
    """A DIRECTORY at ``.gitignore`` is refused.

    Pre-fix this reached ``safe_read_capped_text``, whose ``os.fdopen``
    raised ``IsADirectoryError`` — a traceback naming a file descriptor.
    """
    target = tmp_path / "project"
    target.mkdir()
    (target / ".gitignore").mkdir()

    result = runner.invoke(app, ["init", str(target)])

    _assert_refused(result, phrases=(".gitignore", "not a regular file"))


def test_init_refuses_regular_file_at_bonfire_directory(tmp_path: Path) -> None:
    """A regular file at ``.bonfire`` is refused.

    Pre-fix ``bonfire_dir.mkdir(exist_ok=True)`` raised
    ``FileExistsError`` — ``exist_ok`` forgives an existing *directory*,
    not an existing file.
    """
    target = tmp_path / "project"
    target.mkdir()
    (target / ".bonfire").write_text("not a directory\n")

    result = runner.invoke(app, ["init", str(target)])

    _assert_refused(result, phrases=(".bonfire", "not a directory"))
    assert (target / ".bonfire").read_text() == "not a directory\n", (
        "init must not modify the blocking file when refusing"
    )


def test_init_refuses_regular_file_at_agents_directory(tmp_path: Path) -> None:
    """A regular file at ``agents`` is refused (same shape, second slot)."""
    target = tmp_path / "project"
    target.mkdir()
    (target / "agents").write_text("not a directory\n")

    result = runner.invoke(app, ["init", str(target)])

    _assert_refused(result, phrases=("agents", "not a directory"))


def test_init_refuses_dangling_symlink_at_bonfire_directory(tmp_path: Path) -> None:
    """A dangling symlink at ``.bonfire`` is refused.

    ``Path.exists()`` follows symlinks and returns False for a dangling
    one, so the pre-fix code fell through to ``mkdir(exist_ok=True)``,
    which raises ``FileExistsError`` on the link itself.
    """
    target = tmp_path / "project"
    target.mkdir()
    (target / ".bonfire").symlink_to(tmp_path / "nowhere")

    result = runner.invoke(app, ["init", str(target)])

    _assert_refused(result, phrases=("symlink",))


def test_init_still_succeeds_when_every_slot_is_the_right_shape(tmp_path: Path) -> None:
    """Control: correct shapes still initialise, including the partial case.

    Without this, a guard that refused unconditionally would pass every
    test above. The pre-seeded ``bonfire.toml`` file and ``.bonfire/``
    directory are the exact shapes the guards inspect and clear.
    """
    target = tmp_path / "project"
    target.mkdir()
    (target / "bonfire.toml").write_text("[bonfire]\n")
    (target / ".bonfire").mkdir()

    result = runner.invoke(app, ["init", str(target)])

    assert result.exit_code == 0, f"init must succeed; output={result.output!r}"
    assert "Initialized Bonfire project" in result.output
    assert (target / "bonfire.toml").is_file()
    assert (target / ".bonfire").is_dir()
    assert (target / "agents").is_dir()
    assert (target / ".gitignore").is_file()
