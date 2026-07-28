# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The checkpoint a run leaves behind — proved through the real composition root.

``bonfire status``, ``bonfire resume`` and ``bonfire handoff`` are three shipped
verbs that all read one artifact, and nothing wrote it. ``SessionStore.save``
had no caller anywhere in ``src/bonfire/`` and the pipeline loop had no
checkpoint write site, so a run that really dispatched and really spent money
was followed by three commands reporting an empty store.

That is the same shape as the ``Envelope.artifacts`` and
``.bonfire/review-verdict.json`` gaps, and it was invisible for the same
reason: every test of the run path injects its own engine factory, so the
wiring nothing exercises is the wiring nothing can catch. This module
therefore calls :func:`bonfire.engine.composition.build_default_engine` and
runs the engine it returns. Assembling the object graph by hand would
re-implement the wiring under test and pass whether or not the product is
wired at all.

One replacement, stated: ``claude_agent_sdk.query``. Every dispatch below
would otherwise be a billed network call. The fake charges a real
``total_cost_usd`` because the assertions here are partly about money being
recorded, and a zero-cost fake would let an empty figure look correct.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from bonfire.dispatch import sdk_backend
from bonfire.engine.checkpoint import CheckpointSink
from bonfire.engine.composition import build_default_engine
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType
from bonfire.session.store import CHECKPOINT_DIR_ENV_VAR, SessionStore
from bonfire.workflow.standard import debug

#: What one faked dispatch charges. Deliberately not round: a total asserted
#: against this figure cannot be satisfied by a default, a zero, or a number
#: someone rounded on the way through.
STAGE_COST_USD = 0.11


class CountingTransport:
    """``claude_agent_sdk.query`` stand-in that charges and counts its calls.

    The call count is the load-bearing part for the resume assertions: the
    question "was this stage billed again?" is answered by whether the
    transport was reached, not by re-reading a total the engine computed.
    """

    def __init__(self, cost_usd: float = STAGE_COST_USD) -> None:
        self.cost_usd = cost_usd
        self.prompts: list[str] = []

    def __call__(self, *, prompt: str, options: Any) -> Any:
        self.prompts.append(prompt)
        cost = self.cost_usd

        async def _stream() -> Any:
            yield AssistantMessage(content=[TextBlock(text="done")], model="fake")
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="fake-session",
                total_cost_usd=cost,
                result="done",
            )

        return _stream()


