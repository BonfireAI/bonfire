"""CANONICAL RED — BON-337 (Sage-merged) — ``ToolPolicy`` + ``DefaultToolPolicy``.

Merged from Knight-A (adversarial) and Knight-B (conservative contract).
The Warrior implements ``src/bonfire/dispatch/tool_policy.py`` against THIS
file. Every assertion below is a locked contract.

Sage decisions asserted (BON-337 unified Sage doc, 2026-04-18):
    D1  — Module path ``bonfire.dispatch.tool_policy``; ``__all__`` =
          {"DefaultToolPolicy", "ToolPolicy"}.
    D2  — ``ToolPolicy`` is a ``@runtime_checkable`` Protocol with one method
          ``tools_for(role: str) -> list[str]``.
    D3  — ``DefaultToolPolicy`` implements the 8-role W1.5.3 floor matrix
          byte-for-byte; unmapped roles return ``[]``; each call returns a
          FRESH list (callers may mutate). ``_FLOOR: dict[str, list[str]]``.
    D8  — ``ToolPolicy`` is NOT re-exported from ``bonfire.protocols.__all__``.

Sage ambiguity locks merged from both Knights:
    AMBIG #5 — ``DefaultToolPolicy.tools_for`` MUST be defensive against
               non-str inputs: hashable non-str (None, int, tuple) returns
               ``[]`` (because ``dict.get(x, [])`` with a hashable non-str
               key just misses). Unhashable inputs (list, dict) raise
               ``TypeError`` from dict.get — that is Python's built-in
               behavior and is the acceptable failure mode.

Knight-A adversarial tests (elevated to mandatory, not xfail):
    whitespace/case/unicode/prefix/adversarial-role-name /
    concurrency-immutability / return-type lockdown / Bard-Bash-omission /
    wizard-steward strictness / scout web-access.
"""

from __future__ import annotations

import inspect
from typing import Protocol, get_type_hints

import pytest

# Lazy-imported — Warrior's job to make these importable. Shim mirrors the
# pattern in the pre-existing ``test_protocols.py``.
try:
    from bonfire.dispatch.tool_policy import DefaultToolPolicy, ToolPolicy
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    DefaultToolPolicy = None  # type: ignore[assignment,misc]
    ToolPolicy = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module() -> None:
    """Fail every test while ``bonfire.dispatch.tool_policy`` is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.tool_policy not importable: {_IMPORT_ERROR}")


_ALL_ROLES = ("scout", "knight", "warrior", "prover", "sage", "bard", "wizard", "steward")


# ===========================================================================
# 1. Module location + __all__ re-export discipline (D1, D8)
# ===========================================================================


class TestModuleLocation:
    """Sage D1 — module lives at ``bonfire.dispatch.tool_policy``."""

    def test_module_importable_from_dispatch_subpackage(self) -> None:
        """Module MUST live inside ``bonfire.dispatch`` (D1 lockdown)."""
        import bonfire.dispatch.tool_policy as tp_module

        assert tp_module is not None

    def test_module_exports_tool_policy(self) -> None:
        """``ToolPolicy`` is importable from the module."""
        from bonfire.dispatch.tool_policy import ToolPolicy as _TP

        assert _TP is not None

    def test_module_exports_default_tool_policy(self) -> None:
        """``DefaultToolPolicy`` is importable from the module."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy as _DTP

        assert _DTP is not None

    def test_all_contains_both_symbols(self) -> None:
        """Sage D1 — ``__all__`` lists exactly these two names."""
        import bonfire.dispatch.tool_policy as tp_module

        assert hasattr(tp_module, "__all__")
        assert set(tp_module.__all__) == {"DefaultToolPolicy", "ToolPolicy"}


