"""The 1.1.0 release notes must file the trust change under ``### Security``.

Users read the release notes; the project-settings trust change is a security
fix, so its entry belongs under ``### Security`` and in no ``### Changed``
subsection. Both predicates are pure rods over text, and the teeth test proves
each one catches a plant.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_MARKER = "BONFIRE_TRUST_ROOTS"
_VERSION = "1.1.0"


def _real_changelog() -> str:
    return (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")


def _section(changelog: str, version: str) -> str:
    start = re.search(r"^## \[" + re.escape(version) + r"\]", changelog, re.MULTILINE)
    assert start, f"CHANGELOG has no `## [{version}]` heading"
    rest = changelog[start.start() :]
    following = re.search(r"^## \[", rest[1:], re.MULTILINE)
    return rest if following is None else rest[: following.start() + 1]


def _subsections(section: str, name: str) -> list[str]:
    pattern = re.compile(r"^### " + re.escape(name) + r"[ \t]*$", re.MULTILINE)
    bodies = []
    for found in pattern.finditer(section):
        tail = section[found.end() :]
        nxt = re.search(r"^### ", tail, re.MULTILINE)
        bodies.append(tail if nxt is None else tail[: nxt.start()])
    return bodies


def _subsection(section: str, name: str) -> str:
    bodies = _subsections(section, name)
    return bodies[0] if bodies else ""


def _under_security(section: str) -> bool:
    return _MARKER in _subsection(section, "Security")


def _under_changed(section: str) -> bool:
    return any(_MARKER in body for body in _subsections(section, "Changed"))


def test_1_1_0_trust_roots_entry_is_under_security() -> None:
    section = _section(_real_changelog(), _VERSION)
    assert _under_security(section), f"{_MARKER} is not listed under ### Security"


def test_1_1_0_trust_roots_entry_is_not_under_changed() -> None:
    section = _section(_real_changelog(), _VERSION)
    assert not _under_changed(section), f"{_MARKER} is still listed under ### Changed"


def test_rods_have_teeth() -> None:
    misfiled = (
        "# Changelog\n\n## [1.1.0] — 2026-01-01\n\n### Changed\n\n"
        f"- Settings load only from `{_MARKER}`.\n\n### Fixed\n\n- Other.\n\n"
        "## [1.0.0] — 2025-01-01\n\n### Security\n\n- Old.\n"
    )
    filed = (
        "# Changelog\n\n## [1.1.0] — 2026-01-01\n\n### Changed\n\n- Other.\n\n"
        f"### Security\n\n- Settings load only from `{_MARKER}`.\n\n"
        "### Changed\n\n- More.\n\n## [1.0.0] — 2025-01-01\n"
    )
    bad = _section(misfiled, _VERSION)
    assert not _under_security(bad)
    assert _under_changed(bad)
    good = _section(filed, _VERSION)
    assert _under_security(good)
    assert not _under_changed(good)
