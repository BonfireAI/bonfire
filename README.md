# Bonfire

**An installable Python pipeline runtime that enforces software-build discipline at the dispatch boundary.** Define agents. Wire stages. Ship quality.

[![PyPI](https://img.shields.io/pypi/v/bonfire-ai.svg)](https://pypi.org/project/bonfire-ai/)
[![Python](https://img.shields.io/pypi/pyversions/bonfire-ai.svg)](https://pypi.org/project/bonfire-ai/)
[![License](https://img.shields.io/pypi/l/bonfire-ai.svg)](https://github.com/BonfireAI/bonfire/blob/main/LICENSE)

> ### Alpha — `v0.1.0a2`
>
> This is the first functional release of `bonfire-ai`. The pipeline
> engine, the role-bound cadre, the quality gates, the persona system,
> and the `bonfire scan` onboarding flow are wired and exercised by
> the test suite. An in-memory `VaultBackend` ships as the default
> knowledge store; a LanceDB-backed implementation is available
> behind the `bonfire-ai[knowledge]` extra. The CLI verb that drives
> the engine end-to-end (`bonfire run`), the bundled prompt-template
> directory, and the persistent knowledge-graph storage are deferred
> to later 0.1.x releases. The frame is shipped; some operations are
> deliberately not.
>
> If you are an early adopter, run it against a throwaway repo, file
> issues at [github.com/BonfireAI/bonfire/issues](https://github.com/BonfireAI/bonfire/issues),
> and tell us where it bites. The vocabulary, the protocols, and the
> config schema are stable for 0.1.x.

---

## What Bonfire Is

Bonfire is a layer of good software-developing practices that wraps
your already-AI-assisted workflow. You `pip install` it; your agents
suddenly know they have nine roles talking to each other for quality.

Each agent has a static axiom of rules and an injected handoff from
the prior agent. That isolation is the whole point: every role gets
the best of the LLM by being asked one focused thing at a time, with
exactly the context it needs and nothing else.

The discipline is structural, not advisory. The role that writes
failing tests cannot edit implementation. The role that writes
implementation cannot edit tests. The reviewer is read-only. A typed
envelope passes between stages; a quality gate decides whether each
handoff moves forward, retries once, or stops the pipeline. Source
code is the deliverable.

## Quick Start

```bash
pip install bonfire-ai
```

The PyPI package is `bonfire-ai`; the installed console script is
`bonfire`. Python 3.12+ is required.

```bash
# Initialize a project (creates bonfire.toml and .bonfire/)
bonfire init .

# Launch the browser-based onboarding scan
bonfire scan

# Inspect cumulative cost and recent sessions
bonfire cost

# List installed personas
bonfire persona list
```

Available subcommands in `v0.1.0a2`: `init`, `scan`, `status`, `resume`,
`handoff`, `persona`, `cost`. Run `bonfire --help` for the full surface
or `bonfire <command> --help` for any single command.

## Architecture Overview

A Bonfire pipeline is an ordered sequence of stages. Each stage
dispatches an agent of a specific `AgentRole` (researcher, tester,
implementer, verifier, publisher, reviewer, closer, synthesizer,
analyst). Between stages, `QualityGate` instances inspect the
envelope and decide whether to proceed, retry once, or stop.

The TDD contract is enforced at the role boundary: the **tester**
writes failing tests that define the contract (RED), the
**implementer** writes code to pass them (GREEN), and the
**verifier** runs an independent quality check before the
**publisher** opens a PR. The **reviewer** can bounce work back
into the loop until it passes or the budget is exhausted. The
**closer** seals the work — merges the PR, posts the completion,
closes the ticket — only after every gate has cleared.

Bring your own provider key. Pick the model per role. Models are
resolved through `resolve_model_for_role`, which maps each
`AgentRole` to a capability tier (`reasoning`, `fast`, or `balanced`)
and returns the corresponding provider model string from your
config. Pure synchronous resolution; never raises on a string input.

## The Cadre

Bonfire ships nine role-bound agents; the runtime picks how each one
runs. Four dispatch through an LLM agent backend; three are
deterministic stage handlers wrapping `gh` / `git` / `pytest` with no
LLM call at all; one combines synthesis with a bounded correction
step; one is opt-in pre-pipeline architectural analysis. The cadre is
fixed in source as a `StrEnum` and rendered through three name
layers — the generic identifier, the professional display name, and
the gamified display name.

### Naming Glossary

The **generic concept** describes what the role does. The
**professional name** (`AgentRole`) is the canonical serialized form
used in TOML, JSONL, CLI output, and grep patterns. The **gamified
name** is a workflow alias emitted by the standard and research
workflow templates and normalized through `GAMIFIED_TO_GENERIC`
before tier lookup.

| Generic Concept                                   | Professional (`AgentRole`) | Gamified (workflow alias) |
| ------------------------------------------------- | -------------------------- | ------------------------- |
| Investigates the task and gathers context         | `researcher`               | `scout`                   |
| Writes failing tests (TDD RED)                    | `tester`                   | `knight`                  |
| Writes code to pass the tests (TDD GREEN)         | `implementer`              | `warrior`                 |
| Independent quality verification                  | `verifier`                 | `cleric`                  |
| Creates branches, commits, opens PRs              | `publisher`                | `bard`                    |
| Code review with structured verdicts              | `reviewer`                 | `wizard`                  |
| Merges approved PRs and announces completion      | `closer`                   | `steward`                 |
| Combines multiple reports into unified analysis   | `synthesizer`              | `sage`                    |
| Architectural and structural analysis             | `analyst`                  | `architect`               |

The string `prover` appears in the `standard_build` pipeline as a
stage label; that stage dispatches to the `verifier` role. Stage
labels name DAG nodes inside a workflow plan; display names are the
persona-emitted role names in CLI output.

> **Note — Falcor is a persona, not a role.** The cadre is the nine
> roles above. The persona is what speaks for them at the CLI surface.
> See [Personality](#personality-optional) below.

## The Vault

Alongside the cadre, the **Vault** is the named knowledge store of
Bonfire's world — capitalized, personified in display vocabulary,
narrated by the persona at lifecycle moments (*The Vault remembers*,
*The Vault gives back*). The Vault is not an agent; it is never
dispatched and has no role. Today the `VaultBackend` Protocol is
published and an **in-memory default backend** ships (substring
matching, no embeddings, no external dependencies — suitable for
tests and small projects). A LanceDB-backed implementation is
available behind the `bonfire-ai[knowledge]` extra; the persistent
knowledge-graph storage layer lands in a later 0.1.x release.

## Config Reference

Bonfire reads `bonfire.toml` from the current working directory.
Settings priority is: constructor kwargs → environment variables
(`BONFIRE_` prefix, `__` nested delimiter) → `bonfire.toml` → field
defaults.

A minimal complete config showing every section and its real
defaults:

```toml
# bonfire.toml

[bonfire]
tier = "free"                       # commercial tier
model = "claude-sonnet-4-6"         # default model when no role match
max_turns = 10                      # per-agent turn cap (must be > 0)
max_budget_usd = 5.0                # per-pipeline budget cap (>= 0)
persona = "falcor"                  # CLI output persona

[models]                            # bring your own provider key — strings live here
reasoning = "claude-opus-4-7"       # researcher, reviewer, synthesizer, analyst
fast      = "claude-haiku-4-5"      # tester, implementer, verifier, publisher, closer
balanced  = "claude-sonnet-4-6"     # fallback for unknown role strings

[memory]
session_dir  = ".bonfire/sessions"
context_file = ".bonfire/context.json"

[git]
auto_branch          = true
auto_commit_on_green = true
require_pr           = true
```

The `[models]` section holds the strings Bonfire passes verbatim to
the agent backend. To use a different provider, swap the strings to
that provider's model identifiers and plug in a matching
`AgentBackend` (see Extension Points below).

## Per-Role Model Routing

`resolve_model_for_role(role, settings) -> str` is the public
primitive. Given a role string (canonical or gamified) and a
`BonfireSettings`, it normalizes the input, looks up the canonical
`AgentRole`, maps that role to a `ModelTier`, and returns the
provider model string for that tier from `settings.models`.

The default role-to-tier mapping:

| `AgentRole`     | `ModelTier`  |
| --------------- | ------------ |
| `researcher`    | `reasoning`  |
| `tester`        | `fast`       |
| `implementer`   | `fast`       |
| `verifier`      | `fast`       |
| `publisher`     | `fast`       |
| `reviewer`      | `reasoning`  |
| `closer`        | `fast`       |
| `synthesizer`   | `reasoning`  |
| `analyst`       | `reasoning`  |

If the input string matches neither a canonical `AgentRole` nor a
gamified alias, the resolver falls back to `ModelTier.BALANCED` and
returns `settings.models.balanced`. The function never raises on a
string input — unknown roles degrade to the balanced model rather
than failing the dispatch.

## Personality (Optional)

Bonfire ships persona-driven CLI output. The persona affects
**display only** — it never enters agent prompts and never changes
quality standards. The cadre is what runs; the persona is what
speaks.

The default persona for `v0.1.0a2` is **Falcor** — gentle,
encouraging, warm. The friend who tells you not to let it
end.[^falcor] Falcor narrates pipeline events, greets you on
`bonfire scan`, and names lifecycle moments of the Vault.

Two other personas ship for users who want neutral output:
`default` (professional) and `minimal` (terse, CI-friendly).

```bash
# Inspect installed personas
bonfire persona list

# Switch the default for this project (writes to bonfire.toml)
bonfire persona set default

# Override per command without changing config
bonfire scan --persona minimal
```

Custom personas live in `~/.bonfire/personas/`. The persona slot is
user-extensible: name your own assistant, write a phrase bank, drop
it in the directory.

A breadcrumb: Falcor refactors a slot earlier occupied by a
predecessor named Passelewe. History is sacred — see
`docs/_lore/passelewe.md` if you want the lineage.

[^falcor]: Yes, that Falcor — the luckdragon, *The Neverending Story* (1984).

## Extension Points

Four `@runtime_checkable` Protocols define Bonfire's pluggable
boundaries. The composition root verifies conformance at registration
time, so any object with the matching shape works — no inheritance
required.

```python
from typing import Protocol, runtime_checkable

from bonfire.protocols import (
    AgentBackend,
    DispatchOptions,
    QualityGate,
    StageHandler,
    VaultBackend,
    VaultEntry,
)
```

**`AgentBackend`** — swap the LLM provider that executes a single
agent turn.

```python
@runtime_checkable
class AgentBackend(Protocol):
    async def execute(
        self, envelope: Envelope, *, options: DispatchOptions
    ) -> Envelope: ...
    async def health_check(self) -> bool: ...
```

**`VaultBackend`** — swap the persistent knowledge store. Embedding
is internal to the backend; callers pass text, never vectors.

```python
@runtime_checkable
class VaultBackend(Protocol):
    async def store(self, entry: VaultEntry) -> str: ...
    async def query(
        self, query: str, *, limit: int = 5, entry_type: str | None = None
    ) -> list[VaultEntry]: ...
    async def exists(self, content_hash: str) -> bool: ...
    async def get_by_source(self, source_path: str) -> list[VaultEntry]: ...
```

**`QualityGate`** — custom pass/fail logic between pipeline stages.

```python
@runtime_checkable
class QualityGate(Protocol):
    async def evaluate(
        self, envelope: Envelope, context: GateContext
    ) -> GateResult: ...
```

**`StageHandler`** — custom stage orchestration when an agent
dispatch is the wrong shape (parallel fan-out, human-in-the-loop,
external APIs).

```python
@runtime_checkable
class StageHandler(Protocol):
    async def handle(
        self,
        stage: StageSpec,
        envelope: Envelope,
        prior_results: dict[str, str],
    ) -> Envelope: ...
```

The full persistent Vault knowledge-graph implementation lands in a
later 0.1.x release. The protocol is stable today; the in-memory
default backend ships today and a LanceDB-backed implementation is
available behind the `bonfire-ai[knowledge]` extra.

## What's Not There Yet

Honest list, because alpha means alpha:

- **There is no `bonfire run` command.** The library works —
  `from bonfire.engine import PipelineEngine` and `await engine.run(plan)`
  drives a real pipeline against a real backend — but the CLI verb
  that wires the engine end-to-end is deferred to `v0.1.1`. The
  shipped subcommands (`init`, `scan`, `status`, `resume`,
  `handoff`, `persona`, `cost`) cover onboarding, persona, and cost;
  `status` / `resume` / `handoff` print one-line stubs for now.
- **The bundled prompt-template directory ships a `.gitkeep` and
  nothing else.** The cadre's prompt-layer identity is
  contributor-supplied today. Default identity blocks for the
  LLM-dispatching roles (Scout, Knight, Warrior, Wizard) come in a
  later 0.1.x release.
- **The persistent Vault knowledge-graph is not yet shipped.** The
  `VaultBackend` Protocol is stable and an in-memory default backend
  ships today (substring matching, no embeddings); the
  knowledge-graph storage and query implementation lands once the
  schema is locked.
- **No downstream surface imports the package today.** Wrappers and
  vertical surfaces are designed against the engine but not yet
  wired to it. The release-gate Box validates the artifact contract,
  not the orchestration capability.

The `v0.1.0aN` alpha series reserves the name on PyPI and ships the
frame. Later 0.1.x releases ship the verb, the bundled prompt
templates, and the persistent Vault knowledge-graph. The under-claim
is the feature.

## Roadmap

What's coming next, in rough order:

- **`bonfire run`** — the CLI verb that drives the engine end-to-end.
  Deferred to `v0.1.1`.
- **Bundled prompt-template identity blocks** for the four
  LLM-dispatching cadre roles.
- **Persistent Vault knowledge-graph** — the durable storage and
  query implementation behind the `VaultBackend` Protocol (today's
  default is in-memory; LanceDB is available behind the
  `bonfire-ai[knowledge]` extra).
- **Multi-forge support** via the Instruction Set Markup (ISM) seam —
  declarative third-party tool integrations replacing today's
  hard-coded `gh`-only forge calls.
- **Additional public products** — Bonfire is the first; more open
  repos will follow.

## Project

Bonfire is developed at [github.com/BonfireAI](https://github.com/BonfireAI).
Issues, PRs, and discussion welcome.

## License

Apache-2.0.
