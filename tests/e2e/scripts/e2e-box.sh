#!/usr/bin/env bash
# Host-side Bonfire E2E release-gate box driver.
# Builds the image, mounts an output directory, runs the box with ANTHROPIC_API_KEY.
# Emits verdict.json and exits non-zero when the verdict is FAIL.
#
# Usage: tests/e2e/scripts/e2e-box.sh <wave> [fixture-ref]
# Requires .env at the repo root with ANTHROPIC_API_KEY=...

set -euo pipefail

WAVE="${1:?wave number required — e.g. 6}"
FIXTURE_REF="${2:-main}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

if [ ! -f "$REPO_ROOT/.env" ]; then
  echo "FAIL: $REPO_ROOT/.env not found." >&2
  echo "Create it with: ANTHROPIC_API_KEY=sk-ant-..." >&2
  exit 2
fi

IMAGE_TAG="bonfire-e2e:local"
RUN_ID="e2e-$(date +%Y%m%d-%H%M%S)"
OUT_DIR="$REPO_ROOT/.e2e-runs/$RUN_ID"

mkdir -p "$OUT_DIR"

echo "==> Building box image"
docker build \
  -t "$IMAGE_TAG" \
  -f "$REPO_ROOT/tests/e2e/Dockerfile" \
  "$REPO_ROOT/tests/e2e"

echo "==> Running box — run_id=$RUN_ID wave=$WAVE fixture=$FIXTURE_REF"
docker run --rm \
  --env-file "$REPO_ROOT/.env" \
  -e RUN_ID="$RUN_ID" \
  -e WAVE="$WAVE" \
  -e FIXTURE_REF="$FIXTURE_REF" \
  -v "$OUT_DIR:/workspace/out" \
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
