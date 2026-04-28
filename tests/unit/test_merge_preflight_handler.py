# === Knight A SPINE ===
"""RED tests for MergePreflightHandler — foundation/conservative spine.

Knight A owns lines 1-200: imports, fixtures, and 6 conservative-pattern
test classes. Knight B owns lines 201+ (classifier/integration innovation).

Per Sage memo bon-519-sage-20260428T033101Z.md §D-CL.1 (lines 804-855)
and §D10 surface map (lines 725-801).

Decisions ratified by Anta:
- Q1 PATH β: handler at bonfire.handlers.merge_preflight with module-level
  ROLE = AgentRole.VERIFIER. NOT in HANDLER_ROLE_MAP. The 4-entry
  assertion at test_handlers_package.py:118 stays exactly at
  {bard, wizard, herald, architect}.
- Q6 ALLOW-WITH-ANNOTATION for pre_existing_debt (gate test file).
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

# --- v0.1-tolerant imports (RED state: all of these fail today) -------------
try:
    from bonfire.handlers.merge_preflight import (  # type: ignore[import-not-found]
        MergePreflightHandler,
    )
except ImportError:  # pragma: no cover
    MergePreflightHandler = None  # type: ignore[assignment,misc]

try:
    from bonfire.github.mock import MockGitHubClient  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    MockGitHubClient = None  # type: ignore[assignment,misc]

from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import (
    META_PR_NUMBER,
    META_REVIEW_VERDICT,
    Envelope,
    TaskStatus,
)
from bonfire.models.plan import StageSpec
from bonfire.protocols import StageHandler

pytestmark = pytest.mark.skipif(
    MergePreflightHandler is None,
    reason="v0.1 RED: MergePreflightHandler not yet implemented",
)


# --- Fixtures (Knight B reuses these) ---------------------------------------


@pytest.fixture()
def preflight_stage() -> StageSpec:
    """Verifier stage spec (file-stem: merge_preflight)."""
    return StageSpec(
        name="merge_preflight",
        agent_name="merge-preflight",
        role="verifier",
        handler_name="merge_preflight",
        depends_on=["wizard"],
    )


@pytest.fixture()
def base_envelope() -> Envelope:
    """Envelope with PR number metadata."""
    return Envelope(task="Run merge preflight", metadata={META_PR_NUMBER: "42"})


@dataclass
class _MockScratchInfo:
    path: Path
    branch_name: str = "bonfire/preflight-pr-42-deadbeef"
    base_sha: str = "a" * 40


class _MockScratchContext:
    """Async CM mimicking ScratchWorktreeContext."""

    def __init__(self, info: _MockScratchInfo, raise_on_enter: Exception | None = None) -> None:
        self.info = info
        self.raise_on_enter = raise_on_enter

    async def __aenter__(self) -> _MockScratchInfo:
        if self.raise_on_enter is not None:
            raise self.raise_on_enter
        return self.info

    async def __aexit__(self, *exc_info: Any) -> None:
        return None


class _MockScratchFactory:
    """Stand-in for ScratchWorktreeFactory."""

    def __init__(
        self,
        *,
        info: _MockScratchInfo | None = None,
        raise_on_acquire: Exception | None = None,
        raise_on_enter: Exception | None = None,
    ) -> None:
        self._info = info or _MockScratchInfo(path=Path("/tmp/preflight-mock"))
        self._raise_on_acquire = raise_on_acquire
        self._raise_on_enter = raise_on_enter
        self.acquire_calls: list[dict[str, Any]] = []

    def acquire(self, base_ref: str, *, pr_number: int | None = None, prefix: str = "preflight") -> _MockScratchContext:
        self.acquire_calls.append({"base_ref": base_ref, "pr_number": pr_number, "prefix": prefix})
        if self._raise_on_acquire is not None:
            raise self._raise_on_acquire
        return _MockScratchContext(self._info, raise_on_enter=self._raise_on_enter)


def _make_handler(*, github_client: Any = None, scratch_factory: Any = None, repo_path: Path | None = None, base_branch: str = "master") -> Any:
    gh = github_client if github_client is not None else (MockGitHubClient() if MockGitHubClient else AsyncMock())
    factory = scratch_factory if scratch_factory is not None else _MockScratchFactory()
    return MergePreflightHandler(
        github_client=gh,
        scratch_worktree_factory=factory,
        repo_path=repo_path or Path("/tmp/repo"),
        base_branch=base_branch,
    )


# --- TestProtocolConformance (Sage §D-CL.1 lines 815-818) -------------------


class TestProtocolConformance:
    def test_importable_from_submodule(self) -> None:
        """Sage §D-CL.1 line 816: importable from bonfire.handlers.merge_preflight."""
        from bonfire.handlers.merge_preflight import MergePreflightHandler as _H

        assert _H is not None

    def test_importable_from_package(self) -> None:
        """Sage §D-CL.1 line 816 + §D10 line 745: re-exported from package."""
        import bonfire.handlers as handlers_pkg

        assert hasattr(handlers_pkg, "MergePreflightHandler")

    def test_satisfies_stage_handler_protocol(self) -> None:
        """Sage §D-CL.1 line 817: runtime_checkable Protocol conformance."""
        assert isinstance(_make_handler(), StageHandler)

    def test_handle_is_coroutine_function(self) -> None:
        """Sage §D-CL.1 line 818: handle is async."""
        assert inspect.iscoroutinefunction(_make_handler().handle)

    def test_handle_signature_matches_protocol(self) -> None:
        """Sage §D2 lines 257-262: signature is (stage, envelope, prior_results) -> Envelope."""
        sig = inspect.signature(MergePreflightHandler.handle)
        assert list(sig.parameters.keys()) == ["self", "stage", "envelope", "prior_results"]


# --- TestPRNumberExtraction (Sage §D-CL.1 lines 820-821, Herald-pattern) ----


class TestPRNumberExtraction:
    """Mirror Herald's PR extraction chain (Sage §D-CL.1 line 820-821)."""

    @pytest.mark.asyncio
    async def test_reads_pr_from_prior_results_meta_key(self, preflight_stage: StageSpec) -> None:
        """prior_results[META_PR_NUMBER] direct -> handler proceeds."""
        envelope = Envelope(task="t")
        prior = {META_PR_NUMBER: "100", META_REVIEW_VERDICT: "approve"}
        handler = _make_handler()
        result = await handler.handle(preflight_stage, envelope, prior)
        assert isinstance(result, Envelope)

    @pytest.mark.asyncio
    async def test_reads_pr_from_bard_pull_url_fallback(self, preflight_stage: StageSpec) -> None:
        """prior_results['bard'] URL fallback -> handler proceeds (Herald-mirror)."""
        envelope = Envelope(task="t")
        prior = {"bard": "https://github.com/org/repo/pull/404", META_REVIEW_VERDICT: "approve"}
        handler = _make_handler()
        result = await handler.handle(preflight_stage, envelope, prior)
        assert isinstance(result, Envelope)

    @pytest.mark.asyncio
    async def test_reads_pr_from_envelope_metadata_final_fallback(self, preflight_stage: StageSpec) -> None:
        """envelope.metadata[META_PR_NUMBER] final fallback when prior_results lacks it."""
        envelope = Envelope(task="t", metadata={META_PR_NUMBER: "55"})
        prior = {META_REVIEW_VERDICT: "approve"}
        handler = _make_handler()
        result = await handler.handle(preflight_stage, envelope, prior)
        assert isinstance(result, Envelope)

    @pytest.mark.asyncio
    async def test_missing_pr_returns_failed_envelope(self, preflight_stage: StageSpec) -> None:
        """No PR number anywhere -> FAILED envelope (Sage §D2 line 269)."""
        envelope = Envelope(task="t")
        prior = {META_REVIEW_VERDICT: "approve"}
        handler = _make_handler()
        result = await handler.handle(preflight_stage, envelope, prior)
        assert result.status == TaskStatus.FAILED
        assert result.error is not None


