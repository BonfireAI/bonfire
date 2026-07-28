# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the box runner's pip install resilience and failure attribution.

The release-gate attempt of 2026-07-27 died twice in the runner's install
phase on ``ReadTimeoutError`` against ``files.pythonhosted.org`` at a
measured 13 KiB/s. Both runs reported ``artifact_install_failed``, which
``docs/box-operator.md`` and ``docs/release-gates.md`` teach the operator to
read as *the box worked and the artifact did not*. The artifact had never
been installed, imported or executed; it installs into a clean venv in 1.4
seconds. The verdict named the wrong layer.

These tests grade the shipped bash, not a transcription of it. Both
``classify_pip_failure`` and ``install_step`` are extracted verbatim from
``tests/e2e/scripts/e2e-runner.sh`` and executed by a real bash, so a rename
or a deletion fails the extraction rather than passing a stale copy.

Every pip log below was captured from a real pip run, not written from
memory: ``pip 24.0`` inside the box image (``bonfire-e2e:local``) with
``--network none``, and ``pip 26.1`` on the host against a deliberately
unreachable index and against deliberately malformed wheels.

The load-bearing case is ``test_hard_artifact_marker_beats_transport_noise``.
Without it this change would be a way to relabel a genuinely broken wheel as
somebody else's network problem. With it, a wheel defect that pip can see
without reaching an index stays an artifact failure even when the same log
carries connection errors.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNNER = REPO_ROOT / "tests" / "e2e" / "scripts" / "e2e-runner.sh"
BOX_DRIVER = REPO_ROOT / "tests" / "e2e" / "scripts" / "e2e-box.sh"
PLAYBOOK = REPO_ROOT / "docs" / "box-operator.md"
RELEASE_GATES = REPO_ROOT / "docs" / "release-gates.md"

# --------------------------------------------------------------------------
# Captured pip output. Line breaks are preserved; the source is wrapped with
# implicit concatenation so the file stays readable without altering a byte
# of what pip printed.
# --------------------------------------------------------------------------

#: pip 24.0, box image, `--network none`. The DNS-failure shape of an
#: unreachable index: a transport exception, then the same
#: "Could not find a version" line a genuinely missing dependency produces.
#: That overlap is why the classifier keys on the transport exception and not
#: on the resolution error.
LOG_NETWORK_DNS = (
    "WARNING: Retrying (Retry(total=1, connect=None, read=None, redirect=None, status=None)) "
    "after connection broken by 'NewConnectionError('<pip._vendor.urllib3.connection."
    "HTTPSConnection object at 0x7afe5bdda0f0>: Failed to establish a new connection: "
    "[Errno -3] Temporary failure in name resolution')': /simple/requests/\n"
    "ERROR: Could not find a version that satisfies the requirement requests (from versions: none)\n"
    "ERROR: No matching distribution found for requests\n"
)

#: The 2026-07-27 incident's own signature, reproduced on the host against a
#: socket that accepts and never answers.
LOG_NETWORK_READ_TIMEOUT = (
    "Looking in indexes: https://pypi.org/simple\n"
    "WARNING: Retrying (Retry(total=0, connect=None, read=None, redirect=None, status=None)) "
    "after connection broken by 'ReadTimeoutError(\"HTTPSConnectionPool("
    "host='files.pythonhosted.org', port=443): Read timed out. (read timeout=15.0)\")': "
    "/packages/bonfire/claude_agent_sdk-0.1.0-py3-none-any.whl\n"
    "pip._vendor.urllib3.exceptions.ReadTimeoutError: HTTPSConnectionPool("
    "host='files.pythonhosted.org', port=443): Read timed out.\n"
)

#: pip 26.1, host, connection refused on a closed port.
LOG_NETWORK_REFUSED = (
    "Looking in indexes: http://127.0.0.1:1/simple\n"
    "WARNING: Retrying (Retry(total=1, connect=None, read=None, redirect=None, status=None)) "
    "after connection broken by 'NewConnectionError(\"HTTPConnection(host='127.0.0.1', "
    "port=1): Failed to establish a new connection: [Errno 111] Connection refused\")': "
    "/simple/somepkg/\n"
    "ERROR: Could not find a version that satisfies the requirement somepkg (from versions: none)\n"
)

