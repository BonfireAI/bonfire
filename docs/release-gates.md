# Release Gates — Bonfire v0.1

Discipline for what lands on `main`, what tags a release, and what reaches the public. This document IS the protocol. Changes require a PR.

## Why this exists

Bonfire is a **transfer target**, not a greenfield build. Wave 2–10 lifts hardened pieces from the internal engine into this repository. The gate catches *transfer errors* — missed imports, broken wiring, packaging drift, composition-root bugs that unit tests miss — before they reach users.

None of those are catchable by a box that installs the last published release and validates artifacts a prompt handed it. The box installs a wheel built from the working tree and executes it; the verdict names the wheel, the command, and the command's exit code.

During v0.1 development the repository is **private**. We flip public when v0.1.0 ships clean through the release gate. The flip is reversible.

## Tiers

Every wave closes with a gate-tier declaration in its close-PR. The Wizard picks the tier based on what the wave actually enabled — not on a predicted schedule.

| Tier | When | Required signal |
|------|------|-----------------|
| **Infra** | Waves 2–3 (transfers, no runnable pipeline) | Unit tests green + Wizard + code-reviewer |
| **Integration** | Waves 4–5 (scaffolding, partial pipeline) | Infra + integration tests green |
| **E2E** | Waves 6+ (runnable engine end-to-end through the `bonfire run` CLI verb) | Integration + **box E2E PASS verdict on a wheel built from the tree** |
| **Release** | v0.1.0 tag + re-publish | E2E + every README example executable + re-publish checklist |

## Reviewer cadence

Every PR into `v0.1` requires **both**:

- **Wizard** — the prompt-architect role. Standard dispatch review.
- **code-reviewer** — superpowers agent. Independent lens.

Two-lens review is non-negotiable. Drift happens when the same voice reviews the same work.

## The E2E box

### Substrate

`ubuntu:24.04` Docker container. **Local execution only.** Never runs in CI.

Rationale: API key stays on the operator's machine. Cost is observable in real time. No unattended runs draining the key. Pop!_OS 24.04 is Ubuntu-flavored, so box behavior mirrors host.

### Contents

- `git`, `curl`, `ca-certificates`, `build-essential`
- `python3.12` + `python3.12-venv`
- Node.js 20 (via NodeSource)
- `@anthropic-ai/claude-code` (npm global) — the dispatch surface both the observer session and Bonfire's own agents run on

The image carries the harness only. The artifact under test never lives in a layer; it arrives at run time on a read-only mount, so the image is not version-bound to any Bonfire build.

### The artifact under test

**The box installs a wheel built from the working tree. Never PyPI.** This is the property that makes the gate mean anything: a run that installed `bonfire-ai` from PyPI certifies the last release, not the change in front of you.

`e2e-box.sh` builds the wheel host-side (`python -m build --wheel`, falling back to `pip wheel --no-deps`), then writes `.e2e-runs/<run-id>/artifact-under-test.json`:

| Field | Meaning |
|---|---|
| `wheel` | file name, e.g. `bonfire_ai-1.0.1-py3-none-any.whl` |
| `version` | version parsed from the wheel name |
| `sha256` | digest of the exact file the container installs |
| `source_commit` | commit the wheel was built from |
| `source_dirty` | whether the tree had uncommitted changes at build time |
| `built_by` | build command, or the operator-supplied path when `BONFIRE_WHEEL` is set |

The wheel is bind-mounted read-only at `/workspace/artifact`. Inside the box the runner re-computes the digest and refuses to continue on a mismatch, then installs in three steps: the wheel **and** its own requirements into the clean venv (step label `artifact-and-deps` — this step installs the artifact too, so a wheel that cannot install at all fails here), the fixture's dev extras on top, and finally the wheel itself again with `--force-reinstall --no-deps`.

That last step is not decoration. pip skips a local wheel whose version already matches an installed distribution ("already installed with the same version as the provided wheel") and exits 0, so ordering alone buys nothing: if anything the fixture pulls resolves a same-versioned `bonfire-ai` off an index, a plain artifact install is a silent no-op. `--force-reinstall` makes the mounted wheel land unconditionally; `--no-deps` keeps that forced step from re-resolving what the fixture pinned.

