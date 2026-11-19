"""Tests for scripts/check_tag_version.py — the release version-truth guard.

The guard is the tripwire between a pushed ``v*`` tag and the PyPI publish
pipeline: it exits 0 only when the tag equals ``'v' + pyproject version``,
and fails closed with a typed, self-describing error otherwise.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_tag_version.py"


def _write_pyproject(tmp_path: Path, version: str = "1.2.3") -> Path:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text(f'[project]\nname = "demo"\nversion = "{version}"\n')
    return pyproject


def _run(args: list[str], env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged = {**os.environ, **(env or {})}
    merged.pop("GITHUB_REF", None)
    if env:
        merged.update(env)
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        env=merged,
    )


def test_script_exists() -> None:
    assert SCRIPT.is_file(), f"guard script missing at {SCRIPT}"


def test_matching_tag_passes(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "1.2.3")
    result = _run(["v1.2.3", "--pyproject", str(pyproject)])
    assert result.returncode == 0, result.stderr


def test_mismatched_tag_fails_with_typed_error(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "1.2.3")
    result = _run(["v9.9.9", "--pyproject", str(pyproject)])
    assert result.returncode == 1
    assert "RELEASE_TAG_VERSION_MISMATCH" in result.stderr
    assert "v9.9.9" in result.stderr  # the offending tag
    assert "1.2.3" in result.stderr  # the declared version
    assert "v1.2.3" in result.stderr  # the expected tag


def test_malformed_tag_fails_closed(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "1.2.3")
    result = _run(["1.2.3", "--pyproject", str(pyproject)])  # missing leading 'v'
    assert result.returncode == 1
    assert "RELEASE_TAG_MALFORMED" in result.stderr


def test_empty_tag_fails_closed(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "1.2.3")
    result = _run(["", "--pyproject", str(pyproject)])
    assert result.returncode == 1
    assert "RELEASE_TAG_MALFORMED" in result.stderr


def test_missing_pyproject_fails_closed(tmp_path: Path) -> None:
    result = _run(["v1.2.3", "--pyproject", str(tmp_path / "nope" / "pyproject.toml")])
    assert result.returncode == 1
    assert "RELEASE_PYPROJECT_UNREADABLE" in result.stderr


def test_pyproject_without_version_fails_closed(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nname = "demo"\n')
    result = _run(["v1.2.3", "--pyproject", str(pyproject)])
    assert result.returncode == 1
    assert "RELEASE_PYPROJECT_UNREADABLE" in result.stderr


def test_tag_read_from_github_ref_env(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "1.2.3")
    ok = _run(["--pyproject", str(pyproject)], env={"GITHUB_REF": "refs/tags/v1.2.3"})
    assert ok.returncode == 0, ok.stderr
    bad = _run(["--pyproject", str(pyproject)], env={"GITHUB_REF": "refs/tags/v2.0.0"})
    assert bad.returncode == 1
    assert "RELEASE_TAG_VERSION_MISMATCH" in bad.stderr


def test_no_tag_anywhere_fails_closed(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "1.2.3")
    result = _run(["--pyproject", str(pyproject)])
    assert result.returncode == 1
    assert "RELEASE_TAG_MALFORMED" in result.stderr
