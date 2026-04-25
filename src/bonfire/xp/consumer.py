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

    async def _handle_pipeline_failed(self, event: PipelineFailed) -> None:
        """Bus handler for pipeline failures — applies XP penalty or respawn.

        PipelineFailed carries failed_stage and error_message but no
        stages_completed count. We synthesize a minimal PipelineCompleted
        to reuse the existing on_pipeline_completed logic with success=False.
        """
        # Synthesize a PipelineCompleted-compatible event for the XP path
        compat = PipelineCompleted(
            session_id=event.session_id,
            sequence=event.sequence,
            total_cost_usd=0.0,
            duration_seconds=0.0,
            stages_completed=0,
        )
        await self.on_pipeline_completed(compat, success=False, stages_failed=1)

    async def on_pipeline_completed(
        self,
        event: PipelineCompleted,
        *,
        success: bool,
        stages_failed: int,
    ) -> None:
        """Process a pipeline completion event.

        Args:
            event: The PipelineCompleted event from the bus.
            success: Whether the pipeline succeeded.
            stages_failed: Number of stages that failed.
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
            reason = f"Pipeline failed with {stages_failed} stage failures"
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
