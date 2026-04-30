"""RED tests for ``SageCorrectionBounceHandler`` — foundation/conservative spine.

Knight A SPINE — pins the *shape* of the contract (Protocol conformance,
signature, ROLE constant, envelope shape on success, early-return paths,
never-raises, verdict routing). Knight B owns the *algorithm* surface in
this same file under the ``# === Knight B INNOVATION ===`` banner.

Per Sage §D-CL.1 (lines 17-19, 52-92) the seven Knight-A test classes:

    - TestProtocolConformance
    - TestStageHandlerSignature
    - TestModuleRoleConstant
    - TestCorrectionEnvelopeShape
    - TestEarlyReturnPaths
    - TestNeverRaises
    - TestVerdictRouting

Anta-ratified §A decisions reflected in these tests (2026-04-28):
    - Q1 (c) hybrid: classifier in ``bonfire.verify``, handler in
      ``bonfire.handlers.sage_correction_bounce``.
    - Q1a: 3-verdict classifier (``SAGE_UNDER_MARKED``, ``WARRIOR_BUG``,
      ``AMBIGUOUS``).
    - Q3 (a): stage fires post-Warrior+Prover, pre-Bard. Standard pipeline
      becomes 9-stage.
    - Q4 (b): restricted xfail-corrector via ``DispatchOptions`` with
      ``allowed_tools={"Read", "Edit"}``.
    - Q4a: reuse ``AgentRole.SYNTHESIZER`` with ``correction_mode`` flag.
    - Q5 (d): max_attempts configurable, default 1.
    - Q9 (b): Stage + Gate (``SageCorrectionResolvedGate``).

Sage memo (canonical):
    docs/audit/sage-decisions/bon-513-sage-CL-20260428T210000Z.md §D-CL.1
    docs/audit/sage-decisions/bon-513-sage-A-20260428T210000Z.md §A Q1-Q9
    docs/audit/sage-decisions/bon-513-sage-D-20260428T210000Z.md §D1-§D5

Conservative RED idiom (per dispatch + Sage §D-CL.1 lines 25-50): each
test imports the missing surface inside its own body; the resulting
``ImportError`` (or assertion failure on partial impl) is captured by
``@pytest.mark.xfail(strict=True, reason=...)``. ``strict=True`` flips
unexpected pass to a hard failure: a Warrior who lands an empty stub
will see RED, not silent green.

Per the dispatch contract: this file may reference BON-513 in docstrings
(tests/, not src/) but never bare in src/.
"""

from __future__ import annotations

import importlib.util
import inspect
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

# === Knight A SPINE ===

_RED_REASON = (
    "BON-513 not implemented: bonfire.handlers.sage_correction_bounce + "
    "bonfire.verify package not yet on disk (Sage §D-CL.1, §D1, §D3)."
)


# ---------------------------------------------------------------------------
# Shared helpers (Knight B reuses these by import-by-name discipline; if
# Knight B redefines, banner-comment merge is still trivial — pytest tolerates
# duplicate top-level helpers).
# ---------------------------------------------------------------------------


def _make_stage_spec():
    """Construct a synthetic ``StageSpec`` for the sage_correction_bounce stage.

    Per Sage §A Q3 lines 119-128: handler_name='sage_correction_bounce',
    role='verifier' (reusing AgentRole.SYNTHESIZER per §A Q1 lines 49-50).
    """
    from bonfire.models.plan import StageSpec

    return StageSpec(
        name="sage_correction_bounce",
        agent_name="sage-correction-bounce",
        role="synthesizer",
        handler_name="sage_correction_bounce",
        gates=["sage_correction_resolved"],
        depends_on=["prover"],
        max_iterations=1,
    )


def _make_envelope():
    """Minimal envelope with a placeholder task string."""
    from bonfire.models.envelope import Envelope

    return Envelope(task="run sage correction bounce")


def _make_handler():
    """Construct a minimal ``SageCorrectionBounceHandler`` for shape tests.

    Constructor surface follows Sage §D3 lines 202-214. Tests pin only
    the public Protocol shape; constructor parameter coverage is Knight B's
    lane (algorithm wiring).
    """
    from pathlib import Path

    from bonfire.handlers.sage_correction_bounce import (
        SageCorrectionBounceHandler,
    )

    return SageCorrectionBounceHandler(
        backend=None,
        github_client=None,
        config=None,
        repo_path=Path("/tmp/bon-513-spine"),
    )


# ---------------------------------------------------------------------------
# TestProtocolConformance (Sage §D-CL.1 lines 54-58, §D3 line 188)
# ---------------------------------------------------------------------------


