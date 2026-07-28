"""Control rods: the gates grade the tree, and the old gates are shown failing.

Nothing here is stubbed below the gate. A real repository is written to
disk, a real ``pytest`` subprocess runs in it, and the real gate objects
the composition root builds are the ones asked for a verdict. The only
thing constructed by hand is the envelope, which is what a dispatched
stage would have handed the engine.

Every test carries its own falsifier: alongside the new gate's verdict it
evaluates the predicate the old gate used, *written out literally*, on the
same envelope. A rod that only showed the new gate passing would not show
that anything changed.

The two replayed cases are the two paid box runs this work exists because
of. Their exact agent transcripts were not retained, so what is replayed
is the property that killed them, taken from each run's own recorded
artefacts: a correctly fixed tree whose suite passes, described in words
that do not contain the substring the gate demanded.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from bonfire.engine.composition import build_default_gates
from bonfire.engine.gate_state import GateStateUnavailableError, PytestSuiteProbe
from bonfire.models.envelope import META_REVIEW_VERDICT, Envelope
from bonfire.models.plan import GateContext

# --------------------------------------------------------------------------
# The gate predicates as they stood on the parent commit, written out so the
# rods measure a difference rather than assert one.
# --------------------------------------------------------------------------

_NONZERO_FAILED_RE = re.compile(r"[1-9]\d*\s+failed", re.IGNORECASE)


def old_test_pass(text: str) -> bool:
    return "passed" in text.lower() and not _NONZERO_FAILED_RE.search(text)


def old_verification(text: str) -> bool:
    lowered = text.lower()
    return "verified" in lowered or "checks passed" in lowered


def old_review_approval(text: str) -> bool:
    lowered = text.lower()
    return "approve" in lowered or "approved" in lowered


# --------------------------------------------------------------------------
# A real repository, in the shape of the release-gate fixture's defect:
# ``average([])`` must return 0.0 rather than dividing by zero.
# --------------------------------------------------------------------------

_SOURCE_FIXED = '''\
"""Statistics helpers."""


def average(values):
    """Arithmetic mean; an empty input averages to 0.0."""
    if not values:
        return 0.0
    return sum(values) / len(values)
'''

_SOURCE_BROKEN = '''\
"""Statistics helpers."""


def average(values):
    """Arithmetic mean. Divides by zero on an empty input."""
    return sum(values) / len(values)
'''

_TESTS = """\
from stats import average


def test_average_of_values():
    assert average([1, 2, 3]) == 2


def test_average_of_empty_is_zero():
    assert average([]) == 0.0


def test_average_of_one():
    assert average([4]) == 4
"""


def _write_repo(root: Path, source: str) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "stats.py").write_text(source, encoding="utf-8")
    (root / "test_stats.py").write_text(_TESTS, encoding="utf-8")
    return root


@pytest.fixture
def fixed_repo(tmp_path: Path) -> Path:
    """A tree where the ticket's fix is present and the suite is green."""
    return _write_repo(tmp_path / "fixed", _SOURCE_FIXED)


@pytest.fixture
def broken_repo(tmp_path: Path) -> Path:
    """The same tree with the defect still in it; one test fails."""
    return _write_repo(tmp_path / "broken", _SOURCE_BROKEN)


def _gates(root: Path) -> dict:
    return build_default_gates(budget_usd=10.0, project_root=root)


def _ctx() -> GateContext:
    return GateContext(pipeline_cost_usd=0.0)


def _stage_envelope(narration: str, **metadata: object) -> Envelope:
    return Envelope(task="fix average").with_result(narration).with_metadata(**metadata)


# --------------------------------------------------------------------------
# The probe itself sees the two worlds apart
# --------------------------------------------------------------------------


async def test_the_probe_reports_the_real_tree(fixed_repo: Path, broken_repo: Path) -> None:
    """If the probe could not tell these apart, every rod below would be theatre."""
    green = await PytestSuiteProbe(project_root=fixed_repo).observe()
    red = await PytestSuiteProbe(project_root=broken_repo).observe()

    assert green.green is True, green.describe()
    assert green.count("passed") == 3
    assert red.green is False and red.red is True, red.describe()
    assert red.count("failed") == 1


# --------------------------------------------------------------------------
# ROD 1 — the false negative dies (replay of the warrior/test_pass run)
# --------------------------------------------------------------------------


# The property recorded for that run: the file on disk carried exactly the
# demanded fix, the fixture's own logs recorded "3 passed", and the gate said
# "Tests did not pass" because the narration lacked the substring "passed".
_WARRIOR_NARRATION = (
    "Read src/fixture_gate/stats.py and found the empty-input branch missing. "
    "Added an early return of 0.0 for an empty sequence. Ran the suite: all "
    "checks came back clean, no regressions, and I did not touch any test file."
)


async def test_the_warrior_run_would_now_survive_its_gate(fixed_repo: Path) -> None:
    gate = _gates(fixed_repo)["test_pass"]
    envelope = _stage_envelope(_WARRIOR_NARRATION)

    result = await gate.evaluate(envelope, _ctx())

    assert old_test_pass(_WARRIOR_NARRATION) is False, (
        "the replayed narration must reproduce the old gate's rejection, "
        "otherwise this rod proves nothing"
    )
    assert result.passed is True, result.message
    assert result.gate_name == "test_pass"


