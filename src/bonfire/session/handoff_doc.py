# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Render a session-handoff document from a persisted checkpoint.

A handoff is the artifact a successor reads to pick up where a previous Bonfire
run stopped — a human returning the next morning, or a fresh-boot agent session
that has never seen this work. :func:`render_handoff` turns a
:class:`~bonfire.engine.checkpoint.CheckpointData` into a self-contained
markdown document: what the run was, what it cost, which stages completed, and
(when the plan is a known registered workflow) which stages remain.

The honesty contract: the doc never fabricates remaining stages. If the plan
name does not resolve to a registered workflow, the "remaining" section says so
plainly rather than inventing a stage list.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonfire.engine.checkpoint import CheckpointData


def _remaining_stage_names(plan_name: str, completed: set[str]) -> list[str] | None:
    """Stage names in *plan_name* not yet in *completed*, or ``None`` if the
    plan name is not a registered workflow (so remaining cannot be derived)."""
    # Imported lazily: the workflow registry pulls the full plan-factory set,
    # which the lightweight status/handoff read path should not force-import
    # until a handoff is actually rendered.
    from bonfire.workflow.registry import get_default_registry

    registry = get_default_registry()
    if plan_name not in registry:
        return None
    plan = registry.get(plan_name)()
    return [stage.name for stage in plan.stages if stage.name not in completed]


def render_handoff(checkpoint: CheckpointData) -> str:
    """Return a markdown handoff document for *checkpoint*."""
    completed_names = sorted(checkpoint.completed)
    when = datetime.fromtimestamp(checkpoint.timestamp, tz=UTC).strftime("%Y-%m-%d %H:%M:%SZ")

    lines: list[str] = [
        f"# Session Handoff — {checkpoint.session_id}",
        "",
        f"- **Workflow:** {checkpoint.plan_name}",
        f"- **Task:** {checkpoint.task_description or '(none recorded)'}",
        f"- **Checkpointed:** {when}",
        f"- **Cost so far:** ${checkpoint.total_cost_usd:.2f}",
        f"- **Stages completed:** {len(completed_names)}",
        "",
        "## Completed stages",
        "",
    ]
    if completed_names:
        lines.extend(f"- {name}" for name in completed_names)
    else:
        lines.append("- (none)")

    lines.extend(["", "## Remaining stages", ""])
    remaining = _remaining_stage_names(checkpoint.plan_name, set(completed_names))
    if remaining is None:
        lines.append(
            f"- Workflow '{checkpoint.plan_name}' is not a registered plan; "
            "remaining stages cannot be derived from this checkpoint."
        )
    elif remaining:
        lines.extend(f"- {name}" for name in remaining)
    else:
        lines.append("- (none — the workflow ran to completion)")

    lines.extend(
        [
            "",
            "## How to resume",
            "",
            f"Run `bonfire resume` to re-enter '{checkpoint.plan_name}' from this "
            f"checkpoint (session {checkpoint.session_id}).",
            "",
        ]
    )
    return "\n".join(lines)
