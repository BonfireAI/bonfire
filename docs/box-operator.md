# Box Operator Playbook

How to run the Bonfire release-gate Box. **Local-only**, never in CI.
Five minutes to first verdict.

The box installs a **wheel built from your working tree** and executes the real
`bonfire run` against the fixture ticket. It is not testing PyPI. It is testing
the code you are looking at, and it will say so by name in the verdict.

## Prerequisites

- Docker 24+
- Read access to `BonfireAI/bonfire-e2e-fixture` (private until v0.1.0). The
  clone happens **on the host over HTTPS** by default — your `gh`/git
  credential helper authenticates it, and no credential ever enters the box.
  Set `FIXTURE_SRC_DIR=/path/to/checkout` to skip the network entirely.
- A Pop!_OS / Ubuntu / macOS host with bash 5+, git, jq
- A host Python 3.12+ that can build a wheel. The driver prefers the repo's
  own `.venv/bin/python` when present, uses `python -m build` if available,
  and falls back to `pip wheel --no-deps`.
- **One** of the two auth modes below:
  - **Path A — Claude Max OAuth (auto-detected default).** Claude Code logged
    in on the host (`~/.claude/.credentials.json` present). The box driver
    auto-mounts your credentials into the container; cost is counted against
    your Claude Max plan allocation, not against your Anthropic console
    billing. No `.env` staging required.
  - **Path B — Anthropic console API key (explicit override).** A
    `sk-ant-api03-…` key from <https://console.anthropic.com/settings/keys>,
    staged in `.env` with the `ANTHROPIC_API_KEY=` line uncommented. Cost
    lands on console billing.

Precedence: an active `.env` line ALWAYS wins. The driver checks `.env` first;
if `.env` is absent or has only commented-out lines, the driver falls through
to the OAuth path. If neither is available, the driver exits 2 with a message
listing both options. In short: stage `.env` only when you deliberately want
to bill against your Anthropic console rather than your Claude Max plan.

Both auth paths serve `bonfire run` too — the Claude Agent SDK shells out to
the same pinned claude-cli inside the box.

## First-run setup

### Path A — Claude Max OAuth (preferred)

If you have Claude Code installed and signed in on this host, you're done —
skip ahead to **Run a gate**. The driver finds your credentials at
`~/.claude/.credentials.json` and bind-mounts a per-run RW copy into the
container at `/home/box/.claude/.credentials.json`. The per-run copy isolates
in-container token refreshes from your host file, and carries only the
`claudeAiOauth` block.

If `~/.claude/.credentials.json` is missing, log in:

```bash
claude login
```

That writes `~/.claude/.credentials.json`. Re-run the box.

### Path B — Anthropic console API key

Use this when you do **not** have Claude Max, or when you want to bound cost
explicitly per fire.

1. `cp .env.example .env`
2. Edit `.env`, paste your `ANTHROPIC_API_KEY`. Format: `sk-ant-api03-…`
3. Verify the key works:

   ```bash
   curl -s -H "x-api-key: $(grep ANTHROPIC_API_KEY .env | cut -d= -f2)" \
        -H "anthropic-version: 2023-06-01" \
        https://api.anthropic.com/v1/models | head
   ```

4. Set a daily-spend cap on the Anthropic console
   (`Settings → Limits → Daily spend limit`).

## Run a gate

```bash
tests/e2e/scripts/e2e-box.sh <wave> [fixture-ref]
# iteration:     tests/e2e/scripts/e2e-box.sh 9 main
# certification: BOX_BUILD_CACHE=off tests/e2e/scripts/e2e-box.sh 9 main
```

The driver prints `==> Auth mode: …`, `==> Build cache: …` and
`==> Artifact under test: …` at startup, so you can confirm what is being
tested before a cent is spent.

### Arguments

| Position | Name | Default | Meaning |
|---|---|---|---|
| 1 | `<wave>` | *(required)* | Wave number the gate is evaluating. **Whole number only** — the verdict types `wave` as an integer. A decimal label such as "Wave 9.1" is passed as its major number (`9`). A missing, empty or non-numeric argument exits 7 immediately, before the wheel build — never 1, which is reserved for a FAIL verdict |
| 2 | `[fixture-ref]` | `main` | Git ref checked out in the fixture clone |