#: pip 24.0, box image, `--no-index`, against a wheel whose bytes are not a
#: zip. pip reads the local file and fails before any index is consulted.
LOG_ARTIFACT_CORRUPT_WHEEL = (
    "Processing /workspace/artifact/bonfire_ai-1.0.1-py3-none-any.whl\n"
    "ERROR: Wheel 'bonfire_ai' located at "
    "/workspace/artifact/bonfire_ai-1.0.1-py3-none-any.whl is invalid.\n"
)

#: pip 26.1, host. A filename that is not a wheel name at all.
LOG_ARTIFACT_BAD_FILENAME = "ERROR: Invalid wheel filename (wrong number of parts): 'notawheel'\n"

#: pip 24.0, box image, `--no-index`, against a structurally valid wheel that
#: requires a package which cannot be resolved. No transport exception
#: anywhere, so the default branch is what classifies it.
LOG_ARTIFACT_UNSATISFIABLE = (
    "Processing /workspace/artifact/bonfire_ai-1.0.1-py3-none-any.whl\n"
    "INFO: pip is looking at multiple versions of bonfire-ai to determine which version is "
    "compatible with other requirements. This could take a while.\n"
    "ERROR: Could not find a version that satisfies the requirement "
    "totally-nonexistent-dep-xyz>=99.0 (from bonfire-ai) (from versions: none)\n"
    "ERROR: No matching distribution found for totally-nonexistent-dep-xyz>=99.0\n"
)

#: A build-backend crash. Nothing an unreachable index can manufacture: pip
#: has to have downloaded and unpacked a source tree to get here.
LOG_ARTIFACT_BUILD_CRASH = (
    "Processing /workspace/artifact/bonfire_ai-1.0.1.tar.gz\n"
    "  Preparing metadata (pyproject.toml): started\n"
    "  error: subprocess-exited-with-error\n"
    "  ERROR: metadata-generation-failed\n"
)

#: The control-rod case: a real wheel defect observed on a link that was ALSO
#: failing. The artifact reading must win.
LOG_MIXED_CORRUPT_WHEEL_ON_DEAD_LINK = LOG_NETWORK_REFUSED + LOG_ARTIFACT_CORRUPT_WHEEL


# --------------------------------------------------------------------------
# Harness: run the shipped bash functions.
# --------------------------------------------------------------------------


def _extract_function(name: str) -> str:
    """Return the verbatim body of shell function *name* from the runner.

    The extraction is the guard: a renamed or deleted function yields an
    empty string and every test that needs it fails loudly, rather than
    silently grading a copy that no longer ships.
    """
    lines = RUNNER.read_text(encoding="utf-8").splitlines()
    opener = f"{name}() {{"
    try:
        start = lines.index(opener)
    except ValueError:
        return ""
    for offset, line in enumerate(lines[start + 1 :], start=start + 1):
        if line == "}":
            return "\n".join(lines[start : offset + 1])
    return ""


def _harness(body: str, out_dir: Path) -> str:
    """Assemble a runnable script around the extracted functions."""
    classify = _extract_function("classify_pip_failure")
    install = _extract_function("install_step")
    assert classify, "classify_pip_failure is no longer defined in the runner"
    assert install, "install_step is no longer defined in the runner"
    return "\n".join(
        [
            "set -euo pipefail",
            f'OUT_DIR="{out_dir}"',
            # Stand-in for the runner's verdict emitter. It records what the
            # verdict WOULD have said; the real emitter is exercised by the
            # runner's own contract tests.
            'emit_failure_verdict() { echo "REASON=$1"; echo "EXITCODE=$2"; }',
            classify,
            install,
            body,
        ]
    )


def _run(body: str, out_dir: Path) -> subprocess.CompletedProcess[str]:
    script = out_dir / "harness.sh"
    script.write_text(_harness(body, out_dir), encoding="utf-8")
    return subprocess.run(
        ["bash", str(script)], capture_output=True, text=True, cwd=str(out_dir), check=False
    )


