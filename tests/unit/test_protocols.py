"""RED tests for bonfire.protocols — pluggable extension-point contracts.

Covers the four core runtime-checkable protocols (AgentBackend, VaultBackend,
QualityGate, StageHandler) and the two supporting Pydantic value types
(DispatchOptions, VaultEntry).

Contract highlights locked by this suite (Warrior hands these back GREEN):

* All four protocols decorated with ``@runtime_checkable``.
* No protocol inherits from ``abc.ABC``; no ABCMeta metaclass anywhere.
* The module lives at ``bonfire.protocols`` (package root), never under
  ``bonfire.models``.  Cross-package model types are imported under
  ``if TYPE_CHECKING:`` only.
* The module does not import from ``bonfire.engine``, ``bonfire.dispatch``,
  ``bonfire.cli``, or ``bonfire.handlers`` at any scope.
* ``DispatchOptions`` is a frozen Pydantic model with exactly eight fields
  (see ``TestDispatchOptions`` for the inventory + default + type lock).
* ``VaultEntry`` is a frozen Pydantic model whose ``entry_id`` default factory
  yields a 12-character lowercase hex string sliced from ``uuid4().hex``.

The RED phase uses the same shim pattern as ``test_envelope.py``: the imports
are attempted inside ``try/except`` so collection always succeeds, then the
autouse fixture fails every test with the captured ``ImportError`` message
until the Warrior lands the module.
"""

from __future__ import annotations

import abc
import inspect
from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

if TYPE_CHECKING:
    # These names are used only by stringified annotations inside the
    # conformer test classes below. ``from __future__ import annotations``
    # defers their evaluation, so they never need to resolve at runtime.
    # noqa is load-bearing: ruff cannot see the deferred-annotation usage.
    from bonfire.models.envelope import Envelope  # noqa: F401
    from bonfire.models.plan import (  # noqa: F401
        GateContext,
        GateResult,
        StageSpec,
    )

# ---------------------------------------------------------------------------
# RED-phase import shim — mirror of tests/unit/test_envelope.py
# Collection must succeed; each test fails via the autouse fixture below.
# ---------------------------------------------------------------------------
try:
    from bonfire.protocols import (
        AgentBackend,
        DispatchOptions,
        QualityGate,
        StageHandler,
        VaultBackend,
        VaultEntry,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    AgentBackend = VaultBackend = QualityGate = StageHandler = None  # type: ignore[assignment,misc]
    DispatchOptions = VaultEntry = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test with the import error while bonfire.protocols is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.protocols not importable: {_IMPORT_ERROR}")


# Parametrize lists are assembled at collection time. In the RED phase these
# are all ``None``; the autouse fixture still fails each test before the
# parametrize id function runs because pytest evaluates ids lazily.
ALL_PROTOCOLS = [AgentBackend, VaultBackend, QualityGate, StageHandler]
ALL_PROTOCOL_IDS = ["AgentBackend", "VaultBackend", "QualityGate", "StageHandler"]


# ---------------------------------------------------------------------------
# TestImports — public surface
# ---------------------------------------------------------------------------


class TestImports:
    """All six public names live at ``bonfire.protocols``."""

    def test_agent_backend_importable(self):
        assert AgentBackend is not None

    def test_vault_backend_importable(self):
        assert VaultBackend is not None

    def test_quality_gate_importable(self):
        assert QualityGate is not None

    def test_stage_handler_importable(self):
        assert StageHandler is not None

    def test_dispatch_options_importable(self):
        assert DispatchOptions is not None

    def test_vault_entry_importable(self):
        assert VaultEntry is not None

    def test_all_exports_listed(self):
        """``__all__`` covers every public symbol expected by the module spec."""
        import bonfire.protocols as mod

        exported = set(mod.__all__)
        assert {
            "AgentBackend",
            "DispatchOptions",
            "QualityGate",
            "StageHandler",
            "VaultBackend",
            "VaultEntry",
        } <= exported

    def test_module_path_is_top_level(self):
        """The module is ``bonfire.protocols``, not ``bonfire.models.protocols``."""
        import bonfire.protocols as mod

        assert mod.__name__ == "bonfire.protocols"
        assert "/models/" not in mod.__file__.replace("\\", "/")

    def test_module_is_importable_via_importlib(self):
        """Canonical dotted path must round-trip through ``importlib``."""
        import importlib

        mod = importlib.import_module("bonfire.protocols")
        assert mod is not None


# ---------------------------------------------------------------------------
# TestRuntimeCheckable — every protocol carries the @runtime_checkable marker
# ---------------------------------------------------------------------------


class TestRuntimeCheckable:
    """Every protocol is decorated with ``@runtime_checkable`` (C47)."""

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=ALL_PROTOCOL_IDS)
    def test_runtime_protocol_marker_present(self, proto):
        """``typing`` sets ``_is_runtime_protocol`` when ``@runtime_checkable`` is applied."""
        assert getattr(proto, "_is_runtime_protocol", False) is True

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=ALL_PROTOCOL_IDS)
    def test_isinstance_does_not_raise(self, proto):
        """A bare object must resolve to ``False``, never raise ``TypeError``."""
        assert isinstance(object(), proto) is False

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=ALL_PROTOCOL_IDS)
    def test_isinstance_none_is_false(self, proto):
        """``None`` is emphatically not a conforming implementation."""
        assert isinstance(None, proto) is False

    def test_direct_instantiation_is_forbidden(self):
        """Protocols are contracts, not classes — direct ``AgentBackend()`` raises."""
        with pytest.raises(TypeError):
            AgentBackend()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# TestNoABCs — typing.Protocol only, never abc.ABC (C48)
