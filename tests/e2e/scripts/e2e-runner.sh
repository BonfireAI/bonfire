#!/usr/bin/env bash
# Container-side Bonfire E2E runner. ALWAYS emits a verdict.json.
#
# WHAT THIS RUNNER PROVES
# -----------------------
# The box exists to catch transfer errors — missed imports, broken wiring,
# packaging drift, composition-root bugs that unit tests miss. It can only do
# that if it INSTALLS AND EXECUTES the artifact under test. So it does, in
# this order:
#
#   install  the wheel built from the working tree (bind-mounted read-only at
#            /workspace/artifact), verified by sha256 against the host-written
#            manifest, version-checked against `import bonfire`, and traced
#            back to the mount through pip's own PEP 610 install record.
#   execute  the real `bonfire run` CLI against the fixture's ticket, from
#            /workspace/target, with stdout / stderr / exit code captured to
#            /workspace/out.
#   observe  a claude-cli session whose ONLY job is to diagnose what the run
#            did. It is forbidden to author Bonfire's artifacts, and a
#            before/after fingerprint of /workspace/target enforces that
#            mechanically.
#   grade    the fixture's gate/check-verdict.sh reads the on-disk artifacts,
#            then this runner merges artifact + execution provenance into the
#            verdict and forces FAIL if Bonfire itself failed.
#
# The last step is one-directional: the runner can turn a PASS into a FAIL,
# never a FAIL into a PASS.
#
# A bash trap guarantees a verdict.json is always written even on crash,
# signal, or early exit.
#
# See docs/box-operator.md for operator usage and docs/release-gates.md for the
# gate-tier protocol.

set -euo pipefail

# Auth mode is operator-selected: at least one of (a) ANTHROPIC_API_KEY env var
# or (b) mounted OAuth credentials at ~/.claude/.credentials.json must be
# present. The bare-cli flag was dropped from the claude invocation precisely
# so that claude-cli can fall back to OAuth when the env var is absent. See
# docs/box-operator.md for the operator-side path-selection logic.
# Both auth paths also serve `bonfire run`: the Claude Agent SDK shells out to
# the same pinned claude-cli, so the artifact under test dispatches with the
# same credentials and the same isolation.
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
# Presence is not shape. The verdict types `wave` as an integer and every
# emitter writes it with `int(wave)`, so a decimal label — this project's own
# docs say "Wave 9.1" — would make the emitter that promises to ALWAYS write a
# verdict raise instead. The driver checks this too; this check is what holds
# when an operator hand-runs the entrypoint under `docker run` and bypasses it.
if [[ ! "$WAVE" =~ ^[0-9]+$ ]]; then
    echo "FAIL: WAVE must be a whole number (got: $WAVE) — the verdict types it as an integer." >&2
    exit 7
fi
: "${FIXTURE_REF:=main}"
: "${BONFIRE_ARTIFACT_DIR:=/workspace/artifact}"
: "${BONFIRE_RUN_BUDGET_USD:=5.00}"
: "${BONFIRE_RUN_TIMEOUT_SEC:=1800}"
: "${BONFIRE_WORKFLOW:=standard_build}"

OUT_DIR="/workspace/out"
TARGET_DIR="/workspace/target"
VENV_DIR="$TARGET_DIR/.venv"
ARTIFACT_MANIFEST="$OUT_DIR/artifact-under-test.json"
VERDICT_PATH="$OUT_DIR/verdict.json"
EXECUTION_PATH="$OUT_DIR/bonfire-execution.json"
PHASE="init"
BONFIRE_VERSION="unknown"
FAILURE_REASONS=()
mkdir -p "$OUT_DIR"

# System interpreter, addressed by absolute path on purpose: this script
# prepends the fixture venv to PATH once the artifact is installed, and the
# venv's python is NOT guaranteed to carry PyYAML.
#
# SAFE PATH IS NOT OPTIONAL, AND IT IS NOT LOCAL TO THE PRE-FLIGHT PROOFS.
# Every interpreter this runner starts — system or venv, `-c`, `-m`, or a
# heredoc on stdin — is invoked with `-P`. The runner's cwd is
# /workspace/target, the FIXTURE worktree; without `-P` Python prepends that
# directory to sys.path[0], so a file dropped at the fixture root (`json.py`,
# `yaml.py`, `glob.py`, a `bonfire/` package, a `bonfire_ai-<ver>.dist-info/`)
# is imported ahead of the stdlib and ahead of site-packages by this script's
# OWN code.
#
# That is not a theoretical gap. The observer session (Phase 8) runs with
# --permission-mode bypassPermissions, and snapshot_target deliberately does
# not fingerprint untracked files, so an untracked module planted at the
# fixture root survives the Phase 9 comparison unchanged. Without `-P` the
# highest-value target is Phase 13: the verdict arbitration would import the
# planted `json`, and its `json.load`/`json.dump` could rewrite verdict.json to
# PASS with empty failure_reasons while the runner still exits 0. `-P` on every
# interpreter is what makes the untracked-file blind spot in the fingerprint
# harmless. If you add a Python invocation to this script, it carries `-P`.
SYS_PY="/usr/bin/python3"

set_phase() {
    PHASE="$1"
    echo "==> phase=$PHASE"
}

