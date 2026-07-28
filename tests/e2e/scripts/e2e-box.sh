#!/usr/bin/env bash
# Host-side Bonfire E2E release-gate box driver.
#
# WHAT THIS BOX TESTS
# -------------------
# The artifact under test is a WHEEL BUILT FROM THIS WORKING TREE — never a
# PyPI download. The driver builds it host-side, records its identity (file
# name, version, sha256, source commit, dirty flag) into
# `<run>/artifact-under-test.json`, and bind-mounts it into the container at
# /workspace/artifact. The container-side runner installs THAT wheel, verifies
# the installed version and hash match the manifest, and then executes the
# real `bonfire` CLI against the fixture ticket. A verdict therefore always
# names the exact artifact it graded.
#
# AUTH
# ----
# Auto-detected at startup:
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
# CREDENTIAL ISOLATION (unchanged, load-bearing)
# ---------------------------------------------
# No host git/SSH/gh credential ever enters the box. The fixture is cloned on
# the host; the wheel is built on the host; the container sees three bind
# mounts and nothing else.
#
# Emits verdict.json and exits non-zero when the verdict is FAIL.
#
# Usage: tests/e2e/scripts/e2e-box.sh <wave> [fixture-ref]
#
# Environment knobs (all optional):
#   BOX_BUILD_CACHE=auto|off   Docker layer-cache policy. Default `auto`
#                              (fast, reuses layers). A release-gate
#                              certification run MUST use `off` — see
#                              docs/release-gates.md § "Build cache policy".
#   BOX_PIP_CACHE=warm|off     In-box pip download cache. Default `warm`
#                              (a host directory shared by every run, so the
#                              dependency wheels are fetched once). `off`
#                              forces a cold download on every run.
#   BONFIRE_WHEEL=<path>       Skip the build; test this exact wheel instead.
#   FIXTURE_URL=<git url>      Fixture remote (defaults to HTTPS).
#   FIXTURE_SRC_DIR=<path>     Pre-cloned fixture checkout to copy from.
#   BONFIRE_RUN_BUDGET_USD     Budget passed to `bonfire run` (default 5.00).
#   BONFIRE_RUN_TIMEOUT_SEC    Wall clock cap on `bonfire run` (default 1800).
#   BONFIRE_WORKFLOW           Workflow plan name (default standard_build).

set -euo pipefail

WAVE="${1:-}"
FIXTURE_REF="${2:-main}"

# <wave> is carried into box-run.json and verdict.json as an INTEGER (the
# verdict schema types it that way), and both records are written by `int(wave)`
# in Python. Validate it here, before the wheel build, the image build and the
# fixture clone: an unvalidated decimal label like `9.1` — which this project's
# own docs use for waves — otherwise dies on a raw traceback after all that
# work, and inside the box it would make the emitter that promises to ALWAYS
# write a verdict.json raise instead. A MISSING or empty argument takes the same
# usage exit rather than bash's `${1:?…}` status of 1 — 1 is the FAIL code, and
# an automation wrapper keying on it would file a usage error as a red gate.
if [[ ! "$WAVE" =~ ^[0-9]+$ ]]; then
    echo "FAIL: <wave> must be a whole number (got: ${WAVE:-<missing>})" >&2
    echo "  Usage: e2e-box.sh <wave> [fixture-ref]. The verdict records the wave" >&2
    echo "  as an integer; for a decimal label such as 9.1, pass 9." >&2
    exit 7
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

IMAGE_TAG="bonfire-e2e:local"
RUN_ID="e2e-$(date +%Y%m%d-%H%M%S)"
OUT_DIR="$REPO_ROOT/.e2e-runs/$RUN_ID"
ARTIFACT_DIR="$OUT_DIR/artifact"
ARTIFACT_MANIFEST="$OUT_DIR/artifact-under-test.json"
BUILD_CACHE="${BOX_BUILD_CACHE:-auto}"

