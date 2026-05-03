# Bonfire architecture — orientation for new contributors

This document orients a new contributor to the **shape** of the Bonfire
codebase: what packages exist, how a single run flows through them, and
where to plug in new behavior. It is deliberately complementary to the
other docs in this directory:

- The `README.md` answers *what Bonfire does* for end users.
- `docs/release-policy.md` and `docs/release-gates.md` describe how the
  project ships.
- `docs/adr/ADR-001-naming-vocabulary.md` locks the naming vocabulary
  used throughout the source.
- `docs/audit/sage-decisions/` records the design decisions that
  produced today's contracts.

What's missing from those is a single map of the territory. This doc
fills that gap. Read it once on day one, then come back for the
"Extension points" and "Where to read next" sections when you need them.

## What Bonfire is

Bonfire is **a pipeline of role-bound agents over a typed event bus**.
Each stage of a run is owned by an agent that plays a specific role
(scout, knight, sage, warrior, bard, wizard, steward, architect); each
stage emits typed events on a shared bus; cross-cutting observers — cost
tracking, session logging, knowledge ingest, display — subscribe to
those events without ever calling stages back.

The framework ships an opinionated default: TDD-shaped 7-stage builds
with code review baked in, run against your own model keys, with
quality gates between stages. Everything else — the agents, the
backends, the personas, the workflows — is pluggable through small
``Protocol`` contracts.

Tagline (from `src/bonfire/__init__.py`):

> *Define agents. Wire stages. Ship quality.*

## Module map

Bonfire's source lives under `src/bonfire/`. Packages group by role:

### Core

| Package | One-line purpose |
|---|---|
| `bonfire.engine` | Pipeline execution: `PipelineEngine`, per-stage `StageExecutor`, the six built-in quality gates, the checkpoint trio. |
| `bonfire.dispatch` | Agent execution backends (Claude SDK, Pydantic AI), the `execute_with_retry` runner, `TierGate`, and the pre-exec security hook. |
| `bonfire.models` | Cross-package data contracts — frozen Pydantic shapes for envelopes, plans, events, and configuration. Dependency-free. |
| `bonfire.events` | Typed pub/sub spine — `EventBus` plus the `BonfireEvent` base contract; consumers live one level deeper. |
| `bonfire.protocols` | The four core extension protocols: `AgentBackend`, `VaultBackend`, `QualityGate`, `StageHandler`. |

### Agents

| Package | One-line purpose |
|---|---|
| `bonfire.agent` | Canonical `AgentRole` enum and the role↔display vocabulary. |
| `bonfire.handlers` | Pipeline-stage handlers (`Bard`, `Wizard`, `Steward`, `Architect`) — the bespoke logic for stages that aren't a plain agent dispatch. |
| `bonfire.persona` | CLI display translation only — turns events into character-voiced lines via TOML-defined personas. Never touches prompts. |
| `bonfire.prompt` | Prompt compiler with priority-based truncation, identity blocks, and U-shape ordering. |

### Integrations

| Package | One-line purpose |
|---|---|
| `bonfire.git` | Branch / commit / worktree-isolation helpers used by the workflow stages. |
| `bonfire.github` | GitHub API client for PRs and issues (with a mock for tests). |
| `bonfire.knowledge` | Vault-backend factory — in-memory by default, LanceDB when configured. |
| `bonfire.scan` | Scanners that turn project state into `VaultEntry` records for ingest. |
| `bonfire.cost` | Cost ledger consumer, analyzer, and per-dispatch / per-pipeline records. |
| `bonfire.session` | Session state and JSONL persistence — the durable footprint of a run. |
| `bonfire.xp` | XP / progression — calculator, tracker, display consumer. |

### CLI and workflows

| Package | One-line purpose |
|---|---|
| `bonfire.cli` | Typer composition root — `app` is the entry point exposed by `[project.scripts]`. |
| `bonfire.cli.commands` | Per-command Typer modules (`init`, `scan`, `status`, `resume`, `handoff`, `persona`, `cost`). |
| `bonfire.workflows` | Pre-built workflow plans (`standard_build`, `debug`, `dual_scout`, `triple_scout`, `spike`) — pure data factories that depend only on `bonfire.models`. |

### Reserved

| Package | Status |
|---|---|
| `bonfire.analysis` | Pydantic shapes + fingerprint for code-graph studies (Cartographer track). |
| `bonfire.onboard` | The Front Door — browser-based onboarding scan + conversation. |

`bonfire.naming` is a single module (not a package) that holds the
three-layer naming vocabulary referenced from `bonfire.persona` and
documented in `ADR-001`.

## Pipeline flow

A single `bonfire run` follows the same path top-to-bottom every time:

