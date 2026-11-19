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

# Mirrors _PERSON_NAME in test_no_persona_names_in_public_docs.py (case-sensitive).
PERSON_NAME = re.compile(r"\b(Anta|Antawari)\b")


def _name_hits(text: str, label: str) -> list[str]:
    """``label:lineno`` for each line of ``text`` that names a person."""
    return [
        f"{label}:{n}" for n, line in enumerate(text.splitlines(), 1) if PERSON_NAME.search(line)
    ]


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

    def test_no_personal_name_in_shipped_tree(self) -> None:
        src = REPO_ROOT / "src" / "bonfire"
        files = [f for f in sorted(src.rglob("*")) if f.is_file() and "__pycache__" not in f.parts]
        files.append(REPO_ROOT / "README.md")
        hits: list[str] = []
        for f in files:
            try:
                text = f.read_text()
            except UnicodeDecodeError:
                continue
            hits += _name_hits(text, str(f.relative_to(REPO_ROOT)))
        assert not hits, f"personal names in shipped tree: {hits}"

    def test_personal_name_rod_has_teeth(self) -> None:
        assert _name_hits("    + Anta-ratified §A Q9a):\n", "plant") == ["plant:1"]
        # Case-sensitive on purpose: a lowercase address host is not a name mention.
        assert _name_hits("x@antawari.example", "plant") == []
        assert _name_hits("Antawari wrote this", "plant") == ["plant:1"]