# ---------------------------------------------------------------------------


class TestNoABCs:
    """Protocols are structural (``typing.Protocol``), not nominal (``abc.ABC``)."""

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=ALL_PROTOCOL_IDS)
    def test_metaclass_is_not_abcmeta(self, proto):
        """Metaclass must not be *exactly* ``abc.ABCMeta``.

        ``typing.Protocol`` uses ``typing._ProtocolMeta``, which **inherits**
        from ``abc.ABCMeta`` at the CPython level. Therefore
        ``isinstance(proto, abc.ABCMeta)`` is always ``True`` for any
        ``Protocol`` subclass — an unreachable invariant. The correct fence is
        an identity check on the metaclass: ``_ProtocolMeta is not ABCMeta``
        catches a regression where a protocol is accidentally declared as a
        plain ``abc.ABC`` (metaclass becomes ``ABCMeta`` exactly), while still
        admitting the legitimate ``_ProtocolMeta`` case.
        """
        assert type(proto) is not abc.ABCMeta

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=ALL_PROTOCOL_IDS)
    def test_protocol_does_not_inherit_abc(self, proto):
        assert not issubclass(proto, abc.ABC)

    @pytest.mark.parametrize("proto", ALL_PROTOCOLS, ids=ALL_PROTOCOL_IDS)
    def test_protocol_is_typing_protocol(self, proto):
        from typing import Protocol

        assert issubclass(proto, Protocol)

    def test_source_has_no_abc_import(self):
        """``protocols.py`` must not import anything from the ``abc`` module."""
        import bonfire.protocols

        source = inspect.getsource(bonfire.protocols)
        assert "from abc" not in source
        assert "import abc" not in source
        assert "ABCMeta" not in source


# ---------------------------------------------------------------------------
# TestAgentBackendConformance — execute() + health_check()
# ---------------------------------------------------------------------------