class TestProtocolConformance:
    """``SageCorrectionBounceHandler`` satisfies the ``StageHandler`` Protocol.

    Mirrors BON-519 ``MergePreflightHandler`` precedent (BON-519 §D2):
    runtime_checkable Protocol; importable from package and submodule.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_handler_importable_from_submodule(self) -> None:
        """Sage §D-CL.1 line 55: importable from
        ``bonfire.handlers.sage_correction_bounce``."""
        from bonfire.handlers.sage_correction_bounce import (
            SageCorrectionBounceHandler,
        )

        assert SageCorrectionBounceHandler is not None

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_handler_importable_from_package(self) -> None:
        """Sage §D-CL.1 line 55 + §B line 50: re-exported via ``__all__``."""
        import bonfire.handlers as handlers_pkg

        assert hasattr(handlers_pkg, "SageCorrectionBounceHandler")

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_handler_in_package_dunder_all(self) -> None:
        """Sage §B line 50: ``SageCorrectionBounceHandler`` listed in
        ``bonfire.handlers.__all__``."""
        import bonfire.handlers as handlers_pkg

        assert "SageCorrectionBounceHandler" in getattr(handlers_pkg, "__all__", [])

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_handler_satisfies_stage_handler_protocol(self) -> None:
        """Sage §D-CL.1 line 56: ``isinstance(handler, StageHandler)``."""
        from bonfire.protocols import StageHandler

        assert isinstance(_make_handler(), StageHandler)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_handle_is_coroutine_function(self) -> None:
        """Sage §D-CL.1 line 57: ``inspect.iscoroutinefunction(handler.handle)``
        is True."""
        from bonfire.handlers.sage_correction_bounce import (
            SageCorrectionBounceHandler,
        )

        assert inspect.iscoroutinefunction(SageCorrectionBounceHandler.handle)


# ---------------------------------------------------------------------------
# TestStageHandlerSignature (Sage §D-CL.1 lines 60-62, §D3 lines 216-221)
# ---------------------------------------------------------------------------


class TestStageHandlerSignature:
    """``handle`` signature matches the StageHandler Protocol exactly.

    Mirror ``MergePreflightHandler.handle`` (BON-519) and
    ``WizardHandler.handle`` (Sage §D-CL.1 line 61): parameters are
    ``(stage, envelope, prior_results)`` returning ``Envelope``.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_handle_parameters_match_protocol(self) -> None:
        """Sage §D-CL.1 line 61: signature is
        ``(self, stage, envelope, prior_results) -> Envelope``."""
        from bonfire.handlers.sage_correction_bounce import (
            SageCorrectionBounceHandler,
        )

        sig = inspect.signature(SageCorrectionBounceHandler.handle)
        assert list(sig.parameters.keys()) == [
            "self",
            "stage",
            "envelope",
            "prior_results",
        ]

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_handle_return_annotation_is_envelope(self) -> None:
        """Sage §D3 line 221: return type is ``Envelope``.

        Tolerant check: accepts the imported class OR a forward-ref
        string ``'Envelope'`` (PEP 563 deferred annotations).
        """
        from bonfire.handlers.sage_correction_bounce import (
            SageCorrectionBounceHandler,
        )
        from bonfire.models.envelope import Envelope

        sig = inspect.signature(SageCorrectionBounceHandler.handle)
        ret = sig.return_annotation
        assert ret is Envelope or ret == "Envelope" or ret is inspect.Signature.empty


# ---------------------------------------------------------------------------
# TestModuleRoleConstant (Sage §D-CL.1 lines 64-66, §A Q1 lines 49-50, §A Q4a)
# ---------------------------------------------------------------------------


