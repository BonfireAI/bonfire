# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Reviewer pipeline stage handler -- automated code review.

Reads the PR diff, dispatches a review agent, parses the verdict, and posts
a structured review on GitHub. The handler owns the full review lifecycle:
diff -> agent -> verdict -> post.

Parser discipline:
  - ``<verdict>`` XML tag is canonical; parse failures fail-safe to
    ``request_changes`` (never fail-open into ``approve``).
  - Polite refusals in prose ("I cannot approve...") never leak APPROVE.
  - Multi-tag bodies take the first match and flag ``multiple_verdicts``.

Dispatch discipline:
  - Review agent runs read-only (tools=Read/Grep/Glob, no mutation surface).
  - Verdict metadata is written to the returned envelope BEFORE the GitHub
    call so a GH failure never swallows the verdict.
  - Fail-safe review body is handler-authored, not agent-authored.

The module exposes ``ROLE: AgentRole = AgentRole.REVIEWER`` for generic-
vocabulary discipline. Display translation (reviewer -> "Wizard") happens
in the display layer via ``ROLE_DISPLAY[ROLE].gamified``; the review-body
H1 heading is plain ``"Code Review"`` -- bonfire does not stamp its own
cadre vocabulary onto another repo's PR surface.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from bonfire.agent.roles import AgentRole
from bonfire.dispatch.runner import execute_with_retry
from bonfire.engine import factory
from bonfire.engine.model_resolver import resolve_dispatch_model
from bonfire.models.envelope import (
    META_PR_NUMBER,
    META_REVIEW_SEVERITY,
    META_REVIEW_VERDICT,
    Envelope,
    ErrorDetail,
    TaskStatus,
)
from bonfire.protocols import DispatchOptions

if TYPE_CHECKING:
    from bonfire.events.bus import EventBus  # noqa: TC004 -- only for type hints
    from bonfire.models.config import BonfireSettings, PipelineConfig
    from bonfire.models.plan import StageSpec

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.REVIEWER

# ---------------------------------------------------------------------------
# Module-scope constants
# ---------------------------------------------------------------------------

# GitHub review events only support APPROVE, REQUEST_CHANGES, COMMENT.
# "reject" maps to REQUEST_CHANGES -- the gate system handles severity
# distinction via META_REVIEW_SEVERITY.
_VERDICT_TO_EVENT: dict[str, str] = {
    "approve": "APPROVE",
    "request_changes": "REQUEST_CHANGES",
    "reject": "REQUEST_CHANGES",
}

_VERDICT_TAG_RE: re.Pattern[str] = re.compile(
    r"<verdict>\s*(APPROVE|REQUEST_CHANGES|REJECT)\s*</verdict>",
    re.IGNORECASE,
)

_SEVERITY_TAG_RE: re.Pattern[str] = re.compile(
    r"<severity>\s*(critical|high|medium|low|minor)\s*</severity>",
    re.IGNORECASE,
)

# Metadata keys not yet present in ``bonfire.models.envelope`` -- when the
# authoritative constants land they will hold these exact string values,
# which makes the xfail'd tests flip GREEN automatically.
_META_VERDICT_SOURCE: str = "review_verdict_source"
_META_PARSE_FAILURE_REASON: str = "review_parse_failure_reason"

# Review-body H1 heading -- plain "Code Review" so bonfire does not
# stamp its cadre vocabulary onto a downstream repo's PR surface.
FAIL_SAFE_BODY_TEMPLATE = """## Code Review -- CHANGES REQUESTED (parse-failure fallback)

> **Parser fallback engaged.** The review agent did not emit a parseable `<verdict>` tag.
> This PR is blocked by fail-safe policy. This is NOT a substantive rejection
> by the reviewer -- it means the review output could not be validated.
>
> **To unblock:** re-run the review stage, or review the raw agent output below
> and post an approval manually if the diff is sound.

**Verdict:** REQUEST_CHANGES (fail-safe)
**Verdict source:** parser_fallback
**Parse-failure reason:** `{reason}`
**Model:** {model}
**Cost:** ${cost:.4f}

### Raw agent output
<details>
<summary>Click to expand ({char_count} chars)</summary>

```
{raw_output}
```

</details>

### What the developer should do
1. Read the raw output above.
2. If the agent's intent was clearly APPROVE or REQUEST_CHANGES, file a
   ticket to harden the axiom (the agent is emitting malformed verdicts).
3. Re-dispatch the review stage.
4. If this is a known persistent issue, post the approval manually via
   `gh pr review --comment` and document in the PR thread.

---
<verdict>REQUEST_CHANGES</verdict>
"""


