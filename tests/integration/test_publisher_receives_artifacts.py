# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The publisher stage receives the files the agent reported writing.

``Envelope.artifacts`` had one reader -- ``BardHandler``, which refuses to
commit when it is empty -- and no producer at all, so the publishing stage
of ``standard_build`` refused on every run of every shape. Closing that took
two halves: the dispatch layer records the agent's file-mutating tool calls,
and the engine carries them down the run into the envelope each stage gets.

This drives the real composition root -- not an injected factory -- with a
transport that reports an ``Edit``, and asserts the publisher gets past its
empty-artifacts precondition. It is the companion to
``test_composition_root.py::test_standard_build_reaches_the_publisher_stage``,
which pins the other side: a run in which nothing was written still refuses,
because there is genuinely nothing to commit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from bonfire.dispatch import sdk_backend
from bonfire.engine.composition import build_default_engine
from bonfire.workflow.standard import standard_build
from tests.integration.conftest import AGENT_REPLY, RecordingTransport

try:  # pragma: no cover - exercised whenever the SDK is installed
    from claude_agent_sdk.types import (  # type: ignore[import-untyped]
        AssistantMessage,
        ResultMessage,
        TextBlock,
        ToolUseBlock,
    )
except ImportError:  # pragma: no cover
    AssistantMessage = ResultMessage = TextBlock = ToolUseBlock = None  # type: ignore[assignment,misc]


def test_a_reported_file_write_reaches_the_publisher(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    git_repo: object,
) -> None:
    """The closed half: a tool use the agent made lands on the publisher.

    The publisher's refusal used to be unconditional -- no run of any shape
    could put an entry on ``Envelope.artifacts``. This drives the real
    composition root with a transport that reports an ``Edit``, and asserts
    the publisher gets past its empty-artifacts precondition.

    It stops at git rather than succeeding, because the throwaway repository
    has no remote. That is the honest boundary for this fixture, and naming
    it is the point: the failure moved from "refused to look" to "tried and
    could not reach a remote".
    """
    root = git_repo(tmp_path / "r")
    monkeypatch.chdir(root)
    target = root / "src" / "thing.py"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("x = 1\n")

    class _EditingTransport(RecordingTransport):
        def __call__(self, *, prompt: str, options: Any) -> Any:
            self.calls.append(options)

            async def _stream() -> Any:
                yield AssistantMessage(
                    content=[
                        TextBlock(text=AGENT_REPLY),
                        ToolUseBlock(
                            id="toolu_1",
                            name="Edit",
                            input={"file_path": str(target)},
                        ),
                    ],
                    model="fake",
                )
                yield ResultMessage(
                    subtype="success",
                    duration_ms=1,
                    duration_api_ms=1,
                    is_error=False,
                    num_turns=1,
                    session_id="fake-session",
                    total_cost_usd=0.0,
                    result=AGENT_REPLY,
                )

            return _stream()

    monkeypatch.setattr(sdk_backend, "query", _EditingTransport())

    plan = standard_build().model_copy(update={"task_description": "probe"})
    result = __import__("asyncio").run(build_default_engine(plan).run(plan))

    assert result.failed_stage == "bard", (
        f"expected the publisher stage, got {result.failed_stage!r}: {result.error}"
    )
    assert "empty_artifacts" not in result.error, (
        f"the publisher still refused to look at the file the agent edited: {result.error}"
    )
