# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

""":mod:`bonfire._safe_read` size-capped reader.

Validates the three invariants the helper is documented to provide:

1. A file *under* the cap is returned verbatim — no truncation marker.
2. A file *over* the cap is truncated, the
   :data:`SAFE_READ_TRUNCATION_MARKER` is appended, and a WARNING is
   logged.
3. The cap is overridable via the configured env var; an invalid env
   value falls back to the default with a WARNING.

These tests use *real* files and *real* cap values (NOT mocks) so the
stat()/read pipeline is exercised end-to-end. The oversize fixture uses
a small cap to keep the test fast — the cap mechanism itself is
size-agnostic.
"""

from __future__ import annotations

import logging
import os

import pytest

from bonfire._safe_read import (
    SAFE_READ_TRUNCATION_MARKER,
    resolve_cap_bytes,
    safe_read_text,
)


def test_under_cap_returns_verbatim(tmp_path) -> None:
    """Small file under the cap returns the file content verbatim."""
    f = tmp_path / "small.txt"
    payload = "hello\nworld\n"
    f.write_text(payload)

    out = safe_read_text(f, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=1024)

    assert out == payload
    assert SAFE_READ_TRUNCATION_MARKER not in out


def test_over_cap_truncates_and_marks(tmp_path, caplog) -> None:
    """File larger than the cap is truncated at cap bytes + marker appended."""
    f = tmp_path / "big.txt"
    payload = "X" * 4096
    f.write_text(payload)

    cap = 1024
    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        out = safe_read_text(f, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=cap)

    # The body up to cap bytes is preserved verbatim.
    assert out.startswith("X" * cap)
    # The marker is appended (only once, at the tail).
    assert out.endswith(SAFE_READ_TRUNCATION_MARKER)
    # Nothing else past the marker.
    assert out.count(SAFE_READ_TRUNCATION_MARKER) == 1
    # A WARNING was logged naming the file and the cap.
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


def test_env_var_override_lowers_cap(tmp_path, monkeypatch) -> None:
    """An env-var override is honoured over the default cap."""
    f = tmp_path / "mid.txt"
    f.write_text("Y" * 2048)

    # Default is large (no truncation), but env override drops cap below
    # the file size — truncation MUST fire.
    monkeypatch.setenv("BONFIRE_TEST_CAP_ENV", "512")
    out = safe_read_text(f, env_var="BONFIRE_TEST_CAP_ENV", default_bytes=1_000_000)

    assert out.endswith(SAFE_READ_TRUNCATION_MARKER)
    assert len(out) == 512 + len(SAFE_READ_TRUNCATION_MARKER)


def test_env_var_invalid_falls_back(monkeypatch, caplog) -> None:
    """A non-integer env value falls back to default + WARNS."""
    monkeypatch.setenv("BONFIRE_TEST_CAP_ENV", "not-a-number")

    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        cap = resolve_cap_bytes("BONFIRE_TEST_CAP_ENV", default_bytes=4242)

    assert cap == 4242
    assert any("Ignoring invalid" in rec.message for rec in caplog.records)


def test_env_var_non_positive_falls_back(monkeypatch) -> None:
    """Zero or negative env value falls back silently to the default."""
    monkeypatch.setenv("BONFIRE_TEST_CAP_ENV", "0")
    assert resolve_cap_bytes("BONFIRE_TEST_CAP_ENV", default_bytes=4242) == 4242

    monkeypatch.setenv("BONFIRE_TEST_CAP_ENV", "-5")
    assert resolve_cap_bytes("BONFIRE_TEST_CAP_ENV", default_bytes=4242) == 4242


def test_missing_file_raises_oserror(tmp_path) -> None:
    """A missing path raises ``OSError`` so callers' existing try/except still fires."""
    missing = tmp_path / "nope.txt"
    with pytest.raises(OSError):
        safe_read_text(missing, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=1024)


def test_symlink_to_large_file_capped_on_target(tmp_path) -> None:
    """A symlink to an oversize file is capped on the target's size.

    This is the ``/dev/zero``-symlink threat model in miniature:
    ``open()`` follows symlinks so the link's tiny self-size does not
    bypass the cap (the bounded read against the target is what
    actually fires).
    """
    big = tmp_path / "big.txt"
    big.write_text("Z" * 4096)
    link = tmp_path / "link.txt"
    link.symlink_to(big)

    out = safe_read_text(link, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=1024)

    assert out.endswith(SAFE_READ_TRUNCATION_MARKER)
    assert out.startswith("Z" * 1024)


