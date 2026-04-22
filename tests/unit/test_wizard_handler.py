"""BON-342 W5.3 RED — WizardHandler canonical synthesis.

Sage-synthesized from Knight A (Conservative Porter) + Knight B
(Generic-Vocabulary Modernizer).

Decisions locked here:

- D2 ADOPT: module-level ``ROLE: AgentRole = AgentRole.REVIEWER``.
- D3 ADOPT_WITH_EXEMPTION: no gamified ``"Wizard"`` string literal in code,
  with one exemption — the ``"Wizard Code Review"`` H1 heading in the
  review-body template (user-facing markdown rendered by GitHub's UI).
- D4 DEFER: META_REVIEW_VERDICT_SOURCE / META_REVIEW_PARSE_FAILURE_REASON /
  WizardReviewCompleted / VerdictParseFailed not in v0.1 — xfail-gated.
- D5 DEFER: DispatchOptions.setting_sources + PipelineConfig.dispatch_timeout_seconds
  not in v0.1 — xfail-gated.
"""

from __future__ import annotations

import asyncio
import inspect
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

# --- v0.1-tolerant imports ---------------------------------------------------

try:
    from bonfire.handlers.wizard import WizardHandler  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    WizardHandler = None  # type: ignore[assignment,misc]

try:
    from bonfire.handlers.wizard import (  # type: ignore[import-not-found]
        _parse_severity,
        _parse_verdict,
    )

    _PARSER_HELPERS_PRESENT = True
except ImportError:  # pragma: no cover
    _parse_severity = None  # type: ignore[assignment]
    _parse_verdict = None  # type: ignore[assignment]
    _PARSER_HELPERS_PRESENT = False

try:
    from bonfire.events.bus import EventBus  # type: ignore[import-not-found]

    _EVENT_BUS_PRESENT = True
except ImportError:  # pragma: no cover
    EventBus = None  # type: ignore[assignment,misc]
    _EVENT_BUS_PRESENT = False

from bonfire.agent.roles import AgentRole
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import (
    META_PR_NUMBER,
    META_REVIEW_SEVERITY,
    META_REVIEW_VERDICT,
    Envelope,
    TaskStatus,
)
from bonfire.models.plan import StageSpec
from bonfire.naming import ROLE_DISPLAY

# D4: v1 extra meta keys — xfail-gated
try:
    from bonfire.models.envelope import (  # type: ignore[import-not-found]
        META_REVIEW_PARSE_FAILURE_REASON,
        META_REVIEW_VERDICT_SOURCE,
    )

    _EXTRA_META_PRESENT = True
except ImportError:  # pragma: no cover
    META_REVIEW_VERDICT_SOURCE = "review_verdict_source"
    META_REVIEW_PARSE_FAILURE_REASON = "review_parse_failure_reason"
    _EXTRA_META_PRESENT = False

# D4: Wizard-specific events — xfail-gated
try:
    from bonfire.models.events import (  # type: ignore[import-not-found]
        VerdictParseFailed,
        WizardReviewCompleted,
    )

    _WIZARD_EVENTS_PRESENT = True
except ImportError:  # pragma: no cover

    class VerdictParseFailed:  # type: ignore[no-redef]
        """Placeholder — real class not yet ported."""

    class WizardReviewCompleted:  # type: ignore[no-redef]
        """Placeholder — real class not yet ported."""

    _WIZARD_EVENTS_PRESENT = False

# D5: PipelineConfig.dispatch_timeout_seconds — xfail-gated
_CONFIG_HAS_TIMEOUT = "dispatch_timeout_seconds" in PipelineConfig.model_fields

# D5: DispatchOptions.setting_sources — xfail-gated
try:
    from bonfire.protocols import DispatchOptions

    _DO_HAS_SETTING_SOURCES = "setting_sources" in DispatchOptions.model_fields
except ImportError:  # pragma: no cover
    _DO_HAS_SETTING_SOURCES = False

try:
    _DO_HAS_MAX_BUDGET_NONE = (
        "max_budget_usd" in DispatchOptions.model_fields  # type: ignore[name-defined]
    )
except NameError:  # pragma: no cover
    _DO_HAS_MAX_BUDGET_NONE = False


pytestmark = pytest.mark.skipif(
    WizardHandler is None,
    reason="v0.1 handler not yet ported: WizardHandler missing",
)


_PARSER_XFAIL = pytest.mark.xfail(
    condition=not _PARSER_HELPERS_PRESENT,
    reason="v0.1 gap: _parse_verdict / _parse_severity not yet ported",
    strict=False,
)

_EXTRA_META_XFAIL = pytest.mark.xfail(
    condition=not _EXTRA_META_PRESENT,
    reason=(
        "v0.1 gap: META_REVIEW_VERDICT_SOURCE / META_REVIEW_PARSE_FAILURE_REASON "
        "not yet ported — deferred to BON-W5.3-meta-ports"
    ),
    strict=False,
)

_WIZARD_EVENTS_XFAIL = pytest.mark.xfail(
    condition=not _WIZARD_EVENTS_PRESENT,
    reason=(
        "v0.1 gap: WizardReviewCompleted / VerdictParseFailed events not yet ported — "
        "deferred to BON-W5.3-meta-ports"
    ),
    strict=False,
)

_TIMEOUT_XFAIL = pytest.mark.xfail(
    condition=not _CONFIG_HAS_TIMEOUT,
    reason=(
        "v0.1 gap: PipelineConfig.dispatch_timeout_seconds not yet present — "
        "deferred to BON-W5.3-protocol-widen"
    ),
    strict=False,
)

