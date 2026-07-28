# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The gates that grade a live observation of the project's test suite.

Three of the built-in gates ask questions about tests: ``test_pass``
(warrior), ``red_phase`` (TDD red stage), and ``verification`` (prover).
Each of them used to answer by looking for a word in the agent's own
narration -- ``"passed"``, ``"exit code 1"``, ``"verified"``. That is a
measurement of the writing, not of the work: correct work described in
unusual words was rejected, and a sentence like "tests did not pass"
survived only because the pattern happened to ask for ``"passed"`` rather
than ``"pass"``. Luck, not design.

Each gate here takes a :class:`~bonfire.engine.gate_state.SuiteProbe`,
runs the suite at evaluation time, and grades the
:class:`~bonfire.verify.suite.SuiteOutcome`. The envelope's ``result``
string is never read.

``test_pass`` and ``verification`` grade the same world-fact
---------------------------------------------------------
Stated plainly rather than dressed up: both now pass exactly when the
suite is green, from two *independent* observations taken at two
different points in the run. They are not the same check -- the prover's
observation is taken after the prover stage, so work that broke the suite
between the two is caught -- but they do ask one question, where the
prose versions pretended to ask two.

The question that would genuinely distinguish them is "did anything
*regress*?", and it needs a baseline observation recorded before the
warrior stage. No stage records one today. Inventing one from the same
run's later output would be the prose defect wearing a type, so this
module does not; the gap is named here instead.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.engine.gate_state import GateStateUnavailableError
from bonfire.models.envelope import TaskStatus
from bonfire.models.plan import GateResult

if TYPE_CHECKING:
    from bonfire.engine.gate_state import SuiteProbe
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import GateContext
    from bonfire.verify.suite import SuiteOutcome

__all__ = [
    "RedPhaseGate",
    "TestPassGate",
    "VerificationGate",
]


def _verdict(gate_name: str, *, passed: bool, message: str) -> GateResult:
    return GateResult(
        gate_name=gate_name,
        passed=passed,
        severity="info" if passed else "error",
        message=message,
    )


async def _observe(probe: SuiteProbe | None, gate_name: str) -> SuiteOutcome:
    """Return the current suite state, or refuse to guess.

    An absent probe means the gate was constructed without the collaborator
    that answers its question. Returning ``passed=True`` would bypass the
    gate silently; returning ``passed=False`` would blame a stage for
    something the gate never checked. Both are lies, so this raises.
    """
    if probe is None:
        msg = (
            f"gate '{gate_name}' has no suite probe, so it cannot observe whether "
            "the tests pass. Build the gate registry through "
            "bonfire.engine.composition.build_default_gates(project_root=...) "
            "instead of constructing the gate bare."
        )
        raise GateStateUnavailableError(msg)
    return await probe.observe()


def _refuse_incomplete(gate_name: str, envelope: Envelope) -> GateResult | None:
    """Fail the gate when the stage itself did not complete.

    A stage that errored produced no work to certify, and the suite state
    says nothing about why it errored. This is read off ``envelope.status``
    -- a field the engine sets, not a sentence the agent wrote.
    """
    if envelope.status == TaskStatus.COMPLETED:
        return None
    return _verdict(
        gate_name,
        passed=False,
        message=f"Stage did not complete (status={envelope.status}); tests not graded",
    )


class TestPassGate:
    """Passes when the project's test suite is observed green.

    Green means: pytest exited 0, reported no failures and no errors, and
    at least one test body actually ran. The last clause is not decoration
    -- a suite that collected nothing also exits without failures, and a
    gate that accepted it would pass on a mistyped test path.
    """

    def __init__(self, suite_probe: SuiteProbe | None = None) -> None:
        self._probe = suite_probe

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        del context  # gate grades the tree, not the run's cost or prior prose
        incomplete = _refuse_incomplete("test_pass", envelope)
        if incomplete is not None:
            return incomplete
        outcome = await _observe(self._probe, "test_pass")
        return _verdict(
            "test_pass",
            passed=outcome.green,
            message=(
                f"Tests passed -- {outcome.describe()}"
                if outcome.green
                else f"Tests did not pass -- {outcome.describe()}"
            ),
        )


class RedPhaseGate:
    """Passes when the suite is observed genuinely red.

    Red means tests ran and at least one failed or errored -- pytest's
    ``TESTS_FAILED`` exit, not merely "not green". A usage error, an
    import-time crash, or an empty collection are all non-green without
    demonstrating the red phase a TDD stage is claiming, and accepting
    them would let a broken invocation stand in for a failing test.
    """

    def __init__(self, suite_probe: SuiteProbe | None = None) -> None:
        self._probe = suite_probe

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        del context
        incomplete = _refuse_incomplete("red_phase", envelope)
        if incomplete is not None:
            return incomplete
        outcome = await _observe(self._probe, "red_phase")
        return _verdict(
            "red_phase",
            passed=outcome.red,
            message=(
                f"Red phase confirmed -- {outcome.describe()}"
                if outcome.red
                else f"No failing tests observed -- {outcome.describe()}"
            ),
        )


class VerificationGate:
    """Passes when an independent suite observation finds the tree green.

    Independent of the verifying stage: the gate runs the suite itself
    rather than reading the stage's report of having run it. See the module
    docstring for why this currently asks the same question as
    ``test_pass`` and what would separate them.
    """

    def __init__(self, suite_probe: SuiteProbe | None = None) -> None:
        self._probe = suite_probe

    async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult:
        del context
        incomplete = _refuse_incomplete("verification", envelope)
        if incomplete is not None:
            return incomplete
        outcome = await _observe(self._probe, "verification")
        return _verdict(
            "verification",
            passed=outcome.green,
            message=(
                f"Verification passed -- {outcome.describe()}"
                if outcome.green
                else f"Verification not confirmed -- {outcome.describe()}"
            ),
        )