# ---------------------------------------------------------------------------
# Bounded-read TOCTOU defense
# ---------------------------------------------------------------------------


def test_file_at_exactly_cap_bytes_returns_full_content(tmp_path) -> None:
    """A file *exactly* the cap size returns full content, no marker.

    Boundary pin: the cap is inclusive — a file of exactly ``cap``
    bytes is NOT truncated. The implementation reads ``cap + 1`` bytes
    and only truncates when the read returns ``> cap`` bytes.
    """
    f = tmp_path / "exact.txt"
    payload = "A" * 1024
    f.write_text(payload)

    out = safe_read_text(f, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=1024)

    assert out == payload
    assert SAFE_READ_TRUNCATION_MARKER not in out


def test_file_at_cap_plus_one_byte_truncates(tmp_path, caplog) -> None:
    """A file *one byte* over the cap triggers truncation.

    Pair with :func:`test_file_at_exactly_cap_bytes_returns_full_content`
    — together they pin the off-by-one boundary of the bounded read.
    """
    f = tmp_path / "over.txt"
    payload = "B" * 1025  # cap + 1
    f.write_text(payload)

    with caplog.at_level(logging.WARNING, logger="bonfire._safe_read"):
        out = safe_read_text(f, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=1024)

    assert out.endswith(SAFE_READ_TRUNCATION_MARKER)
    assert out.startswith("B" * 1024)
    assert any("exceeds size cap" in rec.message for rec in caplog.records)


def test_bounded_read_caps_growing_file(tmp_path, monkeypatch) -> None:
    """A file growing between stat() and read() cannot bypass the cap.

    Models the TOCTOU race the docstring lists as a threat: a slowly
    growing log file. The bounded read is the only mechanism gating
    output size, so even if an external observer would have seen a
    smaller ``st_size`` before the read, the returned content is still
    capped at ``cap`` bytes + marker.

    We simulate the race by monkeypatching ``Path.stat`` to lie about
    the size (claim under-cap) while the on-disk file is over-cap. A
    pre-fix implementation would have read the file unbounded; the
    fixed implementation reads at most ``cap + 1`` bytes regardless.
    """
    from pathlib import Path

    f = tmp_path / "growing.log"
    payload = b"C" * 4096  # well over the test cap
    f.write_bytes(payload)

    # Make stat() report a size well under the cap, mimicking a file
    # that grew after an earlier check.
    real_stat = Path.stat

    def lying_stat(self, *args, **kwargs):
        result = real_stat(self, *args, **kwargs)
        # Pretend the file is empty so any stat-gated branch would
        # take the fast path. The bounded read must still cap output.
        return os.stat_result(
            (
                result.st_mode,
                result.st_ino,
                result.st_dev,
                result.st_nlink,
                result.st_uid,
                result.st_gid,
                0,  # st_size — the LIE
                result.st_atime,
                result.st_mtime,
                result.st_ctime,
            )
        )

    monkeypatch.setattr(Path, "stat", lying_stat)

    out = safe_read_text(f, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=512)

    # Output is bounded by the cap regardless of what stat reported.
    # Either the full file fit (it did not — 4096 > 512) or the
    # truncation path fired. Assert the latter.
    assert out.endswith(SAFE_READ_TRUNCATION_MARKER)
    # Body is exactly the first ``cap`` bytes.
    assert out[: -len(SAFE_READ_TRUNCATION_MARKER)] == "C" * 512


def test_binary_content_does_not_crash(tmp_path) -> None:
    """A file with binary bytes decodes with replacement, not a crash.

    Default ``errors="replace"`` keeps the scanner non-fatal on a
    pyproject.toml replaced with a binary blob (or a partially-corrupt
    file). Pins the uniform encoding behaviour across small-file and
    truncation paths.
    """
    f = tmp_path / "binary.bin"
    f.write_bytes(b"\xff\xfe\xfd\x00valid\x00")

    # Small-file path (the file is well under the cap).
    out = safe_read_text(f, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=1024)

    # Did not raise UnicodeDecodeError. The replacement character is
    # used for invalid bytes — exact form depends on the platform's
    # default behaviour, so we only assert non-empty + valid-substring.
    assert "valid" in out
    assert isinstance(out, str)