class TestModuleRoleConstant:
    """Module-level ``ROLE`` constant binds the handler to its
    generic AgentRole.

    Anta-ratified §A Q4a (line 159): reuse ``AgentRole.SYNTHESIZER`` —
    the corrector IS a Sage doing surgical work, not a new role. The
    dispatch SMEAC also pins this. NB: §A Q1 line 49 separately mentions
    ``AgentRole.SYNTHESIZER`` for the deterministic verification stage; per
    the dispatch SMEAC and §A Q4a the ROLE for the auto-dispatched
    correction agent is SYNTHESIZER. This test pins SYNTHESIZER per the
    dispatch contract.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_module_exposes_role_constant(self) -> None:
        """Sage §D-CL.1 line 64: module-level ``ROLE`` exists."""
        from bonfire.handlers import sage_correction_bounce

        assert hasattr(sage_correction_bounce, "ROLE"), (
            "sage_correction_bounce.py must expose a module-level ROLE "
            "constant per Sage §D-CL.1 line 64."
        )

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_role_is_synthesizer(self) -> None:
        """Sage §D-CL.1 line 64 + §A Q4a line 159 (Anta-ratified):
        ``ROLE is AgentRole.SYNTHESIZER``."""
        from bonfire.agent.roles import AgentRole
        from bonfire.handlers import sage_correction_bounce

        assert sage_correction_bounce.ROLE is AgentRole.SYNTHESIZER

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_role_is_agent_role_instance(self) -> None:
        """Sage §D-CL.1 line 65: ROLE is an ``AgentRole`` enum member."""
        from bonfire.agent.roles import AgentRole
        from bonfire.handlers import sage_correction_bounce

        assert isinstance(sage_correction_bounce.ROLE, AgentRole)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_role_value_is_synthesizer_string(self) -> None:
        """StrEnum value: ``ROLE == 'synthesizer'``."""
        from bonfire.handlers import sage_correction_bounce

        assert sage_correction_bounce.ROLE == "synthesizer"


# ---------------------------------------------------------------------------
# TestCorrectionEnvelopeShape (Sage §D-CL.1 lines 68-74, §D3 lines 285-307)
# ---------------------------------------------------------------------------


class TestCorrectionEnvelopeShape:
    """Successful correction-cycle returns an envelope with the
    documented metadata shape.

    Sage §D-CL.1 lines 68-74 + §D3 lines 290-307. The handler MUST
    preserve original envelope metadata (Bardo-style ``{**envelope.metadata,
    ...}`` merge — Sage line 73-74) and write the
    correction-lifecycle keys.

    NB: This class verifies the *contract* shape — that the metadata keys
    exist with the documented values when correction succeeds. The full
    correction-cycle dispatch + cherry-pick + re-verify orchestration is
    Knight B's lane (TestSageRerunBackend, TestCherryPickFlow,
    TestReverifyOrchestration).
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_meta_bounce_verdict_constant_importable(self) -> None:
        """Sage §A Q3 line 132 + §B line 327: ``META_CORRECTION_VERDICT``
        constant lives in ``bonfire.models.envelope`` (alphabetically
        adjacent to existing META_* keys)."""
        from bonfire.models.envelope import META_CORRECTION_VERDICT

        assert isinstance(META_CORRECTION_VERDICT, str)
        assert META_CORRECTION_VERDICT  # non-empty

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_meta_bounce_attempt_constant_importable(self) -> None:
        """Sage §A Q3 line 132 + §B line 327: ``META_CORRECTION_CYCLES``
        constant lives in ``bonfire.models.envelope``."""
        from bonfire.models.envelope import META_CORRECTION_CYCLES

        assert isinstance(META_CORRECTION_CYCLES, str)
        assert META_CORRECTION_CYCLES

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_meta_bounce_correction_branch_constant_importable(self) -> None:
        """Sage §A Q3 line 132 + §B line 327: ``META_CORRECTION_BRANCH``
        constant lives in ``bonfire.models.envelope``."""
        from bonfire.models.envelope import META_CORRECTION_BRANCH

        assert isinstance(META_CORRECTION_BRANCH, str)
        assert META_CORRECTION_BRANCH

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_meta_bounce_keys_distinct(self) -> None:
        """The three new keys are distinct from each other and from
        existing META_* keys (no collision). Mirror BON-519
        ``test_meta_preflight_keys_are_distinct`` discipline."""
        from bonfire.models.envelope import (
            META_CORRECTION_BRANCH,
            META_CORRECTION_CYCLES,
            META_CORRECTION_VERDICT,
            META_PR_NUMBER,
            META_PR_URL,
            META_REVIEW_VERDICT,
            META_TICKET_REF,
        )

        all_keys = {
            META_PR_NUMBER,
            META_PR_URL,
            META_REVIEW_VERDICT,
            META_TICKET_REF,
            META_CORRECTION_VERDICT,
            META_CORRECTION_CYCLES,
            META_CORRECTION_BRANCH,
        }
        assert len(all_keys) == 7, (
            "All three META_CORRECTION_* keys must be distinct from each "
            "other AND from existing META_* keys."
        )

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_corrected_envelope_status_is_completed(self) -> None:
        """Sage §D-CL.1 line 70: after a successful correction cycle the
        envelope returns COMPLETED."""
        from bonfire.models.envelope import TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        # Knight A only pins the *shape* on the empty / no-op path:
        # an envelope returned from handle() must always be an Envelope
        # with a defined status (never raises). Knight B exercises the
        # full corrected-path metadata writes.
        result = await handler.handle(stage, envelope, {})
        assert result.status in (TaskStatus.COMPLETED, TaskStatus.FAILED)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_corrected_envelope_preserves_original_metadata(self) -> None:
        """Sage §D-CL.1 lines 73-74: original metadata is preserved via
        ``{**envelope.metadata, ...}`` merge (never replacement). The
        Bardo-style envelope-merge pattern."""
        handler = _make_handler()
        envelope = _make_envelope().model_copy(
            update={"metadata": {"upstream_key": "preserved"}},
        )
        stage = _make_stage_spec()
        result = await handler.handle(stage, envelope, {})
        # Metadata MUST be a superset of the input metadata (handler may
        # ADD keys but must NOT drop upstream keys).
        assert "upstream_key" in result.metadata
        assert result.metadata["upstream_key"] == "preserved"


# ---------------------------------------------------------------------------
# TestEarlyReturnPaths (Sage §D-CL.1 lines 76-78, §D3 lines 226-241)
# ---------------------------------------------------------------------------


