# SPDX-License-Identifier: Apache-2.0
"""Contract test for the release-gate runner script.

Asserts the runner script's structural commitments WITHOUT actually
launching Docker (that's the human-driven Box run). Verifies the
script names the right env vars, has the trap, calls the gate, etc.
"""

from __future__ import annotations

import json
import re
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
RUNNER = REPO_ROOT / "tests" / "e2e" / "scripts" / "e2e-runner.sh"
DOCKERFILE = REPO_ROOT / "tests" / "e2e" / "Dockerfile"
PROMPT = REPO_ROOT / "tests" / "e2e" / "prompts" / "runner-prompt.md"
SCHEMA = REPO_ROOT / "tests" / "e2e" / "schemas" / "verdict.schema.json"
ENV_EXAMPLE = REPO_ROOT / ".env.example"
PLAYBOOK = REPO_ROOT / "docs" / "box-operator.md"


def test_runner_script_exists_and_is_executable() -> None:
    assert RUNNER.exists()
    assert RUNNER.stat().st_mode & stat.S_IXUSR


def test_runner_passes_shellcheck() -> None:
    try:
        result = subprocess.run(["shellcheck", str(RUNNER)], capture_output=True, text=True)
    except FileNotFoundError:
        pytest.skip("shellcheck not installed")
    assert result.returncode == 0, result.stdout + result.stderr


def test_runner_declares_required_env_vars() -> None:
    body = RUNNER.read_text()
    for var in ("ANTHROPIC_API_KEY", "RUN_ID", "WAVE", "FIXTURE_REF"):
        assert f': "${{{var}' in body, f"runner must require {var}"


def test_runner_invokes_claude_with_locked_flags() -> None:
    body = RUNNER.read_text()
    assert "--bare" in body
    assert "--permission-mode bypassPermissions" in body
    assert "--output-format stream-json" in body
    assert "--max-turns 50" in body
    assert "--max-budget-usd 5.00" in body
    assert "--session-id" in body


def test_runner_exports_bonfire_cost_ledger_path() -> None:
    body = RUNNER.read_text()
    assert "BONFIRE_COST_LEDGER_PATH=/workspace/target/.bonfire/costs.jsonl" in body


def test_runner_has_failure_trap() -> None:
    body = RUNNER.read_text()
    assert "trap " in body
    assert "emit_failure_verdict" in body
    assert "EXIT" in body


def test_runner_invokes_gate_check_verdict() -> None:
    body = RUNNER.read_text()
    assert "gate/check-verdict.sh" in body


def test_runner_uses_timeout_on_claude_cli() -> None:
    body = RUNNER.read_text()
    assert "timeout " in body
    assert "1800" in body  # 30 min


def test_dockerfile_pins_claude_cli_version() -> None:
    body = DOCKERFILE.read_text()
    assert "@anthropic-ai/claude-code@2.1.123" in body


def test_dockerfile_installs_jq_and_uuidgen() -> None:
    body = DOCKERFILE.read_text()
    assert "jq" in body
    # uuidgen ships in util-linux; verify via the package or the binary
    assert "util-linux" in body or "uuidgen" in body


def test_dockerfile_runs_as_non_root() -> None:
    body = DOCKERFILE.read_text()
    assert re.search(r"^\s*USER\s+box\s*$", body, re.MULTILINE), (
        "Dockerfile must include `USER box` directive"
    )


def test_dockerfile_copies_prompt_template() -> None:
    body = DOCKERFILE.read_text()
    assert "COPY" in body and "runner-prompt.md" in body
    assert "/usr/local/bin/e2e-prompt.txt" in body


def test_prompt_template_exists_with_artifact_specs() -> None:
    assert PROMPT.exists()
    body = PROMPT.read_text()
    assert ".bonfire/costs.jsonl" in body
    assert ".bonfire/sessions/" in body
    assert ".bonfire/review-verdict.json" in body
    assert "tests/" in body
    assert "src/" in body
    assert "bonfire/fix/" in body
    assert "bypassPermissions" not in body  # don't leak runner flags into prompt
    # The prompt must remind Claude not to push or modify forbidden paths.
    assert "Do not push" in body or "no remote" in body.lower()
    assert "tests/" in body and "Do not modify" in body or "DO NOT" in body.upper()


def test_env_example_exists_at_repo_root() -> None:
    assert ENV_EXAMPLE.exists()
    body = ENV_EXAMPLE.read_text()
    assert "ANTHROPIC_API_KEY=" in body


def test_gitignore_includes_env_glob() -> None:
    gitignore = REPO_ROOT / ".gitignore"
    assert gitignore.exists()
    body = gitignore.read_text()
    # Either the broad glob or both .env and .env.* explicitly
    assert ".env*" in body or (".env" in body and ".env.local" in body)


def test_box_operator_playbook_exists() -> None:
    assert PLAYBOOK.exists()
    body = PLAYBOOK.read_text()
    assert "Box Operator Playbook" in body
    assert "Troubleshooting" in body
    assert "Cost expectations" in body


def test_release_gates_doc_updated_for_v01_caveat() -> None:
    doc = REPO_ROOT / "docs" / "release-gates.md"
    body = doc.read_text()
    # New honest prose about by-trust network
    assert "by-trust" in body or "by trust" in body
    # New honest prose about library-use vs end-to-end
    assert "library" in body.lower() or "as a library" in body.lower()
    # claude-cli bump policy section
    assert "bump" in body.lower()


def test_verdict_schema_unchanged() -> None:
    """Sanity: the release-gate work does NOT mutate the verdict schema."""
    schema = json.loads(SCHEMA.read_text())
    required = set(schema["required"])
    assert required == {
        "run_id",
        "wave",
        "bonfire_version",
        "fixture",
        "ticket",
        "pipeline",
        "assertions",
        "artifacts",
        "verdict",
    }
    assertions_required = set(schema["properties"]["assertions"]["required"])
    assert assertions_required == {
        "broken_test_now_passes",
        "no_regressions",
        "pr_opened",
        "test_files_untouched",
        "src_files_modified",
        "review_verdict_emitted",
        "cost_log_present",
    }