_SETTING_SOURCES_XFAIL = pytest.mark.xfail(
    condition=not _DO_HAS_SETTING_SOURCES,
    reason=(
        "v0.1 gap: DispatchOptions.setting_sources not yet present — "
        "deferred to BON-W5.3-protocol-widen"
    ),
    strict=False,
)


# ---------------------------------------------------------------------------
# Fakes / stubs
# ---------------------------------------------------------------------------


@dataclass
class _FakeBackend:
    """Fake AgentBackend that captures the DispatchOptions it was given."""

    canned_result: str
    canned_cost: float = 0.03
    captured_options: object | None = None
    captured_envelope: Envelope | None = None

    async def execute(self, envelope: Envelope, *, options: object) -> Envelope:
        self.captured_options = options
        self.captured_envelope = envelope
        return envelope.with_result(result=self.canned_result, cost_usd=self.canned_cost)

    async def health_check(self) -> bool:
        return True


@dataclass
class _HangingBackend:
    """Backend whose execute() never returns — used for timeout test."""

    hang_forever: asyncio.Event = field(default_factory=asyncio.Event)

    async def execute(self, envelope: Envelope, *, options: object) -> Envelope:
        await self.hang_forever.wait()
        return envelope

    async def health_check(self) -> bool:
        return True


class _MockGH:
    """Minimal GitHub client stub capturing post_review actions."""

    def __init__(self, *, diff: str = "", files: list[dict] | None = None) -> None:
        self.actions: list[dict] = []
        self._diff = diff
        self._files = files or [{"path": "src/example.py", "additions": 1, "deletions": 0}]

    async def get_pr_diff(self, number: int) -> str:
        self.actions.append({"type": "get_pr_diff", "number": number})
        return self._diff

    async def get_pr_files(self, number: int) -> list[dict]:
        self.actions.append({"type": "get_pr_files", "number": number})
        return self._files

    async def post_review(self, number: int, body: str, *, event: str) -> None:
        self.actions.append(
            {"type": "post_review", "pr": number, "body": body, "event": event},
        )


class _RaisingGH(_MockGH):
    """GitHub client whose post_review raises — for write-ordering tests."""

    async def post_review(self, number: int, body: str, *, event: str) -> None:
        raise RuntimeError("gh API down")