### Environment knobs

| Variable | Default | Meaning |
|---|---|---|
| `BOX_BUILD_CACHE` | `auto` | `auto` reuses Docker layers (fast). `off` builds with `--no-cache --pull`. **Every release-gate certification run must use `off`.** |
| `BONFIRE_WHEEL` | *(unset)* | Skip the build and test this exact wheel file. Use it to reproduce an old verdict or to grade a release candidate. |
| `FIXTURE_URL` | HTTPS fixture remote | Where to clone the fixture from. |
| `FIXTURE_SRC_DIR` | *(unset)* | Path to a pre-cloned fixture checkout; cloned locally, your copy is never mutated, no network needed. |
| `BONFIRE_RUN_BUDGET_USD` | `5.00` | `--budget` passed to `bonfire run` inside the box. |
| `BONFIRE_RUN_TIMEOUT_SEC` | `1800` | Wall-clock cap on `bonfire run`. |
| `BONFIRE_WORKFLOW` | `standard_build` | `--workflow` passed to `bonfire run`. |
| `BOX_PIP_CACHE` | `warm` | `warm` bind-mounts `.e2e-runs/pip-cache/` into the box as pip's download cache, so the roughly 86 MB of dependency wheels is fetched once instead of on every run. `off` sets `PIP_NO_CACHE_DIR` and forces a cold download. Independent of `BOX_BUILD_CACHE`, which governs Docker layers. The cache never holds the artifact under test: that wheel is installed by explicit path from the read-only mount and is never resolved from an index. |

## Read the verdict

Everything lands under `.e2e-runs/e2e-<timestamp>/` (mode 0700):

| File | What it tells you |
|---|---|
| `verdict.json` | the verdict, plus `artifact_under_test` (once the driver wrote a manifest) and `bonfire_execution` (once the runner reached Phase 6) |
| `verdict-unparseable.json` | **present only when the gate's `--out` file was not a usable verdict** — the quarantined original, exactly as the gate left it |
| `verdict-parse.err` | **present only when `verdict-unparseable.json` is** — why the file was rejected (a JSON decode error, or the shape it had instead of an object with a string `verdict`) |
| `artifact-under-test.json` | wheel name, version, sha256, source commit, dirty flag |
| `box-run.json` | image id, **build-cache mode**, fixture ref, auth mode |
| `bonfire-command.txt` | the exact `bonfire run` invocation |
| `bonfire-run.stdout` / `bonfire-run.stderr` / `bonfire-run.exit` | what Bonfire printed and how it exited |
| `bonfire-artifact-inventory.txt` | every file Bonfire wrote, under the fixture **and** under `~/.bonfire` |
| `pip-install.log` / `pip-freeze.txt` | the install of the artifact under test, all three steps appended in order |
| `pip-step-<step>.log` | one file per install step, holding only that step's own output. This is what the runner reads to decide whether a failed install was the artifact or the box's network, and it is what you should read first on any `artifact_install_failed` or `box_network_unreachable` |
| `bonfire-version.txt` / `bonfire-import.txt` | console-script and import smoke results |
| `bonfire-direct-url.json` / `.err` | pip's PEP 610 record for the installed `bonfire-ai` — the proof it came from the mount |
| `bonfire-dependency-check.txt` / `.err` | each of the artifact's base requirements with the version that satisfied it, and a trailing `checked N base requirement(s)` line — the proof the venv still meets the wheel's floors, and the control rod proving the check was not run against an empty set |
| `operator-report.json` | the observer's diagnosis (colour, not gate input) |
| `claude-stream.jsonl` | the observer session transcript |
| `target-fingerprint-pre.txt` / `-post.txt` | the anti-forgery fingerprints |
| `target/` | the fixture worktree, post-run |
| `artifact/` | the wheel that was installed |

