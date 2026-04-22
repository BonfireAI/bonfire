"""Closer pipeline stage handler.

Merges approved PRs and closes associated issues. Not an LLM caller --
pure GitHub orchestration: read prior verdict + PR number, merge on
``approve``, post a completion comment, and close the ticket if a
``ticket_ref`` was carried on the envelope metadata.

The module exposes ``ROLE: AgentRole = AgentRole.CLOSER`` for generic-
vocabulary discipline. Display translation (closer -> "Herald") happens
in the display layer via ``ROLE_DISPLAY[ROLE].gamified``; this module
never hardcodes the gamified name in code.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import (
    META_PR_NUMBER,
    META_REVIEW_VERDICT,
    ErrorDetail,
    TaskStatus,
)

if TYPE_CHECKING:
    from bonfire.models.envelope import Envelope
    from bonfire.models.plan import StageSpec

# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.CLOSER


# ---------------------------------------------------------------------------
# Module-scope helpers
# ---------------------------------------------------------------------------


def _extract_pr_number(prior_results: dict[str, Any]) -> int | None:
    """Extract PR number from prior results."""
    raw = prior_results.get(META_PR_NUMBER)
    if raw is not None:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass

    bard_val = prior_results.get("bard", "")
    if bard_val:
        m = re.search(r"/pull/(\d+)", str(bard_val))
        if m:
            return int(m.group(1))

    return None


def _extract_verdict(prior_results: dict[str, Any]) -> str:
    """Extract review verdict from prior results (case-insensitive)."""
    verdict = prior_results.get(META_REVIEW_VERDICT, "")
    if verdict:
        return verdict.lower()

    wizard_val = prior_results.get("wizard", "")
    if wizard_val:
        return wizard_val.lower()

    return ""


def _extract_ticket_ref(envelope: Any) -> int | None:
    """Extract ticket reference from envelope metadata.

    Handles direct ``ticket_ref`` keys and the nested-metadata shape
    produced when factory helpers wrap a metadata dict under a
    ``"metadata"`` key.
    """
    ref = envelope.metadata.get("ticket_ref")
    if ref is not None:
        try:
            return int(ref)
        except (ValueError, TypeError):
            pass

    nested = envelope.metadata.get("metadata")
    if isinstance(nested, dict):
        ref = nested.get("ticket_ref")
        if ref is not None:
            try:
                return int(ref)
            except (ValueError, TypeError):
                pass

    return None


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class HeraldHandler:
    """Pipeline stage handler for the closer role.

    Merges an approved PR, posts a completion comment, and closes the
    associated ticket / issue. All GitHub failures are wrapped into a
    FAILED envelope with a peer-shape ``ErrorDetail``.
    """

    def __init__(self, *, github_client: Any) -> None:
        self._github_client = github_client

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Merge PR if approved, close issue, add completion comment."""
        try:
            pr_number = _extract_pr_number(prior_results)
            verdict = _extract_verdict(prior_results)

            if verdict == "approve" and pr_number is not None:
                await self._github_client.merge_pr(pr_number)

            ticket_ref = _extract_ticket_ref(envelope)

            issue_to_close: int | None = None
            if ticket_ref is not None:
                issue_to_close = ticket_ref
            elif "bard" in prior_results and verdict == "approve" and pr_number is not None:
                issue_to_close = pr_number

            if pr_number is not None and verdict == "approve":
                await self._github_client.add_comment(
                    pr_number,
                    f"Release agent: PR #{pr_number} merged. Pipeline complete.",
                )

            if issue_to_close is not None:
                await self._github_client.close_issue(issue_to_close)

            new_metadata = {
                **envelope.metadata,
                "herald_verdict": verdict,
                "herald_pr": str(pr_number) if pr_number else "",
            }
            return envelope.model_copy(
                update={
                    "metadata": new_metadata,
                    "status": TaskStatus.COMPLETED,
                    "result": f"closer: verdict={verdict}, pr={pr_number}",
                },
            )
        except Exception as exc:
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    stage_name=stage.name,
                ),
            )
