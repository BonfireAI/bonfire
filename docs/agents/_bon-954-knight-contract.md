# Knight contract — Caronte vendor port (post-bracket Inquisitor + Loremaster)

This memo summarizes the decisions locked by the Knight tests on
``antawari/bon-954-caronte-vendor``. The four contract test files
encode the law; this memo is the readable digest. Cleaned up at PR
time.

## Files

- ``tests/unit/test_inquisitor_handler.py``
- ``tests/unit/test_loremaster_handler.py``
- ``tests/unit/test_pipeline_engine_brackets.py``
- ``tests/unit/test_tool_policy_caronte.py``
- ``tests/unit/_strict_fake_lexicon.py`` (shared fixture)

## Handler signatures

```python
class InquisitorHandler:
    ROLE: AgentRole = AgentRole.JUDGE  # generic identifier

    def __init__(
        self,
        *,
        lexicon: LexiconClient,
        agent_runner: AgentRunner,
        project: str,
        run_id: str,
    ) -> None: ...

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope: ...


class LoremasterHandler:
    ROLE: AgentRole = AgentRole.PROMOTER

    def __init__(
        self,
        *,
        lexicon: LexiconClient,
        agent_runner: AgentRunner,
        project: str,
    ) -> None: ...

    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope: ...
```

Both handlers declare an inline ``LexiconClient`` Protocol with
``search``, ``list``, ``read``, ``write``, ``supersede``. The
``supersede`` Protocol method declares BOTH legacy ``project=`` AND
explicit ``project_old=``/``project_new=`` kwargs (post-d72903b
``bonfire-lexicon`` shape).

## AgentRole enum decision

**Adopted: ``JUDGE = "judge"`` and ``PROMOTER = "promoter"``.**

ADR-001 binds three layers: generic (code) / professional (default
display) / gamified (opt-in display). Existing nine generic slots all
use professional/agentive nouns (researcher, tester, implementer,
verifier, publisher, reviewer, closer, synthesizer, analyst). ``judge``
+ ``promoter`` extend the same vocabulary cleanly.

Display layer additions (``naming.py``):

```python
ROLE_DISPLAY["judge"] = DisplayNames("Judge Agent", "Inquisitor")
ROLE_DISPLAY["promoter"] = DisplayNames("Promoter Agent", "Loremaster")
```

Rejected alternatives:

- **``INQUISITOR`` / ``LOREMASTER`` as enum values.** Would put gamified
  names in the code-layer identifier — explicitly forbidden by ADR-001
  §"Code never uses display names."
- **``ARBITER`` / ``HISTORIAN``.** Considered, but ``judge`` /
  ``promoter`` are the more accurate professional name for what each
  agent does (renders verdicts, promotes muscle to tech).

Class names stay gamified (``InquisitorHandler``,
``LoremasterHandler``) — matches the existing public-tree precedent
(``WizardHandler``, ``StewardHandler``, ``ArchitectHandler``,
``BardHandler``). File-level names also gamified
(``handlers/inquisitor.py``, ``handlers/loremaster.py``).

ADR-001 amendment required: the table at lines 31–40 grows two rows.

## Engine API choice

```python
PipelineEngine.__init__(
    *,
    # ... existing kwargs ...
    pre_bracket: list[StageSpec] | None = None,
    post_bracket: list[StageSpec] | None = None,
)
```

Both default to ``None`` for backward compat with every existing engine
construction site. ``pre_bracket`` ships v1.0 empty (Hephaestus v1.1 /
BON-958 lands the first use case).

**Verdict signaling.** ``PipelineResult`` has a frozen 8-field shape
(Sage D8 lock). The bracket verdict signal lives on the **post-bracket
stage envelope's metadata** under two pinned keys:

- ``META_BRACKET_VERDICT_STATUS`` (= ``"bracket_verdict_status"``):
  ``"PASS"`` | ``"CONCERNS"`` | ``"FAIL"``.
- ``META_BRACKET_EFFECTUATE`` (= ``"bracket_verdict_effectuate"``):
  ``bool``. ``True`` iff verdict is PASS.

Pipeline ``success`` routing:

| Verdict   | success | effectuate | Behavior                               |
|-----------|---------|------------|----------------------------------------|
| PASS      | True    | True       | Steward proceeds                       |
| CONCERNS  | True    | False      | Halt before effectuation; Anta triages |
| FAIL      | False   | False      | Pipeline rejected at bracket           |

**Alternative considered (deferred to Sage):** widen ``PipelineResult``
to add a ``bracket_verdict: BracketVerdict | None`` field. Rejected
for v1.0 because Sage D8 explicitly locks the 8-field shape; widening
requires its own audit log entry. The metadata-key path keeps the
contract additive without breaking the locked shape. The alternative
is open for the Sage to weigh during synthesis.

**Main-DAG-failure short-circuit.** If the main DAG fails, the
post-bracket Inquisitor does NOT run — locked by
``TestMainDAGFailureShortCircuit``.

## tool_policy floor

```python
DefaultToolPolicy._FLOOR["inquisitor"] = [
    "Read", "Grep", "Glob",
    "mcp__bonfire_lexicon__memory_search",
    "mcp__bonfire_lexicon__memory_read",
    "mcp__bonfire_lexicon__memory_list",
    "mcp__bonfire_lexicon__memory_write",
    "mcp__bonfire_lexicon__memory_supersede",
    "mcp__bonfire_lexicon__memory_write_batch",
]

DefaultToolPolicy._FLOOR["loremaster"] = [
    "Read", "Grep", "Glob",
    "mcp__bonfire_lexicon__memory_search",
    "mcp__bonfire_lexicon__memory_read",
    "mcp__bonfire_lexicon__memory_list",
    "mcp__bonfire_lexicon__memory_write",
    "mcp__bonfire_lexicon__memory_supersede",
    "mcp__bonfire_lexicon__memory_write_batch",
]
```

