# Box Operator Playbook

How to run the Bonfire release-gate Box. **Local-only**, never in CI.
Five minutes to first verdict.

## Prerequisites

- Docker 24+
- SSH access to `BonfireAI/bonfire-e2e-fixture` (private until v0.1.0)
- A Pop!_OS / Ubuntu / macOS host with bash 5+, git, jq
- **One** of the two auth modes below:
  - **Path A — Claude Max OAuth (auto-detected default).** Claude Code logged
    in on the host (`~/.claude/.credentials.json` present). The box driver
    auto-mounts your credentials into the container; cost is counted against
    your Claude Max plan allocation, not against your Anthropic console
    billing. No `.env` staging required.
  - **Path B — Anthropic console API key (explicit override).** A
    `sk-ant-api03-…` key from <https://console.anthropic.com/settings/keys>,
    staged in `.env` with the `ANTHROPIC_API_KEY=` line uncommented. Cost
    lands on console billing — typical run is **~$0.10–$1.00** per fire.

Precedence: an active `.env` line ALWAYS wins. The driver checks `.env` first;
if `.env` is absent or has only commented-out lines, the driver falls through
to the OAuth path. If neither is available, the driver exits 2 with a message
listing both options. In short: stage `.env` only when you deliberately want
to bill against your Anthropic console rather than your Claude Max plan.

## First-run setup

### Path A — Claude Max OAuth (preferred)

If you have Claude Code installed and signed in on this host, you're done —
skip ahead to **Run a gate**. The driver finds your credentials at
`~/.claude/.credentials.json` and bind-mounts a per-run RW copy into the
container at `/home/box/.claude/.credentials.json`. The per-run copy isolates
in-container token refreshes from your host file.

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
# example: tests/e2e/scripts/e2e-box.sh 9 main
```

The driver prints `==> Auth mode: …` at startup so you can confirm which
path was selected.

## Read the verdict

- Verdict JSON: `.e2e-runs/e2e-<timestamp>/verdict.json`
- Claude stream: `.e2e-runs/e2e-<timestamp>/claude-stream.jsonl`
- Fixture worktree (post-run): `.e2e-runs/e2e-<timestamp>/target/`
- Evidence (gate-side scratch): `.e2e-runs/e2e-<timestamp>/evidence/`

The script exits:

- 0 on PASS
- 1 on FAIL (`verdict.json::verdict == "FAIL"`)
- 2 if no auth available (neither `.env` with `ANTHROPIC_API_KEY=sk-…` nor
  `~/.claude/.credentials.json` found)
- 3 if no verdict emitted (should be impossible with the runner trap;
  if it happens, runner crashed before trap registered — inspect Docker
  logs)
- 4 if fixture not mounted
- 6 if the runner found neither auth source inside the container (driver
  failed to wire either an env var or the credentials mount)

## Cost expectations

- **Claude Max OAuth path:** counted against your Claude Max plan
  allocation. No out-of-pocket per fire. If you saturate the plan limit,
  fall back to the API-key path.
- **API-key path:** a typical gate run consumes **~$0.10–$1.00** per fire
  on Anthropic console billing. Set a low daily cap to bound surprises
  (`Settings → Limits → Daily spend limit`).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Exit 2 — `no auth available on host` | Neither `.env` nor `~/.claude/.credentials.json` present | Either `cp .env.example .env` and fill in a key, or run `claude login` to create `~/.claude/.credentials.json` |
| Exit 6 — `no auth available` (inside container) | Driver did not wire either auth path; mount or env-file failed | Check docker run output; verify `~/.claude/.credentials.json` is readable, or `.env` line-format matches `ANTHROPIC_API_KEY=sk-…` |
| OAuth credentials missing on host | Claude Code never logged in | Run `claude login` on the host to create `~/.claude/.credentials.json`, then re-run the box |
| OAuth path exhausts Claude Max allocation | Plan limit reached | Stage a `.env` with a console API key — driver auto-falls back when `.env` is present |
| Exit 3 — `no verdict emitted` | Should be impossible with the runner trap. If it happens, runner crashed before the trap registered. | `docker run` with `-it` and re-execute the entrypoint to debug |
| Verdict FAIL, `failure_reasons: ["claude_cli_auth_error"]` | API key invalid OR OAuth token expired | API-key path: check `.env`, verify key on console.anthropic.com. OAuth path: re-run `claude login` on host. |
| Verdict FAIL, `failure_reasons: ["claude_cli_rate_limited"]` | Sustained 429s from Anthropic | Wait 5 min, re-run. Check usage dashboard. |
| Verdict FAIL, `failure_reasons: ["claude_cli_timeout"]` | Box ran > 30 min | Likely a model loop. Inspect `claude-stream.jsonl` for repetition; consider lowering `--max-turns` |
| Verdict FAIL, `failure_reasons: ["broken_test_now_passes"]` | Agent's fix didn't actually pass the test | Inspect `evidence/pytest-broken.log` |
| Verdict FAIL, `failure_reasons: ["test_files_untouched"]` | Agent modified `tests/` | Cheat caught. Re-run; if persistent, the model is gaming the gate — file an issue |
| Verdict FAIL, `failure_reasons: ["pr_opened"]` | Branch name doesn't match `^bonfire/fix/[a-z0-9-]+-[0-9a-f]{8}$` | Inspect `evidence/branches.txt`; tighten prompt if a model variant keeps drifting |
| Verdict FAIL, `failure_reasons: ["cost_log_present"]` | `.bonfire/costs.jsonl` missing or malformed | Inspect `target/.bonfire/costs.jsonl` |
| Verdict FAIL, `failure_reasons: ["review_verdict_emitted"]` | `.bonfire/review-verdict.json` missing or malformed | Inspect `target/.bonfire/review-verdict.json` |
| Verdict FAIL, `failure_reasons: ["tampering_detected"]` | Agent modified `gate/`, `tests/`, or `expected-assertions.yaml` | Cheat caught. File an issue with the model variant info |
| Docker daemon not running | systemd | `sudo systemctl start docker` |
| SSH clone of fixture fails | Missing SSH key for BonfireAI org | `ssh-add ~/.ssh/id_ed25519`, verify with `ssh -T git@github.com` |
| Stale image cache produces wrong claude-cli version | Old image layer | `docker build --no-cache -t bonfire-e2e:local -f tests/e2e/Dockerfile tests/e2e` |

## Bumping the claude-cli pin

Per `release-gates.md` § "claude-cli bump policy":

1. Run two box runs (current pin + candidate pin) on the same fixture-ref. Both must PASS.
2. Update `tests/e2e/Dockerfile` (the `npm install -g @anthropic-ai/claude-code@…` line) and `release-gates.md` (claude-cli bump policy section) in the same PR.
3. Cite the upstream CHANGELOG link in the PR body, calling out any flag renames or behavior changes.
4. Both review lenses approve before merge.
5. After merge, file a one-line note in the project's release notes.

## Where this lives

- Box flow: `docs/release-gates.md` lines 32–62
- Verdict schema: `tests/e2e/schemas/verdict.schema.json`
- Driver (host-side): `tests/e2e/scripts/e2e-box.sh`
- Runner (container-side): `tests/e2e/scripts/e2e-runner.sh`
- Prompt template: `tests/e2e/prompts/runner-prompt.md`
- Dockerfile: `tests/e2e/Dockerfile`
- Fixture (separate repo): `BonfireAI/bonfire-e2e-fixture`
