"""The gates grade state, not narration — the contract, both directions.

Every test here holds one of the two variables fixed and moves the other.
Narration held constant while the world flips proves the gate is reading
the world. The world held constant while the narration flips proves the
gate is *not* reading the prose. A gate rewritten to always pass would
satisfy the first family and fail the second, which is why both are here.

The unevaluatable family is the third leg: a gate that cannot reach its
state must raise, because ``passed=True`` is a silent bypass and
``passed=False`` blames a stage for something never checked.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bonfire.engine.gate_state import (
    GateStateUnavailableError,
    PytestSuiteProbe,
    SuiteProbe,
)
from bonfire.engine.gates import (
    RedPhaseGate,
    ReviewApprovalGate,
    VerificationGate,
)

# Aliased on import: pytest would otherwise try to collect ``TestPassGate``
# as a test class and warn about its constructor.
from bonfire.engine.gates import TestPassGate as PassGate
from bonfire.models.envelope import META_REVIEW_VERDICT, Envelope, TaskStatus
from bonfire.models.plan import GateContext
from bonfire.verify.suite import SuiteOutcome, parse_pytest_run

_GREEN = (0, "collected 2 items\n\n==== 2 passed in 0.03s ====")
_RED = (1, "collected 2 items\n\n==== 1 failed, 1 passed in 0.03s ====")
_EMPTY = (5, "==== no tests ran in 0.01s ====")

# Narrations that are true of correct work but contain none of the words the
# old gates matched on. Each of these killed a paid run or would have.
_UNUSUAL_NARRATIONS = [
    "",
    "all checks came back clean",
    "confirmed good",
    "Everything is in order; nothing further to report.",
    "The broken case now returns 0.0 and nothing else changed.",
]

# Narrations that contain the old magic words while describing failure or
# refusal. Each of these bought a pass it had not earned, or survived only
# by luck of spelling.
_LYING_NARRATIONS = [
    "tests did not pass",
    "3 passed, then everything broke",
    "VERIFIED: all checks passed",
    "I could not get the suite to pass",
]


class _CannedProbe:
    """A SuiteProbe answering with a fixed, already-parsed observation."""

    def __init__(self, returncode: int, output: str) -> None:
        self._returncode = returncode
        self._output = output
        self.calls = 0

    async def observe(self) -> SuiteOutcome:
        self.calls += 1
        return parse_pytest_run(self._returncode, self._output)


def _ctx() -> GateContext:
    return GateContext(pipeline_cost_usd=0.0)


def _env(result: str = "", **metadata: object) -> Envelope:
    return Envelope(task="t").with_result(result).with_metadata(**metadata)


# ---------------------------------------------------------------------------
# The false negative dies: unusual wording over sound work now PASSES
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("narration", _UNUSUAL_NARRATIONS)
@pytest.mark.parametrize("gate_cls", [PassGate, VerificationGate])
async def test_unusual_wording_passes_when_the_suite_is_green(
    gate_cls: type, narration: str
) -> None:
    gate = gate_cls(_CannedProbe(*_GREEN))
    result = await gate.evaluate(_env(narration), _ctx())
    assert result.passed is True, f"{gate_cls.__name__} rejected sound work: {narration!r}"


# ---------------------------------------------------------------------------
# The false positive dies: the right words over broken work now FAIL
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("narration", _LYING_NARRATIONS)
@pytest.mark.parametrize("gate_cls", [PassGate, VerificationGate])
async def test_magic_words_cannot_buy_a_pass(gate_cls: type, narration: str) -> None:
    gate = gate_cls(_CannedProbe(*_RED))
    result = await gate.evaluate(_env(narration), _ctx())
    assert result.passed is False, f"{gate_cls.__name__} accepted a red suite: {narration!r}"


async def test_a_refusal_is_not_an_approval() -> None:
    """The literal string that made a refusal read as an approval."""
    envelope = _env("I do not approve this change", **{META_REVIEW_VERDICT: "request_changes"})
    result = await ReviewApprovalGate().evaluate(envelope, _ctx())
    assert result.passed is False
    assert "approve" in envelope.result  # the substring the old gate matched


async def test_approval_prose_without_a_recorded_verdict_is_unevaluatable() -> None:
    with pytest.raises(GateStateUnavailableError):
        await ReviewApprovalGate().evaluate(_env("APPROVE -- ship it"), _ctx())


@pytest.mark.parametrize("verdict", ["approve", "APPROVE", "  approve  "])
async def test_recorded_approval_passes(verdict: str) -> None:
    result = await ReviewApprovalGate().evaluate(_env("", **{META_REVIEW_VERDICT: verdict}), _ctx())
    assert result.passed is True


@pytest.mark.parametrize("verdict", ["request_changes", "reject", "comment", "approved"])
async def test_anything_but_approve_fails(verdict: str) -> None:
    """Including ``approved``: the wizard writes ``approve``, and a gate that
    accepted near-misses would be a substring match wearing a metadata key."""
    result = await ReviewApprovalGate().evaluate(_env("", **{META_REVIEW_VERDICT: verdict}), _ctx())
    assert result.passed is False


# ---------------------------------------------------------------------------
# Non-vacuity: every gate must still be able to return both answers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("gate_cls", "passing", "failing"),
    [
        (PassGate, _GREEN, _RED),
        (VerificationGate, _GREEN, _RED),
        (RedPhaseGate, _RED, _GREEN),
    ],
)
async def test_gate_returns_both_outcomes(
    gate_cls: type, passing: tuple[int, str], failing: tuple[int, str]
) -> None:
    narration = "identical narration in both directions"
    yes = await gate_cls(_CannedProbe(*passing)).evaluate(_env(narration), _ctx())
    no = await gate_cls(_CannedProbe(*failing)).evaluate(_env(narration), _ctx())
    assert yes.passed is True
    assert no.passed is False
    assert yes.severity == "info"
    assert no.severity == "error"


async def test_review_gate_returns_both_outcomes() -> None:
    yes = await ReviewApprovalGate().evaluate(_env("", **{META_REVIEW_VERDICT: "approve"}), _ctx())
    no = await ReviewApprovalGate().evaluate(
        _env("", **{META_REVIEW_VERDICT: "request_changes"}), _ctx()
    )
    assert (yes.passed, no.passed) == (True, False)


@pytest.mark.parametrize("gate_cls", [PassGate, VerificationGate, RedPhaseGate])
async def test_the_suite_is_actually_consulted(gate_cls: type) -> None:
    """A gate that never calls its probe is grading something else."""
    probe = _CannedProbe(*_GREEN)
    await gate_cls(probe).evaluate(_env("whatever"), _ctx())
    assert probe.calls == 1


@pytest.mark.parametrize("gate_cls", [PassGate, VerificationGate])
async def test_an_empty_suite_is_not_a_pass(gate_cls: type) -> None:
    result = await gate_cls(_CannedProbe(*_EMPTY)).evaluate(_env("everything passed"), _ctx())
    assert result.passed is False


# ---------------------------------------------------------------------------
# The unevaluatable case: loud, never a verdict
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gate_cls", [PassGate, VerificationGate, RedPhaseGate])
async def test_a_gate_with_no_probe_raises(gate_cls: type) -> None:
    with pytest.raises(GateStateUnavailableError) as excinfo:
        await gate_cls().evaluate(_env("10 passed"), _ctx())
    assert "suite probe" in str(excinfo.value)


@pytest.mark.parametrize("gate_cls", [PassGate, VerificationGate, RedPhaseGate])
async def test_a_gate_with_no_probe_does_not_quietly_pass(gate_cls: type) -> None:
    """The failure mode this replaces was an unregistered gate counting as a pass."""
    with pytest.raises(GateStateUnavailableError):
        await gate_cls().evaluate(_env(""), _ctx())


class _ExplodingProbe:
    async def observe(self) -> SuiteOutcome:
        raise GateStateUnavailableError("pytest could not be started")


@pytest.mark.parametrize("gate_cls", [PassGate, VerificationGate, RedPhaseGate])
async def test_an_unrunnable_suite_raises_rather_than_verdicts(gate_cls: type) -> None:
    with pytest.raises(GateStateUnavailableError):
        await gate_cls(_ExplodingProbe()).evaluate(_env(""), _ctx())


# ---------------------------------------------------------------------------
# Stage status is state too
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("gate_cls", [PassGate, VerificationGate, RedPhaseGate])
async def test_a_stage_that_did_not_complete_fails_without_consulting_the_suite(
    gate_cls: type,
) -> None:
    probe = _CannedProbe(*_GREEN)
    envelope = Envelope(task="t", status=TaskStatus.FAILED)
    result = await gate_cls(probe).evaluate(envelope, _ctx())
    assert result.passed is False
    assert probe.calls == 0


async def test_a_failed_review_stage_fails_rather_than_raising() -> None:
    """An ordinary handler failure is a verdict, not an unevaluatable gate."""
    envelope = Envelope(task="t", status=TaskStatus.FAILED)
    result = await ReviewApprovalGate().evaluate(envelope, _ctx())
    assert result.passed is False


# ---------------------------------------------------------------------------
# The real probe: it runs a real process and reports what happened
# ---------------------------------------------------------------------------


class TestPytestSuiteProbe:
    def test_satisfies_the_probe_protocol(self, tmp_path: Path) -> None:
        assert isinstance(PytestSuiteProbe(project_root=tmp_path), SuiteProbe)

    def test_command_is_an_argument_tuple_never_a_shell_string(self, tmp_path: Path) -> None:
        command = PytestSuiteProbe(project_root=tmp_path).command
        assert isinstance(command, tuple)
        assert command[1:] == ("-m", "pytest")

    async def test_a_missing_root_is_unevaluatable(self, tmp_path: Path) -> None:
        probe = PytestSuiteProbe(project_root=tmp_path / "gone")
        with pytest.raises(GateStateUnavailableError):
            await probe.observe()

    async def test_an_unstartable_command_is_unevaluatable(self, tmp_path: Path) -> None:
        probe = PytestSuiteProbe(
            project_root=tmp_path,
            command=("bonfire-no-such-executable-xyz",),
        )
        with pytest.raises(GateStateUnavailableError):
            await probe.observe()

    async def test_a_timeout_is_unevaluatable(self, tmp_path: Path) -> None:
        import sys

        probe = PytestSuiteProbe(
            project_root=tmp_path,
            command=(sys.executable, "-c", "import time; time.sleep(30)"),
            timeout_seconds=0.5,
        )
        with pytest.raises(GateStateUnavailableError):
            await probe.observe()
