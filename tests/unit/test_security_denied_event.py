"""RED contract tests — ``SecurityDenied`` event.

Sage-canonical (BON-338). Knight-B basis with Sage ambiguity #3 pattern_id
slugs (``_infra.error``, ``_infra.unwrap-exhausted``) tracked via the
RESERVED_INFRA_PATTERN_IDS fixture.

Locks Sage D10.

- Class name is EXACTLY ``SecurityDenied`` (no ``Event`` suffix — house style).
- Lives in ``bonfire.models.events``.
- ``event_type`` literal is ``"security.denial"``.
- Fields: ``tool_name: str``, ``reason: str``, ``pattern_id: str``,
  ``agent_name: str = ""`` — session_id/sequence inherited from BonfireEvent.
- Registered in ``BonfireEventUnion`` (via ``event_adapter``).
- Registered in ``EVENT_REGISTRY`` at key ``"security.denial"``.
- BEFORE the ticket: 28 events. AFTER: 29.
"""

from __future__ import annotations

from typing import get_type_hints

import pytest
from pydantic import BaseModel, ValidationError

try:
    from bonfire.models import events as _events_mod
    from bonfire.models.events import (
        EVENT_REGISTRY,
        BonfireEvent,
        SecurityDenied,
        event_adapter,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    _events_mod = None  # type: ignore[assignment]
    EVENT_REGISTRY = None  # type: ignore[assignment]
    BonfireEvent = None  # type: ignore[assignment,misc]
    SecurityDenied = None  # type: ignore[assignment,misc]
    event_adapter = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.models.events.SecurityDenied not importable: {_IMPORT_ERROR}")


SESSION = {"session_id": "sess-abc", "sequence": 1}


# ---------------------------------------------------------------------------
# RESERVED infrastructure pattern_ids (ambiguities #2 and #3)
# ---------------------------------------------------------------------------


RESERVED_INFRA_PATTERN_IDS: frozenset[str] = frozenset(
    {
        "_infra.error",  # ambiguity #3 — hook internal exception
        "_infra.unwrap-exhausted",  # ambiguity #2 — past unwrap_max_depth=5
    }
)


# ---------------------------------------------------------------------------
# Class identity
# ---------------------------------------------------------------------------


class TestSecurityDeniedClassIdentity:
    def test_class_name_exact(self):
        """D10: class name is ``SecurityDenied`` — NOT ``SecurityDenialEvent``."""
        assert SecurityDenied.__name__ == "SecurityDenied"

    def test_no_event_suffix_alias(self):
        """D10 house-style: no ``SecurityDenialEvent`` alias should leak."""
        assert not hasattr(_events_mod, "SecurityDenialEvent"), (
            "House style: event classes do not carry an 'Event' suffix."
        )

    def test_inherits_bonfire_event(self):
        assert issubclass(SecurityDenied, BonfireEvent)

    def test_is_basemodel(self):
        assert issubclass(SecurityDenied, BaseModel)


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------


class TestSecurityDeniedFields:
    def test_event_type_literal(self):
        e = SecurityDenied(
            tool_name="Bash",
            reason="r",
            pattern_id="C1.1-rm-rf-non-temp",
            agent_name="a",
            **SESSION,
        )
        assert e.event_type == "security.denial"

    def test_event_type_default(self):
        e = SecurityDenied(
            tool_name="Bash",
            reason="r",
            pattern_id="C1.1-rm-rf-non-temp",
            **SESSION,
        )
        assert e.event_type == "security.denial"

    def test_required_fields_present(self):
        names = set(SecurityDenied.model_fields.keys())
        required = {"event_type", "tool_name", "reason", "pattern_id", "agent_name"}
        assert required.issubset(names)

    def test_no_unexpected_fields(self):
        base_fields = set(BonfireEvent.model_fields.keys())
        added = set(SecurityDenied.model_fields.keys()) - base_fields
        expected_added = {"event_type", "tool_name", "reason", "pattern_id", "agent_name"}
        assert added == expected_added

    def test_tool_name_is_str(self):
        hints = get_type_hints(SecurityDenied)
        assert hints["tool_name"] is str

    def test_reason_is_str(self):
        hints = get_type_hints(SecurityDenied)
        assert hints["reason"] is str

    def test_pattern_id_is_str(self):
        hints = get_type_hints(SecurityDenied)
        assert hints["pattern_id"] is str

    def test_agent_name_is_str(self):
        hints = get_type_hints(SecurityDenied)
        assert hints["agent_name"] is str

    def test_agent_name_defaults_empty(self):
        e = SecurityDenied(
            tool_name="Bash",
            reason="r",
            pattern_id="C1.1-rm-rf-non-temp",
            **SESSION,
        )
        assert e.agent_name == ""

    def test_tool_name_required(self):
        with pytest.raises(ValidationError):
            SecurityDenied(reason="r", pattern_id="C1.1", **SESSION)  # type: ignore[call-arg]

    def test_reason_required(self):
        with pytest.raises(ValidationError):
            SecurityDenied(tool_name="Bash", pattern_id="C1.1", **SESSION)  # type: ignore[call-arg]

    def test_pattern_id_required(self):
        with pytest.raises(ValidationError):
            SecurityDenied(tool_name="Bash", reason="r", **SESSION)  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Infrastructure pattern_ids accept values (ambiguities #2 and #3)
# ---------------------------------------------------------------------------


class TestInfraPatternIds:
    """Ambiguities #2 + #3: ``_infra.*`` pattern_ids are reserved for the
    hook's internal state. The event class itself accepts any string — the
    contract is that the HOOK emits these specific values. This test asserts
    the event model accepts them without validation error."""

    @pytest.mark.parametrize("pid", sorted(RESERVED_INFRA_PATTERN_IDS))
    def test_accepts_infra_pattern_id(self, pid: str):
        e = SecurityDenied(
            tool_name="Bash",
            reason=f"infra: {pid}",
            pattern_id=pid,
            **SESSION,
        )
        assert e.pattern_id == pid


# ---------------------------------------------------------------------------
# Immutability
# ---------------------------------------------------------------------------


class TestSecurityDeniedFrozen:
    def test_mutation_raises(self):
        e = SecurityDenied(
            tool_name="Bash",
            reason="r",
            pattern_id="C1.1-rm-rf-non-temp",
            **SESSION,
        )
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            e.tool_name = "Write"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------


class TestSecurityDeniedCategory:
    def test_category_is_security(self):
        e = SecurityDenied(
            tool_name="Bash",
            reason="r",
            pattern_id="C1.1-rm-rf-non-temp",
            **SESSION,
        )
        assert e.category == "security"


# ---------------------------------------------------------------------------
# EVENT_REGISTRY
# ---------------------------------------------------------------------------


class TestSecurityDeniedRegistry:
    def test_registered_at_security_denial_key(self):
        assert "security.denial" in EVENT_REGISTRY

    def test_registry_value_is_class(self):
        assert EVENT_REGISTRY["security.denial"] is SecurityDenied


# ---------------------------------------------------------------------------
# BonfireEventUnion
# ---------------------------------------------------------------------------


class TestSecurityDeniedUnionMembership:
    def test_round_trip_via_adapter(self):
        raw = {
            "event_id": "abc123def456",
            "timestamp": 0.0,
            "session_id": "s",
            "sequence": 1,
            "event_type": "security.denial",
            "tool_name": "Bash",
            "reason": "r",
            "pattern_id": "C1.1-rm-rf-non-temp",
            "agent_name": "a",
        }
        parsed = event_adapter.validate_python(raw)
        assert parsed.event_type == "security.denial"
        assert isinstance(parsed, SecurityDenied)


# ---------------------------------------------------------------------------
# Count invariant (28 → 29)
# ---------------------------------------------------------------------------


class TestEventCountDelta:
    """BEFORE BON-338: 28 events registered. AFTER: 29."""

    def test_registry_has_29_entries(self):
        assert len(EVENT_REGISTRY) == 29, (
            f"Expected 29 registered events (28 base + SecurityDenied), got {len(EVENT_REGISTRY)}."
        )

    def test_security_denial_is_only_new_entry(self):
        expected_preexisting = {
            "pipeline.started",
            "pipeline.completed",
            "pipeline.failed",
            "pipeline.paused",
            "stage.started",
            "stage.completed",
            "stage.failed",
            "stage.skipped",
            "dispatch.started",
            "dispatch.completed",
            "dispatch.failed",
            "dispatch.retry",
            "quality.passed",
            "quality.failed",
            "quality.bypassed",
            "git.branch_created",
            "git.commit_created",
            "git.pr_created",
            "git.pr_merged",
            "cost.accrued",
            "cost.budget_warning",
            "cost.budget_exceeded",
            "session.started",
            "session.ended",
            "xp.awarded",
            "xp.penalty",
            "xp.respawn",
            "axiom.loaded",
        }
        assert expected_preexisting.issubset(set(EVENT_REGISTRY.keys())), (
            "BON-338 must not remove existing registry entries."
        )
        new_keys = set(EVENT_REGISTRY.keys()) - expected_preexisting
        assert new_keys == {"security.denial"}, (
            f"BON-338 must add only 'security.denial'; added {new_keys}"
        )
