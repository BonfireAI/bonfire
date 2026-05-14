# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight contract for ``bonfire.handlers.loremaster.LoremasterHandler``.

The Loremaster is the muscle->tech promoter — the cross-project
abstraction layer that runs asynchronously (post-pipeline or cron) and
promotes N>=3 muscle entries into a single global concept (tech) entry.

This file defines the public API surface as RED tests; the Warrior
implements against this contract.

API surface defined here:

1. ``LoremasterHandler`` exists at ``bonfire.handlers.loremaster``.
2. Constructor accepts a ``LexiconClient`` Protocol via keyword. The
   Protocol is declared inline in the handler module (mirrors the
   private tree's ``forge/core/handlers/loremaster.py:185`` shape).
3. ``LexiconClient.supersede`` declares ``project_old=``/``project_new=``
   kwargs (in addition to legacy ``project=``) — the cross-project
   form is the Loremaster's promotion path.
4. ``handle(stage, envelope, prior_results)`` is an async method
   matching the ``StageHandler`` Protocol.
5. Cross-project supersede emits ``project_old`` + ``project_new``
   kwargs on the strict fake — NOT legacy ``project=`` — when
   promoting a muscle entry from project X into global tech.
6. The ``_build_frontmatter`` shape carries the post-PR-#100 fields
   (``source_run``, ``verdict_status``, ``finding_severity``) on
   every promotion write so Mirror calibration can trace promotions
   back to their originating muscle pattern.
7. Batch-op shape preserves BON-981 atomicity: muscle writes are
   inlined into a single batch primitive call (a ``memory_write_batch``-
   style atomic disk mutation) NOT delegated to N sequential
   per-entry calls. Falling back to per-entry calls is allowed if the
   strict fake lacks the batch method; the contract is that the
   batch primitive IS the preferred path.
8. The ``ROLE: AgentRole`` module constant binds the handler to the
   canonical generic identifier (per ADR-001 layer 1).

Reference (private tree): ``ishtar/forge/core/handlers/loremaster.py``
+ ``ishtar/forge/agents/loremaster/prompt.md``.
"""

from __future__ import annotations

import inspect
import json
from typing import Any

import pytest

from bonfire.models.envelope import Envelope
from bonfire.models.plan import StageSpec
from tests.unit._strict_fake_lexicon import StrictFakeLexicon

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAgentRunner:
    """Async callable returning ``(response_markdown, cost_usd)``."""

    def __init__(self, response: str, cost_usd: float = 0.01) -> None:
        self.response = response
        self.cost_usd = cost_usd
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> tuple[str, float]:
        self.calls.append(kwargs)
        return self.response, self.cost_usd


def _make_envelope(task: str = "promote muscle to tech") -> Envelope:
    return Envelope(task=task)


def _make_stage(name: str = "loremaster", role: str = "promoter") -> StageSpec:
    return StageSpec(name=name, agent_name="loremaster", role=role, handler_name="loremaster")


def _loremaster_response(
    clusters: list[dict] | None = None,
) -> str:
    """Build a canonical Loremaster agent response.

    Per the private tree's loremaster axiom, the fenced label is
    ``json-loremaster-output``.
    """
    body = {"clusters": clusters or []}
    return "Some preamble prose.\n\n```json-loremaster-output\n" + json.dumps(body) + "\n```\n"


# ===========================================================================
# 1. Module surface — class exists, ROLE constant, Protocol shape
# ===========================================================================


class TestModuleSurface:
    def test_loremaster_handler_importable(self) -> None:
        from bonfire.handlers.loremaster import LoremasterHandler

        assert LoremasterHandler is not None

    def test_role_constant_is_promoter(self) -> None:
        """The module exposes ``ROLE: AgentRole = AgentRole.PROMOTER``.

        ADR-001 layer 1 (generic) name for the Loremaster stage is
        ``promoter``. Display translation (promoter -> "Loremaster")
        happens in the naming/persona module.
        """
        from bonfire.agent.roles import AgentRole
        from bonfire.handlers import loremaster as mod

        assert hasattr(mod, "ROLE"), "module must expose a ROLE constant"
        assert mod.ROLE == AgentRole.PROMOTER

    def test_lexicon_client_protocol_declared(self) -> None:
        from bonfire.handlers import loremaster as mod

        assert hasattr(mod, "LexiconClient"), "LexiconClient Protocol missing"

    def test_lexicon_client_supersede_has_cross_project_kwargs(self) -> None:
        """``LexiconClient.supersede`` declares ``project_old`` AND
        ``project_new`` kwargs.

        The Loremaster's tech-promotion path is the canonical
        cross-project use case (muscle entry in project X superseded
        by a global concept entry). Without these kwargs, the handler
        can only emit same-project supersedes and silently corrupts
        the promotion's audit trail."""
        from bonfire.handlers.loremaster import LexiconClient

        sig = inspect.signature(LexiconClient.supersede)
        params = set(sig.parameters.keys())
        for required in ("project_old", "project_new"):
            assert required in params, (
                f"LexiconClient.supersede must declare `{required}=` kwarg. Got: {sorted(params)!r}"
            )

    def test_lexicon_client_write_has_frontmatter_kwarg(self) -> None:
        from bonfire.handlers.loremaster import LexiconClient

        sig = inspect.signature(LexiconClient.write)
        assert "frontmatter" in set(sig.parameters.keys())


# ===========================================================================
# 2. Constructor surface
# ===========================================================================


class TestConstructor:
    def test_constructor_accepts_lexicon_and_agent_runner(self) -> None:
        from bonfire.handlers.loremaster import LoremasterHandler

        handler = LoremasterHandler(
            lexicon=StrictFakeLexicon(),
            agent_runner=_FakeAgentRunner(_loremaster_response()),
            project="bonfire-public",
        )
        assert handler is not None

    def test_constructor_rejects_unknown_kwarg(self) -> None:
        from bonfire.handlers.loremaster import LoremasterHandler

        with pytest.raises(TypeError):
            LoremasterHandler(
                lexicon=StrictFakeLexicon(),
                agent_runner=_FakeAgentRunner(_loremaster_response()),
                project="bonfire-public",
                bogus_unknown_kwarg="should-raise",  # type: ignore[call-arg]
            )


# ===========================================================================
# 3. handle() signature matches StageHandler Protocol
# ===========================================================================


class TestStageHandlerProtocol:
    def test_handle_is_async(self) -> None:
        from bonfire.handlers.loremaster import LoremasterHandler

        assert inspect.iscoroutinefunction(LoremasterHandler.handle)

    def test_handle_signature_matches_protocol(self) -> None:
        from bonfire.handlers.loremaster import LoremasterHandler

        sig = inspect.signature(LoremasterHandler.handle)
        param_names = list(sig.parameters.keys())
        assert param_names[1:] == ["stage", "envelope", "prior_results"], (
            f"handle() signature drifted from StageHandler Protocol. "
            f"Got params after self: {param_names[1:]!r}"
        )

    async def test_handle_returns_envelope_on_no_clusters(self) -> None:
        """No-promotion run still returns a well-formed Envelope (the
        ``default_no_promotion`` mirror of the Inquisitor's
        ``never-silently-FAIL`` discipline)."""
        from bonfire.handlers.loremaster import LoremasterHandler

        handler = LoremasterHandler(
            lexicon=StrictFakeLexicon(),
            agent_runner=_FakeAgentRunner(_loremaster_response(clusters=[])),
            project="bonfire-public",
        )
        env = await handler.handle(_make_stage(), _make_envelope(), {})
        assert isinstance(env, Envelope)


# ===========================================================================
# 4. Cross-project supersede — project_old / project_new emitted
# ===========================================================================


class TestCrossProjectSupersede:
    async def test_supersede_emits_cross_project_kwargs(self) -> None:
        """When the Loremaster promotes a muscle entry in project X
        into a global concept entry, the supersede call MUST carry
        ``project_old=<src>`` + ``project_new="global"`` — NOT
        legacy ``project=``.

        The Loremaster's promotion path is inherently cross-project:
        each source muscle was scoped to its originating project; the
        promoted tech entry lives in ``scope="global"``. Using legacy
        ``project=`` collapses the predecessor's audit-trail
        provenance (you cannot tell which project owned the source
        muscle from the supersede receipt alone).

        Recipe: cluster carries 3 source muscle entries spanning
        projects ``alpha``, ``beta``, ``gamma``. The handler MUST
        emit three supersede calls, each with ``project_old=<src>``
        and ``project_new="global"`` (the canonical promotion
        destination).
        """
        from bonfire.handlers.loremaster import LoremasterHandler

        # The agent surfaces a promotable cluster.
        cluster = {
            "key": "shared-pattern-001",
            "kind": "concept",
            "content": "Three projects independently invented X.",
            "tags": ["cross-project-pattern"],
            "essence_articulable": True,
            "search_query": "pattern X discovery",
            "source_muscle_keys": [
                {"project": "alpha", "key": "alpha-pattern-X"},
                {"project": "beta", "key": "beta-pattern-X"},
                {"project": "gamma", "key": "gamma-pattern-X"},
            ],
        }

        lexicon = StrictFakeLexicon(
            # First search call: existing-tech check returns empty
            # (no prior global concept entry shadows this promotion).
            search_returns=[[]]
        )
        handler = LoremasterHandler(
            lexicon=lexicon,
            agent_runner=_FakeAgentRunner(_loremaster_response(clusters=[cluster])),
            project="bonfire-public",
        )
        await handler.handle(_make_stage(), _make_envelope(), {})

        # Either via direct supersede calls OR via batch-op shape, the
        # cross-project form must appear for each source muscle.
        cross_project_supersedes = [
            call
            for call in lexicon.supersede_calls
            if call.get("project_old") != call.get("project_new")
        ]
        assert len(cross_project_supersedes) >= 3, (
            f"Expected at least 3 cross-project supersedes (one per "
            f"source muscle). Got {len(cross_project_supersedes)} "
            f"cross-project, {len(lexicon.supersede_calls)} total."
        )
        for call in cross_project_supersedes:
            assert call["project_new"] == "global", (
                f"Cross-project supersede must target ``global`` scope. "
                f"Got project_new={call['project_new']!r}."
            )

    async def test_supersede_does_not_use_legacy_project_kwarg_for_promotion(
        self,
    ) -> None:
        """Promotion supersedes use the explicit cross-project form;
        the legacy single-``project=`` shorthand is reserved for
        same-project semantics (the Inquisitor's muscle writes).

        The strict fake will NOT raise on legacy shorthand — it's a
        valid wire shape per the post-d72903b XOR contract — but the
        Loremaster handler MUST emit the explicit cross-project form
        for promotion writes so the audit trail preserves originating
        project provenance.
        """
        from bonfire.handlers.loremaster import LoremasterHandler

        cluster = {
            "key": "shared-pattern-002",
            "kind": "concept",
            "content": "Pattern observed across projects.",
            "tags": [],
            "essence_articulable": True,
            "source_muscle_keys": [
                {"project": "alpha", "key": "alpha-key"},
                {"project": "beta", "key": "beta-key"},
                {"project": "gamma", "key": "gamma-key"},
            ],
        }
        lexicon = StrictFakeLexicon(search_returns=[[]])
        handler = LoremasterHandler(
            lexicon=lexicon,
            agent_runner=_FakeAgentRunner(_loremaster_response(clusters=[cluster])),
            project="bonfire-public",
        )
        await handler.handle(_make_stage(), _make_envelope(), {})

        # No supersede in the Loremaster's promotion path should use
        # legacy single-project shorthand. (The Inquisitor's writes
        # are tested separately.)
        legacy_form_calls = [
            call for call in lexicon.supersede_calls if call.get("project") is not None
        ]
        assert legacy_form_calls == [], (
            f"Loremaster promotion path emitted legacy `project=` "
            f"supersede(s); should be cross-project form only. "
            f"Got: {legacy_form_calls!r}."
        )


# ===========================================================================
# 5. Frontmatter — post-PR-#100 fields threaded
# ===========================================================================


class TestPromotionFrontmatter:
    async def test_promotion_write_carries_pedigree_frontmatter(self) -> None:
        """The promotion ``write`` call's frontmatter carries the full
        Mirror-calibration pedigree.

        Required keys per axiom + night-3 PR #100: ``source``,
        ``source_run``, ``verdict_status``, ``finding_severity``,
        ``promoted_at``, ``trigger_type``, ``source_muscle_keys``.
        These let Mirror calibration trace tech writes back to their
        originating Loremaster pass + the upstream Inquisitor verdict
        that seeded the source muscle cluster.
        """
        from bonfire.handlers.loremaster import LoremasterHandler

        cluster = {
            "key": "tech-pattern-003",
            "kind": "concept",
            "content": "Promoted pattern.",
            "tags": [],
            "essence_articulable": True,
            "source_run": "upstream-run-xyz",
            "verdict_status": "CONCERNS",
            "finding_severity": "MAJOR",
            "source_muscle_keys": [
                {"project": "alpha", "key": "alpha-key"},
                {"project": "beta", "key": "beta-key"},
                {"project": "gamma", "key": "gamma-key"},
            ],
        }
        lexicon = StrictFakeLexicon(search_returns=[[]])
        handler = LoremasterHandler(
            lexicon=lexicon,
            agent_runner=_FakeAgentRunner(_loremaster_response(clusters=[cluster])),
            project="bonfire-public",
        )
        await handler.handle(_make_stage(), _make_envelope(), {})

        assert len(lexicon.write_calls) >= 1, (
            "At least one tech write expected (cluster passed all gates)."
        )
        fm = lexicon.write_calls[0]["frontmatter"]
        required_keys = {
            "source",
            "source_run",
            "verdict_status",
            "finding_severity",
            "promoted_at",
            "trigger_type",
            "source_muscle_keys",
        }
        assert required_keys.issubset(set(fm.keys())), (
            f"Frontmatter missing required keys. "
            f"Required: {sorted(required_keys)!r}. "
            f"Got: {sorted(fm.keys())!r}."
        )
        assert fm["source"] == "loremaster"
        assert fm["source_run"] == "upstream-run-xyz"
        assert fm["verdict_status"] == "CONCERNS"
        assert fm["finding_severity"] == "MAJOR"


# ===========================================================================
# 6. N-floor gate
# ===========================================================================


class TestNFloorGate:
    async def test_cluster_below_n_floor_not_promoted(self) -> None:
        """Clusters with fewer than 3 distinct projects do not promote.

        Per axiom: "N>=3 distinct projects is pattern; N=2 is
        anecdote; N>=5 is consensus". The Loremaster does not promote
        anecdotes."""
        from bonfire.handlers.loremaster import LoremasterHandler

        cluster_n2 = {
            "key": "anecdote-pattern",
            "kind": "concept",
            "content": "Two projects share this.",
            "tags": [],
            "essence_articulable": True,
            "source_muscle_keys": [
                {"project": "alpha", "key": "alpha-key"},
                {"project": "beta", "key": "beta-key"},
            ],
        }
        lexicon = StrictFakeLexicon(search_returns=[[]])
        handler = LoremasterHandler(
            lexicon=lexicon,
            agent_runner=_FakeAgentRunner(_loremaster_response(clusters=[cluster_n2])),
            project="bonfire-public",
        )
        await handler.handle(_make_stage(), _make_envelope(), {})

        assert lexicon.write_calls == [], (
            f"N=2 cluster must not promote. Got writes: {lexicon.write_calls!r}."
        )
        assert lexicon.supersede_calls == [], (
            f"N=2 cluster must not supersede. Got supersedes: {lexicon.supersede_calls!r}."
        )
