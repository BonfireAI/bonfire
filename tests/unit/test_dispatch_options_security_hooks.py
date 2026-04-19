"""RED contract tests — ``DispatchOptions.security_hooks`` field.

Sage-canonical (BON-338). Knight-B basis. Locks Sage D9.

- Field name ``security_hooks`` (snake_case, plural).
- Type ``SecurityHooksConfig`` (imported from ``bonfire.dispatch.security_hooks``).
- Default factory ``SecurityHooksConfig`` — non-None by default.
- Default instance has ``enabled=True`` — trust-triangle W4.2 guarantee.
- Frozen model: cannot reassign after construction.
- BON-338 does NOT add ``role``, ``tool_policy``, or ``disallowed_tools``
  (those are BON-337's territory).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

try:
    from bonfire.dispatch.security_hooks import SecurityHooksConfig
    from bonfire.protocols import DispatchOptions
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    SecurityHooksConfig = None  # type: ignore[assignment,misc]
    DispatchOptions = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    if _IMPORT_ERROR is not None:
        pytest.fail(
            f"DispatchOptions.security_hooks not importable: {_IMPORT_ERROR}"
        )


class TestSecurityHooksFieldPresent:
    def test_field_exists(self):
        assert "security_hooks" in DispatchOptions.model_fields

    def test_field_name_snake_case_plural(self):
        """D9 lockdown: NOT ``security``, NOT ``hook_config``."""
        names = set(DispatchOptions.model_fields.keys())
        assert "security_hooks" in names
        assert "security" not in names
        assert "hook_config" not in names
        assert "hooks" not in names

    def test_field_type_is_security_hooks_config(self):
        info = DispatchOptions.model_fields["security_hooks"]
        assert info.annotation is SecurityHooksConfig

    def test_bon337_fields_absent(self):
        """BON-338 MUST NOT add BON-337's fields."""
        names = set(DispatchOptions.model_fields.keys())
        for forbidden in ("tool_policy", "disallowed_tools"):
            assert forbidden not in names, (
                f"Field {forbidden!r} belongs to BON-337 — must not appear here."
            )


class TestSecurityHooksDefault:
    def test_default_instance_present(self):
        opts = DispatchOptions()
        assert opts.security_hooks is not None

    def test_default_is_security_hooks_config(self):
        opts = DispatchOptions()
        assert isinstance(opts.security_hooks, SecurityHooksConfig)

    def test_default_is_enabled(self):
        """Trust-triangle W4.2: default config MUST have enabled=True."""
        opts = DispatchOptions()
        assert opts.security_hooks.enabled is True

    def test_default_emits_events(self):
        opts = DispatchOptions()
        assert opts.security_hooks.emit_denial_events is True

    def test_default_no_extra_patterns(self):
        opts = DispatchOptions()
        assert opts.security_hooks.extra_deny_patterns == []

    def test_default_factory_produces_consistent_state(self):
        a = DispatchOptions()
        b = DispatchOptions()
        assert a.security_hooks == b.security_hooks


class TestSecurityHooksOverride:
    def test_disable_via_constructor(self):
        opts = DispatchOptions(security_hooks=SecurityHooksConfig(enabled=False))
        assert opts.security_hooks.enabled is False

    def test_extra_patterns_via_constructor(self):
        cfg = SecurityHooksConfig(extra_deny_patterns=["rm\\s+.*"])
        opts = DispatchOptions(security_hooks=cfg)
        assert opts.security_hooks.extra_deny_patterns == ["rm\\s+.*"]

    def test_override_preserves_other_options(self):
        opts = DispatchOptions(
            model="x",
            max_turns=3,
            security_hooks=SecurityHooksConfig(enabled=False),
        )
        assert opts.model == "x"
        assert opts.max_turns == 3
        assert opts.security_hooks.enabled is False


class TestDispatchOptionsFrozen:
    def test_reassignment_raises(self):
        opts = DispatchOptions()
        with pytest.raises(ValidationError):
            opts.security_hooks = SecurityHooksConfig(enabled=False)  # type: ignore[misc]