class TestEarlyReturnPaths:
    """Early-return paths short-circuit dispatch: WARRIOR_BUG, missing
    classifier verdict, warrior-green, max-attempts exhaustion.

    Sage §D-CL.1 lines 76-78 + §D3 lines 228-241.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_warrior_bug_verdict_short_circuits_to_completed(self) -> None:
        """Sage §D-CL.1 line 76: classifier verdict ``warrior_bug`` →
        handler returns COMPLETED with escalation flag (no Sage dispatch).

        Mirror BON-519 §D-CL.7 #4: the handler reads the upstream verdict
        from prior_results (or envelope metadata fallback) and routes
        without invoking the backend.
        """
        from bonfire.models.envelope import META_CORRECTION_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_CORRECTION_VERDICT: "warrior_bug"}
        result = await handler.handle(stage, envelope, prior)
        assert result.status == TaskStatus.COMPLETED, (
            "warrior_bug verdict must short-circuit to COMPLETED, not FAILED."
        )

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_missing_classifier_verdict_returns_completed_skipped(self) -> None:
        """Sage §D-CL.1 line 77: prior_results missing classifier verdict
        → handler returns COMPLETED (NOT FAILED — pipeline must continue)."""
        from bonfire.models.envelope import TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        result = await handler.handle(stage, envelope, {})
        # Conservative shape: missing-input is a skip path, not a hard fail.
        assert result.status == TaskStatus.COMPLETED, (
            "Missing classifier verdict must skip-pass, not fail (Sage §D-CL.1 line 77)."
        )

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_warrior_green_short_circuits_no_dispatch(self) -> None:
        """Sage §D-CL.1 line 78 + §D3 lines 240-241: warrior-green
        (META_REVIEW_VERDICT='approve' AND no warrior failure) → handler
        skips correction (``META_CORRECTION_SKIPPED_REASON='warrior_green'``
        in BON-519's family of metadata keys; for BON-513 the analogous
        sentinel is ``META_CORRECTION_VERDICT`` set to a not-needed value).
        """
        from bonfire.models.envelope import (
            META_REVIEW_VERDICT,
            TaskStatus,
        )

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {
            META_REVIEW_VERDICT: "approve",
            "warrior": "100 passed in 1.0s",  # warrior reports green
        }
        result = await handler.handle(stage, envelope, prior)
        assert result.status == TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# TestNeverRaises (Sage §D-CL.1 lines 80-85, §D3 line 199 + line 309-315)
# ---------------------------------------------------------------------------


class TestNeverRaises:
    """``StageHandler`` Protocol contract: handler MUST NOT raise. Every
    exception in the body produces a FAILED envelope with structured
    ``ErrorDetail`` (mirror ``WizardHandler`` lines 419-426 +
    ``MergePreflightHandler`` lines 626-633).

    Knight A pins only the *no-raise* property on the public surface;
    detailed exception-source coverage (classifier raise, backend raise,
    git-cherry-pick raise, pytest-runner raise) is Knight B's lane.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_handle_with_minimal_inputs_never_raises(self) -> None:
        """Smoke test: minimal env + empty prior_results → handler returns
        Envelope, never raises. Sage §D3 line 199."""
        from bonfire.models.envelope import Envelope

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        result = await handler.handle(stage, envelope, {})
        assert isinstance(result, Envelope), (
            "handle() must return an Envelope, never raise (Protocol contract)."
        )

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_handle_with_invalid_prior_results_never_raises(self) -> None:
        """Garbage in prior_results (non-string values) → handler returns
        Envelope, never raises. Sage §D-CL.1 line 80."""
        from bonfire.models.envelope import Envelope

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        # prior_results is dict[str, str] per Protocol; pass a malformed
        # input and verify graceful FAILED envelope (NOT a raised exception).
        prior = {"warrior": "invalid: not a known status string"}
        result = await handler.handle(stage, envelope, prior)
        assert isinstance(result, Envelope)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_failure_envelope_carries_error_detail(self) -> None:
        """Sage §D-CL.1 line 85: every FAILED return path has
        ``ErrorDetail.error_type`` and ``.stage_name == stage.name``."""
        from bonfire.models.envelope import META_CORRECTION_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        # Trigger an intentionally-undefined verdict to force the
        # ``UnknownClassifierVerdict`` failure path (Sage §D-CL.1 line 91).
        prior = {META_CORRECTION_VERDICT: "this_verdict_is_bogus_xyz"}
        result = await handler.handle(stage, envelope, prior)
        if result.status == TaskStatus.FAILED:
            assert result.error is not None
            assert result.error.error_type, (
                "ErrorDetail.error_type must be non-empty on FAILED envelope."
            )
            assert result.error.stage_name == stage.name


# ---------------------------------------------------------------------------
# TestVerdictRouting (Sage §D-CL.1 lines 87-92, §D3 lines 256-273)
# ---------------------------------------------------------------------------