async def test_an_empty_narration_passes_when_the_work_is_sound(fixed_repo: Path) -> None:
    """The limit case: an agent that said nothing at all."""
    result = await _gates(fixed_repo)["test_pass"].evaluate(_stage_envelope(""), _ctx())
    assert old_test_pass("") is False
    assert result.passed is True, result.message


# --------------------------------------------------------------------------
# ROD 2 — the false negative dies (replay of the prover/verification run)
# --------------------------------------------------------------------------


_PROVER_NARRATION = (
    "Independent check of the change. The previously broken case now returns "
    "0.0, the other tests still hold, and no test file was modified. "
    "Confirmed good."
)


async def test_the_prover_run_would_now_survive_its_gate(fixed_repo: Path) -> None:
    gate = _gates(fixed_repo)["verification"]
    envelope = _stage_envelope(_PROVER_NARRATION)

    result = await gate.evaluate(envelope, _ctx())

    assert old_verification(_PROVER_NARRATION) is False, (
        "the replayed narration must reproduce the old gate's rejection"
    )
    assert result.passed is True, result.message
    assert result.gate_name == "verification"


# --------------------------------------------------------------------------
# ROD 3 — the false positive dies
# --------------------------------------------------------------------------


_REFUSAL = "I do not approve this change; the empty-input branch is still wrong."


async def test_a_refusal_is_no_longer_read_as_an_approval(fixed_repo: Path) -> None:
    gate = _gates(fixed_repo)["review_approval"]
    envelope = _stage_envelope(_REFUSAL, **{META_REVIEW_VERDICT: "request_changes"})

    result = await gate.evaluate(envelope, _ctx())

    assert old_review_approval(_REFUSAL) is True, (
        "the refusal must reproduce the old gate's acceptance, or this rod is empty"
    )
    assert result.passed is False, result.message
    assert result.gate_name == "review_approval"


async def test_the_word_passed_cannot_certify_a_red_tree(broken_repo: Path) -> None:
    """The other direction of the same defect, on the suite-backed gate."""
    narration = "All 3 tests passed and the change is verified."
    envelope = _stage_envelope(narration)

    assert old_test_pass(narration) is True
    assert old_verification(narration) is True
    gates = _gates(broken_repo)
    assert (await gates["test_pass"].evaluate(envelope, _ctx())).passed is False
    assert (await gates["verification"].evaluate(envelope, _ctx())).passed is False


# --------------------------------------------------------------------------
# NON-VACUITY — same words, opposite worlds, opposite verdicts
# --------------------------------------------------------------------------


@pytest.mark.parametrize("gate_name", ["test_pass", "verification"])
async def test_the_verdict_follows_the_tree_not_the_words(
    gate_name: str, fixed_repo: Path, broken_repo: Path
) -> None:
    envelope = _stage_envelope(_WARRIOR_NARRATION)
    on_green = await _gates(fixed_repo)[gate_name].evaluate(envelope, _ctx())
    on_red = await _gates(broken_repo)[gate_name].evaluate(envelope, _ctx())

    assert on_green.passed is True, on_green.message
    assert on_red.passed is False, on_red.message


async def test_red_phase_follows_the_tree_too(fixed_repo: Path, broken_repo: Path) -> None:
    envelope = _stage_envelope("wrote a failing test first")
    assert (await _gates(broken_repo)["red_phase"].evaluate(envelope, _ctx())).passed is True
    assert (await _gates(fixed_repo)["red_phase"].evaluate(envelope, _ctx())).passed is False


async def test_a_tree_with_no_tests_at_all_is_not_a_pass(tmp_path: Path) -> None:
    """The vacuity trap: nothing to run must never read as everything green."""
    empty = tmp_path / "empty"
    empty.mkdir()
    envelope = _stage_envelope("all tests passed and everything is verified")
    gates = _gates(empty)
    assert (await gates["test_pass"].evaluate(envelope, _ctx())).passed is False
    assert (await gates["verification"].evaluate(envelope, _ctx())).passed is False
    assert (await gates["red_phase"].evaluate(envelope, _ctx())).passed is False


# --------------------------------------------------------------------------
# THE UNEVALUATABLE CASE — loud, never a verdict
# --------------------------------------------------------------------------


@pytest.mark.parametrize("gate_name", ["test_pass", "verification", "red_phase"])
async def test_a_registry_built_without_a_root_refuses_to_guess(gate_name: str) -> None:
    gate = build_default_gates(budget_usd=10.0)[gate_name]
    with pytest.raises(GateStateUnavailableError):
        await gate.evaluate(_stage_envelope("10 passed, all verified"), _ctx())


async def test_a_review_with_no_recorded_verdict_refuses_to_guess(fixed_repo: Path) -> None:
    gate = _gates(fixed_repo)["review_approval"]
    with pytest.raises(GateStateUnavailableError):
        await gate.evaluate(_stage_envelope("APPROVE -- looks good to me"), _ctx())


# --------------------------------------------------------------------------
# The registry still reports the names it is filed under
# --------------------------------------------------------------------------


async def test_every_wired_gate_reports_its_registry_key(fixed_repo: Path) -> None:
    registry = _gates(fixed_repo)
    envelope = _stage_envelope("", **{META_REVIEW_VERDICT: "approve"})

    checked = 0
    for key, gate in registry.items():
        result = await gate.evaluate(envelope, _ctx())
        assert result.gate_name == key, f"registered {key!r}, reports {result.gate_name!r}"
        checked += 1

    assert checked == len(registry) and checked >= 8, (
        f"only {checked} gate(s) checked; an empty loop guards nothing"
    )