class _RecordingBus:
    """EventBus-like fake recording every emitted event."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    async def emit(self, event: Any) -> None:
        self.events.append(event)


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------


def _make_config(
    *,
    model: str = "claude-opus-4-7",
    max_turns: int = 10,
    max_budget_usd: float = 5.0,
    dispatch_timeout_seconds: float | None = None,
) -> PipelineConfig:
    kwargs: dict[str, Any] = {
        "tier": "pro",
        "model": model,
        "max_turns": max_turns,
        "max_budget_usd": max_budget_usd,
    }
    if _CONFIG_HAS_TIMEOUT and dispatch_timeout_seconds is not None:
        kwargs["dispatch_timeout_seconds"] = dispatch_timeout_seconds
    return PipelineConfig(**kwargs)


def _make_stage(
    *,
    name: str = "wizard",
    model_override: str | None = None,
    metadata: dict | None = None,
) -> StageSpec:
    return StageSpec(
        name=name,
        agent_name="wizard",
        role="reviewer",
        model_override=model_override,
        metadata=metadata or {},
    )


def _make_envelope(*, task: str = "Review PR", pr_number: int = 1) -> Envelope:
    return Envelope(task=task, metadata={META_PR_NUMBER: str(pr_number)})


def _make_handler(
    *,
    canned: str = "<verdict>APPROVE</verdict>",
    canned_cost: float = 0.03,
    config: PipelineConfig | None = None,
    event_bus: Any = None,
    gh: _MockGH | None = None,
) -> tuple[Any, _FakeBackend, _MockGH]:
    backend = _FakeBackend(canned_result=canned, canned_cost=canned_cost)
    gh = gh or _MockGH()
    cfg = config or _make_config()
    handler = WizardHandler(
        github_client=gh,
        backend=backend,
        config=cfg,
        event_bus=event_bus,
    )
    return handler, backend, gh


# ---------------------------------------------------------------------------
# GENERIC-VOCABULARY DISCIPLINE (D2, D3)
# ---------------------------------------------------------------------------


class TestGenericVocabularyDiscipline:
    def test_module_exposes_role_constant_bound_to_reviewer(self) -> None:
        """wizard.ROLE is AgentRole.REVIEWER."""
        import bonfire.handlers.wizard as wizard_mod

        assert hasattr(wizard_mod, "ROLE"), (
            "wizard.py must expose a module-level ROLE constant bound to AgentRole.REVIEWER."
        )
        assert wizard_mod.ROLE is AgentRole.REVIEWER
        assert isinstance(wizard_mod.ROLE, AgentRole)

    def test_role_constant_value_is_reviewer_string(self) -> None:
        """StrEnum value equality: ROLE == 'reviewer'."""
        import bonfire.handlers.wizard as wizard_mod

        assert wizard_mod.ROLE == "reviewer"

    def test_handler_class_docstring_cites_generic_role(self) -> None:
        assert WizardHandler.__doc__ is not None
        assert "reviewer" in WizardHandler.__doc__.lower()

    def test_handler_module_docstring_cites_generic_role(self) -> None:
        import bonfire.handlers.wizard as wizard_mod

        assert wizard_mod.__doc__ is not None
        assert "reviewer" in wizard_mod.__doc__.lower()

    def test_role_in_display_map_translates_to_wizard(self) -> None:
        assert ROLE_DISPLAY["reviewer"].gamified == "Wizard"
        assert ROLE_DISPLAY["reviewer"].professional == "Review Agent"

    def test_handler_source_does_not_hardcode_gamified_display(self) -> None:
        """D3 guard: no ``"Wizard"`` literal in code body.

        Exemption: ``"Wizard Code Review"`` — the review-body H1 heading
        constant, a user-visible markdown token rendered by GitHub's UI.
        """
        import bonfire.handlers.wizard as wizard_mod

        src = Path(wizard_mod.__file__).read_text()
        lines = src.splitlines()
        offenders: list[tuple[int, str]] = []
        in_docstring = False
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.endswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            if "Wizard Code Review" in line:
                continue
            if '"Wizard"' in line or "'Wizard'" in line:
                offenders.append((idx, line))
        assert not offenders, (
            f"WizardHandler source must not hardcode the gamified display 'Wizard'. "
            f"Use ROLE_DISPLAY[ROLE].gamified. Offenders: {offenders}"
        )

    def test_role_matches_stage_spec_role_field(self) -> None:
        """stage.role for reviewer stage equals handler module ROLE."""
        import bonfire.handlers.wizard as wizard_mod

        stage = _make_stage()
        assert stage.role == wizard_mod.ROLE


# ---------------------------------------------------------------------------
# CORE CONTRACT — constructor + return shape + verdict metadata
# ---------------------------------------------------------------------------


class TestCoreContract:
    def test_constructor_accepts_core_kwargs(self) -> None:
        """WizardHandler accepts github_client, backend, config, event_bus=None."""
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>")
        assert handler is not None

    @pytest.mark.asyncio
    async def test_handle_returns_envelope_with_verdict(self) -> None:
        """handle() returns Envelope with META_REVIEW_VERDICT."""
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert isinstance(result, Envelope)
        assert META_REVIEW_VERDICT in result.metadata

    @pytest.mark.asyncio
    async def test_approve_verdict_lowercase(self) -> None:
        """APPROVE -> 'approve'."""
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.metadata[META_REVIEW_VERDICT] == "approve"

    @pytest.mark.asyncio
    async def test_request_changes_verdict(self) -> None:
        handler, _, _ = _make_handler(canned="<verdict>REQUEST_CHANGES</verdict>")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.metadata[META_REVIEW_VERDICT] == "request_changes"

    @pytest.mark.asyncio
    async def test_reject_verdict(self) -> None:
        handler, _, _ = _make_handler(canned="<verdict>REJECT</verdict>")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.metadata[META_REVIEW_VERDICT] == "reject"

    @pytest.mark.asyncio
    async def test_posts_review_via_github(self) -> None:
        handler, _, gh = _make_handler(canned="<verdict>APPROVE</verdict>")
        await handler.handle(_make_stage(), _make_envelope(), {})
        assert any(a["type"] == "post_review" for a in gh.actions)

    @pytest.mark.asyncio
    async def test_reads_diff_before_dispatching(self) -> None:
        """handle() reads PR diff and files via github_client."""
        handler, _, gh = _make_handler(canned="<verdict>APPROVE</verdict>")
        await handler.handle(_make_stage(), _make_envelope(), {})

        action_types = [a["type"] for a in gh.actions]
        assert "get_pr_diff" in action_types
        assert "get_pr_files" in action_types

    def test_satisfies_stage_handler_protocol(self) -> None:
        from bonfire.protocols import StageHandler

        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>")
        assert isinstance(handler, StageHandler)


# ---------------------------------------------------------------------------
# DispatchOptions plumbing
# ---------------------------------------------------------------------------


class TestDispatchOptionsPlumbing:
    @pytest.mark.asyncio
    async def test_max_turns_is_5(self) -> None:
        handler, backend, _ = _make_handler()
        await handler.handle(_make_stage(), _make_envelope(), {})
        assert backend.captured_options.max_turns == 5

    @pytest.mark.xfail(
        reason=(
            "v0.1 gap: DispatchOptions.max_budget_usd is non-nullable (float = 0.0) — "
            "deferred to BON-W5.3-protocol-widen"
        ),
        strict=False,
    )
    @pytest.mark.asyncio
    async def test_max_budget_is_none(self) -> None:
        """Reviewer is the final gate — uncapped (max_budget_usd=None)."""
        handler, backend, _ = _make_handler()
        await handler.handle(_make_stage(), _make_envelope(), {})
        assert backend.captured_options.max_budget_usd is None

    @pytest.mark.asyncio
    async def test_thinking_depth_default_thorough(self) -> None:
        handler, backend, _ = _make_handler()
        await handler.handle(_make_stage(), _make_envelope(), {})
        assert backend.captured_options.thinking_depth == "thorough"

    @pytest.mark.asyncio
    async def test_thinking_depth_override_honored(self) -> None:
        """stage.metadata['thinking_depth_override'] wins."""
        handler, backend, _ = _make_handler()
        stage = _make_stage(metadata={"thinking_depth_override": "ultrathink"})
        await handler.handle(stage, _make_envelope(), {})
        assert backend.captured_options.thinking_depth == "ultrathink"

    @pytest.mark.asyncio
    async def test_tools_locked_to_read_only(self) -> None:
        """tools=['Read','Grep','Glob'] — no mutation surface."""
        handler, backend, _ = _make_handler()
        await handler.handle(_make_stage(), _make_envelope(), {})
        assert backend.captured_options.tools == ["Read", "Grep", "Glob"]

    @pytest.mark.asyncio
    async def test_permission_mode_dont_ask(self) -> None:
        handler, backend, _ = _make_handler()
        await handler.handle(_make_stage(), _make_envelope(), {})
        assert backend.captured_options.permission_mode == "dontAsk"

    @_SETTING_SOURCES_XFAIL
    @pytest.mark.asyncio
    async def test_setting_sources_empty(self) -> None:
        """setting_sources=[] disables filesystem settings."""
        handler, backend, _ = _make_handler()
        await handler.handle(_make_stage(), _make_envelope(), {})
        assert backend.captured_options.setting_sources == []

    @pytest.mark.asyncio
    async def test_model_uses_config_when_no_override(self) -> None:
        """model = config.model when stage.model_override is None."""
        handler, backend, _ = _make_handler(config=_make_config(model="claude-opus-4-7"))
        await handler.handle(_make_stage(model_override=None), _make_envelope(), {})
        assert backend.captured_options.model == "claude-opus-4-7"

    @pytest.mark.asyncio
    async def test_model_uses_override_when_set(self) -> None:
        """stage.model_override wins over config.model."""
        handler, backend, _ = _make_handler(config=_make_config(model="claude-opus-4-7"))
        await handler.handle(
            _make_stage(model_override="claude-sonnet-4-6"),
            _make_envelope(),
            {},
        )
        assert backend.captured_options.model == "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Verdict -> GitHub event mapping
# ---------------------------------------------------------------------------


class TestVerdictToGitHubEvent:
    @pytest.mark.asyncio
    async def test_approve_posts_approve_event(self) -> None:
        handler, _, gh = _make_handler(canned="## Review\n\n<verdict>APPROVE</verdict>")
        await handler.handle(_make_stage(), _make_envelope(), {})
        reviews = [a for a in gh.actions if a["type"] == "post_review"]
        assert len(reviews) == 1
        assert reviews[0]["event"] == "APPROVE"

    @pytest.mark.asyncio
    async def test_request_changes_posts_request_changes_event(self) -> None:
        handler, _, gh = _make_handler(canned="## Review\n\n<verdict>REQUEST_CHANGES</verdict>")
        await handler.handle(_make_stage(), _make_envelope(), {})
        reviews = [a for a in gh.actions if a["type"] == "post_review"]
        assert reviews[0]["event"] == "REQUEST_CHANGES"

    @pytest.mark.asyncio
    async def test_reject_maps_to_request_changes_event(self) -> None:
        """GitHub has no REJECT primitive; maps to REQUEST_CHANGES."""
        handler, _, gh = _make_handler(canned="## Review\n\n<verdict>REJECT</verdict>")
        await handler.handle(_make_stage(), _make_envelope(), {})
        reviews = [a for a in gh.actions if a["type"] == "post_review"]
        assert reviews[0]["event"] == "REQUEST_CHANGES"


# ---------------------------------------------------------------------------
# Verdict source metadata (agent vs parser_fallback)
# ---------------------------------------------------------------------------


class TestVerdictSourceMetadata:
    @_EXTRA_META_XFAIL
    @pytest.mark.asyncio
    async def test_verdict_source_agent_on_tag_match(self) -> None:
        """Tag match -> verdict_source='agent'; reason omitted."""
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.metadata[META_REVIEW_VERDICT_SOURCE] == "agent"
        assert META_REVIEW_PARSE_FAILURE_REASON not in result.metadata

    @_EXTRA_META_XFAIL
    @pytest.mark.asyncio
    async def test_verdict_source_parser_fallback_on_no_tag(self) -> None:
        """Polite refusal -> parser_fallback + no_tag_found."""
        handler, _, _ = _make_handler(canned="I cannot approve this change.")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.metadata[META_REVIEW_VERDICT_SOURCE] == "parser_fallback"
        assert result.metadata[META_REVIEW_PARSE_FAILURE_REASON] == "no_tag_found"

    @_EXTRA_META_XFAIL
    @pytest.mark.asyncio
    async def test_verdict_source_parser_fallback_on_empty_response(self) -> None:
        """Empty string -> parser_fallback + empty_response."""
        handler, _, _ = _make_handler(canned="")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.metadata[META_REVIEW_VERDICT_SOURCE] == "parser_fallback"
        assert result.metadata[META_REVIEW_PARSE_FAILURE_REASON] == "empty_response"

    @pytest.mark.asyncio
    async def test_verdict_metadata_always_set(self) -> None:
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.metadata[META_REVIEW_VERDICT] == "approve"
        assert META_REVIEW_SEVERITY in result.metadata


# ---------------------------------------------------------------------------
# Fail-safe review body template
# ---------------------------------------------------------------------------


class TestFailSafeBodyTemplate:
    @pytest.mark.asyncio
    async def test_contains_parser_fallback_banner(self) -> None:
        handler, _, gh = _make_handler(canned="I cannot approve.")
        await handler.handle(_make_stage(), _make_envelope(), {})
        body = gh.actions[-1]["body"]
        assert "parse-failure fallback" in body
        assert "Parser fallback engaged" in body

    @pytest.mark.asyncio
    async def test_preserves_raw_output(self) -> None:
        raw = "I cannot approve this change — see findings."
        handler, _, gh = _make_handler(canned=raw)
        await handler.handle(_make_stage(), _make_envelope(), {})
        body = gh.actions[-1]["body"]
        assert raw in body
        assert "<details>" in body

    @pytest.mark.asyncio
    async def test_has_trailing_verdict_tag(self) -> None:
        """Idempotent re-parse: fail-safe body ends with trailing verdict tag."""
        handler, _, gh = _make_handler(canned="")
        await handler.handle(_make_stage(), _make_envelope(), {})
        body = gh.actions[-1]["body"]
        assert "<verdict>REQUEST_CHANGES</verdict>" in body

    @pytest.mark.asyncio
    async def test_shows_reason_enum(self) -> None:
        handler, _, gh = _make_handler(canned="")
        await handler.handle(_make_stage(), _make_envelope(), {})
        body = gh.actions[-1]["body"]
        assert "empty_response" in body

    @pytest.mark.asyncio
    async def test_shows_model_and_cost(self) -> None:
        handler, _, gh = _make_handler(canned="", config=_make_config(model="claude-opus-4-7"))
        await handler.handle(_make_stage(), _make_envelope(), {})
        body = gh.actions[-1]["body"]
        assert "claude-opus-4-7" in body
        assert "$0." in body

    @pytest.mark.asyncio
    async def test_success_body_is_agent_verbatim(self) -> None:
        """Success: agent output posted verbatim (no re-template)."""
        agent_body = (
            "## Wizard Code Review\n\n### Findings\nAll checks pass.\n\n<verdict>APPROVE</verdict>"
        )
        handler, _, gh = _make_handler(canned=agent_body)
        await handler.handle(_make_stage(), _make_envelope(), {})
        body = gh.actions[-1]["body"]
        assert body == agent_body


# ---------------------------------------------------------------------------
# Multi-tag path
# ---------------------------------------------------------------------------


class TestMultipleTagsPath:
    @_EXTRA_META_XFAIL
    @pytest.mark.asyncio
    async def test_multiple_tags_uses_first_but_flags_reason(self) -> None:
        """First tag wins; reason=multiple_verdicts; source=parser_fallback."""
        handler, _, gh = _make_handler(
            canned="<verdict>APPROVE</verdict> then <verdict>REJECT</verdict>",
        )
        result = await handler.handle(_make_stage(), _make_envelope(), {})

        assert result.metadata[META_REVIEW_VERDICT] == "approve"
        assert result.metadata[META_REVIEW_PARSE_FAILURE_REASON] == "multiple_verdicts"
        assert result.metadata[META_REVIEW_VERDICT_SOURCE] == "parser_fallback"
        reviews = [a for a in gh.actions if a["type"] == "post_review"]
        assert reviews[0]["event"] == "APPROVE"


# ---------------------------------------------------------------------------
# Post-review ordering (metadata written even when GH raises)
# ---------------------------------------------------------------------------


class TestPostReviewOrdering:
    @_EXTRA_META_XFAIL
    @pytest.mark.asyncio
    async def test_verdict_metadata_written_before_post_review_raises(self) -> None:
        """GH failure doesn't swallow verdict metadata."""
        handler, _, _ = _make_handler(
            canned="<verdict>REQUEST_CHANGES</verdict>",
            gh=_RaisingGH(),
        )
        result = await handler.handle(_make_stage(), _make_envelope(), {})

        assert result.status == TaskStatus.FAILED
        assert result.metadata[META_REVIEW_VERDICT] == "request_changes"
        assert result.metadata[META_REVIEW_VERDICT_SOURCE] == "agent"

    @pytest.mark.asyncio
    async def test_post_review_failure_surfaces_error_type(self) -> None:
        handler, _, _ = _make_handler(
            canned="<verdict>APPROVE</verdict>",
            gh=_RaisingGH(),
        )
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "RuntimeError"


