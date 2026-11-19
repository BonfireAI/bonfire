"""Contract for the 1.0.2 security patch release."""

from __future__ import annotations

import fnmatch
import re
import tomllib
from pathlib import Path

import yaml
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[2]
ATTRIBUTION = re.compile(r"\b[A-Z][a-z]+-ratified\b")


def _pyproject() -> dict:
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))


def test_pyproject_version_is_1_0_2() -> None:
    assert _pyproject()["project"]["version"] == "1.0.2"


def test_claude_agent_sdk_floor_excludes_vulnerable_range() -> None:
    reqs = [Requirement(d) for d in _pyproject()["project"]["dependencies"]]
    sdk = [r for r in reqs if r.name == "claude-agent-sdk"]
    assert len(sdk) == 1
    spec = sdk[0].specifier
    assert "0.2.120" not in spec
    assert "0.1.0" not in spec
    assert "0.2.121" in spec
    assert "0.2.185" in spec


def test_init_version_fallback_is_1_0_2() -> None:
    src = (ROOT / "src" / "bonfire" / "__init__.py").read_text(encoding="utf-8")
    assert '__version__ = "1.0.2"' in src


def test_changelog_first_heading_is_1_0_2() -> None:
    for line in (ROOT / "CHANGELOG.md").read_text(encoding="utf-8").splitlines():
        if line.startswith("## ["):
            assert line.startswith("## [1.0.2]"), line
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
    files = sorted((ROOT / "src" / "bonfire").rglob("*.py")) + [ROOT / "README.md"]
    hits: list[str] = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), start=1):
            if ATTRIBUTION.search(line) or "§A Q" in line:
                hits.append(f"{path.relative_to(ROOT)}:{lineno}")
    assert not hits, "internal attribution markers found: " + ", ".join(hits)
