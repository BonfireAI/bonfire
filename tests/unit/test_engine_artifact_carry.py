# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Artifacts produced by one stage must reach the stage that publishes them.

Giving the dispatch layer an artifact producer is only half of what the
publishing stage needs. ``PipelineEngine._execute_stage`` builds a *fresh*
``Envelope`` for every stage, so a file the build stage wrote was recorded
on the build stage's envelope and then dropped on the floor: the publisher
was handed ``artifacts=[]`` no matter what any earlier stage did.

These tests pin the carry. Deliberately they assert on the envelope the
*handler* receives rather than on engine internals -- that is the surface
``BardHandler`` reads, and the one that was empty.
"""

from __future__ import annotations

from typing import Any

from bonfire.engine.pipeline import PipelineEngine
from bonfire.events.bus import EventBus
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import Artifact, Envelope, TaskStatus
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType


class _WritingBackend:
    """Backend whose dispatch reports one written file per stage."""

    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, envelope: Envelope, *, options: Any, **_: Any) -> Envelope:
        del options
        self.calls += 1
        return envelope.model_copy(
            update={
                "status": TaskStatus.COMPLETED,
                "result": f"wrote file {self.calls}; 1 passed",
                "artifacts": [
                    Artifact(
                        name=f"src/file{self.calls}.py",
                        content="",
                        artifact_type="file_written",
                    )
                ],
            }
        )

    async def health_check(self) -> bool:
        return True


class _RecordingHandler:
    """Captures the envelope the engine hands a handler stage."""

    def __init__(self) -> None:
        self.seen: Envelope | None = None

    async def handle(
        self, stage: StageSpec, envelope: Envelope, prior_results: dict[str, str]
    ) -> Envelope:
        del stage, prior_results
        self.seen = envelope
        return envelope.model_copy(update={"status": TaskStatus.COMPLETED, "result": "ok"})


def _plan(*stage_names: str, handler_on: str) -> WorkflowPlan:
    stages = []
    prev: list[str] = []
    for name in stage_names:
        stages.append(
            StageSpec(
                name=name,
                agent_name=name,
                role=name,
                handler_name="publish" if name == handler_on else None,
                depends_on=list(prev),
            )
        )
        prev = [name]
    return WorkflowPlan(
        name="carry_probe",
        workflow_type=WorkflowType.DEBUG,
        description="probe",
        stages=stages,
    )


def _engine(backend: Any, handler: Any) -> PipelineEngine:
    return PipelineEngine(
        backend=backend,
        bus=EventBus(),
        config=PipelineConfig(),
        handlers={"publish": handler},
    )


class TestArtifactsReachTheHandler:
    async def test_a_single_upstream_artifact_reaches_the_handler(self) -> None:
        handler = _RecordingHandler()
        await _engine(_WritingBackend(), handler).run(
            _plan("build", "publish", handler_on="publish")
        )

        assert handler.seen is not None
        assert [a.name for a in handler.seen.artifacts] == ["src/file1.py"]

    async def test_artifacts_from_every_upstream_stage_accumulate(self) -> None:
        handler = _RecordingHandler()
        await _engine(_WritingBackend(), handler).run(
            _plan("scout", "build", "verify", "publish", handler_on="publish")
        )

        assert handler.seen is not None
        assert [a.name for a in handler.seen.artifacts] == [
            "src/file1.py",
            "src/file2.py",
            "src/file3.py",
        ]

    async def test_artifact_type_survives_the_carry(self) -> None:
        handler = _RecordingHandler()
        await _engine(_WritingBackend(), handler).run(
            _plan("build", "publish", handler_on="publish")
        )

        assert handler.seen is not None
        assert handler.seen.artifacts[0].artifact_type == "file_written"

    async def test_the_same_file_touched_twice_is_carried_once(self) -> None:
        class _SameFileBackend(_WritingBackend):
            async def execute(self, envelope: Envelope, *, options: Any, **_: Any) -> Envelope:
                del options
                self.calls += 1
                return envelope.model_copy(
                    update={
                        "status": TaskStatus.COMPLETED,
                        "result": "1 passed",
                        "artifacts": [
                            Artifact(name="src/same.py", content="", artifact_type="file_modified")
                        ],
                    }
                )

        handler = _RecordingHandler()
        await _engine(_SameFileBackend(), handler).run(
            _plan("build", "fixup", "publish", handler_on="publish")
        )

        assert handler.seen is not None
        # Two stages edited one file. The publisher stages paths; carrying
        # the duplicate would list it twice in the commit metadata.
        assert [a.name for a in handler.seen.artifacts] == ["src/same.py"]


class TestCarryDoesNotInventArtifacts:
    async def test_no_upstream_artifacts_means_an_empty_list(self) -> None:
        class _SilentBackend(_WritingBackend):
            async def execute(self, envelope: Envelope, *, options: Any, **_: Any) -> Envelope:
                del options
                return envelope.model_copy(
                    update={"status": TaskStatus.COMPLETED, "result": "1 passed"}
                )

        handler = _RecordingHandler()
        await _engine(_SilentBackend(), handler).run(
            _plan("build", "publish", handler_on="publish")
        )

        assert handler.seen is not None
        assert handler.seen.artifacts == []

    async def test_the_first_stage_starts_with_no_artifacts(self) -> None:
        handler = _RecordingHandler()
        await _engine(_WritingBackend(), handler).run(_plan("publish", handler_on="publish"))

        assert handler.seen is not None
        assert handler.seen.artifacts == []