`--no-deps` is one-sided, though: step 3 re-lands the *artifact* and never the *dependency set*. If step 2 dragged a shared runtime dep below the wheel's floor, pip only warns and exits 0. Assertion 5 below is what turns that warning into a named RED, so the failure is attributed to the environment rather than mis-attributed to the artifact at `bonfire run` time.

The runner then proves the install five ways before spending a cent. **Every** interpreter the runner starts — system or venv, `-c`, `-m`, or a heredoc on stdin — runs under `python -P` (safe path), not just these five proofs. The runner's cwd is the *fixture* worktree, so without `-P` a module planted at the fixture root is imported ahead of the stdlib and ahead of site-packages by the runner's own code: a `bonfire/` package or a `bonfire_ai-<ver>.dist-info/` would shadow the checks whose purpose is "nothing shadowed the mounted wheel", and a plain `json.py` would shadow the step in Flow 9 that writes the final verdict. That second case is the one that matters most, because the target fingerprint (Flow 7) hashes the committed tip, the branch set, the tracked-file diff and `.bonfire/` — untracked files are deliberately outside it, so an untracked shadow module survives the comparison unchanged. `-P` everywhere is what makes that blind spot harmless.

1. `import bonfire` succeeds — the cheapest catch for a missed import or an omitted package.
2. `bonfire --version` succeeds — resolves the console script and walks the CLI composition root.
3. the reported version equals the wheel's version — a mismatched copy that shadowed the mount fails here.
4. pip's PEP 610 `direct_url.json` for the installed `bonfire-ai` points at exactly the manifest-pinned, hash-verified wheel path under `/workspace/artifact` — an index install writes no such record at all, so the check fails on absence too.
5. every base requirement in the installed `bonfire-ai`'s `Requires-Dist` is installed and inside its specifier — **and there is at least one of them**. Scoped to the artifact's own requirements on purpose: a whole-environment `pip check` would fail this gate on unrelated fixture breakage, which is the same mis-attribution pointing the other way. The non-empty clause is the control rod: this assertion selects the set it grades, so a wheel that declares no base requirements would otherwise iterate nothing, collect no problems and report a green floor having checked nothing. The proof records the count it checked in its evidence file.

Assertion 3 alone is not enough: a same-versioned `bonfire-ai` pulled from an index answers it identically, and the sha256 check only proves the mounted *file* is intact, never that pip consumed it. Assertion 4 is the one that says the installed distribution *is* the wheel this run built — it compares the recorded path against the same `$WHEEL_PATH` the digest check verified, so it does not lean on any "only one file is ever under the mount" assumption held elsewhere.

The whole block merges into the verdict as `artifact_under_test`, so a verdict names what it graded whenever the driver got as far as writing the manifest — including on the abort paths, and including the `sha256`. Read that digest as *the artifact the driver built and mounted*, not as *the artifact pip installed*: on `artifact_hash_mismatch` it is precisely the value the run just proved does **not** describe the file on the mount, and before assertion 4 has run nothing has yet tied the installed distribution to it.

### Flow

