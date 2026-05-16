# ADR-001: Three-Layer Naming Vocabulary

**Status:** Accepted
**Date:** 2026-04-16
**Decision makers:** Blacksmith King + Prompt Architect (engineer-operator + AI prompt-architect roles)
**Research:** Triple-scout (Brand Architect, Developer Ergonomist, Lore Keeper) + Sage synthesis

## Context

Bonfire needs a naming system that serves three audiences simultaneously:
developers reading code, professionals reading docs, and enthusiasts who
want personality. The private codebase used gamified names (scout, knight,
warrior) everywhere, which confused outsiders in a perception gap audit.

## Decision

Three-layer naming system:

1. **Generic layer (code):** Python identifiers, config keys, serialized data.
   Boring, grep-friendly, unambiguous. `AgentRole(StrEnum)` with one string everywhere.
2. **Professional layer (default display):** CLI output, docs, website.
   Self-explanatory without a glossary. "Research Agent" not "Scout."
3. **Gamified layer (opt-in display):** Forge-themed personality via `--persona forge`.
   Every metaphor is load-bearing — it teaches the system, not just decorates.

The persona module maps generic -> display. Code never uses display names.
Display is a presentation concern, not a data concern.

## Agent Roles

| Generic | Professional | Gamified | Function |
|---------|-------------|----------|----------|
| researcher | Research Agent | Scout | Investigates, produces reports |
| tester | Test Agent | Knight | Writes failing tests (RED) |
| implementer | Build Agent | Warrior | Writes code to pass tests (GREEN) |
| verifier | Verify Agent | Cleric | Independent quality verification |
| publisher | Publish Agent | Bard | Branch, commit, PR |
| reviewer | Review Agent | Wizard | Code review |
| closer | Release Agent | Steward | Merge, close, announce |
| synthesizer | Synthesis Agent | Sage | Multi-report synthesis |
| analyst | Analysis Agent | Architect | Architectural and structural analysis |

## Module Renames (from private codebase)

| Private | Public | Rationale |
|---------|--------|-----------|
| vault/ | knowledge/ | Self-documenting import path |
| cartographer/ | analysis/ | Describes output, not metaphor |
| front_door/ | onboard/ | Standard SaaS term |
| workflows/ | workflow/ | PEP singular convention |
| costs/ | cost/ | Singular |
| scanners/ | scan/ | Singular, verb-noun duality |

## Class Renames

| Private | Public | Rationale |
|---------|--------|-----------|
| AxiomMeta | IdentityBlock | "Axiom" collides with CS meaning |
| ProjectStudy | ProjectAnalysis | Standard term for analysis output |
| WorkflowPlan | WorkflowSpec | "Spec" implies frozen contract |
| PhrasePool | PhraseBank | Standard metaphor (word bank) |
| TechFingerprinter | TechScanner | Matches module name |

## Consequences

- All code uses generic names, with two ratified exceptions (see § Ratified Exceptions below): the W1.5.3 default tool floor keys on gamified names to match the workflow-factory wire format, and `ROLE_DISPLAY` carries a `"prover"` alias entry mirroring the verifier display strings so that lookups against raw factory-emitted role strings resolve cleanly. No new gamified-keyed surfaces without amending this ADR.
- Serialized formats (JSONL, TOML) use StrEnum values directly.
- Display names are resolved at render time by the persona module.
- Adding a new role requires: StrEnum value + naming.py entry + persona TOML.

## Ratified Exceptions

This ADR's doctrinal default is "all code uses generic names." A single
exception is ratified below. The exception list is closed: new gamified-keyed
surfaces in code require an explicit amendment to this section, not silent
precedent.

### `DefaultToolPolicy._FLOOR` keys (`bonfire.dispatch.tool_policy`)

The W1.5.3 default tool allow-list shipped in `DefaultToolPolicy._FLOOR` keys
on the **gamified** role names (`scout`, `knight`, `warrior`, `prover`,
`sage`, `bard`, `wizard`, `steward`) rather than the generic `AgentRole`
StrEnum values. This is a deliberate exception, accepted as part of the W4.1
trust-triangle surface.

**Why:**

1. Workflow factories in `bonfire.workflow.standard` and `bonfire.workflow.research`
   emit gamified role strings into `StageSpec.role`; the wire format at the
   dispatch boundary is gamified.
2. The W1.5.3 floor is the shipped contract that 1352 LOC of test coverage
   (`tests/unit/test_tool_policy.py`) locks in place; this contract is one
   of the trust-triangle gates blocking the v0.1.0 tag.
3. A normalization seam already exists at `bonfire.agent.tiers.GAMIFIED_TO_GENERIC`
   and is consumed by `resolve_model_for_role`. `DefaultToolPolicy.tools_for`
   accepts either gamified or generic input via the same mapping; the floor's
   internal key vocabulary is invisible to callers, while the table's
   internal keys stay gamified to preserve the W4.1 contract and its test
   suite.

### `ROLE_DISPLAY["prover"]` alias entry (`bonfire.naming`)

The workflow factory `standard_build()` emits
`StageSpec(role="prover", ...)` for the post-Warrior verification stage
(see `bonfire.workflow.standard`). `"prover"` is a gamified workflow alias
for the canonical `AgentRole.VERIFIER`, normalized by
`bonfire.agent.tiers.GAMIFIED_TO_GENERIC`. `ROLE_DISPLAY` therefore ships
a `"prover"` entry that mirrors the verifier's display strings
(`"Verify Agent"` / `"Cleric"`), so any code path that looks up the raw
factory-emitted role string in `ROLE_DISPLAY` resolves cleanly without
falling through.

**Why:**

1. The wire format at the dispatch boundary is gamified for the
   `standard_build` factory; `"prover"` ships in `GAMIFIED_TO_GENERIC`
   alongside `"cleric"` as a verifier alias.
2. Persona display translation in `bonfire.persona.base.BasePersona.display_name`
   accepts canonical `AgentRole` values, but consumers that read
   `StageSpec.role` directly (status surfaces, knowledge ingest, future
   display consumers) may look up `ROLE_DISPLAY[stage.role]` against the
   raw factory-emitted string. Without a `"prover"` entry, that lookup
   silently misses and the caller falls back to the raw string —
   leaking the wire vocabulary into user-facing display.
3. The alias is closed-list: only `"prover"` ships under this exception,
   mirroring `verifier`'s display values. New gamified-keyed entries in
   `ROLE_DISPLAY` require amending this section.

**Forward rule:**

New dict-keyed-by-role surfaces in code MUST prefer the generic `AgentRole`
enum values. Any new gamified-keyed surface requires explicit amendment of
this section, not silent precedent. Pinning tests assert the ratified set
is exactly as enumerated above:

- `tests/unit/test_adr_001_ratified_exceptions.py` asserts that
  `DefaultToolPolicy._FLOOR`'s keys exactly match the ratified set
  (`RATIFIED_FLOOR_KEYS` — the eight names enumerated under
  `DefaultToolPolicy._FLOOR` above) AND that every ratified key is a
  known alias in `GAMIFIED_TO_GENERIC`.
- `tests/unit/test_doc_code_drift.py::test_role_display_covers_all_factory_roles`
  asserts that every `role=` string emitted by the workflow factories
  in `bonfire.workflow.{standard,research}` resolves through
  `ROLE_DISPLAY` (directly or via `GAMIFIED_TO_GENERIC` to a canonical
  `AgentRole`), catching factory drift that would re-open the
  ratified-list gap.

Silent extension or omission of the ratified set fails at CI.
