#!/usr/bin/env bash
# Container-side Bonfire E2E runner.
# Clones the fixture, drives Bonfire via Claude CLI, verifies the result.
#
# SCAFFOLD. Exact claude-cli invocation and verdict writer to be completed by
# BON-359 once the fixture repo (BON-360) exposes gate/check-verdict.sh and
# ships a deterministic fixture ticket. This file stands as the interface
# contract between the host driver, the fixture, and the verdict schema.

set -euo pipefail

: "${ANTHROPIC_API_KEY:?required}"
: "${RUN_ID:?required}"
: "${WAVE:?required}"
: "${FIXTURE_REF:=main}"

FIXTURE_REPO="https://github.com/BonfireAI/bonfire-e2e-fixture.git"
OUT_DIR="/workspace/out"

mkdir -p "$OUT_DIR"

echo "==> Cloning fixture ($FIXTURE_REPO @ $FIXTURE_REF)"
git clone "$FIXTURE_REPO" /workspace/target
cd /workspace/target
git checkout "$FIXTURE_REF"

echo "==> Driving Bonfire via Claude CLI"
# TODO(BON-359): finalize the exact invocation.
# Expected shape (subject to claude-cli current syntax):
#
#   claude -p "$(cat <<'PROMPT'
#   Install bonfire-ai from PyPI into a fresh venv.
#   Run: bonfire scan .
#   Then: bonfire run "<ticket>" (ticket text from fixture spec).
#   Do not modify files under tests/. Report the PR branch URL.
#   PROMPT
#   )"
#
# The fixture's README + gate/expected-assertions.yaml declare the exact ticket text.

echo "==> Running post-run verification"
# TODO(BON-359): invoke fixture's gate/check-verdict.sh and write verdict.json to $OUT_DIR.
#
#   bash gate/check-verdict.sh \
#     --run-id "$RUN_ID" \
#     --wave "$WAVE" \
#     --fixture-ref "$FIXTURE_REF" \
#     --out "$OUT_DIR/verdict.json"

echo "==> Verdict will be at $OUT_DIR/verdict.json when BON-359 completes the scaffold."
