"""The README upgrade notice must name the newest released CHANGELOG version.

Both helpers are pure rods over text. The real files must yield no problems;
each plant (a copy with one defect) must yield exactly its own stable name.
``project.version`` is read nowhere: a dev version must never be forced into
the README.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SEMVER = r"\d+\.\d+\.\d+"
_HEADING_RE = re.compile(r"^## \[(" + _SEMVER + r")\]", re.MULTILINE)
_UPGRADE_MARKERS = ("pip install -U bonfire-ai", "pip install --upgrade bonfire-ai")


def _real_readme() -> str:
    return (ROOT / "README.md").read_text(encoding="utf-8")


def _real_changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def _newest_released(changelog: str) -> str:
    found = _HEADING_RE.search(changelog)
    assert found, "CHANGELOG has no `## [X.Y.Z]` heading"
    return found.group(1)


def _is_upgrade_line(line: str) -> bool:
    return any(marker in line for marker in _UPGRADE_MARKERS)


def _readme_problems(readme: str, changelog: str) -> list[str]:
    problems: list[str] = []
    lines = readme.splitlines()
    upgrade = next((ln for ln in lines if _is_upgrade_line(ln)), None)
    if upgrade is None:
        problems.append("readme-upgrade-command-missing")
    else:
        newest = re.escape(_newest_released(changelog))
        has_newest = re.search(r"(?<![\d.])" + newest + r"(?![\d.])", upgrade)
        others = [v for v in re.findall(_SEMVER, upgrade) if v != _newest_released(changelog)]
        if not has_newest or others:
            problems.append("readme-names-stale-release")
    if any(ln.startswith("#") and "v1.0.0" in ln for ln in lines):
        problems.append("readme-v1.0.0-heading")
    return problems


def _insert_before_first_section(changelog: str, block: str) -> str:
    idx = changelog.index("## [")
    return changelog[:idx] + block + changelog[idx:]


def test_real_readme_has_no_release_notice_problems() -> None:
    assert _readme_problems(_real_readme(), _real_changelog()) == []


def test_newest_released_matches_first_semver_heading() -> None:
    changelog = _real_changelog()
    first = next(ln for ln in changelog.splitlines() if re.match(r"^## \[" + _SEMVER + r"\]", ln))
    expected = re.match(r"^## \[(" + _SEMVER + r")\]", first).group(1)  # type: ignore[union-attr]
    assert _newest_released(changelog) == expected


def test_plant_newer_changelog_release_makes_readme_stale() -> None:
    changelog = _insert_before_first_section(_real_changelog(), "## [1.0.4] — 2099-01-01\n\n")
    assert _readme_problems(_real_readme(), changelog) == ["readme-names-stale-release"]


def test_plant_upgrade_command_dropped() -> None:
    readme = "\n".join(ln for ln in _real_readme().splitlines() if not _is_upgrade_line(ln))
    assert _readme_problems(readme, _real_changelog()) == ["readme-upgrade-command-missing"]


def test_plant_v1_0_0_heading() -> None:
    readme = _real_readme() + "\n## What's in v1.0.0\n"
    assert _readme_problems(readme, _real_changelog()) == ["readme-v1.0.0-heading"]


def test_control_unreleased_section_is_skipped() -> None:
    changelog = _real_changelog()
    planted = _insert_before_first_section(changelog, "## [Unreleased]\n\n- something\n\n")
    assert _newest_released(planted) == _newest_released(changelog)
    assert _readme_problems(_real_readme(), planted) == []
