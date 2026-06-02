# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract tests for ``compute_study_fingerprint`` — the analysis cache key.

``compute_study_fingerprint(input_fingerprint, budget, versions,
schema_version)`` is the public cache key for a project-analysis study: a
later scan that produces the same four inputs is allowed to reuse a cached
study instead of recomputing it. Because the digest decides cache HIT vs
MISS, every property below is a correctness contract, not a nicety — a bug
that makes the digest unstable would silently re-run scans (waste), and a
bug that makes the digest collide across differing inputs would silently
serve a *stale* study (a correctness fault).

The function had zero direct tests before this file; these tests lock the
observed behaviour so a future refactor of the serialization cannot
silently change the cache key.
"""

from __future__ import annotations

from bonfire.analysis import compute_study_fingerprint
from bonfire.analysis.models import CartographerBudget

# A representative, fully-specified set of inputs reused across the tests.
# ``CartographerBudget()`` takes every field's default, so the bare
# constructor is a valid, frozen budget — no optional dependency needed.
_FP = "sha256-of-sorted-source-tuples"
_BUDGET = CartographerBudget()
_VERSIONS = {"cartographer": "1.2.3", "tiktoken": "0.7.0"}
_SCHEMA = 2


def test_digest_is_deterministic() -> None:
    """Same four inputs must always yield the SAME digest.

    Cache reuse depends on this: a second scan that genuinely matches the
    first must compute the identical key so it lands on the cached study.
    If the digest wobbled between calls (e.g. unsorted dict serialization,
    hash randomization), every scan would MISS and recompute — defeating
    the cache entirely.
    """
    first = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)
    second = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)
    third = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)

    assert first == second == third


def test_digest_is_64_char_lowercase_hex() -> None:
    """The digest is a canonical sha256: 64 lowercase hex characters.

    Callers store and compare the digest as an opaque string key. Pinning
    the exact shape (sha256 hex, never uppercase, never truncated) guards
    the key format that downstream cache storage and lookups rely on.
    """
    digest = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)

    assert len(digest) == 64
    assert digest == digest.lower()
    # Every character is a valid hex nibble (0-9, a-f).
    assert all(ch in "0123456789abcdef" for ch in digest)


def test_changing_input_fingerprint_changes_digest() -> None:
    """A different source fingerprint must produce a different cache key.

    ``input_fingerprint`` summarises the actual source bytes. If two
    different source sets hashed to the same key, the cache could hand a
    caller the wrong project's study — a silent correctness fault.
    """
    base = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)
    changed = compute_study_fingerprint(_FP + "-different", _BUDGET, _VERSIONS, _SCHEMA)

    assert base != changed


def test_changing_a_budget_field_changes_digest() -> None:
    """Tuning any budget knob must invalidate the cache key.

    The budget controls what the study computes (token ceiling, ranking
    parameters, projection size). A study built under ``max_tokens=1024``
    is NOT interchangeable with one built under ``max_tokens=2048``, so
    flipping a single budget field must change the digest.
    """
    base = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)
    changed = compute_study_fingerprint(
        _FP, CartographerBudget(max_tokens=2048), _VERSIONS, _SCHEMA
    )

    assert base != changed


def test_changing_versions_changes_digest() -> None:
    """A change in tool versions must invalidate the cache key.

    The ``versions`` dict records the versions of the libraries that
    produced the study (cartographer, tree-sitter pack, tiktoken,
    networkx). A study computed by an old tool version may be subtly
    different from one a new version produces, so a version bump must
    force a fresh scan rather than reuse the stale artefact.
    """
    base = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)
    changed = compute_study_fingerprint(
        _FP, _BUDGET, {"cartographer": "9.9.9", "tiktoken": "0.7.0"}, _SCHEMA
    )

    assert base != changed


def test_changing_schema_version_changes_digest() -> None:
    """A change in the study schema version must invalidate the cache key.

    The on-disk study layout is versioned. A v2 reader must not be handed
    a v3-shaped artefact, so the schema version participates in the key:
    bumping it forces a cache MISS and a fresh, correctly-shaped scan.
    """
    base = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)
    changed = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA + 1)

    assert base != changed


def test_versions_key_order_does_not_change_digest() -> None:
    """The ``versions`` dict is order-independent.

    Two dicts with the same entries in a different insertion order describe
    the SAME tooling and must yield the SAME key — otherwise an irrelevant
    accident of construction order would cause a spurious cache MISS. The
    function guarantees this by serializing with ``sort_keys=True``.
    """
    forward = compute_study_fingerprint(_FP, _BUDGET, {"a": "1", "b": "2"}, _SCHEMA)
    reversed_order = compute_study_fingerprint(_FP, _BUDGET, {"b": "2", "a": "1"}, _SCHEMA)

    assert forward == reversed_order


def test_digest_is_workspace_agnostic() -> None:
    """The digest depends ONLY on the four documented inputs.

    The "workspace-agnostic" contract (C3 in the source docstring) is what
    lets two different checkouts that scan identical sources SHARE a cached
    study. The guarantee is structural: ``compute_study_fingerprint`` takes
    no workspace/cwd/path parameter, so workspace identity simply cannot
    enter the key. We pin that by computing the digest twice with identical
    inputs — there is no place for ambient workspace state to leak in, so
    the two results must match.
    """
    from_one_workspace = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)
    from_another_workspace = compute_study_fingerprint(_FP, _BUDGET, _VERSIONS, _SCHEMA)

    assert from_one_workspace == from_another_workspace
