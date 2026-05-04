# ADR-001: Three-Layer Naming Vocabulary

**Status:** Accepted
**Date:** 2026-04-16
**Decision makers:** Anta (Blacksmith King), Ishtar (Prompt Architect)
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

- All code uses generic names. No gamified terms in data models or tests.
- Serialized formats (JSONL, TOML) use StrEnum values directly.
- Display names are resolved at render time by the persona module.
- Adding a new role requires: StrEnum value + naming.py entry + persona TOML.
