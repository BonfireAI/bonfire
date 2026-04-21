"""BON-342 W5.3 RED — HeraldHandler canonical synthesis.

Sage-synthesized from Knight A (Conservative Porter) + Knight B
(Generic-Vocabulary Modernizer).

Decisions locked here:

- D2 ADOPT: module-level ``ROLE: AgentRole = AgentRole.CLOSER``.
- D3 ADOPT: no hardcoded ``"Herald"`` string literal in code body.

Contract preserved from v1:

- Constructor: ``HeraldHandler(*, github_client)``.
- Protocol: satisfies ``StageHandler`` runtime_checkable.
- Happy path: approve verdict + pr_number -> merge_pr + add_comment +
  (optional) close_issue. Returns completed envelope.
- Cold path: verdict != "approve" -> does NOT merge.
- PR extraction: reads pr_number from prior_results, falls back to parsing
  any GitHub PR URL in a "bard" key, falls back to envelope metadata.
- Error path: GitHub failures wrapped in a FAILED envelope with
  ``ErrorDetail`` matching peer-handler shape.
"""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

try:
    from bonfire.github.mock import MockGitHubClient  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    MockGitHubClient = None  # type: ignore[assignment,misc]

try:
    from bonfire.handlers.herald import HeraldHandler  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    HeraldHandler = None  # type: ignore[assignment,misc]

from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import (
    META_PR_NUMBER,
    META_REVIEW_VERDICT,
    META_TICKET_REF,
    Artifact,
    Envelope,
    TaskStatus,
)
from bonfire.models.plan import StageSpec
from bonfire.naming import ROLE_DISPLAY