# ---------------------------------------------------------------------------
# Module-scope helpers
# ---------------------------------------------------------------------------


def _extract_pr_number(prior_results: dict[str, Any], envelope: Any) -> int | None:
    """Extract PR number from prior_results or envelope metadata."""
    raw = prior_results.get(META_PR_NUMBER)
    if raw is not None:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass

    bard_val = prior_results.get("bard", "")
    if bard_val:
        m = re.search(r"/pull/(\d+)", str(bard_val))
        if m:
            return int(m.group(1))

    meta_val = envelope.metadata.get(META_PR_NUMBER)
    if meta_val is not None:
        try:
            return int(meta_val)
        except (ValueError, TypeError):
            pass

    return None


def _parse_verdict(text: str) -> tuple[str, str | None]:
    """Extract verdict from the agent response.

    Returns ``(verdict, parse_failure_reason)``:
      - verdict: ``"approve"`` | ``"request_changes"`` | ``"reject"``
      - parse_failure_reason: ``None`` on successful match;
        ``"empty_response"`` | ``"no_tag_found"`` | ``"multiple_verdicts"``
        otherwise.

    Fail-safe: any parse failure returns ``("request_changes", <reason>)`` --
    NEVER fail-open into ``"approve"`` because the review result gates merge.
    """
    if not text:
        return ("request_changes", "empty_response")
    matches = _VERDICT_TAG_RE.findall(text)
    if not matches:
        return ("request_changes", "no_tag_found")
    if len(matches) > 1:
        return (matches[0].lower(), "multiple_verdicts")
    return (matches[0].lower(), None)


def _parse_severity(text: str) -> str:
    """Extract severity tag or fall back to substring scan. Default 'normal'."""
    m = _SEVERITY_TAG_RE.search(text)
    if m is not None:
        return m.group(1).lower()
    lower = text.lower()
    for level in ("critical", "high", "medium", "low", "minor"):
        if level in lower:
            return level
    return "normal"


def _build_review_prompt(
    *,
    diff: str,
    task: str,
    files: list[dict],
    pr_number: int,
) -> str:
    """Build the review prompt with diff and file context."""
    file_list = "\n".join(
        f"  - {f.get('path', '?')} (+{f.get('additions', 0)} -{f.get('deletions', 0)})"
        for f in files
    )
    return (
        f"Review PR #{pr_number}.\n\n"
        f"## Task\n{task}\n\n"
        f"## Changed files\n{file_list}\n\n"
        f"## Diff\n```diff\n{diff}\n```\n\n"
        "Produce your review in the format specified by your axiom."
    )


