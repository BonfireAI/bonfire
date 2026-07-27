# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract test for the agent workflow's author allow-list.

``.github/workflows/claude.yml`` runs an agent whose prompt is the body of
an issue or comment, in the base-repository context, with the repository's
Claude credential available to it. Two things follow:

* the run is billed to the repository owner, and
* the instructions the agent follows are written by whoever filed the event.

So the ``@claude`` mention is not a gate. The gate is ``author_association``.
This test pins that guard structurally: every trigger declared under ``on:``
must have a matching clause in the job's ``if:`` that both checks the mention
*and* restricts ``author_association`` to the trusted set.

The trigger list is read from the workflow's own ``on:`` block rather than
hard-coded, so adding a new trigger without adding a guard clause fails here
instead of shipping. Conversely the allow-list values are written out
literally, so widening them in the workflow fails the test rather than being
absorbed by it.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent.parent
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "claude.yml"

#: The only associations trusted to spend the repository's credential and to
#: choose what the agent is told to do. Anything else -- CONTRIBUTOR,
#: FIRST_TIME_CONTRIBUTOR, FIRST_TIMER, MANNEQUIN, NONE -- is the internet.
TRUSTED_ASSOCIATIONS = ("OWNER", "MEMBER", "COLLABORATOR")

#: Untrusted associations that must never appear in the allow-list. ``NONE``
#: is the association of an arbitrary account with no relationship to the
#: repository, i.e. the anonymous case this guard exists to stop.
UNTRUSTED_ASSOCIATIONS = (
    "NONE",
    "CONTRIBUTOR",
    "FIRST_TIME_CONTRIBUTOR",
    "FIRST_TIMER",
    "MANNEQUIN",
)

#: For each trigger, the event field that carries the ``@claude`` text and
#: therefore the field whose author must be checked. Checking the wrong
#: object's association (e.g. the pull request's author for a review comment)
#: would let an outsider's comment ride in on a trusted author's PR.
ASSOCIATION_FIELD_BY_TRIGGER = {
    "issue_comment": "github.event.comment.author_association",
    "pull_request_review_comment": "github.event.comment.author_association",
    "pull_request_review": "github.event.review.author_association",
    "issues": "github.event.issue.author_association",
}


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text())


def _triggers(workflow: dict) -> list[str]:
    """Return the trigger names under ``on:``.

    PyYAML resolves the bare key ``on`` to the boolean ``True`` (YAML 1.1
    truthy), so accept either spelling rather than depending on the loader.
    """
    section = workflow.get("on", workflow.get(True))
    assert isinstance(section, dict), "workflow must declare a mapping of triggers"
    return sorted(section)


def _job_condition(workflow: dict) -> str:
    jobs = workflow["jobs"]
    assert len(jobs) == 1, (
        f"this test guards a single job; found {sorted(jobs)}. "
        "A second job needs its own author guard and its own assertion here."
    )
    return next(iter(jobs.values()))["if"]


def test_workflow_declares_triggers_and_a_condition() -> None:
    """Control rod: the assertions below must have something to check.

    Every other test in this module iterates over the trigger list. If that
    list were empty -- a renamed key, a loader change, a restructured file --
    those tests would pass vacuously while guarding nothing.
    """
    workflow = _workflow()
    triggers = _triggers(workflow)
    assert triggers, "no triggers found; the guard tests below would be vacuous"
    assert set(triggers) <= set(ASSOCIATION_FIELD_BY_TRIGGER), (
        f"unmapped trigger(s): {sorted(set(triggers) - set(ASSOCIATION_FIELD_BY_TRIGGER))}. "
        "Add the event field carrying the mention to ASSOCIATION_FIELD_BY_TRIGGER "
        "and a guard clause to the workflow."
    )
    assert _job_condition(workflow).strip(), "the job must carry an if: condition"


@pytest.mark.parametrize("association", TRUSTED_ASSOCIATIONS)
def test_condition_names_each_trusted_association(association: str) -> None:
    assert association in _job_condition(_workflow()), f"the allow-list must name {association}"


@pytest.mark.parametrize("association", UNTRUSTED_ASSOCIATIONS)
def test_condition_never_names_an_untrusted_association(association: str) -> None:
    condition = _job_condition(_workflow())
    # FIRST_TIME_CONTRIBUTOR contains CONTRIBUTOR as a substring, so compare
    # against the whole-word occurrences rather than a naive `in`.
    words = set(condition.replace('"', " ").replace(",", " ").split())
    assert association not in words, (
        f"{association} must not be trusted to spend the repository credential "
        "or to author the agent's prompt"
    )


def test_every_trigger_is_guarded_by_its_own_association_check() -> None:
    """Each declared trigger has a clause pairing mention + author check.

    A filter on three of four triggers is a hole with extra steps, so this
    walks the ``on:`` block rather than a hard-coded list.
    """
    workflow = _workflow()
    condition = _job_condition(workflow)
    checked = 0
    for trigger in _triggers(workflow):
        assert f"github.event_name == '{trigger}'" in condition, (
            f"trigger {trigger!r} is accepted by on: but has no clause in if:"
        )
        field = ASSOCIATION_FIELD_BY_TRIGGER[trigger]
        assert field in condition, (
            f"trigger {trigger!r} is not gated on {field}; without it any account "
            "can run the agent on instructions of its choosing"
        )
        checked += 1
    assert checked == len(ASSOCIATION_FIELD_BY_TRIGGER), (
        f"checked {checked} trigger(s); expected all {len(ASSOCIATION_FIELD_BY_TRIGGER)}"
    )


def test_association_check_count_matches_trigger_count() -> None:
    """No clause may check the mention without also checking the author.

    Counting is what catches the half-guarded shape: a clause that keeps its
    ``contains(..., '@claude')`` test but loses its allow-list still parses,
    still matches the trigger name, and still runs for anyone.
    """
    workflow = _workflow()
    condition = _job_condition(workflow)
    triggers = _triggers(workflow)
    assert condition.count("author_association") == len(triggers), (
        f"{condition.count('author_association')} author checks for {len(triggers)} "
        "triggers; every trigger needs exactly one"
    )
    assert condition.count("fromJSON") == len(triggers), (
        "every trigger's clause must carry its own allow-list"
    )