1. Host invokes `tests/e2e/scripts/e2e-box.sh <wave> [fixture-ref]`.
2. Host builds the wheel from this working tree and records its identity.
3. **Host clones the fixture into `.e2e-runs/<run-id>/target/`.** Credentials stay on the host; the clone defaults to HTTPS (`FIXTURE_URL`), or copies a pre-cloned checkout (`FIXTURE_SRC_DIR`).
4. Container launches with auth (`.env` API key or the mounted OAuth block), the output dir at `/workspace/out`, the fixture read-write at `/workspace/target`, and the wheel read-only at `/workspace/artifact`.
5. Runner installs and verifies the artifact under test (previous section).
6. Runner reads `ticket_text` from the fixture's `gate/expected-assertions.yaml` and **executes the real CLI**: `bonfire run "<ticket_text>" --budget … --workflow standard_build`, from `/workspace/target`, with stdout, stderr, exit code and wall time captured to `/workspace/out`. Everything the gate grades — `.bonfire/costs.jsonl`, `.bonfire/sessions/<id>.jsonl`, `.bonfire/review-verdict.json`, the `src/` fix, the `bonfire/fix/…` branch — must be written by this command.
7. Runner fingerprints `/workspace/target`, then runs a claude-cli **observer** session. The observer diagnoses the run and writes `/workspace/out/operator-report.json`. It is forbidden to repair anything, to touch a tracked file, or to write under `.bonfire/`; the fingerprint is re-taken afterwards and any delta fails the run with `observer_mutated_target`. The prompt contains no artifact templates, by design — while it did, an agent could satisfy the gate without the product ever running.
8. Post-run: diff filter + pytest + verdict JSON emission via the fixture's `gate/check-verdict.sh`, pointed at the session log Bonfire actually wrote.
9. Runner merges `artifact_under_test` and `bonfire_execution` into the verdict and **forces FAIL when `bonfire run` exited non-zero or never ran**, naming the failure with Bonfire's own stderr. The arbitration is one-directional: PASS can become FAIL, FAIL never becomes PASS.
10. Verdict written to host at `.e2e-runs/<run-id>/verdict.json`.
11. Both review lenses (Wizard + code-reviewer) read the verdict. Maintainer signs the merge.

Historical note: v0.1 ran this box in library-use mode — claude-cli read `bonfire-ai` as a library and hand-wrote the artifacts. That mode certified the CLI agent, not Bonfire. The `bonfire run` verb now ships, so the box drives the product directly.

*Security properties:*

- *Filesystem (enforced): the container has no host filesystem access beyond three bind-mounts: the cloned fixture worktree (`/workspace/target`, read-write), the host output directory (`/workspace/out`, read-write), and the wheel under test (`/workspace/artifact`, read-only). The host machine, the operator's git credentials, and any other repo on disk are unreachable.*
- *GitHub credentials (enforced): no SSH key, no `gh` CLI, no `GITHUB_TOKEN` enters the container. The fixture is cloned on the host before `docker run` and bind-mounted in. Any remote PR push happens on the host after verdict capture.*
- *Artifact integrity (enforced): the wheel's sha256 is fixed host-side and re-checked in the box before install. Integrity does not rest on the read-only mount flag.*
- *Network egress (by-trust today): the container's only network-active processes are `claude-cli` (pinned to `@anthropic-ai/claude-code@2.1.123`), `pip install`, and the Claude Agent SDK dispatches Bonfire itself makes. All are trusted to reach only `api.anthropic.com` + PyPI mirrors. The default Docker bridge network does not enforce this; a v0.2 follow-up will add a `DOCKER-USER` iptables allowlist following Anthropic's reference devcontainer pattern.*

### Build cache policy

`docker build` reuses layers by default, which is right for iteration and wrong for certification: a run meant to prove clean install can be served entirely from day-old layers, including a stale `npm install -g @anthropic-ai/claude-code` and a stale apt index.

The policy is explicit and operator-controlled:

| `BOX_BUILD_CACHE` | Build | Use for |
|---|---|---|
| `auto` (default) | cached | iteration, debugging a fixture, re-reading a verdict |
| `off` | `--no-cache --pull` | **every release-gate certification run** |

The driver prints the mode it used and records it, with the resulting image id, in `.e2e-runs/<run-id>/box-run.json`. A PASS produced under `auto` is a development signal, not a release signal — check `box-run.json` before you cite a verdict in a release decision.

### What "RED" looks like

A gate that cannot go red is not a gate. The box fails, loudly and by name, when:

