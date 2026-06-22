"""RED tests for ``bonfire.knowledge.hasher``.

Type locks:
- ``content_hash(text: str) -> str`` — SHA-256 hex (64 chars).
- ``file_hash(path: pathlib.Path) -> str`` — SHA-256 hex (64 chars).
"""

from __future__ import annotations

import re

import pytest

# RED-phase: target module not yet present on v0.1. Warrior ports it in Phase C.
from bonfire.knowledge.hasher import content_hash, file_hash

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


class TestContentHashIdentityAndShape:
    """Shape + identity invariants for :func:`content_hash`."""

    def test_content_hash_returns_hex_digest(self) -> None:
        """Returns SHA-256 hex string (64 lowercase hex chars)."""
        h = content_hash("hello world")
        assert isinstance(h, str)
        assert _HEX64.fullmatch(h), f"Expected 64-char lowercase hex, got {h!r}"

    def test_content_hash_returns_exactly_64_chars(self) -> None:
        """SHA-256 hex is always exactly 64 characters."""
        assert len(content_hash("a")) == 64

    @pytest.mark.parametrize(
        "text",
        [
            "short",
            "a" * 10_000,  # large input
            "🔥 unicode bonfire ☃",  # non-ASCII
            "\n".join(["line"] * 100),  # multiline
            "x",  # single char
        ],
    )
    def test_content_hash_shape_holds_for_many_inputs(self, text: str) -> None:
        """Shape invariant holds across many inputs (innovative lens split)."""
        h = content_hash(text)
        assert _HEX64.fullmatch(h)


class TestContentHashStability:
    """Determinism invariants for :func:`content_hash`."""

    def test_content_hash_stable_across_calls(self) -> None:
        """Same input in same process -> same output."""
        text = "deterministic"
        assert content_hash(text) == content_hash(text)


class TestContentHashDistinguishability:
    """Different inputs must produce different hashes (avalanche property)."""

    def test_content_hash_different_inputs_produce_different_outputs(self) -> None:
        assert content_hash("apples") != content_hash("oranges")

    @pytest.mark.parametrize(
        ("a", "b"),
        [
            ("apples", "apple"),  # substring vs superstring
            ("CASE", "case"),  # case-sensitivity
            ("hello", "hell0"),  # single-char flip
            ("one\ntwo", "one two"),  # newlines vs spaces — normalization collapses these
        ],
    )
    def test_pairs_of_distinct_inputs_hash_differently_except_normalized(
        self, a: str, b: str
    ) -> None:
        """Most distinct pairs hash differently. The one exception (newlines vs spaces)
        is intentional per hasher's whitespace normalization — covered separately."""
        # The v1 hasher normalizes whitespace runs: "one\ntwo" and "one two" may collide.
        # For that pair we expect equality; for all others we expect inequality.
        if a.replace("\n", " ") == b and re.sub(r"\s+", " ", a.strip()) == re.sub(
            r"\s+", " ", b.strip()
        ):
            assert content_hash(a) == content_hash(b)
        else:
            assert content_hash(a) != content_hash(b)


class TestContentHashWhitespaceNormalization:
    """Sage D8.3: ``test_content_hash_normalizes_whitespace_consistently``."""

    def test_content_hash_normalizes_whitespace_consistently(self) -> None:
        """Leading/trailing whitespace stripped; internal runs collapsed."""
        assert content_hash("  hello  world  ") == content_hash("hello world")
        assert content_hash("hello\n\n\tworld") == content_hash("hello world")

    # knight-a(innovative): split-multi-invariant — verify normalization is idempotent.
    def test_content_hash_normalization_is_idempotent(self) -> None:
        """Normalizing twice yields the same result as once."""
        once = content_hash("  a   b  ")
        twice = content_hash(re.sub(r"\s+", " ", "  a   b  ".strip()))
        assert once == twice


class TestFileHash:
    """File hashing semantics (Sage D8.3 required tests 5-6)."""

    def test_file_hash_matches_content_hash_of_file_bytes(self, tmp_path) -> None:
        """file_hash(path) == content_hash(path.read_text())."""
        p = tmp_path / "sample.txt"
        payload = "alpha beta gamma"
        p.write_text(payload, encoding="utf-8")
        assert file_hash(p) == content_hash(payload)

    def test_file_hash_raises_on_missing_file(self, tmp_path) -> None:
        """Missing path -> FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            file_hash(tmp_path / "does-not-exist.txt")

    # knight-a(innovative): edge case — empty file hashes cleanly.
    def test_file_hash_handles_empty_file(self, tmp_path) -> None:
        p = tmp_path / "empty.txt"
        p.write_text("", encoding="utf-8")
        h = file_hash(p)
        assert _HEX64.fullmatch(h)
