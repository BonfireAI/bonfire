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

What's missing from those is a single map of the territory. This doc
fills that gap. Read it once on day one, then come back for the
"Extension points" and "Where to read next" sections when you need them.

## What Bonfire is

Bonfire is **a pipeline of role-bound agents over a typed event bus**.
Each stage of a run is owned by an agent that plays a specific role —
researcher (Scout), tester (Knight), implementer (Warrior), verifier
(Cleric), publisher (Bard), reviewer (Wizard), closer (Steward),
synthesizer (Sage), analyst (Architect); each stage emits typed events
on a shared bus; cross-cutting observers — cost tracking, session
logging, knowledge ingest, display — subscribe to those events without
ever calling stages back.

The role names follow the three-layer vocabulary locked by
[`ADR-001`](adr/ADR-001-naming-vocabulary.md): a generic layer for
code (`researcher`, `tester`, …), a professional layer for default
display (`Research Agent`, `Test Agent`, …), and an opt-in gamified
layer for personality-themed display (`Scout`, `Knight`, …). Above and
throughout this doc the generic name is primary and the gamified alias
is parenthetical; the table in ADR-001 § Agent Roles is the binding
reference.

The framework ships an opinionated default: TDD-shaped 9-stage builds
with the stage-name sequence ``scout``, ``knight``, ``warrior``,
``prover``, ``sage_correction_bounce``, ``bard``, ``wizard``,
``merge_preflight``, ``steward`` (these are the canonical wire-format
``StageSpec.name`` strings emitted by ``standard_build()`` — see
``bonfire.workflow.standard`` and the ratified gamified-key exception
in ADR-001 § Ratified Exceptions). Code review is baked in, runs use
your own model keys, and quality gates evaluate between stages.
Everything else — the agents, the backends, the personas, the
workflows — is pluggable through small ``Protocol`` contracts.

Within the standard build, the ``prover`` stage is a **verifier-role
alias**: ``standard_build()`` emits ``StageSpec(role="prover", ...)``
and the tier resolver in ``bonfire.agent.tiers`` normalizes ``"prover"``
to ``AgentRole.VERIFIER`` through ``GAMIFIED_TO_GENERIC`` (alongside
the canonical ``"cleric"`` alias). The prover stage runs after Warrior
to verify the implementation against the failing tests; with
``allowed_tools = ["Read", "Bash", "Grep", "Glob"]`` per
``DefaultToolPolicy._FLOOR``, it is the read-and-execute counterpart to
Warrior's read-write-edit toolset. Display translation resolves through
``ROLE_DISPLAY["verifier"]`` (→ "Verify Agent" / "Cleric"); ``"prover"``
itself is not a key in ``ROLE_DISPLAY``, which is intentional — the
gamified workflow-stage name aliases to the canonical verifier role for
display. **Note for ADR-001:** workflow-factory emission of gamified
strings into ``StageSpec.role`` is a second ratified surface alongside
``DefaultToolPolicy._FLOOR`` keys; ADR-001 § Ratified Exceptions should
be amended in a follow-up to formally enumerate it.

Tagline (from `src/bonfire/__init__.py`):

> *Define agents. Wire stages. Ship quality.*

## Module map

Bonfire's source lives under `src/bonfire/`. Packages group by role:

### Core

| Package | One-line purpose |
|---|---|
| `bonfire.engine` | Pipeline execution: `PipelineEngine` (owns the topological walk, gate evaluation, bounce, and budget watchdog), `StageExecutor` (a separately testable stage runner, re-exported but not driven by `PipelineEngine` today — the engine has its own inline stage loop), `ContextBuilder`, the eight built-in quality gates, and the `CheckpointManager` trio for opt-in save / restore. |
| `bonfire.dispatch` | Agent execution backends (Claude SDK, Pydantic AI), the `execute_with_retry` runner, `TierGate`, and the pre-exec security hook. |
| `bonfire.models` | Cross-package data contracts — frozen Pydantic shapes for envelopes, plans, events, and configuration. Dependency-free. |
| `bonfire.events` | Typed pub/sub spine — `EventBus` plus the `BonfireEvent` base contract; consumers live one level deeper. |
| `bonfire.protocols` | The four core extension protocols: `AgentBackend`, `VaultBackend`, `QualityGate`, `StageHandler`. |

