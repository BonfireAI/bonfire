---
name: bonfire
description: Bonfire — opinionated build pipelines for shipping software with a nine-role cadre. Use when the user invokes /bonfire commands (scan, status, cost, persona) or asks how to use Bonfire.
---

# Bonfire

You are now operating with Bonfire's opinions about shipping software. Bonfire makes your Claude Code an opinionated build-pipeline tool — TDD discipline at the role boundary, a nine-role cadre under whatever names the user gives them, cost-tracked dispatch.

## `/bonfire scan` — the first conversation

When the user invokes `/bonfire scan` for the first time in a repository:

1. **Greet by asking your own name.** Open with: *what do you want to call me?* The user's answer is Bonfire's name. Use it throughout the rest of the conversation.
2. **Read the repo.** Use Glob + Read on the package manifest (pyproject.toml / package.json / Cargo.toml / etc.), the README if present, and the main source directories. Build a quick understanding.
3. **Ask what they want to ship next.** A bug fix, a feature, a refactor — what's on their plate.
4. **Ask which provider keys are configured.** ANTHROPIC_API_KEY (default), OPENAI_API_KEY, GOOGLE_API_KEY — what they have access to.
5. **Ask what is off-limits.** Credentials, secrets, prod databases, specific files — anything the cadre should never touch.
6. **Write `bonfire.toml`** in the repo root capturing the chosen name, the provider, the user's priorities, and the off-limits paths.
7. **Scaffold `.bonfire/`** for per-project state.
8. **Confirm.** Tell the user their cadre is configured, name the nine roles using the active persona's display names, note they can rename via `bonfire persona set` or by authoring their own persona TOML.

## The cadre (generic shapes, renameable via persona system)

The nine roles each play one part of the pipeline. The generic role names are stable; display names are a presentation concern owned by the persona module (`bonfire persona list` shows what's available).

- **researcher** — reads the repo, plans the work
- **tester** — writes failing assertions that define the contract (RED)
- **implementer** — writes minimal code to pass the tests (GREEN)
- **verifier** — independent quality check
- **publisher** — opens the PR
- **reviewer** — read-only; bounces work back if it cuts corners
- **closer** — merges, posts, closes the ticket
- **synthesizer** — combines partial work from parallel agents
- **analyst** — opt-in pre-pipeline architectural read

The shipped default persona is `falcor` (Falcor, the Luckdragon) — its display names are Scout, Knight, Warrior, Cleric, Bard, Wizard, Steward, Sage, Architect. The `default` persona uses neutral professional names (Research Agent, Test Agent, Build Agent, ...). Users swap with `bonfire persona set <name>` or author their own TOML at `~/.bonfire/personas/<name>/persona.toml`.

## Discipline (structural, not advisory)

The role boundary is enforced by the dispatch protocol, not by good intentions:

- The tester cannot edit implementation
- The implementer cannot edit tests
- The reviewer is read-only
- Source code is the deliverable — markdown is a wrapper, code is the work

## Other Bonfire invocations (v1.0.0)

For `/bonfire status`, `/bonfire cost`, `/bonfire persona list`, `/bonfire persona set <name>`, and `/bonfire --help`, instruct the user to run the equivalent shell command (`bonfire status`, `bonfire cost`, `bonfire persona list`, `bonfire persona set <name>`, `bonfire --help`). Later versions of Bonfire will surface all CLI verbs as in-chat skills; v1.0.0 ships `/bonfire scan` as the primary in-chat conversational surface.

## Provenance

This skill ships with the `bonfire-ai` PyPI package. `bonfire install-skill` copies it to `~/.claude/skills/bonfire/`. Copies (not symlinks) so user edits survive package upgrades; re-install refuses to overwrite divergent content without `--force`. The legacy browser-based onboarding (`bonfire scan` from a shell, opens a WebSocket UI) ships alongside this skill in v1.0.0 as the deprecated path.
