# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""XP pipeline consumer — connects pipeline events to the XP system."""

from __future__ import annotations

from typing import TYPE_CHECKING

from bonfire.models.events import (
    PipelineCompleted,
    PipelineFailed,
    XPAwarded,
    XPPenalty,
    XPRespawn,
)

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus
    from bonfire.xp.calculator import XPCalculator
    from bonfire.xp.tracker import XPTracker

#: ``PipelineFailed.failed_handler`` sentinel for outer-exception halts,
#: which cannot name a bounce target. Distinct from ``None``, which the
#: schema uses for "no bounce happened".
_OUTER_HALT_SENTINEL = "__outer__"


class XPConsumer:
    """Subscribes to PipelineCompleted and drives the XP system.

    On each pipeline completion:
    1. Calculates XP via the calculator.
    2. Records to the tracker.
    3. Emits XPAwarded, XPPenalty, or XPRespawn on the bus.
    """

    def __init__(
        self,
        *,
        tracker: XPTracker,
        calculator: XPCalculator,
        bus: EventBus,
    ) -> None:
        self._tracker = tracker
        self._calculator = calculator
        self._bus = bus

        # Auto-subscribe to pipeline lifecycle events
        bus.subscribe(PipelineCompleted, self._handle_pipeline_completed)
        bus.subscribe(PipelineFailed, self._handle_pipeline_failed)

    async def _handle_pipeline_completed(self, event: PipelineCompleted) -> None:
        """Bus handler — delegates to on_pipeline_completed.

        PipelineCompleted is a success event by definition (stages_failed=0).
        """
        await self.on_pipeline_completed(event, success=True, stages_failed=0)

    @classmethod
    def _halt_reason(cls, event: PipelineFailed) -> str:
        """Render the halt's REAL cause for the emitted penalty event.

        ``PipelineFailed`` already names what broke (``failed_stage``,
        ``error_message``) and, on bounce-target halts, which handler
        actually died (``failed_handler``). The penalty event used to
        discard all three and announce a counted-up substitute —
        "Pipeline failed with 1 stage failures" — where the 1 was a
        constant, not an observation. A reader was told a number that
        was never measured instead of the cause that was.

        Two halt paths (budget-exceeded, outer-exception) legitimately
        carry no stage name, so this states no stage rather than
        inventing one; ``__outer__`` is a schema sentinel, not a real
        bounce target, and is never rendered as one.
        """
        detail = event.error_message.strip() if event.error_message else ""
        stage = event.failed_stage
        handler = event.failed_handler
        if handler and handler not in (_OUTER_HALT_SENTINEL, stage):
            stage = f"{stage or 'unknown stage'} (bounce target {handler})"
        where = f" at {stage}" if stage else ""
        return f"Pipeline halted{where}: {detail}" if detail else f"Pipeline halted{where}"

    async def _handle_pipeline_failed(self, event: PipelineFailed) -> None:
        """Bus handler for pipeline failures — applies XP penalty or respawn.

        Wave 11 Lane A grew ``PipelineFailed`` to carry
        ``stages_completed`` (M7) and ``duration_seconds`` (M3),
        symmetric with ``PipelineCompleted``. Forwarding both lets the
        XP calculator distinguish a stage-1 failure (no progress) from
        a stage-19 failure (nearly complete) — the penalty / respawn
        logic is sensitive to progress made before the halt.

        We still build a ``PipelineCompleted``-shaped wrapper so the
        existing ``on_pipeline_completed`` logic stays the single path.

        ``stages_failed=1`` is deliberately NOT derived from the event:
        every ``PipelineFailed`` emit site in ``engine/pipeline.py``
        halts on the first failing stage, so exactly one stage failed
        and 1 is the measured truth rather than a placeholder. What WAS
        a placeholder is the reason, which is why ``halt_reason``
        carries the event's own account of the failure through.
        """
        compat = PipelineCompleted(
            session_id=event.session_id,
            sequence=event.sequence,
            total_cost_usd=event.total_cost_usd,
            duration_seconds=event.duration_seconds,
            stages_completed=event.stages_completed,
        )
        await self.on_pipeline_completed(
            compat,
            success=False,
            stages_failed=1,
            halt_reason=self._halt_reason(event),
        )

    async def on_pipeline_completed(
        self,
        event: PipelineCompleted,
        *,
        success: bool,
        stages_failed: int,
        halt_reason: str | None = None,
    ) -> None:
        """Process a pipeline completion event.

        Args:
            event: The PipelineCompleted event from the bus.
            success: Whether the pipeline succeeded.
            stages_failed: Number of stages that failed.
            halt_reason: The failure's own account of what went wrong,
                used verbatim as the emitted penalty's reason. Callers
                that have a real cause pass it; when it is absent the
                penalty falls back to the stage-failure count, which
                describes how many stages failed but not why.
        """
        # Snapshot XP before recording
        old_xp = self._tracker.total_xp()

        # Calculate XP
        result = self._calculator.calculate(
            success=success,
            stages_completed=event.stages_completed,
            stages_failed=stages_failed,
        )

        # Record to tracker
        self._tracker.record(result.xp_total, success, result.respawn)

        # Determine level-up
        level_changed = self._tracker.level_changed(old_xp)

        # Build reason
        if result.respawn:
            reason = result.respawn_reason or (
                f"Too many stage failures: {stages_failed} stages failed"
            )
            await self._bus.emit(
                XPRespawn(
                    session_id=event.session_id,
                    sequence=event.sequence,
                    checkpoint="",
                    reason=reason,
                ),
            )
        elif not success:
            reason = halt_reason or f"Pipeline failed with {stages_failed} stage failures"
            await self._bus.emit(
                XPPenalty(
                    session_id=event.session_id,
                    sequence=event.sequence,
                    amount=result.xp_penalty,
                    reason=reason,
                ),
            )
        else:
            # Success path
            if level_changed:
                level_num, tier_name = self._tracker.level()
                reason = f"Pipeline completed — leveled up to Level {level_num}: {tier_name}"
            else:
                reason = "Pipeline completed successfully"

            await self._bus.emit(
                XPAwarded(
                    session_id=event.session_id,
                    sequence=event.sequence,
                    amount=result.xp_total,
                    reason=reason,
                ),
            )