### Agents

| Package | One-line purpose |
|---|---|
| `bonfire.agent` | Canonical `AgentRole` enum and the role↔display vocabulary. |
| `bonfire.handlers` | Pipeline-stage handlers (`Bard`, `Wizard`, `Steward`, `Architect`, `MergePreflight`, `SageCorrectionBounce`) — the bespoke logic for stages that aren't a plain agent dispatch. The verifier-role `MergePreflight` runs a deterministic pre-merge full-suite pytest against the simulated merged tip to catch cross-wave interactions; the synthesizer-role `SageCorrectionBounce` auto-bounces under-marked xfail decorators to a tool-restricted Sage correction agent before publication. |
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
| `bonfire.workflow` | Pre-built workflow plans (`standard_build`, `debug`, `dual_scout`, `triple_scout`, `spike`) — pure data factories that depend only on `bonfire.models`. |

### Reserved

| Package | Status |
|---|---|
| `bonfire.analysis` | Pydantic shapes + fingerprint for code-graph studies (Cartographer track). |
| `bonfire.onboard` | The Front Door — browser-based onboarding scan + conversation. |

`bonfire.naming` is a single module (not a package) that holds the
three-layer naming vocabulary referenced from `bonfire.persona` and
documented in `ADR-001`.

## Pipeline flow

