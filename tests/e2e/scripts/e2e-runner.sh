#!/usr/bin/env bash
# Container-side Bonfire E2E runner. ALWAYS emits a verdict.json.
#
# Drives an in-box claude-cli session against a bind-mounted fixture worktree,
# captures Bonfire-shaped artifacts, then invokes the fixture's gate script to
# validate the result. Runs eight phases (0-7); a bash trap guarantees that a
# verdict.json is always written even on crash, signal, or early exit.
#
# See docs/box-operator.md for operator usage and docs/release-gates.md for the
# gate-tier protocol.

set -euo pipefail

# Auth mode is operator-selected: at least one of (a) ANTHROPIC_API_KEY env var
# or (b) mounted OAuth credentials at ~/.claude/.credentials.json must be
# present. The bare-cli flag was dropped from the claude invocation precisely
# so that claude-cli can fall back to OAuth when the env var is absent. See
# docs/box-operator.md for the operator-side path-selection logic.
# Use the literal mount path rather than $HOME/.claude/...: under USER box,
# HOME resolves to /home/box today, but a future `docker run --user <other>`
# would silently change HOME and route the check to the wrong path.
if [[ -z "${ANTHROPIC_API_KEY:-}" ]] && [[ ! -f "/home/box/.claude/.credentials.json" ]]; then
    echo "FAIL: no auth available." >&2
    echo "  Provide ONE of:" >&2
    echo "    - ANTHROPIC_API_KEY env var (Anthropic console API key path)" >&2
    echo "    - /home/box/.claude/.credentials.json mount (Claude Max OAuth path)" >&2
    exit 6
fi

: "${RUN_ID:?required}"
: "${WAVE:?required}"
: "${FIXTURE_REF:=main}"

OUT_DIR="/workspace/out"
VERDICT_PATH="$OUT_DIR/verdict.json"
PHASE="init"
FAILURE_REASONS=()
mkdir -p "$OUT_DIR"

set_phase() {
    PHASE="$1"
    echo "==> phase=$PHASE"
}

# Failure-mode verdict emitter. Writes a minimal but schema-conforming
# verdict.json with verdict=FAIL and failure_reasons populated. Idempotent:
# if a verdict already exists (i.e. the gate script wrote one), do not
# overwrite it.
emit_failure_verdict() {
    local reason="$1"
    local exit_code="$2"

    if [[ -f "$VERDICT_PATH" ]]; then
        echo "==> verdict.json already present; not overwriting (incoming reason was: $reason)"
        return 0
    fi

    FAILURE_REASONS+=("$reason")
    FAILURE_REASONS+=("phase:$PHASE")
    FAILURE_REASONS+=("exit:$exit_code")

    python3 - "$VERDICT_PATH" "$RUN_ID" "$WAVE" "$FIXTURE_REF" "${FAILURE_REASONS[@]}" <<'PY'
import json
import sys

out_path, run_id, wave, fixture_ref, *reasons = sys.argv[1:]
verdict = {
    "run_id": run_id,
    "wave": int(wave),
    "bonfire_version": "unknown",
    "fixture": {"repo": "BonfireAI/bonfire-e2e-fixture", "ref": fixture_ref},
    "ticket": {
        "id": "unknown",
        "description": "runner aborted before verdict emission",
    },
    "pipeline": {"stages": [], "total_cost_usd": 0.0, "duration_sec": 0.0},
    "assertions": {
        "broken_test_now_passes": False,
        "no_regressions": False,
        "pr_opened": False,
        "test_files_untouched": False,
        "src_files_modified": False,
        "review_verdict_emitted": False,
        "cost_log_present": False,
    },
    "artifacts": {},
    "verdict": "FAIL",
    "failure_reasons": reasons,
}
with open(out_path, "w") as fh:
    json.dump(verdict, fh, indent=2)
print(f"==> emitted FAIL verdict: {out_path} reasons={reasons}", file=sys.stderr)
PY
}

# Trap: any non-zero exit (including SIGTERM/SIGINT) routes through here.
on_exit_trap() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        emit_failure_verdict "trap:nonzero_exit" "$rc"
    fi
}
trap on_exit_trap EXIT
trap 'emit_failure_verdict "trap:sigterm" 143; exit 143' TERM
trap 'emit_failure_verdict "trap:sigint" 130; exit 130' INT

# ---------------------------------------------------------------------
# Phase 0: verify fixture is mounted
# ---------------------------------------------------------------------
set_phase "verify_fixture_mounted"
if [[ ! -d /workspace/target/.git ]]; then
    echo "FAIL: /workspace/target not mounted — host must clone fixture via e2e-box.sh before docker run." >&2
    emit_failure_verdict "fixture_not_mounted" 4
    exit 4
fi
cd /workspace/target

