# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Every workflow ``uses:`` value is pinned to a recorded commit SHA on a current runtime.

``_pin_problems`` is a pure helper: it takes parsed workflows and returns readable
problem lines, so the real files and the planted breakages are judged by one function.
The ``uses:`` values come from the parsed YAML, so a pin that exists only in a comment
can never satisfy the contract.

The same file exists on the main branch with a larger table; keep the checker functions
identical between the branches and change only the table.
"""

from __future__ import annotations

import copy
import re
from pathlib import Path

import yaml

from tests.unit.test_release_workflow_guard import PUBLISHER_BUNDLES

WORKFLOW_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"

# SHAs are commits resolved from each tag through the GitHub API (annotated tags
# peeled); the runtime is ``runs.using`` from the action's ``action.yml`` at that
# commit. To bump an action, change the workflow line and this table in the same commit.
ACTION_PINS: dict[tuple[str, str], tuple[str, str]] = {
    ("actions/checkout", "df4cb1c069e1874edd31b4311f1884172cec0e10"): ("v6.0.3", "node24"),
    ("actions/setup-python", "a309ff8b426b58ec0e2a45f0f869d46889d02405"): ("v6.2.0", "node24"),
    ("actions/upload-artifact", "cf430e030ddbb5b0abf93d22962f4752f3646cd9"): ("v7.0.2", "node24"),
    ("actions/download-artifact", "9000827ccba6bdab643e8b6fd33ac0654aef8333"): (
        "v8.0.2",
        "node24",
    ),
}

ALLOWED_RUNTIMES = frozenset({"node24", "composite", "docker", "workflow"})
_PUBLISHER = "pypa/gh-action-pypi-publish"
_SHA_RE = re.compile(r"[0-9a-f]{40}")
_USES_RE = re.compile(r"(?P<name>[^@\s]+)@(?P<ref>\S+)")


def _uses_values(workflow: dict) -> list[tuple[str, str]]:
    """Return ``(job, value)`` for every job-level and step-level ``uses``."""
    found: list[tuple[str, str]] = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        if not isinstance(job, dict):
            continue
        if "uses" in job:
            found.append((job_name, str(job["uses"])))
        for step in job.get("steps") or []:
            if isinstance(step, dict) and "uses" in step:
                found.append((job_name, str(step["uses"])))
    return found


def _count_uses(workflows: dict[str, dict]) -> int:
    return sum(len(_uses_values(wf)) for wf in workflows.values())


def _value_problems(
    where: str,
    value: str,
    pins: dict[tuple[str, str], tuple[str, str]],
    publisher_shas: set[str],
    used: set[tuple[str, str]],
) -> list[str]:
    if value.startswith("./"):
        return []
    match = _USES_RE.fullmatch(value)
    if match is None or not _SHA_RE.fullmatch(match["ref"]):
        return [f"{where}: uses {value!r} is not pinned to a 40-hex commit SHA"]
    name, sha = match["name"], match["ref"]
    if name == _PUBLISHER:
        if sha not in publisher_shas:
            return [f"{where}: publisher SHA {sha} is not in PUBLISHER_BUNDLES"]
        return []
    used.add((name, sha))
    if (name, sha) not in pins:
        return [f"{where}: {name}@{sha} is not recorded in ACTION_PINS"]
    return []


def _pin_problems(
    workflows: dict[str, dict],
    pins: dict[tuple[str, str], tuple[str, str]],
    publisher_shas: set[str],
) -> list[str]:
    """Readable problem lines for each way a workflow action pin can be wrong."""
    if not workflows or _count_uses(workflows) == 0:
        return ["VOID: no workflow files or no `uses:` values were found to judge"]
    problems: list[str] = []
    used: set[tuple[str, str]] = set()
    for file_name, workflow in sorted(workflows.items()):
        for job, value in _uses_values(workflow):
            where = f"{file_name} job {job}"
            problems += _value_problems(where, value, pins, publisher_shas, used)
    for key, (_tag, runtime) in sorted(pins.items()):
        if runtime not in ALLOWED_RUNTIMES:
            problems.append(f"{key[0]}@{key[1]}: runtime {runtime!r} is not allowed")
        if key not in used:
            problems.append(f"{key[0]}@{key[1]}: record is stale, no workflow uses it")
    return problems


def _real_workflows() -> dict[str, dict]:
    files = sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])
    return {p.name: yaml.safe_load(p.read_text()) or {} for p in files}


def _publisher_shas() -> set[str]:
    return set(PUBLISHER_BUNDLES)


def _mini(value: str, job: str = "build") -> dict[str, dict]:
    return {"x.yml": {"jobs": {job: {"steps": [{"uses": value}]}}}}


_CHECKOUT = ("actions/checkout", "df4cb1c069e1874edd31b4311f1884172cec0e10")
_CHECKOUT_USES = "{}@{}".format(*_CHECKOUT)
_PUBLISH_SHA = next(iter(PUBLISHER_BUNDLES))


class TestWorkflowActionPins:
    def test_real_workflows_have_no_pin_problems(self) -> None:
        assert _pin_problems(_real_workflows(), ACTION_PINS, _publisher_shas()) == []

    def test_denominator_comes_from_the_directory(self) -> None:
        workflows = _real_workflows()
        on_disk = list(WORKFLOW_DIR.glob("*.yml")) + list(WORKFLOW_DIR.glob("*.yaml"))
        assert len(workflows) == len(on_disk) > 0
        assert _count_uses(workflows) > 0

    def test_void_when_nothing_to_judge(self) -> None:
        problems = _pin_problems({}, ACTION_PINS, _publisher_shas())
        assert len(problems) == 1 and problems[0].startswith("VOID:")

    def test_void_when_no_uses_values(self) -> None:
        wf = {"x.yml": {"jobs": {"j": {"steps": [{"run": "true"}]}}}}
        problems = _pin_problems(wf, ACTION_PINS, _publisher_shas())
        assert problems and problems[0].startswith("VOID:")

    def test_table_runtimes_are_current(self) -> None:
        for key, (_tag, runtime) in ACTION_PINS.items():
            assert runtime in ALLOWED_RUNTIMES, f"{key}: runtime {runtime!r}"

    def test_table_shas_are_full_hex(self) -> None:
        for name, sha in ACTION_PINS:
            assert _SHA_RE.fullmatch(sha), f"{name}: {sha!r} is not 40 lowercase hex"

    def test_tag_ref_fails(self) -> None:
        problems = _pin_problems(_mini("actions/checkout@v4"), {}, set())
        assert any("'actions/checkout@v4' is not pinned" in p for p in problems)

    def test_branch_ref_fails(self) -> None:
        problems = _pin_problems(_mini("actions/checkout@main"), {}, set())
        assert any("'actions/checkout@main' is not pinned" in p for p in problems)

    def test_short_sha_fails(self) -> None:
        problems = _pin_problems(_mini("actions/checkout@df4cb1c"), {}, set())
        assert any("'actions/checkout@df4cb1c' is not pinned" in p for p in problems)

    def test_problem_names_file_and_job(self) -> None:
        problems = _pin_problems(_mini("actions/checkout@v4", job="lint"), {}, set())
        assert any(p.startswith("x.yml job lint:") for p in problems)

    def test_unrecorded_sha_fails(self) -> None:
        sha = "0123456789abcdef0123456789abcdef01234567"
        pins = {_CHECKOUT: ("v6.0.3", "node24")}
        problems = _pin_problems(_mini(f"actions/checkout@{sha}"), pins, set())
        assert any(f"actions/checkout@{sha} is not recorded" in p for p in problems)

    def test_node20_entry_in_use_fails(self) -> None:
        pins = {_CHECKOUT: ("v4.0.0", "node20")}
        problems = _pin_problems(_mini(_CHECKOUT_USES), pins, set())
        assert any("runtime 'node20' is not allowed" in p for p in problems)

    def test_stale_entry_fails(self) -> None:
        other = ("actions/setup-python", "a309ff8b426b58ec0e2a45f0f869d46889d02405")
        pins = {_CHECKOUT: ("v6.0.3", "node24"), other: ("v6.2.0", "node24")}
        problems = _pin_problems(_mini(_CHECKOUT_USES), pins, set())
        assert any("actions/setup-python" in p and "stale" in p for p in problems)

    def test_unknown_publisher_sha_fails(self) -> None:
        sha = "f" * 40
        wf = _mini(f"{_PUBLISHER}@{sha}")
        problems = _pin_problems(wf, {}, {_PUBLISH_SHA})
        assert any(f"publisher SHA {sha} is not in PUBLISHER_BUNDLES" in p for p in problems)

    def test_known_publisher_sha_passes(self) -> None:
        wf = _mini(f"{_PUBLISHER}@{_PUBLISH_SHA}")
        assert _pin_problems(wf, {}, {_PUBLISH_SHA}) == []

    def test_job_level_reusable_workflow_tag_fails(self) -> None:
        wf = {"q.yml": {"jobs": {"gate": {"uses": "org/repo/.github/workflows/g.yml@v1"}}}}
        problems = _pin_problems(wf, {}, set())
        assert any("q.yml job gate:" in p and "@v1'" in p for p in problems)

    def test_local_action_is_allowed_and_counted(self) -> None:
        wf = _mini("./.github/actions/local")
        assert _count_uses(wf) == 1
        assert _pin_problems(wf, {}, set()) == []

    def test_planted_tag_in_real_workflow_is_caught(self) -> None:
        workflows = copy.deepcopy(_real_workflows())
        step = next(
            s
            for wf in workflows.values()
            for job in (wf.get("jobs") or {}).values()
            for s in job.get("steps") or []
            if str(s.get("uses", "")).startswith("actions/checkout@")
        )
        step["uses"] = "actions/checkout@v4"
        problems = _pin_problems(workflows, ACTION_PINS, _publisher_shas())
        assert any("'actions/checkout@v4' is not pinned" in p for p in problems)
