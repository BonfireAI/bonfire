"""CANONICAL RED — BON-337 (Sage-merged) — ``DispatchOptions.role`` field.

Merged from Knight-A (adversarial) and Knight-B (conservative contract).
The Warrior adds ``role: str = ""`` to ``DispatchOptions`` in
``src/bonfire/protocols.py`` against THIS file.

Sage decisions asserted (BON-337 unified Sage doc, 2026-04-18):
    D4  — Add ``role: str = ""`` to the existing frozen Pydantic
          ``DispatchOptions`` model. Type is ``str`` (not Optional, not
          Literal, not enum). Default is ``""`` (empty string). Placement:
          "Agent isolation" block, immediately below ``permission_mode``.
    D7  — ``options.role`` is NOT consumed by ``sdk_backend.py`` in BON-337;
          that's BON-338's job. This file asserts Pydantic contract only.

Sage ambiguity locks encoded here:
    AMBIG #2 — ``DispatchOptions(role=None)`` MUST raise ``ValidationError``.
    AMBIG #3 — The existing ``test_has_exactly_eight_fields`` assertion in
               ``tests/unit/test_protocols.py`` is the WARRIOR's
               responsibility to update (8 → 9) when adding ``role``.
               This file does NOT duplicate that test.
    AMBIG #4 — ``DispatchOptions(role=42)`` MUST raise ``ValidationError``.
               Warrior may need ``strict=True`` on the role field or a
               validator to enforce (see implementation note).
"""

from __future__ import annotations

from typing import get_type_hints

import pytest
from pydantic import ValidationError

from bonfire.protocols import DispatchOptions

# ===========================================================================
# 1. Field existence + canonical name (Sage D4)
# ===========================================================================


class TestRoleFieldExists:
    """Sage D4 — ``role`` is declared on ``DispatchOptions``."""

    def test_role_field_in_model_fields(self) -> None:
        """Sage D4 — ``role`` is a declared Pydantic field, not a stray attribute."""
        assert "role" in DispatchOptions.model_fields

    def test_field_name_is_lowercase_singular(self) -> None:
        """Sage D4 lockdown — field name is ``role`` (not ``agent_role``, not ``stage_role``)."""
        assert "agent_role" not in DispatchOptions.model_fields
        assert "stage_role" not in DispatchOptions.model_fields
        assert "role" in DispatchOptions.model_fields


# ===========================================================================
# 2. Type lock — str, not Optional, not Literal, not enum (Sage D4)
# ===========================================================================


class TestRoleFieldType:
    """Sage D4 — ``role: str`` exactly."""

    def test_role_annotation_is_str(self) -> None:
        """Sage D4 — the field annotation resolves to ``str``."""
        hints = get_type_hints(DispatchOptions)
        assert hints.get("role") is str

    def test_role_model_field_annotation_is_str(self) -> None:
        """Pydantic's ``FieldInfo.annotation`` must also report ``str`` (not Optional)."""
        assert DispatchOptions.model_fields["role"].annotation is str

    def test_role_value_is_str_instance(self) -> None:
        """Constructed default is a Python ``str`` instance."""
        opts = DispatchOptions()
        assert isinstance(opts.role, str)


# ===========================================================================
# 3. Default value lock (Sage D4)
# ===========================================================================


class TestRoleFieldDefault:
    """Sage D4 — default is ``""`` (empty string, not ``None``)."""

    def test_default_is_empty_string(self) -> None:
        """Sage D4 lockdown — empty string default."""
        opts = DispatchOptions()
        assert opts.role == ""

    def test_default_is_not_none(self) -> None:
        """Sage D4 — default is NOT ``None`` (field is ``str``, not ``Optional``)."""
        opts = DispatchOptions()
        assert opts.role is not None

    def test_default_is_zero_length(self) -> None:
        """Empty string default has length zero."""
        opts = DispatchOptions()
        assert len(opts.role) == 0


# ===========================================================================
# 4. Construction — canonical + adversarial values
# ===========================================================================


