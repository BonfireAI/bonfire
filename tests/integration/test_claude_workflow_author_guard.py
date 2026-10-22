# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract test: no workflow runs the Claude agent on outsider-written text.

``.github/workflows/claude.yml`` ran an agent whose prompt was the body of an
issue or comment. Its author check let only OWNER/MEMBER/COLLABORATOR trigger
it, but once a trusted account mentioned the bot on an outsider's issue or
pull request, the agent still read the outsider's text, and it ran with a
token that could write to the repository. The workflow had gone unused, so it
was removed; its history stays in git.

This module now pins the state that replaced it, by reading every file under
``.github/workflows/`` with ``yaml.safe_load``:

* no workflow that uses an ``anthropics/claude-code-action`` step (any
  version) declares a trigger whose event body an outsider writes;
* ``claude.yml`` itself does not exist;
* a control proves the checker can fail, and can also pass, on in-memory
  samples, so a green run here is evidence rather than a vacuous loop.

Breadcrumb: this file previously pinned claude.yml's per-trigger
``author_association`` allow-list guard; that contract retired with the file.
"""

from __future__ import annotations

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"
REMOVED_WORKFLOW = WORKFLOW_DIR / "claude.yml"
REVIEW_WORKFLOW = WORKFLOW_DIR / "claude-code-review.yml"

#: Step ``uses:`` prefix of the agent action, matched with any ``@version``.
AGENT_ACTION = "anthropics/claude-code-action"

#: Triggers whose event carries a body an outsider can write. Each one hands
#: that body to the agent as its instructions, whoever mentioned the bot.
OUTSIDER_BODY_TRIGGERS = frozenset(
    {
        "issue_comment",
        "issues",
        "pull_request_review",
        "pull_request_review_comment",
        "discussion",
        "discussion_comment",
    }
)


def _triggers(workflow: dict) -> set[str]:
    """Return the trigger names a workflow declares, in any ``on:`` shape.

    PyYAML resolves the bare key ``on`` to the boolean ``True`` (YAML 1.1
    truthy), so both spellings are read. ``on:`` may be a string, a list or a
    mapping; all three are normalised to a set of names.
    """
    section = workflow.get("on", workflow.get(True))
    if isinstance(section, str):
        return {section}
    if isinstance(section, dict):
        return {str(name) for name in section}
    if isinstance(section, list):
        return {str(name) for name in section}
    return set()


def _uses_agent(workflow: dict) -> bool:
    """True when any step in any job uses the Claude agent action."""
    jobs = workflow.get("jobs") or {}
    for job in jobs.values():
        for step in (job or {}).get("steps") or []:
            uses = str((step or {}).get("uses", ""))
            if uses == AGENT_ACTION or uses.startswith(f"{AGENT_ACTION}@"):
                return True
    return False


def outsider_trigger_violations(workflow: dict) -> list[str]:
    """Return the outsider-body triggers an agent workflow declares, sorted.

    An empty list means the workflow is compliant: either it does not run
    the agent, or it runs it only on triggers whose body an outsider cannot
    hand to the agent as instructions.
    """
    if not _uses_agent(workflow):
        return []
    return sorted(_triggers(workflow) & OUTSIDER_BODY_TRIGGERS)


def _workflow_files() -> list[Path]:
    return sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])


def _load(path: Path) -> dict:
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), f"{path.name}: expected a YAML mapping, got {type(loaded)}"
    return loaded


#: In-memory control samples. Both use the agent action; only the trigger
#: differs, so the control isolates the rule under test.
_AGENT_STEP = {"name": "Run agent", "uses": f"{AGENT_ACTION}@v1"}
COMMENT_TRIGGERED_SAMPLE: dict = {
    True: {"issue_comment": {"types": ["created"]}},
    "jobs": {"agent": {"runs-on": "ubuntu-latest", "steps": [_AGENT_STEP]}},
}
PULL_REQUEST_ONLY_SAMPLE: dict = {
    "on": {"pull_request": {"types": ["opened"]}},
    "jobs": {"agent": {"runs-on": "ubuntu-latest", "steps": [_AGENT_STEP]}},
}


def test_checker_sees_at_least_one_workflow_file() -> None:
    """Denominator rod: the tree scan below must have something to scan."""
    files = _workflow_files()
    assert len(files) > 0, (
        f"found 0 workflow files under {WORKFLOW_DIR.relative_to(REPO_ROOT)}; "
        "the outsider-trigger scan would pass vacuously"
    )


def test_no_agent_workflow_declares_an_outsider_body_trigger() -> None:
    files = _workflow_files()
    offenders = {}
    for path in files:
        found = outsider_trigger_violations(_load(path))
        if found:
            offenders[path.name] = found
    assert len(files) > 0, "checked 0 workflow files; the scan is vacuous"
    assert not offenders, (
        f"checked {len(files)} workflow file(s); {len(offenders)} run the Claude agent on "
        f"triggers whose body an outsider writes: {offenders}"
    )


def test_comment_triggered_agent_workflow_is_removed() -> None:
    assert not REMOVED_WORKFLOW.exists(), (
        f"{REMOVED_WORKFLOW.relative_to(REPO_ROOT)} exists; it ran the agent on issue and "
        "comment bodies with a write-capable token and must stay removed"
    )


def test_control_checker_flags_a_comment_triggered_agent_sample() -> None:
    """Control rod: the checker can fail (the ``True`` key spelling included)."""
    found = outsider_trigger_violations(COMMENT_TRIGGERED_SAMPLE)
    assert found == ["issue_comment"], (
        f"checked 1 sample (issue_comment + {AGENT_ACTION}); expected 1 violation "
        f"['issue_comment'], got {len(found)}: {found}"
    )


def test_control_checker_passes_a_pull_request_only_agent_sample() -> None:
    """Control rod: the checker can pass, so it does not flag every agent workflow."""
    found = outsider_trigger_violations(PULL_REQUEST_ONLY_SAMPLE)
    assert found == [], (
        f"checked 1 sample (pull_request + {AGENT_ACTION}); expected 0 violations, "
        f"got {len(found)}: {found}"
    )


def test_review_workflow_runs_the_agent_and_passes_the_checker() -> None:
    """The pull_request review workflow is an agent workflow and is compliant.

    Asserting it uses the agent first keeps the pass from being vacuous: a
    checker that missed the action step would report nothing for any file.
    """
    workflow = _load(REVIEW_WORKFLOW)
    assert _uses_agent(workflow), (
        f"{REVIEW_WORKFLOW.name}: no {AGENT_ACTION} step detected; the checker would "
        "pass it without inspecting its triggers"
    )
    found = outsider_trigger_violations(workflow)
    assert found == [], (
        f"{REVIEW_WORKFLOW.name}: checked {len(_triggers(workflow))} trigger(s); "
        f"{len(found)} outsider-body trigger(s) found: {found}"
    )