class TestAgentBackendConformance:
    """``AgentBackend`` requires ``execute`` and ``health_check``."""

    def test_conforming_class_is_instance(self):
        class _Good:
            async def execute(
                self, envelope: Envelope, *, options: DispatchOptions
            ) -> Envelope: ...

            async def health_check(self) -> bool: ...

        assert isinstance(_Good(), AgentBackend)

    def test_missing_execute_is_not_instance(self):
        class _Bad:
            async def health_check(self) -> bool: ...

        assert not isinstance(_Bad(), AgentBackend)

    def test_missing_health_check_is_not_instance(self):
        class _Bad:
            async def execute(
                self, envelope: Envelope, *, options: DispatchOptions
            ) -> Envelope: ...

        assert not isinstance(_Bad(), AgentBackend)

    def test_empty_class_is_not_instance(self):
        class _Empty:
            pass

        assert not isinstance(_Empty(), AgentBackend)

    def test_execute_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(AgentBackend.execute)

    def test_health_check_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(AgentBackend.health_check)

    def test_sync_methods_still_match_isinstance(self):
        """Documented gotcha: ``runtime_checkable`` checks NAME only, not async-ness.

        A sync implementation registers as conforming at runtime even though
        the protocol stubs are async. Static type-checkers will flag it, but
        ``isinstance`` will not. This invariant is load-bearing: downstream
        code that needs async-discipline must rely on a type checker, never on
        runtime isinstance alone.
        """

        class _SyncImpostor:
            def execute(self, envelope, *, options): ...  # sync, not async

            def health_check(self) -> bool: ...  # sync, not async

        assert isinstance(_SyncImpostor(), AgentBackend)

    def test_extra_methods_still_conform(self):
        """Protocols define a minimum interface — extras are welcome."""

        class _Extended:
            async def execute(
                self, envelope: Envelope, *, options: DispatchOptions
            ) -> Envelope: ...

            async def health_check(self) -> bool: ...

            def extra(self) -> str:
                return "bonus"

        assert isinstance(_Extended(), AgentBackend)

    def test_agent_conformer_is_not_a_vault(self):
        """Same-shape confusion: ``AgentBackend`` and ``VaultBackend`` are
        distinct types. An ``AgentBackend`` conformer must NOT satisfy
        ``VaultBackend`` (different method names)."""

        class _AgentOnly:
            async def execute(
                self, envelope: Envelope, *, options: DispatchOptions
            ) -> Envelope: ...

            async def health_check(self) -> bool: ...

        instance = _AgentOnly()
        assert isinstance(instance, AgentBackend)
        assert not isinstance(instance, VaultBackend)


# ---------------------------------------------------------------------------
# TestVaultBackendConformance — four-method contract
# ---------------------------------------------------------------------------


class TestVaultBackendConformance:
    """``VaultBackend`` requires ``store``, ``query``, ``exists``, and ``get_by_source``."""

    def test_conforming_class_is_instance(self):
        class _Good:
            async def store(self, entry: VaultEntry) -> str: ...

            async def query(
                self,
                query: str,
                *,
                limit: int = 5,
                entry_type: str | None = None,
            ) -> list[VaultEntry]: ...

            async def exists(self, content_hash: str) -> bool: ...

            async def get_by_source(self, source_path: str) -> list[VaultEntry]: ...

        assert isinstance(_Good(), VaultBackend)

    def test_missing_store_is_not_instance(self):
        class _Bad:
            async def query(
                self,
                query: str,
                *,
                limit: int = 5,
                entry_type: str | None = None,
            ) -> list[VaultEntry]: ...

            async def exists(self, content_hash: str) -> bool: ...

            async def get_by_source(self, source_path: str) -> list[VaultEntry]: ...

        assert not isinstance(_Bad(), VaultBackend)

    def test_missing_query_is_not_instance(self):
        class _Bad:
            async def store(self, entry: VaultEntry) -> str: ...

            async def exists(self, content_hash: str) -> bool: ...

            async def get_by_source(self, source_path: str) -> list[VaultEntry]: ...

        assert not isinstance(_Bad(), VaultBackend)

    def test_missing_exists_is_not_instance(self):
        class _Bad:
            async def store(self, entry: VaultEntry) -> str: ...

            async def query(
                self,
                query: str,
                *,
                limit: int = 5,
                entry_type: str | None = None,
            ) -> list[VaultEntry]: ...

            async def get_by_source(self, source_path: str) -> list[VaultEntry]: ...

        assert not isinstance(_Bad(), VaultBackend)

    def test_missing_get_by_source_is_not_instance(self):
        class _Bad:
            async def store(self, entry: VaultEntry) -> str: ...

            async def query(
                self,
                query: str,
                *,
                limit: int = 5,
                entry_type: str | None = None,
            ) -> list[VaultEntry]: ...

            async def exists(self, content_hash: str) -> bool: ...

        assert not isinstance(_Bad(), VaultBackend)

    def test_store_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(VaultBackend.store)

    def test_query_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(VaultBackend.query)

    def test_exists_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(VaultBackend.exists)

    def test_get_by_source_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(VaultBackend.get_by_source)


