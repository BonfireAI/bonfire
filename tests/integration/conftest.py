# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Shared fixtures for the composition-root integration tests.

Two test modules exercise the same real objects from opposite directions --
``test_composition_root.py`` asks what the CLI is wired to, and
``test_project_root_trust.py`` asks what the wiring lets into the agent's
prompt. Both need a throwaway git work tree and a transport that records the
options the backend built, so those live here rather than being copied.

The transport is the only replacement either module makes. Everything above
it is the code under test; below it is a billed network call.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from bonfire.dispatch import sdk_backend
from bonfire.models.plan import StageSpec, WorkflowPlan, WorkflowType

#: A reply shaped to satisfy the real gates: ``test_pass`` wants "passed" with
#: no non-zero "N failed", ``verification`` wants "verified", and
#: ``review_approval`` wants "approve". Canned rather than random so a gate
#: that starts rejecting it is reporting a change in the gate, not in the fake.
AGENT_REPLY = "Done. 12 passed, 0 failed. All checks passed and verified. I approve."


class RecordingTransport:
    """Stands in for ``claude_agent_sdk.query`` and keeps every options object.

    Recording the ``ClaudeAgentOptions`` is the point: ``setting_sources`` is
    computed inside the backend from the ``cwd`` the engine passed, so the
    only way to observe that decision without asserting on a re-derivation of
    it is to look at what the backend actually built.
    """

    def __init__(self, reply: str = AGENT_REPLY) -> None:
        self.reply = reply
        self.calls: list[Any] = []

    def __call__(self, *, prompt: str, options: Any) -> Any:
        self.calls.append(options)
        reply = self.reply

        async def _stream() -> Any:
            yield AssistantMessage(content=[TextBlock(text=reply)], model="fake")
            yield ResultMessage(
                subtype="success",
                duration_ms=1,
                duration_api_ms=1,
                is_error=False,
                num_turns=1,
                session_id="fake-session",
                total_cost_usd=0.0,
                result=reply,
            )

        return _stream()


@pytest.fixture
def transport(monkeypatch: pytest.MonkeyPatch) -> RecordingTransport:
    """Replace the SDK transport for the duration of one test."""
    fake = RecordingTransport()
    monkeypatch.setattr(sdk_backend, "query", fake)
    return fake


@pytest.fixture
def git_repo() -> Callable[[Path], Path]:
    """Return a factory that initialises a throwaway git work tree.

    A real work tree, not a marker directory: ``resolve_project_root`` and
    ``detect_repo_slug`` shell out to git, and stubbing git would mean the
    tests no longer exercise the discovery they are here to check.
    """

    def _make(path: Path) -> Path:
        path.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init", "-q", str(path)], check=True)
        (path / "README.md").write_text("fixture\n")
        subprocess.run(["git", "-C", str(path), "add", "."], check=True)
        subprocess.run(
            [
                "git",
                "-C",
                str(path),
                "-c",
                "user.email=fixture@example.invalid",
                "-c",
                "user.name=fixture",
                "commit",
                "-qm",
                "init",
            ],
            check=True,
        )
        return path

    return _make


def one_stage_plan(name: str = "probe") -> WorkflowPlan:
    """The smallest plan that reaches the transport: one backend stage."""
    return WorkflowPlan(
        name=name,
        workflow_type=WorkflowType.DEBUG,
        description="probe",
        task_description="probe",
        stages=[StageSpec(name="scout", agent_name="scout", role="scout")],
    )