1. **CLI entry.** `bonfire.cli.app` parses the command and instantiates
   the composition root. The user-facing `bonfire run`-style commands
   resolve a workflow plan from `bonfire.workflows` (e.g.
   `standard_build`).
2. **Workflow plan.** A `WorkflowPlan` (see `bonfire.models.plan`) is a
   frozen, DAG-validated description of stages: each stage has a role,
   a handler, a list of gates, and dependency edges to earlier stages.
3. **PipelineEngine.** `bonfire.engine.pipeline.PipelineEngine` walks
   the plan in topological order and dispatches each stage to a
   `StageExecutor`. It owns the `EventBus`, the `CheckpointManager`,
   and the running cost / XP context.
4. **StageExecutor.** For each stage, `bonfire.engine.executor`
   constructs the input envelope, picks the right `StageHandler`, runs
   it, and then runs the stage's `GateChain` over the result.
5. **Handler.** A handler is either a plain agent dispatch (the
   default for scouts, knights, warriors, sages) or one of the bespoke
   handlers under `bonfire.handlers` (`Bard` for PR publication,
   `Wizard` for review, `Steward` for closure, `Architect` for analysis).
6. **Dispatch backend.** Plain-dispatch handlers call into
   `bonfire.dispatch` — by default `ClaudeSDKBackend`, optionally
   `PydanticAIBackend` — through the `execute_with_retry` runner. The
   pre-exec security hook (see "Security model" below) sits inside
   the SDK backend.
7. **Event bus.** Every stage emits typed events
   (`StageStarted`, `StageCompleted`, `DispatchUsage`,
   `SecurityDenied`, …). All events subclass `BonfireEvent`.
8. **Consumers.** Cost, display, knowledge ingest, and session-logger
   consumers (`bonfire.events.consumers`) react to events without
   blocking the pipeline. Wiring is done once at composition time via
   `wire_consumers`.
9. **Checkpoint and gates.** After each stage the engine writes a
   checkpoint and evaluates the stage's `GateChain`. A failing
   error-severity gate short-circuits the run; the pipeline reports
   `PipelineResult(success=False)` with the gate's message.

The vocabulary in this section — *stage*, *handler*, *gate*,
*envelope*, *plan* — is locked by
[`ADR-001-naming-vocabulary.md`](adr/ADR-001-naming-vocabulary.md).

## Event bus and consumers

Bonfire's bus is **one-way**. Stages emit; consumers subscribe. There
is no return channel from a consumer to a stage. This is intentional:
it keeps observers (cost tracking, display, knowledge ingest, session
logging) decoupled from execution and makes the pipeline easy to reason
about under retry and resume.

Shipped consumers, all under `bonfire.events.consumers`:

| Consumer | Purpose |
|---|---|
| `CostTracker` | Accumulates `DispatchUsage` events into a running session cost the rest of the engine can read. |
| `DisplayConsumer` | Turns events into persona-voiced display lines. |
| `KnowledgeIngestConsumer` | Stores selected events as `VaultEntry` records in the configured vault backend. |
| `SessionLoggerConsumer` | Appends every event to the session's JSONL log via `bonfire.session.persistence`. |

To register a new consumer:

1. Implement an async `handle(event: BonfireEvent) -> None` (or
   subscribe to a specific event type via `bus.subscribe(SomeEvent,
   handler)`).
