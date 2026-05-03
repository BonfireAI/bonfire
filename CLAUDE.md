# Bonfire — Public Tree (v0.1)

The public PyPI ship surface for Bonfire. This is `BonfireAI/bonfire` on GitHub —
the Apache-2.0 framework that defines agents, wires stages, and ships quality. This
file is the repo-local constitution: every agent dispatch, every contributor PR, and
every release operation against this tree starts here. Read it before you touch
code, open a PR, or tag a release. The reader may be a returning maintainer, an
external Apache-2.0 contributor, or a fresh-boot AI agent session that has never
seen this repo before; everything below assumes nothing.

## Architecture

The authoritative shape of this codebase lives in
[`docs/architecture.md`](docs/architecture.md) — read it before building. Bonfire
is a pipeline of role-bound agents over a typed event bus: each stage has an agent
that plays a specific role; each stage emits typed events; cross-cutting observers
(cost, session, knowledge, display) subscribe without ever calling stages back.

Supporting files:

- [`docs/architecture.md`](docs/architecture.md) — module map and pipeline flow (read first)
- [`docs/adr/`](docs/adr/) — Architecture Decision Records, with ADR-001 binding the naming vocabulary
- [`docs/release-policy.md`](docs/release-policy.md) + [`docs/release-gates.md`](docs/release-gates.md) — what blocks a v0.1.0 tag
- [`docs/audit/sage-decisions/`](docs/audit/sage-decisions/) — design decisions that produced today's contracts

## Tech Stack

- Python 3.12+ with venv (ALWAYS use venv, never global pip)
- Claude Agent SDK for agent execution (default backend)
- Pydantic for schemas and validation; frozen models for cross-package contracts
- Typer for CLI (sync commands, `asyncio.run()` at boundary)
- Rich for terminal output
- TOML for configuration; YAML for configurations that need human-edit ergonomics
- Jinja2 for prompt templating
- pytest + pytest-asyncio (`asyncio_mode = "auto"`) for testing
- Ruff for lint + format
- hatchling for packaging (src layout)

Optional knowledge backend (extra dependency `bonfire-ai[knowledge]`): LanceDB +
Ollama for local vector search.

## TDD Is the Law

- Tests come first. The test file defines the contract; implementation passes it.
- Test authors and implementation authors should not be the same author within a
  single change — the contract gets weaker when one hand writes both.
- Implementation NEVER modifies test files.
- Commit after every green phase.
- Feature branches + PRs. Never commit to `main` or `v0.1` directly.

## Virtual Environment

ALWAYS activate the venv. System Python on most modern Linux distributions
(Pop!_OS, Ubuntu 23.04+, Fedora) is PEP 668-protected — `pip install` against the
system interpreter fails by design. Bonfire is built and tested only inside a venv.

```bash
source .venv/bin/activate
# OR prefix commands: .venv/bin/python, .venv/bin/pytest, .venv/bin/ruff
```

All commands below assume the venv is active.

For first-time setup:

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

## ADR-001 Naming Vocabulary

Bonfire uses a three-layer naming system. Code uses generic identifiers everywhere;
display names are a presentation concern. The full decision lives in
[`docs/adr/ADR-001-naming-vocabulary.md`](docs/adr/ADR-001-naming-vocabulary.md) —
read it before adding a role, renaming a module, or writing user-facing copy.

The three layers:

1. **Generic (code).** Python identifiers, config keys, serialized data. Used in
   every `.py` file. Example: `AgentRole.RESEARCHER`.
2. **Professional (default display).** CLI output, docs, website. Self-explanatory
   without a glossary. Example: `Research Agent`.
3. **Gamified (opt-in display).** Forge-themed personality via `--persona forge`.
   Example: `Scout`.

The `persona` module owns generic-to-display translation. **Code never uses display
names.** A full agent-role table (9 roles × 3 layers) lives in
[`docs/adr/ADR-001-naming-vocabulary.md`](docs/adr/ADR-001-naming-vocabulary.md)
lines 31–40 and in [`CONTRIBUTING.md`](CONTRIBUTING.md) lines 71–80. This file
does not duplicate the table; it cites both.

### Module Renames From the Private Codebase

The public tree uses different module names than Bonfire's internal v1 codebase.
When porting code or referencing modules, use the public column — never the v1
column. The full rename table with rationale is at
[`docs/adr/ADR-001-naming-vocabulary.md`](docs/adr/ADR-001-naming-vocabulary.md)
lines 44–51. Inline summary:

| Public (use this) | Private v1 (do NOT use) | Module purpose |
|---|---|---|
| `knowledge/` | `vault/` | Knowledge backend (in-memory, LanceDB) |
| `cost/` | `costs/` | Per-dispatch cost ledger |
| `workflow/` | `workflows/` | Pre-built workflow plans |
| `analysis/` | `cartographer/` | Code-graph studies |
| `onboard/` | `front_door/` | Browser-based onboarding |
| `scan/` | `scanners/` | Project-state scanners |

