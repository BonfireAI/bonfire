# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Symlink-refusing text writer for operator-controlled paths.

Companion module to :mod:`bonfire._safe_read`. Centralises the
arbitrary-write defense W7.M established for ``write_config`` so the
same primitive can be reused at every operator-controlled write site
(``cli/commands/init.py``, ``cli/commands/persona.py``,
``engine/checkpoint.py``, plus the existing ``cli/commands/scan.py`` +
``onboard/config_generator.py`` sites W7.M originally hardened).

The defense is a two-layer guard against the
``Path.exists()`` + ``Path.write_text()`` arbitrary-write primitive:

1. **Pre-check** — :meth:`pathlib.Path.is_symlink` (which does NOT
   follow symlinks, unlike :meth:`pathlib.Path.exists`). Any symlink at
   the target path is refused with a ``FileExistsError`` whose message
   contains the literal substring ``"symlink"`` so log-grep can
   distinguish symlink-refusal from regular collision.
2. **Defense-in-depth** — :func:`os.open` with ``O_NOFOLLOW`` (refuses
   symlinks at ``open(2)`` time, closing the TOCTOU window against the
   pre-check) + ``O_EXCL`` when ``allow_existing=False`` (refuses an
   existing regular file atomically, closing the TOCTOU window against
   a separate ``exists()`` check the caller may already have performed).

POSIX-only. ``O_NOFOLLOW`` is unavailable on Windows; the helper falls
back to the ``is_symlink()`` pre-check alone there. Windows shipping
is not currently in scope (see commit ``cd848a0`` PR#94 for the
platform-canonicalization standard the rest of v0.1 follows).

Threat model
------------

A malicious or compromised operator (or a process running as the same
user) plants a symlink at one of Bonfire's operator-controlled write
targets — e.g. ``bonfire.toml -> ~/.ssh/authorized_keys``.
``Path.exists()`` returns ``False`` for a dangling symlink, so the
existing-file overwrite-guard does not trip. ``Path.write_text``
follows symlinks, opening the symlink target in ``O_WRONLY |
O_CREAT | O_TRUNC`` mode. The attacker-controlled file is now
overwritten with Bonfire's generated content.

This primitive is reachable today (before this module lands) at:

* ``bonfire init`` — writes ``[bonfire]\\n`` stub.
* ``bonfire persona set`` — reads-then-writes ``bonfire.toml``.
* ``CheckpointManager.save`` — writes ``{session_id}.json.tmp``.
* ``bonfire scan`` + ``write_config`` — closed by W7.M (PR #93); kept
  here behind the same helper for DRY consistency.
"""

from __future__ import annotations

import os
from pathlib import Path

__all__ = ["safe_write_text"]


# ``os.O_NOFOLLOW`` is POSIX-only. On Windows the flag is not defined;
# we fall back to a zero-value bitmask so the open() call shape stays
# uniform and the ``is_symlink()`` pre-check is the only defense
# layer. Windows is not in v0.1's symlink threat model.
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def safe_write_text(
    path: Path,
    content: str,
    *,
    allow_existing: bool = False,
    encoding: str = "utf-8",
    mode: int = 0o644,
) -> None:
    """Write *content* to *path*, refusing to follow symlinks.

    Parameters
    ----------
    path
        The target path. MUST NOT be a symlink. Symlinks (dangling,
        live, or looping) are refused before any write.
    content
        Text to write. Encoded with *encoding* (default ``"utf-8"``).
    allow_existing
        When ``False`` (default), refuse any pre-existing file at
        *path* — equivalent to ``O_EXCL`` semantics, mirroring the
        W7.M overwrite-guard contract. When ``True``, an existing
        **regular** file at *path* is overwritten (but a symlink is
        still refused). Used by callers that intentionally re-write a
        file in place — e.g. ``checkpoint`` atomic-rename tmp paths,
        or ``persona set`` mutate-in-place.
    encoding
        Text encoding for *content*. Default ``"utf-8"``.
    mode
        Filesystem mode bits applied to the newly-created file
        (default ``0o644``). Ignored when ``allow_existing=True`` and
        the file already exists (the existing mode is preserved).

    Raises
    ------
    FileExistsError
        If *path* is a symlink (message contains the literal substring
        ``"symlink"``), OR if ``allow_existing=False`` and *path*
        already exists as a regular file.
    OSError
        Other open(2)/write(2) failures (disk full, permissions, etc.)
        propagate. The helper unlinks the half-written file before
        re-raising so the caller is left with a clean directory.

    Notes
    -----
    * ``Path.is_symlink()`` does NOT follow symlinks, so a dangling
      symlink is correctly identified (unlike ``Path.exists()``).
    * The ``O_NOFOLLOW`` flag closes the TOCTOU race between the
      ``is_symlink()`` pre-check and the ``open(2)`` system call: a
      concurrent process planting a symlink between the two operations
      causes ``open(2)`` to fail with ``ELOOP`` (Linux) / ``EMLINK``
      (some BSDs). The OSError is translated into a uniform
      ``FileExistsError`` with a ``"symlink"`` message so callers
      handle both pre-check and race paths identically.
    * ``O_EXCL`` (set when ``allow_existing=False``) closes the TOCTOU
      race against the ``exists()`` check a caller may have performed
      before invoking ``safe_write_text``.
    * On Windows, ``O_NOFOLLOW`` is unavailable; the ``is_symlink()``
      pre-check is the only defense. Windows is not in v0.1's symlink
      threat model (see PR #94 for platform scoping).
    """
    # Pre-check: is_symlink() does NOT follow the link, so a dangling
    # symlink is correctly identified here even though Path.exists()
    # would return False.
    if path.is_symlink():
        msg = (
            f"refusing to write to {path}: target is a symlink. "
            "Refusing to follow or overwrite a symlinked path. "
            "Remove the symlink and re-run."
        )
        raise FileExistsError(msg)

    # When allow_existing=False, the W7.M overwrite-guard semantics
    # apply: the caller pinky-promises no file at this path. We fold
    # that into the open(2) flags via O_EXCL — kernel-atomic refusal
    # closes the TOCTOU window against any separate exists() check
    # the caller may have already done.
    flags = os.O_WRONLY | os.O_CREAT | _O_NOFOLLOW
    if not allow_existing:
        flags |= os.O_EXCL
    else:
        # When overwriting is permitted, truncate the existing file
        # so we don't leave stale bytes past our content's length.
        flags |= os.O_TRUNC

    try:
        fd = os.open(path, flags, mode)
    except FileExistsError:
        # Race: a regular file appeared between any exists() check and
        # this open. Re-raise with a path-mentioning message.
        msg = (
            f"refusing to write to {path}: a file already exists at this path. "
            "Remove or move the existing file and re-run."
        )
        raise FileExistsError(msg) from None
    except OSError as exc:
        # Race: a symlink appeared between the is_symlink() pre-check
        # and this open(2). O_NOFOLLOW makes open(2) fail with ELOOP
        # on Linux / EMLINK on some BSDs. Re-raise as FileExistsError
        # with a "symlink" message so the caller contract is uniform.
        msg = (
            f"refusing to write to {path}: detected symlink at open via "
            f"O_NOFOLLOW ({exc.strerror or exc}). "
            "Refusing to follow or overwrite a symlinked path. "
            "Remove the symlink and re-run."
        )
        raise FileExistsError(msg) from exc

    try:
        with os.fdopen(fd, "w", encoding=encoding) as f:
            f.write(content)
    except Exception:
        # Regular write failures clean up so we leave no half-written
        # file. Interpreter-shutdown signals (KeyboardInterrupt,
        # SystemExit) are intentionally NOT caught: the kernel will
        # close the file descriptor on process exit, and a partial
        # file is a recoverable situation the user can inspect.
        try:
            path.unlink()
        except OSError:
            pass
        raise