| Failure reason | Meaning |
|---|---|
| `artifact_manifest_missing` / `artifact_wheel_not_mounted` | driver never delivered a wheel |
| `artifact_hash_mismatch` | the mounted wheel is not the one the driver built |
| `artifact_install_failed:<step>` | a pip step broke. `artifact-and-deps` and `artifact-under-test` mean the wheel itself does not install (packaging drift); `fixture-deps` points at the fixture |
| `artifact_import_failed` | `import bonfire` breaks against the installed wheel |
| `artifact_cli_entrypoint_failed` | console script or CLI composition root is broken |
| `artifact_version_mismatch` | something other than the artifact under test answered |
| `artifact_provenance_failed` | the installed `bonfire-ai` does not trace back to the mounted wheel — pip resolved it from an index, or from some other path |
| `artifact_dependency_floor_violated` | the venv no longer satisfies the artifact's own `Requires-Dist` (the environment is poisoned, not the artifact) — **or** the artifact declares no base `Requires-Dist` at all, which means the floor proof had nothing to check and the wheel lost its dependency metadata |
| `fixture_ticket_text_missing` | fixture carries no ticket to ship |
| `bonfire_run_failed:exit=<n>` + `bonfire_stderr:<line>` | **the product failed** — Bonfire's own last error line rides in the verdict |
| `bonfire_never_executed` | the run never happened; a verdict without execution is a FAIL |
| `observer_mutated_target` | the observer session wrote what only Bonfire may write |
| `gate_verdict_unparseable` | the fixture gate left a truncated or non-JSON verdict; it is quarantined to `verdict-unparseable.json` so arbitration still runs and the gate's status still reaches the operator |
| `gate_script_crashed` | the fixture gate exited non-zero; its verdict (even a clean PASS) still goes through arbitration and is forced to FAIL |

In every one of these cases the *box* worked and the *artifact* did not, but the runner's own exit code differs: it exits **0** for the `bonfire_*` rows (the run completed, the verdict carries the artifact's fate) and **non-zero** for the rows that abort the run — 8 for the `artifact_*` rows, 9 for `fixture_ticket_text_missing`, 10 for `observer_mutated_target`. One case crosses that split: a fixture gate that crashes no longer exits on the spot, so its verdict still goes through arbitration — which stamps `gate_script_crashed` into it and forces FAIL, even when the gate had already written a clean PASS — and the runner then propagates the gate's own status. That status is **unconstrained**: the fixture owns it, nothing in this repo or in the anti-cheat rules below bounds it, so it may be any non-zero value and it may collide with 8/9/10. Read `failure_reasons`, not the code. Either way the runner has written a FAIL `verdict.json` first, so the host driver reports **exit 1** with named `failure_reasons`, never a bare container code. See [box-operator.md](box-operator.md) § "Read the verdict" for the driver's full exit contract.

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

The paths and shapes are unchanged; **who writes them is not**. Every one of those seven is now a claim about output `bonfire run` produced. The box adds its own rules on top (see *What "RED" looks like*), and the last of them — the target fingerprint around the observer session — is what makes rules 1–7 assertions about Bonfire rather than about a model's typing.

## Verdict artifact

Schema: `tests/e2e/schemas/verdict.schema.json` (JSON Schema Draft-07).

The schema IS the contract. To tighten the bar, add an assertion to the schema and the gate re-validates. The schema is the reverse-spec of what v0.1 guarantees — if a capability is required to emit the verdict, that capability must ship in v0.1.

## Cost logging (Fork C for v0.1)

v0.1 ships the minimum viable:

- Per-agent-dispatch line in `.bonfire/costs.jsonl`.
- Stdout summary at the end of a pipeline run, driven by the `bonfire run` CLI verb.

The box exports `BONFIRE_COST_LEDGER_PATH=/workspace/target/.bonfire/costs.jsonl`, and that export is now load-bearing at **both** ends: the writer (`CostLedgerConsumer`) and the reader (`bonfire cost`) both resolve their path through `cost.models.resolve_ledger_path`, so the ledger lands where the gate reads it. With no override set, the destination stays the cross-project default `~/.bonfire/cost/cost_ledger.jsonl` — `bonfire cost` reports cumulative spend across every project on the machine, and relocating that default per-target would fragment the history it exists to keep.

