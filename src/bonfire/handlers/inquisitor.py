# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Judge pipeline stage handler -- post-bracket verdict rendering.

The :class:`InquisitorHandler` is the post-pipeline judge that closes the
Caronte bracket: it reads the closed envelope chain plus each upstream
stage's payload, dispatches an agent to render a verdict, parses the
agent's draft, and walks each candidate muscle-write through a
search-then-route Lexicon pipeline.

The module exposes ``ROLE: AgentRole = AgentRole.JUDGE`` for generic-
vocabulary discipline. Display translation (``judge`` -> ``"Inquisitor"``)
happens via :data:`bonfire.naming.ROLE_DISPLAY`; the file name preserves
the gamified register so a maintainer reading the cadre tree as a unit
sees the parallel against ``architect.py`` / ``wizard.py``.

Verdict surface (post-night-3 PR #100):

- The agent emits a fenced ``json-inquisitor-verdict`` block containing
  ``status`` (PASS / CONCERNS / FAIL), ``rationale``, ``findings``, and
  ``candidate_muscle_writes``. A generic ``json`` fence is NOT honored as
  the operative verdict surface (last-fence-wins payload-echo defense).
- Malformed / missing payloads default to ``CONCERNS`` so a parse failure
  never silently passes and never crashes.
- The Verdict is surfaced on the returned envelope's ``result`` field as
  JSON, AND the verdict status is mirrored on
  ``envelope.metadata[META_BRACKET_VERDICT_STATUS]`` /
  ``envelope.metadata[META_BRACKET_EFFECTUATE]`` for the engine's
  bracket-routing read.

Trust-boundary discipline:

- Each upstream payload supplied via ``prior_results`` is wrapped in an
  ``<untrusted_payload from="...">...</untrusted_payload>`` sentinel via
  :func:`_trust_boundary.wrap_untrusted_payload`. Sentinel-tag literals
  inside the body are ZWJ-split so an attacker who plants
  ``</untrusted_payload>`` inside a payload body cannot terminate the
  sentinel mid-block and land subsequent directive text at cadre
  authority (Probe 5 closure).

Frontmatter pedigree (uniform 7-field shape with the Loremaster):

- ``source``, ``source_run``, ``verdict_status``, ``finding_severity``,
  ``promoted_at``, ``trigger_type``, ``source_muscle_keys``.

Reference (private tree): ``forge/core/handlers/inquisitor.py`` +
``forge/agents/inquisitor/prompt.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol

from bonfire.agent.roles import AgentRole
from bonfire.handlers._trust_boundary import wrap_untrusted_payload
from bonfire.models.envelope import (
    META_BRACKET_EFFECTUATE,
    META_BRACKET_VERDICT_STATUS,
    Envelope,
)

if TYPE_CHECKING:
    from bonfire.models.plan import StageSpec

__all__ = [
    "AgentRunner",
    "InquisitorHandler",
    "LexiconClient",
    "ROLE",
]

# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.JUDGE


# ---------------------------------------------------------------------------
# Duck-typed Protocols / type aliases
# ---------------------------------------------------------------------------


class LexiconClient(Protocol):
    """Duck-typed Lexicon (MCP memory) client.

    Mirrors the private tree's
    ``forge/core/handlers/inquisitor.py:LexiconClient`` shape. The
    ``supersede`` Protocol method declares BOTH the legacy
    same-project ``project=`` shorthand AND the explicit cross-project
    ``project_old=``/``project_new=`` pair -- the
    ``bonfire-lexicon`` master ``d72903b``
    ``memory_supersede`` MCP handler accepts either form. Downstream code
    duck-types against this Protocol; the runtime never isinstance-checks.
    """

    def search(self, *, query: str, scope: str, kind: str) -> list[dict]: ...

    def list(
        self,
        *,
        scope: str,
        kind: str | None = None,
        limit: int | None = None,
        since: Any = None,
    ) -> list[dict]: ...

    def read(
        self,
        *,
        key: str,
        project: str,
        kind: str | None = None,
    ) -> dict | None: ...

    def write(
        self,
        *,
        project: str,
        key: str,
        kind: str,
        content: str,
        tags: list[str],
        frontmatter: dict,
    ) -> None: ...

    def supersede(
        self,
        *,
        key_old: str,
        key_new: str,
        kind: str,
        content: str,
        tags: list[str],
        frontmatter: dict,
        project: str | None = None,
        project_old: str | None = None,
        project_new: str | None = None,
    ) -> None: ...


# ``AgentRunner`` is structurally an async callable returning
# ``(response_markdown, cost_usd)``. Declared as a type alias rather than a
# Protocol class so plain ``async def`` test fixtures and ``AsyncMock``
# instances type-check cleanly without isinstance ambiguity.
AgentRunner = Callable[..., Awaitable[tuple[str, float]]]


# ---------------------------------------------------------------------------
# Module-scope helpers
# ---------------------------------------------------------------------------

# Last-fence-wins parser: the operative verdict surface is ONLY the
# namespaced ``json-inquisitor-verdict`` fence so a generic ``json`` block
# echoed from upstream chain content cannot overwrite the agent's real
# verdict (prompt-injection trust boundary).
_VERDICT_FENCE_RE: re.Pattern[str] = re.compile(
    r"```json-inquisitor-verdict\s*\n(.*?)\n```",
    re.DOTALL,
)

_STATUS_PASS = "PASS"
_STATUS_CONCERNS = "CONCERNS"
_STATUS_FAIL = "FAIL"
_VALID_STATUSES = frozenset({_STATUS_PASS, _STATUS_CONCERNS, _STATUS_FAIL})


def _now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _coerce_status(raw: Any) -> str:
    """Coerce the agent's status string to PASS / CONCERNS / FAIL.

    Unknown values fall back to ``CONCERNS`` -- the never-silently-FAIL
    rule means an unparseable status is closer to "I don't know" than to
    "everything's fine" or "everything's broken".
    """
    if isinstance(raw, str):
        s = raw.strip().upper()
        if s in _VALID_STATUSES:
            return s
    return _STATUS_CONCERNS


def _parse_verdict_payload(response: str) -> dict | None:
    """Extract the JSON PAYLOAD object from the agent's response.

    Returns the parsed dict on success, ``None`` on any failure (missing
    fence, malformed JSON, wrong shape). The caller routes failures to a
    default-CONCERNS exit.

    The operative verdict surface is ONLY the namespaced
    ``json-inquisitor-verdict`` fence (last-fence-wins parser). When the
    response legitimately carries multiple labeled fences, only the LAST
    is kept (defensive against buggy agents emitting drafts then finals).
    """
    if not response or not response.strip():
        return None
    last_match = None
    for last_match in _VERDICT_FENCE_RE.finditer(response):
        pass
    if last_match is None:
        return None
    raw = last_match.group(1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(obj, dict):
        return None
    obj.setdefault("status", _STATUS_CONCERNS)
    obj.setdefault("rationale", "")
    obj.setdefault("findings", [])
    obj.setdefault("candidate_muscle_writes", [])
    return obj


def _highest_severity(tags: list[Any]) -> str | None:
    """Return the highest severity present in ``tags`` (CRITICAL > MAJOR > MINOR > INFO)."""
    priority = ["CRITICAL", "MAJOR", "MINOR", "INFO"]
    seen: set[str] = set()
    for tag in tags:
        if isinstance(tag, str):
            up = tag.strip().upper()
            if up in priority:
                seen.add(up)
    for level in priority:
        if level in seen:
            return level
    return None


def _build_frontmatter(
    *,
    run_id: str,
    verdict_status: str,
    finding_severity: str | None,
    promoted_at: str,
) -> dict:
    """Build the uniform 7-field frontmatter shape for an Inquisitor write.

    The Inquisitor does not promote source-muscle clusters, so
    ``source_muscle_keys`` is always an empty list at this site -- the
    field is still present for shape uniformity with the Loremaster's
    writes (night-3 PR #100 architectural close).
    """
    return {
        "source": "inquisitor",
        "source_run": run_id,
        "verdict_status": verdict_status,
        "finding_severity": finding_severity,
        "promoted_at": promoted_at,
        "trigger_type": "manual",
        "source_muscle_keys": [],
    }


def _process_candidate_write(
    *,
    candidate: dict,
    lexicon: LexiconClient,
    project: str,
    run_id: str,
    verdict_status: str,
    promoted_at: str,
) -> None:
    """Search-then-write a single candidate against the Lexicon.

    The Inquisitor axiom mandates a search-before-write pass: existing
    entries with the same key are left alone; a refinement of a known
    entry triggers ``supersede``; a fresh key triggers ``write``. The
    Lexicon's ``search`` is the seed for the routing decision -- when the
    hit list is empty (the strict-fake fixture path the public Knight
    tests drive), the candidate routes to a fresh ``write``.

    Malformed candidates (missing key, wrong type) are silently skipped --
    the verdict's audit-trail is the source of truth; the Lexicon write
    is a side-effect for downstream Architect reads.
    """
    if not isinstance(candidate, dict):
        return
    key = str(candidate.get("key") or "").strip()
    if not key:
        return
    kind = str(candidate.get("kind") or "verb")
    content = str(candidate.get("content") or "")
    tags = list(candidate.get("tags") or [])
    severity = _highest_severity(tags)

    fm = _build_frontmatter(
        run_id=run_id,
        verdict_status=verdict_status,
        finding_severity=severity,
        promoted_at=promoted_at,
    )

    # Search before write -- the Inquisitor axiom's non-negotiable.
    try:
        hits = lexicon.search(query=key, scope=project, kind=kind)
    except Exception:  # noqa: BLE001 -- Lexicon outage routes to silent skip
        return

    # Strict-match contract: an exact key match in the top-5 routes to a
    # skip-existing (no-op); otherwise fall through to ``write``. The
    # public-tree handler does not implement supersede routing on the
    # Inquisitor side -- supersede is the Loremaster's lane. (The private
    # tree's similar-match branch is preserved there.)
    if isinstance(hits, list):
        for hit in hits[:5]:
            if isinstance(hit, dict):
                hit_key = str(hit.get("key") or "").strip()
                if hit_key and hit_key == key:
                    return  # skip-existing

    lexicon.write(
        project=project,
        key=key,
        kind=kind,
        content=content,
        tags=tags,
        frontmatter=fm,
    )


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class InquisitorHandler:
    """Pipeline stage handler for the judge role.

    Reads the closed envelope chain (carried implicitly via
    ``prior_results``), wraps each upstream payload in an
    ``<untrusted_payload>`` sentinel with body neutralization, dispatches
    the agent to render a verdict, parses the verdict, and walks candidate
    muscle writes through the Lexicon's search-then-route pipeline.

    The returned envelope carries the parsed Verdict as JSON in
    ``result`` AND surfaces the verdict status on
    ``metadata[META_BRACKET_VERDICT_STATUS]`` /
    ``metadata[META_BRACKET_EFFECTUATE]`` for the engine's
    bracket-routing read.
    """

    ROLE: AgentRole = AgentRole.JUDGE

    def __init__(
        self,
        *,
        lexicon: LexiconClient,
        agent_runner: AgentRunner,
        project: str,
        run_id: str,
    ) -> None:
        self._lexicon = lexicon
        self._agent_runner = agent_runner
        self._project = project
        self._run_id = run_id

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Render an Inquisitor verdict over the closed pipeline chain.

        Control flow:

        1. Build the agent injection from ``prior_results``, wrapping each
           upstream stage's payload in an ``<untrusted_payload>`` sentinel
           with body neutralization (Probe 5 close-tag defense).
        2. Dispatch the configured agent runner.
        3. Parse the agent's response. Missing / malformed payloads
           default to CONCERNS.
        4. Walk each candidate muscle write through the Lexicon's
           search-then-route pipeline.
        5. Return an envelope carrying the verdict JSON in ``result`` +
           the bracket metadata for the engine's routing read.
        """
        injection = self._build_injection(envelope, prior_results)

        try:
            response, _cost = await self._agent_runner(
                injection=injection,
                stage=stage,
                envelope=envelope,
            )
        except Exception:  # noqa: BLE001 -- never propagate; emit a verdict
            return self._default_concerns(envelope, diagnostic="agent_runner_crashed")

        payload = _parse_verdict_payload(response)
        if payload is None:
            return self._default_concerns(envelope, diagnostic="parse_failure")

        status = _coerce_status(payload.get("status"))
        rationale = str(payload.get("rationale") or "")
        findings = payload.get("findings") or []
        candidate_writes = payload.get("candidate_muscle_writes") or []

        promoted_at = _now_iso()

        # Walk candidate writes; per-candidate failures are isolated --
        # we never let a Lexicon issue propagate as an uncaught exception.
        for candidate in candidate_writes:
            try:
                _process_candidate_write(
                    candidate=candidate if isinstance(candidate, dict) else {},
                    lexicon=self._lexicon,
                    project=self._project,
                    run_id=self._run_id,
                    verdict_status=status,
                    promoted_at=promoted_at,
                )
            except Exception:  # noqa: BLE001 -- isolate per-candidate failure
                continue

        verdict_body = {
            "status": status,
            "rationale": rationale,
            "findings": findings,
            "candidate_muscle_writes": candidate_writes,
            "run_id": self._run_id,
            "project": self._project,
            "completed_at": promoted_at,
        }
        result_text = json.dumps(verdict_body)
        return self._with_bracket_metadata(envelope.with_result(result_text), status)

    # -- helpers ------------------------------------------------------------

    def _build_injection(
        self,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> str:
        """Compose the agent's injection from envelope + sentinel-wrapped chain.

        Each upstream payload in ``prior_results`` is wrapped in a
        per-stage ``<untrusted_payload from="...">...</untrusted_payload>``
        sentinel. The body is run through
        :func:`_trust_boundary.neutralize_sentinel_tags` so a
        ``</untrusted_payload>`` literal planted inside a payload body
        does NOT terminate the sentinel mid-block (Probe 5).
        """
        lines: list[str] = [
            "# Inquisitor judgment input",
            "",
            f"- **run_id:** {self._run_id}",
            f"- **project:** {self._project}",
            f"- **task:** {envelope.task}",
            "",
            "## Envelope chain",
            "",
        ]
        if not prior_results:
            lines.append("(no prior stages)")
        else:
            blocks: list[str] = []
            for from_agent, payload in prior_results.items():
                blocks.append(wrap_untrusted_payload(str(payload), from_agent=str(from_agent)))
            # Also wrap the envelope's own task/context so an attacker's
            # injection into the envelope can't escape either.
            blocks.append(
                wrap_untrusted_payload(
                    envelope.task,
                    from_agent="envelope:task",
                )
            )
            lines.append("\n\n---\n\n".join(blocks))
        return "\n".join(lines)

    def _default_concerns(self, envelope: Envelope, *, diagnostic: str) -> Envelope:
        """Build the default-CONCERNS envelope for any failure-mode exit."""
        verdict_body = {
            "status": _STATUS_CONCERNS,
            "rationale": (
                "Inquisitor could not render a substantive verdict; "
                "defaulting to CONCERNS so the operator triages."
            ),
            "findings": [],
            "candidate_muscle_writes": [],
            "run_id": self._run_id,
            "project": self._project,
            "default_concerns": True,
            "diagnostic": diagnostic,
            "completed_at": _now_iso(),
        }
        return self._with_bracket_metadata(
            envelope.with_result(json.dumps(verdict_body)),
            _STATUS_CONCERNS,
        )

    @staticmethod
    def _with_bracket_metadata(envelope: Envelope, status: str) -> Envelope:
        """Stamp the bracket-routing metadata on ``envelope``.

        ``META_BRACKET_VERDICT_STATUS`` carries the raw PASS/CONCERNS/FAIL
        label; ``META_BRACKET_EFFECTUATE`` is ``True`` iff the verdict is
        PASS (the engine reads this to gate the Steward).
        """
        return envelope.with_metadata(
            **{
                META_BRACKET_VERDICT_STATUS: status,
                META_BRACKET_EFFECTUATE: status == _STATUS_PASS,
                "verdict_status": status,
            }
        )
