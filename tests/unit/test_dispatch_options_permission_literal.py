"""RED contract for ``DispatchOptions.permission_mode`` Literal lock — W5.G.

Mirror Probe N+1 findings S1.9 + S1.10:

Subject: ``bonfire.protocols.DispatchOptions.permission_mode`` is currently
typed as ``str`` (free-form). The Claude Agent SDK honors the special string
``"bypassPermissions"`` by **skipping ALL permission checks, including the
registered PreToolUse security_hooks chain**. With ``permission_mode: str``
this entire defense-in-depth framework is bypassable by any caller that
constructs ``DispatchOptions(permission_mode="bypassPermissions")``.

This file pins down the v0.1 ship-safe answer: lock ``permission_mode`` to a
``Literal[...]`` of the four values Bonfire actually understands. The SDK's
``"bypassPermissions"`` escape-hatch is deliberately excluded from the
allow-set — the security hooks must always run.

Allowed values:
    * ``"default"`` (SDK ask-mode; the new post-#72 default)
    * ``"acceptEdits"`` (SDK auto-accept-edits mode)
    * ``"plan"`` (SDK plan-only mode)
    * ``"dontAsk"`` (legacy deny-all-without-prompting; opted in by name in
      ``handlers/wizard.py`` and ``handlers/sage_correction_bounce.py``)

Disallowed (currently accepted by ``str`` field — these are the bug surface):
    * ``"bypassPermissions"`` — bypasses security_hooks; THE defect.
    * ``"bypass"`` — typo/short-form that today silently no-ops in the SDK.
    * ``"auto"`` — common typo for ``"acceptEdits"``.
    * ``"UNKNOWN"`` — arbitrary string; today silently no-ops.
    * ``""`` — empty; today silently no-ops.

The Warrior's job after this RED contract is one line:

    permission_mode: Literal["default", "acceptEdits", "plan", "dontAsk"] = "default"

(plus the import already present in ``protocols.py``).
"""

from __future__ import annotations

import typing

import pydantic
import pytest

from bonfire.protocols import DispatchOptions

# ---------------------------------------------------------------------------
# 1. Disallowed values must raise ValidationError
# ---------------------------------------------------------------------------


class TestDisallowedPermissionModesRejected:
    """Free-form strings the SDK doesn't honor (or honors dangerously) are rejected."""

    def test_bypass_permissions_is_rejected(self) -> None:
        """The SDK's ``bypassPermissions`` value is the headline defect.

        With ``permission_mode='bypassPermissions'`` the SDK skips ALL
        PreToolUse hooks, defeating Bonfire's security_hooks chain.
        """
        with pytest.raises(pydantic.ValidationError):
            DispatchOptions(permission_mode="bypassPermissions")

    def test_short_form_bypass_is_rejected(self) -> None:
        """``"bypass"`` is not an SDK value; today it silently no-ops."""
        with pytest.raises(pydantic.ValidationError):
            DispatchOptions(permission_mode="bypass")

    def test_auto_is_rejected(self) -> None:
        """``"auto"`` is a common typo for ``"acceptEdits"`` — reject hard."""
        with pytest.raises(pydantic.ValidationError):
            DispatchOptions(permission_mode="auto")

    def test_arbitrary_unknown_string_is_rejected(self) -> None:
        """Any non-Literal string must fail validation."""
        with pytest.raises(pydantic.ValidationError):
            DispatchOptions(permission_mode="UNKNOWN")

    def test_empty_string_is_rejected(self) -> None:
        """The empty string is not a valid permission mode."""
        with pytest.raises(pydantic.ValidationError):
            DispatchOptions(permission_mode="")


# ---------------------------------------------------------------------------
# 2. Allowed values must construct cleanly
# ---------------------------------------------------------------------------


class TestAllowedPermissionModesAccepted:
    """The four Literal members all construct without error."""

    @pytest.mark.parametrize(
        "mode",
        ["default", "acceptEdits", "plan", "dontAsk"],
    )
    def test_allowed_mode_round_trips(self, mode: str) -> None:
        opts = DispatchOptions(permission_mode=mode)
        assert opts.permission_mode == mode


# ---------------------------------------------------------------------------
# 3. Default value preserved (regression on PR #72 flip)
# ---------------------------------------------------------------------------


class TestDefaultPreserved:
    """The PR #72 default flip (``"default"``) survives the Literal lock."""

    def test_default_is_default_string(self) -> None:
        """``DispatchOptions()`` still produces ``permission_mode == "default"``."""
        opts = DispatchOptions()
        assert opts.permission_mode == "default"


# ---------------------------------------------------------------------------
# 4. Static-analysis surface — the field IS typed as Literal
# ---------------------------------------------------------------------------


class TestPermissionModeIsLiteral:
    """``typing.get_type_hints`` must report the Literal[...] shape.

    This pins the static-analysis surface — third-party type checkers
    (mypy, pyright) only see what ``typing.get_type_hints`` exposes. A
    runtime Literal validator without a Literal annotation would silently
    fail to surface the constraint to IDEs and CI.
    """

    def test_type_hint_is_literal_of_four_allowed_values(self) -> None:
        hints = typing.get_type_hints(DispatchOptions)
        permission_hint = hints["permission_mode"]

        # The annotation must be a Literal[...] form
        assert typing.get_origin(permission_hint) is typing.Literal, (
            f"DispatchOptions.permission_mode should be typed as "
            f"typing.Literal[...]; got origin {typing.get_origin(permission_hint)!r} "
            f"for annotation {permission_hint!r}"
        )

        # And its args must be exactly the four allowed values (order-agnostic)
        allowed = {"default", "acceptEdits", "plan", "dontAsk"}
        assert set(typing.get_args(permission_hint)) == allowed, (
            f"DispatchOptions.permission_mode Literal should hold exactly "
            f"{allowed!r}; got {set(typing.get_args(permission_hint))!r}"
        )
