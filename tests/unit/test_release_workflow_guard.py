"""The release workflow must run the tag/version guard before any build or upload.

``_guard_problems`` is a pure rod over the parsed workflow. The real file must
yield no problems; each plant (a deep copy with one defect) must yield exactly
its own stable name, so the rod demonstrably has teeth.
"""

from __future__ import annotations

import copy
import re
import shlex
from pathlib import Path

import yaml

WORKFLOW = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "release.yml"
GUARD_SCRIPT = "scripts/check_tag_version.py"


def _load() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _run(step: dict) -> str:
    return str(step.get("run", ""))


def _guard_problems(workflow: dict) -> list[str]:
    problems: list[str] = []
    jobs = workflow.get("jobs", {})
    steps = jobs.get("build", {}).get("steps", [])
    guard_idx = next((i for i, s in enumerate(steps) if GUARD_SCRIPT in _run(s)), None)
    build_idx = next((i for i, s in enumerate(steps) if "python -m build" in _run(s)), None)
    if guard_idx is None:
        problems.append("release-guard-missing")
    elif build_idx is None or guard_idx >= build_idx:
        problems.append("release-guard-after-build")
    needs = jobs.get("publish", {}).get("needs", [])
    needs = [needs] if isinstance(needs, str) else list(needs)
    if "build" not in needs:
        problems.append("publish-not-gated-on-build")
    return problems


def _guard_index(workflow: dict) -> int:
    steps = workflow["jobs"]["build"]["steps"]
    return next(i for i, s in enumerate(steps) if GUARD_SCRIPT in _run(s))


def test_real_release_workflow_has_no_guard_problems() -> None:
    assert _guard_problems(_load()) == []


def test_plant_guard_step_removed() -> None:
    wf = copy.deepcopy(_load())
    steps = wf["jobs"]["build"]["steps"]
    del steps[_guard_index(wf)]
    assert _guard_problems(wf) == ["release-guard-missing"]


def test_plant_guard_step_after_build() -> None:
    wf = copy.deepcopy(_load())
    steps = wf["jobs"]["build"]["steps"]
    guard = steps.pop(_guard_index(wf))
    build_idx = next(i for i, s in enumerate(steps) if "python -m build" in _run(s))
    steps.insert(build_idx + 1, guard)
    assert _guard_problems(wf) == ["release-guard-after-build"]


def test_plant_publish_needs_dropped() -> None:
    wf = copy.deepcopy(_load())
    wf["jobs"]["publish"].pop("needs", None)
    assert _guard_problems(wf) == ["publish-not-gated-on-build"]


# Hand-recorded from `requirements/runtime.txt` of pypa/gh-action-pypi-publish at
# each SHA: (twine, packaging) the action bundles. The build job must install
# exactly this pair, so the wheel is checked by the instrument that publishes it.
# The v1.14.0 SHA (cef2210...) is deliberately absent: it is inside a published
# advisory range.
PUBLISHER_BUNDLES = {
    "7245906fb61fa33a13554f9d5fb856fe61758086": ("7.0.0", "26.2"),  # v1.14.3
}

_PUBLISHER_PREFIX = "pypa/gh-action-pypi-publish@"
_SHA_RE = re.compile(r"[0-9a-f]{40}")


_COMMENT_RE = re.compile(r"(^|\s)#.*$")


def _tokens(line: str) -> list[str]:
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()


def _commands(runs: list[str]) -> list[list[str]]:
    """Tokenised shell commands: comments removed, blank lines dropped."""
    lines = (_COMMENT_RE.sub("", ln).strip() for text in runs for ln in text.splitlines())
    return [_tokens(ln) for ln in lines if ln]


def _install_args(commands: list[list[str]]) -> list[list[str]]:
    """Per pip-install command, the tokens after ``install``."""
    found = []
    for tokens in commands:
        for i, tok in enumerate(tokens[:-1]):
            if "pip" in tok and tokens[i + 1] == "install":
                found.append(tokens[i + 2 :])
                break
    return found


def _pin_state(installs: list[list[str]], name: str) -> str | None:
    """The pinned version, or None when unpinned or any install names it bare."""
    pinned = None
    for args in installs:
        for tok in args:
            if tok.startswith(name + "=="):
                pinned = pinned or tok[len(name) + 2 :]
            elif re.match(re.escape(name) + r"(?![\w.-])", tok):
                return None
    return pinned


def _has_strict_check(commands: list[list[str]]) -> bool:
    return any(c[:4] == ["python", "-m", "twine", "check"] and "--strict" in c for c in commands)


def _publish_pin_problems(workflow: dict, bundles: dict[str, tuple[str, str]]) -> list[str]:
    problems: list[str] = []
    jobs = workflow.get("jobs", {})
    publish_steps = jobs.get("publish", {}).get("steps", [])
    uses = next(
        (
            str(s["uses"])
            for s in publish_steps
            if str(s.get("uses", "")).startswith(_PUBLISHER_PREFIX)
        ),
        None,
    )
    sha_recorded = False
    sha = ""
    if uses is None:
        problems.append("publisher-step-missing")
    else:
        sha = uses[len(_PUBLISHER_PREFIX) :]
        if not _SHA_RE.fullmatch(sha):
            problems.append("publisher-not-sha-pinned")
        elif sha not in bundles:
            problems.append("publisher-sha-unrecorded")
        else:
            sha_recorded = True
    runs = [_run(s) for s in jobs.get("build", {}).get("steps", [])]
    commands = _commands(runs)
    installs = _install_args(commands)
    for idx, name in enumerate(("twine", "packaging")):
        pinned = _pin_state(installs, name)
        if pinned is None:
            problems.append(f"build-{name}-unpinned")
        elif sha_recorded and pinned != bundles[sha][idx]:
            problems.append(f"build-{name}-mismatch")
    if not _has_strict_check(commands):
        problems.append("build-twine-check-missing")
    return problems