There is deliberately **no** session-directory export either, and the honest reason is narrower than "no such knob exists". It does exist: `VaultConfig.session_dir` defaults to exactly `.bonfire/sessions` and mounts on the settings object as `memory`, so it is addressable as `[memory] session_dir` in `bonfire.toml` or as `BONFIRE_MEMORY__SESSION_DIR`. It is **declared but unwired** — `SessionPersistence` takes `session_dir` as a constructor argument and nothing in this tree passes the loaded setting into it, so setting the key steers nothing. (`BONFIRE_CHECKPOINT_DIR` *is* wired, but it steers engine checkpoints under `~/.bonfire/checkpoints` — a different artifact from the `.bonfire/sessions/<id>.jsonl` log the fixture gate reads.) The box does not export a key that would be silently ignored.

What actually answers "where did it go" is evidence, not configuration: the box grades what landed on disk and captures an inventory of both roots (`/workspace/target/.bonfire` and the box user's `~/.bonfire`) at `bonfire-artifact-inventory.txt`, so "artifact missing" resolves into "artifact written somewhere else" instead of a shrug. **Wiring the session-directory key that already exists**, rather than inventing a second one, remains open; the ledger path half is closed.

Throttle, budget caps, and full configuration module defer to **v0.2** (tracked as a v0.2 epic in the maintainers' internal tracker, which is not public).

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
- [ ] Internal-tracker audit covers **both** (a) commit subjects on `v0.1` / `main` **and** (b) committed *docs-surface* file contents at `v0.1` HEAD — namely `docs/`, the root markdown files (`README.md`, `CHANGELOG.md`, `CONTRIBUTING.md`, `CLAUDE.md`), and no other tree. Pre-`v0.1.0` commit *history* is grandfathered (rewriting published history is more harmful than preserving it); HEAD-state docs-surface files must be clean of internal-tracker IDs, internal Linear URLs, and contributor worktree paths. New commits comply per [CONTRIBUTING.md](../CONTRIBUTING.md). See [CHANGELOG.md](../CHANGELOG.md) Notes section. **Residual at this PR (pre-tag) — six items, none of them clean yet.** No automated test guards this surface (the source sweeps scan `src/bonfire/` and `tests/integration/`; the person-name sweep matches names, not IDs), so this list *is* the gate and it is written to over-report rather than under-report. Re-run the sweep case-insensitively before the tag — an uppercase-only grep misses four of these.

      - `docs/` — **four**, all lowercase: two in `docs/pipeline-stages.md` and two in `docs/product/discipline.md`, each citing an internal decision-memo *filename* that embeds an internal-tracker ID. Close by stating the decision in plain English against a public artifact and dropping the filename. Sweeping these also clears the adjacent internal-process token (`Sage memo`, banned in `src/` and `tests/integration/` by the pin test but never swept in `docs/`, where it appears on five lines — two of them among the four scheduled here, so **three** survive the sweep: two in `docs/pipeline-stages.md` and one in `docs/wizard-playbook.md`). (The `bon-<n>-*` token in this file's own release-train diagram is a branch-name *pattern*, not an ID — it carries no ticket number, and it is a registered allowlist anchor in `tests/unit/test_no_persona_names_in_public_docs.py`. Leave it alone.)
      - `CHANGELOG.md` — **two**: one internal-tracker epic ID in the `0.1.0a3` entry (the third-alpha section, not `0.1.0a2`), closed by rewording; and one illustrative ID-shaped token in the trailing Notes section that states the grandfathering rule itself, closed by naming the pattern without spelling it.
      - `README.md`, `CONTRIBUTING.md`, `CLAUDE.md` — clean at HEAD.

      All six close in the v0.1.0 tag preflight sweep. This bullet list is the sweep's worklist; do not shorten it without re-running the scan.
- [ ] *(Gate 7a — narrow scope closed; the broader test-helper subtree is tracked as a follow-up in the maintainers' internal tracker.)* Source-comment and test-file audit: `src/bonfire/` + `tests/integration/` cleaned. Test-helper dirs (`tests/unit/`, `tests/smoke/`, `tests/dispatch/`, `scripts/`, `.github/workflows/`) still leak: the last audit measured 356 internal-tracker-ID occurrences across 112 files at HEAD, including test *file names*, which is why widening this gate is a rename sweep and not a comment sweep.
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
