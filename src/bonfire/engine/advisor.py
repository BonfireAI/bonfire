# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""VaultAdvisor -- pre-dispatch vault query for known failure patterns.

Advisory-only, never blocking. Queries the vault for error patterns matching
the current stage and returns formatted markdown. Fail-open: returns ``""``
on any failure (exception, timeout, non-list payload, empty results).

VaultAdvisor is NOT re-exported from ``bonfire.engine``; it is importable
only from ``bonfire.engine.advisor``.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonfire.models.plan import StageSpec
    from bonfire.protocols import VaultBackend

logger = logging.getLogger(__name__)


class VaultAdvisor:
    """Pre-dispatch vault query -- advisory, never blocking."""

    def __init__(
        self,
        backend: VaultBackend,
        *,
        timeout_seconds: float = 0.2,
        confidence_threshold: float = 0.6,
        max_entries: int = 3,
        decay_sessions: int = 5,
        current_session_id: str = "",
    ) -> None:
        self._backend = backend
        self._timeout_seconds = timeout_seconds
        self._confidence_threshold = confidence_threshold
        self._max_entries = max_entries
        self._decay_sessions = decay_sessions
        self._current_session_id = current_session_id

    async def check(self, stage: StageSpec) -> str:
        """Query vault for known failure patterns.

        Returns formatted markdown or ``""``. Never raises.
        """
        try:
            query_text = f"{stage.name} {stage.agent_name}"
            results = await asyncio.wait_for(
                self._backend.query(
                    query_text,
                    entry_type="error_pattern",
                    limit=self._max_entries * 2,
                ),
                timeout=self._timeout_seconds,
            )
        except Exception:  # noqa: BLE001
            logger.warning("VaultAdvisor.check failed, returning empty (fail-open)")
            return ""

        if not results or not isinstance(results, list):
            return ""

        # Position-based confidence filtering
        total = len(results)
        kept: list[str] = []
        for index, entry in enumerate(results):
            confidence = 1.0 - (index / total)
            if confidence < self._confidence_threshold:
                break
            kept.append(entry.content)
            if len(kept) >= self._max_entries:
                break

        if not kept:
            return ""

        lines = "\n".join(f"- {content}" for content in kept)
        return f"## Known Issues (from vault)\n\n{lines}"
