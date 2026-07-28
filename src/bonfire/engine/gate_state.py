# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The state the quality gates grade, and the error raised when it is absent.

A gate must grade what happened, not what was said about it. Two of the
built-in gates ask a question the pipeline does not record anywhere --
"do the project's tests pass?" -- so somebody has to go and look. This
module is the looking: a small protocol, one real implementation that
runs pytest as a subprocess, and the error a gate raises when it has no
way to find out.

Why the gate observes instead of reading a record
-------------------------------------------------
The alternative is a producer that runs the suite once and stamps the
result onto the envelope for the gate to read. That is one indirection
away from the defect being fixed: whatever writes the record becomes the
thing the gate trusts, and a gate that trusts a record cannot tell a
truthful record from a stale or forged one. Observing at evaluation time
costs a suite run per gate and buys a verdict about the tree as it stands
when the verdict is issued.

The cost is real and is not hidden: every evaluation of a suite-backed
gate runs the project's tests. ``MergePreflightHandler`` already pays the
same price for the same reason.

Why an absent observation raises
--------------------------------
An unevaluatable gate is an error, not a verdict. Returning
``passed=True`` would be a silent bypass -- the exact failure mode the
composition root exists to prevent. Returning ``passed=False`` would be a
verdict about the work that the gate has no evidence for, and would send
the pipeline bouncing back to a stage that did nothing wrong.
:class:`GateStateUnavailableError` propagates out of ``GateChain``
(which, per its own contract, does not wrap gate exceptions) and reaches
``PipelineEngine.run()``'s outer handler, which fails the run loudly and
names the cause.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Protocol, runtime_checkable

from bonfire.verify.suite import SuiteOutcome, parse_pytest_run

__all__ = [
    "GateStateUnavailableError",
    "PytestSuiteProbe",
    "SuiteProbe",
]

# Wall-clock ceiling for one suite observation. A hung suite must not hang
# the pipeline; it must fail the gate loudly.
_DEFAULT_TIMEOUT_SECONDS: float = 600.0


class GateStateUnavailableError(RuntimeError):
    """A gate could not obtain the state it grades.

    Raised instead of returning a :class:`~bonfire.models.plan.GateResult`,
    because neither available verdict would be honest. See the module
    docstring.
    """


@runtime_checkable
class SuiteProbe(Protocol):
    """Something that can report the current state of a project's test suite."""

    async def observe(self) -> SuiteOutcome:
        """Run the suite and return what happened.

        Raises:
            GateStateUnavailableError: If the suite could not be run at all.
        """
        ...


class PytestSuiteProbe:
    """Runs the project's pytest suite in a subprocess and parses the result.

    The command is a fixed argument tuple -- never a shell string -- and
    defaults to ``<this interpreter> -m pytest``, so the suite runs under
    the same environment Bonfire itself was installed into.

    A run that cannot start (no interpreter, no pytest, missing root) or
    that exceeds *timeout_seconds* raises
    :class:`GateStateUnavailableError`. A run that starts and finishes is
    an observation, whatever its exit code -- including a red one.
    """

    def __init__(
        self,
        *,
        project_root: Path,
        command: tuple[str, ...] = (),
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._project_root = project_root
        self._command = command or (sys.executable, "-m", "pytest")
        self._timeout_seconds = timeout_seconds

    @property
    def command(self) -> tuple[str, ...]:
        """The exact argv this probe runs. Exposed so tests can assert it."""
        return self._command

    async def observe(self) -> SuiteOutcome:
        """Run pytest under ``project_root`` and parse its output."""
        if not self._project_root.is_dir():
            msg = (
                f"cannot observe the test suite: project root {self._project_root} "
                "is not a directory"
            )
            raise GateStateUnavailableError(msg)

        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=str(self._project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
            )
        except OSError as exc:
            msg = (
                f"cannot observe the test suite: {' '.join(self._command)} "
                f"could not be started in {self._project_root} ({exc})"
            )
            raise GateStateUnavailableError(msg) from exc

        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), timeout=self._timeout_seconds)
        except TimeoutError as exc:
            process.kill()
            await process.wait()
            msg = (
                f"cannot observe the test suite: {' '.join(self._command)} "
                f"did not finish within {self._timeout_seconds:.0f}s"
            )
            raise GateStateUnavailableError(msg) from exc

        returncode = process.returncode if process.returncode is not None else -1
        return parse_pytest_run(returncode, stdout.decode("utf-8", errors="replace"))