# ---------------------------------------------------------------------------
# execute_with_retry routing (Dispatch* events)
# ---------------------------------------------------------------------------


class TestExecuteWithRetryRouting:
    @pytest.mark.skipif(not _EVENT_BUS_PRESENT, reason="EventBus not available")
    @pytest.mark.asyncio
    async def test_dispatch_started_and_completed_emitted(self) -> None:
        """DispatchStarted + DispatchCompleted both emitted on success."""
        from bonfire.models.events import DispatchCompleted, DispatchStarted

        bus = EventBus()
        seen: list[Any] = []

        async def _collect(event: Any) -> None:
            seen.append(event)

        bus.subscribe_all(_collect)

        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>", event_bus=bus)
        await handler.handle(_make_stage(), _make_envelope(), {})

        event_types = [type(e) for e in seen]
        assert DispatchStarted in event_types
        assert DispatchCompleted in event_types


# ---------------------------------------------------------------------------
# WizardReviewCompleted + VerdictParseFailed emission
# ---------------------------------------------------------------------------


class TestReviewCompletedEmission:
    """Reviewer emits domain completion + parse-fail events."""

    @_WIZARD_EVENTS_XFAIL
    @pytest.mark.asyncio
    async def test_review_completed_emitted_on_success(self) -> None:
        bus = _RecordingBus()
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>", event_bus=bus)
        await handler.handle(_make_stage(), _make_envelope(), {})
        completed = [e for e in bus.events if isinstance(e, WizardReviewCompleted)]
        assert len(completed) == 1
        assert completed[0].verdict == "approve"
        assert completed[0].verdict_source == "agent"
        assert completed[0].pr_number == 1

    @_WIZARD_EVENTS_XFAIL
    @pytest.mark.asyncio
    async def test_verdict_parse_failed_emitted_on_fallback(self) -> None:
        """Fallback path fires VerdictParseFailed BEFORE WizardReviewCompleted."""
        bus = _RecordingBus()
        handler, _, _ = _make_handler(
            canned="I cannot approve this change.",
            event_bus=bus,
        )
        await handler.handle(_make_stage(), _make_envelope(), {})

        parse_failed = [
            (i, e) for i, e in enumerate(bus.events) if isinstance(e, VerdictParseFailed)
        ]
        completed = [
            (i, e) for i, e in enumerate(bus.events) if isinstance(e, WizardReviewCompleted)
        ]
        assert len(parse_failed) == 1
        assert len(completed) == 1
        assert parse_failed[0][0] < completed[0][0]

        pf_event = parse_failed[0][1]
        assert pf_event.failure_reason == "no_tag_found"
        assert pf_event.pr_number == 1
        assert "I cannot approve this change" in pf_event.review_text_snippet

    @_WIZARD_EVENTS_XFAIL
    @pytest.mark.asyncio
    async def test_verdict_parse_failed_not_emitted_on_success(self) -> None:
        bus = _RecordingBus()
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>", event_bus=bus)
        await handler.handle(_make_stage(), _make_envelope(), {})
        assert not any(isinstance(e, VerdictParseFailed) for e in bus.events)

    @_WIZARD_EVENTS_XFAIL
    @pytest.mark.asyncio
    async def test_review_completed_fires_even_on_fallback(self) -> None:
        bus = _RecordingBus()
        handler, _, _ = _make_handler(canned="", event_bus=bus)
        await handler.handle(_make_stage(), _make_envelope(), {})

        completed = [e for e in bus.events if isinstance(e, WizardReviewCompleted)]
        assert len(completed) == 1
        assert completed[0].verdict == "request_changes"
        assert completed[0].verdict_source == "parser_fallback"

    @_WIZARD_EVENTS_XFAIL
    @pytest.mark.asyncio
    async def test_verdict_parse_failed_snippet_truncated_to_500(self) -> None:
        long_text = "I cannot approve. " * 200
        bus = _RecordingBus()
        handler, _, _ = _make_handler(canned=long_text, event_bus=bus)
        await handler.handle(_make_stage(), _make_envelope(), {})

        parse_failed = [e for e in bus.events if isinstance(e, VerdictParseFailed)]
        assert parse_failed
        assert len(parse_failed[0].review_text_snippet) <= 500


