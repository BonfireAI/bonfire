"""Contract: every ``src/bonfire/**/*.py`` file carries SPDX + Copyright headers.

Bonfire ships under Apache-2.0. Per the v0.1.0 release-gate checklist
(``docs/release-gates.md``), license headers must be consistent across
``src/`` before a release tag is cut. This test locks in the contract:

  1. Every Python source file under ``src/bonfire/`` carries an
     ``SPDX-License-Identifier: Apache-2.0`` line.
  2. Every Python source file under ``src/bonfire/`` carries a
     ``Copyright YYYY BonfireAI`` line.

Both lines must appear within the first 5 lines of each file. The
5-line tolerance accommodates a possible shebang on line 1 and any
forward-compatible header layout (e.g., a blank line between the two
header lines).

Discovery is dynamic via ``rglob`` — adding or removing a source file
extends or shrinks the contract automatically. Failure messages list
every offending file (relative to the repo root) so the implementer
knows exactly what to fix.

The header form is anchored on regex match (not literal compare) so a
future variation in spacing or year value does not break the contract.
The ``Apache-2.0`` identifier is matched exactly. The copyright year is
matched as ``\\d{4}`` (forward-compatible). The holder is matched
exactly as ``BonfireAI``.

Test scope is intentionally limited to ``src/bonfire/`` — header
discipline does not extend to ``tests/`` or repo-root tooling.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` -> ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src" / "bonfire"

_HEADER_LINE_LIMIT = 5

_SPDX_PATTERN = re.compile(r"#\s*SPDX-License-Identifier:\s*Apache-2\.0")
_COPYRIGHT_PATTERN = re.compile(r"#\s*Copyright\s+\d{4}\s+BonfireAI")


def _iter_source_files(root: Path) -> list[Path]:
    """Return every ``.py`` file under *root*, excluding ``__pycache__``."""
    if not root.is_dir():
        return []
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def _missing(pattern: re.Pattern[str]) -> list[str]:
    """Return repo-relative paths whose first ``_HEADER_LINE_LIMIT`` lines lack *pattern*."""
    failures: list[str] = []
    for py_path in _iter_source_files(_SRC_DIR):
        head = py_path.read_text(encoding="utf-8").splitlines()[:_HEADER_LINE_LIMIT]
        if not any(pattern.search(line) for line in head):
            failures.append(py_path.relative_to(_REPO_ROOT).as_posix())
    return failures


def test_all_src_files_have_spdx_header() -> None:
    """Every ``src/bonfire/**/*.py`` carries ``SPDX-License-Identifier: Apache-2.0``.

    The line must appear within the first 5 lines of the file. Failure
    message lists every offending file relative to the repo root so the
    implementer can fix them in one pass.
    """
    sources = _iter_source_files(_SRC_DIR)
    assert sources, f"Expected at least one .py file under {_SRC_DIR}"

    failures = _missing(_SPDX_PATTERN)
    assert not failures, (
        f"{len(failures)} source files missing "
        f"'SPDX-License-Identifier: Apache-2.0' in first {_HEADER_LINE_LIMIT} lines:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )


def test_all_src_files_have_copyright_line() -> None:
    """Every ``src/bonfire/**/*.py`` carries ``Copyright YYYY BonfireAI``.

    The line must appear within the first 5 lines of the file. The year
    is matched as ``\\d{4}`` (forward-compatible); the holder is matched
    exactly as ``BonfireAI``. Failure message lists every offending file
    relative to the repo root so the implementer can fix them in one pass.
    """
    sources = _iter_source_files(_SRC_DIR)
    assert sources, f"Expected at least one .py file under {_SRC_DIR}"

    failures = _missing(_COPYRIGHT_PATTERN)
    assert not failures, (
        f"{len(failures)} source files missing "
        f"'Copyright YYYY BonfireAI' in first {_HEADER_LINE_LIMIT} lines:\n"
        + "\n".join(f"  - {f}" for f in failures)
    )