def _classify(log_text: str, tmp_path: Path) -> str:
    log = tmp_path / "step.log"
    log.write_text(log_text, encoding="utf-8")
    result = _run(f'classify_pip_failure "{log}"', tmp_path)
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


def _failing_install(log_text: str, tmp_path: Path) -> subprocess.CompletedProcess[str]:
    """Drive install_step with a command that emits *log_text* and exits 1."""
    canned = tmp_path / "canned.log"
    canned.write_text(log_text, encoding="utf-8")
    body = f'install_step "artifact-and-deps" bash -c \'cat "$0" >&2; exit 1\' {canned}'
    return _run(body, tmp_path)


# --------------------------------------------------------------------------
# classify_pip_failure
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "log"),
    [
        ("dns", LOG_NETWORK_DNS),
        ("read_timeout", LOG_NETWORK_READ_TIMEOUT),
        ("refused", LOG_NETWORK_REFUSED),
    ],
)
def test_transport_failures_classify_as_network(name: str, log: str, tmp_path: Path) -> None:
    assert _classify(log, tmp_path) == "network", name


@pytest.mark.parametrize(
    ("name", "log"),
    [
        ("corrupt_wheel", LOG_ARTIFACT_CORRUPT_WHEEL),
        ("bad_filename", LOG_ARTIFACT_BAD_FILENAME),
        ("unsatisfiable", LOG_ARTIFACT_UNSATISFIABLE),
        ("build_crash", LOG_ARTIFACT_BUILD_CRASH),
    ],
)
def test_artifact_failures_classify_as_artifact(name: str, log: str, tmp_path: Path) -> None:
    assert _classify(log, tmp_path) == "artifact", name


def test_hard_artifact_marker_beats_transport_noise(tmp_path: Path) -> None:
    """Control rod: a real wheel defect cannot be relabelled a network problem.

    The log carries a genuine connection error AND a genuine corrupt-wheel
    error. If the transport branch were allowed to win, this change would be
    a way to launder a broken artifact into an excuse. The counterfactual is
    the case directly above: strip the wheel error and the same log
    classifies as ``network``.
    """
    assert _classify(LOG_MIXED_CORRUPT_WHEEL_ON_DEAD_LINK, tmp_path) == "artifact"
    assert _classify(LOG_NETWORK_REFUSED, tmp_path) == "network"


def test_unrecognised_output_defaults_to_artifact(tmp_path: Path) -> None:
    """Silence is never read as an excuse: the default is the blocking reading."""
    assert _classify("", tmp_path) == "artifact"
    assert _classify("ERROR: something nobody has seen before\n", tmp_path) == "artifact"


def test_missing_log_defaults_to_artifact(tmp_path: Path) -> None:
    """An unreadable slice must not become a network alibi."""
    result = _run(f'classify_pip_failure "{tmp_path / "absent.log"}"', tmp_path)
    assert result.returncode == 0
    assert result.stdout.strip() == "artifact"


# --------------------------------------------------------------------------
# install_step: both causes still abort, with different verdicts.
# --------------------------------------------------------------------------


def test_network_failure_aborts_with_its_own_reason_and_code(tmp_path: Path) -> None:
    result = _failing_install(LOG_NETWORK_READ_TIMEOUT, tmp_path)
    assert result.returncode == 11, result.stdout + result.stderr
    assert "REASON=box_network_unreachable:artifact-and-deps" in result.stdout
    assert "EXITCODE=11" in result.stdout
    # The operator must be told the wheel was never exercised.
    assert "NOT installed and NOT tested" in result.stderr


def test_broken_wheel_still_fails_loudly_as_an_artifact_failure(tmp_path: Path) -> None:
    """The half this change must not soften.

    A genuinely broken wheel takes the same exit code and the same reason
    string it took before: exit 8, ``artifact_install_failed:<step>``.
    """
    result = _failing_install(LOG_ARTIFACT_CORRUPT_WHEEL, tmp_path)
    assert result.returncode == 8, result.stdout + result.stderr
    assert "REASON=artifact_install_failed:artifact-and-deps" in result.stdout
    assert "EXITCODE=8" in result.stdout