class TestProtocolExportDiscipline:
    """Sage D8 — ``ToolPolicy`` MUST NOT leak into ``bonfire.protocols``."""

    def test_tool_policy_not_in_protocols_all(self) -> None:
        """Sage D8 — ``ToolPolicy`` NOT in ``bonfire.protocols.__all__``."""
        import bonfire.protocols as proto_mod

        assert "ToolPolicy" not in getattr(proto_mod, "__all__", ())

    def test_default_tool_policy_not_in_protocols_all(self) -> None:
        """Sage D8 — ``DefaultToolPolicy`` NOT in ``bonfire.protocols.__all__``."""
        import bonfire.protocols as proto_mod

        assert "DefaultToolPolicy" not in getattr(proto_mod, "__all__", ())

    def test_tool_policy_not_attribute_on_protocols(self) -> None:
        """Sage D8 — ``ToolPolicy`` is NOT a public attribute of ``bonfire.protocols``."""
        import bonfire.protocols as proto_mod

        assert not hasattr(proto_mod, "ToolPolicy")

    def test_protocols_all_unchanged(self) -> None:
        """Sage D8 — ``bonfire.protocols.__all__`` remains exactly the v0.1 set."""
        import bonfire.protocols as proto_mod

        assert set(proto_mod.__all__) == {
            "AgentBackend",
            "DispatchOptions",
            "QualityGate",
            "StageHandler",
            "VaultBackend",
            "VaultEntry",
        }


# ===========================================================================
# 2. ``ToolPolicy`` Protocol shape (D2)
# ===========================================================================


class TestToolPolicyProtocolShape:
    """Sage D2 — ``ToolPolicy`` is a ``@runtime_checkable`` Protocol."""

    def test_tool_policy_is_a_protocol(self) -> None:
        """``ToolPolicy`` MUST be a ``typing.Protocol`` subclass."""
        assert issubclass(ToolPolicy, Protocol) or Protocol in ToolPolicy.__mro__

    def test_default_policy_satisfies_protocol(self) -> None:
        """``DefaultToolPolicy`` structurally satisfies ``ToolPolicy``."""
        assert isinstance(DefaultToolPolicy(), ToolPolicy)

    def test_protocol_is_runtime_checkable(self) -> None:
        """Sage D2 — any duck type with ``tools_for`` satisfies the protocol."""

        class _FakePolicy:
            def tools_for(self, role: str) -> list[str]:
                return ["Read"]

        assert isinstance(_FakePolicy(), ToolPolicy)

    def test_protocol_has_tools_for_attribute(self) -> None:
        """Sage D2 — the protocol declares ``tools_for`` — exact method name."""
        assert hasattr(ToolPolicy, "tools_for")

    def test_protocol_does_not_declare_get_role_tools(self) -> None:
        """Sage D2 lockdown — ``get_role_tools`` (blocked V1 name) MUST NOT be it."""
        assert not hasattr(ToolPolicy, "get_role_tools")


class TestToolPolicyProtocolNegative:
    """Protocol rejects non-conforming classes / objects."""

    def test_class_without_tools_for_rejected(self) -> None:
        """An object lacking ``tools_for`` MUST NOT satisfy the protocol."""

        class _NotAPolicy:
            def get_tools(self, role: str) -> list[str]:
                return []

        assert not isinstance(_NotAPolicy(), ToolPolicy)

    def test_class_with_v1_misnamed_method_rejected(self) -> None:
        """``get_role_tools`` (V1 drift name) MUST NOT satisfy the protocol."""

        class _V1StylePolicy:
            def get_role_tools(self, role: str) -> list[str]:
                return []

        assert not isinstance(_V1StylePolicy(), ToolPolicy)

    def test_none_is_not_a_policy(self) -> None:
        """``None`` is emphatically not a conforming implementation."""
        assert not isinstance(None, ToolPolicy)

    def test_arbitrary_object_is_not_a_policy(self) -> None:
        """Random objects don't satisfy the protocol."""
        assert not isinstance(object(), ToolPolicy)
        assert not isinstance("some string", ToolPolicy)
        assert not isinstance(42, ToolPolicy)
        assert not isinstance([], ToolPolicy)