Selective class renames (full table in ADR-001 lines 53–61): `IdentityBlock` (was
`AxiomMeta`), `ProjectAnalysis` (was `ProjectStudy`), `WorkflowSpec` (was
`WorkflowPlan`), `PhraseBank` (was `PhrasePool`), `TechScanner` (was
`TechFingerprinter`).

When in doubt: read ADR-001. The ADR is the binding contract; this section is the
boot-time summary so a fresh-boot session sees the public-tree names without
leaving this file.

## Canon Awareness

Before any commit that touches canonical vocabulary — tier names, agent roles, claim counts (the Four Claims), palette names, mascot names (CHUNK), voice rules — consult **THE CANON**:
<https://linear.app/bonfire-codeforge/document/the-canon-source-of-truth-for-all-surfaces-331e401a0fbf>

bonfire-public is a customer-facing PyPI ship surface; canonical drift here propagates to every install. The Canon wins on contradiction — consult it before any change to canonical vocabulary, and never paraphrase or rename without amending Canon first. ADR-001's three-layer naming vocabulary (`knowledge/`, `cost/`, `workflow/`) is part of the Canon's surface-level vocabulary.

## Agent Commit Protocol

Every agent role (test author, implementer, synthesizer, publisher, reviewer)
MUST follow this sequence before committing:

```bash
# 1. Run tests
pytest tests/ -x

# 2. Stage specific files FIRST (never git add -A blindly)
git add src/bonfire/cost/ledger.py tests/unit/test_cost_ledger.py
# (example uses public-tree module name `cost/` — singular per ADR-001)

# 3. Auto-fix lint — ONLY on files you changed (prevents collateral noise)
git diff --name-only --cached | xargs ruff check --fix
git diff --name-only --cached | xargs ruff format

# 4. Verify clean — full tree (catches transitive issues)
ruff check src/ tests/
ruff format --check src/ tests/

# 5. If ruff fails on YOUR files: fix manually, re-run pytest
# 6. If ruff fails on OTHER files: do NOT fix them. File an issue.

# 7. Re-stage after ruff fixes, then commit
git add -u
git commit -m "<short, imperative summary>"
```

The ruff step is NOT optional. The scoped fix + full verify pattern prevents
agents from creating noisy diffs when one targeted change accidentally re-formats
neighboring files.

Common ruff rules to watch:

- `I001` — import block unsorted
- `E501` — line too long (>100 chars per `pyproject.toml`)
- `UP042` — use `StrEnum` instead of `(str, Enum)`
- `F401` — unused import

