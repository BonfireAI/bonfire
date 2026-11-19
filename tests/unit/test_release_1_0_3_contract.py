"""Contract for the 1.0.3 release (the 1.0.2 security patch contract, carried forward).

Was test_release_1_0_2_contract.py; 1.0.2 was tagged but never published, 1.0.3 carries the same contract.
"""

from __future__ import annotations

import fnmatch
import re
import tomllib
from pathlib import Path

import yaml
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTION = re.compile(r"\b[A-Z][a-z]+-ratified\b")
# Mirrors _PERSON_NAME in tests/unit/test_no_persona_names_in_public_docs.py.
PERSON_NAME = re.compile(r"\b(Anta|Antawari)\b")


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_version_is_1_0_3() -> None:
    assert _pyproject()["project"]["version"] == "1.0.3"


def test_claude_agent_sdk_floor_excludes_vulnerable_range() -> None:
    reqs = [Requirement(d) for d in _pyproject()["project"]["dependencies"]]
    sdk = [r for r in reqs if r.name == "claude-agent-sdk"]
    assert len(sdk) == 1
    spec = sdk[0].specifier
    assert "0.2.120" not in spec
    assert "0.1.0" not in spec
    assert "0.2.121" in spec
    assert "0.2.185" in spec


def test_init_version_fallback_is_1_0_3() -> None:
    src = (ROOT / "src" / "bonfire" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "1.0.3"' in src


def test_changelog_first_heading_is_1_0_3() -> None:
    for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## ["):
            assert line.startswith("## [1.0.3]"), line
            return
    raise AssertionError("no '## [' heading in CHANGELOG.md")


def _branch_patterns(workflow: dict, event: str) -> list[str]:
    triggers = workflow.get("on", workflow.get(True))
    return list(triggers[event]["branches"])


def test_ci_and_smoke_run_on_release_branches() -> None:
    for name in ("ci.yml", "smoke.yml"):
        wf = yaml.safe_load((ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8"))
        for event in ("push", "pull_request"):
            patterns = _branch_patterns(wf, event)
            assert any(fnmatch.fnmatch("release/1.0.x", p) for p in patterns), (
                f"{name} {event} branches {patterns} do not cover release/1.0.x"
            )


def test_no_internal_attribution_marker_in_shipped_tree() -> None:
    """Pins the personal-attribution marker only; planning-note citations are a separate cleanup."""
    files = sorted((ROOT / "src" / "bonfire").rglob("*.py")) + [ROOT / "README.md"]
    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ATTRIBUTION.search(line):
                hits.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not hits, "internal attribution markers found: " + ", ".join(hits)


def _name_hits(text: str, label: str) -> list[str]:
    return [
        f"{label}:{n}"
        for n, line in enumerate(text.splitlines(), start=1)
        if PERSON_NAME.search(line)
    ]


def test_no_personal_name_in_shipped_tree() -> None:
    hits: list[str] = []
    paths = [p for p in sorted((ROOT / "src" / "bonfire").rglob("*")) if p.is_file()]
    for path in [*paths, ROOT / "README.md"]:
        if "__pycache__" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="strict")
        except UnicodeDecodeError:
            continue
        hits += _name_hits(text, str(path.relative_to(ROOT)))
    assert not hits, "personal names found: " + ", ".join(hits)


def test_personal_name_rod_has_teeth() -> None:
    assert _name_hits("    + Anta-ratified §A Q9a):\n", "plant") == ["plant:1"]
    assert _name_hits("x@antawari.example", "plant") == []
    assert _name_hits("Antawari wrote this", "plant") == ["plant:1"]