# ---------------------------------------------------------------------------
# Handler without event_bus is graceful
# ---------------------------------------------------------------------------


class TestHandlerWithoutEventBus:
    @pytest.mark.asyncio
    async def test_no_bus_does_not_raise_on_success(self) -> None:
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>", event_bus=None)
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.status == TaskStatus.COMPLETED

    @_EXTRA_META_XFAIL
    @pytest.mark.asyncio
    async def test_no_bus_does_not_raise_on_fallback(self) -> None:
        handler, _, _ = _make_handler(canned="I cannot approve.", event_bus=None)
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert result.status == TaskStatus.COMPLETED
        assert result.metadata[META_REVIEW_VERDICT] == "request_changes"
        assert result.metadata[META_REVIEW_VERDICT_SOURCE] == "parser_fallback"


# ---------------------------------------------------------------------------
# Timeout propagation
# ---------------------------------------------------------------------------


class TestTimeoutPropagation:
    @_TIMEOUT_XFAIL
    @pytest.mark.asyncio
    async def test_timeout_propagated_from_config(self) -> None:
        """dispatch_timeout_seconds reaches execute_with_retry."""
        hanging = _HangingBackend()
        gh = _MockGH()
        handler = WizardHandler(
            github_client=gh,
            backend=hanging,
            config=_make_config(dispatch_timeout_seconds=1.5),
            event_bus=None,
        )

        try:
            async with asyncio.timeout(5.0):
                result = await handler.handle(_make_stage(), _make_envelope(), {})
        finally:
            hanging.hang_forever.set()

        assert result is not None