Both are identical at the floor — the role separation lives in the
agent axiom + the Protocol surface, not the tool budget. Neither role
gets ``Bash``, ``Edit``, or ``Write``: the judge + promoter are pure
readers + Lexicon mutators. Per-user TOML overrides (W4.1) can widen.

## _StrictFakeLexicon interface

Lives at ``tests/unit/_strict_fake_lexicon.py``. Mirrors the
``LexiconClient`` Protocol exactly with EXPLICIT kwargs and NO
``**kwargs``. Unknown kwargs raise ``TypeError`` at the Python call
site; mixed ``project=`` + ``project_old=``/``project_new=`` raise
``ValueError``.

Methods:

- ``search(*, query, scope, kind) -> list[dict]``
- ``list(*, scope, kind=None, limit=None, since=None) -> list[dict]``
- ``read(*, key, project, kind=None) -> dict | None``
- ``write(*, project, key, kind, content, tags, frontmatter) -> None``
- ``supersede(*, key_old, key_new, kind, content, tags, frontmatter,
  project=None, project_old=None, project_new=None) -> None``

Every method records calls on a per-method ``*_calls`` list for test
introspection.

## Frontmatter pedigree (night-3 PR #100)

Both handlers' ``_build_frontmatter`` produce a dict with the SAME
seven keys (uniform shape across cadre):

- ``source`` — ``"inquisitor"`` or ``"loremaster"``
- ``source_run`` — pipeline run identifier
- ``verdict_status`` — upstream Inquisitor verdict (PASS/CONCERNS/FAIL)
- ``finding_severity`` — highest severity in source cluster
- ``promoted_at`` — ISO-8601 timestamp
- ``trigger_type`` — ``"cron"`` | ``"threshold"`` | ``"manual"``
  (always ``"manual"`` for Inquisitor; varies for Loremaster)
- ``source_muscle_keys`` — list of ``{project, key}`` dicts (may be
  empty for Inquisitor)

This is the load-bearing canon-grade lesson from night-3:
``feedback_fake_lexicon_hides_vendor_mismatch_2026_05_12``. Mirror
calibration depends on this shape; the strict fake locks it.

## Intentionally deferred to Hephaestus v1.1 (BON-958)

These are NOT in scope for v0.1.0 / BON-954 and are explicitly NOT
tested in this Knight contract:

- ``pre_bracket`` use cases. The parameter exists; v1.0 ships with
  ``pre_bracket=None`` everywhere. Hephaestus v1.1 carves the first
  pre-bracket stage (Artificer / domain-axiom enforcement).
- Pre-bracket gate evaluation (Artificer's spike harness).
- ``filter_tech_kind`` / Hephaestus-shared trust-boundary primitives
  (live in the private tree's ``forge/core/handlers/trust_boundary.py``;
  Hephaestus v1.1 vendors them).
- Performance / cost-budget regression tests (deferred past v0.1.0).
- Modifying existing handlers (architect, wizard, steward, bard,
  sage_correction_bounce, merge_preflight).
- Vendoring the axiom markdown files
  (``forge/agents/{inquisitor,loremaster}/prompt.md``); the handler
  module docstrings reference them.

## Notes for Warriors

1. The Inquisitor handler MUST surface its verdict on the returned
   envelope. Two acceptable paths: serialize the parsed Verdict as JSON
   in ``Envelope.result`` (richer; preserves findings + receipts), OR
   write ``verdict_status`` to ``Envelope.metadata`` (minimal; engine-
   only consumer). Test
   ``TestVerdictEmission.test_pass_verdict_emitted_on_clean_response``
   accepts either. Pick the JSON-in-result path for v1.0 — Mirror
   calibration will need findings + receipts soon.

2. ``Envelope.with_metadata(**kwargs)`` already exists on the Envelope
   model; use it instead of ``model_copy(update={...})`` for the
   bracket metadata writes.

3. The bracket verdict's metadata keys
   (``META_BRACKET_VERDICT_STATUS``, ``META_BRACKET_EFFECTUATE``) are
   exported by the test file; the Warrior should declare matching
   ``META_*`` constants in ``bonfire.models.envelope`` and the test's
   import will switch to importing from there once the production
   names land. The test file's local declaration is a Knight-side
   placeholder.

4. Probe 5 close-tag neutralization: the strategy is to mutate any
   literal ``</untrusted_payload>`` in body text via a ZWJ insertion
   between ``</`` and ``untrusted_payload>`` so the closing tag does
   not match the structural sentinel opener. The private tree's
   ``forge/core/handlers/trust_boundary._neutralize_sentinel_tags``
   is the reference impl; vendor a focused subset.

5. The handler's ``handle()`` signature must match
   ``StageHandler.handle`` exactly — three positional params
   ``stage``, ``envelope``, ``prior_results`` — so the engine's
   ``self._handlers[handler_name].handle(...)`` call site works
   verbatim.

6. For the Loremaster's batch write path: if production wires
   ``memory_write_batch`` end-to-end, prefer that for the supersede+
   write atomic op (BON-981 lesson). The strict fake exposes both
   `supersede` direct calls and an opportunistic batch path; the
   tests assert against the eventual recorded calls, not the path.

7. Smoke pipeline (out of Knight scope, in Warrior scope): the
   ``bonfire-e2e-fixture`` Box runner should exercise a single-stage
   plan with ``post_bracket=[inquisitor_stage]`` end-to-end before
   the v0.1.0 tag.