@pytest.fixture
def store_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the checkpoint store at a throwaway directory.

    The env override is the same one the three verbs honour, so redirecting it
    steers the write and all three reads together -- which is itself part of
    what these tests check.
    """
    path = tmp_path / "checkpoints"
    monkeypatch.setenv(CHECKPOINT_DIR_ENV_VAR, str(path))
    return path


@pytest.fixture
def counting(monkeypatch: pytest.MonkeyPatch) -> CountingTransport:
    fake = CountingTransport()
    monkeypatch.setattr(sdk_backend, "query", fake)
    return fake


def _plan(*, budget_usd: float = 10.0, gate_second_stage: bool = False) -> WorkflowPlan:
    """A three-stage chain. Optionally gate the middle stage on cost.

    ``cost_limit`` is the one built-in gate that fails deterministically with
    no filesystem and no subprocess: ``build_default_gates`` registers it
    against the plan's own budget, so a budget below the running total fails
    the stage that names it.
    """
    gates = ["cost_limit"] if gate_second_stage else []
    return WorkflowPlan(
        name="debug",
        workflow_type=WorkflowType.DEBUG,
        description="checkpoint probe",
        task_description="ship the checkout refactor",
        budget_usd=budget_usd,
        stages=[
            StageSpec(name="scout", agent_name="scout", role="scout"),
            StageSpec(
                name="warrior",
                agent_name="warrior",
                role="warrior",
                depends_on=["scout"],
                gates=gates,
            ),
            StageSpec(name="bard", agent_name="bard", role="bard", depends_on=["warrior"]),
        ],
    )


def _run(plan: WorkflowPlan, root: Path, **kwargs: Any) -> Any:
    return asyncio.run(build_default_engine(plan, project_root=root).run(plan, **kwargs))


# ---------------------------------------------------------------------------
# The producer exists at all
# ---------------------------------------------------------------------------


def test_a_run_leaves_a_checkpoint_on_disk(
    tmp_path: Path, git_repo: Any, store_dir: Path, counting: CountingTransport
) -> None:
    """The regression this module exists for.

    Before the producer landed this directory stayed empty after a run that
    dispatched three stages and spent real money.
    """
    result = _run(_plan(), git_repo(tmp_path / "r"))

    assert result.success
    written = sorted(p.name for p in store_dir.iterdir())
    assert written == [f"{result.session_id}.json"], (
        "a completed run must leave exactly one checkpoint, named for its session"
    )
    data = json.loads((store_dir / written[0]).read_text())
    assert sorted(data["completed"]) == ["bard", "scout", "warrior"]
    assert data["total_cost_usd"] == pytest.approx(3 * STAGE_COST_USD)
    assert data["plan_name"] == "debug"
    assert data["task_description"] == "ship the checkout refactor"


def test_an_engine_with_no_sink_writes_nothing(
    tmp_path: Path, git_repo: Any, store_dir: Path, counting: CountingTransport
) -> None:
    """Control rod on the assertion above.

    The engine's sink is optional, and a library caller who omits it keeps the
    previous behaviour. If the test above passed with the sink removed it
    would be measuring the fixture, not the producer.
    """
    plan = _plan()
    engine = build_default_engine(plan, project_root=git_repo(tmp_path / "r"))
    engine._checkpoint_sink = None

    assert asyncio.run(engine.run(plan)).success
    assert not store_dir.exists() or list(store_dir.iterdir()) == []


# ---------------------------------------------------------------------------
# Partway through -- the case resume exists for
# ---------------------------------------------------------------------------


def test_a_run_that_halts_partway_records_only_the_stages_that_passed(
    tmp_path: Path, git_repo: Any, store_dir: Path, counting: CountingTransport
) -> None:
    """A halt at stage two must leave stage one on disk and stage two off it.

    Writing the failed stage into ``completed`` would be worse than writing
    nothing: resume skips whatever the checkpoint names, so a failed stage
    recorded as done is a stage that silently never runs again.
    """
    plan = _plan(budget_usd=STAGE_COST_USD * 1.5, gate_second_stage=True)
    result = _run(plan, git_repo(tmp_path / "r"))

    assert not result.success
    assert result.failed_stage == "warrior"
    data = json.loads((store_dir / f"{result.session_id}.json").read_text())
    assert sorted(data["completed"]) == ["scout"], (
        "the gate-failed stage and the stage after it must not be recorded as done"
    )
    assert data["total_cost_usd"] == pytest.approx(STAGE_COST_USD)


def test_the_verbs_read_the_checkpoint_from_a_separate_process(
    tmp_path: Path, git_repo: Any, store_dir: Path, counting: CountingTransport
) -> None:
    """Survival of the process that wrote it, proved by leaving that process.

    ``CliRunner`` would exercise the same interpreter that just ran the
    engine, which cannot distinguish a checkpoint on disk from state still
    in memory. These three invocations are real ``bonfire`` processes with
    no knowledge of the run beyond the file.

    The plan is the registry's own ``debug``, not an ad-hoc one: a checkpoint
    stores ``plan_name`` and not the stage list, so ``status`` and ``resume``
    re-derive the total and the remainder from the registry. A test plan
    reusing a registered name with a different shape would be graded against
    the registered shape and report a denominator nobody ran.

    It halts on the budget check that follows the first stage, which also
    pins the ordering the engine promises: work already dispatched and paid
    for is on disk before the halt that follows it.
    """
    plan = debug().model_copy(
        update={"budget_usd": STAGE_COST_USD / 2, "task_description": "ship the refactor"}
    )
    result = _run(plan, git_repo(tmp_path / "r"))
    assert not result.success and "Budget exceeded" in result.error
    bonfire = Path(sys.executable).with_name("bonfire")

    def _verb(name: str) -> str:
        done = subprocess.run([str(bonfire), name], capture_output=True, text=True, check=True)
        return done.stdout

    status = _verb("status")
    assert result.session_id in status
    assert "1 / 2 stages" in status, f"status must report progress, not a total: {status!r}"
    assert "$0.11" in status

    resume = _verb("resume")
    assert "warrior" in resume, f"resume must name what is left: {resume!r}"

    handoff = _verb("handoff")
    assert "scout" in handoff and "ship the refactor" in handoff


# ---------------------------------------------------------------------------
# Resume does not pay twice
# ---------------------------------------------------------------------------


def test_resuming_from_the_checkpoint_does_not_re_dispatch_or_re_bill(
    tmp_path: Path, git_repo: Any, store_dir: Path, counting: CountingTransport
) -> None:
    """The ruling on re-billing, measured at the transport rather than inferred.

    The first leg halts after ``scout``. Feeding that checkpoint's
    ``completed`` map back into a second engine must reach the transport only
    for the two stages that remain, and the final total must be the whole
    pipeline's spend -- the seeded first stage plus the tail, counted once.
    """
    root = git_repo(tmp_path / "r")
    first = _run(_plan(budget_usd=STAGE_COST_USD * 1.5, gate_second_stage=True), root)
    assert not first.success
    assert len(counting.prompts) == 2, "first leg dispatched scout and the failed warrior"

    saved = SessionStore().load(first.session_id)
    counting.prompts.clear()

    second = _run(_plan(), root, session_id=first.session_id, completed=dict(saved.completed))

    assert second.success
    assert len(counting.prompts) == 2, (
        f"resume must dispatch only warrior and bard, not scout again: {len(counting.prompts)}"
    )
    assert "Output from scout" in counting.prompts[0], (
        "the seeded envelope must be carried forward as context, which is what "
        "makes skipping the stage legitimate rather than merely cheaper"
    )
    assert second.total_cost_usd == pytest.approx(3 * STAGE_COST_USD), (
        "the seeded stage is counted once, not spent again and not dropped"
    )


# ---------------------------------------------------------------------------
# The wiring itself
# ---------------------------------------------------------------------------


def test_the_root_wires_a_sink_resolving_the_directory_the_verbs_read(
    tmp_path: Path, git_repo: Any, store_dir: Path
) -> None:
    """Write side and read side must resolve one directory by one rule.

    Two independent resolutions that happen to agree today are a defect
    waiting for the next change to either.
    """
    engine = build_default_engine(_plan(), project_root=git_repo(tmp_path / "r"))
    sink = engine._checkpoint_sink

    assert isinstance(sink, SessionStore)
    assert sink.checkpoint_dir == store_dir == SessionStore().checkpoint_dir


def test_session_store_satisfies_the_sink_protocol() -> None:
    assert isinstance(SessionStore(), CheckpointSink)


def test_a_sink_that_cannot_write_does_not_fail_the_run(
    tmp_path: Path,
    git_repo: Any,
    store_dir: Path,
    counting: CountingTransport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A disk problem must not turn a healthy run into a failed one.

    ``run()`` never raises, so an uncaught error here would be converted into
    a failed ``PipelineResult`` -- reporting that the work failed when only
    the record of it did. It must not be silent either, or an empty
    ``bonfire status`` has no explanation.
    """

    class RefusingSink:
        def save_progress(self, *args: Any) -> Path:
            raise OSError("read-only file system")

    plan = _plan()
    engine = build_default_engine(plan, project_root=git_repo(tmp_path / "r"))
    engine._checkpoint_sink = RefusingSink()

    with caplog.at_level("WARNING"):
        result = asyncio.run(engine.run(plan))

    assert result.success, "a checkpoint that cannot be written must not fail the run"
    assert "read-only file system" in caplog.text
