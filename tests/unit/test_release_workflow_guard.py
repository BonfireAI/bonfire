# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The release workflow must run the tag/version guard before it builds.

``_guard_problems`` is a pure helper: it takes a parsed workflow and returns
stable problem names, so the real file and three planted breakages are judged
by the same function.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
_GUARD_SCRIPT = "scripts/check_tag_version.py"
_BUILD_MARKER = "python -m build"


def _steps(workflow: dict, job: str) -> list[dict]:
    return list(workflow.get("jobs", {}).get(job, {}).get("steps", []) or [])


def _index(steps: list[dict], needle: str) -> int | None:
    for i, step in enumerate(steps):
        if needle in str(step.get("run", "")):
            return i
    return None


def _needs(workflow: dict, job: str) -> list[str]:
    needs = workflow.get("jobs", {}).get(job, {}).get("needs", [])
    return [needs] if isinstance(needs, str) else list(needs or [])


def _guard_problems(workflow: dict) -> list[str]:
    """Stable names for each way the release guard can be missing or misplaced."""
    problems: list[str] = []
    steps = _steps(workflow, "build")
    guard = _index(steps, _GUARD_SCRIPT)
    build = _index(steps, _BUILD_MARKER)
    if guard is None:
        problems.append("release-guard-missing")
    elif build is None or guard >= build:
        problems.append("release-guard-after-build")
    if "build" not in _needs(workflow, "publish"):
        problems.append("publish-not-gated-on-build")
    return problems


def _real() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


class TestReleaseWorkflowGuard:
    def test_real_workflow_has_no_guard_problems(self) -> None:
        assert _guard_problems(_real()) == []

    def test_plant_guard_removed(self) -> None:
        wf = copy.deepcopy(_real())
        steps = wf["jobs"]["build"]["steps"]
        wf["jobs"]["build"]["steps"] = [
            s for s in steps if _GUARD_SCRIPT not in str(s.get("run", ""))
        ]
        assert _guard_problems(wf) == ["release-guard-missing"]

    def test_plant_guard_after_build(self) -> None:
        wf = copy.deepcopy(_real())
        steps = wf["jobs"]["build"]["steps"]
        guard = next(s for s in steps if _GUARD_SCRIPT in str(s.get("run", "")))
        steps.remove(guard)
        steps.append(guard)
        assert _guard_problems(wf) == ["release-guard-after-build"]

    def test_plant_publish_not_gated_on_build(self) -> None:
        wf = copy.deepcopy(_real())
        wf["jobs"]["publish"].pop("needs", None)
        assert _guard_problems(wf) == ["publish-not-gated-on-build"]