class TestRoleFieldValueAcceptance:
    """``role: str`` accepts arbitrary strings — no Literal constraint."""

    def test_construct_with_no_role_kwarg_works(self) -> None:
        """Sage D4 — backward compat: omitted ``role`` still works."""
        opts = DispatchOptions()
        assert opts.role == ""

    def test_explicit_canonical_role_warrior(self) -> None:
        opts = DispatchOptions(role="warrior")
        assert opts.role == "warrior"

    def test_explicit_canonical_role_scout(self) -> None:
        opts = DispatchOptions(role="scout")
        assert opts.role == "scout"

    def test_construct_with_role_empty_string_explicit(self) -> None:
        """Explicit ``role=""`` is valid (same as default)."""
        opts = DispatchOptions(role="")
        assert opts.role == ""

    def test_construct_with_arbitrary_role_string(self) -> None:
        """``role: str`` is free-form; any str accepted at model layer."""
        opts = DispatchOptions(role="gardener")
        assert opts.role == "gardener"

    def test_whitespace_role_accepted_verbatim(self) -> None:
        """Pydantic str field does NOT auto-strip; the SDK-facing ratchet decides."""
        opts = DispatchOptions(role="   ")
        assert opts.role == "   "

    def test_unicode_role_accepted(self) -> None:
        """Unicode role string survives round-trip at model layer."""
        opts = DispatchOptions(role="ニンジャ")
        assert opts.role == "ニンジャ"

    def test_very_long_role_accepted(self) -> None:
        """1000-char role string is accepted and retained verbatim."""
        long_role = "x" * 1000
        opts = DispatchOptions(role=long_role)
        assert opts.role == long_role
        assert len(opts.role) == 1000

    def test_role_with_control_chars_accepted(self) -> None:
        """Control characters in role preserved verbatim at model layer."""
        opts = DispatchOptions(role="knight\x00\t\n")
        assert opts.role == "knight\x00\t\n"

    def test_role_with_leading_slash_accepted(self) -> None:
        """Path-like strings are just strings at this layer."""
        opts = DispatchOptions(role="../scout")
        assert opts.role == "../scout"

    def test_role_paired_with_tools_and_model(self) -> None:
        """Sage D4 + D7 — role travels alongside tools and model."""
        opts = DispatchOptions(
            model="claude-opus-4-7",
            tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
            role="warrior",
        )
        assert opts.role == "warrior"
        assert opts.tools == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert opts.model == "claude-opus-4-7"


# ===========================================================================
# 5. Type coercion / rejection at the Pydantic boundary
# ===========================================================================


class TestRoleFieldTypeCoercion:
    """Sage AMBIG #2 + #4 — non-str inputs MUST raise ``ValidationError``."""

    def test_role_rejects_none(self) -> None:
        """AMBIG #2 — ``role: str`` NOT ``str | None``; ``None`` raises."""
        with pytest.raises(ValidationError):
            DispatchOptions(role=None)  # type: ignore[arg-type]

    def test_role_rejects_int(self) -> None:
        """AMBIG #4 — ``role=42`` MUST raise (Warrior: add ``strict=True`` if Pydantic coerces)."""
        with pytest.raises(ValidationError):
            DispatchOptions(role=42)  # type: ignore[arg-type]

    def test_role_rejects_bool(self) -> None:
        """Bool is not a str — MUST raise."""
        with pytest.raises(ValidationError):
            DispatchOptions(role=True)  # type: ignore[arg-type]

    def test_role_rejects_list(self) -> None:
        """A list is not a str — MUST raise ValidationError."""
        with pytest.raises(ValidationError):
            DispatchOptions(role=["knight"])  # type: ignore[arg-type]

    def test_role_rejects_dict(self) -> None:
        """A dict is not a str — MUST raise ValidationError."""
        with pytest.raises(ValidationError):
            DispatchOptions(role={"r": "knight"})  # type: ignore[arg-type]


# ===========================================================================
# 6. Frozen discipline — pre-existing model_config=frozen inherits for role
# ===========================================================================


