"""RED contract tests — ``SecurityHooksConfig`` Pydantic model.

Sage-canonical (BON-338). Merges Knight-B's field inventory + frozen contract
+ Knight-A's adversarial floor-cannot-be-softened lockdowns.

Locks Sage D7 (no fail-open), D8 (config model shape).

- Frozen ``BaseModel`` with ``ConfigDict(frozen=True)``.
- EXACTLY three fields: ``enabled``, ``extra_deny_patterns``, ``emit_denial_events``.
- ``enabled: bool = True``.
- ``extra_deny_patterns: list[str] = []`` (default_factory).
- ``emit_denial_events: bool = True``.
- NO ``extra_allow_patterns`` — BON-337 territory (D8 lockdown).
- NO ``fail_open_on_hook_error`` — D7 fail-closed lockdown.
- NO ``unwrap_max_depth`` — hardcoded to 5 in hook body.
- Exported via ``__all__``.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

try:
    from bonfire.dispatch import security_hooks as _mod
    from bonfire.dispatch.security_hooks import SecurityHooksConfig
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    _mod = None  # type: ignore[assignment]
    SecurityHooksConfig = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.security_hooks not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Class identity (Knight-B)
# ---------------------------------------------------------------------------


class TestConfigClassIdentity:
    def test_class_name(self):
        """Sage D8: exact name ``SecurityHooksConfig`` (plural Hooks)."""
        assert SecurityHooksConfig.__name__ == "SecurityHooksConfig"

    def test_is_pydantic_basemodel(self):
        assert issubclass(SecurityHooksConfig, BaseModel)

    def test_exported_in_all(self):
        names = set(getattr(_mod, "__all__", []) or [])
        assert "SecurityHooksConfig" in names, (
            f"SecurityHooksConfig must be in __all__, got {names}"
        )


# ---------------------------------------------------------------------------
# Defaults — every default is SAFE (Knight-A adversarial framing)
# ---------------------------------------------------------------------------


class TestDefaultsAreSafe:
    """W4.2 trust-triangle: every default MUST fail-closed / deny-by-default."""

    def test_default_enabled_true(self):
        """D8: ``enabled=True`` by default — users get deny set automatically."""
        cfg = SecurityHooksConfig()
        assert cfg.enabled is True

    def test_default_emit_events_true(self):
        """D8: audit trail is on by default."""
        cfg = SecurityHooksConfig()
        assert cfg.emit_denial_events is True

    def test_default_extra_deny_empty(self):
        cfg = SecurityHooksConfig()
        assert cfg.extra_deny_patterns == []

    def test_default_factory_independent_instances(self):
        """Pydantic default_factory trap — each config MUST own its list."""
        a = SecurityHooksConfig()
        b = SecurityHooksConfig()
        assert a.extra_deny_patterns is not b.extra_deny_patterns, (
            "Pydantic Field(default_factory=list) MUST produce independent lists. "
            "Shared mutable default is the classic Python footgun."
        )

    def test_default_construction(self):
        cfg = SecurityHooksConfig()
        assert cfg.enabled is True
        assert cfg.emit_denial_events is True
        assert cfg.extra_deny_patterns == []
        assert isinstance(cfg.extra_deny_patterns, list)


# ---------------------------------------------------------------------------
# Field inventory — exactly three (D8 lockdown)
# ---------------------------------------------------------------------------


class TestConfigFields:
    def test_field_names_exactly(self):
        fields = set(SecurityHooksConfig.model_fields.keys())
        expected = {"enabled", "extra_deny_patterns", "emit_denial_events"}
        assert fields == expected, f"Field inventory mismatch. Expected {expected}, got {fields}"

    def test_field_count_is_exactly_three(self):
        assert len(SecurityHooksConfig.model_fields) == 3


# ---------------------------------------------------------------------------
# Floor cannot be softened (D7 + W1.5.3 — Knight-A adversarial)
# ---------------------------------------------------------------------------


class TestFloorCannotBeSoftened:
    """Forbidden fields MUST NOT exist."""

    def test_no_fail_open_field_exists(self):
        """D7 lockdown: a failsafe that fails open is not a failsafe."""
        assert "fail_open_on_hook_error" not in SecurityHooksConfig.model_fields, (
            "D7 FORBIDS fail_open_on_hook_error. MUST NOT be reintroduced."
        )

    def test_no_extra_allow_patterns_field_exists(self):
        """Allow-lists are BON-337's territory — scope must be clean."""
        assert "extra_allow_patterns" not in SecurityHooksConfig.model_fields

    def test_no_unwrap_depth_field_exists(self):
        """Unwrap depth is hardcoded to 5 in v0.1 — not user-tunable."""
        assert "unwrap_max_depth" not in SecurityHooksConfig.model_fields

    def test_no_override_patterns_field(self):
        """Users cannot delete entries from DEFAULT_DENY_PATTERNS."""
        forbidden = {
            "disabled_rule_ids",
            "remove_patterns",
            "override_deny_patterns",
            "replace_deny_patterns",
            "skip_patterns",
            "allowed_rule_ids",
        }
        for field in forbidden:
            assert field not in SecurityHooksConfig.model_fields, (
                f"Field {field!r} would allow softening the floor. FORBIDDEN."
            )

    def test_no_allow_field_synonyms(self):
        """Any 'allow' field name is BON-337 territory."""
        for name in SecurityHooksConfig.model_fields:
            assert "allow" not in name.lower(), (
                f"Field {name!r} contains 'allow' — BON-337 boundary"
            )


