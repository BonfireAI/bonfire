"""The release workflow must run the tag/version guard before any build or upload.

``_guard_problems`` is a pure rod over the parsed workflow. The real file must
yield no problems; each plant (a deep copy with one defect) must yield exactly
its own stable name, so the rod demonstrably has teeth.
"""

from __future__ import annotations

import copy
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
GUARD_SCRIPT = "scripts/check_tag_version.py"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _run(step: dict) -> str:
    return str(step.get("run", ""))


def _guard_problems(workflow: dict) -> list[str]:
    problems: list[str] = []
    jobs = workflow.get("jobs", {})
    steps = jobs.get("build", {}).get("steps", [])
    guard_idx = next((i for i, s in enumerate(steps) if GUARD_SCRIPT in _run(s)), None)
    build_idx = next((i for i, s in enumerate(steps) if "python -m build" in _run(s)), None)
    if guard_idx is None:
        problems.append("release-guard-missing")
    elif build_idx is None or guard_idx >= build_idx:
        problems.append("release-guard-after-build")
    needs = jobs.get("publish", {}).get("needs", [])
    needs = [needs] if isinstance(needs, str) else list(needs)
    if "build" not in needs:
        problems.append("publish-not-gated-on-build")
    return problems


def _guard_index(workflow: dict) -> int:
    steps = workflow["jobs"]["build"]["steps"]
    return next(i for i, s in enumerate(steps) if GUARD_SCRIPT in _run(s))


def test_real_release_workflow_has_no_guard_problems() -> None:
    assert _guard_problems(_load()) == []


def test_plant_guard_step_removed() -> None:
    wf = copy.deepcopy(_load())
    steps = wf["jobs"]["build"]["steps"]
    del steps[_guard_index(wf)]
    assert _guard_problems(wf) == ["release-guard-missing"]


def test_plant_guard_step_after_build() -> None:
    wf = copy.deepcopy(_load())
    steps = wf["jobs"]["build"]["steps"]
    guard = steps.pop(_guard_index(wf))
    build_idx = next(i for i, s in enumerate(steps) if "python -m build" in _run(s))
    steps.insert(build_idx + 1, guard)
    assert _guard_problems(wf) == ["release-guard-after-build"]


def test_plant_publish_needs_dropped() -> None:
    wf = copy.deepcopy(_load())
    wf["jobs"]["publish"].pop("needs", None)
    assert _guard_problems(wf) == ["publish-not-gated-on-build"]