class TestRoleFieldFrozen:
    """``DispatchOptions`` is frozen (pre-existing); ``role`` inherits the lock."""

    def test_cannot_mutate_role_after_construction(self) -> None:
        """Sage D4 + pre-existing ``model_config = ConfigDict(frozen=True)``."""
        opts = DispatchOptions(role="warrior")
        with pytest.raises(ValidationError):
            opts.role = "scout"  # type: ignore[misc]

    def test_cannot_delete_role_after_construction(self) -> None:
        """Pydantic frozen model — deletion also blocked."""
        opts = DispatchOptions(role="warrior")
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            del opts.role

    def test_model_copy_with_role_update_works(self) -> None:
        """``model_copy(update=...)`` IS the escape hatch for frozen models."""
        opts = DispatchOptions(role="warrior")
        new_opts = opts.model_copy(update={"role": "knight"})
        assert opts.role == "warrior"  # original unchanged
        assert new_opts.role == "knight"


# ===========================================================================
# 7. Non-interference with existing fields
# ===========================================================================


class TestRoleFieldNonInterference:
    """Adding ``role`` MUST NOT change behavior of existing fields."""

    def test_tools_still_defaults_to_empty_list(self) -> None:
        """``tools`` default is still ``[]`` after adding role."""
        opts = DispatchOptions()
        assert opts.tools == []

    def test_permission_mode_still_defaults_to_default(self) -> None:
        """CONTRACT-CHANGE: default flipped from 'dontAsk' to 'default'.

        Per the CLI / scanner / session hardening contract, the SDK-level
        ask-mode is the new ship-safe default. Explicit ``dontAsk``
        opt-ins in ``handlers/`` are unchanged.
        """
        opts = DispatchOptions()
        assert opts.permission_mode == "default"

    def test_tools_and_role_coexist(self) -> None:
        """Both fields coexist independently."""
        opts = DispatchOptions(
            tools=["Read", "Write", "Edit", "Bash", "Grep", "Glob"],
            role="warrior",
        )
        assert opts.tools == ["Read", "Write", "Edit", "Bash", "Grep", "Glob"]
        assert opts.role == "warrior"

    def test_role_default_with_explicit_tools(self) -> None:
        """Setting ``tools=`` alone leaves ``role=""``."""
        opts = DispatchOptions(tools=["Read"])
        assert opts.tools == ["Read"]
        assert opts.role == ""

    def test_tools_default_with_explicit_role(self) -> None:
        """Setting ``role=`` alone leaves ``tools=[]``."""
        opts = DispatchOptions(role="warrior")
        assert opts.role == "warrior"
        assert opts.tools == []


# ===========================================================================
# 8. Serialization round-trip
# ===========================================================================


class TestRoleFieldSerialization:
    """``role`` serializes / deserializes cleanly — important for logs / vault."""

    def test_model_dump_includes_role(self) -> None:
        """``role`` appears in ``model_dump()`` output."""
        opts = DispatchOptions(role="warrior")
        dumped = opts.model_dump()
        assert "role" in dumped
        assert dumped["role"] == "warrior"

    def test_model_dump_empty_role_present(self) -> None:
        """Even default ``""`` role is present in serialization."""
        opts = DispatchOptions()
        dumped = opts.model_dump()
        assert dumped["role"] == ""

    def test_model_validate_round_trip(self) -> None:
        """Dump → validate preserves role."""
        original = DispatchOptions(role="knight", tools=["Read"])
        dumped = original.model_dump()
        restored = DispatchOptions.model_validate(dumped)
        assert restored.role == original.role
        assert restored.tools == original.tools

    def test_model_dump_json_includes_role(self) -> None:
        """JSON serialization includes role."""
        import json

        opts = DispatchOptions(role="warrior")
        json_str = opts.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["role"] == "warrior"


# ===========================================================================
# 9. Equality / hashing — role participates in model equality
# ===========================================================================


class TestRoleFieldEquality:
    """Two ``DispatchOptions`` with same fields compare equal; role participates."""

    def test_same_role_equal(self) -> None:
        a = DispatchOptions(role="warrior")
        b = DispatchOptions(role="warrior")
        assert a == b

    def test_different_role_not_equal(self) -> None:
        a = DispatchOptions(role="warrior")
        b = DispatchOptions(role="knight")
        assert a != b

    def test_default_empty_role_equal(self) -> None:
        """Two options with default (empty) role are equal."""
        a = DispatchOptions()
        b = DispatchOptions(role="")
        assert a == b
