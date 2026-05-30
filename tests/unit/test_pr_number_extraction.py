# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Pin the shared ``extract_pr_number`` helper (handlers/_pr_number.py).

Phase 4 dedups three identical ``_extract_pr_number`` definitions
(wizard / steward / merge_preflight) into one shared helper. These tests
pin all three resolution paths plus the int-coerce failure -> None
contract, and lock the steward behaviour (``envelope=None`` MUST NOT
consult envelope metadata).
"""

from __future__ import annotations

import pytest

from bonfire.handlers._pr_number import extract_pr_number
from bonfire.models.envelope import META_PR_NUMBER, Envelope


def _env(**meta: object) -> Envelope:
    return Envelope(task="t", metadata=dict(meta))


# ---------------------------------------------------------------------------
# Path 1: prior_results[META_PR_NUMBER] direct int-coerce
# ---------------------------------------------------------------------------


def test_path1_prior_results_pr_number_int() -> None:
    assert extract_pr_number({META_PR_NUMBER: 42}) == 42


def test_path1_prior_results_pr_number_str_coerced() -> None:
    assert extract_pr_number({META_PR_NUMBER: "42"}) == 42


def test_path1_int_coerce_failure_falls_through_to_none() -> None:
    # Non-numeric pr_number must NOT crash; with no other signal -> None.
    assert extract_pr_number({META_PR_NUMBER: "not-a-number"}) is None


# ---------------------------------------------------------------------------
# Path 2: prior_results["bard"] /pull/(\d+) regex
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("bard_text", "expected"),
    [
        ("https://github.com/o/r/pull/7", 7),
        ("see PR at /pull/123 thanks", 123),
        ("/pull/0", 0),
        ("no pull url here", None),
        ("", None),
    ],
)
def test_path2_bard_url_regex(bard_text: str, expected: int | None) -> None:
    assert extract_pr_number({"bard": bard_text}) == expected


def test_path1_wins_over_path2() -> None:
    # Direct pr_number takes precedence over the bard URL fallback.
    result = extract_pr_number({META_PR_NUMBER: 5, "bard": "https://github.com/o/r/pull/9"})
    assert result == 5


# ---------------------------------------------------------------------------
# Path 3: envelope.metadata[META_PR_NUMBER] final fallback (wizard/preflight)
# ---------------------------------------------------------------------------


def test_path3_envelope_metadata_fallback() -> None:
    env = _env(**{META_PR_NUMBER: 99})
    assert extract_pr_number({}, envelope=env) == 99


def test_path3_envelope_metadata_str_coerced() -> None:
    env = _env(**{META_PR_NUMBER: "99"})
    assert extract_pr_number({}, envelope=env) == 99


def test_path3_envelope_metadata_int_coerce_failure_none() -> None:
    env = _env(**{META_PR_NUMBER: "bad"})
    assert extract_pr_number({}, envelope=env) is None


# ---------------------------------------------------------------------------
# Steward behaviour: envelope=None MUST NOT consult envelope metadata
# ---------------------------------------------------------------------------


def test_steward_path_envelope_none_does_not_consult_metadata() -> None:
    # The steward call passes envelope=None; even if a (hypothetical)
    # envelope carried a pr_number, the None call must ignore it. With no
    # prior_results signal the answer is None.
    assert extract_pr_number({}, envelope=None) is None


def test_steward_path_still_resolves_prior_results() -> None:
    assert extract_pr_number({META_PR_NUMBER: 13}, envelope=None) == 13
    assert extract_pr_number({"bard": "/pull/77"}, envelope=None) == 77


def test_default_envelope_is_none() -> None:
    # Default arg preserves the steward (no-envelope) behaviour.
    assert extract_pr_number({META_PR_NUMBER: 1}) == 1


def test_no_signal_anywhere_returns_none() -> None:
    assert extract_pr_number({}) is None
