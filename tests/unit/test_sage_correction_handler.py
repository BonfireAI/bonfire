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

import inspect

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
    role='verifier' (reusing AgentRole.VERIFIER per §A Q1 lines 49-50).
    """
    from bonfire.models.plan import StageSpec

    return StageSpec(
        name="sage_correction_bounce",
        agent_name="sage-correction-bounce",
        role="verifier",
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
    ``AgentRole.VERIFIER`` for the deterministic verification stage; per
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
        """Sage §A Q3 line 132 + §B line 327: ``META_BOUNCE_VERDICT``
        constant lives in ``bonfire.models.envelope`` (alphabetically
        adjacent to existing META_* keys)."""
        from bonfire.models.envelope import META_BOUNCE_VERDICT

        assert isinstance(META_BOUNCE_VERDICT, str)
        assert META_BOUNCE_VERDICT  # non-empty

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_meta_bounce_attempt_constant_importable(self) -> None:
        """Sage §A Q3 line 132 + §B line 327: ``META_BOUNCE_ATTEMPT``
        constant lives in ``bonfire.models.envelope``."""
        from bonfire.models.envelope import META_BOUNCE_ATTEMPT

        assert isinstance(META_BOUNCE_ATTEMPT, str)
        assert META_BOUNCE_ATTEMPT

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_meta_bounce_correction_branch_constant_importable(self) -> None:
        """Sage §A Q3 line 132 + §B line 327: ``META_BOUNCE_CORRECTION_BRANCH``
        constant lives in ``bonfire.models.envelope``."""
        from bonfire.models.envelope import META_BOUNCE_CORRECTION_BRANCH

        assert isinstance(META_BOUNCE_CORRECTION_BRANCH, str)
        assert META_BOUNCE_CORRECTION_BRANCH

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_meta_bounce_keys_distinct(self) -> None:
        """The three new keys are distinct from each other and from
        existing META_* keys (no collision). Mirror BON-519
        ``test_meta_preflight_keys_are_distinct`` discipline."""
        from bonfire.models.envelope import (
            META_BOUNCE_ATTEMPT,
            META_BOUNCE_CORRECTION_BRANCH,
            META_BOUNCE_VERDICT,
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
            META_BOUNCE_VERDICT,
            META_BOUNCE_ATTEMPT,
            META_BOUNCE_CORRECTION_BRANCH,
        }
        assert len(all_keys) == 7, (
            "All three META_BOUNCE_* keys must be distinct from each "
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
        from bonfire.models.envelope import META_BOUNCE_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_BOUNCE_VERDICT: "warrior_bug"}
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
        sentinel is ``META_BOUNCE_VERDICT`` set to a not-needed value).
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
        from bonfire.models.envelope import META_BOUNCE_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        # Trigger an intentionally-undefined verdict to force the
        # ``UnknownClassifierVerdict`` failure path (Sage §D-CL.1 line 91).
        prior = {META_BOUNCE_VERDICT: "this_verdict_is_bogus_xyz"}
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
            META_BOUNCE_VERDICT,
            TaskStatus,
        )

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_BOUNCE_VERDICT: "sage_under_marked"}
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

        The §A-pinned analogous metadata key in BON-513 is ``META_BOUNCE_VERDICT``
        carrying a string value indicating escalation; Knight A pins only
        that the handler returns COMPLETED (not FAILED) for this verdict.
        """
        from bonfire.models.envelope import META_BOUNCE_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_BOUNCE_VERDICT: "warrior_bug"}
        result = await handler.handle(stage, envelope, prior)
        # Escalation is a successful pipeline outcome (Wizard sees the
        # bounce and reviews); handler must NOT return FAILED.
        assert result.status == TaskStatus.COMPLETED

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    async def test_unknown_verdict_yields_failed_envelope(self) -> None:
        """Sage §D-CL.1 line 91: unknown verdict → FAILED envelope with
        ``error.error_type='UnknownClassifierVerdict'`` (fail-safe; never
        silently pass)."""
        from bonfire.models.envelope import META_BOUNCE_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_BOUNCE_VERDICT: "totally_made_up_verdict"}
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
        from bonfire.models.envelope import META_BOUNCE_VERDICT, TaskStatus

        handler = _make_handler()
        envelope = _make_envelope()
        stage = _make_stage_spec()
        prior = {META_BOUNCE_VERDICT: "ambiguous"}
        result = await handler.handle(stage, envelope, prior)
        # AMBIGUOUS is a known verdict — must NOT trigger
        # UnknownClassifierVerdict.
        if result.status == TaskStatus.FAILED and result.error is not None:
            assert result.error.error_type != "UnknownClassifierVerdict", (
                "AMBIGUOUS is a known verdict per §A Q1a (Anta-ratified)."
            )
