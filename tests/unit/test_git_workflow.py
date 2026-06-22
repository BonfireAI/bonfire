"""RED tests for bonfire.git.workflow._run_git error redaction — BON-913.

Wave-2 leak hardening. Surfaced by the Mirror Path B production-1 run on
2026-05-07 (Security Scout, finding #8). Adjacent to BON-897 (SDK-backend
traceback redaction, PR #72 merged) — this is one of the surfaces feeding
that hazard.

``git/workflow.py`` ``_run_git`` currently raises, on non-zero git exit::

    RuntimeError(
        f"git command failed (exit {proc.returncode}): "
        f"git {' '.join(args)}\\n{stderr.decode().strip()}"
    )

The wrapper joins ALL args — including ``commit -m "<message>"`` — into the
RuntimeError. ``_do_execute`` in ``sdk_backend.py`` then captures that into a
traceback envelope persisted as JSONL. Commit messages can carry user content
from prior agent stages, so this leaks them into long-lived error artifacts.

These tests pin the intended post-fix behaviour (per AC):

  * Default: the RuntimeError message includes only the git subcommand name
    + exit code — NOT the full arg list, NOT stderr.
  * Opt-in: a ``verbose: bool = False`` parameter on ``_run_git`` restores the
    full message + stderr for callers that explicitly need it.

RED expectation: the current implementation always interpolates the full
``' '.join(args)`` and stderr, so the secret-bearing commit message and
stderr content leak into the default-path RuntimeError — the redaction
assertions fail.
"""

from __future__ import annotations

import asyncio

import pytest

from bonfire.git.workflow import _run_git

# A secret-looking string planted in a commit message / arg list. It must
# never appear in the *default* RuntimeError message.
_SECRET = "secret-content-XYZ-do-not-leak"


def _init_repo(path) -> None:
    """Initialise an empty git repo at *path* (no commits, no identity)."""
    asyncio.get_event_loop()  # touch loop; subprocess calls happen in-test
    import subprocess

    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)


async def test_failed_commit_does_not_leak_message_by_default(tmp_path) -> None:
    """A failed ``git commit -m <secret>`` raises a RuntimeError WITHOUT the secret.

    ``git commit`` in a repo with no staged changes / no identity exits
    non-zero; ``_run_git`` raises. The default error message must not echo
    the commit message back.
    """
    _init_repo(tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        # Nothing staged + no user.email/user.name configured -> non-zero exit.
        await _run_git(tmp_path, "commit", "-m", _SECRET)

    message = str(excinfo.value)
    assert _SECRET not in message, (
        "the commit message leaked into the default RuntimeError — it would be "
        f"persisted into session JSONL via the SDK-backend traceback envelope: {message!r}"
    )


async def test_failed_commit_does_not_leak_full_arg_list_by_default(tmp_path) -> None:
    """The default RuntimeError must not echo the whole joined arg list."""
    _init_repo(tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        await _run_git(tmp_path, "commit", "-m", _SECRET)

    message = str(excinfo.value)
    # The "-m" flag plus the message body is the arg-list leak signature.
    assert "-m" not in message, (
        f"the full git arg list leaked into the default RuntimeError: {message!r}"
    )


async def test_default_error_names_subcommand_and_exit_code(tmp_path) -> None:
    """The default RuntimeError still names the subcommand + exit code (useful, not silent)."""
    _init_repo(tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        await _run_git(tmp_path, "commit", "-m", _SECRET)

    message = str(excinfo.value)
    assert "commit" in message, (
        f"the redacted RuntimeError should still name the git subcommand: {message!r}"
    )
    assert "exit" in message.lower(), (
        f"the redacted RuntimeError should still report the exit code: {message!r}"
    )


async def test_verbose_opt_in_restores_full_message(tmp_path) -> None:
    """``verbose=True`` opts back into the full message + stderr for callers that need it."""
    _init_repo(tmp_path)

    with pytest.raises(RuntimeError) as excinfo:
        await _run_git(tmp_path, "commit", "-m", _SECRET, verbose=True)

    message = str(excinfo.value)
    # When the caller explicitly opts in, the full detail (incl. the message
    # and stderr) is allowed back.
    assert _SECRET in message, (
        "verbose=True should restore the full RuntimeError message including "
        f"the git args: {message!r}"
    )


async def test_failed_non_commit_command_redacted_by_default(tmp_path) -> None:
    """Redaction is not commit-specific: a failed ``rev-parse <bad-ref>`` is also redacted.

    stderr from git for an unknown ref ("fatal: ambiguous argument ...") can
    itself echo caller-supplied content; the default path must not include it.
    """
    _init_repo(tmp_path)

    bad_ref = "definitely-not-a-real-ref-" + _SECRET

    with pytest.raises(RuntimeError) as excinfo:
        await _run_git(tmp_path, "rev-parse", bad_ref)

    message = str(excinfo.value)
    assert _SECRET not in message, (
        "stderr / arg content leaked into the default RuntimeError for a "
        f"non-commit git command: {message!r}"
    )
    assert "rev-parse" in message, (
        f"the redacted RuntimeError should still name the subcommand: {message!r}"
    )