> **v0.1 disclaimer.** The CLI verb `bonfire run` described in this section
> is **post-v0.1 design surface, not a shipped v0.1 command.** v0.1 ships
> the engine as a library — `from bonfire.engine import PipelineEngine`
> and `await engine.run(plan)` drives a real pipeline against a real
> backend — plus the CLI subcommands `init`, `scan`, `status`, `resume`,
> `handoff`, `persona`, and `cost`. The end-to-end `bonfire run` verb
> that wires the engine through the CLI is deferred to a later 0.1.x
> release (see [`README.md` § What's Not There Yet](../README.md)). The
> pipeline flow described below is the shape the engine executes today
> when driven from the library; it is also the shape `bonfire run` will
> drive when the verb lands.

A single pipeline run follows the same path top-to-bottom every time:

1. **Entry point.** Today: a library caller imports `bonfire.engine`,
   resolves a `WorkflowPlan` from `bonfire.workflow` (e.g.
   `standard_build()`), constructs a `PipelineEngine`, and `await`s
   `engine.run(plan)`. Tomorrow (post-v0.1): the `bonfire run`-style
   CLI verb in `bonfire.cli.app` will resolve the same workflow plan
   through the same composition root.
2. **Workflow plan.** A `WorkflowPlan` (see `bonfire.models.plan`) is a
   frozen, DAG-validated description of stages: each stage has a role,
   an optional handler name, a list of gate names, and dependency
   edges to earlier stages.
3. **PipelineEngine.** `bonfire.engine.pipeline.PipelineEngine`
   constructs a `TopologicalSorter` over the plan, groups ready stages
   by `parallel_group`, and runs each group either sequentially or
   under an `asyncio.TaskGroup`. The engine holds the `AgentBackend`,
   `EventBus`, `PipelineConfig`, the handler and gate registries, a
   `ContextBuilder`, an optional `ToolPolicy`, and `BonfireSettings`.
   It does **not** own a `CheckpointManager`; checkpoint persistence
   is an opt-in surface (see "Checkpoints" below).
4. **Inline stage execution.** For each stage the engine calls its
   own `_execute_stage` method, which builds the per-stage context
   via `ContextBuilder`, constructs the input envelope, and dispatches
   it either to the named handler from the registry or, when no
   handler is configured, to the agent backend through
   `bonfire.dispatch.runner.execute_with_retry`. The standalone
   `StageExecutor` class in `bonfire.engine.executor` implements the
   same stage-runner contract and is re-exported from `bonfire.engine`
   for downstream patching and for direct use by callers that want a
   stage runner without the surrounding DAG / gate machinery; the
   shipped `PipelineEngine` does not delegate to it today.
5. **Handler.** A handler is either a plain agent dispatch (the
   default for the researcher / tester / implementer / synthesizer
   roles — Scout / Knight / Warrior / Sage in the gamified vocabulary)
   or one of the bespoke classes in `bonfire.handlers`: `Bard` for PR
   publication (publisher), `Wizard` for review (reviewer), `Steward`
   for closure (closer), `Architect` for analysis (analyst),
   `MergePreflight` for the pre-merge full-suite pytest gate (verifier),
   and `SageCorrectionBounce` for auto-bouncing under-marked xfail
   decorators to a tool-restricted Sage agent (synthesizer).
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
9. **Gates and bounce.** After each stage the engine evaluates the
   stage's gate chain in registration order. A passing chain advances
   the pipeline. A failing error-severity gate triggers an optional
   single bounce to a recovery stage if `StageSpec.on_gate_failure`
   is set, then re-runs the original stage and re-evaluates gates
   exactly once (Sage decision D7 — no recursive retries). If the
   gate still fails, the engine short-circuits and returns
   `PipelineResult(success=False)` with the gate's failure result.
   Budget enforcement runs at parallel-group boundaries: a group that
   pushes accumulated cost above `plan.budget_usd` halts the run.

The vocabulary in this section — *stage*, *handler*, *gate*,
*envelope*, *plan* — is locked by
[`ADR-001-naming-vocabulary.md`](adr/ADR-001-naming-vocabulary.md).

### Checkpoints

`PipelineEngine.run()` does **not** write checkpoints. The engine has
no `CheckpointManager` dependency on its constructor, and the pipeline
loop has no checkpoint write site. `CheckpointManager`
(`bonfire.engine.checkpoint`) is a standalone, publicly-importable
helper that persists a `PipelineResult` plus its `WorkflowPlan` to an
atomic JSON file per session, and reads it back for resume. Callers
that want save / restore semantics must drive the manager themselves
around `PipelineEngine.run()` — typically: run the engine, take the
returned `PipelineResult`, and call `CheckpointManager.save(...)`. The
resume path on `PipelineEngine.run()` accepts a `completed=` mapping
of already-done stages, which is what a caller would build from a
loaded `CheckpointData`. The CLI does not yet wire this up; the
machinery is shipped as an extension surface, not as a default
behavior.

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
- **Workflows — `bonfire.workflow`**: register a new workflow factory
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

`bonfire.engine.gates` ships eight built-in `QualityGate` implementations
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
| `MergePreflightGate` | The `MergePreflightHandler` envelope reports `COMPLETED` (clean → `info`; with `META_PREFLIGHT_TEST_DEBT_NOTED` set → `warning`, allow-with-annotation per Sage Q6). Any non-COMPLETED status (cross-wave interaction, pure-warrior bug, pytest collection error, merge conflict) blocks the merge with `error` severity. Gate name is locked at `"merge_preflight_passed"`. |
| `SageCorrectionResolvedGate` | The `SageCorrectionBounceHandler` envelope reports a non-ambiguous resolution. Clean resolutions (`corrected`, `not_needed_*`, skip path) pass with `info`; `warrior_bug` verdicts and Wizard-escalated bounces pass with `warning` (the bounce is visible but does not block); `ambiguous` classifier verdicts block with `error` (forces Wizard inspection). Gate name is locked at `"sage_correction_resolved"`. |

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

For decision provenance — reach for these when you want to know *why*
a contract is shaped the way it is:

- [`docs/adr/ADR-001-naming-vocabulary.md`](adr/ADR-001-naming-vocabulary.md)
  — the locked vocabulary referenced throughout this doc.

For surface-level reading, the package-level `__init__.py` docstrings
(notably `bonfire.handlers`, `bonfire.persona`, and
`bonfire.workflow`) are the model voice for the rest of the codebase
and double as quick reference cards.
