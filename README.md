# Bonfire

**AI Build Pipelines for Real Code.** Define agents. Wire stages. Ship quality.

[![PyPI](https://img.shields.io/pypi/v/bonfire-ai.svg)](https://pypi.org/project/bonfire-ai/)
[![Python](https://img.shields.io/pypi/pyversions/bonfire-ai.svg)](https://pypi.org/project/bonfire-ai/)
[![License](https://img.shields.io/pypi/l/bonfire-ai.svg)](https://github.com/BonfireAI/bonfire/blob/main/LICENSE)

> ### Beta — `v0.1.0`
>
> This is the first functional release of `bonfire-ai`. The pipeline
> primitives, BYOK model routing, and `bonfire scan` onboarding are
> wired and exercised by the test suite. Knowledge-graph storage
> ("the vault") and the end-to-end project workflow are still in
> progress and ship in later 0.1.x releases.
>
> If you are an early adopter, run it against a throwaway repo, file
> issues at [github.com/BonfireAI/bonfire/issues](https://github.com/BonfireAI/bonfire/issues),
> and tell us where it bites. The vocabulary, the protocols, and the
> config schema are stable for 0.1.x.

---

## What Bonfire Is

Bonfire runs a pipeline of role-specialized AI agents — researcher,
tester, implementer, verifier, publisher, reviewer, closer — with
quality gates between every stage and TDD discipline (RED → GREEN)
baked into the contract. You bring your own provider key. You pick
the model per role. The framework handles dispatch, isolation, gate
evaluation, and the retry loop. Source code is the deliverable.

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

# Inspect cumulative cost across all sessions
bonfire cost

# List installed personas
bonfire persona list
```

Available subcommands in `v0.1.0`: `init`, `scan`, `status`, `resume`,
`handoff`, `persona`, `cost`. Run `bonfire --help` for the full surface
or `bonfire <command> --help` for any single command.

## Architecture Overview

A Bonfire pipeline is an ordered sequence of stages. Each stage
dispatches an agent of a specific `AgentRole` (researcher, tester,
implementer, verifier, publisher, reviewer, closer, synthesizer,
analyst). Between stages, `QualityGate` instances inspect the
envelope and decide whether to proceed, retry, or abort.

The TDD contract is enforced at the role boundary: the **tester**
writes failing tests that define the contract (RED), the
**implementer** writes code to pass them (GREEN), and the
**verifier** runs an independent quality check before the
**publisher** opens a PR. The **reviewer** can bounce work back
into the loop until it passes or the budget is exhausted.

Models are resolved per role through `resolve_model_for_role`, which
maps each `AgentRole` to a capability tier (`reasoning`, `fast`, or
`balanced`) and returns the corresponding provider model string from
your config. Pure synchronous resolution, never raises on a string
input.

## Naming Glossary

Bonfire ships three vocabularies for the same set of roles. The
**generic concept** is what the role does. The **professional
name** (`AgentRole`) is the canonical serialized form used in TOML,
JSONL, CLI output, and grep patterns. The **gamified name** is a
workflow alias emitted by the standard and research workflow
templates and normalized through `GAMIFIED_TO_GENERIC` before tier
lookup.

| Generic Concept                                   | Professional (`AgentRole`) | Gamified (workflow alias) |
| ------------------------------------------------- | -------------------------- | ------------------------- |
| Investigates the task and gathers context         | `researcher`               | `scout`                   |
| Writes failing tests (TDD RED)                    | `tester`                   | `knight`                  |
| Writes code to pass the tests (TDD GREEN)         | `implementer`              | `warrior`                 |
| Independent quality verification                  | `verifier`                 | `assayer`, `prover`       |
| Creates branches, commits, opens PRs              | `publisher`                | `bard`                    |
| Code review with structured verdicts              | `reviewer`                 | `wizard`                  |
| Merges approved PRs and announces completion      | `closer`                   | `herald`                  |
| Combines multiple reports into unified analysis   | `synthesizer`              | `sage`                    |
| Architectural and structural analysis             | `analyst`                  | `architect`               |

The string `prover` appears in the `standard_build` pipeline as a stage
label; that stage dispatches to the `verifier` role. `Assayer` is the
verifier's only display alias — stage labels name DAG nodes inside a
workflow plan, while display names are the persona-emitted role names
in CLI output.

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
persona = "default"                 # CLI output persona

[models]                            # most-likely-customized — BYOK lives here
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

The `[models]` section is BYOK: Bonfire passes the configured string
verbatim to the agent backend. To use a different provider, swap the
strings to that provider's model identifiers and plug in a matching
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

Bonfire ships with persona-driven CLI output. The persona affects
**display only** — it never enters agent prompts and never changes
quality standards.

```bash
bonfire scan --persona forge
```

Use `bonfire persona list` to see installed personas and
`bonfire persona set <name>` to make a choice persistent in
`bonfire.toml`. Custom personas live in `~/.bonfire/personas/`.

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

The full vault knowledge-graph implementation lands in a later 0.1.x
release. The protocol is stable today; the default backend ships
once the schema is locked.

## Project

Bonfire is developed at [github.com/BonfireAI](https://github.com/BonfireAI).
Issues, PRs, and discussion welcome.

## License

Apache-2.0.
