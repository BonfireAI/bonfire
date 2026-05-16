# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Size-capped text reader used by scanners.

Bonfire scanners walk arbitrary project trees, which means a
``CLAUDE.md`` / ``MEMORY.md`` / ``pyproject.toml`` / ``requirements.txt`` /
``package.json`` they touch may be:

* a 5 GB regular file written by a misbehaving tool,
* a symlink pointing at ``/dev/zero`` or a device file,
* a slowly-growing log file.

An unbounded ``Path.read_text()`` against any of those hangs the scanner
indefinitely or exhausts RAM. This module centralises a *fail-safe*
read that:

  1. Opens the path in binary mode (following symlinks, so the cap
     applies to the link target's content) and reads at most
     ``cap + 1`` bytes from the file descriptor.
  2. Resolves the cap from an env-var override, falling back to the
     supplied default.
  3. On cap-exceeded: emits a ``WARNING`` log + truncates to the cap.
  4. Appends a deterministic sentinel marker so callers parsing the
     content can detect the truncation.

The bounded read is the only mechanism gating output size — there is
no separate stat() check, which means a file growing between an
external check and the read cannot bypass the cap (no TOCTOU race).

The sentinel is a fixed marker that consumers may scan for to skip
partial content. It is appended only when truncation occurred — the
common "small file" path returns the file verbatim.

This complements ``onboard/scanners/mcp_servers.py`` which uses a
*skip-on-oversize* policy (returns empty). The scanners migrated to
``safe_read_text`` instead return *truncated* content so partial
detection still works on a giant ``pyproject.toml`` rather than the
scanner pretending the file does not exist.
"""

from __future__ import annotations

import errno
import logging
import os
from pathlib import Path

__all__ = [
    "MAX_CHECKPOINT_BYTES",
    "SAFE_READ_TRUNCATION_MARKER",
    "resolve_cap_bytes",
    "safe_read_capped_text",
    "safe_read_text",
]

# Hard byte cap on checkpoint files. Checkpoints contain pipeline state
# (envelopes, plan name, cost) — kilobytes in practice, hundreds of
# kilobytes for very large fan-out runs. A 10 MiB cap is comfortably
# beyond any legitimate checkpoint while bounding the damage from a
# planted oversized file (e.g. attacker fills the checkpoint dir with a
# 5 GB file to exhaust RAM during ``CheckpointManager.latest()``).
MAX_CHECKPOINT_BYTES: int = 10 * 1024 * 1024

_log = logging.getLogger(__name__)

# Appended (verbatim) to the returned string when truncation occurred. The
# marker is on its own line and unambiguous so downstream parsers can
# detect partial content. Stable per the public-API contract of this
# helper — do not change without a deprecation cycle.
SAFE_READ_TRUNCATION_MARKER = "\n<!-- bonfire-safe-read: truncated -->\n"


def resolve_cap_bytes(env_var: str, default_bytes: int) -> int:
    """Resolve a byte-cap from *env_var*, falling back to *default_bytes*.

    A missing / empty / unparseable / non-positive override falls back
    to the default (with a WARN on parse-failure to surface typos).
    """
    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        return default_bytes
    try:
        value = int(raw)
    except ValueError:
        _log.warning(
            "Ignoring invalid %s=%r; using default %d bytes",
            env_var,
            raw,
            default_bytes,
        )
        return default_bytes
    if value <= 0:
        return default_bytes
    return value


def safe_read_text(
    path: Path,
    *,
    env_var: str,
    default_bytes: int,
    encoding: str = "utf-8",
    errors: str = "replace",
) -> str:
    """Read *path* as text with a byte-cap applied.

    Behaviour:

    * At most ``cap + 1`` bytes are read from the file. If the read
      returns ``> cap`` bytes the content is truncated to ``cap`` bytes
      and the :data:`SAFE_READ_TRUNCATION_MARKER` is appended; a WARNING
      is also logged.
    * Otherwise the full content is returned (no marker).
    * If the file is unreadable (broken symlink, perms, device error),
      :class:`OSError` propagates — callers already wrap their reads in
      ``try/except OSError`` so this preserves their existing contract.

    The bounded read is the *only* mechanism gating output size. No
    separate ``stat()`` check is performed, which closes a TOCTOU race
    where a file growing between a ``stat()`` and a ``read()`` would
    otherwise bypass the cap.

    ``open()`` follows symlinks so a symlink to a 5 GB target is capped
    on the target's size, not the link's.

    The cap is recomputed from the env var on every call so tests can
    monkeypatch the env between cases without module reload.

    Decode errors default to ``"replace"`` so a binary or partially
    binary file does not crash the scanner — the intended use case
    walks operator-controlled trees and only inspects partial content
    for fingerprints.

    .. note::

       The truncation sentinel is an HTML-style comment and is **not**
       valid TOML. Callers that pass the output of this helper to a
       TOML parser must either re-validate the bytes or check for the
       :data:`SAFE_READ_TRUNCATION_MARKER` substring and skip parsing
       when present.
    """
    cap = resolve_cap_bytes(env_var, default_bytes)

    # Bounded read is the only thing that gates output size — read
    # ``cap + 1`` bytes so we can distinguish "fit exactly" from
    # "needs truncation". A file growing between any earlier stat()
    # and this read() cannot bypass the cap because we never read
    # more than ``cap + 1`` bytes regardless of advertised size.
    #
    # open() (not lstat-based) follows symlinks so a symlink to a
    # 5 GB target reads against the target's bytes. OSError on a
    # genuinely unreadable path propagates — callers already wrap
    # ``safe_read_text`` in ``try/except OSError``.
    with path.open("rb") as fh:
        raw = fh.read(cap + 1)

    if len(raw) <= cap:
        # File fit within the cap. ``errors="replace"`` (default)
        # keeps decode non-fatal on partially binary content.
        return raw.decode(encoding, errors=errors)

    _log.warning(
        "%s exceeds size cap (read > %d bytes); truncating read to cap",
        path,
        cap,
    )

    # When the slice falls mid-character, ``errors="replace"`` keeps
    # the call non-fatal; callers downstream parse line-by-line and
    # tolerate junk.
    truncated = raw[:cap]
    text = truncated.decode(encoding, errors="replace")
    return text + SAFE_READ_TRUNCATION_MARKER


# ``os.O_NOFOLLOW`` is POSIX-only. On Windows the flag is not defined;
# we fall back to a zero-value bitmask so the open() call shape stays
# uniform and the ``is_symlink()`` pre-check is the only defense
# layer. Windows is not in v0.1's symlink threat model.
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)

# Errnos that O_NOFOLLOW raises when the path is a symlink. Linux + glibc
# return ELOOP; some BSDs (and historic glibc) return EMLINK. Any other
# OSError is a distinct failure mode and propagates untranslated.
_SYMLINK_ERRNOS: frozenset[int] = frozenset(
    {errno.ELOOP} | ({errno.EMLINK} if hasattr(errno, "EMLINK") else set())
)


def safe_read_capped_text(
    path: Path,
    *,
    max_bytes: int,
    encoding: str = "utf-8",
) -> str:
    """Read *path* as text, refusing symlinks and capping at *max_bytes*.

    Symmetric companion to :func:`bonfire._safe_write.safe_write_text`.
    Where :func:`safe_read_text` (the scanner-facing helper) deliberately
    follows symlinks so a scanner can fingerprint a project tree, this
    helper refuses them — intended for operator-controlled read sites
    (e.g. ``engine/checkpoint.py``) where the read path is a known file
    Bonfire itself created and any symlink at that path is suspicious.

    Defense layers:

    1. **Pre-check** — :meth:`pathlib.Path.is_symlink` (does NOT follow
       symlinks). Any symlink at *path* is refused with a
       ``FileExistsError`` whose message contains the literal substring
       ``"symlink"`` (W7.M log-grep contract carried forward).
    2. **Defense-in-depth** — :func:`os.open` with ``O_NOFOLLOW`` closes
       the TOCTOU window between the pre-check and the read. On Linux,
       a race-planted symlink causes ``open(2)`` to fail with ``ELOOP``;
       we translate to the same ``FileExistsError("symlink ...")`` shape.
    3. **Size cap** — at most ``max_bytes + 1`` bytes are read. If the
       file exceeds the cap a ``ValueError`` is raised — checkpoint
       data is fully consumed by ``json.loads`` so silent truncation is
       NOT acceptable (it would produce a JSONDecodeError downstream
       and lose the security signal).

    Parameters
    ----------
    path
        The read target. MUST NOT be a symlink. Symlinks (dangling,
        live, or looping) are refused before any read.
    max_bytes
        Hard byte cap. Files larger than this raise ``ValueError``.
    encoding
        Text encoding for the returned string. Default ``"utf-8"``.

    Raises
    ------
    FileExistsError
        If *path* is a symlink (message contains the literal substring
        ``"symlink"``).
    FileNotFoundError
        If *path* does not exist (passed through unchanged).
    ValueError
        If the file exceeds *max_bytes*.
    OSError
        Other open(2)/read(2) failures (permissions, etc.) propagate
        untranslated.
    """
    # Pre-check: is_symlink() does NOT follow the link, so a dangling
    # symlink is correctly identified even though Path.exists() returns
    # False for a dangling link.
    if path.is_symlink():
        msg = (
            f"refusing to read from {path}: target is a symlink. "
            "Refusing to follow a symlinked path. "
            "Remove the symlink and re-run."
        )
        raise FileExistsError(msg)

    flags = os.O_RDONLY | _O_NOFOLLOW

    try:
        fd = os.open(path, flags)
    except OSError as exc:
        # Only the O_NOFOLLOW symlink-detection errnos get translated to
        # the W7.M "symlink"-mentioning FileExistsError. Other OSErrors
        # (ENOENT, EPERM, EISDIR, EACCES, ...) propagate untranslated.
        if exc.errno in _SYMLINK_ERRNOS:
            msg = (
                f"refusing to read from {path}: detected symlink at open via "
                f"O_NOFOLLOW ({exc.strerror or exc}). "
                "Refusing to follow a symlinked path. "
                "Remove the symlink and re-run."
            )
            raise FileExistsError(msg) from exc
        raise

    try:
        with os.fdopen(fd, "rb") as fh:
            # Read cap+1 bytes so we can distinguish "fits exactly" from
            # "exceeds cap" without trusting any external stat().
            raw = fh.read(max_bytes + 1)
    except Exception:
        # fdopen takes ownership of fd; on failure the context manager
        # closes it. Nothing else to clean up.
        raise

    if len(raw) > max_bytes:
        msg = (
            f"refusing to read {path}: file exceeds cap of {max_bytes} bytes "
            f"(read at least {len(raw)} bytes). Refused to prevent unbounded "
            "memory consumption from a planted oversized file."
        )
        raise ValueError(msg)

    return raw.decode(encoding)
