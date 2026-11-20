# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Workflow files, comments included, carry no internal issue reference.

``_reference_problems`` is a pure helper over raw text, so the real files and the
planted references are judged by one function. Raw text is read, not parsed YAML,
because comments are dropped by the parser. One allowance: a full public security
advisory id is removed from a line before it is scanned.
"""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOW_DIR = Path(__file__).resolve().parents[2] / ".github" / "workflows"

_REFERENCE_RE = re.compile(r"\b[A-Z]{2,}-[0-9]+")
_ADVISORY_RE = re.compile(r"\bGHSA(?:-[0-9a-z]{4}){3}\b")


def _workflow_paths() -> list[Path]:
    return sorted([*WORKFLOW_DIR.glob("*.yml"), *WORKFLOW_DIR.glob("*.yaml")])


def _reference_problems(texts: dict[str, str]) -> list[str]:
    """Return ``<file>:<line>: <match>`` for each internal reference found."""
    if not texts:
        return ["VOID: no workflow files were scanned"]
    problems: list[str] = []
    for name, text in texts.items():
        for number, line in enumerate(text.splitlines(), start=1):
            scanned = _ADVISORY_RE.sub("", line)
            problems.extend(
                f"{name}:{number}: {m.group(0)}" for m in _REFERENCE_RE.finditer(scanned)
            )
    return problems


def _ref(prefix: str, digits: str) -> str:
    return prefix + "-" + digits


def test_real_workflows_have_no_internal_references() -> None:
    texts = {p.name: p.read_text(encoding="utf-8") for p in _workflow_paths()}
    assert _reference_problems(texts) == []


def test_empty_input_is_void() -> None:
    problems = _reference_problems({})
    assert len(problems) == 1
    assert problems[0].startswith("VOID")


def test_directory_yields_files_and_count_matches_glob() -> None:
    paths = _workflow_paths()
    assert len(paths) > 0
    texts = {p.name: p.read_text(encoding="utf-8") for p in paths}
    assert len(texts) == len(list(WORKFLOW_DIR.glob("*.yml"))) + len(
        list(WORKFLOW_DIR.glob("*.yaml"))
    )


def test_planted_reference_in_comment_is_reported_with_file_and_line() -> None:
    text = "name: x\n# " + _ref("Q" * 3, "41") + " note\non: push\n"
    assert _reference_problems({"a.yml": text}) == ["a.yml:2: " + _ref("QQQ", "41")]


def test_planted_reference_in_run_value_is_reported() -> None:
    text = "jobs:\n  t:\n    steps:\n      - run: echo " + _ref("ZZ", "7") + "\n"
    assert _reference_problems({"b.yml": text}) == ["b.yml:4: " + _ref("ZZ", "7")]


def test_full_advisory_id_passes() -> None:
    advisory = "GHSA-" + "-".join(["5xjx", "3w67", "w9x9"])
    assert _reference_problems({"c.yml": "# inside " + advisory + " fixed\n"}) == []


def test_malformed_advisory_id_is_reported() -> None:
    malformed = "GHSA-" + "5xjx"
    assert _reference_problems({"d.yml": "# see " + malformed + "\n"}) == [
        "d.yml:1: " + "GHSA" + "-5"
    ]


def test_lowercase_or_single_letter_form_is_not_reported() -> None:
    text = "# " + "d-12" + " and " + "D-12" + "\n"
    assert _reference_problems({"e.yml": text}) == []
