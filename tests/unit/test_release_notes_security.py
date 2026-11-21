"""The 1.1.0 release notes file the trust change under Security, never under Changed."""

from __future__ import annotations

import re
from pathlib import Path

_M = "BONFIRE_TRUST_ROOTS"
_LOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
_BAD = f"## [1.1.0]\n### Changed\n- {_M}\n## [1.0.0]\n### Security\n- {_M}\n"
_GOOD = f"## [1.1.0]\n### Changed\n- x\n### Security\n- {_M}\n### Changed\n- y\n"


def _bodies(changelog: str, version: str, name: str) -> list[str]:
    sec = next(p for p in re.split(r"^## \[", changelog, flags=re.M) if p.startswith(version + "]"))
    return [p for p in re.split(r"^### ", sec, flags=re.M)[1:] if p.split("\n")[0].strip() == name]


def _hit(log: str, name: str) -> bool:
    return any(_M in b for b in _bodies(log, "1.1.0", name))


def test_1_1_0_trust_roots_entry_is_under_security() -> None:
    assert _hit(_LOG.read_text(encoding="utf-8"), "Security")


def test_1_1_0_trust_roots_entry_is_not_under_changed() -> None:
    assert not _hit(_LOG.read_text(encoding="utf-8"), "Changed")


def test_rods_have_teeth() -> None:
    assert not _hit(_BAD, "Security") and _hit(_BAD, "Changed")
    assert _hit(_GOOD, "Security") and not _hit(_GOOD, "Changed")