**Read `bonfire_execution.exit_code` first, when there is one.** If it is
non-zero, Bonfire failed and the verdict is FAIL no matter what any assertion
says — the last line of Bonfire's stderr rides along in `failure_reasons` as
`bonfire_stderr:…`. The whole `bonfire_execution` block is **absent** when the
runner aborted before it ever executed `bonfire run`: exit 4, the exit-8
`artifact_*` family, the exit-11 `box_network_unreachable` family, exit 9,
and any trap that fires before Phase 6. There,
read `failure_reasons` instead — it names the reason and the phase that
stopped the run.

**Read `artifact_*` and `box_network_unreachable` as claims about different
layers, because they are.** An `artifact_*` reason says the box reached the
artifact and the artifact failed. `box_network_unreachable:<step>` says the
box could not reach its package index, so the wheel was never installed,
never imported and never executed: nothing in that verdict is evidence about
the artifact, and the correct next step is to fix the link and re-run, not to
open a bug against the wheel. The runner decides between them from the failing
step's own `pip-step-<step>.log`, and a failure only earns the network reading
when that log carries an unambiguous transport exception and carries no error
that pip could only have raised after reaching the wheel. Anything ambiguous
or unrecognised stays `artifact_install_failed`, so the quiet reading is never
the default. Both are a FAIL, both abort the run, and neither is softer than
the other.

`artifact_under_test` is absent only when the driver never
wrote a manifest; whenever a manifest exists it is carried into the verdict
whole, digest included, on every path. Read it as what the driver **built**,
not as what the box proved installed — on `artifact_hash_mismatch` the digest
is precisely the value the run just proved does not describe the file on the
mount, which is the diagnosis, not a contradiction. The same record stays
readable in `artifact-under-test.json` beside the verdict.

`e2e-box.sh` — the command you actually run — **decides** with one of five
codes. Container-side codes are never passed through; see the rule below.

- 0 on PASS
- 1 on FAIL (`verdict.json::verdict == "FAIL"`, or a PASS verdict contradicted
  by a non-zero container exit)
- 2 if no auth available **on the host** (neither `.env` with
  `ANTHROPIC_API_KEY=sk-…` nor `~/.claude/.credentials.json` found)
- 3 if no verdict was emitted at all
- 7 driver-side usage error: a non-integer `<wave>`, bad `BOX_BUILD_CACHE`,
  missing `BONFIRE_WHEEL`, or a build that produced zero or several wheels

Those five are the driver's *decision* vocabulary — they are **not** a closed
exit contract, and nothing enforces one. `e2e-box.sh` runs under
`set -euo pipefail` with no trap, so a host-side command that fails before the
driver reaches a decision aborts the script with **that command's own status**,
which is usually outside the five. These are the live host-side failure modes,
and the troubleshooting table below carries a row for each:

| Host-side abort (driver never reached a verdict) | Code you actually see |
|---|---|
| fixture `git clone` fails — no access, or an SSH-only remote | git's status, typically **128** |
| `docker build` fails, or the Docker daemon is not running | docker's status — **1**, **125**, **126** or **127** |
| host wheel build (`python -m build` / `pip wheel`) fails | the build backend's status, typically **1** |

Exit 1 is therefore ambiguous by construction. Disambiguate by output, not by
code: a genuine FAIL always prints the verdict path and named
`failure_reasons`; a host-side abort dies before the box ever launches and
prints the failing command's own error instead.

The rule for everything the *runner* does inside the container: the driver
reports what the verdict file says, not the container's exit code.

A container-side abort that **wrote a FAIL verdict** surfaces as driver
**exit 1** with a named `failure_reasons` entry. The runner's trap is registered
before every one of these, so a verdict always exists:

| Runner exit | `failure_reasons` entry |
|---|---|
| 4 | `fixture_not_mounted` |
| 5 | `gate_script_did_not_emit_verdict` (gate exited 0 and wrote nothing — or wrote something that is not a usable verdict, additionally named `gate_verdict_unparseable`) |
| 8 | the `artifact_*` family — manifest/mount/hash, `artifact_install_failed:<step>`, import, CLI entrypoint, version mismatch, provenance, dependency floor |
| 9 | `fixture_expected_assertions_missing`, `fixture_ticket_text_missing` |
| 10 | `observer_mutated_target` |
| 11 | `box_network_unreachable:<step>`: a pip step could not reach the package index. The artifact was NOT tested, and this reason makes no claim about the wheel |
| *the fixture gate's own status* — any non-zero, not a fixed number | `gate_script_crashed` |
| any other non-zero exit | `trap:nonzero_exit` — the EXIT trap named it |

