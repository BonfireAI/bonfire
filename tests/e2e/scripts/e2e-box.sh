#!/usr/bin/env bash
# Host-side Bonfire E2E release-gate box driver.
#
# Builds the image, mounts an output directory, and runs the box. Auto-detects
# auth mode at startup:
#   - API-key path: $REPO_ROOT/.env contains an active ANTHROPIC_API_KEY=sk-…
#     line (passed to docker via --env-file).
#   - OAuth path:   $HOME/.claude/.credentials.json exists (Claude Max). The
#     credential file is copied into OUT_DIR (per-run, mode 0600) and bind-
#     mounted RW into the container at /home/box/.claude/.credentials.json so
#     in-container token refreshes don't corrupt the host's file.
# Operator must provide at least one. The OAuth path is preferred when the
# operator has Claude Code logged in: cost is counted against the Claude Max
# plan rather than out-of-pocket per fire.
#
# Emits verdict.json and exits non-zero when the verdict is FAIL.
#
# Usage: tests/e2e/scripts/e2e-box.sh <wave> [fixture-ref]

set -euo pipefail

WAVE="${1:?wave number required — e.g. 6}"
FIXTURE_REF="${2:-main}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

IMAGE_TAG="bonfire-e2e:local"
RUN_ID="e2e-$(date +%Y%m%d-%H%M%S)"
OUT_DIR="$REPO_ROOT/.e2e-runs/$RUN_ID"

mkdir -p "$OUT_DIR"
# Lock OUT_DIR to the operator only — it holds the per-run OAuth credentials
# copy (mode 0600 file inside) plus claude-stream artifacts. Default umask
# (0022) leaves the directory listing world-readable; tighten to 0700 so the
# directory contents can't be enumerated by other host users.
chmod 0700 "$OUT_DIR"

# ---------------------------------------------------------------------
# Auth-mode detection. Build the docker auth args into AUTH_ARGS.
# ---------------------------------------------------------------------
AUTH_ARGS=()
AUTH_MODE=""

# API-key path: .env present with an active (non-comment) ANTHROPIC_API_KEY=sk-…
if [ -f "$REPO_ROOT/.env" ] && grep -qE '^[[:space:]]*ANTHROPIC_API_KEY=sk-' "$REPO_ROOT/.env"; then
    AUTH_MODE="api_key"
    AUTH_ARGS+=(--env-file "$REPO_ROOT/.env")
    echo "==> Auth mode: API key (via .env)"
elif [ -f "$HOME/.claude/.credentials.json" ]; then
    # OAuth path: per-run RW copy of the host's credentials. The container
    # may refresh tokens during the run; we don't want to mutate the host file.
    AUTH_MODE="oauth"
    OAUTH_COPY="$OUT_DIR/.credentials.json"
    cp "$HOME/.claude/.credentials.json" "$OAUTH_COPY"
    chmod 0600 "$OAUTH_COPY"
    AUTH_ARGS+=(-v "$OAUTH_COPY:/home/box/.claude/.credentials.json")
    echo "==> Auth mode: Claude Max OAuth (via $HOME/.claude/.credentials.json)"
else
    echo "FAIL: no auth available on host." >&2
    echo "  Provide ONE of:" >&2
    echo "    - $REPO_ROOT/.env containing ANTHROPIC_API_KEY=sk-… (API-key path)" >&2
    echo "    - $HOME/.claude/.credentials.json (Claude Max OAuth — run \`claude login\`)" >&2
    exit 2
fi

echo "==> Building box image"
# Pass the operator's UID/GID so the in-container `box` user owns
# bind-mounted output directories cleanly. Defaults inside the Dockerfile
# preserve the UID 1000 path used by the GitHub Actions runner.
docker build \
  --build-arg "BOX_UID=$(id -u)" \
  --build-arg "BOX_GID=$(id -g)" \
  -t "$IMAGE_TAG" \
  -f "$REPO_ROOT/tests/e2e/Dockerfile" \
  "$REPO_ROOT/tests/e2e"

FIXTURE_DIR="$OUT_DIR/target"
echo "==> Cloning fixture on host (SSH — credentials never enter the box)"
git clone git@github.com:BonfireAI/bonfire-e2e-fixture.git "$FIXTURE_DIR"
(cd "$FIXTURE_DIR" && git checkout "$FIXTURE_REF")

echo "==> Running box — run_id=$RUN_ID wave=$WAVE fixture=$FIXTURE_REF auth=$AUTH_MODE"
docker run --rm \
  "${AUTH_ARGS[@]}" \
  -e RUN_ID="$RUN_ID" \
  -e WAVE="$WAVE" \
  -e FIXTURE_REF="$FIXTURE_REF" \
  -v "$OUT_DIR:/workspace/out" \
  -v "$FIXTURE_DIR:/workspace/target" \
  "$IMAGE_TAG"

VERDICT_PATH="$OUT_DIR/verdict.json"

if [ ! -f "$VERDICT_PATH" ]; then
  echo "FAIL: no verdict emitted — box run incomplete." >&2
  exit 3
fi

VERDICT="$(python3 -c "import json,sys; print(json.load(open('$VERDICT_PATH'))['verdict'])")"
echo "==> Verdict: $VERDICT"
echo "==> Artifact: $VERDICT_PATH"

[ "$VERDICT" = "PASS" ] || exit 1