# ---------------------------------------------------------------------------
# Gate-contract invariant: polite refusal MUST NOT post APPROVE
# ---------------------------------------------------------------------------


POLITE_REFUSAL_VOCABULARY: list[str] = [
    "I cannot approve this change in its current form.",
    "Unable to approve — the error handling is incomplete.",
    "I can't approve this until the tests are added.",
    "Not going to approve; see findings below.",
    "I will not approve a change that swallows exceptions silently.",
    "This does not meet the bar for approval.",
    "Cannot approve. Too many untested branches.",
    "I approve of the overall direction but reject the impl",
]


class TestGateContractInvariant:
    """Polite refusals MUST NOT leak APPROVE to GitHub."""

    @pytest.mark.parametrize("polite_refusal", POLITE_REFUSAL_VOCABULARY)
    @pytest.mark.asyncio
    async def test_polite_refusal_does_not_post_approve(self, polite_refusal: str) -> None:
        handler, _, gh = _make_handler(canned=polite_refusal)
        result = await handler.handle(_make_stage(), _make_envelope(), {})

        reviews = [a for a in gh.actions if a["type"] == "post_review"]
        if reviews:
            assert reviews[-1]["event"] != "APPROVE", (
                f"GATE BROKEN: polite refusal {polite_refusal!r} posted APPROVE."
            )
        assert result.metadata.get(META_REVIEW_VERDICT) != "approve"


# ---------------------------------------------------------------------------
# Cost accumulation
# ---------------------------------------------------------------------------


class TestCostAccumulation:
    @pytest.mark.asyncio
    async def test_cost_accumulated_on_success(self) -> None:
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>", canned_cost=0.25)
        envelope = _make_envelope()
        initial_cost = envelope.cost_usd
        result = await handler.handle(_make_stage(), envelope, {})
        assert result.cost_usd == pytest.approx(initial_cost + 0.25)


# ---------------------------------------------------------------------------
# No PR number regression
# ---------------------------------------------------------------------------


class TestNoPRNumberRegression:
    @pytest.mark.asyncio
    async def test_missing_pr_number_returns_failed_envelope(self) -> None:
        """No PR in metadata -> FAILED envelope with ValueError error_type."""
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>")
        envelope_no_pr = Envelope(task="review", metadata={})
        result = await handler.handle(_make_stage(), envelope_no_pr, {})

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "ValueError"


# ---------------------------------------------------------------------------
# Identity Seal invariants
# ---------------------------------------------------------------------------


class TestIdentitySealInvariants:
    def test_handle_signature_matches_stage_handler_protocol(self) -> None:
        sig = inspect.signature(WizardHandler.handle)
        params = list(sig.parameters.keys())
        assert params == ["self", "stage", "envelope", "prior_results"]
        assert asyncio.iscoroutinefunction(WizardHandler.handle)

    @pytest.mark.asyncio
    async def test_handle_returns_envelope(self) -> None:
        handler, _, _ = _make_handler(canned="<verdict>APPROVE</verdict>")
        result = await handler.handle(_make_stage(), _make_envelope(), {})
        assert isinstance(result, Envelope)


