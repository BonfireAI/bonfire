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

  1. Calls ``stat()`` (NOT ``lstat()``) so the cap applies to the symlink
     target's size — checking the link's own size would be useless.
  2. Compares ``st_size`` against an env-var-overridable cap.
  3. On cap-exceeded: emits a ``WARNING`` log + truncates to the cap.
  4. Appends a deterministic sentinel marker so callers parsing the
     content can detect the truncation.

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
    errors: str = "strict",
) -> str:
    """Read *path* as text with a byte-cap applied.

    Behaviour:

    * If ``path.stat().st_size`` is at or under the resolved cap, the
      file is read normally.
    * If oversized: a WARNING is logged and at most ``cap`` bytes are
      read; the returned string carries the
      :data:`SAFE_READ_TRUNCATION_MARKER` appended.
    * If the file is unreadable (broken symlink, perms, device error),
      :class:`OSError` propagates — callers already wrap their reads in
      ``try/except OSError`` so this preserves their existing contract.

    ``stat()`` follows symlinks so a symlink to a 5 GB target is capped
    on the target's size, not the link's.

    The cap is recomputed from the env var on every call so tests can
    monkeypatch the env between cases without module reload.
    """
    cap = resolve_cap_bytes(env_var, default_bytes)

    # stat() (NOT lstat()) — follow symlinks so the target's size is
    # what we cap on.
    st = path.stat()
    size = st.st_size

    if size <= cap:
        return path.read_text(encoding=encoding, errors=errors)

    _log.warning(
        "%s exceeds size cap (%d bytes > %d bytes); truncating read to cap",
        path,
        size,
        cap,
    )

    # Open in binary mode and read up to cap bytes — read_text() has no
    # length parameter. Decode with replacement on cap boundary to avoid
    # UnicodeDecodeError on a sliced multi-byte character.
    with path.open("rb") as fh:
        data = fh.read(cap)
    # When the slice falls mid-character, "replace" keeps the call
    # non-fatal; callers downstream parse line-by-line and tolerate junk.
    text = data.decode(encoding, errors="replace")
    return text + SAFE_READ_TRUNCATION_MARKER