# ---------------------------------------------------------------------
# Phase 1: capture pre-run git SHA
# ---------------------------------------------------------------------
set_phase "capture_pre_run_sha"
git rev-parse HEAD > "$OUT_DIR/pre-run-sha.txt"
PRE_RUN_SHA="$(cat "$OUT_DIR/pre-run-sha.txt")"

# ---------------------------------------------------------------------
# Phase 2: capture pre-run working-tree status (expect clean)
# ---------------------------------------------------------------------
set_phase "capture_pre_run_status"
git status --porcelain > "$OUT_DIR/pre-run-status.txt"

# ---------------------------------------------------------------------
# Phase 3: baseline tamper-evidence hashes (anti-cheat)
# ---------------------------------------------------------------------
set_phase "compute_baseline_hashes"
{
    sha256sum gate/check-verdict.sh
    sha256sum gate/expected-assertions.yaml
    find tests/ -type f -print0 | sort -z | xargs -0 sha256sum
} > "$OUT_DIR/baseline-hashes.txt"

# ---------------------------------------------------------------------
# Phase 4: drive Bonfire via claude-cli
# ---------------------------------------------------------------------
set_phase "drive_claude_cli"

SESSION_ID="$(uuidgen)"
START_TS="$(date +%s)"
export BONFIRE_COST_LEDGER_PATH=/workspace/target/.bonfire/costs.jsonl
export BONFIRE_SESSION_DIR=/workspace/target/.bonfire/sessions
mkdir -p /workspace/target/.bonfire/sessions
echo "$SESSION_ID" > "$OUT_DIR/claude-session-id.txt"
echo "$START_TS"   > "$OUT_DIR/start-timestamp.txt"

set +e
timeout --signal=TERM --kill-after=30s 1800s \
    stdbuf -oL -eL \
    claude -p "$(cat /usr/local/bin/e2e-prompt.txt)" \
        --session-id "$SESSION_ID" \
        --permission-mode bypassPermissions \
        --output-format stream-json \
        --verbose \
        --include-partial-messages \
        --max-turns 50 \
        --max-budget-usd 5.00 \
        --add-dir /workspace/out \
    > "$OUT_DIR/claude-stream.jsonl" \
    2> "$OUT_DIR/claude-cli.stderr"
CLAUDE_EXIT=$?
set -e
echo "$CLAUDE_EXIT" > "$OUT_DIR/claude-exit.txt"
# Extract the final `result` event for cost/duration/session_id (last line of stream).
tail -n1 "$OUT_DIR/claude-stream.jsonl" > "$OUT_DIR/claude-result.json" || true

# ---------------------------------------------------------------------
# Phase 5: capture post-run diff + branches for the gate script
# ---------------------------------------------------------------------
set_phase "capture_post_run_diff"
git diff "$PRE_RUN_SHA"..HEAD --name-only > "$OUT_DIR/diff.patch" 2>/dev/null \
    || git diff --name-only > "$OUT_DIR/diff.patch"
git for-each-ref --format='%(refname:short)' refs/heads > "$OUT_DIR/branches.txt"

# ---------------------------------------------------------------------
# Phase 6: invoke the fixture's gate/check-verdict.sh to write verdict.json
# ---------------------------------------------------------------------
set_phase "gate_check"
set +e
bash gate/check-verdict.sh \
    --run-id           "$RUN_ID" \
    --wave             "$WAVE" \
    --fixture-ref      "$FIXTURE_REF" \
    --out              "$VERDICT_PATH" \
    --session-log      "/workspace/target/.bonfire/sessions/$SESSION_ID.jsonl" \
    --claude-result    "$OUT_DIR/claude-result.json" \
    --claude-exit      "$CLAUDE_EXIT" \
    --start-ts         "$START_TS" \
    --pre-sha          "$PRE_RUN_SHA" \
    --diff             "$OUT_DIR/diff.patch" \
    --branches         "$OUT_DIR/branches.txt" \
    --baseline-hashes  "$OUT_DIR/baseline-hashes.txt"
GATE_RC=$?
set -e
if [[ "$GATE_RC" -ne 0 ]]; then
    emit_failure_verdict "gate_script_crashed" "$GATE_RC"
    exit "$GATE_RC"
fi

# ---------------------------------------------------------------------
# Phase 7: idempotent fallback if gate exited 0 but did not write verdict
# ---------------------------------------------------------------------
set_phase "verify_verdict_emitted"
if [[ ! -f "$VERDICT_PATH" ]]; then
    emit_failure_verdict "gate_script_did_not_emit_verdict" 5
    exit 5
fi

# ---------------------------------------------------------------------
# Phase 8: success exit; trap will see rc==0 and not overwrite the verdict
# ---------------------------------------------------------------------
set_phase "done"
echo "==> verdict at $VERDICT_PATH"
exit 0