case "$BUILD_CACHE" in
    auto | off) ;;
    *)
        echo "FAIL: BOX_BUILD_CACHE must be 'auto' or 'off' (got: $BUILD_CACHE)" >&2
        exit 7
        ;;
esac

# In-box pip download cache, persisted on the host across runs.
#
# The three in-box pip steps pull roughly 86 MB of dependency wheels, and a
# container is `--rm`, so without a mounted cache every run re-downloads all
# of it. On the degraded link measured on 2026-07-27 (13 KiB/s) that alone is
# the difference between a gate that runs and a gate that never starts.
#
# This cannot launder a bad artifact. The wheel under test is installed by
# explicit path from the read-only /workspace/artifact mount and is never
# resolved from an index, so it is never a cache entry; step 3 re-lands it
# with --force-reinstall regardless. What the cache holds is the DEPENDENCY
# set, and every dependency is still verified against the artifact's own
# Requires-Dist by the dependency-floor proof inside the box.
#
# `off` is kept for the operator who wants a cold-download run, and it is
# separate from BOX_BUILD_CACHE on purpose: that knob governs Docker layers,
# this one governs PyPI downloads, and a certification run may want either.
PIP_CACHE_MODE="${BOX_PIP_CACHE:-warm}"
case "$PIP_CACHE_MODE" in
    warm | off) ;;
    *)
        echo "FAIL: BOX_PIP_CACHE must be 'warm' or 'off' (got: $PIP_CACHE_MODE)" >&2
        exit 7
        ;;
esac
PIP_CACHE_DIR_HOST="$REPO_ROOT/.e2e-runs/pip-cache"

mkdir -p "$ARTIFACT_DIR"
# Lock OUT_DIR to the operator only — it holds the per-run OAuth credentials
# copy (mode 0600 file inside) plus claude-stream artifacts. Default umask
# (0022) leaves the directory listing world-readable; tighten to 0700 so the
# directory contents can't be enumerated by other host users.
chmod 0700 "$OUT_DIR"

# Host interpreter used for the wheel build and for reading JSON back out.
# Prefer the repo's own venv when present: it already carries the build
# toolchain the maintainer uses, so the wheel is produced the same way a
# release wheel is.
PY_HOST="python3"
if [ -x "$REPO_ROOT/.venv/bin/python" ]; then
    PY_HOST="$REPO_ROOT/.venv/bin/python"
fi

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
    # Copy ONLY the claudeAiOauth block into the container-mounted credential
    # file. The host's ~/.claude/.credentials.json also holds unrelated OAuth
    # tokens (e.g. designOauth, and mcpOAuth for third-party integrations);
    # none of those belong in the box. claude-cli reads and refreshes only the
    # claudeAiOauth block, so the stripped file is sufficient for in-container
    # auth while carrying no unrelated secrets. Create the file empty at mode
    # 0600 BEFORE writing the token so it is never momentarily world-readable
    # ('w' truncates but preserves the pre-set mode).
    : > "$OAUTH_COPY"
    chmod 0600 "$OAUTH_COPY"
    "$PY_HOST" - "$HOME/.claude/.credentials.json" "$OAUTH_COPY" <<'PY'
import json
import sys

src, dst = sys.argv[1], sys.argv[2]
with open(src, encoding="utf-8") as fh:
    creds = json.load(fh)
if "claudeAiOauth" not in creds:
    sys.exit("FAIL: no claudeAiOauth block in " + src)
with open(dst, "w", encoding="utf-8") as fh:
    json.dump({"claudeAiOauth": creds["claudeAiOauth"]}, fh)
PY
    AUTH_ARGS+=(-v "$OAUTH_COPY:/home/box/.claude/.credentials.json")
    echo "==> Auth mode: Claude Max OAuth (claudeAiOauth block only, via $HOME/.claude/.credentials.json)"
else
    echo "FAIL: no auth available on host." >&2
    echo "  Provide ONE of:" >&2
    echo "    - $REPO_ROOT/.env containing ANTHROPIC_API_KEY=sk-… (API-key path)" >&2
    echo "    - $HOME/.claude/.credentials.json (Claude Max OAuth — run \`claude login\`)" >&2
    exit 2
