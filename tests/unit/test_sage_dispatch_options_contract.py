# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The Sage correction stage must dispatch with options the backend can read.

``SageCorrectionDispatchOptions`` was a standalone frozen dataclass carrying
five fields. ``ClaudeSDKBackend._do_execute`` reads eight attributes off the
options it is handed, and the wrapper declared only one of them. The first
read -- ``options.thinking_depth`` -- raised ``AttributeError``, which
``execute``'s blanket handler converted into a FAILED envelope, which the
handler's own ``except`` converted into a COMPLETED "escalated" stage. A
programming error surfaced to the operator as a stage that passed.

The seven absent attributes were not cosmetic:

``cwd``
    Empty ``cwd`` makes the backend resolve ``setting_sources=["project"]``,
    which loads the *target* repository's ``CLAUDE.md`` and
    ``.claude/settings.json`` into the agent's prompt. The composition root
    closed exactly that hole for the dispatched stages; the Sage path would
    have reopened it the moment the ``thinking_depth`` crash was patched
    in isolation.
``security_hooks``
    The security hook policy. Absent means no hooks are built.
``max_budget_usd`` / ``max_turns``
    The spend caps.

So the fix is the contract, not the missing field: the wrapper *is* a
``DispatchOptions`` now, and keeps its frozenset tool discipline on top.

The load-bearing test here is
:func:`test_a_real_dispatch_does_not_raise_attribute_error` -- it drives the
*real* backend body, so an attribute the backend starts reading tomorrow
fails this file rather than escalating silently in production.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import bonfire.dispatch.sdk_backend as sdk_backend
from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
from bonfire.events.bus import EventBus
from bonfire.handlers.sage_correction_bounce import SageCorrectionDispatchOptions
from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.protocols import DispatchOptions

# Every attribute ``_do_execute`` reads off its ``options`` argument.
BACKEND_READS = (
    "cwd",
    "max_budget_usd",
    "max_turns",
    "model",
    "permission_mode",
    "security_hooks",
    "thinking_depth",
    "tools",
)


class _FakeResult:
    subtype = "success"
    duration_ms = 1
    is_error = False
    session_id = "s"
    total_cost_usd = 0.0
    result = "corrected"
    errors = None


@pytest.fixture
def fake_transport(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Replace only the network call; the whole backend body still runs."""
    seen: list[Any] = []

    async def _query(*, prompt: str, options: Any) -> Any:
        del prompt
        seen.append(options)
        return
        yield  # pragma: no cover -- makes this an async generator

    monkeypatch.setattr(sdk_backend, "query", _query)
    return seen


class TestTheContract:
    def test_it_is_a_dispatch_options(self) -> None:
        assert issubclass(SageCorrectionDispatchOptions, DispatchOptions)

    @pytest.mark.parametrize("attribute", BACKEND_READS)
    def test_every_attribute_the_backend_reads_is_present(self, attribute: str) -> None:
        assert hasattr(SageCorrectionDispatchOptions(), attribute), (
            f"the backend reads options.{attribute}; the Sage wrapper does not carry it"
        )


class TestSageDiscipline:
    def test_allowed_tools_is_still_a_frozenset(self) -> None:
        options = SageCorrectionDispatchOptions()
        assert isinstance(options.allowed_tools, frozenset)

    def test_the_default_tool_set_is_read_and_edit(self) -> None:
        assert SageCorrectionDispatchOptions().allowed_tools == frozenset({"Read", "Edit"})

    def test_the_backends_tool_list_mirrors_allowed_tools(self) -> None:
        # The backend passes ``options.tools`` to the SDK. A wrapper that kept
        # its tools in ``allowed_tools`` alone would dispatch Sage with none.
        options = SageCorrectionDispatchOptions(allowed_tools=frozenset({"Read", "Edit"}))
        assert sorted(options.tools) == ["Edit", "Read"]

    def test_an_explicit_tool_list_is_not_overwritten(self) -> None:
        options = SageCorrectionDispatchOptions(
            allowed_tools=frozenset({"Read"}), tools=["Read", "Grep"]
        )
        assert options.tools == ["Read", "Grep"]

    def test_it_is_frozen(self) -> None:
        options = SageCorrectionDispatchOptions()
        with pytest.raises((TypeError, ValueError, AttributeError)):
            options.correction_mode = False  # type: ignore[misc]

    def test_correction_mode_defaults_true(self) -> None:
        assert SageCorrectionDispatchOptions().correction_mode is True


class TestAgainstTheRealBackend:
    async def test_a_real_dispatch_does_not_raise_attribute_error(
        self, fake_transport: list[Any]
    ) -> None:
        backend = ClaudeSDKBackend(bus=EventBus())
        result = await backend.execute(
            Envelope(task="correct the marker"),
            options=SageCorrectionDispatchOptions(),
        )

        assert result.status is not TaskStatus.FAILED, (
            f"dispatch failed: "
            f"{result.error.error_type if result.error else None}: "
            f"{result.error.message if result.error else ''}"
        )
        assert fake_transport, "the backend never reached the transport"

    async def test_the_trust_boundary_is_carried_through(
        self, fake_transport: list[Any], tmp_path: Path
    ) -> None:
        """An explicit cwd must survive into the SDK options.

        Empty cwd is what makes the backend trust the target repository's
        own settings files. This asserts on the object handed to the SDK,
        not on the wrapper, because that is where the decision lands.
        """
        backend = ClaudeSDKBackend(bus=EventBus())
        await backend.execute(
            Envelope(task="correct the marker"),
            options=SageCorrectionDispatchOptions(cwd=str(tmp_path)),
        )

        assert fake_transport
        assert fake_transport[0].cwd == str(tmp_path)
        assert fake_transport[0].setting_sources == []


class TestTheHandlerBuildsThemProperly:
    """The options class carrying a field is worth nothing if the one
    construction site in ``src/`` leaves it at its default."""

    async def test_the_handler_passes_its_repo_path_as_cwd(self, tmp_path: Path) -> None:
        from bonfire.handlers.sage_correction_bounce import SageCorrectionBounceHandler
        from bonfire.models.config import PipelineConfig
        from bonfire.models.plan import StageSpec

        seen: list[Any] = []

        class _CapturingBackend:
            async def execute(self, envelope: Envelope, *, options: Any, **_: Any) -> Envelope:
                seen.append(options)
                return envelope.model_copy(update={"status": TaskStatus.COMPLETED})

            async def health_check(self) -> bool:
                return True

        class _Verdict:
            verdict = "sage_under_marked"

        class _Classifier:
            def classify(self, **_kw: Any) -> Any:
                return _Verdict()

        handler = SageCorrectionBounceHandler(
            backend=_CapturingBackend(),
            classifier=_Classifier(),
            config=PipelineConfig(max_turns=7, max_budget_usd=1.5),
            repo_path=tmp_path,
        )
        await handler.handle(
            StageSpec(name="sage", agent_name="sage", role="synthesizer"),
            Envelope(task="t"),
            {"warrior": "1 failed"},
        )

        assert seen, "the handler never dispatched"
        assert seen[0].cwd == str(tmp_path), (
            "an empty cwd makes the backend trust the target repo's own settings files"
        )
        assert seen[0].max_turns == 7
        assert seen[0].max_budget_usd == 1.5
