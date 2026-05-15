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
    the helper must ``stat()`` (follow symlinks) so the link's tiny
    self-size does not bypass the cap.
    """
    big = tmp_path / "big.txt"
    big.write_text("Z" * 4096)
    link = tmp_path / "link.txt"
    link.symlink_to(big)

    out = safe_read_text(link, env_var="BONFIRE_TEST_UNUSED_ENV", default_bytes=1024)

    assert out.endswith(SAFE_READ_TRUNCATION_MARKER)
    assert out.startswith("Z" * 1024)