# ---------------------------------------------------------------------------
# TestQualityGateConformance — one-method protocol
# ---------------------------------------------------------------------------


class TestQualityGateConformance:
    """``QualityGate`` requires ``evaluate``."""

    def test_conforming_class_is_instance(self):
        class _Good:
            async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult: ...

        assert isinstance(_Good(), QualityGate)

    def test_missing_evaluate_is_not_instance(self):
        class _Bad:
            pass

        assert not isinstance(_Bad(), QualityGate)

    def test_wrong_method_name_is_not_instance(self):
        """Name matters. ``check`` is not ``evaluate``."""

        class _Bad:
            async def check(self, envelope: Envelope, context: GateContext) -> GateResult: ...

        assert not isinstance(_Bad(), QualityGate)

    def test_evaluate_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(QualityGate.evaluate)

    def test_subclass_of_runtime_protocol_still_conforms(self):
        """A class that explicitly subclasses the protocol also registers."""

        class _Explicit(QualityGate):
            async def evaluate(self, envelope: Envelope, context: GateContext) -> GateResult: ...

        assert isinstance(_Explicit(), QualityGate)


# ---------------------------------------------------------------------------
# TestStageHandlerConformance — arity and composition
# ---------------------------------------------------------------------------


class TestStageHandlerConformance:
    """``StageHandler`` requires ``handle(stage, envelope, prior_results)``."""

    def test_conforming_class_is_instance(self):
        class _Good:
            async def handle(
                self,
                stage: StageSpec,
                envelope: Envelope,
                prior_results: dict[str, str],
            ) -> Envelope: ...

        assert isinstance(_Good(), StageHandler)

    def test_missing_handle_is_not_instance(self):
        class _Bad:
            pass

        assert not isinstance(_Bad(), StageHandler)

    def test_wrong_method_name_is_not_instance(self):
        class _Bad:
            async def run(
                self,
                stage: StageSpec,
                envelope: Envelope,
                prior_results: dict[str, str],
            ) -> Envelope: ...

        assert not isinstance(_Bad(), StageHandler)

    def test_handle_is_coroutine_function(self):
        assert inspect.iscoroutinefunction(StageHandler.handle)

    def test_handle_signature_arity_and_order(self):
        """Signature introspection: ``handle`` stub declares exactly
        ``(self, stage, envelope, prior_results)`` — four parameters, in order."""
        sig = inspect.signature(StageHandler.handle)
        assert len(sig.parameters) == 4
        assert list(sig.parameters.keys()) == [
            "self",
            "stage",
            "envelope",
            "prior_results",
        ]

    def test_extra_methods_still_conform(self):
        """Protocols define minimum interface — extras are fine."""

        class _Extended:
            async def handle(
                self,
                stage: StageSpec,
                envelope: Envelope,
                prior_results: dict[str, str],
            ) -> Envelope: ...

            def extra_method(self) -> None: ...

        assert isinstance(_Extended(), StageHandler)


# ---------------------------------------------------------------------------
# TestDispatchOptions — frozen Pydantic model with 8 fields
# ---------------------------------------------------------------------------


