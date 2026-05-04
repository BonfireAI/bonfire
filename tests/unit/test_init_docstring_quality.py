"""RED test — every ``__init__.py`` under ``src/bonfire/`` carries a real docstring.

Locks in audit items **A1–A6** from the BON-353 doc-polish audit
(``docs/audit/scout-reports/bon-353-audit-20260427T164458Z.md``).

Walks every ``__init__.py`` under ``src/bonfire/`` and asserts that:

  1. The module has a docstring (not ``None``).
  2. The docstring is at least 40 characters after ``.strip()``.
  3. The docstring does NOT contain the literal substring
     ``"placeholder for v0.1 transfer"`` — placeholder docstrings
     promise machinery that doesn't exist (or, worse, lie about
     packages that DO ship real code, e.g. ``models``).

Discovery is dynamic via ``rglob`` — if the Warrior chooses to delete
an empty package (a valid GREEN path for audit items A1 and A6) the
test simply has one less file to check.

Expected RED-state failures at HEAD include (audit Category A):

  * ``src/bonfire/models/__init__.py``  — placeholder (item A5, FALSE
    placeholder; package contains real, heavily-imported modules).
  * ``src/bonfire/events/__init__.py``  — short one-liner (item A4).

Other failures may surface from later refactors (e.g. ``cli/__init__.py``
short tagline) — those are real invariant violations and should be
fixed in the same wave or a follow-up ticket. The test is durable.
"""

from __future__ import annotations

import ast
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src" / "bonfire"

_MIN_DOCSTRING_CHARS = 40
_BANNED_PLACEHOLDER = "placeholder for v0.1 transfer"


def _iter_init_files(root: Path) -> list[Path]:
    """Return every ``__init__.py`` under *root*, excluding ``__pycache__``."""
    if not root.is_dir():
        return []
    return [p for p in root.rglob("__init__.py") if "__pycache__" not in p.parts]


def _classify(path: Path) -> tuple[str, str]:
    """Classify an ``__init__.py`` against the docstring contract.

    Returns ``(status, evidence)`` where ``status`` is one of:

      * ``"ok"``         — passes all three checks.
      * ``"missing"``    — no module docstring at all.
      * ``"too_short"``  — docstring exists but is < 40 chars stripped.
      * ``"placeholder"`` — docstring contains the banned placeholder substring.
      * ``"parse_error"`` — module text could not be parsed (rare).

    ``evidence`` is the first 60 characters of the docstring (or the
    parse-error message), useful for the failure report.
    """
    src = path.read_text(encoding="utf-8")
    try:
        doc = ast.get_docstring(ast.parse(src))
    except SyntaxError as exc:
        return "parse_error", str(exc)
    if doc is None:
        return "missing", "<no docstring>"
    if _BANNED_PLACEHOLDER in doc:
        return "placeholder", doc.strip()[:60]
    if len(doc.strip()) < _MIN_DOCSTRING_CHARS:
        return "too_short", doc.strip()[:60]
    return "ok", doc.strip()[:60]


def test_every_init_py_has_real_docstring() -> None:
    """Every ``src/bonfire/**/__init__.py`` must carry a real docstring.

    Failure message lists each offender as
    ``(path, status, current_text_first_60_chars)`` so the Warrior knows
    exactly what to fix.
    """
    init_files = _iter_init_files(_SRC_DIR)
    assert init_files, f"Expected at least one __init__.py under {_SRC_DIR}"

    offenders: list[tuple[str, str, str]] = []
    for init in init_files:
        status, evidence = _classify(init)
        if status != "ok":
            rel = init.relative_to(_REPO_ROOT).as_posix()
            offenders.append((rel, status, evidence))

    assert not offenders, (
        "Found __init__.py files with placeholder, too-short, or missing "
        "docstrings (BON-353 audit Category A):\n"
        + "\n".join(f"  {p}: {status} — {evidence!r}" for p, status, evidence in offenders)
    )
