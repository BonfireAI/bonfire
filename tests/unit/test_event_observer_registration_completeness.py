# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight bonus — Wave 11 Lane D: observer-registration completeness canary.

Background
----------
Wave 11 Lane A surfaced ``H7``: ``DisplayConsumer.register()`` did not
subscribe to ``PipelineCompleted`` / ``PipelineFailed`` /
``CostBudgetExceeded``. The defect class is "an event was added to
``bonfire.models.events`` without wiring any consumer for it". A
``subscribe_all`` global like ``SessionLoggerConsumer`` does partial work
here, but any future event added without a consumer review still slips
past every typed observer.

This Knight test is the regression canary: every concrete subclass of
``BonfireEvent`` declared in ``bonfire.models.events`` must have at least
one consumer subscribed in the default wiring (whether typed via
``bus.subscribe(EventType, ...)`` or global via ``bus.subscribe_all(...)``).

If a developer adds ``class MyShinyEvent(BonfireEvent): ...`` and forgets
to add a consumer, this test fails loudly with a concrete diff.

``pyproject.toml`` sets ``asyncio_mode = "auto"`` so async tests are
discovered without the ``@pytest.mark.asyncio`` decorator.
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

from bonfire.events.bus import EventBus
from bonfire.events.consumers import wire_consumers
from bonfire.models import events as events_module
from bonfire.models.events import BonfireEvent


def _concrete_event_classes() -> list[type[BonfireEvent]]:
    """Enumerate every concrete ``BonfireEvent`` subclass in ``events_module``.

    Excludes the base ``BonfireEvent`` class itself. Order is stable
    (insertion order of the module's namespace) so parametrized output
    is deterministic.
    """
    klasses: list[type[BonfireEvent]] = []
    for _name, obj in vars(events_module).items():
        if not inspect.isclass(obj):
            continue
        if obj is BonfireEvent:
            continue
        if not issubclass(obj, BonfireEvent):
            continue
        klasses.append(obj)
    return klasses


class _StubPersistence:
    """Persistence mock for SessionLoggerConsumer wiring."""

    def __init__(self) -> None:
        self.appended: list[Any] = []

    def append_event(self, session_id: str, event: Any) -> None:
        self.appended.append((session_id, event))


class _StubVaultBackend:
    """Minimal Vault stand-in so wire_consumers can construct
    KnowledgeIngestConsumer without exercising lancedb / ollama."""

    async def store(self, entry: Any) -> str:
        return "stub-id"

    async def query(
        self,
        query: str,
        *,
        limit: int = 5,
        entry_type: str | None = None,
    ) -> list[Any]:
        return []


def _make_wired_bus() -> EventBus:
    """Build a bus with the default consumer set wired."""
    from bonfire.events.consumers import CostTracker

    bus = EventBus()
    cost_tracker = CostTracker(budget_usd=10.0, bus=bus)
    wire_consumers(
        bus=bus,
        persistence=_StubPersistence(),
        cost_tracker=cost_tracker,
        display_callback=lambda *_a, **_kw: None,
        vault_backend=_StubVaultBackend(),
    )
    return bus


# ===========================================================================
# Sanity: at least the core event classes exist (sanity check the discovery)
# ===========================================================================


class TestEventDiscovery:
    """Sanity check that the discovery helper finds the known events.

    Catches a "discovery returned nothing" silent pass.
    """

    def test_discovery_finds_pipeline_failed(self) -> None:
        from bonfire.models.events import PipelineFailed

        assert PipelineFailed in _concrete_event_classes()

    def test_discovery_finds_dispatch_started(self) -> None:
        from bonfire.models.events import DispatchStarted

        assert DispatchStarted in _concrete_event_classes()

    def test_discovery_count_is_at_least_twenty(self) -> None:
        """Lower bound so we know we're finding most of the catalog —
        the registry has 29 entries today; future growth is fine, sudden
        collapse to <20 is not."""
        assert len(_concrete_event_classes()) >= 20


# ===========================================================================
# Completeness: every event has at least one consumer (typed OR global)
# ===========================================================================


class TestEveryEventHasAtLeastOneConsumer:
    """For every concrete ``BonfireEvent`` subclass, the default wiring
    must register at least one consumer that would receive an emission of
    that event. Counting both typed subscriptions and ``subscribe_all``
    global subscribers.
    """

    @pytest.mark.parametrize(
        "event_cls",
        _concrete_event_classes(),
        ids=lambda c: c.__name__,
    )
    def test_event_has_consumer(self, event_cls: type[BonfireEvent]) -> None:
        bus = _make_wired_bus()
        typed_count = len(bus._typed.get(event_cls, []))
        global_count = len(bus._global)
        total = typed_count + global_count
        assert total >= 1, (
            f"Event class {event_cls.__name__} has NO consumer in the default "
            f"wiring (typed={typed_count}, global={global_count}). Either add "
            f"a typed subscription in the appropriate consumer's register() "
            f"or accept the global subscribe_all fallback. Without ANY "
            f"consumer, every emission of {event_cls.__name__} is dropped on "
            f"the floor — repeat of the H7 defect class."
        )