class TestToolPolicySignature:
    """Sage D2 — exact signature of ``tools_for``."""

    def test_tools_for_signature_arity(self) -> None:
        """``tools_for`` declares exactly ``(self, role)`` — 2 params."""
        sig = inspect.signature(ToolPolicy.tools_for)
        params = list(sig.parameters.values())
        assert len(params) == 2
        assert params[1].name == "role"

    def test_tools_for_role_param_is_str(self) -> None:
        """Sage D2 — parameter ``role`` MUST be typed as ``str``."""
        hints = get_type_hints(ToolPolicy.tools_for)
        assert hints.get("role") is str

    def test_tools_for_return_type_is_list_of_str(self) -> None:
        """Sage D2 — return type MUST be ``list[str]``. Not Sequence, tuple, frozenset."""
        hints = get_type_hints(ToolPolicy.tools_for)
        assert hints.get("return") == list[str]


# ===========================================================================
# 3. ``DefaultToolPolicy`` floor matrix — byte-for-byte contract (D3)
# ===========================================================================


class TestDefaultToolPolicyFloorMatrix:
    """Sage D3 — the 8-role floor is the W1.5.3 deliverable, frozen verbatim."""

    @pytest.mark.parametrize(
        ("role", "expected"),
        [
            ("scout", ["Read", "Write", "Grep", "WebSearch", "WebFetch"]),
            ("knight", ["Read", "Write", "Edit", "Grep", "Glob"]),
            ("warrior", ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]),
            ("prover", ["Read", "Bash", "Grep", "Glob"]),
            ("sage", ["Read", "Write", "Grep"]),
            ("bard", ["Read", "Write", "Grep", "Glob"]),
            ("wizard", ["Read", "Grep", "Glob"]),
            ("steward", ["Read", "Grep"]),
        ],
    )
    def test_floor_row(self, role: str, expected: list[str]) -> None:
        """Parametrized byte-for-byte floor assertion — the moat."""
        assert DefaultToolPolicy().tools_for(role) == expected


class TestDefaultToolPolicyShape:
    """Sage D3 — class-level attributes + type signatures."""

    def test_class_name_is_singular_no_suffix(self) -> None:
        """Sage D3 lockdown — class name is exactly ``DefaultToolPolicy``."""
        assert DefaultToolPolicy.__name__ == "DefaultToolPolicy"

    def test_has_floor_class_attr(self) -> None:
        """Sage D3 — ``_FLOOR`` class attribute exists, exact name."""
        assert hasattr(DefaultToolPolicy, "_FLOOR")

    def test_floor_has_exactly_eight_roles(self) -> None:
        """Sage D3 — exactly 8 canonical roles. Adding a ninth is out of scope."""
        assert len(DefaultToolPolicy._FLOOR) == 8

    def test_floor_keys_are_exact_eight_roles(self) -> None:
        """Sage D3 — the eight keys are exactly these (order agnostic)."""
        assert set(DefaultToolPolicy._FLOOR.keys()) == set(_ALL_ROLES)

    def test_floor_type_annotation_is_dict_str_list_str(self) -> None:
        """Sage D3 — ``_FLOOR: dict[str, list[str]]`` (D3 code-block lockdown)."""
        hints = get_type_hints(DefaultToolPolicy)
        assert hints.get("_FLOOR") == dict[str, list[str]]

    def test_tools_for_return_type_is_list_str(self) -> None:
        """Sage D3 — ``DefaultToolPolicy.tools_for -> list[str]``."""
        hints = get_type_hints(DefaultToolPolicy.tools_for)
        assert hints.get("return") == list[str]

    def test_tools_for_role_param_is_str(self) -> None:
        """``role: str`` — not enum, not Literal."""
        hints = get_type_hints(DefaultToolPolicy.tools_for)
        assert hints.get("role") is str


# ===========================================================================
# 4. Missing / empty / case — strict-once-opted-in (D3 edges)
# ===========================================================================