# ===========================================================================
# VERDICT / SEVERITY PARSER UNIT TESTS
# (pure functions — independent of events or config)
# ===========================================================================


VALID_VERDICTS: list[tuple[str, tuple[str, str | None]]] = [
    ("<verdict>APPROVE</verdict>", ("approve", None)),
    ("<verdict>REQUEST_CHANGES</verdict>", ("request_changes", None)),
    ("<verdict>REJECT</verdict>", ("reject", None)),
    ("<verdict> APPROVE </verdict>", ("approve", None)),
    ("<verdict>\n  APPROVE\n</verdict>", ("approve", None)),
    ("Prefix text <verdict>APPROVE</verdict> trailer text", ("approve", None)),
    (
        "# Review\n\nSummary ...\n\n<verdict>REQUEST_CHANGES</verdict>\n",
        ("request_changes", None),
    ),
    ("<verdict>APPROVE</verdict>\nSome afterword about minor nits", ("approve", None)),
    ("<verdict>approve</verdict>", ("approve", None)),
    ("<verdict>Approve</verdict>", ("approve", None)),
    ("<Verdict>APPROVE</Verdict>", ("approve", None)),
    ("<VERDICT>APPROVE</VERDICT>", ("approve", None)),
    ("<verdict>request_changes</verdict>", ("request_changes", None)),
    ("<verdict>reject</verdict>", ("reject", None)),
]


NO_TAG_FAIL_SAFE: list[str] = [
    "I cannot approve this change in its current form.",
    "Unable to approve - the error handling is incomplete.",
    "I can't approve this until the tests are added.",
    "Not going to approve; see findings below.",
    "I will not approve a change that swallows exceptions silently.",
    "Approval withheld pending review of the concurrency model.",
    "This does not meet the bar for approval.",
    "I reviewed the PR and cannot recommend approval.",
    "The approval threshold is not met.",
    "I'd approve this if the race condition were addressed. It is not.",
    "Cannot approve. Too many untested branches.",
    "No approval from me - the naming drift is intentional per the author.",
    "I approve of the overall direction but reject the impl",
    "This looks mostly fine but I have a few concerns about error paths.",
    "The approach is reasonable. The implementation has rough edges.",
    "I'm on the fence - leaning positive but not fully convinced.",
    "Some good things here, some not. Hard to call.",
    "Overall decent work with caveats on the error-handling side.",
    "< verdict >APPROVE< / verdict >",
    "&lt;verdict&gt;APPROVE&lt;/verdict&gt;",
    "<verdict>APPROVE",
    "</verdict>APPROVE",
    "<verdict >APPROVE</verdict>",
    "Verdict: APPROVE",
]


EMPTY_FAIL_SAFE: list[str] = [""]


UNKNOWN_VALUE_FAIL_SAFE: list[str] = [
    "<verdict>MAYBE</verdict>",
    "<verdict>APPROVED</verdict>",
    "<verdict>\u0410PPROVE</verdict>",  # leading Cyrillic А (U+0410)
    "<verdict></verdict>",
    "<verdict>   </verdict>",
    "<verdict>approve rejected</verdict>",
]


MULTI_VERDICT: list[tuple[str, tuple[str, str]]] = [
    (
        "<verdict>APPROVE</verdict> <verdict>REJECT</verdict>",
        ("approve", "multiple_verdicts"),
    ),
    (
        "<verdict>REQUEST_CHANGES</verdict>\n\nOn reflection <verdict>APPROVE</verdict>",
        ("request_changes", "multiple_verdicts"),
    ),
    (
        "Multiple tags: <verdict>REJECT</verdict> then <verdict>APPROVE</verdict>",
        ("reject", "multiple_verdicts"),
    ),
]


ADVERSARIAL_TAG_WINS: list[tuple[str, tuple[str, str | None]]] = [
    ("```\n<verdict>APPROVE</verdict>\n```", ("approve", None)),
    (
        "The spec said '<verdict>APPROVE</verdict>' but I disagree. See below.",
        ("approve", None),
    ),
]


ADVERSARIAL_NO_MATCH: list[str] = [
    '<verdict confidence="low">APPROVE</verdict>',
    '<verdict data-source="agent">REQUEST_CHANGES</verdict>',
]


_ALL_NO_APPROVE_STRINGS: list[str] = (
    NO_TAG_FAIL_SAFE + EMPTY_FAIL_SAFE + UNKNOWN_VALUE_FAIL_SAFE + ADVERSARIAL_NO_MATCH
)


@_PARSER_XFAIL
def test_parser_module_regex_compiled() -> None:
    """``_VERDICT_TAG_RE`` compiled at module scope with IGNORECASE."""
    import re as _re

    from bonfire.handlers import wizard as wizard_mod

    assert hasattr(wizard_mod, "_VERDICT_TAG_RE")
    assert (
        wizard_mod._VERDICT_TAG_RE.pattern
        == r"<verdict>\s*(APPROVE|REQUEST_CHANGES|REJECT)\s*</verdict>"
    )
    assert wizard_mod._VERDICT_TAG_RE.flags & _re.IGNORECASE


@_PARSER_XFAIL
def test_severity_module_regex_compiled() -> None:
    """``_SEVERITY_TAG_RE`` compiled at module scope with IGNORECASE."""
    import re as _re

    from bonfire.handlers import wizard as wizard_mod

    assert hasattr(wizard_mod, "_SEVERITY_TAG_RE")
    assert (
        wizard_mod._SEVERITY_TAG_RE.pattern
        == r"<severity>\s*(critical|high|medium|low|minor)\s*</severity>"
    )
    assert wizard_mod._SEVERITY_TAG_RE.flags & _re.IGNORECASE


