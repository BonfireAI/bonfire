# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Deterministic mock embedder for testing.

Produces reproducible vectors by hashing input text. No external deps.
"""

from __future__ import annotations

import hashlib


class MockEmbedder:
    """Deterministic mock embedder for testing."""

    def __init__(self, dim: int = 768) -> None:
        self._dim = dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Produce deterministic vectors from text hashes."""
        return [self._hash_to_vector(t) for t in texts]

    def _hash_to_vector(self, text: str) -> list[float]:
        """Hash text to a fixed-dim float vector. Deterministic, no NaN."""
        h = hashlib.sha256(text.encode()).digest()
        extended = h
        while len(extended) < self._dim:
            extended += hashlib.sha256(extended).digest()
        raw = [(b / 127.5 - 1.0) for b in extended[: self._dim]]
        norm = (sum(x * x for x in raw)) ** 0.5
        if norm > 0:
            raw = [x / norm for x in raw]
        return raw

    @property
    def dim(self) -> int:
        return self._dim