2. Wire it from `bonfire.events.consumers.wire_consumers` (or call
   `your_consumer.register(bus)` directly from the composition root if
   you'd rather not touch the helper).

The bus itself is `bonfire.events.bus.EventBus`, an async fan-out
broker that swallows consumer exceptions so a misbehaving observer
cannot rescue (or break) a stage decision.

## Extension points

Bonfire is designed to be extended through a small number of explicit
seams. Every seam is a `typing.Protocol` so structural subtyping
(rather than ABC inheritance) gates conformance.

- **Agent backends — `AgentBackend`** (`bonfire.protocols`): implement
  `execute(envelope, *, options) -> Envelope` and `health_check()` and
  the engine will dispatch through your runtime instead of the default
  Claude SDK. See `bonfire.dispatch.sdk_backend` and
  `bonfire.dispatch.pydantic_ai_backend` for working references.
- **Vault backends — `VaultBackend`** (`bonfire.protocols`): implement
  `store`, `query`, `exists`, and `get_by_source` to plug a different
  knowledge store under `bonfire.knowledge.get_vault_backend`.
- **Personas — TOML in `src/bonfire/persona/builtins/`**: drop a new
  persona TOML with the required schema and `PersonaLoader.load` will
  pick it up. Personas are display-only — they cannot reach into
  prompts or gates by construction.
- **Workflows — `bonfire.workflows`**: register a new workflow factory
  on the `WorkflowRegistry`. The factory returns a frozen,
  DAG-validated `WorkflowPlan`. The package depends only on
  `bonfire.models`, so new workflows do not need to touch the engine.
- **Stage handlers — `StageHandler`** (`bonfire.protocols`):
  implement `handle(stage, envelope, prior_results) -> Envelope` if you
  need bespoke orchestration (parallel fan-out, human-in-the-loop, an
  external API call) instead of a plain agent dispatch.
- **Quality gates — `QualityGate`** (`bonfire.protocols`): implement
  `evaluate(envelope, context) -> GateResult` to add a new pass/fail
  check. The shipped gates in `bonfire.engine.gates` are the canonical
  reference for severity semantics.

## Gates and quality

`bonfire.engine.gates` ships six built-in `QualityGate` implementations
plus the `GateChain` composer. The chain runs gates in registration
order and short-circuits on the first error-severity failure.

| Gate | Passes when… |
|---|---|
| `CompletionGate` | The envelope's `TaskStatus` is `COMPLETED`. |
| `TestPassGate` | The result text contains "passed" and no non-zero failure indicator. |
| `RedPhaseGate` | The result text contains a non-zero failure indicator (the inverse of `TestPassGate`, used for TDD RED phases). |
| `VerificationGate` | The result text contains "verified" or "checks passed". |
| `ReviewApprovalGate` | The result text contains "approve" or "approved". |
| `CostLimitGate` | The pipeline's accumulated cost is within the configured budget. |

`GateChain.evaluate_all` does **not** wrap individual gate exceptions —
a raising gate propagates to `PipelineEngine.run()`, which catches it
in its outer `try/except` and reports `PipelineResult(success=False)`.
This is locked by Sage decision D5 on the gate package; do not change
it without a fresh decision.

## Security model

Bonfire enforces a **fail-closed pre-exec security hook** on every
`Bash`, `Write`, and `Edit` tool invocation made by an agent through
`ClaudeSDKBackend`. The hook lives in `bonfire.dispatch.security_hooks`
and matches against the curated pattern catalogue in
`bonfire.dispatch.security_patterns`.

Two short pieces orient the model:

1. **Configuration.** `SecurityHooksConfig` is part of
   `DispatchOptions` (see `bonfire.protocols`). Users can extend the
   deny list with `extra_deny_patterns` but cannot soften the default
   floor. The config is frozen and `extra="forbid"`.
2. **Decision flow.** The hook normalizes the command (NFKC, `$IFS`
   expansion, backslash-newline collapse), recursively unwraps
   `sudo` / `bash -c` / `nohup` / `xargs` / `find -exec` wrappers up
   to depth 5, then matches the segments against the deny rules
   (categories C1 destructive-fs, C2 destructive-git, C3
   pipe-to-shell, C4 exfiltration, C7 system-integrity) and the
   warn rules (C5 priv-escalation, C6 shell-escape). Any exception
   inside the hook turns into a DENY plus a `SecurityDenied` event
   tagged `_infra.error`.

DENY emits a `SecurityDenied` event and blocks the tool call. WARN
emits the same event with the reason prefixed `"WARN: "` and lets the
call through — visibility without blocking.

## Where to read next

For day-to-day contributor work:

- [`README.md`](../README.md) — start here; the `## What Bonfire Does`
  section is the consumer-facing summary this doc deliberately does
  not duplicate.
- [`docs/release-policy.md`](release-policy.md) — what counts as a
  ship-ready change.
- [`docs/release-gates.md`](release-gates.md) — the gate-by-gate map of
  what each ticket must clear before it merges.
- [`docs/release-gate-tickets.md`](release-gate-tickets.md) — the
  ticket-level expectations that feed the gates.

For decision provenance — reach for these when you want to know *why*
a contract is shaped the way it is:

- [`docs/adr/ADR-001-naming-vocabulary.md`](adr/ADR-001-naming-vocabulary.md)
  — the locked vocabulary referenced throughout this doc.
- [`docs/audit/sage-decisions/bon-337-unified-sage-2026-04-18.md`](audit/sage-decisions/bon-337-unified-sage-2026-04-18.md)
  — the unified Sage decision behind the agent-tool policy.
- [`docs/audit/sage-decisions/bon-338-unified-sage-2026-04-18.md`](audit/sage-decisions/bon-338-unified-sage-2026-04-18.md)
  — the security-hook design (the source of the catalogue + the
  fail-closed semantics).
- [`docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md`](audit/sage-decisions/bon-341-sage-20260422T235032Z.md)
  — the knowledge-layer decision that grounds `bonfire.knowledge`.

For surface-level reading, the package-level `__init__.py` docstrings
(notably `bonfire.handlers`, `bonfire.persona`, and
`bonfire.workflows`) are the model voice for the rest of the codebase
and double as quick reference cards.