@_PARSER_XFAIL
@pytest.mark.parametrize(("text", "expected"), VALID_VERDICTS)
def test_valid_verdict_matches(text: str, expected: tuple[str, str | None]) -> None:
    """Valid <verdict> tag returns (verdict, None)."""
    assert _parse_verdict(text) == expected


@_PARSER_XFAIL
@pytest.mark.parametrize("text", NO_TAG_FAIL_SAFE)
def test_no_tag_returns_fail_safe(text: str) -> None:
    """Any text without <verdict> tag -> (request_changes, no_tag_found)."""
    assert _parse_verdict(text) == ("request_changes", "no_tag_found")


@_PARSER_XFAIL
@pytest.mark.parametrize("text", EMPTY_FAIL_SAFE)
def test_empty_response_returns_fail_safe(text: str) -> None:
    """Empty string -> (request_changes, empty_response)."""
    assert _parse_verdict(text) == ("request_changes", "empty_response")


@_PARSER_XFAIL
@pytest.mark.parametrize("text", UNKNOWN_VALUE_FAIL_SAFE)
def test_unknown_verdict_value_returns_fail_safe(text: str) -> None:
    """Regex alternation rejects unknown words -> no_tag_found."""
    verdict, reason = _parse_verdict(text)
    assert verdict == "request_changes"
    assert reason == "no_tag_found"


@_PARSER_XFAIL
@pytest.mark.parametrize("text", ADVERSARIAL_NO_MATCH)
def test_adversarial_tag_with_attributes_rejected(text: str) -> None:
    """Tag-with-attributes rejected (regex needs immediate >)."""
    assert _parse_verdict(text) == ("request_changes", "no_tag_found")


@_PARSER_XFAIL
@pytest.mark.parametrize(("text", "expected"), MULTI_VERDICT)
def test_multiple_tags_first_wins_with_reason(text: str, expected: tuple[str, str]) -> None:
    """First tag wins; reason=multiple_verdicts."""
    assert _parse_verdict(text) == expected


@_PARSER_XFAIL
@pytest.mark.parametrize(("text", "expected"), ADVERSARIAL_TAG_WINS)
def test_adversarial_tag_wins_when_bare(text: str, expected: tuple[str, str | None]) -> None:
    """Bare tag in code fence or quote still matches."""
    assert _parse_verdict(text) == expected


@_PARSER_XFAIL
@pytest.mark.parametrize("text", _ALL_NO_APPROVE_STRINGS)
def test_verdict_never_fails_open(text: str) -> None:
    """No fail-open path: parser MUST NOT return 'approve' on any no-approve string."""
    verdict, _ = _parse_verdict(text)
    assert verdict != "approve", f"FAIL-OPEN REGRESSION: parser returned 'approve' on {text!r}."


@_PARSER_XFAIL
def test_severity_tag_parsed() -> None:
    """<severity>critical</severity> returns 'critical'."""
    assert _parse_severity("<severity>critical</severity>") == "critical"


@_PARSER_XFAIL
def test_severity_tag_case_insensitive() -> None:
    assert _parse_severity("<Severity>HIGH</Severity>") == "high"


@_PARSER_XFAIL
def test_severity_falls_back_to_substring() -> None:
    """Legacy substring fallback preserved for rollout compat."""
    assert _parse_severity("This is a critical bug") == "critical"


@_PARSER_XFAIL
def test_severity_default_normal() -> None:
    """No tag, no substring match -> 'normal'."""
    assert _parse_severity("No severity mention here") == "normal"


@_PARSER_XFAIL
def test_severity_tag_beats_conflicting_substring() -> None:
    """<severity>low</severity> with 'CRITICAL' in prose -> 'low'."""
    assert _parse_severity("This is CRITICAL but <severity>low</severity>") == "low"


@_PARSER_XFAIL
def test_severity_parser_never_raises_on_empty() -> None:
    assert _parse_severity("") == "normal"


@_PARSER_XFAIL
def test_parser_returns_tuple_on_success() -> None:
    result = _parse_verdict("<verdict>APPROVE</verdict>")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert result[0] == "approve"
    assert result[1] is None


@_PARSER_XFAIL
def test_parser_returns_tuple_on_failure() -> None:
    result = _parse_verdict("I cannot approve this.")
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert result[0] == "request_changes"
    assert result[1] == "no_tag_found"


@_PARSER_XFAIL
def test_parse_verdict_never_returns_unknown_sentinel() -> None:
    """Legacy 'unknown' sentinel is GONE — only approve/request_changes/reject."""
    for text in _ALL_NO_APPROVE_STRINGS + [s for s, _ in VALID_VERDICTS]:
        verdict, _ = _parse_verdict(text)
        assert verdict != "unknown"
        assert verdict in ("approve", "request_changes", "reject")


@_PARSER_XFAIL
def test_parse_verdict_handles_very_long_input_without_hang() -> None:
    """50KB input with no tag returns in <1s (ReDoS sanity check)."""
    import time as _time

    huge = "This is a long review body with no verdict tag. " * 1000
    start = _time.monotonic()
    verdict, reason = _parse_verdict(huge)
    elapsed = _time.monotonic() - start
    assert elapsed < 1.0
    assert verdict == "request_changes"
    assert reason == "no_tag_found"


@_PARSER_XFAIL
def test_parse_verdict_handles_many_nested_tags_deterministically() -> None:
    """100 concatenated tags -> first-wins + multiple_verdicts."""
    repeated = "<verdict>REJECT</verdict>" * 100
    verdict, reason = _parse_verdict(repeated)
    assert verdict == "reject"
    assert reason == "multiple_verdicts"
