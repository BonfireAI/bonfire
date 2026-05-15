"""RED regression tests — BON-886.

The ``bonfire.dispatch`` package public surface must re-export the two
Trust-Triangle (Gate 3) user-facing config types that are currently only
reachable via deeper-path imports:

  * W4.1 — ``ToolPolicy`` / ``DefaultToolPolicy`` (``dispatch/tool_policy.py``)
  * W4.2 — ``SecurityHooksConfig`` (``dispatch/security_hooks.py``)

Today ``dispatch/__init__.py:__all__`` lists only five symbols and omits
all three. External contributors browsing ``from bonfire.dispatch import ...``
cannot discover W4.1 / W4.2 without reading the source tree.

Contract pinned here:
  * ``from bonfire.dispatch import ToolPolicy, DefaultToolPolicy,
    SecurityHooksConfig`` works.
  * ``__all__`` includes the three new symbols.
  * ``__all__`` stays sorted (AC: "alphabetical-sort preserved").
  * Pre-existing exports are not dropped (addition only, no rename).

Until ``dispatch/__init__.py`` re-exports the three symbols, the tests
below FAIL (ImportError / missing-from-__all__).
"""

from __future__ import annotations

import bonfire.dispatch as dispatch_pkg

# Symbols that must remain exported (no regression — addition only).
_PRE_EXISTING_EXPORTS = {
    "ClaudeSDKBackend",
    "DispatchResult",
    "PydanticAIBackend",
    "TierGate",
    "execute_with_retry",
}

# The three symbols BON-886 requires adding.
_REQUIRED_NEW_EXPORTS = {
    "ToolPolicy",
    "DefaultToolPolicy",
    "SecurityHooksConfig",
}


class TestDispatchPackageReExports:
    """BON-886 — W4.1 / W4.2 config types are importable from bonfire.dispatch."""

    def test_tool_policy_importable_from_package_root(self):
        from bonfire.dispatch import ToolPolicy  # noqa: F401

    def test_default_tool_policy_importable_from_package_root(self):
        from bonfire.dispatch import DefaultToolPolicy  # noqa: F401

    def test_security_hooks_config_importable_from_package_root(self):
        from bonfire.dispatch import SecurityHooksConfig  # noqa: F401

    def test_combined_import_statement_works(self):
        """The exact import line from the BON-886 acceptance criteria."""
        from bonfire.dispatch import (  # noqa: F401
            DefaultToolPolicy,
            SecurityHooksConfig,
            ToolPolicy,
        )

    def test_re_exports_are_the_canonical_objects(self):
        """The package-root names must be the same objects as the submodule ones."""
        from bonfire.dispatch.security_hooks import (
            SecurityHooksConfig as _ShcCanonical,
        )
        from bonfire.dispatch.tool_policy import (
            DefaultToolPolicy as _DtpCanonical,
        )
        from bonfire.dispatch.tool_policy import (
            ToolPolicy as _TpCanonical,
        )

        assert dispatch_pkg.ToolPolicy is _TpCanonical
        assert dispatch_pkg.DefaultToolPolicy is _DtpCanonical
        assert dispatch_pkg.SecurityHooksConfig is _ShcCanonical


class TestDispatchPackageAllList:
    """BON-886 — __all__ includes the new symbols, stays sorted, drops nothing."""

    def test_all_includes_required_new_exports(self):
        names = set(dispatch_pkg.__all__)
        missing = _REQUIRED_NEW_EXPORTS - names
        assert not missing, (
            f"dispatch.__all__ is missing W4.1/W4.2 surface symbols: {sorted(missing)}"
        )

    def test_all_retains_pre_existing_exports(self):
        names = set(dispatch_pkg.__all__)
        dropped = _PRE_EXISTING_EXPORTS - names
        assert not dropped, (
            f"dispatch.__all__ must not drop pre-existing exports: {sorted(dropped)}"
        )

    def test_all_is_sorted(self):
        """AC: alphabetical-sort preserved."""
        assert list(dispatch_pkg.__all__) == sorted(dispatch_pkg.__all__), (
            f"dispatch.__all__ must stay alphabetically sorted, got {dispatch_pkg.__all__}"
        )

    def test_every_all_entry_is_a_real_attribute(self):
        for name in dispatch_pkg.__all__:
            assert hasattr(dispatch_pkg, name), (
                f"dispatch.__all__ lists {name!r} but it is not importable"
            )