fi

# ---------------------------------------------------------------------
# Build the artifact under test.
#
# THE seam this box was missing: what gets installed in the container is a
# wheel built from THIS tree, not `pip install bonfire-ai` from PyPI. The
# build happens host-side (the container has no source mount and no build
# toolchain guarantee), and the resulting wheel is delivered read-only.
# ---------------------------------------------------------------------
if [ -n "${BONFIRE_WHEEL:-}" ]; then
    if [ ! -f "$BONFIRE_WHEEL" ]; then
        echo "FAIL: BONFIRE_WHEEL=$BONFIRE_WHEEL is not a file." >&2
        exit 7
    fi
    echo "==> Artifact source: operator-supplied wheel $BONFIRE_WHEEL"
    cp "$BONFIRE_WHEEL" "$ARTIFACT_DIR/"
    ARTIFACT_ORIGIN="operator-supplied:$BONFIRE_WHEEL"
elif "$PY_HOST" -c 'import build' > /dev/null 2>&1; then
    echo "==> Artifact source: building wheel from $REPO_ROOT (python -m build)"
    "$PY_HOST" -m build --wheel --outdir "$ARTIFACT_DIR" "$REPO_ROOT"
    ARTIFACT_ORIGIN="build:$PY_HOST -m build --wheel"
else
    echo "==> Artifact source: building wheel from $REPO_ROOT (pip wheel --no-deps)"
    "$PY_HOST" -m pip wheel --no-deps --wheel-dir "$ARTIFACT_DIR" "$REPO_ROOT"
    ARTIFACT_ORIGIN="pip:$PY_HOST -m pip wheel --no-deps"
fi