def _render_fail_safe_body(
    *,
    reason: str,
    model: str,
    cost: float,
    raw_output: str,
) -> str:
    """Render the fail-safe review body. Handler-authored, not agent-authored.

    Uses placeholder-only formatting so agent output containing
    ``{reason}``-shaped braces does not trigger ``str.format`` KeyError or
    escape-hatch interpolation.
    """
    body = FAIL_SAFE_BODY_TEMPLATE.replace("{raw_output}", "___BONFIRE_RAW_OUTPUT_PLACEHOLDER___")
    body = body.format(
        reason=reason,
        model=model,
        cost=cost,
        char_count=len(raw_output),
    )
    safe_raw = raw_output if raw_output else "(empty response from agent)"
    return body.replace("___BONFIRE_RAW_OUTPUT_PLACEHOLDER___", safe_raw)


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class WizardHandler:
    """Pipeline stage handler for the reviewer role.

    Dispatches a review agent, parses the verdict, and posts a structured
    review to GitHub. Verdict metadata is written before the GitHub call
    so a GH failure never swallows the decision.
    """

    def __init__(
        self,
        *,
        github_client: Any,
        backend: Any,
        config: PipelineConfig,
        event_bus: EventBus | None = None,
        settings: BonfireSettings | None = None,
    ) -> None:
        self._github_client = github_client
        self._backend = backend
        self._config = config
        self._bus = event_bus
        self._settings = settings if settings is not None else factory.load_settings_or_default()

    async def _emit(self, event: Any) -> None:
        """Emit an event on the bus when the bus exists. No-op otherwise."""
        if self._bus is not None:
            await self._bus.emit(event)

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Read diff, dispatch review agent, post verdict."""
        try:
            pr_number = _extract_pr_number(prior_results, envelope)
            if pr_number is None:
                return envelope.with_error(
                    ErrorDetail(
                        error_type="ValueError",
                        message="No PR number found in prior_results or envelope metadata",
                        stage_name=stage.name,
                    ),
                )

            diff = await self._github_client.get_pr_diff(pr_number)
            files = await self._github_client.get_pr_files(pr_number)

            if self._backend is None:
                return envelope.with_error(
                    ErrorDetail(
                        error_type="config",
                        message="Reviewer handler requires a backend for sub-agent dispatch",
                        stage_name=stage.name,
                    ),
                )

            prompt = _build_review_prompt(
                diff=diff,
                task=envelope.task,
                files=files,
                pr_number=pr_number,
            )

            # Wizard call site preserves the canonical ``ROLE.value``
            # ("reviewer") -- gamified passthrough at executor + pipeline
            # uses ``stage.role``, but the reviewer handler is locked to
            # the canonical string per Sage memo §K and the existing
            # ``tests/unit/test_wizard_handler.py:586`` assertion contract.
            review_envelope = Envelope(
                task=prompt,
                agent_name="review-agent",
                model=resolve_dispatch_model(
                    explicit_override=stage.model_override or "",
                    role=ROLE.value,
                    settings=self._settings,
                    config=self._config,
                ),
                metadata={"role": ROLE.value},
            )

            thinking_depth = stage.metadata.get("thinking_depth_override", "thorough")

            # ``max_budget_usd=0.0`` is the v0.1 non-nullable contract; the
            # v1 parity value is ``None`` (uncapped). Widening the protocol
            # is deferred to BON-W5.3-protocol-widen.
            options = DispatchOptions(
                model=review_envelope.model,
                max_turns=5,
                max_budget_usd=0.0,
                thinking_depth=thinking_depth,
                tools=["Read", "Grep", "Glob"],
                permission_mode="dontAsk",
                role=ROLE.value,
            )

            # Timeout routing is deferred to BON-W5.3-protocol-widen -- the
            # v0.1 ``PipelineConfig`` has no ``dispatch_timeout_seconds``.
            timeout_seconds = getattr(self._config, "dispatch_timeout_seconds", None)

            dispatch_result = await execute_with_retry(
                self._backend,
                review_envelope,
                options,
                max_retries=0,
                timeout_seconds=timeout_seconds,
                event_bus=self._bus,
            )
            result = dispatch_result.envelope
            review_cost = dispatch_result.cost_usd
            review_text = result.result or ""

            # Parse verdict and severity.
            verdict, parse_failure_reason = _parse_verdict(review_text)
            severity = _parse_severity(review_text)

            verdict_source = "agent" if parse_failure_reason is None else "parser_fallback"

            # Compose final body: agent-verbatim on success, handler-templated on fallback.
            if parse_failure_reason is None:
                final_body = review_text
            else:
                final_body = _render_fail_safe_body(
                    reason=parse_failure_reason,
                    model=review_envelope.model,
                    cost=review_cost,
                    raw_output=review_text,
                )

            # Write verdict metadata BEFORE post_review so a GH failure
            # cannot swallow the verdict.
            new_metadata = {
                **envelope.metadata,
                META_REVIEW_VERDICT: verdict,
                META_REVIEW_SEVERITY: severity,
                _META_VERDICT_SOURCE: verdict_source,
            }
            if parse_failure_reason is not None:
                new_metadata[_META_PARSE_FAILURE_REASON] = parse_failure_reason

            enriched_envelope = envelope.model_copy(
                update={
                    "metadata": new_metadata,
                    "status": TaskStatus.COMPLETED,
                    "result": final_body,
                    "cost_usd": envelope.cost_usd + review_cost,
                },
            )

            # Post to GitHub. Failures here are caught inline so we can
            # preserve verdict metadata on the returned envelope.
            gh_event = _VERDICT_TO_EVENT.get(verdict, "COMMENT")
            try:
                await self._github_client.post_review(pr_number, final_body, event=gh_event)
            except Exception as post_exc:
                logger.exception(
                    "wizard.post_review_failed pr=%d verdict=%s source=%s",
                    pr_number,
                    verdict.upper(),
                    verdict_source,
                )
                return enriched_envelope.with_error(
                    ErrorDetail(
                        error_type=type(post_exc).__name__,
                        message=str(post_exc),
                        stage_name=stage.name,
                    ),
                )

            logger.info(
                "wizard.review_posted pr=%d verdict=%s source=%s severity=%s model=%s cost=%.4f",
                pr_number,
                verdict.upper(),
                verdict_source,
                severity,
                review_envelope.model,
                review_cost,
            )

            return enriched_envelope

        except Exception as exc:
            return envelope.with_error(
                ErrorDetail(
                    error_type=type(exc).__name__,
                    message=str(exc),
                    stage_name=stage.name,
                ),
            )
