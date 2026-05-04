# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Event bus machinery and consumers — Bonfire's nervous system.

This package owns the typed pub/sub spine that decouples pipeline stages
from observers (cost tracking, display, knowledge ingest, session
logging). Stages emit; consumers react.

Public surface:
    * :class:`EventBus` — async fan-out broker, the single point through
      which every pipeline event flows.
    * :class:`BonfireEvent` — base contract every event subclasses
      (re-exported from :mod:`bonfire.models.events`).

For downstream observers and the ``wire_consumers`` helper that
registers them on a bus, see :mod:`bonfire.events.consumers`.
"""

from bonfire.events.bus import EventBus
from bonfire.models.events import BonfireEvent

__all__ = ["BonfireEvent", "EventBus"]