# ---------------------------------------------------------------------------
# Field types
# ---------------------------------------------------------------------------


class TestConfigFieldTypes:
    def test_enabled_type_bool(self):
        info = SecurityHooksConfig.model_fields["enabled"]
        assert info.annotation is bool

    def test_extra_deny_patterns_type_list_str(self):
        info = SecurityHooksConfig.model_fields["extra_deny_patterns"]
        assert info.annotation == list[str]

    def test_emit_denial_events_type_bool(self):
        info = SecurityHooksConfig.model_fields["emit_denial_events"]
        assert info.annotation is bool


# ---------------------------------------------------------------------------
# Frozen contract (Knight-B + Knight-A)
# ---------------------------------------------------------------------------


class TestConfigFrozen:
    def test_mutation_enabled_raises(self):
        cfg = SecurityHooksConfig()
        with pytest.raises(ValidationError):
            cfg.enabled = False  # type: ignore[misc]

    def test_mutation_emit_events_raises(self):
        cfg = SecurityHooksConfig()
        with pytest.raises(ValidationError):
            cfg.emit_denial_events = False  # type: ignore[misc]

    def test_mutation_extra_patterns_raises(self):
        cfg = SecurityHooksConfig()
        with pytest.raises(ValidationError):
            cfg.extra_deny_patterns = ["x"]  # type: ignore[misc]

    def test_model_config_frozen_flag(self):
        cfg_meta = SecurityHooksConfig.model_config
        assert cfg_meta.get("frozen") is True


# ---------------------------------------------------------------------------
# Extra deny patterns — additive only (Knight-A)
# ---------------------------------------------------------------------------


class TestExtraDenyPatternsIsAdditive:
    """Extras EXTEND the floor — they cannot remove defaults."""

    def test_extra_does_not_remove_default(self):
        """Supplying extras MUST NOT mutate DEFAULT_DENY_PATTERNS."""
        from bonfire.dispatch.security_patterns import DEFAULT_DENY_PATTERNS

        defaults_snapshot = tuple(r.rule_id for r in DEFAULT_DENY_PATTERNS)

        cfg = SecurityHooksConfig(extra_deny_patterns=["^my-rule$"])
        assert cfg.extra_deny_patterns == ["^my-rule$"]

        still = tuple(r.rule_id for r in DEFAULT_DENY_PATTERNS)
        assert still == defaults_snapshot

    def test_extra_empty_list_accepted(self):
        cfg = SecurityHooksConfig(extra_deny_patterns=[])
        assert cfg.extra_deny_patterns == []

    def test_extra_accepts_multiple_patterns(self):
        cfg = SecurityHooksConfig(
            extra_deny_patterns=[r"rm\s+-rf\s+/specific/path", r"dangerous-tool"],
        )
        assert len(cfg.extra_deny_patterns) == 2


# ---------------------------------------------------------------------------
# Value-level construction (Knight-B)
# ---------------------------------------------------------------------------


class TestConfigConstruction:
    def test_override_enabled(self):
        cfg = SecurityHooksConfig(enabled=False)
        assert cfg.enabled is False
        assert cfg.emit_denial_events is True
        assert cfg.extra_deny_patterns == []

    def test_override_emit_events(self):
        cfg = SecurityHooksConfig(emit_denial_events=False)
        assert cfg.emit_denial_events is False

    def test_override_extra_deny_patterns(self):
        cfg = SecurityHooksConfig(extra_deny_patterns=["rm .*", "my-bad .*"])
        assert cfg.extra_deny_patterns == ["rm .*", "my-bad .*"]


# ---------------------------------------------------------------------------
# Type coercion — adversarial (Knight-A)
# ---------------------------------------------------------------------------


class TestTypeCoercion:
    def test_extra_deny_patterns_rejects_non_list(self):
        with pytest.raises(ValidationError):
            SecurityHooksConfig(extra_deny_patterns="rm -rf")  # type: ignore[arg-type]

    def test_extra_deny_patterns_rejects_dict(self):
        with pytest.raises(ValidationError):
            SecurityHooksConfig(extra_deny_patterns={"rule": "rm"})  # type: ignore[arg-type]

    def test_invalid_type_rejected(self):
        """Pydantic validation — wrong type rejected."""
        with pytest.raises(ValidationError):
            SecurityHooksConfig(enabled="yes")  # type: ignore[arg-type]

    def test_unknown_field_rejected(self):
        """Strict Pydantic — unknown kwargs raise."""
        with pytest.raises(ValidationError):
            SecurityHooksConfig(fail_open_on_hook_error=True)  # type: ignore[call-arg]