def test_the_two_causes_do_not_share_a_verdict(tmp_path: Path) -> None:
    """The whole point, asserted as a difference rather than as two absolutes."""
    network_dir = tmp_path / "n"
    artifact_dir = tmp_path / "a"
    network_dir.mkdir()
    artifact_dir.mkdir()
    network = _failing_install(LOG_NETWORK_DNS, network_dir)
    artifact = _failing_install(LOG_ARTIFACT_UNSATISFIABLE, artifact_dir)
    assert network.returncode != artifact.returncode
    assert network.stdout != artifact.stdout
    # Neither is a pass.
    assert network.returncode != 0
    assert artifact.returncode != 0


def test_successful_step_returns_zero_and_writes_both_logs(tmp_path: Path) -> None:
    result = _run(
        "install_step \"fixture-deps\" bash -c 'echo Successfully installed bonfire-ai-1.0.1'",
        tmp_path,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REASON=" not in result.stdout
    shared = tmp_path / "pip-install.log"
    slice_log = tmp_path / "pip-step-fixture-deps.log"
    assert "Successfully installed" in shared.read_text(encoding="utf-8")
    assert "Successfully installed" in slice_log.read_text(encoding="utf-8")


def test_per_step_slice_isolates_the_failing_step(tmp_path: Path) -> None:
    """A recovered stall in step 1 must not classify step 2's failure.

    The three steps share ``pip-install.log``. Reading that whole file would
    let a retry warning step 1 survived decide what killed step 2. The slice
    is what keeps attribution honest.
    """
    body = "\n".join(
        [
            'install_step "artifact-and-deps" bash -c '
            '\'echo "WARNING: Retrying after connection broken by ReadTimeoutError"; '
            'echo "Successfully installed bonfire-ai-1.0.1"\'',
            'install_step "fixture-deps" bash -c '
            "'echo \"ERROR: Wheel '\"'\"'fixture'\"'\"' located at /x.whl is invalid.\" >&2; exit 1'",
        ]
    )
    result = _run(body, tmp_path)
    assert result.returncode == 8, result.stdout + result.stderr
    assert "REASON=artifact_install_failed:fixture-deps" in result.stdout
    # The shared log does carry step 1's transport noise; the slice does not.
    assert "ReadTimeoutError" in (tmp_path / "pip-install.log").read_text(encoding="utf-8")
    assert "ReadTimeoutError" not in (tmp_path / "pip-step-fixture-deps.log").read_text(
        encoding="utf-8"
    )


# --------------------------------------------------------------------------
# Resilience knobs, and the doc surface that reads the reason codes.
# --------------------------------------------------------------------------


def test_every_install_step_carries_the_timeout_and_retry_flags() -> None:
    body = RUNNER.read_text(encoding="utf-8")
    assert "PIP_NET_ARGS=(--timeout 60 --retries 8)" in body, (
        "the resilience flags must be written out, not assembled from variables"
    )
    for label in ("artifact-and-deps", "fixture-deps", "artifact-under-test"):
        assert f'install_step "{label}"' in body, label
    # One expansion per install call, and no more.
    assert body.count('"${PIP_NET_ARGS[@]}"') == 3


def test_driver_mounts_a_persistent_pip_cache_with_an_off_switch() -> None:
    body = BOX_DRIVER.read_text(encoding="utf-8")
    assert "BOX_PIP_CACHE" in body
    assert "PIP_CACHE_DIR=/home/box/.cache/pip" in body
    assert "PIP_NO_CACHE_DIR=1" in body, "an operator must be able to force a cold download"
    assert '"${PIP_CACHE_ARGS[@]}"' in body, "the cache wiring must reach docker run"


def test_docs_teach_the_network_reason_code() -> None:
    """The docs are half the defect; keep them bound to the vocabulary.

    ``artifact_install_failed`` was readable as "the artifact did not
    install" only because both documents said so. A new reason code that no
    document explains puts the operator back where the incident found them.
    """
    for doc in (PLAYBOOK, RELEASE_GATES):
        assert "box_network_unreachable" in doc.read_text(encoding="utf-8"), doc.name