class TestDefaultToolPolicyEdges:
    """Sage D3 — unmapped role returns ``[]``; case-sensitive; fresh list."""

    def test_unknown_role_returns_empty_list(self) -> None:
        """Sage D3 — unmapped role MUST return ``[]``."""
        assert DefaultToolPolicy().tools_for("unknown_role") == []

    def test_unknown_role_returns_empty_not_none(self) -> None:
        """Sage D3 — missing-role default is ``[]``, NOT ``None``."""
        result = DefaultToolPolicy().tools_for("gardener")
        assert result == []
        assert result is not None

    def test_empty_string_role_returns_empty_list(self) -> None:
        """Empty role string MUST return an empty list (D3)."""
        assert DefaultToolPolicy().tools_for("") == []

    def test_numeric_string_role_unmapped(self) -> None:
        """A digits-only role name is unmapped."""
        assert DefaultToolPolicy().tools_for("42") == []

    def test_policy_is_pure(self) -> None:
        """Sage D2 purity clause — same role returns the same list across calls."""
        policy = DefaultToolPolicy()
        for _ in range(3):
            assert policy.tools_for("warrior") == [
                "Read",
                "Write",
                "Edit",
                "Bash",
                "Grep",
                "Glob",
            ]

    def test_instances_share_same_floor(self) -> None:
        """Two ``DefaultToolPolicy`` instances return identical floors."""
        a = DefaultToolPolicy()
        b = DefaultToolPolicy()
        for role in _ALL_ROLES:
            assert a.tools_for(role) == b.tools_for(role)


class TestDefaultToolPolicyCaseSensitive:
    """Scout-1/337 §6 — tool names ARE case-sensitive; role keys too."""

    def test_case_variation_capital_rejected(self) -> None:
        """``"Knight"`` != ``"knight"`` — case-sensitive lookup."""
        assert DefaultToolPolicy().tools_for("Knight") == []

    def test_case_variation_all_caps_rejected(self) -> None:
        """``"KNIGHT"`` != ``"knight"`` — case-sensitive lookup."""
        assert DefaultToolPolicy().tools_for("KNIGHT") == []

    def test_case_variation_scout_rejected(self) -> None:
        """``"Scout"`` != ``"scout"`` — case-sensitive lookup."""
        assert DefaultToolPolicy().tools_for("Scout") == []
        assert DefaultToolPolicy().tools_for("SCOUT") == []
        assert DefaultToolPolicy().tools_for("scout") != []


# ===========================================================================
# 5. Whitespace / unicode / prefix — no fuzzy match (D3 lockdown)
# ===========================================================================


class TestRoleNameAdversarialEdges:
    """Sage D3 lockdown: lookup is dict.get — no auto-trim, no prefix match."""

    def test_whitespace_only_role_returns_empty(self) -> None:
        """Role consisting of spaces only MUST be treated as unmapped."""
        assert DefaultToolPolicy().tools_for("   ") == []

    def test_tab_only_role_returns_empty(self) -> None:
        """Tab-only role MUST be treated as unmapped."""
        assert DefaultToolPolicy().tools_for("\t") == []

    def test_newline_only_role_returns_empty(self) -> None:
        """Newline-only role MUST be treated as unmapped."""
        assert DefaultToolPolicy().tools_for("\n") == []

    def test_trailing_whitespace_treated_as_unmapped(self) -> None:
        """``"knight "`` (trailing space) is NOT ``"knight"`` — no stripping."""
        assert DefaultToolPolicy().tools_for("knight ") == []

    def test_leading_whitespace_treated_as_unmapped(self) -> None:
        """Leading whitespace does NOT collapse to canonical role."""
        assert DefaultToolPolicy().tools_for(" knight") == []

    def test_interior_space_role_unmapped(self) -> None:
        """Role with interior space is unmapped."""
        assert DefaultToolPolicy().tools_for("knight errant") == []

    def test_unicode_role_returns_empty(self) -> None:
        """Unicode / non-ASCII role name is unmapped (no mojibake match)."""
        assert DefaultToolPolicy().tools_for("ニンジャ") == []

    def test_unicode_homoglyph_scout_returns_empty(self) -> None:
        """Cyrillic ``с`` (U+0441) lookalike MUST NOT match ASCII ``"scout"``."""
        fake_scout = "\u0441cout"  # looks like "scout" but isn't
        assert DefaultToolPolicy().tools_for(fake_scout) == []

    def test_very_long_role_string_returns_empty(self) -> None:
        """1000-char role string is unmapped and does not raise."""
        long_role = "x" * 1000
        assert DefaultToolPolicy().tools_for(long_role) == []

    def test_knight_prefix_variants_unmapped(self) -> None:
        """``"knight"`` prefix does NOT fuzzy-match — only exact lookup."""
        assert DefaultToolPolicy().tools_for("knight-custom") == []
        assert DefaultToolPolicy().tools_for("knight_v2") == []
        assert DefaultToolPolicy().tools_for("knightly") == []

    def test_scout_prefix_variants_unmapped(self) -> None:
        """Variations on ``scout`` are unmapped — keys are not prefix-matched."""
        assert DefaultToolPolicy().tools_for("scout_v2") == []
        assert DefaultToolPolicy().tools_for("scout/primary") == []
        assert DefaultToolPolicy().tools_for("scout.1") == []


