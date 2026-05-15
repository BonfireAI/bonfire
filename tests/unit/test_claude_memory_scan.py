"""RED tests for bonfire.onboard.scanners.claude_memory._scan_settings — BON-914.

Wave-2 leak hardening. Surfaced by the Mirror Path B production-1 run on
2026-05-07 (Security Scout, finding #9).

The claude_memory scanner's module docstring states an explicit privacy
posture ("Report counts and topics, never content" / "Settings: report
structure, not values") — but ``_scan_settings`` partially violates it::

    model = data.get("model")
    ...
    await emit(ScanUpdate(panel=PANEL, label="model", value=str(model)))

    permissions = data.get("permissions")
    ...
    await emit(ScanUpdate(panel=PANEL, label="permissions", value=str(permissions)))

``str(permissions)`` dumps the whole nested dict into a ``value`` field that
is broadcast over WS and persisted into ``bonfire.toml`` (``config_generator``'s
``_build_claude_memory`` writes ``permissions = "{value}"``). Claude Code's
``~/.claude/settings.json`` ``permissions`` block can carry deny-list rules and
``env`` values today, and Anthropic has been adding fields — any future auth
or env material lands in committed config.

These tests pin the intended post-fix behaviour (per AC): ``_scan_settings``
emits *structural metadata* about ``permissions`` / ``model`` (keys present +
types, or counts) — never the literal values. This mirrors the existing
``extensions`` handling, which only emits a count.

RED expectation: the current implementation emits ``str(permissions)`` and
``str(model)`` verbatim, so the planted sensitive substrings appear in the
scan output — the no-leak assertions fail.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

from bonfire.onboard.protocol import ScanUpdate

# ---------------------------------------------------------------------------
# Helpers (mirror the existing claude_memory test harness)
# ---------------------------------------------------------------------------


def _build_claude_dir(home, *, settings: dict | None = None):
    """Create a minimal ~/.claude/ directory structure with optional settings.json."""
    claude_dir = home / ".claude"
    claude_dir.mkdir(parents=True)
    if settings is not None:
        (claude_dir / "settings.json").write_text(json.dumps(settings))
    return claude_dir


def _events(emit: AsyncMock) -> list[ScanUpdate]:
    return [c.args[0] for c in emit.call_args_list]


def _all_event_text(emit: AsyncMock) -> str:
    """Concatenate every label/value/detail field across all emitted events.

    The leak surface is *any* string field on *any* event — config_generator
    persists ``value`` but a future change could persist ``detail`` too, so
    the assertion sweeps the whole event.
    """
    parts: list[str] = []
    for e in _events(emit):
        parts.extend((e.panel, e.label, e.value, e.detail))
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# permissions: nested dict with sensitive deny-list / env content
# ---------------------------------------------------------------------------

# A sensitive-looking value planted inside the permissions block. It must
# never appear in any scan event.
_PERM_SECRET = "sk-ant-deadbeef-PRIVATE-do-not-leak"


async def test_permissions_value_is_not_reported_verbatim(tmp_path) -> None:
    """A sensitive value nested in ``permissions`` must NOT appear in scan output."""
    home = tmp_path / "home"
    _build_claude_dir(
        home,
        settings={
            "permissions": {
                "deny": ["Bash(rm -rf /)", f"Read(/secrets/{_PERM_SECRET})"],
                "env": {"ANTHROPIC_API_KEY": _PERM_SECRET},
            }
        },
    )
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    blob = _all_event_text(emit)
    assert _PERM_SECRET not in blob, (
        "a sensitive value nested in settings.json `permissions` leaked into a "
        f"scan event — it would be persisted into bonfire.toml:\n{blob}"
    )


async def test_permissions_dict_not_dumped_as_string(tmp_path) -> None:
    """The raw ``str(dict)`` repr of ``permissions`` must NOT appear in any event value.

    ``str({"deny": [...]})`` produces a ``{'deny': [...]}`` literal — its
    presence is the signature that the whole nested object was dumped.
    """
    home = tmp_path / "home"
    _build_claude_dir(
        home,
        settings={"permissions": {"deny": ["Bash(curl:*)"], "allow": ["Read"]}},
    )
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    for event in _events(emit):
        if event.label == "permissions":
            # Post-fix: structural metadata (keys present / count / types),
            # not the dict repr. The deny-rule body must not survive.
            assert "Bash(curl:*)" not in event.value, (
                f"permissions event dumped the rule body verbatim: {event.value!r}"
            )
            assert "Bash(curl:*)" not in event.detail, (
                f"permissions event dumped the rule body into detail: {event.detail!r}"
            )


async def test_permissions_event_reports_structure_when_present(tmp_path) -> None:
    """When ``permissions`` is present, the event reports structure (keys/count), not values.

    Mirrors the existing ``extensions`` handling, which emits "{n} enabled".
    The exact structural representation is the implementer's choice; this
    test pins the invariant that the *keys* are surfaced and the *values*
    are not.
    """
    home = tmp_path / "home"
    _build_claude_dir(
        home,
        settings={
            "permissions": {
                "deny": [f"Read(/secrets/{_PERM_SECRET})"],
                "allow": ["Read", "Edit"],
            }
        },
    )
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    perm_events = [e for e in _events(emit) if e.label == "permissions"]
    assert len(perm_events) == 1, "expected exactly one 'permissions' structural-metadata event"
    perm = perm_events[0]
    # Structural signal: the key names ARE allowed (they are schema, not content);
    # but the secret-bearing values are NOT.
    assert _PERM_SECRET not in perm.value
    assert _PERM_SECRET not in perm.detail


# ---------------------------------------------------------------------------
# model: future auth-field risk — the value can be a long opaque identifier
# ---------------------------------------------------------------------------


async def test_model_value_is_not_reported_verbatim(tmp_path) -> None:
    """The ``model`` value must NOT be echoed verbatim into scan output.

    The AC groups ``model`` with ``permissions`` as future auth-field risk —
    a custom model endpoint identifier could itself carry a token-like
    segment. Post-fix, the scanner reports that a model override is *present*
    (structure), not *what it is* (value).
    """
    home = tmp_path / "home"
    sensitive_model = f"custom-endpoint-{_PERM_SECRET}"
    _build_claude_dir(home, settings={"model": sensitive_model})
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    blob = _all_event_text(emit)
    assert _PERM_SECRET not in blob, (
        "the settings.json `model` value leaked verbatim into a scan event — "
        f"it would be persisted into bonfire.toml:\n{blob}"
    )


async def test_model_event_reports_presence_not_value(tmp_path) -> None:
    """When ``model`` is set, the event signals presence/structure — not the literal value."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={"model": "claude-sonnet-4-20250514"})
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    model_events = [e for e in _events(emit) if e.label == "model"]
    assert len(model_events) == 1, "expected exactly one 'model' event"
    model = model_events[0]
    assert "claude-sonnet-4-20250514" not in model.value, (
        f"the model event reported the literal value verbatim: {model.value!r}"
    )
    assert "claude-sonnet-4-20250514" not in model.detail, (
        f"the model event reported the literal value in detail: {model.detail!r}"
    )


# ---------------------------------------------------------------------------
# Regression guard: no settings -> no model/permissions events (unchanged behaviour)
# ---------------------------------------------------------------------------


async def test_absent_settings_keys_emit_no_events(tmp_path) -> None:
    """When ``model`` / ``permissions`` are absent, no such events are emitted (unchanged)."""
    home = tmp_path / "home"
    _build_claude_dir(home, settings={})
    project = tmp_path / "project"
    project.mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.claude_memory import scan

    await scan(project, emit, home_dir=home)

    events = _events(emit)
    assert not any(e.label == "model" for e in events)
    assert not any(e.label == "permissions" for e in events)