class TestDispatchOptions:
    """``DispatchOptions`` is a frozen Pydantic model; every field has a default."""

    # --- Construction + base fields ------------------------------------

    def test_can_instantiate_with_no_args(self):
        """Every field has a default — no required fields."""
        opts = DispatchOptions()
        assert opts is not None

    def test_model_field_default_is_empty_string(self):
        opts = DispatchOptions()
        assert opts.model == ""
        assert isinstance(opts.model, str)

    def test_max_turns_default_is_ten(self):
        opts = DispatchOptions()
        assert opts.max_turns == 10
        assert isinstance(opts.max_turns, int)

    def test_max_budget_usd_default_is_zero(self):
        opts = DispatchOptions()
        assert opts.max_budget_usd == 0.0
        assert isinstance(opts.max_budget_usd, float)

    def test_override_model(self):
        opts = DispatchOptions(model="claude-sonnet-4-20250514")
        assert opts.model == "claude-sonnet-4-20250514"

    def test_override_max_turns(self):
        opts = DispatchOptions(max_turns=3)
        assert opts.max_turns == 3

    def test_override_max_budget_usd(self):
        opts = DispatchOptions(max_budget_usd=2.5)
        assert opts.max_budget_usd == 2.5

    # --- Cognitive extensions ------------------------------------------

    def test_thinking_depth_default_is_standard(self):
        """Literal field default — must be ``'standard'``, never arbitrary."""
        opts = DispatchOptions()
        assert opts.thinking_depth == "standard"

    def test_thinking_depth_accepts_all_literals(self):
        """The Literal alphabet is: minimal, standard, thorough, ultrathink."""
        for depth in ("minimal", "standard", "thorough", "ultrathink"):
            opts = DispatchOptions(thinking_depth=depth)
            assert opts.thinking_depth == depth

    def test_thinking_depth_rejects_non_literal(self):
        """Pydantic must enforce the Literal — arbitrary strings fail."""
        with pytest.raises(ValidationError):
            DispatchOptions(thinking_depth="cosmic")

    def test_cognitive_mode_default_is_empty_string(self):
        """V1 ground truth: ``cognitive_mode`` is ``str = ""`` — NOT a Literal."""
        opts = DispatchOptions()
        assert opts.cognitive_mode == ""
        assert isinstance(opts.cognitive_mode, str)

    def test_cognitive_mode_accepts_arbitrary_string(self):
        """Because ``cognitive_mode`` is plain ``str``, any string is valid."""
        opts = DispatchOptions(cognitive_mode="exploratory")
        assert opts.cognitive_mode == "exploratory"

    # --- Agent isolation -----------------------------------------------

    def test_tools_default_is_empty_list(self):
        opts = DispatchOptions()
        assert opts.tools == []
        assert isinstance(opts.tools, list)

    def test_tools_accepts_list_of_strings(self):
        opts = DispatchOptions(tools=["Read", "Write", "Bash"])
        assert opts.tools == ["Read", "Write", "Bash"]

    def test_tools_default_factory_isolates_instances(self):
        """``default_factory=list`` must prevent shared-list aliasing across
        instances — a classic Python mutable-default trap."""
        a = DispatchOptions()
        b = DispatchOptions()
        assert a.tools is not b.tools

    def test_cwd_default_is_empty_string(self):
        opts = DispatchOptions()
        assert opts.cwd == ""
        assert isinstance(opts.cwd, str)

    def test_permission_mode_default_is_dontAsk(self):
        opts = DispatchOptions()
        assert opts.permission_mode == "dontAsk"
        assert isinstance(opts.permission_mode, str)

    # --- Frozen immutability -------------------------------------------

    def test_is_frozen_on_model(self):
        opts = DispatchOptions()
        with pytest.raises(ValidationError):
            opts.model = "changed"

    def test_is_frozen_on_max_turns(self):
        opts = DispatchOptions()
        with pytest.raises(ValidationError):
            opts.max_turns = 99

    # --- Field inventory lock ------------------------------------------

    def test_has_exactly_eight_fields(self):
        """The v0.1 field inventory is ten — BON-337 added ``role``,
        BON-338 added ``security_hooks``. Any future field additions are
        a breaking change that must flow through a migration."""
        assert set(DispatchOptions.model_fields.keys()) == {
            "model",
            "max_turns",
            "max_budget_usd",
            "thinking_depth",
            "cognitive_mode",
            "tools",
            "cwd",
            "permission_mode",
            "role",
            "security_hooks",
        }
        assert len(DispatchOptions.model_fields) == 10


# ---------------------------------------------------------------------------
# TestVaultEntry — frozen Pydantic model with auto-generated entry_id
# ---------------------------------------------------------------------------


