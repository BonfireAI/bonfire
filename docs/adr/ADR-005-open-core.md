# ADR-005: Open-Core Commercial Model

**Status:** Accepted
**Date:** 2026-05-30
**Decision makers:** Anta, Ishtar

## Context

bonfire-public ships under Apache-2.0 as the free, self-hostable framework —
the complete pipeline anyone can run, fork, and extend. A commercial tier sits
above this free baseline, offering advanced capabilities. Public readers need a
path to that framing so that the `tier` config key reads as a deliberate seam
rather than a dead-end.

## Decision

Bonfire follows an **open-core** model: the framework in this repository is free
and Apache-2.0; advanced capabilities are offered under a separate commercial
tier. The full commercial-model decision record is filed in the internal canon
and is not reproduced here.

## Implication for Config

The `[bonfire].tier` key in `bonfire.toml` (see `README.md` line 160) selects the
commercial tier. In this Apache-2.0 release the baseline is `tier = "free"`, and
`TierGate.check_tier` (`src/bonfire/dispatch/tier.py`) always returns `True` — no
capability is gated. The key is forward-looking: it is reserved as the contract
seam for future tier-based gating, so that adding a commercial tier later is an
additive change rather than a breaking one.

## Out of Scope

Full commercial-tier documentation never goes public; it lives in the internal
canon. This ADR records only the open-core framing and what the `tier` key means
in the free release.
