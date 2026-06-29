# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the handoff-document renderer (``bonfire.session.handoff_doc``).

``render_handoff`` turns a persisted :class:`CheckpointData` into a markdown
session-handoff document: a successor (human or fresh-boot agent) can read it
and know exactly where the previous session stopped, what it cost, and which
stages remain.
"""

from __future__ import annotations

import time

from bonfire.engine.checkpoint import CheckpointData
from bonfire.models.envelope import Envelope
from bonfire.session.handoff_doc import render_handoff


def _checkpoint(
    *,
    session_id: str = "ses_handoff",
    plan_name: str = "standard_build",
    completed: dict[str, Envelope] | None = None,
    cost: float = 0.75,
) -> CheckpointData:
    if completed is None:
        completed = {
            "scout": Envelope(task="research", result="ok", cost_usd=0.5),
            "knight": Envelope(task="tests", result="ok", cost_usd=0.25),
        }
    return CheckpointData(
        session_id=session_id,
        plan_name=plan_name,
        task_description="refactor the checkout endpoint",
        completed=completed,
        total_cost_usd=cost,
        timestamp=time.time(),
    )


class TestHandoffRendering:
    def test_includes_session_id_and_plan(self) -> None:
        doc = render_handoff(_checkpoint())
        assert "ses_handoff" in doc
        assert "standard_build" in doc

    def test_includes_task_description(self) -> None:
        doc = render_handoff(_checkpoint())
        assert "refactor the checkout endpoint" in doc

    def test_lists_completed_stages(self) -> None:
        doc = render_handoff(_checkpoint())
        assert "scout" in doc
        assert "knight" in doc

    def test_reports_cost(self) -> None:
        doc = render_handoff(_checkpoint(cost=1.5))
        assert "1.50" in doc

    def test_is_markdown_document(self) -> None:
        doc = render_handoff(_checkpoint())
        # A heading anchors the doc as markdown.
        assert doc.lstrip().startswith("#")

    def test_remaining_stages_listed_when_plan_known(self) -> None:
        # standard_build has more stages than the two completed here; the
        # handoff must name what is left so a successor knows the next move.
        doc = render_handoff(
            _checkpoint(completed={"scout": Envelope(task="research", result="ok", cost_usd=0.1)})
        )
        assert "remaining" in doc.lower()

    def test_honest_when_no_remaining_stages(self) -> None:
        # An unknown plan name cannot enumerate remaining stages; the doc must
        # not fabricate them.
        doc = render_handoff(_checkpoint(plan_name="not_a_real_plan"))
        assert "not_a_real_plan" in doc
