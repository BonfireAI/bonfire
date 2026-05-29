# ADR-002: Failure Architecture — Typed Errors as an Interop Substrate

**Status:** Accepted
**Date:** 2026-05-29
**Decision makers:** Anta (Blacksmith King), Ishtar (Prompt Architect)
**Research:** Five-scout failure-surface inventory + dual-Sage synthesis (conservative "exceptions-first" vs innovative "typed-outcomes")

## Context

A tree-wide read of `src/bonfire/` found no coherent failure architecture. The
numbers (134 `except` sites across 127 files):

- **42 broad `except Exception`** (~31% of sites); only 8 acknowledged as deliberate.
- **2 custom exception classes total** — no common base, no `errors.py`.
- **At least five competing failure-signaling conventions** coexist: `raise`;
  broad-swallow-and-log; a plain-string error envelope; sentinel returns
  (`None` / `{}` / `[]` / `-1` / `"installed"`); `typer.Exit`; and a handful of
  ad-hoc `Result`/outcome objects.
- **Traceback loss** — many handlers log only `type(exc).__name__` (no
  `exc_info`) or swallow silently; only one outcome object carries a traceback.
- **Timeout fragmentation** — `asyncio.timeout` and `asyncio.wait_for` mixed
  across sites with four default scales and three config sources.

There is already a gold standard in the tree: the **dispatch engine**. Backends
never raise — a failure becomes a `FAILED` envelope carrying an `ErrorDetail`
(`error_type`, `message`, `traceback`, `stage_name`); the runner classifies
terminal-vs-retryable and emits typed failure events. The rest of the codebase
does not follow it.

The governing principle: **failure is how the machines talk.** A crash, a
timeout, a refused call is not the absence of a message — it is the richest
message a system sends. A typed, self-describing failure vocabulary is therefore
an *interop substrate*: when every component speaks one failure language, a
caller can **reason** about a failure (retry it, escalate it, translate it, route
it) instead of parsing prose or guessing from a `None`. This is the leverage HTTP
status codes gave the web and gRPC status codes gave RPC.

## Decision

Adopt a **hybrid** failure architecture in two parts: a fully additive spine
everywhere, and typed outcomes proven at one boundary first.

### Part 1 — The spine (additive; no public-API break)

1. **`bonfire/errors.py` — a `BonfireError(Exception)` base + a small taxonomy.**
   `terminal` / `retryable` becomes a class attribute on the error type,
   replacing the runner's string-matching allow-list (which stays as a shim that
   reads the attribute). The two existing custom exceptions are reparented;
   `PersonaSchemaError` keeps its `ValueError` lineage via dual inheritance so
   existing `except ValueError` callers are unaffected.
2. **`ErrorDetail.from_exception()`** — one bridge that turns any caught
   exception into the structured `ErrorDetail`, always capturing the traceback.
   `ErrorDetail`, `Envelope`, and `DispatchResult` stay wire-stable — **no break
   for `pip install` consumers.**
3. **`bonfire/timeouts.py` — one timeout resolver** (default scales + env
   override) that the fragmented sites converge on, unifying the duplicated
   retrieval-timeout helper.
4. **Logging policy.** `exc_info` is mandatory wherever a caught exception is
   logged (`logger.exception` or `exc_info=`); bare `logger.warning(exc)` is
   banned; one log per failure (no double-logging). Enforced by a CI lint.
5. **Correctness fix.** An empty retrieval result is **success** (`[]`), not
   failure — today an empty result and a backend-down are conflated.

### Part 2 — Typed outcomes at the retrieval boundary first

- Introduce an `Outcome[T]` type (`Ok | Err`) carrying a `BonfireError`.
- **Adopt it at the retrieval boundary only** — the worst smell (three divergent
  failure signals for the same operation) and the highest-value fix. Everywhere
  else stays exceptions-first: a typed `raise` caught **once** at a named
  never-raise shell, which renders an `ErrorDetail`.
- **Re-evaluate with evidence** (call-site ergonomics, churn) after that boundary
  ships, before extending `Outcome` further. Extending it to all boundaries is a
  breaking change and is a deliberate, deferred 2.0 conversation.

## Initial taxonomy

| Class | Kind | `retryable` |
|-------|------|-------------|
| `BonfireError` | base (carries code, message, context, traceback bridge) | — |
| `ConfigError` | terminal | no |
| `AgentError` | terminal (agent run reported an error) | no |
| `RateLimitError` | terminal/transient | yes |
| `CLINotFoundError` | terminal | no |
| `ExecutorError` | terminal | no |
| `RetrievalError` | operational | no |
| `SubprocessError` | operational | no |
| `TimeoutError_` | operational | yes |
| `NetworkError` | operational | yes |
| `ValidationError` / `SchemaError` | data-shape (also `ValueError`) | no |
| `IsolationError` | boundary violation | no |

The taxonomy stays **small and shared** — its growth is review-gated. A
sprawling error vocabulary fragments the substrate and destroys the interop
value, so adding a class is a deliberate act, not a convenience.

## Consequences

- **One vocabulary.** Callers reason about failures structurally
  (retry / escalate / translate / route) rather than parsing strings or
  inspecting sentinel values.
- **Additive spine → no consumer break.** `ErrorDetail` / `Envelope` /
  `DispatchResult` are unchanged; new exception classes subclass builtins where
  existing catches rely on them.
- **The retrieval-boundary change is behavior-changing** (empty = success) and
  is rolled out with heavy tests and review.
- **Phased rollout**, each phase test-first and review-gated: foundation
  (`errors.py`) → timeouts → retrieval proving-ground → dispatch → handlers →
  onboard / CLI. No code lands against this ADR until it is **Accepted** and the
  review gate clears.
- **Graduation.** The `ErrorDetail` and never-raises dispatch core are shared
  lineage with the v1 line and the internal workshop; this architecture is
  intended to graduate to both as a shared `bonfire.errors` / `bonfire.timeouts`
  module, so one taxonomy is reused rather than re-derived.

## Preserved patterns

These existing patterns are correct and are kept (and generalized *from*, not
replaced): the dispatch two-layer never-raises contract; event-bus handler
isolation; the strict-vs-tolerant loader split; writing a verdict before a
side-effecting call so the side-effect's failure can't swallow the verdict;
re-raising `asyncio.CancelledError` before any broad catch; and the fail-safe
parse cascade that returns an empty result by design.
