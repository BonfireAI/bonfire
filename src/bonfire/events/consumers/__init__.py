# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Event consumers — decoupled observers for the EventBus."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from bonfire.errors import ConfigError
from bonfire.events.consumers.cost import CostTracker
from bonfire.events.consumers.display import DisplayConsumer
from bonfire.events.consumers.knowledge_ingest import KnowledgeIngestConsumer
from bonfire.events.consumers.logger import SessionLoggerConsumer

if TYPE_CHECKING:
    from collections.abc import Callable

    from bonfire.events.bus import EventBus

logger = logging.getLogger(__name__)

__all__ = [
    "CostTracker",
    "DisplayConsumer",
    "KnowledgeIngestConsumer",
    "SessionLoggerConsumer",
    "wire_consumers",
]


def wire_consumers(
    *,
    bus: EventBus,
    persistence: Any,
    cost_tracker: CostTracker,
    display_callback: Callable[..., Any],
    vault_backend: Any,
    project_name: str,
) -> None:
    """Create and register all public-v0.1 consumers on the bus.

    Keyword-only. Wires:

    - ``SessionLoggerConsumer(persistence)`` — global subscriber.
    - ``DisplayConsumer(display_callback)`` — four typed subscriptions.
    - ``cost_tracker.register(bus)`` — caller owns the tracker so the
      running total is observable after wiring.
    - ``KnowledgeIngestConsumer(backend=vault_backend, project_name=project_name)``.

    ``project_name`` is the project the run was configured with (from
    ``bonfire.toml`` or the scan CLI). It is threaded into the
    KnowledgeIngestConsumer so vault entries are partitioned per project.
    Threading the configured name prevents the multi-project failure where a
    single hardcoded project tag poisons one operator's vault with another
    project's events.

    Raises:
        ConfigError: if ``project_name`` is empty or blank. A vault tagged
            with the wrong (or a missing) project name silently corrupts
            cross-project retrieval, so this is a terminal configuration
            failure surfaced loudly — never a silent fall-back to a default
            (per the Elegance Law). The error carries structured context
            naming the offending parameter.
    """
    if not project_name or not project_name.strip():
        # Validate BEFORE touching the bus so a rejected wiring leaves the
        # bus pristine (no half-wired partial state).
        logger.error(
            "wire_consumers rejected: project_name is empty or blank",
            extra={"project_name": repr(project_name)},
        )
        raise ConfigError(
            "wire_consumers requires a non-empty project_name; vault entries "
            "are partitioned by project and a blank name would poison "
            "cross-project knowledge retrieval",
            context={"project_name": project_name},
        )

    logger_consumer = SessionLoggerConsumer(persistence=persistence)
    logger_consumer.register(bus)

    display_consumer = DisplayConsumer(callback=display_callback)
    display_consumer.register(bus)

    cost_tracker.register(bus)

    knowledge_consumer = KnowledgeIngestConsumer(backend=vault_backend, project_name=project_name)
    knowledge_consumer.register(bus)

    logger.info(
        "wire_consumers: 4 consumers registered for project %r",
        project_name,
        extra={"project_name": project_name},
    )