pytestmark = pytest.mark.skipif(
    HeraldHandler is None or MockGitHubClient is None,
    reason="v0.1 handler not yet ported: HeraldHandler / MockGitHubClient missing",
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def github_client():  # noqa: ANN201
    return MockGitHubClient()


@pytest.fixture()
def herald_stage() -> StageSpec:
    """Closer (file-stem: herald) stage spec."""
    return StageSpec(name="herald", agent_name="pr-merger", role="closer")


@pytest.fixture()
def base_envelope() -> Envelope:
    """Envelope used by Herald tests."""
    return Envelope(
        task="Implement feature X",
        context="Some context",
        artifacts=[
            Artifact(
                name="src/bonfire/feature_x.py",
                content="",
                artifact_type="file_written",
            ),
        ],
    )


@pytest.fixture()
def handler(github_client) -> Any:  # noqa: ANN001, ANN201
    return HeraldHandler(github_client=github_client)


async def _seed_pr(gh: Any) -> int:
    """Create a mock PR so merge_pr has a valid target."""
    pr = await gh.create_pr(title="seed", head="feature", base="master")
    return pr.number


# ---------------------------------------------------------------------------
# GENERIC-VOCABULARY DISCIPLINE (D2, D3)
# ---------------------------------------------------------------------------


class TestGenericVocabularyDiscipline:
    def test_module_exposes_role_constant_bound_to_closer(self) -> None:
        """herald.ROLE is AgentRole.CLOSER."""
        import bonfire.handlers.herald as herald_mod

        assert hasattr(herald_mod, "ROLE"), (
            "herald.py must expose a module-level ROLE constant bound to AgentRole.CLOSER."
        )
        assert herald_mod.ROLE is AgentRole.CLOSER
        assert isinstance(herald_mod.ROLE, AgentRole)

    def test_role_constant_value_is_closer_string(self) -> None:
        import bonfire.handlers.herald as herald_mod

        assert herald_mod.ROLE == "closer"

    def test_handler_class_docstring_cites_generic_role(self) -> None:
        assert HeraldHandler.__doc__ is not None
        assert "closer" in HeraldHandler.__doc__.lower()

    def test_handler_module_docstring_cites_generic_role(self) -> None:
        import bonfire.handlers.herald as herald_mod

        assert herald_mod.__doc__ is not None
        assert "closer" in herald_mod.__doc__.lower()

    def test_role_in_display_map_translates_to_herald(self) -> None:
        assert ROLE_DISPLAY["closer"].gamified == "Herald"
        assert ROLE_DISPLAY["closer"].professional == "Release Agent"

    def test_handler_source_does_not_hardcode_gamified_display(self) -> None:
        """D3: no ``"Herald"`` literal in code body (docstrings exempted)."""
        import bonfire.handlers.herald as herald_mod

        src = Path(herald_mod.__file__).read_text()
        lines = src.splitlines()
        offenders: list[tuple[int, str]] = []
        in_docstring = False
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.endswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            if '"Herald"' in line or "'Herald'" in line:
                offenders.append((idx, line))
        assert not offenders, (
            f"HeraldHandler source must not hardcode the gamified display 'Herald'. "
            f"Use ROLE_DISPLAY[ROLE].gamified. Offenders: {offenders}"
        )

    def test_role_matches_stage_spec_role_field(self, herald_stage: StageSpec) -> None:
        import bonfire.handlers.herald as herald_mod

        assert herald_stage.role == herald_mod.ROLE


# ---------------------------------------------------------------------------
# Construction + protocol conformance
# ---------------------------------------------------------------------------


class TestConstruction:
    def test_herald_handler_import(self) -> None:
        """HeraldHandler is importable from bonfire.handlers.herald."""
        from bonfire.handlers.herald import HeraldHandler as _HH  # noqa: F401

        assert _HH is not None

    def test_constructor_accepts_github_client(self, github_client) -> None:  # noqa: ANN001
        """Constructor accepts github_client kwarg."""
        handler = HeraldHandler(github_client=github_client)
        assert handler is not None

    def test_satisfies_stage_handler_protocol(self, github_client) -> None:  # noqa: ANN001
        from bonfire.protocols import StageHandler

        handler = HeraldHandler(github_client=github_client)
        assert isinstance(handler, StageHandler)

    def test_handle_signature_matches_stage_handler_protocol(self) -> None:
        """handle(stage, envelope, prior_results) -> Envelope is sealed."""
        sig = inspect.signature(HeraldHandler.handle)
        params = list(sig.parameters.keys())
        assert params == ["self", "stage", "envelope", "prior_results"]
        assert asyncio.iscoroutinefunction(HeraldHandler.handle)


# ---------------------------------------------------------------------------
# Merge-on-approve happy path
# ---------------------------------------------------------------------------


class TestMergeOnApprove:
    @pytest.mark.asyncio
    async def test_returns_envelope(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """handle() returns an Envelope."""
        await github_client.create_pr("feat", "feature/x", "master")
        prior = {
            "bard": "https://github.com/mock/repo/pull/1",
            "wizard": "approve",
        }
        result = await handler.handle(herald_stage, base_envelope, prior)
        assert isinstance(result, Envelope)

    @pytest.mark.asyncio
    async def test_approve_verdict_merges_pr(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """verdict='approve' + pr_number -> merge_pr called."""
        await github_client.create_pr("feat", "feature/x", "master")
        prior = {
            "bard": "https://github.com/mock/repo/pull/1",
            "wizard": "approve",
        }
        await handler.handle(herald_stage, base_envelope, prior)
        assert any(a["type"] == "merge_pr" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_approve_adds_completion_comment(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """Completion comment posted on approved PR."""
        await github_client.create_pr("feat", "feature/x", "master")
        prior = {
            "bard": "https://github.com/mock/repo/pull/1",
            "wizard": "approve",
        }
        await handler.handle(herald_stage, base_envelope, prior)
        assert any(a["type"] == "add_comment" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_approve_closes_issue_default_path(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """Default close_issue path fires on approved happy path."""
        await github_client.create_pr("feat", "feature/x", "master")
        prior = {
            "bard": "https://github.com/mock/repo/pull/1",
            "wizard": "approve",
        }
        await handler.handle(herald_stage, base_envelope, prior)
        assert any(a["type"] == "close_issue" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_approve_closes_ticket_when_ticket_ref_present(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        github_client,  # noqa: ANN001
    ) -> None:
        """META_TICKET_REF drives close_issue with the right issue number."""
        pr_number = await _seed_pr(github_client)
        envelope = Envelope(task="close out", metadata={META_TICKET_REF: 42})
        prior = {"wizard": "approve", META_PR_NUMBER: str(pr_number)}
        await handler.handle(herald_stage, envelope, prior)

        closes = [a for a in github_client.actions if a["type"] == "close_issue"]
        assert closes
        assert closes[-1]["issue_number"] == 42

    @pytest.mark.asyncio
    async def test_explicit_metadata_verdict_key_honored(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        github_client,  # noqa: ANN001
    ) -> None:
        """META_REVIEW_VERDICT in prior_results drives merge behavior."""
        pr_number = await _seed_pr(github_client)
        envelope = Envelope(task="close out")
        prior = {META_REVIEW_VERDICT: "approve", META_PR_NUMBER: str(pr_number)}
        result = await handler.handle(herald_stage, envelope, prior)

        assert result.status == TaskStatus.COMPLETED
        assert any(a["type"] == "merge_pr" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_happy_path_status_completed(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """Happy path returns a COMPLETED-status envelope."""
        await github_client.create_pr("feat", "feature/x", "master")
        prior = {
            "bard": "https://github.com/mock/repo/pull/1",
            "wizard": "approve",
        }
        result = await handler.handle(herald_stage, base_envelope, prior)
        assert result.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# No-merge paths
# ---------------------------------------------------------------------------


class TestNoMergePaths:
    @pytest.mark.asyncio
    async def test_request_changes_verdict_does_not_merge(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        await github_client.create_pr("feat", "feature/x", "master")
        prior = {
            "bard": "https://github.com/mock/repo/pull/1",
            "wizard": "request_changes",
        }
        await handler.handle(herald_stage, base_envelope, prior)
        assert not any(a["type"] == "merge_pr" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_reject_verdict_does_not_merge(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        github_client,  # noqa: ANN001
    ) -> None:
        pr_number = await _seed_pr(github_client)
        envelope = Envelope(task="close out")
        prior = {"wizard": "reject", META_PR_NUMBER: str(pr_number)}
        await handler.handle(herald_stage, envelope, prior)
        assert not any(a["type"] == "merge_pr" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_missing_verdict_does_not_merge(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        github_client,  # noqa: ANN001
    ) -> None:
        pr_number = await _seed_pr(github_client)
        envelope = Envelope(task="close out")
        prior = {META_PR_NUMBER: str(pr_number)}
        await handler.handle(herald_stage, envelope, prior)
        assert not any(a["type"] == "merge_pr" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_approve_without_pr_number_returns_envelope_no_merge(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        base_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """Missing pr_number + approve: no merge, returns envelope, no crash."""
        prior: dict[str, str] = {"wizard": "approve"}

        result = await handler.handle(herald_stage, base_envelope, prior)

        assert not any(a["type"] == "merge_pr" for a in github_client.actions)
        assert isinstance(result, Envelope)


# ---------------------------------------------------------------------------
# PR number extraction
# ---------------------------------------------------------------------------


class TestPRNumberExtraction:
    @pytest.mark.asyncio
    async def test_reads_pr_number_from_prior_results(
        self,
        herald_stage: StageSpec,
    ) -> None:
        """Herald accepts pr_number from prior_results (standard chain)."""
        gh = MockGitHubClient()
        await gh.create_pr("feat", "feature/x", "master")
        gh.merge_pr = AsyncMock(return_value=None)

        handler = HeraldHandler(github_client=gh)
        envelope = Envelope(task="Finish")
        prior = {"pr_number": "300", "review_verdict": "approve"}

        result = await handler.handle(herald_stage, envelope, prior)

        assert isinstance(result, Envelope)
        gh.merge_pr.assert_awaited_once_with(300)

    @pytest.mark.asyncio
    async def test_extracts_pr_from_bard_pull_url(
        self,
        herald_stage: StageSpec,
    ) -> None:
        """Herald parses a GitHub PR URL under the 'bard' key."""
        gh = MockGitHubClient()
        gh.merge_pr = AsyncMock(return_value=None)

        handler = HeraldHandler(github_client=gh)
        envelope = Envelope(task="Finish via URL")
        prior = {
            "bard": "https://github.com/org/repo/pull/404",
            "review_verdict": "approve",
        }
        await handler.handle(herald_stage, envelope, prior)

        gh.merge_pr.assert_awaited_once_with(404)

    @pytest.mark.asyncio
    async def test_uses_review_verdict_key_case_insensitive(
        self,
        herald_stage: StageSpec,
    ) -> None:
        """Prior review_verdict='APPROVE' (upper-case) honored."""
        gh = MockGitHubClient()
        gh.merge_pr = AsyncMock(return_value=None)

        handler = HeraldHandler(github_client=gh)
        envelope = Envelope(task="Task", metadata={META_PR_NUMBER: "55"})
        prior = {META_PR_NUMBER: "55", META_REVIEW_VERDICT: "APPROVE"}

        await handler.handle(herald_stage, envelope, prior)
        gh.merge_pr.assert_awaited_once_with(55)

    @pytest.mark.asyncio
    async def test_pr_number_garbage_is_treated_as_missing(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        github_client,  # noqa: ANN001
    ) -> None:
        """Non-parseable PR number -> no merge_pr, no crash."""
        envelope = Envelope(task="task")
        prior = {"wizard": "approve", META_PR_NUMBER: "not-a-number"}
        result = await handler.handle(herald_stage, envelope, prior)

        assert not any(a["type"] == "merge_pr" for a in github_client.actions)
        assert isinstance(result, Envelope)


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_returns_failed_envelope_on_github_failure(
        self,
        herald_stage: StageSpec,
    ) -> None:
        """GitHub errors wrapped in a FAILED envelope with ErrorDetail."""
        gh = MockGitHubClient()
        gh.merge_pr = AsyncMock(side_effect=RuntimeError("merge conflict"))

        handler = HeraldHandler(github_client=gh)
        envelope = Envelope(task="Task")
        prior = {"pr_number": "10", "review_verdict": "approve"}

        result = await handler.handle(herald_stage, envelope, prior)

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "RuntimeError"
        assert "merge conflict" in result.error.message
        assert result.error.stage_name == "herald"

    @pytest.mark.asyncio
    async def test_merge_failure_via_exploding_client(
        self,
        herald_stage: StageSpec,
    ) -> None:
        """Minimal client whose merge_pr raises -> FAILED envelope."""

        class ExplodingClient:
            actions: list[dict[str, Any]] = []

            async def merge_pr(self, number: int) -> None:
                raise RuntimeError("merge conflict")

            async def add_comment(self, *args: Any, **kwargs: Any) -> None: ...
            async def close_issue(self, *args: Any, **kwargs: Any) -> None: ...

        handler = HeraldHandler(github_client=ExplodingClient())
        envelope = Envelope(task="task")
        prior = {"wizard": "approve", META_PR_NUMBER: "1"}
        result = await handler.handle(herald_stage, envelope, prior)

        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "RuntimeError"


# ---------------------------------------------------------------------------
# Identity Seal invariants
# ---------------------------------------------------------------------------


class TestIdentitySealInvariants:
    @pytest.mark.asyncio
    async def test_never_mutates_input_envelope(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        github_client,  # noqa: ANN001
    ) -> None:
        """Envelope is frozen; returned envelope must be a new instance."""
        await github_client.create_pr("feat", "feature/x", "master")
        envelope = Envelope(task="seal-check", metadata={"upstream": "ok"})
        snapshot = dict(envelope.metadata)
        prior = {
            "bard": "https://github.com/mock/repo/pull/1",
            "wizard": "approve",
        }

        result = await handler.handle(herald_stage, envelope, prior)

        assert result is not envelope
        assert dict(envelope.metadata) == snapshot

    @pytest.mark.asyncio
    async def test_handle_returns_envelope_on_all_paths(
        self,
        handler,  # noqa: ANN001
        herald_stage: StageSpec,
        github_client,  # noqa: ANN001
    ) -> None:
        """Every path returns an Envelope instance."""
        pr_number = await _seed_pr(github_client)

        r1 = await handler.handle(
            herald_stage,
            Envelope(task="t"),
            {"wizard": "approve", META_PR_NUMBER: str(pr_number)},
        )
        assert isinstance(r1, Envelope)

        r2 = await handler.handle(
            herald_stage,
            Envelope(task="t"),
            {"wizard": "request_changes", META_PR_NUMBER: str(pr_number)},
        )
        assert isinstance(r2, Envelope)

        r3 = await handler.handle(herald_stage, Envelope(task="t"), {})
        assert isinstance(r3, Envelope)