# ===========================================================================
# 6. Adversarial role-name content — tool-name collisions, traversal
# ===========================================================================


class TestAdversarialRoleNames:
    """Roles named literally like tools/wildcards must NEVER short-circuit lookup."""

    def test_role_named_bash_returns_empty(self) -> None:
        """A role literally named ``"Bash"`` MUST NOT leak Bash access."""
        assert DefaultToolPolicy().tools_for("Bash") == []
        assert DefaultToolPolicy().tools_for("bash") == []

    def test_role_named_read_returns_empty(self) -> None:
        """Role literally named after a tool ``"Read"`` is unmapped."""
        assert DefaultToolPolicy().tools_for("Read") == []

    def test_role_wildcard_star_returns_empty(self) -> None:
        """``"*"`` role MUST NOT be interpreted as "all tools"."""
        assert DefaultToolPolicy().tools_for("*") == []

    def test_role_glob_pattern_returns_empty(self) -> None:
        """Glob / regex patterns in the role are just strings — unmapped."""
        assert DefaultToolPolicy().tools_for("*knight*") == []
        assert DefaultToolPolicy().tools_for(".*") == []
        assert DefaultToolPolicy().tools_for("knight|warrior") == []

    def test_role_path_traversal_returns_empty(self) -> None:
        """Path-traversal-looking roles are just unmapped strings."""
        assert DefaultToolPolicy().tools_for("../scout") == []
        assert DefaultToolPolicy().tools_for("../../scout") == []
        assert DefaultToolPolicy().tools_for("/scout") == []

    def test_role_with_null_byte_unmapped(self) -> None:
        """Null byte in role name is unmapped and does not raise."""
        assert DefaultToolPolicy().tools_for("scout\x00") == []
        assert DefaultToolPolicy().tools_for("\x00scout") == []

    def test_role_with_sql_fragment_unmapped(self) -> None:
        """SQL-like fragments are just strings; no parsing happens."""
        assert DefaultToolPolicy().tools_for("'; DROP TABLE --") == []

    def test_role_dict_method_name_unmapped(self) -> None:
        """``"__class__"``, ``"__init__"``, ``"keys"`` — no accidental hits."""
        policy = DefaultToolPolicy()
        assert policy.tools_for("__class__") == []
        assert policy.tools_for("__init__") == []
        assert policy.tools_for("keys") == []
        assert policy.tools_for("get") == []


# ===========================================================================
# 7. Non-str role argument — defensive graceful-or-raise (AMBIG #5 lock)
# ===========================================================================


