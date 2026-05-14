# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Promoter pipeline stage handler -- muscle->tech promotion.

The :class:`LoremasterHandler` is the muscle->tech promoter: it scans the
Lexicon for project-scoped muscle entries, dispatches an agent to cluster
them by essential pattern, and promotes clusters that span N>=3 distinct
projects into ``scope="global"`` tech (concept) entries.

The module exposes ``ROLE: AgentRole = AgentRole.PROMOTER`` for generic-
vocabulary discipline. Display translation (``promoter`` ->
``"Loremaster"``) happens via :data:`bonfire.naming.ROLE_DISPLAY`; the
file name preserves the gamified register so a maintainer reading the
cadre tree as a unit sees the parallel against ``architect.py`` /
``wizard.py``.

Promotion shape:

- The agent emits a fenced ``json-loremaster-output`` block containing a
  ``clusters`` list. Each cluster carries ``key``, ``kind``, ``content``,
  ``tags``, ``essence_articulable``, and ``source_muscle_keys`` (list of
  ``{project, key}`` dicts).
- Below the N>=3 project-distinct floor, the cluster is anecdote -- not
  promoted.
- At or above floor: the handler issues an atomic batch composed of one
  ``write`` (the new global tech entry) plus one ``supersede`` per
  source-muscle key. Each supersede uses the explicit cross-project
  ``project_old=<src>`` / ``project_new="global"`` shape -- the legacy
  same-project shorthand is reserved for the Inquisitor's writes.
- A frontmatter pedigree (uniform 7-field shape with the Inquisitor)
  rides on every write/supersede so Mirror calibration can trace
  promotions back to their originating muscle pattern.