class TestVaultEntry:
    """``VaultEntry`` is a frozen Pydantic model with an auto-id factory."""

    # --- Construction + required fields --------------------------------

    def test_minimal_construction(self):
        entry = VaultEntry(content="hello", entry_type="note")
        assert entry.content == "hello"
        assert entry.entry_type == "note"

    def test_content_is_required(self):
        with pytest.raises(ValidationError):
            VaultEntry(entry_type="note")  # type: ignore[call-arg]

    def test_entry_type_is_required(self):
        with pytest.raises(ValidationError):
            VaultEntry(content="x")  # type: ignore[call-arg]

    def test_content_field_is_str(self):
        entry = VaultEntry(content="hello", entry_type="note")
        assert isinstance(entry.content, str)

    def test_entry_type_field_is_str(self):
        entry = VaultEntry(content="hello", entry_type="artifact")
        assert isinstance(entry.entry_type, str)

    # --- entry_id auto-generation --------------------------------------

    def test_entry_id_is_auto_generated(self):
        entry = VaultEntry(content="x", entry_type="note")
        assert entry.entry_id != ""
        assert isinstance(entry.entry_id, str)

    def test_entry_id_is_twelve_chars(self):
        """Default factory returns the first 12 chars of ``uuid4().hex``."""
        entry = VaultEntry(content="x", entry_type="note")
        assert len(entry.entry_id) == 12

    def test_entry_id_is_lowercase_hex(self):
        """``uuid4().hex`` yields lowercase hex digits only (0-9a-f)."""
        entry = VaultEntry(content="x", entry_type="note")
        assert all(c in "0123456789abcdef" for c in entry.entry_id)

    def test_entry_ids_are_unique(self):
        a = VaultEntry(content="x", entry_type="note")
        b = VaultEntry(content="x", entry_type="note")
        assert a.entry_id != b.entry_id

    def test_explicit_entry_id_overrides_factory(self):
        entry = VaultEntry(content="x", entry_type="note", entry_id="fixed-id-01")
        assert entry.entry_id == "fixed-id-01"

    # --- Provenance + dedup fields -------------------------------------

    def test_source_path_default_is_empty_string(self):
        entry = VaultEntry(content="x", entry_type="note")
        assert entry.source_path == ""
        assert isinstance(entry.source_path, str)

    def test_project_name_default_is_empty_string(self):
        entry = VaultEntry(content="x", entry_type="note")
        assert entry.project_name == ""
        assert isinstance(entry.project_name, str)

    def test_scanned_at_default_is_empty_string(self):
        entry = VaultEntry(content="x", entry_type="note")
        assert entry.scanned_at == ""
        assert isinstance(entry.scanned_at, str)

    def test_git_hash_default_is_empty_string(self):
        entry = VaultEntry(content="x", entry_type="note")
        assert entry.git_hash == ""
        assert isinstance(entry.git_hash, str)

    def test_content_hash_default_is_empty_string(self):
        entry = VaultEntry(content="x", entry_type="note")
        assert entry.content_hash == ""
        assert isinstance(entry.content_hash, str)

    def test_tags_default_is_empty_list(self):
        entry = VaultEntry(content="x", entry_type="note")
        assert entry.tags == []
        assert isinstance(entry.tags, list)

    def test_tags_default_factory_isolates_instances(self):
        """``default_factory=list`` prevents shared-list aliasing across instances."""
        a = VaultEntry(content="x", entry_type="note")
        b = VaultEntry(content="x", entry_type="note")
        assert a.tags is not b.tags

    # --- Metadata: dict[str, Any] --------------------------------------

    def test_metadata_default_is_empty_dict(self):
        entry = VaultEntry(content="x", entry_type="note")
        assert entry.metadata == {}
        assert isinstance(entry.metadata, dict)

    def test_metadata_accepts_arbitrary_values(self):
        entry = VaultEntry(
            content="x",
            entry_type="note",
            metadata={"score": 0.91, "tags": ["a"], "nested": {"k": 1}},
        )
        assert entry.metadata["score"] == 0.91
        assert entry.metadata["nested"] == {"k": 1}

    # --- Frozen immutability -------------------------------------------

    def test_is_frozen_on_content(self):
        entry = VaultEntry(content="x", entry_type="note")
        with pytest.raises(ValidationError):
            entry.content = "changed"

    def test_is_frozen_on_entry_type(self):
        entry = VaultEntry(content="x", entry_type="note")
        with pytest.raises(ValidationError):
            entry.entry_type = "other"

    # --- Field inventory lock ------------------------------------------

    def test_has_expected_field_inventory(self):
        """Ten fields total, in the order documented in V1 ground truth."""
        assert set(VaultEntry.model_fields.keys()) == {
            "entry_id",
            "content",
            "entry_type",
            "source_path",
            "project_name",
            "scanned_at",
            "git_hash",
            "content_hash",
            "tags",
            "metadata",
        }


