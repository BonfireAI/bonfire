# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``claude.yml`` only dispatches the agent for trusted authors.

This repository is public, and every trigger in ``.github/workflows/claude.yml``
runs in the base-repo context with access to ``secrets``. The text that mentions
``@claude`` becomes the agent's prompt, so an unfiltered workflow hands any
account on the internet two things at once: the maintainer's Claude budget, and
the choice of instructions the agent executes.

The guard is an ``author_association`` allow-list on the job's ``if:``. These
tests pin it. They are deliberately written against the *trigger list* rather
than against a fixed expression string, because the regression that actually
threatens this file is adding a fifth trigger and forgetting its filter — not
rewording the four that exist. A test that only grep'd for today's wording would
pass that regression.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

WORKFLOW_PATH = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "claude.yml"

#: Associations permitted to drive the agent. Anything outside this set — most
#: notably ``CONTRIBUTOR``, which merely means "has had a PR merged here" — is
#: untrusted for the purpose of spending money and supplying a prompt.
TRUSTED_ASSOCIATIONS = frozenset({"OWNER", "MEMBER", "COLLABORATOR"})

#: Every webhook event this workflow may listen to, mapped to the expression
#: path holding the association of the author who supplies the prompt text.
#: For comments and reviews that is the comment/review author, NOT the issue
#: author — the body being used as the prompt is theirs.
TRIGGER_AUTHOR_FIELD: dict[str, str] = {
    "issue_comment": "github.event.comment.author_association",
    "pull_request_review_comment": "github.event.comment.author_association",
    "pull_request_review": "github.event.review.author_association",
    "issues": "github.event.issue.author_association",
}

#: ``contains(fromJSON('[...]'), <field>)`` — the array form, which is an exact
#: membership test. The plain-string form ``contains('OWNER MEMBER', x)`` is a
#: substring match and is rejected by ``test_membership_tests_use_json_arrays``.
_MEMBERSHIP_RE = re.compile(
    r"contains\(\s*fromJSON\(\s*'(?P<array>\[[^\]]*\])'\s*\)\s*,\s*(?P<field>[A-Za-z0-9_.]+)\s*\)"
)


@pytest.fixture(scope="module")
def workflow() -> dict:
    """The parsed workflow document."""
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def triggers(workflow: dict) -> list[str]:
    """Event names under ``on:``.

    PyYAML resolves the bare key ``on`` to the boolean ``True`` (YAML 1.1
    treats it as a truthy word), so the document is keyed by ``True`` rather
    than by the string. Accept either spelling.
    """
    on_block = workflow.get("on", workflow.get(True))
    assert isinstance(on_block, dict), f"unreadable `on:` block in {WORKFLOW_PATH}"
    return sorted(on_block)


@pytest.fixture(scope="module")
def job_conditions(workflow: dict) -> dict[str, str]:
    """Each job's ``if:`` expression, keyed by job id."""
    return {job_id: str(job.get("if", "")) for job_id, job in workflow["jobs"].items()}


def test_workflow_file_exists() -> None:
    assert WORKFLOW_PATH.is_file(), f"missing {WORKFLOW_PATH}"


def test_every_trigger_has_a_known_author_field(triggers: list[str]) -> None:
    """A trigger with no mapped author field has no filter we can verify.

    This is the load-bearing assertion. Adding a trigger to ``on:`` fails here
    until someone decides *whose* association gates it and records that
    decision in ``TRIGGER_AUTHOR_FIELD``.
    """
    unmapped = [event for event in triggers if event not in TRIGGER_AUTHOR_FIELD]
    assert not unmapped, (
        f"{unmapped} can trigger the agent but has no author_association field mapped. "
        "Add the field to TRIGGER_AUTHOR_FIELD and gate the job on it."
    )


def test_every_trigger_is_gated_on_its_own_author_association(
    triggers: list[str], job_conditions: dict[str, str]
) -> None:
    """Every listened-for event gates on the association of *its* prompt author."""
    conditions = " ".join(job_conditions.values())
    assert conditions.strip(), "no job carries an `if:` — the workflow is ungated"

    for event in triggers:
        field = TRIGGER_AUTHOR_FIELD[event]
        assert field in conditions, (
            f"`on: {event}` is not gated on {field}. Any account able to produce that "
            "event could spend the maintainer's budget and choose the agent's prompt."
        )


def test_membership_tests_use_json_arrays(job_conditions: dict[str, str]) -> None:
    """Association checks must be exact membership, not substring matching.

    ``contains('OWNER MEMBER COLLABORATOR', x)`` is a substring test and would
    accept a crafted value; ``contains(fromJSON('["OWNER", ...]'), x)`` is not.
    """
    for job_id, condition in job_conditions.items():
        if "author_association" not in condition:
            continue
        checked = {
            match.group("field")
            for match in _MEMBERSHIP_RE.finditer(condition)
            if match.group("field").endswith("author_association")
        }
        referenced = set(re.findall(r"github\.event\.[A-Za-z0-9_.]*author_association", condition))
        assert referenced, f"job `{job_id}`: no association field found to check"
        assert referenced == checked, (
            f"job `{job_id}`: {sorted(referenced - checked)} is referenced but not inside a "
            "contains(fromJSON([...]), field) membership test."
        )


def test_allow_list_is_exactly_the_trusted_set(job_conditions: dict[str, str]) -> None:
    """Every allow-list in the file names the trusted set and nothing more.

    Asserting equality — rather than "CONTRIBUTOR is absent" — means a widened
    list fails here whatever the new entry happens to be called.
    """
    found = 0
    for job_id, condition in job_conditions.items():
        for match in _MEMBERSHIP_RE.finditer(condition):
            if not match.group("field").endswith("author_association"):
                continue
            entries = frozenset(re.findall(r'"([^"]+)"', match.group("array")))
            assert entries == TRUSTED_ASSOCIATIONS, (
                f"job `{job_id}`: allow-list {sorted(entries)} != {sorted(TRUSTED_ASSOCIATIONS)}"
            )
            found += 1

    # Without this, a file containing zero membership tests would vacuously
    # satisfy the loop above and report green.
    assert found >= len(set(TRIGGER_AUTHOR_FIELD.values())), (
        f"only {found} association membership test(s) found; expected at least one per "
        "distinct author field so no trigger rides through unchecked."
    )
