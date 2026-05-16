# Bonfire

**Your Claude Code, opinionated.**

Pip-install Bonfire and your CLI becomes a build partner that knows
you, shaped by every conversation. The first time you run `/bonfire
scan`, it asks what you want to call it.

[![PyPI](https://img.shields.io/pypi/v/bonfire-ai.svg)](https://pypi.org/project/bonfire-ai/)
[![Python](https://img.shields.io/pypi/pyversions/bonfire-ai.svg)](https://pypi.org/project/bonfire-ai/)
[![License](https://img.shields.io/pypi/l/bonfire-ai.svg)](https://github.com/BonfireAI/bonfire/blob/main/LICENSE)

> ### v1.0.0 — the opinion package for Claude Code
>
> Bonfire ships as a `pip install` that drops two things into your
> environment: a Python runtime, and a Claude Code skill. After a
> one-time `bonfire install-skill`, your Claude Code session learns
> `/bonfire scan` and the rest of the conversational surface. No
> separate window, no extra process — the conversation happens inside
> the editor you're already in. Bring your own provider key.
>
> If something bites, file it at
> [github.com/BonfireAI/bonfire/issues](https://github.com/BonfireAI/bonfire/issues).
> The vocabulary, the protocols, and the config schema are stable.

---

## What Bonfire Is

You don't start with Bonfire and stay the same. The first time you run
`/bonfire scan`, it asks what you want to call it. You name it. From
then on, every decision you make becomes part of how it understands
you — your trade-offs captured in your `bonfire.toml`, your nine-role
cadre under whatever names you give them, your priorities recorded in
your persona. Like reading *The Neverending Story*: the more you
engage, the more the narrative becomes yours.

For flow coders — people who think in systems, who understand craft —
the point is to stay in the deep state. Nine role-bound voices (your
researcher, your tester, your implementer, your reviewer, and five
others) dispatch as Claude Code subagents while you talk. Conversation
is the interface. Configuration is what the conversation produces.
No external surfaces, no context switching, no friction between
thinking and shipping.

The discipline is structural, not advisory. The role that writes
failing tests cannot edit implementation. The role that writes
implementation cannot edit tests. The reviewer is read-only. Source
code is the deliverable.

## Quick Start

Three things to do before your first scan:

```bash
# 1. Install the package. The PyPI distribution is `bonfire-ai`;
#    the installed console script is `bonfire`. Python 3.12+.
pip install bonfire-ai

# 2. Set your provider key. Bonfire dispatches to Claude via the
#    Anthropic SDK — without ANTHROPIC_API_KEY the first scan fails
#    with a cryptic SDK error. Set it in your shell before you scan.
export ANTHROPIC_API_KEY=sk-ant-...

# 3. Install the Claude Code skill. This copies the bundled
#    SKILL.md to ~/.claude/skills/bonfire/ so Claude Code learns
#    `/bonfire scan` and the rest of the in-chat surface. Re-running
#    is safe; it refuses to overwrite a divergent local copy
#    without `--force`.
bonfire install-skill
```

Now open Claude Code in your project and ask it:

```
> /bonfire scan
```

Bonfire reads your repo, asks you a handful of questions, and writes
the config. See [Your First Scan](#your-first-scan) below for the
shape of the conversation.

### Shell-side companion verbs

A small set of subcommands also work directly from the shell — useful
in CI, scripts, or when you want to peek at state without opening a
Claude Code session.

```bash
# Scaffold a project from the shell (Claude-Code-free path). Creates
# four artefacts under the target directory:
#   - bonfire.toml (project config; minimal stub `[bonfire]`)
#   - .bonfire/ (per-project state directory)
#   - agents/ (role-local prompt + identity-block overrides; see
#     Extension Points)
#   - .gitignore entry: `.bonfire/tools.local.toml` (appended if
#     missing; idempotent — re-running does not duplicate the line)
bonfire init .

# Inspect cumulative cost and recent sessions.
bonfire cost

# List installed personas.
bonfire persona list

# Switch the active persona for this project (writes to bonfire.toml).
bonfire persona set default
```

Available subcommands in v1.0.0: `init`, `scan`, `install-skill`,
`status`, `resume`, `handoff`, `persona`, `cost`. Run `bonfire --help`
for the full surface or `bonfire <command> --help` for any single
command.

**Stub caveat.** `bonfire status`, `bonfire resume`, and
`bonfire handoff` ship as one-line stubs in v1.0.0; the full
implementations land in a later 0.1.x release. Use them as
placeholders only — they print a marker and exit.

**Legacy onboarding path.** `bonfire scan` from a shell still launches
the alpha-era Front Door (a local browser auto-opens by default; pass
`--no-browser` for headless). That path is the deprecated alpha
onboarding surface and is preserved for users who have not yet
installed the Claude Code skill. The opinionated v1.0.0 front door is
`/bonfire scan` from inside Claude Code; see
[`docs/scan-front-door-protocol.md`](docs/scan-front-door-protocol.md)
for the legacy protocol if you need it.

## Your First Scan

From inside Claude Code:

```
> /bonfire scan
```

Bonfire reads your repo first — language, frameworks, what's already
in `.bonfire/` if anything — then starts asking.

```
> what do you want to call me?
you: Cinder

> what do you want to ship next?
you: a tested refactor of the checkout endpoint

> what should your researcher focus on first?
you: the data path, then the error handling

> anything off-limits? credentials, secrets, prod databases?
you: yes — never touch the live db
```

When the conversation completes, `bonfire.toml` and `.bonfire/` are
written. Your cadre is configured.

## Architecture Overview

A Bonfire pipeline is an ordered sequence of stages. Each stage
dispatches an agent of a specific `AgentRole` (researcher, tester,
implementer, verifier, publisher, reviewer, closer, synthesizer,
analyst). Between stages, `QualityGate` instances inspect the
envelope and decide whether to proceed, retry once, or stop.

The TDD contract is enforced at the role boundary: your **tester**
writes failing tests that define the contract (RED), your
**implementer** writes code to pass them (GREEN), and your
**verifier** runs an independent quality check before your
**publisher** opens a PR. Your **reviewer** can bounce work back
into the loop until it passes or the budget is exhausted. Your
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
the gamified display name. The persona you pick chooses how each role
is named in your CLI output; if you author a custom persona, every
role can wear whatever name you give it.

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
trust_project_settings = false      # opt-in: ingest CLAUDE.md / .claude/ (see Security)

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

### Trusting Project Settings (security)

Bonfire dispatches agents with the Claude Agent SDK, which can ingest
the project's `CLAUDE.md` and `.claude/settings.json` into the agent's
system prompt and hook table. Bonfire defaults to **deny**: a foreign
repo's project settings are NOT loaded unless one of these holds:

- `bonfire.toml` contains `[bonfire] trust_project_settings = true`
  (literal boolean — strings and ints are ignored).
- The environment variable `BONFIRE_TRUST_PROJECT_SETTINGS=1` is set
  (operator escape hatch, strict equality on the value `"1"`).
- The dispatch `cwd` is empty / `None` (in-tree dogfood path).

Why this matters: a malicious clone could otherwise plant instructions
in its `CLAUDE.md` or wire hostile hooks in `.claude/settings.json`
that would silently land in any agent you dispatch from inside that
repo. Opt-in is required.

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

The default persona for v1.0.0 is **Falcor** — gentle, encouraging,
warm. The friend who tells you not to let it end.[^falcor] Falcor
narrates pipeline events, greets you on `/bonfire scan`, and names
lifecycle moments of the Vault.

Two other personas ship for users who want neutral output:
`default` (professional) and `minimal` (terse, CI-friendly).

```bash
# Inspect installed personas
bonfire persona list

# Switch the default for this project (writes to bonfire.toml)
bonfire persona set default
```

The persona is configured per project via `bonfire persona set <name>`;
there is no per-command override flag in v1.0.0. A per-command
override lands when the narration/output layer grows persona awareness
in a later 0.1.x release.

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

Honest list:

- **There is no `bonfire run` command.** The library works —
  `from bonfire.engine import PipelineEngine` and `await engine.run(plan)`
  drives a real pipeline against a real backend — but the CLI verb
  that wires the engine end-to-end is deferred to a 0.1.x release.
  The shipped subcommands (`init`, `scan`, `install-skill`,
  `status`, `resume`, `handoff`, `persona`, `cost`) cover onboarding,
  skill install, persona, and cost; `status` / `resume` / `handoff`
  print one-line stubs for now.
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

Later 0.1.x releases ship the verb, the bundled prompt templates, and
the persistent Vault knowledge-graph. The under-claim is the feature.

## Roadmap

What's coming next, in rough order:

- **`bonfire run`** — the CLI verb that drives the engine end-to-end.
- **In-chat parity for every CLI verb.** v1.0.0 ships `/bonfire scan`
  as the primary conversational surface; the other verbs gain
  in-chat skill mappings in later 0.1.x releases.
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
