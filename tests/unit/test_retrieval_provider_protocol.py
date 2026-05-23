# SPDX-License-Identifier: Apache-2.0
"""Tests for the RetrievalProvider Protocol + ContextAtom envelope."""

from __future__ import annotations

from bonfire.protocols import ContextAtom, RetrievalProvider


def test_context_atom_model_roundtrips():
    atom = ContextAtom(
        key="lexicon-is-the-knowledge-store-2026-05-14",
        body="The Lexicon IS memory.",
        source_path="/path/to/atom.md",
        score=0.87,
    )
    assert atom.key == "lexicon-is-the-knowledge-store-2026-05-14"
    assert atom.body == "The Lexicon IS memory."
    assert atom.source_path == "/path/to/atom.md"
    assert atom.score == 0.87
    payload = atom.model_dump_json()
    restored = ContextAtom.model_validate_json(payload)
    assert restored == atom


def test_context_atom_extra_ignore():
    """Unknown fields are silently dropped per family convention."""
    atom = ContextAtom.model_validate(
        {
            "key": "k",
            "body": "b",
            "source_path": "/p",
            "score": 0.1,
            "unknown_future_field": 42,
        }
    )
    assert not hasattr(atom, "unknown_future_field")


def test_retrieval_provider_protocol_structural_match():
    """A class with a matching .retrieve() signature satisfies the Protocol."""

    class FakeProvider:
        def retrieve(
            self,
            *,
            query: str,
            seed_keys: list[str] | None = None,
            token_budget: int = 4000,
        ) -> list[ContextAtom]:
            return []

    provider: RetrievalProvider = FakeProvider()
    result = provider.retrieve(query="anything")
    assert result == []


def test_retrieval_provider_protocol_accepts_seed_keys_and_budget():
    class FakeProvider:
        def retrieve(
            self,
            *,
            query: str,
            seed_keys: list[str] | None = None,
            token_budget: int = 4000,
        ) -> list[ContextAtom]:
            return [
                ContextAtom(key=k, body=f"body of {k}", source_path=f"/atoms/{k}.md", score=1.0)
                for k in (seed_keys or [])
            ]

    provider: RetrievalProvider = FakeProvider()
    out = provider.retrieve(query="q", seed_keys=["a", "b"], token_budget=500)
    assert len(out) == 2
    assert {a.key for a in out} == {"a", "b"}
