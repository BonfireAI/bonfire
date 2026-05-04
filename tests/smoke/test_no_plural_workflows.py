"""BON-637 smoke: ensure no plural workflows references remain post-rename."""

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_no_plural_bonfire_workflows_imports() -> None:
    # Exclude this smoke test itself, since it must contain the literal
    # string "bonfire.workflows" to grep for it.
    result = subprocess.run(
        [
            "grep",
            "-rn",
            "--exclude-dir=__pycache__",
            "--exclude=test_no_plural_workflows.py",
            "bonfire.workflows",
            "src/",
            "tests/",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # grep exits 1 when no match found — that is the success state
    assert result.returncode == 1, f"Found plural bonfire.workflows references:\n{result.stdout}"


def test_singular_workflow_directory_exists() -> None:
    assert (REPO_ROOT / "src" / "bonfire" / "workflow").is_dir()


def test_plural_workflows_directory_gone() -> None:
    assert not (REPO_ROOT / "src" / "bonfire" / "workflows").exists()