Two rows there do not behave like the others. `gate_script_crashed` passes the
**fixture gate's** exit code straight through. The fixture owns that number and
nothing bounds it, so it is not a code to match against — it may be any non-zero
value and may collide with 8, 9 or 10. Match on `failure_reasons`, never on the
code.

If the gate crashed *after* writing a verdict of its own, the runner does not
overwrite that file — but the arbitration still **stamps `gate_script_crashed`
into it and forces FAIL**, so a gate that died after writing a clean PASS cannot
leave a PASS verdict with an empty `failure_reasons` for the driver's exit-code
cross-check to catch on its own. One exception to the preservation rule: when
the gate's file is not a usable verdict at all — killed mid-write and truncated,
or `null`, a list, or an object with no string `verdict` field — the runner moves
it to `verdict-unparseable.json` (with the reason in `verdict-parse.err`), names
`gate_verdict_unparseable`, and writes the verdict itself. Otherwise the
arbitration would raise on the file and bury the gate's own status behind a
runner traceback. A PASS that survives arbitration plus a non-zero container
exit is caught by the driver instead and still reported as **exit 1** ("verdict
says PASS but the runner exited …").

**Exit 3 means no verdict file, whatever the reason.** The driver checks for
`verdict.json` and nothing else, so exit 3 also covers a container that never
ran the runner at all: a bad bind-mount, a missing image, a dead Docker daemon,
an OOM-kill. On the runner side it covers every abort **before the trap is
registered** — the auth pre-flight (runner exit 6, "no auth available" in the
container log), the `RUN_ID` / `WAVE` required-variable checks (presence, and
for `WAVE` also whole-number shape — runner **exit 7**, because the verdict
types `wave` as an integer and a hand `docker run` of the entrypoint bypasses
the driver's own check), and the `mkdir -p` of the output directory, all of
which run ahead of the trap. Exit 3
therefore means *read the Docker log*: it distinguishes "the container never
started" from "the runner died in that early window".

## Cost expectations

- **Claude Max OAuth path:** counted against your Claude Max plan
  allocation. No out-of-pocket per fire. If you saturate the plan limit,
  fall back to the API-key path.
- **API-key path:** a full run now spends on **two** things — Bonfire's own
  pipeline dispatches (bounded by `BONFIRE_RUN_BUDGET_USD`, default $5.00)
  and the observer session (bounded by `--max-budget-usd 5.00`). A red run
  usually costs far less, because Bonfire halts early. Set a low daily cap to
  bound surprises (`Settings → Limits → Daily spend limit`).
- Lower `BONFIRE_RUN_BUDGET_USD` while iterating on the box itself; a
  certification run should keep the default.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Exit 2 — `no auth available on host` | Neither `.env` nor `~/.claude/.credentials.json` present | Either `cp .env.example .env` and fill in a key, or run `claude login` to create `~/.claude/.credentials.json` |
| Exit 3, Docker log shows `FAIL: no auth available` | Driver did not wire either auth path into the container; mount or env-file failed. The runner aborts (its own exit 6) before its trap exists, so no verdict is written and the driver reports 3 | Check docker run output; verify `~/.claude/.credentials.json` is readable, or `.env` line-format matches `ANTHROPIC_API_KEY=sk-…` |
| Exit 7 — `expected exactly one wheel` | Stale artifacts, or a build that emitted more than one wheel | Re-run (each run builds into a fresh per-run directory), or pin the artifact with `BONFIRE_WHEEL=/path/to.whl` |
| Exit 7 — `BOX_BUILD_CACHE must be 'auto' or 'off'` | Typo in the knob | Use one of the two documented values |
| Exit 7 — `<wave> must be a whole number` | A decimal wave label (`9.1`), a non-numeric argument, or **no argument at all** — all three are usage errors, and all three exit 7. The verdict types `wave` as an integer | Pass the major number (`e2e-box.sh 9 main`). The check runs before the wheel build, so nothing was spent |
| Wheel build fails on the host | No build backend available | `pip install build` into the repo venv, or pass a prebuilt `BONFIRE_WHEEL` |
| Exit 3 — `no verdict emitted` | No `verdict.json` on disk: the container never started (bind-mount, image, daemon, OOM), or the runner died in its pre-trap window | Read the Docker log first — it says which. Then `docker run` with `-it` and re-execute the entrypoint to debug; pass `-e WAVE=<whole number>`, since a non-integer `WAVE` aborts the runner at exit 7 before its trap exists |
| FAIL, `artifact_hash_mismatch` | The mounted wheel is not the one the driver built | Re-run; if it persists, something is rewriting `.e2e-runs/<run>/artifact/` |
| FAIL, `artifact_install_failed:artifact-and-deps` | Packaging drift — **the wheel itself** (or one of its requirements) does not install in a clean box. This step installs the artifact, not just its dependency set. The runner reached the wheel before it failed; a run that never reached the index is reported as `box_network_unreachable` instead | Read `pip-step-artifact-and-deps.log`, then `pip-install.log`. This is a real release blocker, not a box bug |
| FAIL, `box_network_unreachable:<step>` (runner exit 11) | The box could not reach its package index. pip already retried 8 times at a 60-second per-read timeout and still could not fetch. **The artifact was never installed, imported or executed, so this verdict says nothing about the wheel** | Read `pip-step-<step>.log` for the transport exception. Fix the host link and re-run; a warm `.e2e-runs/pip-cache/` means the retry does not re-download what already landed. Do not file this against Bonfire, and do not cite the run as evidence about the artifact either way |
| FAIL, `artifact_install_failed:fixture-deps` / `:artifact-under-test` | The fixture's dev extras failed to resolve, or the forced re-install of the wheel failed | Read `pip-install.log`; `fixture-deps` usually points at the fixture, not at Bonfire |
| FAIL, `artifact_dependency_floor_violated` | The venv no longer satisfies the artifact's own `Requires-Dist` — typically the fixture pinned an older `bonfire-ai`, which dragged a shared dep below the wheel's floor, and step 3's `--no-deps` re-landed the artifact without repairing it | Read `bonfire-dependency-check.err` for the offending requirement, then `pip-install.log` for which step moved it. **The environment is poisoned, not the artifact** — do not go debugging Bonfire |
| FAIL, `artifact_dependency_floor_violated` with `declares no base Requires-Dist` in the `.err` | Same reason code, opposite layer: the wheel carries **no** base dependencies, so the floor proof had nothing to check. A `dependencies = [...]` block dropped from `pyproject.toml` looks exactly like this | Read `bonfire-dependency-check.txt` (`checked 0 base requirement(s)`) and the wheel's `METADATA`. **This one IS the artifact** — packaging drift, a real release blocker |
| FAIL, `gate_script_crashed` | The fixture's `gate/check-verdict.sh` exited non-zero. The container's exit code is the gate's own — unbounded, and possibly colliding with 8/9/10, so do not read it as a runner code | Read the Docker log from `phase=gate_check` onward, then the fixture repo. If the gate wrote a *usable* verdict before crashing, the runner preserved the file and stamped this reason into it with verdict FAIL; a file that is not a usable verdict is moved to `verdict-unparseable.json` (with `verdict-parse.err`) and named `gate_verdict_unparseable` |
| FAIL, `gate_script_did_not_emit_verdict` (runner exit 5) | The fixture gate exited 0 but wrote no `verdict.json` | Fixture bug — check that `gate/check-verdict.sh` honours its `--out` argument |
| FAIL, `artifact_import_failed` | `import bonfire` breaks against the installed wheel | Read `bonfire-import.txt` — a missed module in the wheel, or an import-time error |
| FAIL, `artifact_cli_entrypoint_failed` | `bonfire --version` failed | Console-script or CLI composition-root breakage. Read `bonfire-version.txt` |
| FAIL, `artifact_version_mismatch` | Something other than the artifact answered | A PyPI `bonfire-ai` shadowed the mount, or the venv was pre-poisoned |
| FAIL, `artifact_provenance_failed` | The installed `bonfire-ai` does not trace back to the mounted wheel | Read `bonfire-direct-url.err`. No `direct_url.json` at all means pip resolved the distribution from an index — a same-versioned PyPI copy passes the version check and still fails here. Read `pip-install.log` for which step installed it |
| FAIL, `bonfire_run_failed:exit=<n>` | **The product failed.** | Read `bonfire-run.stderr`, then `operator-report.json` for the observer's read of it. Fix Bonfire — do not fix the box |
| FAIL, `bonfire_never_executed` | The execution record is missing | Runner aborted before Phase 6; read the phase markers in the Docker log |
| FAIL, `observer_mutated_target` | The observer session wrote what only Bonfire may write | Diff `target-fingerprint-pre.txt` against `-post.txt`. If a model keeps doing this, file an issue with the model variant |
| FAIL, `fixture_ticket_text_missing` | The fixture's `gate/expected-assertions.yaml` has no `ticket_text` | Check the fixture ref you passed |
| FAIL, `claude_cli_auth_error` | API key invalid OR OAuth token expired | API-key path: check `.env`, verify key on console.anthropic.com. OAuth path: re-run `claude login` on host. |
| FAIL, `claude_cli_rate_limited` | Sustained 429s from Anthropic | Wait 5 min, re-run. Check usage dashboard. |
| FAIL, `broken_test_now_passes` | Bonfire's fix didn't actually pass the test | Inspect `evidence/pytest-broken.log` and `bonfire-run.stdout` |
| FAIL, `test_files_untouched` | Something modified `tests/` | Read the diff. Bonfire's own agents modifying tests is a product defect |
| FAIL, `pr_opened` | Branch name doesn't match `^bonfire/fix/[a-z0-9-]+-[0-9a-f]{8}$` | Inspect `branches.txt`; the publisher stage is what names branches |
| FAIL, `cost_log_present` | `.bonfire/costs.jsonl` missing or malformed | The writer honours `BONFIRE_COST_LEDGER_PATH`, so an empty target root means the run never charged or the export was lost — check `bonfire-artifact-inventory.txt` for a ledger under `~/.bonfire` before suspecting the run |
| FAIL, `review_verdict_emitted` | `.bonfire/review-verdict.json` missing or malformed | The reviewer stage writes it before posting to GitHub, so absence means that stage was never reached — read `bonfire-run.stdout` for where the run stopped |
| FAIL, `tampering_detected` | `gate/`, `tests/`, or `expected-assertions.yaml` changed | Cheat caught. File an issue with the model variant info |
| A PASS you don't trust | Run used the layer cache | Check `box-run.json::image.build_cache`. Re-run with `BOX_BUILD_CACHE=off` before citing it in a release decision |
| Docker daemon not running | systemd | `sudo systemctl start docker` |
| Fixture clone fails | No access to the private fixture, or an SSH-only remote configured | Verify HTTPS access (`gh auth status`), or point `FIXTURE_SRC_DIR` at a local checkout |

## Bumping the claude-cli pin

Per `release-gates.md` § "claude-cli bump policy":

1. Run two box runs (current pin + candidate pin) on the same fixture-ref. Both must PASS.
2. Update `tests/e2e/Dockerfile` (the `npm install -g @anthropic-ai/claude-code@…` line) and `release-gates.md` (claude-cli bump policy section) in the same PR.
3. Cite the upstream CHANGELOG link in the PR body, calling out any flag renames or behavior changes.
4. Both review lenses approve before merge.
5. After merge, file a one-line note in the project's release notes.

## Where this lives

- Box flow, artifact-under-test contract, cache policy: `docs/release-gates.md`
- Verdict schema: `tests/e2e/schemas/verdict.schema.json`
- Driver (host-side): `tests/e2e/scripts/e2e-box.sh`
- Runner (container-side): `tests/e2e/scripts/e2e-runner.sh`
- Observer prompt: `tests/e2e/prompts/runner-prompt.md`
- Dockerfile: `tests/e2e/Dockerfile`
- Fixture (separate repo): `BonfireAI/bonfire-e2e-fixture`