class TestRoleArgumentTypeBoundary:
    """Sage AMBIG #5 — ``DefaultToolPolicy.tools_for`` defensive for non-str.

    Pydantic validation happens upstream at ``DispatchOptions.role``; the
    policy itself is intentionally non-crashy for hashable non-str
    (``dict.get`` just misses). Unhashable containers raise ``TypeError``
    from Python's built-in ``dict.get`` — that is the acceptable failure
    mode at this layer.
    """

    def test_none_as_role_returns_empty(self) -> None:
        """``None`` as role: ``dict.get(None, [])`` just misses → ``[]``."""
        result = DefaultToolPolicy().tools_for(None)  # type: ignore[arg-type]
        assert result == []

    def test_int_as_role_returns_empty(self) -> None:
        """``42`` as role: hashable, not in floor → ``[]``."""
        assert DefaultToolPolicy().tools_for(42) == []  # type: ignore[arg-type]

    def test_tuple_as_role_returns_empty(self) -> None:
        """Tuples are hashable but never in floor → ``[]``."""
        assert DefaultToolPolicy().tools_for(("scout",)) == []  # type: ignore[arg-type]

    def test_unhashable_list_raises_typeerror(self) -> None:
        """Passing a ``list`` as role raises ``TypeError`` from dict.get."""
        with pytest.raises(TypeError):
            DefaultToolPolicy().tools_for(["scout"])  # type: ignore[arg-type]

    def test_unhashable_dict_raises_typeerror(self) -> None:
        """Passing a ``dict`` as role raises ``TypeError`` from dict.get."""
        with pytest.raises(TypeError):
            DefaultToolPolicy().tools_for({"role": "scout"})  # type: ignore[arg-type]


# ===========================================================================
# 8. Concurrency / immutability — fresh list each call (D3 lockdown)
# ===========================================================================


class TestConcurrencyImmutability:
    """Sage D3 — ``list(...)`` wrap is load-bearing; each call yields a fresh list."""

    def test_fresh_list_per_call_identity(self) -> None:
        """Two calls with same role return DIFFERENT list instances."""
        policy = DefaultToolPolicy()
        a = policy.tools_for("scout")
        b = policy.tools_for("scout")
        assert a == b
        assert a is not b

    def test_caller_mutation_does_not_corrupt_policy(self) -> None:
        """Mutating a returned list MUST NOT affect subsequent lookups."""
        policy = DefaultToolPolicy()
        first = policy.tools_for("scout")
        first.append("Bash")
        first.clear()
        second = policy.tools_for("scout")
        assert second == ["Read", "Write", "Grep", "WebSearch", "WebFetch"]

    def test_mutation_of_returned_list_across_roles_isolated(self) -> None:
        """Mutating one role's list MUST NOT affect any other role."""
        policy = DefaultToolPolicy()
        scout_list = policy.tools_for("scout")
        scout_list.append("Bash")
        scout_list.append("../../etc/passwd")

        knight = policy.tools_for("knight")
        assert "Bash" not in knight
        assert knight == ["Read", "Write", "Edit", "Grep", "Glob"]

    def test_empty_result_for_unmapped_role_is_also_fresh(self) -> None:
        """Even the empty-list branch returns a fresh list per call."""
        policy = DefaultToolPolicy()
        a = policy.tools_for("gardener")
        b = policy.tools_for("gardener")
        assert a == [] and b == []
        a.append("leak")
        c = policy.tools_for("gardener")
        assert c == []

    def test_empty_result_for_empty_role_is_also_fresh(self) -> None:
        """Empty-string role yields a fresh (mutable-safe) empty list."""
        policy = DefaultToolPolicy()
        a = policy.tools_for("")
        a.append("Bash")
        b = policy.tools_for("")
        assert b == []

    def test_many_instances_do_not_share_floor_state(self) -> None:
        """Two ``DefaultToolPolicy()`` instances are independent w.r.t. mutation."""
        p1 = DefaultToolPolicy()
        p2 = DefaultToolPolicy()
        p1_scout = p1.tools_for("scout")
        p1_scout.append("Bash")
        assert "Bash" not in p2.tools_for("scout")

    def test_purity_same_role_same_list_value(self) -> None:
        """Sage D2 purity clause — 100 calls, equal list each time."""
        policy = DefaultToolPolicy()
        results = [policy.tools_for("warrior") for _ in range(100)]
        first = results[0]
        for r in results[1:]:
            assert r == first


# ===========================================================================
# 9. Return-type lockdown — list (not tuple, frozenset, Sequence)
# ===========================================================================


