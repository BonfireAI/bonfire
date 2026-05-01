# Box Operator Playbook

How to run the Bonfire release-gate Box. **Local-only**, never in CI.
Five minutes to first verdict.

## Prerequisites

- Docker 24+
- SSH access to `BonfireAI/bonfire-e2e-fixture` (private until v0.1.0)
- `ANTHROPIC_API_KEY` from <https://console.anthropic.com/settings/keys>
- A Pop!_OS / Ubuntu / macOS host with bash 5+, git, jq

## First-run setup

1. `cp .env.example .env`
2. Edit `.env`, paste your `ANTHROPIC_API_KEY`. Format: `sk-ant-api03-…`
3. Verify the key works:

   ```bash
   curl -s -H "x-api-key: $(grep ANTHROPIC_API_KEY .env | cut -d= -f2)" \
        -H "anthropic-version: 2023-06-01" \
        https://api.anthropic.com/v1/models | head
   ```

## Run a gate

```bash
tests/e2e/scripts/e2e-box.sh <wave> [fixture-ref]
# example: tests/e2e/scripts/e2e-box.sh 9 main
```

## Read the verdict

- Verdict JSON: `.e2e-runs/e2e-<timestamp>/verdict.json`
- Claude stream: `.e2e-runs/e2e-<timestamp>/claude-stream.jsonl`
- Fixture worktree (post-run): `.e2e-runs/e2e-<timestamp>/target/`
- Evidence (gate-side scratch): `.e2e-runs/e2e-<timestamp>/evidence/`

The script exits:

- 0 on PASS
- 1 on FAIL (`verdict.json::verdict == "FAIL"`)
- 2 if `.env` missing
- 3 if no verdict emitted (should be impossible with the runner trap;
  if it happens, runner crashed before trap registered — inspect Docker
  logs)
- 4 if fixture not mounted

## Cost expectations

A typical gate run consumes **~$0.10–$1.00** of API. Set a low daily cap
on the Anthropic console to bound surprises (`Settings → Limits →
Daily spend limit`).

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Exit 2 — `.env not found` | Missing or misnamed env file | `cp .env.example .env` and fill in |
| Exit 3 — `no verdict emitted` | Should be impossible with the runner trap. If it happens, runner crashed before the trap registered. | `docker run` with `-it` and re-execute the entrypoint to debug |
| Verdict FAIL, `failure_reasons: ["claude_cli_auth_error"]` | API key invalid | Check `.env`; verify key on console.anthropic.com |
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
