# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight RED tests — StewardHandler returns SKIPPED when no merge happens.

Pre-fix: ``StewardHandler.handle`` returned ``TaskStatus.COMPLETED``
unconditionally — regardless of whether the verdict was ``approve``,
``reject``, or empty, and regardless of whether a PR number was present.
Downstream gates and CLI summaries saw the closer stage as "completed"
when in reality the PR was rejected (verdict != "approve") or never
identifiable (pr_number missing). The closer's contract is to seal the
work; no-op success makes the pipeline lie about outcomes.

The fix returns ``TaskStatus.COMPLETED`` only when an actual merge
happened (``verdict == "approve" and pr_number is not None``), and
``TaskStatus.SKIPPED`` otherwise — preserving the existing return-an-
envelope path (no exception) while reporting the truthful status.

Existing ``test_steward_handler.py`` already verifies that ``reject``
verdict does NOT trigger ``merge_pr`` (a behavioral assertion on the
github_client mock). What it does NOT verify is the resulting
``TaskStatus`` — that's the gap this Knight fills.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

try:
    from bonfire.github.mock import MockGitHubClient  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    MockGitHubClient = None  # type: ignore[assignment,misc]

try:
    from bonfire.handlers.steward import StewardHandler  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    StewardHandler = None  # type: ignore[assignment,misc]

from bonfire.models.envelope import (
    META_PR_NUMBER,
    Envelope,
    TaskStatus,
)
from bonfire.models.plan import StageSpec

if TYPE_CHECKING:
    pass


pytestmark = pytest.mark.skipif(
    StewardHandler is None or MockGitHubClient is None,
    reason="v0.1 handler not yet ported: StewardHandler / MockGitHubClient missing",
)


# ---------------------------------------------------------------------------
# Fixtures (mirror test_steward_handler.py for consistency)
# ---------------------------------------------------------------------------


@pytest.fixture()
def github_client():  # noqa: ANN201
    return MockGitHubClient()


@pytest.fixture()
def steward_stage() -> StageSpec:
    return StageSpec(name="steward", agent_name="pr-merger", role="closer")


@pytest.fixture()
def base_envelope() -> Envelope:
    return Envelope(task="seal-the-work")


@pytest.fixture()
def handler(github_client) -> Any:  # noqa: ANN001, ANN201
    return StewardHandler(github_client=github_client)


async def _seed_pr(gh: Any) -> int:
    pr = await gh.create_pr(title="seed", head="feature", base="master")
    return pr.number


# ---------------------------------------------------------------------------
# Status contract — three non-merge cases all return SKIPPED.
# ---------------------------------------------------------------------------


class TestStatusReflectsActualMerge:
    """The returned TaskStatus reflects whether a merge actually happened."""

    async def test_reject_verdict_returns_skipped(
        self,
        handler,  # noqa: ANN001
        steward_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """verdict='reject' + pr_number present → SKIPPED (no merge happened)."""
        pr_number = await _seed_pr(github_client)
        prior = {"wizard": "reject", META_PR_NUMBER: str(pr_number)}

        result = await handler.handle(steward_stage, base_envelope, prior)

        assert result.status == TaskStatus.SKIPPED, (
            f"Expected SKIPPED on reject verdict (no merge happened); "
            f"got {result.status}. Pre-fix bug: status was hardcoded to "
            f"COMPLETED regardless of verdict, making the pipeline lie about "
            f"actual outcomes."
        )

    async def test_empty_verdict_returns_skipped(
        self,
        handler,  # noqa: ANN001
        steward_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """No verdict key in prior_results → SKIPPED (no merge happened)."""
        pr_number = await _seed_pr(github_client)
        prior = {META_PR_NUMBER: str(pr_number)}  # No verdict key.

        result = await handler.handle(steward_stage, base_envelope, prior)

        assert result.status == TaskStatus.SKIPPED, (
            f"Expected SKIPPED on missing verdict; got {result.status}"
        )

    async def test_approve_without_pr_number_returns_skipped(
        self,
        handler,  # noqa: ANN001
        steward_stage: StageSpec,
        base_envelope: Envelope,
    ) -> None:
        """verdict='approve' but no PR number → SKIPPED (nothing to merge)."""
        prior = {"wizard": "approve"}  # No pr_number.

        result = await handler.handle(steward_stage, base_envelope, prior)

        assert result.status == TaskStatus.SKIPPED, (
            f"Expected SKIPPED when approve verdict has no PR number "
            f"(no merge possible); got {result.status}"
        )

    async def test_approve_with_pr_number_returns_completed(
        self,
        handler,  # noqa: ANN001
        steward_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """Regression guard: the only TRUE merge path still returns COMPLETED."""
        pr_number = await _seed_pr(github_client)
        prior = {"wizard": "approve", META_PR_NUMBER: str(pr_number)}

        result = await handler.handle(steward_stage, base_envelope, prior)

        assert result.status == TaskStatus.COMPLETED, (
            f"approve + pr_number is the actual-merge path — must stay COMPLETED. "
            f"Got {result.status}"
        )
        # Sanity: the merge actually fired.
        assert any(a["type"] == "merge_pr" for a in github_client.actions), (
            "merge_pr should have been invoked on the github client mock"
        )


class TestStatusPreservesEnvelopeStructure:
    """Returning SKIPPED must not mutate the rest of the envelope contract."""

    async def test_skipped_path_still_attaches_metadata(
        self,
        handler,  # noqa: ANN001
        steward_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """The SKIPPED-return path still records steward_verdict + steward_pr metadata.

        Downstream observers (cost rollup, session summary) read these
        metadata keys regardless of status. The status change is the only
        observable contract delta.
        """
        pr_number = await _seed_pr(github_client)
        prior = {"wizard": "reject", META_PR_NUMBER: str(pr_number)}

        result = await handler.handle(steward_stage, base_envelope, prior)

        assert result.status == TaskStatus.SKIPPED
        assert result.metadata.get("steward_verdict") == "reject"
        assert result.metadata.get("steward_pr") == str(pr_number)
        # Result string is preserved (it documents what happened, not status).
        assert "reject" in result.result
