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

import logging
import os
from pathlib import Path

__all__ = [
    "SAFE_READ_TRUNCATION_MARKER",
    "resolve_cap_bytes",
    "safe_read_text",
]

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