Reference (private tree): ``forge/core/handlers/loremaster.py`` +
``forge/agents/loremaster/prompt.md``.
"""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal, Protocol

from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import Envelope

if TYPE_CHECKING:
    from bonfire.models.plan import StageSpec

__all__ = [
    "AgentRunner",
    "LexiconClient",
    "LoremasterHandler",
    "ROLE",
]

# ---------------------------------------------------------------------------
# Module-level role binding (generic-vocabulary discipline)
# ---------------------------------------------------------------------------

ROLE: AgentRole = AgentRole.PROMOTER


# ---------------------------------------------------------------------------
# Duck-typed Protocols / type aliases
# ---------------------------------------------------------------------------


class LexiconClient(Protocol):
    """Duck-typed Lexicon (MCP memory) client.

    Mirrors the private tree's
    ``forge/core/handlers/loremaster.py:LexiconClient`` shape. The
    ``supersede`` Protocol method declares the explicit cross-project
    ``project_old=``/``project_new=`` pair (the Loremaster's promotion
    path is inherently cross-project: source muscle in project X
    superseded by a global concept entry) AND the legacy same-project
    ``project=`` shorthand (preserved for BC + cadre-wide Protocol shape
    parity with the Inquisitor's writes).
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


AgentRunner = Callable[..., Awaitable[tuple[str, float]]]


# ---------------------------------------------------------------------------
# Module-scope helpers
# ---------------------------------------------------------------------------

# The operative cluster-verdict surface is ONLY the namespaced
# ``json-loremaster-output`` fence -- a generic ``json`` block cannot
# overwrite the agent's real cluster verdict.
_OUTPUT_FENCE_RE: re.Pattern[str] = re.compile(
    r"```json-loremaster-output\s*\n(.*?)\n```",
    re.DOTALL,
)

_GLOBAL_SCOPE = "global"
_N_FLOOR = 3


def _now_iso() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _parse_clusters(response: str) -> list[dict]:
    """Extract the JSON PAYLOAD's ``clusters`` list from the agent response.

    Returns ``[]`` on any failure (missing fence, malformed JSON, wrong
    shape). An empty cluster list is a valid no-promotion outcome.
    """
    if not response or not response.strip():
        return []
    last_match = None
    for last_match in _OUTPUT_FENCE_RE.finditer(response):
        pass
    if last_match is None:
        return []
    raw = last_match.group(1).strip()
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(obj, dict):
        return []
    clusters = obj.get("clusters")
    if not isinstance(clusters, list):
        return []
    return [c for c in clusters if isinstance(c, dict)]


def _distinct_projects(cluster: dict) -> set[str]:
    """Return the set of distinct ``project`` values across source muscle keys."""
    sources = cluster.get("source_muscle_keys") or []
    projects: set[str] = set()
    for src in sources:
        if isinstance(src, dict):
            project = str(src.get("project") or "").strip()
            if project:
                projects.add(project)
    return projects


def _build_frontmatter(
    *,
    cluster: dict,
    trigger_type: Literal["cron", "threshold", "manual"],
    promoted_at: str,
) -> dict:
    """Build the uniform 7-field frontmatter for a promoted tech write.

    The shape mirrors the Inquisitor's ``_build_frontmatter`` exactly so
    Mirror calibration reads one taxonomy across muscle + tech writes
    (night-3 PR #100 architectural close).

    The cluster MAY surface ``source_run``, ``verdict_status``, and
    ``finding_severity`` hints (threaded from the upstream Inquisitor
    verdict that seeded the source muscle cluster). When absent the
    field is set to ``None`` -- the key is still load-bearing for the
    Mirror-calibration consumer.
    """
    sources = cluster.get("source_muscle_keys") or []
    source_muscle_keys = [
        {
            "project": str(s.get("project") or "").strip(),
            "key": str(s.get("key") or "").strip(),
        }
        for s in sources
        if isinstance(s, dict)
    ]
    return {
        "source": "loremaster",
        "source_run": cluster.get("source_run"),
        "verdict_status": cluster.get("verdict_status"),
        "finding_severity": cluster.get("finding_severity"),
        "promoted_at": promoted_at,
        "trigger_type": trigger_type,
        "source_muscle_keys": source_muscle_keys,
    }


# ---------------------------------------------------------------------------
# Handler
# ---------------------------------------------------------------------------


class LoremasterHandler:
    """Pipeline stage handler for the promoter role.

    Dispatches an agent to cluster recent muscle entries, walks each
    cluster through the promotion gates (N>=3 distinct projects +
    essence-articulability + no-existing-tech check), and promotes
    survivors by issuing one ``write`` for the new tech entry plus one
    ``supersede`` per source-muscle key.

    Cross-project supersede form: ``project_old=<src>`` /
    ``project_new="global"``. The legacy same-project ``project=``
    shorthand is reserved for the Inquisitor's muscle writes.
    """

    ROLE: AgentRole = AgentRole.PROMOTER

    def __init__(
        self,
        *,
        lexicon: LexiconClient,
        agent_runner: AgentRunner,
        project: str,
    ) -> None:
        self._lexicon = lexicon
        self._agent_runner = agent_runner
        self._project = project

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope:
        """Run a single Loremaster pass.

        Control flow:

        1. Dispatch the agent runner. Crashes route to a no-promotion
           envelope.
        2. Parse the agent's cluster verdict.
        3. Walk each cluster through the promotion gates. Survivors
           trigger one ``write`` for the new global tech entry + one
           ``supersede`` per source-muscle key (explicit cross-project
           form).
        4. Return an envelope carrying the report JSON in ``result``.
        """
        injection = self._build_injection(envelope)

        try:
            response, _cost = await self._agent_runner(
                injection=injection,
                stage=stage,
                envelope=envelope,
            )
        except Exception:  # noqa: BLE001 -- never propagate; emit a report
            return self._no_promotion_envelope(envelope, diagnostic="agent_runner_crashed")

        clusters = _parse_clusters(response)
        promoted_at = _now_iso()
        promoted = 0
        skipped = 0

        for cluster in clusters:
            if self._promote_cluster(cluster, promoted_at=promoted_at):
                promoted += 1
            else:
                skipped += 1

        report = {
            "promoted": promoted,
            "skipped": skipped,
            "clusters_found": len(clusters),
            "project": self._project,
            "completed_at": promoted_at,
            "default_no_promotion": False,
        }
        return envelope.with_result(json.dumps(report))

    # -- helpers ------------------------------------------------------------

    def _build_injection(self, envelope: Envelope) -> str:
        """Compose the agent's injection.

        The Loremaster's input shape is intentionally minimal at the
        handler boundary: the agent uses its Lexicon tools to survey the
        muscle/tech state. The handler frames the request and pins the
        focus project for the pass.
        """
        return (
            "# Loremaster pass input\n\n"
            f"- **focus_project:** {self._project}\n"
            f"- **task:** {envelope.task}\n"
        )

    def _promote_cluster(self, cluster: dict, *, promoted_at: str) -> bool:
        """Walk one cluster through the promotion gates.

        Returns ``True`` iff the cluster was promoted (i.e. issued a
        write + N supersedes). Below-floor / essence-unarticulable /
        existing-tech clusters return ``False`` without touching the
        Lexicon.

        The supersede form is ALWAYS the explicit cross-project pair --
        ``project_old=<src>`` / ``project_new="global"``. The legacy
        single-``project=`` shorthand is reserved for the Inquisitor's
        same-project muscle writes.
        """
        # Gate 1 -- N>=3 distinct-project floor.
        projects = _distinct_projects(cluster)
        if len(projects) < _N_FLOOR:
            return False

        # Gate 2 -- essence-articulable check. When the agent surfaces
        # the field as False (or omits it), defer to next pass.
        if not bool(cluster.get("essence_articulable")):
            return False

        key = str(cluster.get("key") or "").strip()
        if not key:
            return False
        kind = str(cluster.get("kind") or "concept")
        content = str(cluster.get("content") or "")
        tags = list(cluster.get("tags") or [])

        # Gate 3 -- existing-tech check. A global concept already
        # covering this theme blocks re-promotion (the Lexicon entry
        # is already correct; muscle writes are confirmation, not
        # new pattern).
        try:
            hits = self._lexicon.search(query=key, scope=_GLOBAL_SCOPE, kind=kind)
        except Exception:  # noqa: BLE001 -- treat outage as no hits
            hits = []
        if hits:
            return False

        frontmatter = _build_frontmatter(
            cluster=cluster,
            trigger_type="manual",
            promoted_at=promoted_at,
        )

        # Promotion -- one write + N supersedes. Each supersede uses
        # the explicit cross-project form.
        self._lexicon.write(
            project=_GLOBAL_SCOPE,
            key=key,
            kind=kind,
            content=content,
            tags=tags,
            frontmatter=frontmatter,
        )

        sources = cluster.get("source_muscle_keys") or []
        for src in sources:
            if not isinstance(src, dict):
                continue
            old_project = str(src.get("project") or "").strip()
            old_key = str(src.get("key") or "").strip()
            if not old_project or not old_key:
                continue
            self._lexicon.supersede(
                key_old=old_key,
                key_new=key,
                kind=kind,
                content=content,
                tags=tags,
                frontmatter=frontmatter,
                project_old=old_project,
                project_new=_GLOBAL_SCOPE,
            )
        return True

    def _no_promotion_envelope(self, envelope: Envelope, *, diagnostic: str) -> Envelope:
        """Build the default-no-promotion envelope for any failure exit."""
        report = {
            "promoted": 0,
            "skipped": 0,
            "clusters_found": 0,
            "project": self._project,
            "default_no_promotion": True,
            "diagnostic": diagnostic,
            "completed_at": _now_iso(),
        }
        return envelope.with_result(json.dumps(report))