# --- TestWizardVerdictGate (Sage §D-CL.1 lines 823-825) ---------------------


class TestWizardVerdictGate:
    """Sage §D2 line 270-271: handler skips when wizard verdict != approve."""

    @pytest.mark.asyncio
    async def test_request_changes_returns_completed_skipped(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """prior_results[META_REVIEW_VERDICT] != 'approve' -> COMPLETED early-return."""
        prior = {META_REVIEW_VERDICT: "request_changes"}
        handler = _make_handler()
        result = await handler.handle(preflight_stage, base_envelope, prior)
        assert result.status == TaskStatus.COMPLETED
        assert "skipped" in result.result.lower()

    @pytest.mark.asyncio
    async def test_reject_returns_completed_skipped(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """verdict='reject' -> COMPLETED early-return with skip message."""
        prior = {META_REVIEW_VERDICT: "reject"}
        handler = _make_handler()
        result = await handler.handle(preflight_stage, base_envelope, prior)
        assert result.status == TaskStatus.COMPLETED
        assert "skipped" in result.result.lower()

    @pytest.mark.asyncio
    async def test_missing_verdict_returns_completed_skipped(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """No META_REVIEW_VERDICT -> COMPLETED early-return (skip)."""
        handler = _make_handler()
        result = await handler.handle(preflight_stage, base_envelope, {})
        assert result.status == TaskStatus.COMPLETED
        assert "skipped" in result.result.lower()

    @pytest.mark.asyncio
    async def test_approve_does_not_short_circuit(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """verdict='approve' -> handler proceeds (acquires scratch worktree)."""
        factory = _MockScratchFactory()
        handler = _make_handler(scratch_factory=factory)
        prior = {META_REVIEW_VERDICT: "approve"}
        await handler.handle(preflight_stage, base_envelope, prior)
        assert len(factory.acquire_calls) >= 1, (
            "Approve verdict must NOT early-return; scratch worktree acquired."
        )


# --- TestErrorPaths (Sage §D-CL.1 lines 827-828, BardHandler line 254) ------


class TestErrorPaths:
    """All exceptions in handler body produce FAILED envelope with ErrorDetail."""

    @pytest.mark.asyncio
    async def test_failure_envelope_has_error_detail(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """Sage §D-CL.1 line 828: ErrorDetail.error_type set on FAILED envelope."""
        factory = _MockScratchFactory(raise_on_acquire=RuntimeError("boom"))
        handler = _make_handler(scratch_factory=factory)
        prior = {META_REVIEW_VERDICT: "approve"}
        result = await handler.handle(preflight_stage, base_envelope, prior)
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type, "ErrorDetail.error_type must be non-empty."

    @pytest.mark.asyncio
    async def test_failure_envelope_has_stage_name(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """ErrorDetail.stage_name == stage.name (mirror BardHandler line 254)."""
        factory = _MockScratchFactory(raise_on_acquire=RuntimeError("boom"))
        handler = _make_handler(scratch_factory=factory)
        prior = {META_REVIEW_VERDICT: "approve"}
        result = await handler.handle(preflight_stage, base_envelope, prior)
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.stage_name == preflight_stage.name


# --- TestNeverRaises (Sage §D-CL.1 lines 830-833, protocols.py:195) ---------


class TestNeverRaises:
    """StageHandler Protocol contract: handler MUST NOT raise."""

    @pytest.mark.asyncio
    async def test_github_client_raise_yields_failed_envelope(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """Raise from github_client.get_pr_diff -> FAILED envelope (no bubble)."""
        gh = AsyncMock()
        gh.get_pr_diff = AsyncMock(side_effect=RuntimeError("gh down"))
        handler = _make_handler(github_client=gh)
        prior = {META_REVIEW_VERDICT: "approve"}
        # Must NOT raise; must return FAILED envelope.
        result = await handler.handle(preflight_stage, base_envelope, prior)
        assert result.status == TaskStatus.FAILED
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_scratch_factory_acquire_raise_yields_failed_envelope(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """Raise from scratch_worktree_factory.acquire -> FAILED envelope."""
        factory = _MockScratchFactory(raise_on_acquire=OSError("disk full"))
        handler = _make_handler(scratch_factory=factory)
        prior = {META_REVIEW_VERDICT: "approve"}
        result = await handler.handle(preflight_stage, base_envelope, prior)
        assert result.status == TaskStatus.FAILED
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_scratch_context_enter_raise_yields_failed_envelope(
        self, preflight_stage: StageSpec, base_envelope: Envelope
    ) -> None:
        """Raise from inside __aenter__ (mirrors pytest subprocess crash) -> FAILED envelope."""
        factory = _MockScratchFactory(raise_on_enter=RuntimeError("git apply failed"))
        handler = _make_handler(scratch_factory=factory)
        prior = {META_REVIEW_VERDICT: "approve"}
        result = await handler.handle(preflight_stage, base_envelope, prior)
        assert result.status == TaskStatus.FAILED
        assert result.error is not None


# --- TestModuleRoleConstant (Sage §D-CL.1 line 835-837 + Path β anchors) ----


class TestModuleRoleConstant:
    """Path β contract: ROLE constant + handler not in HANDLER_ROLE_MAP."""

    def test_module_exposes_role_bound_to_verifier(self) -> None:
        """Sage §D-CL.1 line 836: merge_preflight.ROLE is AgentRole.VERIFIER."""
        from bonfire.handlers import merge_preflight

        assert hasattr(merge_preflight, "ROLE"), (
            "merge_preflight.py must expose a module-level ROLE constant "
            "bound to AgentRole.VERIFIER."
        )
        assert merge_preflight.ROLE is AgentRole.VERIFIER

    def test_role_is_agent_role_instance(self) -> None:
        """Sage §D-CL.1 line 837: ROLE is an AgentRole enum member."""
        from bonfire.handlers import merge_preflight

        assert isinstance(merge_preflight.ROLE, AgentRole)

    def test_role_value_is_verifier_string(self) -> None:
        """StrEnum value: ROLE == 'verifier'."""
        from bonfire.handlers import merge_preflight

        assert merge_preflight.ROLE == "verifier"

    def test_handler_role_map_stays_at_four_entries(self) -> None:
        """Path β contract anchor: HANDLER_ROLE_MAP NOT extended to 5 entries.

        Sage §A Q1 line 37 + §D10 line 767: deterministic handler bypasses
        gamified-display map. The 4-entry assertion at
        test_handlers_package.py:118 must keep holding.
        """
        import bonfire.handlers as handlers_pkg

        assert set(handlers_pkg.HANDLER_ROLE_MAP.keys()) == {
            "bard",
            "wizard",
            "herald",
            "architect",
        }

    def test_merge_preflight_not_in_handler_role_map(self) -> None:
        """Path β negative contract (Sage §D10 line 745): deterministic
        handler MUST NOT appear in HANDLER_ROLE_MAP."""
        import bonfire.handlers as handlers_pkg

        assert "merge_preflight" not in handlers_pkg.HANDLER_ROLE_MAP

    def test_merge_preflight_handler_in_package_all(self) -> None:
        """Path β positive contract (Sage §D1 line 221): MergePreflightHandler
        in package __all__ even though stem is not in HANDLER_ROLE_MAP."""
        import bonfire.handlers as handlers_pkg

        assert "MergePreflightHandler" in getattr(handlers_pkg, "__all__", [])

    def test_role_display_has_verifier_assayer(self) -> None:
        """Sage §D10 line 755: ROLE_DISPLAY['verifier'].gamified == 'Assayer'.

        Surface map states this entry already exists per docstring at
        roles.py:25; this test pins it as part of the BON-519 contract so any
        Warrior who removes/renames it gets a RED assertion.
        """
        from bonfire.naming import ROLE_DISPLAY

        assert "verifier" in ROLE_DISPLAY
        assert ROLE_DISPLAY["verifier"].gamified == "Assayer"
        assert ROLE_DISPLAY["verifier"].professional == "Verify Agent"