# ---------------------------------------------------------------------------
# TestModuleConstraints — C21 + dependency discipline
# ---------------------------------------------------------------------------


class TestModuleConstraints:
    """``protocols.py`` must live at the package root and not depend on
    orchestration internals."""

    def test_module_file_is_top_level_not_nested(self):
        """C21: the file path is ``src/bonfire/protocols.py`` — flat."""
        import bonfire.protocols as mod

        normalized = mod.__file__.replace("\\", "/")
        assert normalized.endswith("/bonfire/protocols.py")
        assert "/bonfire/models/" not in normalized

    def test_no_engine_imports(self):
        import bonfire.protocols

        source = inspect.getsource(bonfire.protocols)
        assert "from bonfire.engine" not in source
        assert "import bonfire.engine" not in source

    def test_no_dispatch_imports(self):
        """BON-338 carve-out: ``SecurityHooksConfig`` MUST be imported from
        ``bonfire.dispatch.security_hooks`` at module load (Pydantic needs
        the runtime type to validate ``DispatchOptions.security_hooks``).

        Any OTHER ``from bonfire.dispatch`` import remains forbidden — this
        test documents the single allowed exception.
        """
        import bonfire.protocols

        source = inspect.getsource(bonfire.protocols)
        allowed = "from bonfire.dispatch.security_hooks import SecurityHooksConfig"
        # Strip the one allowed line then assert no other dispatch imports
        # slipped in.
        stripped = "\n".join(line for line in source.splitlines() if line.strip() != allowed)
        assert "from bonfire.dispatch" not in stripped
        assert "import bonfire.dispatch" not in stripped

    def test_no_cli_imports(self):
        import bonfire.protocols

        source = inspect.getsource(bonfire.protocols)
        assert "from bonfire.cli" not in source
        assert "import bonfire.cli" not in source

    def test_no_handlers_imports(self):
        """``handlers`` implement ``StageHandler`` — they import us, never
        the other way around."""
        import bonfire.protocols

        source = inspect.getsource(bonfire.protocols)
        assert "from bonfire.handlers" not in source
        assert "import bonfire.handlers" not in source

    def test_cross_package_model_imports_are_guarded_by_type_checking(self):
        """``Envelope`` / ``GateContext`` / ``GateResult`` / ``StageSpec`` must
        live under an ``if TYPE_CHECKING:`` guard, not at runtime top level."""
        import bonfire.protocols

        source = inspect.getsource(bonfire.protocols)
        assert "TYPE_CHECKING" in source
        assert "Envelope" in source
        assert "GateContext" in source
        assert "GateResult" in source
        assert "StageSpec" in source


# ---------------------------------------------------------------------------
# TestTypeCheckingImportsInertAtRuntime — structural evidence that
# TYPE_CHECKING-only imports never resolve at runtime, yet isinstance()
# against a runtime-checkable Protocol still works for conformers whose
# method annotations reference those types.
# ---------------------------------------------------------------------------


class TestTypeCheckingImportsInertAtRuntime:
    """Deferred annotations (``from __future__ import annotations``) combined
    with ``TYPE_CHECKING`` guards keep cross-package imports inert at runtime
    while still letting ``typing.Protocol`` register conformers whose methods
    use those types only as annotations."""

    def test_isinstance_works_with_forward_ref_annotations(self):
        """A conformer whose method annotations are stringified still
        registers. ``typing.Protocol`` does not evaluate method annotations
        at ``isinstance`` time."""

        class _WithForwardRefs:
            async def execute(
                self, envelope: Envelope, *, options: DispatchOptions
            ) -> Envelope: ...

            async def health_check(self) -> bool: ...

        assert isinstance(_WithForwardRefs(), AgentBackend)

    def test_module_has_type_checking_guard(self):
        """The source text exhibits the ``if TYPE_CHECKING:`` guard pattern."""
        import bonfire.protocols

        source = inspect.getsource(bonfire.protocols)
        assert "if TYPE_CHECKING:" in source
