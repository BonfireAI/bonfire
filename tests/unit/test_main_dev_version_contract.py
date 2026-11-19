# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract for the development line: a patch tag on main can never publish main.

Main declares a dev version above the latest patch release, so the release
guard rejects a patch tag pushed on a main commit. Also pins the public-surface
hygiene that rides along with the patch release.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tomllib
from pathlib import Path

from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[2]
GUARD = REPO_ROOT / "scripts" / "check_tag_version.py"


def _declared() -> str:
    with (REPO_ROOT / "pyproject.toml").open("rb") as fh:
        return tomllib.load(fh)["project"]["version"]


def _unreleased_section() -> str:
    text = (REPO_ROOT / "CHANGELOG.md").read_text()
    match = re.search(r"^## \[Unreleased\].*?(?=^## \[)", text, re.MULTILINE | re.DOTALL)
    assert match, "CHANGELOG.md has no [Unreleased] section"
    return match.group(0)


class TestDevVersion:
    def test_declared_version_is_a_dev_release(self) -> None:
        assert Version(_declared()).is_devrelease

    def test_declared_version_is_above_the_patch_release(self) -> None:
        assert Version(_declared()) > Version("1.0.2")

    def test_patch_tag_on_main_fails_the_guard(self) -> None:
        proc = subprocess.run(
            [
                sys.executable,
                str(GUARD),
                "v1.0.2",
                "--pyproject",
                str(REPO_ROOT / "pyproject.toml"),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode != 0
        assert "RELEASE_TAG_VERSION_MISMATCH" in proc.stderr


class TestChangelogPatchEntry:
    def test_patch_release_heading_exists(self) -> None:
        text = (REPO_ROOT / "CHANGELOG.md").read_text()
        assert re.search(r"^## \[1\.0\.2\]", text, re.MULTILINE)

    def test_unreleased_has_no_sdk_security_note(self) -> None:
        section = _unreleased_section()
        assert not ("### Security" in section and "claude-agent-sdk" in section)


class TestPublicSurfaceHygiene:
    def test_readme_images_are_absolute(self) -> None:
        text = (REPO_ROOT / "README.md").read_text()
        urls = re.findall(r'<img[^>]*?\bsrc="([^"]+)"', text)
        urls += re.findall(r"!\[[^\]]*\]\(([^)\s]+)", text)
        relative = [u for u in urls if not re.match(r"https?://", u)]
        assert not relative, f"README images without a scheme: {relative}"

    def test_no_internal_attribution_marker_in_shipped_tree(self) -> None:
        """Pins the personal-attribution marker only; planning-note citations are a separate cleanup."""
        marker = re.compile(r"\b[A-Z][a-z]+-ratified\b")
        files = sorted((REPO_ROOT / "src" / "bonfire").rglob("*.py")) + [REPO_ROOT / "README.md"]
        hits = [
            f"{f.relative_to(REPO_ROOT)}:{n}"
            for f in files
            for n, line in enumerate(f.read_text().splitlines(), 1)
            if marker.search(line)
        ]
        assert not hits, f"internal attribution markers: {hits}"