WHEELS=()
for wheel_candidate in "$ARTIFACT_DIR"/*.whl; do
    [ -e "$wheel_candidate" ] || continue
    WHEELS+=("$wheel_candidate")
done
if [ "${#WHEELS[@]}" -ne 1 ]; then
    echo "FAIL: expected exactly one wheel in $ARTIFACT_DIR, found ${#WHEELS[@]}." >&2
    echo "  A release-gate run must be unambiguous about which artifact it tested." >&2
    exit 7
fi
WHEEL_PATH="${WHEELS[0]}"

SRC_COMMIT="unknown"
SRC_DIRTY="unknown"
if git -C "$REPO_ROOT" rev-parse --git-dir > /dev/null 2>&1; then
    SRC_COMMIT="$(git -C "$REPO_ROOT" rev-parse HEAD)"
    if [ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]; then
        SRC_DIRTY="true"
    else
        SRC_DIRTY="false"
    fi
fi

"$PY_HOST" - "$ARTIFACT_MANIFEST" "$WHEEL_PATH" "$SRC_COMMIT" "$SRC_DIRTY" "$ARTIFACT_ORIGIN" <<'PY'
import hashlib
import json
import os
import sys

manifest_path, wheel_path, commit, dirty, origin = sys.argv[1:6]
name = os.path.basename(wheel_path)
digest = hashlib.sha256()
with open(wheel_path, "rb") as fh:
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        digest.update(chunk)
parts = name.split("-")
manifest = {
    "wheel": name,
    "distribution": parts[0],
    "version": parts[1] if len(parts) > 1 else "unknown",
    "sha256": digest.hexdigest(),
    "source_commit": commit,
    "source_dirty": dirty,
    "built_by": origin,
}
with open(manifest_path, "w", encoding="utf-8") as fh:
    json.dump(manifest, fh, indent=2)
print(
    "==> Artifact under test: {wheel} (version {version}) "
    "from commit {short} dirty={dirty}".format(
        wheel=manifest["wheel"],
        version=manifest["version"],
        short=commit[:12],
        dirty=dirty,
    )
)
PY

# ---------------------------------------------------------------------
# Image build. Cache policy is explicit and operator-controlled — a run
# meant to prove clean install must not be served from day-old layers.
# ---------------------------------------------------------------------
BUILD_ARGS=()
# Pass the operator's UID/GID so the in-container `box` user owns
# bind-mounted output directories cleanly. Defaults inside the Dockerfile
# preserve the UID 1000 path used by the GitHub Actions runner.
BUILD_ARGS+=(--build-arg "BOX_UID=$(id -u)")
BUILD_ARGS+=(--build-arg "BOX_GID=$(id -g)")
if [ "$BUILD_CACHE" = "off" ]; then
    echo "==> Build cache: OFF — --no-cache --pull (release-grade clean build)"
    BUILD_ARGS+=(--no-cache --pull)
else
    echo "==> Build cache: auto — layers may be reused."
    echo "    A release-gate certification run MUST set BOX_BUILD_CACHE=off."
fi

echo "==> Building box image"
docker build \
    "${BUILD_ARGS[@]}" \
    -t "$IMAGE_TAG" \
    -f "$REPO_ROOT/tests/e2e/Dockerfile" \
    "$REPO_ROOT/tests/e2e"

IMAGE_ID="$(docker image inspect --format '{{.Id}}' "$IMAGE_TAG")"

FIXTURE_DIR="$OUT_DIR/target"
# Fixture source. Materialized host-side and bind-mounted into the container, so
# no host credential (SSH key, gh token, git credential helper) ever enters the
# box — the credential-isolation property. Transport is configurable so the box
# runs in HTTPS-only / no-SSH environments:
#   - FIXTURE_SRC_DIR: path to a pre-cloned fixture checkout. Cloned locally (a
#     throwaway per-run copy) so the operator's source dir is never mutated and
#     no network fetch is needed at all.
#   - FIXTURE_URL: remote to clone from. Defaults to HTTPS (the gh token
#     authenticates it via git's credential helper); the historical SSH URL
#     required an SSH key on the host and dies with "Permission denied
#     (publickey)" on a keyless box.
FIXTURE_URL="${FIXTURE_URL:-https://github.com/BonfireAI/bonfire-e2e-fixture.git}"
if [ -n "${FIXTURE_SRC_DIR:-}" ]; then
    echo "==> Cloning fixture from pre-cloned FIXTURE_SRC_DIR=$FIXTURE_SRC_DIR (host-side; credentials never enter the box)"
    git clone "$FIXTURE_SRC_DIR" "$FIXTURE_DIR"
else
    echo "==> Cloning fixture on host ($FIXTURE_URL — credentials never enter the box)"
    git clone "$FIXTURE_URL" "$FIXTURE_DIR"
fi
(cd "$FIXTURE_DIR" && git checkout "$FIXTURE_REF")

# Run-level provenance the verdict cannot forge: which image, which cache
# policy, which fixture ref, which auth mode.
"$PY_HOST" - "$OUT_DIR/box-run.json" "$RUN_ID" "$WAVE" "$FIXTURE_REF" "$FIXTURE_URL" \
    "$IMAGE_TAG" "$IMAGE_ID" "$BUILD_CACHE" "$AUTH_MODE" <<'PY'
import json
import sys

(
    out_path,
    run_id,
    wave,
    fixture_ref,
    fixture_url,
    image_tag,
    image_id,
    build_cache,
    auth_mode,
) = sys.argv[1:10]
record = {
    "run_id": run_id,
    "wave": int(wave),
    "fixture": {"url": fixture_url, "ref": fixture_ref},
    "image": {"tag": image_tag, "id": image_id, "build_cache": build_cache},
    "auth_mode": auth_mode,
}
with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(record, fh, indent=2)
PY

# Cache wiring, resolved here so the docker invocation below stays readable.
# `warm` mounts the shared host cache and points pip at it; `off` disables
# pip's cache entirely rather than merely leaving it unmounted, so an
# operator asking for cold gets cold and not a container-local cache that
# quietly warms within a single run.
PIP_CACHE_ARGS=()
if [ "$PIP_CACHE_MODE" = "warm" ]; then
    mkdir -p "$PIP_CACHE_DIR_HOST"
    PIP_CACHE_ARGS=(
        -v "$PIP_CACHE_DIR_HOST:/home/box/.cache/pip"
        -e PIP_CACHE_DIR=/home/box/.cache/pip
    )
    echo "==> Pip cache: warm ($PIP_CACHE_DIR_HOST)"
else
    PIP_CACHE_ARGS=(-e PIP_NO_CACHE_DIR=1)
    echo "==> Pip cache: off (every dependency re-downloaded)"
fi
echo "==> Running box — run_id=$RUN_ID wave=$WAVE fixture=$FIXTURE_REF auth=$AUTH_MODE"
# The artifact mount is read-only: the container installs from it and never
# writes to it. Integrity is not left to the mount flag — the runner
# re-computes the wheel's sha256 and compares it against the manifest before
# installing.
set +e
docker run --rm \
    "${AUTH_ARGS[@]}" \
    "${PIP_CACHE_ARGS[@]}" \
    -e RUN_ID="$RUN_ID" \
    -e WAVE="$WAVE" \
    -e FIXTURE_REF="$FIXTURE_REF" \
    -e BONFIRE_ARTIFACT_DIR=/workspace/artifact \
    -e BONFIRE_RUN_BUDGET_USD="${BONFIRE_RUN_BUDGET_USD:-5.00}" \
    -e BONFIRE_RUN_TIMEOUT_SEC="${BONFIRE_RUN_TIMEOUT_SEC:-1800}" \
    -e BONFIRE_WORKFLOW="${BONFIRE_WORKFLOW:-standard_build}" \
    -v "$OUT_DIR:/workspace/out" \
    -v "$FIXTURE_DIR:/workspace/target" \
    -v "$ARTIFACT_DIR:/workspace/artifact:ro" \
    "$IMAGE_TAG"
DOCKER_RC=$?
set -e

VERDICT_PATH="$OUT_DIR/verdict.json"

if [ ! -f "$VERDICT_PATH" ]; then
    echo "FAIL: no verdict emitted — box run incomplete (container exit $DOCKER_RC)." >&2
    exit 3
fi

# Read the verdict and print what it graded. Every field below is written by
# the container: the artifact identity, the command it ran, and the exit code
# that command returned.
"$PY_HOST" -c '
import json, sys
verdict = json.load(open(sys.argv[1], encoding="utf-8"))
artifact = verdict.get("artifact_under_test") or {}
execution = verdict.get("bonfire_execution") or {}
print("==> Artifact tested: {} sha256={}".format(
    artifact.get("wheel", "unknown"), (artifact.get("sha256") or "unknown")[:16]))
print("==> Source commit:   {} (dirty={})".format(
    artifact.get("source_commit", "unknown"), artifact.get("source_dirty", "unknown")))
print("==> Bonfire command: {}".format(execution.get("command", "NOT EXECUTED")))
print("==> Bonfire exit:    {}".format(execution.get("exit_code", "NOT EXECUTED")))
for reason in verdict.get("failure_reasons") or []:
    print("==> failure_reason:  {}".format(reason))
' "$VERDICT_PATH"

VERDICT="$("$PY_HOST" -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["verdict"])' "$VERDICT_PATH")"
echo "==> Verdict: $VERDICT"
echo "==> Artifact: $VERDICT_PATH"

# A PASS is only honoured when the container itself also exited clean. The
# arbitration is one-directional: this driver can turn a PASS into a failing
# exit code, never a FAIL into a passing one.
if [ "$VERDICT" = "PASS" ] && [ "$DOCKER_RC" -ne 0 ]; then
    echo "FAIL: verdict says PASS but the runner exited $DOCKER_RC — treating as FAIL." >&2
    exit 1
fi

[ "$VERDICT" = "PASS" ] || exit 1