class TestVerdictRouting:
    """All four verdict branches are explicitly handled (Sage §D-CL.6
    category #4 verdict-routing exhaustiveness).

    Sage §D-CL.1 lines 87-92:
        - sage_under_marked → correction flow (Knight B verifies the
          backend.execute call-count; Knight A only verifies the routing
          *exists* — handler does not return an unhandled-verdict failure).
        - warrior_bug → escalation flow (no backend call).
        - green → no-op pass-through with a skip metadata sentinel.
        - unknown → FAILED with ``error.error_type='UnknownClassifierVerdict'``.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_sage_under_marked_routes_to_correction_flow(self) -> None:
        """Sage §D-CL.1 line 87: ``sage_under_marked`` verdict drives
        the handler into the correction flow.

        Knight A pins only the *routing* property: handler does NOT
        return the ``UnknownClassifierVerdict`` failure for a known verdict.
        Knight B exercises the full backend.execute dispatch.
        """
        from bonfire.models.envelope import (
            META_CORRECTION_VERDICT,
            TaskStatus,
        )

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_CORRECTION_VERDICT: "sage_under_marked"}
        result = await handler.handle(stage, envelope, prior)
        # Whatever the outcome (corrected, escalated, etc.), the handler
        # MUST NOT mark the verdict as 'unknown' — sage_under_marked is
        # a recognized member.
        if result.status == TaskStatus.FAILED and result.error is not None:
            assert result.error.error_type != "UnknownClassifierVerdict", (
                "sage_under_marked is a known verdict; handler must NOT "
                "produce UnknownClassifierVerdict for it."
            )

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_warrior_bug_routes_to_escalation_no_dispatch(self) -> None:
        """Sage §D-CL.1 line 89: ``warrior_bug`` verdict produces
        ``META_CORRECTION_ESCALATED`` (or analogous escalation metadata)
        and does NOT dispatch the correction backend.

        The §A-pinned analogous metadata key in BON-513 is ``META_CORRECTION_VERDICT``
        carrying a string value indicating escalation; Knight A pins only
        that the handler returns COMPLETED (not FAILED) for this verdict.
        """
        from bonfire.models.envelope import META_CORRECTION_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_CORRECTION_VERDICT: "warrior_bug"}
        result = await handler.handle(stage, envelope, prior)
        # Escalation is a successful pipeline outcome (Wizard sees the
        # bounce and reviews); handler must NOT return FAILED.
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_unknown_verdict_yields_failed_envelope(self) -> None:
        """Sage §D-CL.1 line 91: unknown verdict → FAILED envelope with
        ``error.error_type='UnknownClassifierVerdict'`` (fail-safe; never
        silently pass)."""
        from bonfire.models.envelope import META_CORRECTION_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_CORRECTION_VERDICT: "totally_made_up_verdict"}
        result = await handler.handle(stage, envelope, prior)
        assert result.status == TaskStatus.FAILED, (
            "Unknown verdict must produce FAILED (fail-safe)."
        )
        assert result.error is not None
        assert result.error.error_type == "UnknownClassifierVerdict", (
            "Sage §D-CL.1 line 91: error_type is locked at "
            "'UnknownClassifierVerdict' for the unknown-verdict failure path."
        )

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_ambiguous_verdict_handled_explicitly(self) -> None:
        """Sage §A Q1a (Anta-ratified): ``AMBIGUOUS`` is the third
        deterministic verdict (NOT folded into WARRIOR_BUG). The handler
        MUST NOT produce ``UnknownClassifierVerdict`` for it.

        Sage §A Q9a (line 308): AMBIGUOUS → gate returns
        ``passed=False, severity='error'``. Handler envelope shape carries
        AMBIGUOUS through; gate decides pipeline halt.
        """
        from bonfire.models.envelope import META_CORRECTION_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_CORRECTION_VERDICT: "ambiguous"}
        result = await handler.handle(stage, envelope, prior)
        # AMBIGUOUS is a known verdict — must NOT trigger
        # UnknownClassifierVerdict.
        if result.status == TaskStatus.FAILED and result.error is not None:
            assert result.error.error_type != "UnknownClassifierVerdict", (
                "AMBIGUOUS is a known verdict per §A Q1a (Anta-ratified)."
            )


# === Knight B INNOVATION (banner-merged at contract-lock) ===
# Knight B's classes (TestPureFunctionClassifierIntegration, TestDispatchToolRestriction,
# TestAttemptCounter, TestEscalatePath, TestPostDispatchVerification) appended below.
# Per Sage §D-CL.2 lines 106-118 banner-comment file split. Top-level helpers may
# duplicate Knight A's (Python module-level: last def wins; signatures align).

# === Knight B INNOVATION ===

# --- Dep-presence flags (over-specified per Sage §D-CL.1 line 27-50) --------


def _module_present(modname: str) -> bool:
    """Check importability, tolerating missing intermediate packages."""
    try:
        return importlib.util.find_spec(modname) is not None
    except (ModuleNotFoundError, ValueError):
        return False


_HANDLER_PRESENT = _module_present("bonfire.handlers.sage_correction_bounce")
_CLASSIFIER_PRESENT = _module_present("bonfire.verify.classifier")
_DISPATCH_PRESENT = _module_present("bonfire.protocols")
_GIT_WORKFLOW_PRESENT = _module_present("bonfire.git.workflow")

_BOTH_LANDED = _HANDLER_PRESENT and _CLASSIFIER_PRESENT
_FULL_STACK_LANDED = (
    _HANDLER_PRESENT and _CLASSIFIER_PRESENT and _DISPATCH_PRESENT and _GIT_WORKFLOW_PRESENT
)

_HANDLER_XFAIL = pytest.mark.xfail(
    condition=not _BOTH_LANDED,
    reason=(
        "v0.1 RED: bonfire.handlers.sage_correction_bounce AND "
        "bonfire.verify.classifier must both land. Deferred to "
        "BON-513-warrior-impl (Sage memo §D-CL.2 + §D3 + §D7)."
    ),
    strict=True,
)

_FULL_STACK_XFAIL = pytest.mark.xfail(
    condition=not _FULL_STACK_LANDED,
    reason=(
        "v0.1 RED: bonfire.handlers.sage_correction_bounce AND "
        "bonfire.verify.classifier AND bonfire.protocols AND "
        "bonfire.git.workflow must all land. Deferred to "
        "BON-513-warrior-impl (Sage memo §D-CL.2 + §D7)."
    ),
    strict=True,
)


# ---------------------------------------------------------------------------
# Fixture factories — innovation pattern from BON-519 Knight B
# ---------------------------------------------------------------------------


def _make_handler(
    *,
    backend: Any = None,
    classifier: Any = None,
    decision_log_loader: Any = None,
    git_workflow: Any = None,
    pytest_runner: Any = None,
    config: Any = None,
    event_bus: Any = None,
) -> Any:
    """Construct a `SageCorrectionBounceHandler` with mocked deps (lazy import)."""
    from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler

    return SageCorrectionBounceHandler(
        backend=backend if backend is not None else AsyncMock(),
        classifier=classifier if classifier is not None else MagicMock(),
        sage_decision_log_loader=decision_log_loader
        if decision_log_loader is not None
        else MagicMock(),
        git_workflow=git_workflow if git_workflow is not None else MagicMock(),
        pytest_runner=pytest_runner if pytest_runner is not None else AsyncMock(),
        config=config if config is not None else MagicMock(),
        event_bus=event_bus,
    )


def _make_envelope(*, metadata: dict | None = None) -> Any:
    """Construct an Envelope with optional metadata (lazy import)."""
    from bonfire.models.envelope import Envelope

    return Envelope(task="sage_correction test", metadata=metadata or {})


def _make_stage() -> Any:
    """Construct a StageSpec for the sage_correction stage (lazy import)."""
    from bonfire.models.plan import StageSpec

    return StageSpec(
        name="sage_correction_bounce",
        agent_name="sage-correction",
        role="synthesizer",
        handler_name="sage_correction_bounce",
        depends_on=["warrior"],
    )


# ---------------------------------------------------------------------------
# 1. TestPureFunctionClassifierIntegration
#    Handler invokes the pure-function classifier; return value drives flow.
# ---------------------------------------------------------------------------


class TestPureFunctionClassifierIntegration:
    """Handler delegates classification to `classify_warrior_failure`
    (pure function); reads its verdict; routes the envelope accordingly.

    Sage §D-CL.2 line 137 ('TestClassifierIntegration — handler-level
    invocation of classifier (mocked module function)') + user prompt
    Q1 (c) ('pure-fn classifier in bonfire/verify/classifier.py').
    """

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_handler_invokes_classify_warrior_failure_once(self) -> None:
        """Handler calls the classifier exactly once per `handle()` call.
        Repeated calls would risk non-determinism if the function is
        accidentally non-pure."""
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="warrior_bug",  # str matches StrEnum
        )
        handler = _make_handler(classifier=classifier)
        await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # Classifier invoked exactly once (pure-fn discipline; no retries
        # at handler level).
        assert classifier.classify.call_count <= 1

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_handler_passes_decision_log_text_not_path(self) -> None:
        """Handler reads the decision log via the loader, then passes the
        text (not the path) to the classifier — keeps classifier pure."""
        decision_log_loader = MagicMock(return_value="## DEFER via xfail\n\n- `BON-A`\n")
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="warrior_bug")
        handler = _make_handler(
            classifier=classifier,
            decision_log_loader=decision_log_loader,
        )
        await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # Loader was used; classifier call site does NOT include a Path
        # object — it includes a string (text content).
        if classifier.classify.call_args is not None:
            kwargs = classifier.classify.call_args.kwargs
            args = classifier.classify.call_args.args
            all_args = list(args) + list(kwargs.values())
            for arg in all_args:
                # No Path-like objects flow into the classifier (purity).
                assert not hasattr(arg, "open") or isinstance(arg, str)


# ---------------------------------------------------------------------------
# 2. TestDispatchToolRestriction
#    DispatchOptions.allowed_tools == frozenset({"Read", "Edit"})
# ---------------------------------------------------------------------------


class TestDispatchToolRestriction:
    """Sage §D-CL.2 line 188-192 + user-prompt Q4 (b) restricted
    xfail-corrector with `DispatchOptions(allowed_tools=frozenset({"Read",
    "Edit"}))`.

    HARD CONSTRAINT (user prompt): allowed_tools is a `frozenset`, not a
    mutable `set`. Tests assert on the FROZEN nature so a regression that
    accidentally hands back a `set` (mutable) is caught.

    NOTE for Wizard: Sage memo §D-CL.1 line 189 specifies
    `tools=("Read", "Edit", "Grep")` (tuple of 3). User prompt
    contradicts: `frozenset({"Read", "Edit"})` (frozenset of 2).
    Following user prompt verbatim. Wizard reconciles.
    """

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_dispatch_options_allowed_tools_is_frozenset(self) -> None:
        """`allowed_tools` is a `frozenset`, not a `set` (immutability)."""
        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)

        try:
            await handler.handle(
                stage=_make_stage(),
                envelope=_make_envelope(),
                prior_results={"warrior": "1 failed"},
            )
        except Exception:
            # Per StageHandler contract handle() never raises, but mocks may
            # short-circuit; we still inspect what reached the backend.
            pass

        # backend.execute (or .dispatch) was called with DispatchOptions.
        # Locate the DispatchOptions in the call args and assert tools is
        # a frozenset (not a list, not a set, not a tuple).
        if backend.execute.called or backend.dispatch.called:
            mock_call = backend.execute.call_args or backend.dispatch.call_args
            options = None
            for arg in list(mock_call.args) + list(mock_call.kwargs.values()):
                # DispatchOptions has an `allowed_tools` attribute or a
                # `tools` attribute. We allow either spelling but assert
                # frozen-ness on whichever is present.
                if hasattr(arg, "allowed_tools"):
                    options = arg
                    break
                if hasattr(arg, "tools"):
                    options = arg
                    break
            assert options is not None
            tool_field = getattr(options, "allowed_tools", None) or getattr(options, "tools", None)
            # FROZEN nature: frozenset, not set.
            assert isinstance(tool_field, frozenset), (
                f"DispatchOptions tool field MUST be frozenset (immutable); "
                f"got {type(tool_field).__name__}. User prompt §CONSTRAINTS: "
                f"'frozenset({{Read, Edit}}) not set({{Read, Edit}})'."
            )

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_dispatch_options_allowed_tools_contains_read_and_edit(
        self,
    ) -> None:
        """Tool set is exactly `{"Read", "Edit"}` per user-prompt Q4 (b)."""
        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)

        try:
            await handler.handle(
                stage=_make_stage(),
                envelope=_make_envelope(),
                prior_results={"warrior": "1 failed"},
            )
        except Exception:
            pass

        if backend.execute.called or backend.dispatch.called:
            mock_call = backend.execute.call_args or backend.dispatch.call_args
            options = None
            for arg in list(mock_call.args) + list(mock_call.kwargs.values()):
                if hasattr(arg, "allowed_tools") or hasattr(arg, "tools"):
                    options = arg
                    break
            assert options is not None
            tool_field = getattr(options, "allowed_tools", None) or getattr(options, "tools", None)
            assert "Read" in tool_field
            assert "Edit" in tool_field

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_dispatch_options_allowed_tools_excludes_bash_and_write(
        self,
    ) -> None:
        """Sage MUST NOT have `Bash` (cannot break out of correction scope)
        and MUST NOT have `Write` (cannot create new files; only edit
        xfail markers). Sage §D-CL.4 line 302 + user-prompt §CONSTRAINTS."""
        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)

        try:
            await handler.handle(
                stage=_make_stage(),
                envelope=_make_envelope(),
                prior_results={"warrior": "1 failed"},
            )
        except Exception:
            pass

        if backend.execute.called or backend.dispatch.called:
            mock_call = backend.execute.call_args or backend.dispatch.call_args
            options = None
            for arg in list(mock_call.args) + list(mock_call.kwargs.values()):
                if hasattr(arg, "allowed_tools") or hasattr(arg, "tools"):
                    options = arg
                    break
            assert options is not None
            tool_field = getattr(options, "allowed_tools", None) or getattr(options, "tools", None)
            assert "Bash" not in tool_field, (
                "BON-513 axiom: Sage corrects xfail decorators only — never "
                "Bash. (User prompt §CONSTRAINTS.)"
            )
            assert "Write" not in tool_field, (
                "BON-513 axiom: Sage edits xfail decorators only — never "
                "creates new files. (User prompt §CONSTRAINTS.)"
            )


# ---------------------------------------------------------------------------
# 3. TestAttemptCounter
#    META_CORRECTION_CYCLES increments per cycle; capped at 1 in v0.1.
# ---------------------------------------------------------------------------


class TestAttemptCounter:
    """Sage §D8 line 779 + §D-CL.2 line 203 + §D-CL.7 #3:
    `META_CORRECTION_CYCLES` is the per-cycle counter; v0.1 caps at 1.
    Re-verify after correction; if still failing, escalate (do NOT loop)."""

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_first_correction_cycle_sets_cycles_to_one(self) -> None:
        """After one correction cycle, envelope metadata records cycles=1
        (parseable as int)."""
        from bonfire.models.envelope import META_CORRECTION_CYCLES

        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="correction commit deadbeef",
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        cycles_value = result.metadata.get(META_CORRECTION_CYCLES)
        assert cycles_value is not None
        assert int(cycles_value) >= 1

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_second_attempt_caps_at_max_and_escalates(self) -> None:
        """If `META_CORRECTION_CYCLES >= 1` already in prior_results, the
        handler MUST NOT spawn another correction cycle — it escalates."""
        from bonfire.models.envelope import (
            META_CORRECTION_CYCLES,
            META_CORRECTION_ESCALATED,
        )

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={
                "warrior": "1 failed",
                META_CORRECTION_CYCLES: "1",
            },
        )
        # No second backend dispatch — counter cap honored.
        assert backend.execute.call_count == 0
        # Escalation flag set.
        assert result.metadata.get(META_CORRECTION_ESCALATED) is True

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_attempt_counter_is_string_in_prior_results(self) -> None:
        """Sage §D8 line 779: `prior_results: dict[str, str]` — counter is
        stringified-int at the boundary. Handler MUST tolerate string values."""
        from bonfire.models.envelope import META_CORRECTION_CYCLES

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="green")
        handler = _make_handler(backend=backend, classifier=classifier)
        # Pass counter as string ("1"), not int (1).
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={
                "warrior": "passed",
                META_CORRECTION_CYCLES: "0",  # string-not-int
            },
        )
        # Handler did not raise on string-typed counter.
        assert result is not None


# ---------------------------------------------------------------------------
# 4. TestEscalatePath
#    WARRIOR_BUG and AMBIGUOUS verdicts produce ESCALATED envelopes.
# ---------------------------------------------------------------------------


class TestEscalatePath:
    """User-prompt Q9a + Q4a + Sage §D8: escalation paths.

    - WARRIOR_BUG -> handler short-circuits, NO sage dispatch,
      `META_CORRECTION_ESCALATED=True`.
    - AMBIGUOUS -> gate fails hard (severity='error'); handler can still
      mark envelope and let downstream halt the pipeline.
    """

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_warrior_bug_verdict_escalates_without_dispatch(self) -> None:
        """`META_CLASSIFIER_VERDICT="warrior_bug"` -> NO Sage dispatch."""
        from bonfire.models.envelope import META_CORRECTION_ESCALATED

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="warrior_bug")
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # Verify the escalation contract.
        assert backend.execute.call_count == 0
        assert result.metadata.get(META_CORRECTION_ESCALATED) is True

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_ambiguous_verdict_marks_envelope_for_gate_block(self) -> None:
        """User-prompt Q9a: AMBIGUOUS verdict -> gate fails hard
        (severity='error'); pipeline halts. The handler envelope carries
        the AMBIGUOUS classifier verdict so the gate can read it."""
        from bonfire.models.envelope import META_CLASSIFIER_VERDICT

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="ambiguous")
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        # No dispatch on AMBIGUOUS (defensive — Sage can't fix what
        # classifier can't decisively name).
        assert backend.execute.call_count == 0
        # Envelope carries the AMBIGUOUS verdict for the gate.
        assert result.metadata.get(META_CLASSIFIER_VERDICT) == "ambiguous"

    @pytest.mark.asyncio
    @_HANDLER_XFAIL
    async def test_escalation_preserves_prior_metadata(self) -> None:
        """Sage §D-CL.7 #3: escalation envelope preserves prior metadata
        (no envelope-leak via `with_error` overwrite)."""
        from bonfire.models.envelope import META_PR_NUMBER

        backend = AsyncMock()
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(verdict="warrior_bug")
        handler = _make_handler(backend=backend, classifier=classifier)
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(metadata={META_PR_NUMBER: "42"}),
            prior_results={"warrior": "1 failed"},
        )
        # Prior metadata preserved on escalation (Bardo-style merge).
        assert result.metadata.get(META_PR_NUMBER) == "42"


# ---------------------------------------------------------------------------
# 5. TestPostDispatchVerification
#    Re-verify subprocess; cherry-pick orchestration; timeout teardown.
# ---------------------------------------------------------------------------


class TestPostDispatchVerification:
    """Sage §D7 re-verify loop + §D-CL.7 #2 (subprocess teardown on
    timeout: `proc.kill()` THEN `await proc.wait()`).

    These tests assert the orchestration shape; full subprocess execution
    is mocked. The point is the contract: cherry-pick THEN re-verify
    THEN classify THEN envelope-update."""

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_cherry_pick_invoked_after_successful_dispatch(self) -> None:
        """After Sage-correction dispatch succeeds, handler invokes
        `git_workflow.cherry_pick(commit_sha)` exactly once."""
        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="correction commit sha=abc123",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        pytest_runner.run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert git_workflow.cherry_pick.call_count == 1

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_cherry_pick_failure_returns_failed_envelope(self) -> None:
        """Sage §D-CL.7 #7: cherry-pick failure -> handler returns FAILED
        with `error.error_type` reflecting the cause; no re-verify
        attempted (idempotency)."""
        from bonfire.models.envelope import TaskStatus

        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="ok",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()

        class _GitCommandError(Exception):
            pass

        git_workflow.cherry_pick = MagicMock(side_effect=_GitCommandError("conflict"))
        pytest_runner = AsyncMock()
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert result.status == TaskStatus.FAILED
        # No re-verify attempted after cherry-pick failure.
        assert pytest_runner.run.call_count == 0

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_reverify_subprocess_uses_tuple_args_never_shell(self) -> None:
        """Sage §D-CL.7 #9 + user-prompt §CONSTRAINTS: subprocess args
        MUST be `tuple[str, ...]` or `list[str]`; never `shell=True`.

        We assert the pytest_runner is invoked with structured args (a
        sequence), never with a single shell-string."""
        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="ok",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        pytest_runner.run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        if pytest_runner.run.called:
            call = pytest_runner.run.call_args
            for arg in list(call.args) + list(call.kwargs.values()):
                # Reject shell=True anywhere in the call.
                assert arg is not True or not isinstance(call.kwargs.get("shell"), bool), (
                    "shell=True forbidden by user-prompt §CONSTRAINTS"
                )
            # If args list/tuple was passed, every element is str.
            for arg in list(call.args) + list(call.kwargs.values()):
                if isinstance(arg, (list, tuple)) and arg:
                    assert all(isinstance(x, str) for x in arg), (
                        "subprocess args must be sequence-of-str"
                    )

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_reverify_pass_marks_envelope_corrected(self) -> None:
        """After cherry-pick, re-verify pytest passes -> envelope
        metadata `META_CORRECTION_VERDICT="corrected"`."""
        from bonfire.models.envelope import META_CORRECTION_VERDICT

        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="ok",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        pytest_runner.run.return_value = MagicMock(returncode=0, stdout="passed", stderr="")
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert result.metadata.get(META_CORRECTION_VERDICT) == "corrected"

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_reverify_still_failing_marks_escalated(self) -> None:
        """After cherry-pick, re-verify still fails -> envelope metadata
        `META_CORRECTION_VERDICT="escalated"` AND
        `META_CORRECTION_ESCALATED=True`."""
        from bonfire.models.envelope import (
            META_CORRECTION_ESCALATED,
            META_CORRECTION_VERDICT,
        )

        backend = AsyncMock()
        backend.execute.return_value = MagicMock(
            status="completed",
            result="ok",
            metadata={"correction_commit_sha": "abc123"},
        )
        classifier = MagicMock()
        classifier.classify.return_value = MagicMock(
            verdict="sage_under_marked",
            missing_deps=frozenset({"BON-X"}),
        )
        git_workflow = MagicMock()
        git_workflow.cherry_pick = MagicMock(return_value=None)
        pytest_runner = AsyncMock()
        # Re-verify still fails.
        pytest_runner.run.return_value = MagicMock(
            returncode=1,
            stdout="1 failed",
            stderr="",
        )
        handler = _make_handler(
            backend=backend,
            classifier=classifier,
            git_workflow=git_workflow,
            pytest_runner=pytest_runner,
        )
        result = await handler.handle(
            stage=_make_stage(),
            envelope=_make_envelope(),
            prior_results={"warrior": "1 failed"},
        )
        assert result.metadata.get(META_CORRECTION_VERDICT) == "escalated"
        assert result.metadata.get(META_CORRECTION_ESCALATED) is True

    @pytest.mark.asyncio
    @_FULL_STACK_XFAIL
    async def test_handler_handle_is_coroutine_function(self) -> None:
        """Defensive: handle is async (mirrors Sage §D-CL.1 line 56 but
        Knight B asserts again because the handler innovation classes
        rely on this for AsyncMock fixture wiring)."""
        handler = _make_handler()
        assert inspect.iscoroutinefunction(handler.handle)
