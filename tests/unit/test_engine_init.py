"""Canonical RED — public export surface of ``bonfire.engine``.

Synthesized from Knight-A orchestration lens + Knight-B contract-fidelity lens.

Locks the 15-symbol ``__all__`` surface. The 15th symbol —
``SageCorrectionResolvedGate`` — is promoted into ``__all__`` once the
sage-correction-bounce stage is wired into the standard build pipeline.
The compiler interface (V1 ``compiler`` kwarg, V1
``test_executor_compiler.py``) is intentionally omitted for v0.1.

Shim pattern: per-test lazy ``import`` inside each test body. This
produces granular per-test RED rather than one collection ERROR, so the
implementer sees ticket progress move test-by-test as implementation lands.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Canonical 15-symbol public surface.
# ---------------------------------------------------------------------------

_EXPECTED_PUBLIC: tuple[str, ...] = (
    "CheckpointData",
    "CheckpointManager",
    "CheckpointSummary",
    "CompletionGate",
    "ContextBuilder",
    "CostLimitGate",
    "GateChain",
    "PipelineEngine",
    "PipelineResult",
    "RedPhaseGate",
    "ReviewApprovalGate",
    "SageCorrectionResolvedGate",
    "StageExecutor",
    "TestPassGate",
    "VerificationGate",
)


# ===========================================================================
# 1. ``__all__`` contract
# ===========================================================================


class TestAllList:
    """``bonfire.engine.__all__`` locks the v0.1 public surface."""

    def test_all_list_defined(self) -> None:
        """``__all__`` must be defined as a sequence of strings."""
        from bonfire import engine as _e

        assert hasattr(_e, "__all__")
        assert all(isinstance(name, str) for name in _e.__all__)

    def test_all_list_matches_expected_set(self) -> None:
        """``__all__`` equals the 15-symbol canonical set (order-free)."""
        from bonfire import engine as _e

        assert set(_e.__all__) == set(_EXPECTED_PUBLIC)

    def test_all_list_contains_exactly_15_symbols(self) -> None:
        """The v0.1 engine exports exactly 15 names — no compiler symbols."""
        from bonfire import engine as _e

        assert len(set(_e.__all__)) == 15

    def test_sage_correction_resolved_gate_in_all(self) -> None:
        """``SageCorrectionResolvedGate`` is the 15th symbol — promoted into
        ``__all__`` once the sage-correction-bounce stage is wired."""
        from bonfire import engine as _e

        assert "SageCorrectionResolvedGate" in _e.__all__

    def test_all_list_is_sorted(self) -> None:
        """``__all__`` is sorted — mirrors V1 style."""
        from bonfire import engine as _e

        all_list = list(_e.__all__)
        assert all_list == sorted(all_list)

    def test_all_list_has_no_duplicates(self) -> None:
        """Duplicates in ``__all__`` indicate a sloppy rebase; reject them."""
        from bonfire import engine as _e

        assert len(_e.__all__) == len(set(_e.__all__))

    def test_no_private_symbols_leaked_in_all(self) -> None:
        """``__all__`` must not include underscore-prefixed names."""
        from bonfire import engine as _e

        for name in _e.__all__:
            assert not name.startswith("_"), f"private symbol exposed: {name}"


# ===========================================================================
# 2. Symbol importability — every canonical name resolves
# ===========================================================================


class TestSymbolImportability:
    """Every canonical symbol must be importable from ``bonfire.engine``."""

    @pytest.mark.parametrize("symbol", _EXPECTED_PUBLIC)
    def test_symbol_importable_via_package(self, symbol: str) -> None:
        """Every canonical symbol must be an attribute on ``bonfire.engine``."""
        from bonfire import engine as _e

        assert hasattr(_e, symbol), f"missing public symbol: {symbol}"

    def test_star_import_binds_canonical_symbols(self) -> None:
        """``from bonfire.engine import *`` binds every canonical symbol."""
        namespace: dict[str, object] = {}
        exec("from bonfire.engine import *", namespace)  # noqa: S102
        for sym in _EXPECTED_PUBLIC:
            assert sym in namespace, f"star-import did not bind {sym}"


# ===========================================================================
# 3. Submodule layout — canonical 7 submodules resolve
# ===========================================================================


class TestSubmoduleLayout:
    """V1's 7-file layout is preserved in v0.1."""

    def test_pipeline_submodule(self) -> None:
        from bonfire.engine import pipeline

        assert pipeline is not None

    def test_executor_submodule(self) -> None:
        from bonfire.engine import executor

        assert executor is not None

    def test_gates_submodule(self) -> None:
        from bonfire.engine import gates

        assert gates is not None

    def test_checkpoint_submodule(self) -> None:
        from bonfire.engine import checkpoint

        assert checkpoint is not None

    def test_context_submodule(self) -> None:
        from bonfire.engine import context

        assert context is not None

    def test_advisor_submodule(self) -> None:
        """VaultAdvisor lives in ``advisor`` even though it is not in ``__all__``."""
        from bonfire.engine import advisor

        assert advisor is not None


# ===========================================================================
# 4. Type-shape sanity — a few classes must be classes, not modules
# ===========================================================================


class TestTypeShapes:
    """Each canonical name resolves to the right kind of object."""

    def test_pipeline_engine_is_a_class(self) -> None:
        """PipelineEngine must be a class (not a module or callable)."""
        from bonfire import engine as _e

        assert isinstance(_e.PipelineEngine, type)

    def test_pipeline_result_is_pydantic_model(self) -> None:
        """PipelineResult must be a Pydantic BaseModel subclass."""
        from pydantic import BaseModel

        from bonfire import engine as _e

        assert isinstance(_e.PipelineResult, type)
        assert issubclass(_e.PipelineResult, BaseModel)

    def test_stage_executor_is_a_class(self) -> None:
        from bonfire import engine as _e

        assert isinstance(_e.StageExecutor, type)

    def test_context_builder_is_a_class(self) -> None:
        from bonfire import engine as _e

        assert isinstance(_e.ContextBuilder, type)

    def test_checkpoint_manager_is_a_class(self) -> None:
        from bonfire import engine as _e

        assert isinstance(_e.CheckpointManager, type)

    def test_checkpoint_data_is_pydantic_model(self) -> None:
        from pydantic import BaseModel

        from bonfire import engine as _e

        assert isinstance(_e.CheckpointData, type)
        assert issubclass(_e.CheckpointData, BaseModel)

    def test_checkpoint_summary_is_pydantic_model(self) -> None:
        from pydantic import BaseModel

        from bonfire import engine as _e

        assert isinstance(_e.CheckpointSummary, type)
        assert issubclass(_e.CheckpointSummary, BaseModel)

    def test_gate_chain_is_a_class(self) -> None:
        from bonfire import engine as _e

        assert isinstance(_e.GateChain, type)