# Failure-mode verdict emitter. Writes a minimal but schema-conforming
# verdict.json with verdict=FAIL and failure_reasons populated. Idempotent on
# the FILE: if a verdict already exists (i.e. the gate script wrote one), that
# file is preserved rather than overwritten.
#
# It is deliberately NOT idempotent on the REASON. The reason is appended to
# FAILURE_REASONS before the preservation check, because a preserved file still
# has to end up naming why the runner aborted — the Phase 13 arbitration reads
# this array and merges it in. Recording it after the early return was how
# `gate_script_crashed` reached the Docker log and nothing else.
#
# Abort paths never reach the Phase 13 arbitration, so this emitter merges the
# provenance already on disk: absent files yield absent fields, nothing is
# invented, and the ALWAYS-writes-a-verdict guarantee survives a missing file.
emit_failure_verdict() {
    local reason="$1"
    local exit_code="$2"

    FAILURE_REASONS+=("$reason")

    if [[ -f "$VERDICT_PATH" ]]; then
        echo "==> verdict.json already present; not overwriting (incoming reason was: $reason)"
        return 0
    fi

    "$SYS_PY" -P - "$VERDICT_PATH" "$RUN_ID" "$WAVE" "$FIXTURE_REF" "$BONFIRE_VERSION" \
        "$ARTIFACT_MANIFEST" "$EXECUTION_PATH" \
        "${FAILURE_REASONS[@]}" "phase:$PHASE" "exit:$exit_code" <<'PY'
import json
import sys

(out_path, run_id, wave, fixture_ref, bonfire_version, manifest_path,
 execution_path, *reasons) = sys.argv[1:]


def load_provenance(path):
    """Return the JSON object already on disk at `path`, or None.

    Absence is not an error on an abort path — the file may simply not have
    been written yet. A payload that is not an object counts as absence too,
    so a truncated or garbage provenance file can never make this emitter,
    the last thing standing between a crash and a verdict, raise.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


verdict = {
    "run_id": run_id,
    "wave": int(wave),
    "bonfire_version": bonfire_version,
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

# Name what was graded. The manifest is the driver's BUILD record and it is
# carried through whole — digest included. An abort path is exactly when the
# operator most needs to know which wheel the run was pointed at, so nothing
# here is withheld; `bonfire_version` is simply never read from it, because the
# version the verdict reports must come from the INSTALLED distribution.
manifest = load_provenance(manifest_path)
if manifest is not None:
    verdict["artifact_under_test"] = manifest
execution = load_provenance(execution_path)
if execution is not None:
    verdict["bonfire_execution"] = execution
    for verdict_key, execution_key in (
        ("bonfire_stdout_path", "stdout_path"),
        ("bonfire_stderr_path", "stderr_path"),
        ("session_log_path", "session_log_path"),
    ):
        value = execution.get(execution_key)
        if value is not None:
            verdict["artifacts"][verdict_key] = value

with open(out_path, "w", encoding="utf-8") as fh:
    json.dump(verdict, fh, indent=2)
print(f"==> emitted FAIL verdict: {out_path} reasons={reasons}", file=sys.stderr)
PY
}

# Fingerprint of everything the observer session must not move: the committed
# tip, the branch set, the tracked-file diff, and every byte Bonfire wrote
# under .bonfire/. Untracked scratch (pytest caches, the venv) is deliberately
# excluded — the observer is allowed to run the suite, not to author results.
#
# That exclusion is a real blind spot, named here rather than wished away: an
# untracked file the observer creates at the fixture root is invisible to this
# comparison. It is made harmless upstream, not here — every interpreter this
# runner starts runs with `-P` (see SYS_PY), so an untracked module at the
# fixture root can never be imported by the runner's own Python. Widening the
# fingerprint to all untracked files instead would fail every run on pytest
# caches and the venv the observer is explicitly allowed to create.
snapshot_target() {
    local dest="$1"
    {
        git -C "$TARGET_DIR" rev-parse HEAD
        git -C "$TARGET_DIR" for-each-ref --format='%(refname:short) %(objectname)' refs/heads
        git -C "$TARGET_DIR" diff --name-status HEAD
        # Guarded rather than error-suppressed: `set -o pipefail` would turn a
        # missing directory into a runner abort, and `|| true` would hide a
        # genuine hashing failure.
        if [ -d "$TARGET_DIR/.bonfire" ]; then
            find "$TARGET_DIR/.bonfire" -type f -print0 | sort -z | xargs -0 -r sha256sum
        fi
    } > "$dest"
}

# Run one pip step, logging to a single install log; abort with a named
# failure reason when it breaks. A packaging break IS a gate failure.
install_step() {
    local label="$1"
    shift
    if ! "$@" >> "$OUT_DIR/pip-install.log" 2>&1; then
        echo "FAIL: pip step '$label' failed — see pip-install.log" >&2
        emit_failure_verdict "artifact_install_failed:$label" 8
        exit 8
    fi
}

# Trap: any non-zero exit (including SIGTERM/SIGINT) routes through here.
# shellcheck disable=SC2154  # rc is assigned by 'rc=$?' at trap-fire time
trap 'rc=$?; if [[ $rc -ne 0 ]]; then emit_failure_verdict "trap:nonzero_exit" "$rc"; fi' EXIT
trap 'emit_failure_verdict "trap:sigterm" 143; exit 143' TERM
trap 'emit_failure_verdict "trap:sigint" 130; exit 130' INT

# ---------------------------------------------------------------------
# Phase 0: verify fixture is mounted
# ---------------------------------------------------------------------
set_phase "verify_fixture_mounted"
if [[ ! -d "$TARGET_DIR/.git" ]]; then
    echo "FAIL: $TARGET_DIR not mounted — host must clone fixture via e2e-box.sh before docker run." >&2
    emit_failure_verdict "fixture_not_mounted" 4
    exit 4
fi
cd "$TARGET_DIR"

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
# Phase 4: install the artifact under test
#
# The wheel comes from the host bind-mount, NOT from PyPI. Its identity is
# fixed by the manifest the host wrote; the hash check makes a swapped or
# shadowed artifact a hard failure rather than a silent one.
# ---------------------------------------------------------------------
set_phase "install_artifact_under_test"
if [[ ! -f "$ARTIFACT_MANIFEST" ]]; then
    echo "FAIL: no artifact manifest at $ARTIFACT_MANIFEST — driver did not build a wheel." >&2
    emit_failure_verdict "artifact_manifest_missing" 8
    exit 8
fi

WHEEL_NAME="$("$SYS_PY" -P -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["wheel"])' "$ARTIFACT_MANIFEST")"
WHEEL_VERSION="$("$SYS_PY" -P -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["version"])' "$ARTIFACT_MANIFEST")"
WHEEL_SHA_EXPECTED="$("$SYS_PY" -P -c 'import json,sys; print(json.load(open(sys.argv[1], encoding="utf-8"))["sha256"])' "$ARTIFACT_MANIFEST")"
WHEEL_PATH="$BONFIRE_ARTIFACT_DIR/$WHEEL_NAME"

if [[ ! -f "$WHEEL_PATH" ]]; then
    echo "FAIL: artifact wheel $WHEEL_NAME not present at $BONFIRE_ARTIFACT_DIR." >&2
    emit_failure_verdict "artifact_wheel_not_mounted:$WHEEL_NAME" 8
    exit 8
fi

WHEEL_SHA_ACTUAL="$(sha256sum "$WHEEL_PATH" | cut -d' ' -f1)"
if [[ "$WHEEL_SHA_ACTUAL" != "$WHEEL_SHA_EXPECTED" ]]; then
    echo "FAIL: wheel sha256 mismatch — mounted artifact is not the one the driver built." >&2
    emit_failure_verdict "artifact_hash_mismatch:$WHEEL_NAME" 8
    exit 8
fi
echo "==> artifact under test: $WHEEL_NAME (version $WHEEL_VERSION, sha256 ${WHEEL_SHA_ACTUAL:0:16})"

"$SYS_PY" -P -m venv "$VENV_DIR"
export VIRTUAL_ENV="$VENV_DIR"
export PATH="$VENV_DIR/bin:$PATH"

# Install order, and why the last step is forced.
#
# pip does NOT reinstall a local wheel whose version already matches an
# installed distribution: it logs "already installed with the same version as
# the provided wheel. Use --force-reinstall..." and exits 0. So "artifact last"
# alone does not win the venv — if anything the fixture pulls resolves a
# same-versioned `bonfire-ai` off an index, a plain artifact install is a
# silent no-op and the mounted wheel is never consumed.
#
#   1. artifact-and-deps   — the wheel AND its own requirements resolve into a
#                            clean venv, before the fixture has spoken. The
#                            label names the artifact on purpose: this command
#                            installs the wheel itself, so a wheel that cannot
#                            install at all fails HERE, and
#                            `artifact_install_failed:artifact-and-deps` must
#                            not read to an operator as a dependency-resolution
#                            problem.
#   2. fixture-deps        — the fixture's dev extras layer on top; a pin here
#                            may replace bonfire-ai with an index copy.
#   3. artifact-under-test — --force-reinstall puts the mounted wheel back
#                            unconditionally; --no-deps keeps that forced step
#                            surgical, so it cannot re-resolve (and thereby
#                            disturb) anything the fixture pinned. Step 3
#                            therefore re-lands only the wheel — never the
#                            dependency set, which is why the dependency-floor
#                            proof below exists.
#
# Step 3 is what makes "the artifact wins" a fact rather than a hope; the
# provenance assertion below is what proves it happened.
install_step "artifact-and-deps" "$VENV_DIR/bin/python" -P -m pip install \
    --disable-pip-version-check --no-input "$WHEEL_PATH"
install_step "fixture-deps" "$VENV_DIR/bin/python" -P -m pip install \
    --disable-pip-version-check --no-input -e "$TARGET_DIR[dev]"
install_step "artifact-under-test" "$VENV_DIR/bin/python" -P -m pip install \
    --disable-pip-version-check --no-input --force-reinstall --no-deps "$WHEEL_PATH"
"$VENV_DIR/bin/python" -P -m pip freeze > "$OUT_DIR/pip-freeze.txt" 2>&1 || true

# `python -P` (safe path) here for the same reason it is everywhere else in this
# script (see SYS_PY): the interpreter must NOT prepend the cwd
# (/workspace/target — the FIXTURE worktree) to sys.path. For these particular
# checks the stake is direct — a `bonfire/` package or a
# `bonfire_ai-<ver>.dist-info/` sitting at the fixture root would be found ahead
# of site-packages by both `import bonfire` and `Distribution.from_name`, so the
# checks whose whole point is "nothing shadowed the mounted wheel" would
# themselves be shadowable. The graded command is a console script, which is not
# exposed this way, so the proofs must not be weaker than the thing they prove.
#
# Import smoke: the cheapest catch for a missed import or a packaging omission.
if ! "$VENV_DIR/bin/python" -P -c 'import bonfire; print(bonfire.__version__)' \
    > "$OUT_DIR/bonfire-import.txt" 2>&1; then
    echo "FAIL: 'import bonfire' failed against the installed wheel." >&2
    emit_failure_verdict "artifact_import_failed" 8
    exit 8
fi
BONFIRE_VERSION="$(tail -n1 "$OUT_DIR/bonfire-import.txt")"

# Console-script smoke: resolves the entry point and walks the CLI
# composition root. A broken Typer app dies here, before any spend.
if ! "$VENV_DIR/bin/bonfire" --version > "$OUT_DIR/bonfire-version.txt" 2>&1; then
    echo "FAIL: 'bonfire --version' failed — console script or CLI import is broken." >&2
    emit_failure_verdict "artifact_cli_entrypoint_failed" 8
    exit 8
fi

if [[ "$BONFIRE_VERSION" != "$WHEEL_VERSION" ]]; then
    echo "FAIL: installed bonfire $BONFIRE_VERSION != wheel version $WHEEL_VERSION." >&2
    emit_failure_verdict "artifact_version_mismatch:installed=$BONFIRE_VERSION,wheel=$WHEEL_VERSION" 8
    exit 8
fi

# Provenance: WHICH distribution actually landed in the venv?
#
# The version check above is necessary but not sufficient. A `bonfire-ai`
# resolved from an index can carry the same version string as the wheel under
# test and satisfy it while the mounted artifact was never installed at all;
# the sha256 check upstream only proves the mounted FILE is intact, not that
# pip consumed it. pip writes a PEP 610 `direct_url.json` into the
# `.dist-info/` of every wheel/path install and writes NONE for an index
# install, so both its presence and its url are the assertion: the installed
# distribution must trace back to THE wheel this runner already pinned from the
# manifest and verified by sha256 — not merely to some file under the mount,
# which would lean on a one-wheel invariant enforced in another script.
#
# Run under the venv interpreter — the installed metadata is the venv's, not
# the system interpreter's — and under -P, so the fixture worktree cannot plant
# a .dist-info that answers this question.
if ! "$VENV_DIR/bin/python" -P - "$WHEEL_PATH" \
    > "$OUT_DIR/bonfire-direct-url.json" 2> "$OUT_DIR/bonfire-direct-url.err" <<'PY'
import json
import sys
from importlib.metadata import Distribution, PackageNotFoundError
from pathlib import Path
from urllib.parse import unquote, urlparse

expected_wheel = Path(sys.argv[1]).resolve()
try:
    dist = Distribution.from_name("bonfire-ai")
except PackageNotFoundError:
    sys.exit("no installed distribution named 'bonfire-ai' in the fixture venv")

raw = dist.read_text("direct_url.json")
if raw is None:
    sys.exit(
        "installed bonfire-ai carries no direct_url.json: pip resolved it from an "
        "index, not from the mounted artifact"
    )
record = json.loads(raw)
url = str(record.get("url") or "")
parsed = urlparse(url)
if parsed.scheme != "file":
    sys.exit("installed bonfire-ai did not come from a local file: " + (url or "<no url>"))
installed_from = Path(unquote(parsed.path)).resolve()
if installed_from != expected_wheel:
    sys.exit(
        "installed bonfire-ai came from {} — not the manifest-pinned, "
        "hash-verified wheel at {}".format(installed_from, expected_wheel)
    )
json.dump(record, sys.stdout, indent=2)
PY
then
    echo "FAIL: the installed bonfire-ai is not the mounted wheel under test." >&2
    cat "$OUT_DIR/bonfire-direct-url.err" >&2
    emit_failure_verdict "artifact_provenance_failed" 8
    exit 8
fi

# Dependency floors: does the venv still satisfy what the artifact REQUIRES?
#
# Step 3 re-lands the wheel with --no-deps. That is deliberate — the forced
# reinstall must not re-resolve what the fixture pinned — but it is one-sided:
# it repairs the artifact and never the dependency set. Step 2 can legitimately
# drag a shared runtime dep below the wheel's floor (the fixture carries a
# bonfire_version_constraint, so a pin that resolves an older index copy of
# bonfire-ai, which in turn pulls e.g. pydantic down, is a live path). pip only
# WARNS about the resulting inconsistency and exits 0, so install_step passes,
# and nothing reads warnings out of pip-install.log. `import bonfire` and
# `bonfire --version` can both still succeed. The breakage would first appear
# during `bonfire run` and Phase 13 would attribute it to the artifact — a RED
# naming the wrong layer, on the one gate whose product is naming the layer.
#
# Scoped to bonfire-ai's own Requires-Dist on purpose: a whole-environment
# `pip check` would fail this gate on unrelated fixture breakage, which is the
# same mis-attribution pointing the other way.
#
# CONTROL ROD. This assertion SELECTS the set it then grades: it iterates
# `dist.requires`, so an artifact that declares no base requirements makes the
# loop body run zero times, leaves `problems` empty, exits 0 and reports a green
# floor having checked nothing — a gate gone vacuous by the value it guards.
# That is not hypothetical here: a `dependencies = [...]` block dropped from
# pyproject.toml is packaging drift of exactly the class this box exists to
# catch, and every other proof would stay green through it because the fixture's
# own dev extras still put pydantic/typer/pyyaml in the venv. So the script
# asserts `checked > 0` explicitly and names the empty set as its own failure.
if ! "$VENV_DIR/bin/python" -P - \
    > "$OUT_DIR/bonfire-dependency-check.txt" 2> "$OUT_DIR/bonfire-dependency-check.err" <<'PY'
import sys
from importlib.metadata import Distribution, PackageNotFoundError, version

try:
    from packaging.requirements import Requirement
except ModuleNotFoundError:
    # `packaging` is not a bonfire-ai runtime requirement, so its presence is an
    # accident of the fixture's dev extras. pip vendors the same library and pip
    # is guaranteed inside a venv, so fall back rather than skip the proof —
    # a silently skipped assertion is the failure mode this check exists to end.
    try:
        from pip._vendor.packaging.requirements import Requirement
    except ModuleNotFoundError:
        sys.exit("no requirement parser available: neither packaging nor pip's vendored copy")

dist = Distribution.from_name("bonfire-ai")
problems = []
checked = 0
for raw in dist.requires or []:
    req = Requirement(raw)
    # Requirements belonging to an extra the box never installed carry an
    # `extra == "..."` marker; evaluating against an empty extra drops them and
    # leaves exactly the base dependency set the artifact always needs.
    if req.marker is not None and not req.marker.evaluate({"extra": ""}):
        continue
    checked += 1
    try:
        installed = version(req.name)
    except PackageNotFoundError:
        problems.append("{}: required by bonfire-ai, not installed".format(req.name))
        continue
    if req.specifier and not req.specifier.contains(installed, prereleases=True):
        problems.append("{}=={} does not satisfy '{}'".format(req.name, installed, raw))
    else:
        print("{}=={} satisfies '{}'".format(req.name, installed, raw))
# Control rod: an empty base-requirement set means this proof selected nothing
# and would pass by checking nothing. Fail on it explicitly — bonfire-ai always
# declares base runtime dependencies, so zero of them is packaging drift in the
# artifact's own metadata, not a clean environment.
if checked == 0:
    problems.append(
        "the installed bonfire-ai declares no base Requires-Dist: this proof "
        "selected an empty set and would have passed without checking a single "
        "floor — the wheel lost its dependency metadata (packaging drift)"
    )
print("checked {} base requirement(s)".format(checked))
if problems:
    sys.exit("; ".join(problems))
PY
then
    echo "FAIL: the installed dependency set does not satisfy the artifact's requirements." >&2
    cat "$OUT_DIR/bonfire-dependency-check.err" >&2
    emit_failure_verdict "artifact_dependency_floor_violated" 8
    exit 8
fi

# ---------------------------------------------------------------------
# Phase 5: resolve the ticket from the fixture
#
# `ticket_text` in the fixture's expected-assertions.yaml IS the ticket the
# artifact under test must ship. The runner reads it so the prompt cannot
# paraphrase it.
# ---------------------------------------------------------------------
set_phase "resolve_ticket"
ASSERTIONS_YAML="$TARGET_DIR/gate/expected-assertions.yaml"
if [[ ! -f "$ASSERTIONS_YAML" ]]; then
    echo "FAIL: fixture has no gate/expected-assertions.yaml." >&2
    emit_failure_verdict "fixture_expected_assertions_missing" 9
    exit 9
fi

if ! "$SYS_PY" -P - "$ASSERTIONS_YAML" > "$OUT_DIR/ticket-text.txt" 2> "$OUT_DIR/ticket-text.err" <<'PY'
import sys

import yaml

with open(sys.argv[1], encoding="utf-8") as fh:
    data = yaml.safe_load(fh) or {}
text = str(data.get("ticket_text") or "").strip()
if not text:
    sys.exit("no non-empty ticket_text in " + sys.argv[1])
constraint = str(data.get("bonfire_version_constraint") or "").strip()
if constraint:
    print(
        "NOTE: fixture sets bonfire_version_constraint=%r; the box ignores it — "
        "the artifact under test is the wheel built from the working tree." % constraint,
        file=sys.stderr,
    )
sys.stdout.write(text)
PY
then
    echo "FAIL: could not read ticket_text from $ASSERTIONS_YAML." >&2
    cat "$OUT_DIR/ticket-text.err" >&2
    emit_failure_verdict "fixture_ticket_text_missing" 9
    exit 9
fi
TICKET_TEXT="$(cat "$OUT_DIR/ticket-text.txt")"

# ---------------------------------------------------------------------
# Phase 6: EXECUTE the artifact under test
#
# This is the assertion the box existed to make and never made. The three
# artifacts the fixture's gate grades — .bonfire/costs.jsonl,
# .bonfire/sessions/<id>.jsonl, .bonfire/review-verdict.json — must be
# written by THIS command. Nothing downstream transcribes them.
#
# Persistence steering, stated as it actually behaves today rather than as the
# box would like it to behave:
#
#   BONFIRE_COST_LEDGER_PATH is honoured by the READ side only — `bonfire cost`
#   builds its analyzer from it. The writer (CostLedgerConsumer) takes its
#   ledger path as a constructor default and never consults the environment, so
#   this export does NOT redirect where the ledger lands. It is set anyway
#   because it is the documented knob and because it makes the box's intent
#   inspectable; it is not the reason the artifact appears (or does not).
#
#   There is deliberately no session-directory export, and the honest reason is
#   narrower than "there is no such knob". The knob EXISTS in the config schema:
#   VaultConfig.session_dir defaults to exactly ".bonfire/sessions" and mounts
#   on BonfireSettings as `memory`, so it is addressable as `[memory]
#   session_dir` in bonfire.toml or as BONFIRE_MEMORY__SESSION_DIR. It is simply
#   UNWIRED — SessionPersistence takes session_dir as a constructor argument and
#   nothing in this tree passes the loaded setting into it, so setting the key
#   steers nothing. (BONFIRE_CHECKPOINT_DIR is wired, but it steers engine
#   checkpoints under ~/.bonfire/checkpoints — a different artifact from the
#   .bonfire/sessions/<id>.jsonl log the fixture gate reads.) Exporting a key
#   that is declared but unconsumed would be dead configuration dressed as a
#   control; wiring it is product work, not box work.
#
# What actually resolves "where did it go" is the inventory captured right
# after the run: the runner grades what landed on disk, in either root.
# ---------------------------------------------------------------------
set_phase "run_bonfire"
export BONFIRE_COST_LEDGER_PATH=/workspace/target/.bonfire/costs.jsonl
# Pre-create the directory the fixture gate reads so an empty result is a real
# absence rather than a missing-parent artefact of the box.
mkdir -p /workspace/target/.bonfire/sessions

# Recorded verbatim and copy-pasteable: the ticket text is long and often
# multi-line, so the command references the captured file rather than
# inlining a quoted blob nobody can re-run.
BONFIRE_COMMAND="cd /workspace/target && .venv/bin/bonfire run \"\$(cat /workspace/out/ticket-text.txt)\" --budget $BONFIRE_RUN_BUDGET_USD --workflow $BONFIRE_WORKFLOW"
printf '%s\n' "$BONFIRE_COMMAND" > "$OUT_DIR/bonfire-command.txt"
BONFIRE_START_TS="$(date +%s)"

set +e
timeout --signal=TERM --kill-after=30s "${BONFIRE_RUN_TIMEOUT_SEC}s" \
    stdbuf -oL -eL \
    "$VENV_DIR/bin/bonfire" run "$TICKET_TEXT" \
    --budget "$BONFIRE_RUN_BUDGET_USD" \
    --workflow "$BONFIRE_WORKFLOW" \
    > "$OUT_DIR/bonfire-run.stdout" \
    2> "$OUT_DIR/bonfire-run.stderr"
BONFIRE_EXIT=$?
set -e
BONFIRE_DURATION=$(($(date +%s) - BONFIRE_START_TS))
printf '%s\n' "$BONFIRE_EXIT" > "$OUT_DIR/bonfire-run.exit"

if [[ "$BONFIRE_EXIT" -ne 0 ]]; then
    echo "==> bonfire run FAILED (exit $BONFIRE_EXIT) — the artifact under test is red." >&2
    tail -n 20 "$OUT_DIR/bonfire-run.stderr" >&2 || true
fi

# Which session log did Bonfire write? Bonfire mints its own session id, so
# the gate must be pointed at the file the product produced — not at the
# observer's claude session id, and not at a name the box invented. When
# Bonfire wrote nothing, fall back to the expected path so the gate fails on
# a real absence.
BONFIRE_SESSION_LOG="$("$SYS_PY" -P -c '
import glob
import os
import sys

paths = sorted(glob.glob(sys.argv[1]), key=os.path.getmtime)
print(paths[-1] if paths else sys.argv[2])
' "$TARGET_DIR/.bonfire/sessions/*.jsonl" "$TARGET_DIR/.bonfire/sessions/absent.jsonl")"
echo "==> bonfire session log: $BONFIRE_SESSION_LOG"

# Where did Bonfire actually write? Two roots matter: the fixture worktree
# (where the gate looks) and the box user's home (Bonfire's built-in default
# for the cost ledger and checkpoints). Recording both turns "artifact
# missing" into "artifact written somewhere else", which is a diagnosis
# rather than a shrug.
{
    echo "# /workspace/target/.bonfire"
    find "$TARGET_DIR/.bonfire" -type f 2> /dev/null || true
    echo "# $HOME/.bonfire"
    find "$HOME/.bonfire" -type f 2> /dev/null || true
} > "$OUT_DIR/bonfire-artifact-inventory.txt"

"$SYS_PY" -P - "$EXECUTION_PATH" "$BONFIRE_COMMAND" "$BONFIRE_EXIT" "$BONFIRE_DURATION" \
    "$OUT_DIR/bonfire-run.stderr" "$BONFIRE_SESSION_LOG" <<'PY'
import json
import os
import sys

path, command, exit_code, duration, stderr_path, session_log = sys.argv[1:7]
try:
    with open(stderr_path, encoding="utf-8", errors="replace") as fh:
        tail = [line.rstrip("\n") for line in fh.readlines()[-20:]]
except OSError:
    tail = []
record = {
    "command": command,
    "exit_code": int(exit_code),
    "duration_sec": float(duration),
    "stdout_path": "bonfire-run.stdout",
    "stderr_path": "bonfire-run.stderr",
    "session_log_path": session_log,
    "session_log_present": os.path.isfile(session_log),
    "stderr_tail": tail,
}
with open(path, "w", encoding="utf-8") as fh:
    json.dump(record, fh, indent=2)
PY

# ---------------------------------------------------------------------
# Phase 7: fingerprint the target before the observer session
# ---------------------------------------------------------------------
set_phase "snapshot_pre_observer"
snapshot_target "$OUT_DIR/target-fingerprint-pre.txt"

# ---------------------------------------------------------------------
# Phase 8: drive the observer session via claude-cli
#
# The observer diagnoses; it never repairs and never authors. Its report is
# operator colour, not gate input — the gate reads Bonfire's artifacts.
# ---------------------------------------------------------------------
set_phase "drive_claude_cli"

SESSION_ID="$(< /proc/sys/kernel/random/uuid)"
START_TS="$(date +%s)"
echo "$SESSION_ID" > "$OUT_DIR/claude-session-id.txt"
echo "$START_TS" > "$OUT_DIR/start-timestamp.txt"

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
# Phase 9: the observer must not have moved the target
#
# This is what replaces the deleted JSON templates. When the prompt carried
# literal artifact bodies, an agent could satisfy the gate without the
# product ever running. Now any hand-authored artifact, hand-applied fix, or
# hand-made branch shows up as a fingerprint delta and fails the run.
# ---------------------------------------------------------------------
set_phase "verify_target_untouched"
snapshot_target "$OUT_DIR/target-fingerprint-post.txt"
if [[ "$(cat "$OUT_DIR/target-fingerprint-pre.txt")" != "$(cat "$OUT_DIR/target-fingerprint-post.txt")" ]]; then
    echo "FAIL: the observer session mutated /workspace/target." >&2
    emit_failure_verdict "observer_mutated_target" 10
    exit 10
fi

# ---------------------------------------------------------------------
# Phase 10: capture post-run diff + branches for the gate script
# ---------------------------------------------------------------------
set_phase "capture_post_run_diff"
git diff "$PRE_RUN_SHA"..HEAD --name-only > "$OUT_DIR/diff.patch" 2> /dev/null \
    || git diff --name-only > "$OUT_DIR/diff.patch"
git for-each-ref --format='%(refname:short)' refs/heads > "$OUT_DIR/branches.txt"

# ---------------------------------------------------------------------
# Phase 11: invoke the fixture's gate/check-verdict.sh to write verdict.json
# ---------------------------------------------------------------------
set_phase "gate_check"
set +e
bash gate/check-verdict.sh \
    --run-id           "$RUN_ID" \
    --wave             "$WAVE" \
    --fixture-ref      "$FIXTURE_REF" \
    --out              "$VERDICT_PATH" \
    --session-log      "$BONFIRE_SESSION_LOG" \
    --claude-result    "$OUT_DIR/claude-result.json" \
    --claude-exit      "$CLAUDE_EXIT" \
    --start-ts         "$START_TS" \
    --pre-sha          "$PRE_RUN_SHA" \
    --diff             "$OUT_DIR/diff.patch" \
    --branches         "$OUT_DIR/branches.txt" \
    --baseline-hashes  "$OUT_DIR/baseline-hashes.txt"
GATE_RC=$?
set -e
# A gate killed mid-`--out` write leaves truncated JSON; one that writes `null`,
# a list or a bare `{}` leaves JSON that PARSES and is still not a verdict. Both
# are quarantined before anything treats the file as one, so the bar is the
# shape the arbitration and the host driver both index into — a JSON object
# carrying a string `verdict`. Parseability alone is not it: `.get()` on a list
# and `["verdict"]` on `{}` raise, `set -e` aborts the runner at exit 1, and the
# gate's own status dies behind a traceback. The parse error is written out only
# when the file really is unusable, so a clean run leaves no empty `.err` file.
if [[ -f "$VERDICT_PATH" ]]; then
    if ! VERDICT_PARSE_ERR="$("$SYS_PY" -P -c '
import json
import sys

with open(sys.argv[1], encoding="utf-8") as fh:
    document = json.load(fh)
if not isinstance(document, dict) or not isinstance(document.get("verdict"), str):
    sys.exit("gate wrote a {}, not a verdict object with a string verdict field".format(type(document).__name__))
' "$VERDICT_PATH" 2>&1)"; then
        printf '%s\n' "$VERDICT_PARSE_ERR" > "$OUT_DIR/verdict-parse.err"
        mv "$VERDICT_PATH" "$OUT_DIR/verdict-unparseable.json"
        FAILURE_REASONS+=("gate_verdict_unparseable")
    fi
fi
# A non-zero gate does NOT exit here: exiting now would carry the gate's own
# verdict — possibly a PASS — past the Phase 13 arbitration, the only place a
# failed `bonfire run` is forced to FAIL. Its status is reported at Phase 14.
# When the gate DID write a usable verdict the emitter preserves that file, so
# the reason lands only because emit_failure_verdict records it in
# FAILURE_REASONS first and Phase 13 merges the array into the preserved file.
if [[ "$GATE_RC" -ne 0 ]]; then
    emit_failure_verdict "gate_script_crashed" "$GATE_RC"
fi

# ---------------------------------------------------------------------
# Phase 12: idempotent fallback if gate exited 0 but did not write verdict
# ---------------------------------------------------------------------
set_phase "verify_verdict_emitted"
if [[ ! -f "$VERDICT_PATH" ]]; then
    emit_failure_verdict "gate_script_did_not_emit_verdict" 5
    exit 5
fi

# ---------------------------------------------------------------------
# Phase 13: name the artifact, name the failure
#
# Merge provenance into the verdict so it says WHICH wheel it graded and
# WHICH command produced the evidence, merge the reasons the runner itself
# named into a verdict the gate had already written, and force FAIL when the
# artifact under test did not exit clean. One-directional by construction:
# PASS can become FAIL here, FAIL never becomes PASS.
#
# `-P` is load-bearing on THIS invocation above all others: it runs after the
# observer session, with cwd still at the fixture root, and it is the step that
# writes the final verdict. Without safe path an untracked `json.py` planted by
# the observer would be imported here instead of the stdlib, and its
# `json.load`/`json.dump` would decide what verdict.json says.
# ---------------------------------------------------------------------
set_phase "arbitrate_verdict"
"$SYS_PY" -P - "$VERDICT_PATH" "$ARTIFACT_MANIFEST" "$EXECUTION_PATH" \
    "${FAILURE_REASONS[@]}" <<'PY'
import json
import sys

verdict_path, manifest_path, execution_path, *carried = sys.argv[1:]


def load(path):
    """Return the JSON object at `path`, or None.

    Mirrors the emitter's `load_provenance` guard, and for the same reason:
    a payload that is not an object counts as absence. The observer session
    runs with `--add-dir /workspace/out` on a read-write mount and the
    target fingerprint covers only /workspace/target, so these provenance
    files are writable by the observer and unchecked. Without the isinstance
    guard a tampered payload raises here, `set -e` aborts the runner, and the
    EXIT trap preserves whatever the fixture gate had already written — which
    may be a PASS. Arbitration is the one place a failed run is forced to
    FAIL, so it must not be the place that crashes.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


with open(verdict_path, encoding="utf-8") as fh:
    verdict = json.load(fh)

reasons = list(verdict.get("failure_reasons") or [])

# Reasons the runner named on a path that found a verdict the gate had already
# written. emit_failure_verdict preserves that file rather than overwriting it,
# so this is the ONLY place those reasons can reach it — and any of them means
# the run is not a PASS, including a gate that crashed after writing one.
if carried:
    reasons.extend(carried)
    verdict["verdict"] = "FAIL"

manifest = load(manifest_path)
execution = load(execution_path)

if manifest:
    verdict["artifact_under_test"] = manifest
    verdict["bonfire_version"] = manifest.get("version") or verdict.get(
        "bonfire_version", "unknown"
    )

artifacts = verdict.setdefault("artifacts", {})
if execution is None:
    verdict["verdict"] = "FAIL"
    reasons.append("bonfire_never_executed")
else:
    verdict["bonfire_execution"] = execution
    # `.get`, not `[...]`: this block is the one place a failed run is forced
    # to FAIL, so it must never raise. A KeyError here would abort the runner
    # under `set -e` and leave whatever the fixture gate wrote — possibly a
    # PASS — standing as the final verdict. A missing exit_code reads as None,
    # and `None != 0` is True, so an unreadable execution record fails CLOSED.
    for key, artifact_key in (
        ("stdout_path", "bonfire_stdout_path"),
        ("stderr_path", "bonfire_stderr_path"),
        ("session_log_path", "session_log_path"),
    ):
        value = execution.get(key)
        if value:
            artifacts[artifact_key] = value
    exit_code = execution.get("exit_code")
    if exit_code != 0:
        verdict["verdict"] = "FAIL"
        reasons.append("bonfire_run_failed:exit={}".format(exit_code))
        # `timeout` reports 124; a TERM/KILL that lands first shows as 143/137.
        # Naming it separately keeps "the box ran out of patience" distinct
        # from "the product raised".
        if exit_code in (124, 137, 143):
            reasons.append("bonfire_run_timed_out")
        # Name the failure, not the last line of output. Bonfire's own
        # renderer prints the error above a cost summary, so a naive tail
        # would put "Cost: $0.00" in the verdict and bury what broke.
        markers = ("error", "exception", "traceback", "unknown", "failed")
        lines = [line.strip() for line in execution.get("stderr_tail") or []]
        lines = [line for line in lines if line]
        named = ""
        for line in reversed(lines):
            if any(marker in line.lower() for marker in markers):
                named = line
                break
        if not named and lines:
            named = lines[-1]
        if named:
            reasons.append("bonfire_stderr:" + named[:240])

# Deduplicate while preserving order — the gate may already have named a
# reason this step would repeat.
seen = set()
ordered = []
for reason in reasons:
    if reason not in seen:
        seen.add(reason)
        ordered.append(reason)
verdict["failure_reasons"] = ordered

with open(verdict_path, "w", encoding="utf-8") as fh:
    json.dump(verdict, fh, indent=2)

print("==> verdict={} artifact={} bonfire_exit={}".format(
    verdict["verdict"],
    (manifest or {}).get("wheel", "unknown"),
    (execution or {}).get("exit_code", "not-executed"),
))
PY

# ---------------------------------------------------------------------
# Phase 14: exit — the RUNNER succeeded even when the artifact failed. The
# verdict carries the artifact's fate; the driver turns a FAIL into a non-zero
# exit. A crashed gate propagates its own status here, after the arbitration.
# ---------------------------------------------------------------------
set_phase "done"
echo "==> verdict at $VERDICT_PATH"
if [[ "$GATE_RC" -ne 0 ]]; then
    echo "==> gate script exited $GATE_RC — propagating after arbitration" >&2
    exit "$GATE_RC"
fi
exit 0