class TestReturnTypeLockdown:
    """Sage D2 — return type is exactly ``list[str]``."""

    def test_return_type_is_list_for_mapped_role(self) -> None:
        """Returned value for a mapped role MUST be a ``list``."""
        assert type(DefaultToolPolicy().tools_for("scout")) is list

    def test_return_type_is_list_for_unmapped_role(self) -> None:
        """Returned value for an unmapped role MUST be a ``list``, not ``None``."""
        assert type(DefaultToolPolicy().tools_for("unknown")) is list

    def test_return_type_is_list_for_empty_role(self) -> None:
        """Returned value for empty-string role MUST be a ``list``."""
        assert type(DefaultToolPolicy().tools_for("")) is list

    def test_all_floor_entries_are_strings(self) -> None:
        """Every tool name in every floor list MUST be a ``str``."""
        policy = DefaultToolPolicy()
        for role in _ALL_ROLES:
            tools = policy.tools_for(role)
            assert all(isinstance(t, str) for t in tools), role

    def test_no_duplicates_in_any_role_floor(self) -> None:
        """Floor lists MUST NOT contain duplicate tool names."""
        policy = DefaultToolPolicy()
        for role in _ALL_ROLES:
            tools = policy.tools_for(role)
            assert len(tools) == len(set(tools)), role


# ===========================================================================
# 10. Intent-level guard rails — who has Bash, Web, read-only discipline
# ===========================================================================


class TestBardBashOmission:
    """Sage D3 — Bard's floor intentionally OMITS Bash."""

    def test_bard_floor_does_not_contain_bash(self) -> None:
        """``bard`` MUST NOT get Bash — documented Sage D3 intent."""
        assert "Bash" not in DefaultToolPolicy().tools_for("bard")

    def test_bard_floor_has_write_for_pr_body_staging(self) -> None:
        """Bard DOES get Write — to stage PR bodies via files (Sage D3 note)."""
        assert "Write" in DefaultToolPolicy().tools_for("bard")


class TestReadMostlyRolesAreStrict:
    """Wizard / Steward / Sage are review-time roles; lock their restricted floors."""

    def test_steward_is_strictly_read_only(self) -> None:
        """Steward has ONLY Read + Grep (no Write, no Bash, no Edit)."""
        tools = set(DefaultToolPolicy().tools_for("steward"))
        assert "Write" not in tools
        assert "Edit" not in tools
        assert "Bash" not in tools

    def test_wizard_has_no_write_or_edit(self) -> None:
        """Wizard reviews — must NOT have Write/Edit/Bash."""
        tools = set(DefaultToolPolicy().tools_for("wizard"))
        assert "Write" not in tools
        assert "Edit" not in tools
        assert "Bash" not in tools

    def test_sage_does_not_have_bash(self) -> None:
        """Sage is a synthesis role — no shell access."""
        assert "Bash" not in DefaultToolPolicy().tools_for("sage")

    def test_only_warrior_and_prover_have_bash(self) -> None:
        """Only warrior and prover get Bash across all 8 floors."""
        policy = DefaultToolPolicy()
        roles_with_bash = {role for role in _ALL_ROLES if "Bash" in policy.tools_for(role)}
        assert roles_with_bash == {"warrior", "prover"}


class TestScoutWebAccess:
    """Scouts are the ONLY role with WebSearch / WebFetch on the floor."""

    def test_scout_has_websearch(self) -> None:
        assert "WebSearch" in DefaultToolPolicy().tools_for("scout")

    def test_scout_has_webfetch(self) -> None:
        assert "WebFetch" in DefaultToolPolicy().tools_for("scout")

    def test_no_other_role_has_websearch(self) -> None:
        """Only scout gets WebSearch across the entire floor."""
        policy = DefaultToolPolicy()
        for role in _ALL_ROLES:
            if role == "scout":
                continue
            assert "WebSearch" not in policy.tools_for(role), role

    def test_no_other_role_has_webfetch(self) -> None:
        """Only scout gets WebFetch across the entire floor."""
        policy = DefaultToolPolicy()
        for role in _ALL_ROLES:
            if role == "scout":
                continue
            assert "WebFetch" not in policy.tools_for(role), role
