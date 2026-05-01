# Release Gates — Bonfire v0.1

Discipline for what lands on `main`, what tags a release, and what reaches the public. This document IS the protocol. Changes require a PR.

## Why this exists

Bonfire is a **transfer target**, not a greenfield build. Wave 2–10 lifts hardened pieces from the internal engine into this repository. The gate catches *transfer errors* — missed imports, broken wiring, packaging drift, composition-root bugs that unit tests miss — before they reach users.

During v0.1 development the repository is **private**. We flip public when v0.1.0 ships clean through the release gate. The flip is reversible.

## Tiers

Every wave closes with a gate-tier declaration in its close-PR. The Wizard picks the tier based on what the wave actually enabled — not on a predicted schedule.

| Tier | When | Required signal |
|------|------|-----------------|
| **Infra** | Waves 2–3 (transfers, no runnable pipeline) | Unit tests green + Wizard + code-reviewer |
| **Integration** | Waves 4–5 (scaffolding, partial pipeline) | Infra + integration tests green |
| **E2E** | Waves 6+ (runnable `bonfire run`) | Integration + **box E2E PASS verdict** |
| **Release** | v0.1.0 tag + re-publish | E2E + every README example executable + re-publish checklist |

## Reviewer cadence

Every PR into `v0.1` requires **both**:

- **Wizard** — Ishtar, the prompt architect. Standard dispatch review.
- **code-reviewer** — superpowers agent. Independent lens.

Two-lens review is non-negotiable. Drift happens when the same voice reviews the same work.

## The E2E box

### Substrate

`ubuntu:24.04` Docker container. **Local execution only.** Never runs in CI.

Rationale: API key stays on Anta's machine. Cost is observable in real time. No unattended runs draining the key. Pop!_OS 24.04 is Ubuntu-flavored, so box behavior mirrors host.

### Contents

- `git`, `curl`, `ca-certificates`, `build-essential`
- `python3.12` + `python3.12-venv`
- Node.js 20 (via NodeSource)
- `@anthropic-ai/claude-code` (npm global) — the universal test surface

### Flow

1. Host invokes `tests/e2e/scripts/e2e-box.sh <wave>`.
2. **Host clones the fixture into `.e2e-runs/<run-id>/target/` via SSH.** Credentials stay on the host.
3. Container launches with `ANTHROPIC_API_KEY` from host `.env`, output dir mounted at `/workspace/out`, and the fixture bind-mounted read-write at `/workspace/target`.
4. Claude CLI receives the fixture prompt: install `bonfire-ai`, scan, then use the package as a library to fix the broken test and emit Bonfire-shaped artifacts (cost log, session log, branch with bard-pattern naming, review-verdict JSON). v0.2 swaps the library-use prompt for an end-to-end `bonfire run` invocation once the `pipeline` command module ships per the public-port plan.
5. Claude operates as a library client of `bonfire-ai`: it reads the package's source, applies its components, and emits the artifacts the gate expects. v0.1 ships the artifact contract; v0.2 swaps in the full pipeline.
6. Post-run: diff filter + pytest + verdict JSON emission via the fixture's `gate/check-verdict.sh`.
7. Verdict written to host at `.e2e-runs/<run-id>/verdict.json`.
8. Both review lenses (Wizard + code-reviewer) read the verdict. Maintainer signs the merge.

*Security properties:*

- *Filesystem (enforced): the container has no host filesystem access beyond two bind-mounts: the cloned fixture worktree (`/workspace/target`, read-write) and the host output directory (`/workspace/out`, read-write). The host machine, the operator's git credentials, and any other repo on disk are unreachable.*
- *GitHub credentials (enforced): no SSH key, no `gh` CLI, no `GITHUB_TOKEN` enters the container. The fixture is cloned on the host before `docker run` and bind-mounted in. Any remote PR push happens on the host after verdict capture.*
- *Network egress (by-trust today): the container's only network-active processes are `claude-cli` (pinned to `@anthropic-ai/claude-code@2.1.123`) and `pip install`. Both are trusted to reach only `api.anthropic.com` + PyPI mirrors. The default Docker bridge network does not enforce this; a v0.2 follow-up will add a `DOCKER-USER` iptables allowlist following Anthropic's reference devcontainer pattern.*