def _bundles() -> dict[str, tuple[str, str]]:
    return dict(PUBLISHER_BUNDLES)


def _publisher_step(workflow: dict) -> dict:
    steps = workflow["jobs"]["publish"]["steps"]
    return next(s for s in steps if str(s.get("uses", "")).startswith(_PUBLISHER_PREFIX))


def _install_step(workflow: dict) -> dict:
    steps = workflow["jobs"]["build"]["steps"]
    return next(s for s in steps if "pip install" in _run(s) and "twine" in _run(s))


def test_real_release_workflow_has_no_publish_pin_problems() -> None:
    assert _publish_pin_problems(_load(), _bundles()) == []


def test_plant_sha_bumped_without_pins() -> None:
    wf = copy.deepcopy(_load())
    bundles = {**_bundles(), "b" * 40: ("8.0.0", "27.0")}
    _publisher_step(wf)["uses"] = _PUBLISHER_PREFIX + "b" * 40
    assert _publish_pin_problems(wf, bundles) == [
        "build-twine-mismatch",
        "build-packaging-mismatch",
    ]


def test_plant_unpinned_build_install() -> None:
    wf = copy.deepcopy(_load())
    _install_step(wf)["run"] = "python -m pip install build twine"
    assert _publish_pin_problems(wf, _bundles()) == [
        "build-twine-unpinned",
        "build-packaging-unpinned",
    ]


def test_plant_tag_ref_instead_of_sha() -> None:
    wf = copy.deepcopy(_load())
    _publisher_step(wf)["uses"] = _PUBLISHER_PREFIX + "v1.14.3"
    assert _publish_pin_problems(wf, _bundles()) == ["publisher-not-sha-pinned"]


def test_plant_branch_ref_instead_of_sha() -> None:
    wf = copy.deepcopy(_load())
    _publisher_step(wf)["uses"] = _PUBLISHER_PREFIX + "release/v1"
    assert _publish_pin_problems(wf, _bundles()) == ["publisher-not-sha-pinned"]


def test_plant_unrecorded_sha() -> None:
    wf = copy.deepcopy(_load())
    _publisher_step(wf)["uses"] = _PUBLISHER_PREFIX + "cef221092ed1bacb1cc03d23a2d87d1d172e277b"
    assert _publish_pin_problems(wf, _bundles()) == ["publisher-sha-unrecorded"]


def test_plant_twine_check_dropped() -> None:
    wf = copy.deepcopy(_load())
    steps = wf["jobs"]["build"]["steps"]
    steps[:] = [s for s in steps if "twine check" not in _run(s)]
    assert _publish_pin_problems(wf, _bundles()) == ["build-twine-check-missing"]


def test_plant_publisher_step_removed() -> None:
    wf = copy.deepcopy(_load())
    steps = wf["jobs"]["publish"]["steps"]
    steps[:] = [s for s in steps if not str(s.get("uses", "")).startswith(_PUBLISHER_PREFIX)]
    assert _publish_pin_problems(wf, _bundles()) == ["publisher-step-missing"]


def _without_check_step(workflow: dict) -> list[dict]:
    steps = workflow["jobs"]["build"]["steps"]
    steps[:] = [s for s in steps if "twine check" not in _run(s)]
    return steps


def test_plant_check_only_in_comment() -> None:
    wf = copy.deepcopy(_load())
    steps = _without_check_step(wf)
    install = next(s for s in steps if "pip install" in _run(s) and "twine" in _run(s))
    install["run"] = _run(install) + "# later: python -m twine check --strict dist/*\n"
    assert _publish_pin_problems(wf, _bundles()) == ["build-twine-check-missing"]


def test_plant_pins_only_in_comment() -> None:
    wf = copy.deepcopy(_load())
    _install_step(wf)["run"] = (
        "python -m pip install build twine  # was twine==7.0.0 packaging==26.2"
    )
    assert _publish_pin_problems(wf, _bundles()) == [
        "build-twine-unpinned",
        "build-packaging-unpinned",
    ]


def test_plant_pins_only_in_echo() -> None:
    wf = copy.deepcopy(_load())
    _install_step(wf)["run"] = (
        "echo twine==7.0.0 packaging==26.2\npython -m pip install build twine\n"
    )
    assert _publish_pin_problems(wf, _bundles()) == [
        "build-twine-unpinned",
        "build-packaging-unpinned",
    ]


def test_plant_unpinned_install_beside_pinned_one() -> None:
    wf = copy.deepcopy(_load())
    _install_step(wf)["run"] = (
        "python -m pip install build twine\npython -m pip install twine==7.0.0 packaging==26.2\n"
    )
    assert _publish_pin_problems(wf, _bundles()) == ["build-twine-unpinned"]