CI on every push and PR runs `pytest`, `ruff check`, and `ruff format --check`
per [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Run them locally
before opening a PR — green-locally is the floor, not the ceiling.

Commit messages use the imperative mood ("add cost ledger append test", not
"added cost ledger append test"). No internal-tracker IDs in commit messages or
PR descriptions on this repo (see [`CONTRIBUTING.md`](CONTRIBUTING.md) lines
134–137).

## Worktree Merge Protocol

When parallel agents complete work in worktrees, the merging session uses
`git checkout` — NOT cherry-pick:

```bash
# Create feature branch from the integration branch (v0.1 during pre-release)
git checkout v0.1 -b your-name/wave-N-feature

# For each agent's worktree branch, checkout their files
git checkout worktree-agent-XXXX -- src/bonfire/<path>/<files>.py tests/unit/<test_files>.py
git checkout worktree-agent-YYYY -- src/bonfire/<other>/<files>.py tests/unit/<other_tests>.py

# Verify
pytest tests/ -x
ruff check src/ tests/

# Single commit with all files
git add -A && git commit -m "Wave N: description (synthesized from agents)"
```

Why NOT cherry-pick:

- Cherry-picks can land on the wrong branch when cwd is inside a worktree
- Cherry-picks tangle branches with unrelated commits
- Cherry-picks can miss files when packages have only `__init__.py` staged
- `git checkout branch -- files` is deterministic: each file comes from exactly
  one source

The integration branch for v0.1 development is `v0.1`. Once v0.1.0 ships and the
release flips public, the integration branch for v0.2 is cut from `main`.

## Worktree Rules

- ALL parallel agents MUST use worktree isolation
- Agents MUST use ONLY relative paths in worktrees (absolute paths bypass isolation)
- Clean up worktree branches after wave completion
- Only the published feature branch survives
- The repo's `.claude/worktrees/` directory is gitignored — worktrees there are
  ephemeral

## Conventions

- `src/bonfire/` — source package (hatchling, src layout per `pyproject.toml`)
- `tests/unit/` — flat test files (`test_<module>.py`)
- `tests/integration/` — broader tests; deterministic, no network
- `tests/e2e/` — fixture-driven box runs; LOCAL ONLY, never in CI
- `docs/` — architecture, ADRs, release policy, audit trail
- Envelope + Payload handoff protocol between stages (see
  [`docs/architecture.md`](docs/architecture.md))
- Always set `max_turns` and `max_budget_usd` on agent options
- Return `is_error=True` from tool handlers, never throw
- Use `setting_sources=["project"]` to load this file into SDK agents
- Module roster (per `docs/architecture.md`): `agent/`, `analysis/`, `cli/`,
  `cost/`, `dispatch/`, `engine/`, `events/`, `git/`, `github/`, `handlers/`,
  `knowledge/`, `models/`, `onboard/`, `persona/`, `prompt/`, `scan/`,
  `session/`, `workflow/`, `xp/`. ADR-001 binds the naming.
- Cross-platform: no Linux-only assumptions. Use `pathlib` and portable
  libraries; Python 3.12+ on every supported OS (Linux, macOS, Windows).

## Release Policy and Gates

`bonfire-ai` is in pre-release (`0.1.0a1` alpha at the time of this writing).
The original `0.1.0` tag shipped on 2026-04-28; the alpha label is restored
to honestly reflect that release-gate items remain open. The full pre-release
rules live in
[`docs/release-policy.md`](docs/release-policy.md); release-gate discipline lives
in [`docs/release-gates.md`](docs/release-gates.md). Read both before tagging
anything.

### Tier ladder (per [`docs/release-gates.md`](docs/release-gates.md) lines 14–21)

| Tier | When | Required signal |
|---|---|---|
| Infra | early waves (transfers, no runnable pipeline) | Unit tests + reviewer |
| Integration | scaffolding waves | Infra + integration tests |
| E2E | runnable `bonfire run` | Integration + box E2E PASS |
| Release | v0.1.0 tag + re-publish | E2E + every README example executable |

### What BLOCKS a v0.1.0 tag

A `v0.1.0` tag is BLOCKED until ALL of:

1. Wave 9.1 E2E smoke tests pass in CI on `main`
   ([`docs/release-policy.md`](docs/release-policy.md) line 39).
2. Wave 9.2 release preparation merged
   ([`docs/release-policy.md`](docs/release-policy.md) line 40).
3. Trust-triangle components on `main`: the four `@runtime_checkable` extension
   protocols (`AgentBackend`, `VaultBackend`, `QualityGate`, `StageHandler`),
   the per-role tool allow-lists with default floor (W4.1), and the default
   security hook set (W4.2). See [`docs/release-policy.md`](docs/release-policy.md).
4. Box E2E PASS verdict on the v0.1.0 tag commit
   ([`docs/release-gates.md`](docs/release-gates.md) line 105).
5. Every README example executable in a fresh box
   ([`docs/release-gates.md`](docs/release-gates.md) line 107).
6. `CHANGELOG.md` cut and accurate
   ([`docs/release-gates.md`](docs/release-gates.md) line 108).
7. Commit-history audit — no leaked internal lore or secrets
   ([`docs/release-gates.md`](docs/release-gates.md) line 109).
8. License headers consistent across `src/`
   ([`docs/release-gates.md`](docs/release-gates.md) line 110).
9. `CONTRIBUTING.md` re-read against current reality
   ([`docs/release-gates.md`](docs/release-gates.md) line 111).
10. `pip install bonfire-ai==0.1.0` succeeds in a fresh venv
    ([`docs/release-gates.md`](docs/release-gates.md) line 112).

Until all ten clear, the version stays alpha (`0.1.0aN`). When all ten clear, the
classifier in `pyproject.toml` advances from `Development Status :: 3 - Alpha`
to `Development Status :: 4 - Beta` and the GitHub release tag `v0.1.0` is
published.

### Box E2E

The release-gate Box is `ubuntu:24.04` with Python 3.12, Node 20, and
`@anthropic-ai/claude-code`. Runs LOCAL ONLY — never in CI; the API key stays on
the operator's machine. Full flow lives in
[`docs/release-gates.md`](docs/release-gates.md) lines 32–62. The fixture is the
private companion repo `BonfireAI/bonfire-e2e-fixture`.

## v0.1 Branch Protection

`v0.1` is the integration branch during pre-release. `main` is the release
branch. Both are protected. Rules:

1. **No direct pushes** to `v0.1` or `main`. All changes ship via PR.
2. **Two-lens review required** before merge:
   - Reviewer agent (the prompt-architect lens; runs against the PR diff, not
     branch files; runs AFTER PR creation, BEFORE merge).
   - `code-reviewer` (independent superpowers lens).
3. **CI must pass:** `pytest`, `ruff check`, `ruff format --check` per
   [`.github/workflows/ci.yml`](.github/workflows/ci.yml). Required status
   checks include all three.
4. **No force-pushes** to `v0.1` or `main`. If a history rewrite is needed,
   file an issue and coordinate.
5. **No deletion** of `v0.1` until `v0.1.0` is cut on `main` and verified by
   Box E2E. Deletion is the final step of the release-train lifecycle
   ([`docs/release-gates.md`](docs/release-gates.md) lines 122–128).
6. **Signed commits** required for `v0.1.0` and later release tags
   ([`docs/release-policy.md`](docs/release-policy.md) lines 60–62).
7. **Branch naming** for feature work: `your-name/short-description`
   ([`CONTRIBUTING.md`](CONTRIBUTING.md) line 124).

Branch-protection settings live in GitHub admin:
<https://github.com/BonfireAI/bonfire/settings/branches>

The repo is private until v0.1.0 ships clean
([`docs/release-gates.md`](docs/release-gates.md) line 9); the flip to public is
reversible ([`docs/release-gates.md`](docs/release-gates.md) line 120).

## For External Contributors

Most contribution flow lives in [`CONTRIBUTING.md`](CONTRIBUTING.md). This
section covers what an AI-agent session needs to know that a human reading
`CONTRIBUTING.md` does not.

### If you are a Claude Code (or other AI-agent) session opening this repo

1. **You may dispatch agents from this repo** using the `claude-agent-sdk`
   dependency. The repo's own `bonfire run` command targets pipelines against
   external code; using the SDK directly inside this repo is a contributor
   pattern, not the framework's primary use case. Use your own
   `ANTHROPIC_API_KEY`.

2. **API key handling.** `ANTHROPIC_API_KEY` lives in a gitignored `.env` (see
   [`docs/release-gates.md`](docs/release-gates.md) lines 96–100). Never commit
   it. Never bake it into a Docker image. The release-gate Box passes the key
   via `docker run --env-file .env`.

3. **Two-lens review applies to external PRs.** Your PR will face a reviewer
   agent (the prompt-architect lens) and `code-reviewer` (independent lens)
   before merge. Address feedback rather than re-arguing.

4. **Naming discipline (ADR-001).** When writing display strings or docs, use
   the professional names (`Research Agent`, `Test Agent`, `Build Agent`, ...)
   or the gamified names (`Scout`, `Knight`, `Warrior`, ...). Code always uses
   the generic `AgentRole` enum values; the `persona` module owns the
   translation. Full table:
   [`CONTRIBUTING.md`](CONTRIBUTING.md) lines 71–80.

5. **No internal-tracker references.** Do not paste internal IDs, project
   codenames, or non-public references into commit messages, code comments, or
   PR descriptions ([`CONTRIBUTING.md`](CONTRIBUTING.md) lines 134–137). The
   maintainers' internal tracker is not visible to outside readers.

6. **Async tests** auto-discover (`asyncio_mode = "auto"` in `pyproject.toml`).
   Do not decorate with `@pytest.mark.asyncio`.

7. **`@pytest.mark.live`** marks tests that require a real API key. They skip
   by default. Add the marker when your test calls a real model.

If a rule in `CONTRIBUTING.md` and a rule in this CLAUDE.md disagree:
`CONTRIBUTING.md` wins for human-contributor concerns; this file wins for
agent-runtime concerns. If they disagree on something fundamental, file an
issue.

## Links Upward

This repo is one of several in the Bonfire constellation. The constellation has
three governance layers above this file:

- **Workspace coordinator:** `/home/ishtar/Projects/CLAUDE.md` (operator-local;
  not in this repo). Defines the multi-repo path-resolution protocol and the
  boot sequence every session runs before this file is read.
- **Forge constitution:** `ishtar/CLAUDE.md` (operator-local; in the `ishtar/`
  repo). Defines the prompt-architect role, the dual-workflow pattern, and the
  Canon Awareness framing this file mirrors.
- **Internal v1 codebase:** `bonfire/CLAUDE.md` (operator-local; in the
  private `bonfire/` repo). The v1 source that this public tree ports from.
  **Module names differ** (per ADR-001 § Module Renames above) — the public
  tree is the source of truth for module naming inside this repo.

External contributors are not expected to read the operator-local files. They
exist for the maintainer's multi-repo workflow. This section documents them so
a fresh-boot agent session knows where its parents are.

For the canonical vocabulary across the public Bonfire surfaces (Free / Website
/ Cyberdeck), see THE CANON:
<https://linear.app/bonfire-codeforge/document/the-canon-source-of-truth-for-all-surfaces-331e401a0fbf>