### CLI-as-universal-surface

If the box passes, every downstream Bonfire consumer (IDE integration, direct API, future platforms) inherits the proof — they compile to the same tool-use protocol. We only need to guarantee one fidelity.

## Fixture — `BonfireAI/bonfire-e2e-fixture`

Private repo, separate substrate. A small Python project with a deliberately broken test.

### Anti-cheat rules (mechanical, not moral)

Enforced by `gate/check-verdict.sh` inside the fixture:

1. `tests/` directory MUST be untouched.
2. `src/` directory MUST be modified.
3. The one named broken test MUST pass post-run.
4. All other tests MUST remain green.
5. A PR branch MUST be created with canonical naming.
6. `.bonfire/costs.jsonl` MUST exist and be valid JSONL.
7. Review Agent's verdict JSON MUST be in the artifacts.

All seven true → PASS. Any false → FAIL. No judgement calls.

## Verdict artifact

Schema: `tests/e2e/schemas/verdict.schema.json` (JSON Schema Draft-07).

The schema IS the contract. To tighten the bar, add an assertion to the schema and the gate re-validates. The schema is the reverse-spec of what v0.1 guarantees — if a capability is required to emit the verdict, that capability must ship in v0.1.

## Cost logging (Fork C for v0.1)

v0.1 ships the minimum viable:

- Per-agent-dispatch line in `.bonfire/costs.jsonl`.
- Stdout summary at the end of `bonfire run`.

Throttle, budget caps, and full configuration module defer to **v0.2** (see BON-204 epic in the internal tracker).

## API key handling

- `ANTHROPIC_API_KEY` lives in gitignored `.env` on the host.
- Passed to the container via `docker run --env-file .env`.
- **Never** baked into the image.
- **Never** committed.

## claude-cli bump policy

The `@anthropic-ai/claude-code` package is pinned in `tests/e2e/Dockerfile`. Floating to `@latest` means an upstream flag rename or auth-flow change can silently break the gate the morning of a release tag. Pinning is the discipline.

When bumping the pinned version:

1. Run two box runs (current pin + candidate pin) on the same fixture-ref. Both must PASS.
2. Update `tests/e2e/Dockerfile` and this file (the bump policy section) in the same PR.
3. Cite the upstream CHANGELOG link in the PR body, calling out any flag renames or behavior changes.
4. Both review lenses approve before merge.
5. After merge, file a one-line note in the project's release notes capturing the new pin.

A minimum-version constraint (e.g. `@>=2.1.0`) is **not** an acceptable substitute. Either pin or float; no half-measures.

## Re-publish checklist (flip back public at v0.1.0)

- [ ] All waves closed through the release tier.
- [ ] v0.1.0 tag commit passes the full box E2E.
- [ ] Every `README.md` example executable in a fresh box.
- [ ] `CHANGELOG.md` cut and accurate.
- [x] Commit history audited — leaked internal-tracker references in pre-v0.1.0 commit subjects accepted as historical for v0.1.0; new commits comply per [CONTRIBUTING.md](../CONTRIBUTING.md). See [CHANGELOG.md](../CHANGELOG.md) `[0.1.0]` Notes section.
- [ ] License headers consistent across `src/`.
- [ ] `CONTRIBUTING.md` re-read against current reality.
- [ ] `pip install bonfire-ai==0.1.0` works in a fresh venv.
- [ ] `gh repo edit BonfireAI/bonfire --visibility public`.
- [ ] PyPI release uploaded (v0.1.0 — not alpha).
- [ ] `v0.1` branch deleted.
- [ ] `v0.2` branch cut from main.

## Rollback

If strategy shifts — a demo window, a security researcher reach-out, unforeseen need — `gh repo edit BonfireAI/bonfire --visibility public` reverses the private flip in seconds. Not a one-way door. Discipline, not the visibility state, is the gate.

## Release train lifecycle

```
main (tagged 0.1.0)
  └── v0.1 integration branch
        └── antawari/bon-<n>-* feature branches → PR into v0.1
v0.1 fully green → merge v0.1 to main → tag v0.1.0 → delete v0.1 → cut v0.2
```

Each release cycle gets a fresh integration branch. Branches are disposable. The discipline persists.
