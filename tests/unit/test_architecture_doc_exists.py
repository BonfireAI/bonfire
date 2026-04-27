"""RED test — ``docs/architecture.md`` exists with the eight required H2 sections.

Locks in audit item **C1** from the BON-353 doc-polish audit
(``docs/audit/scout-reports/bon-353-audit-20260427T164458Z.md``).

The repo has README (consumer-facing), per-module ``__init__.py``
docstrings (contributor-facing detail), and ``docs/audit/sage-decisions/``
(decision provenance) — but nothing that orients a brand-new
contributor: "what packages exist, what flows through them, where to
plug in new behavior."

This test asserts:

  1. ``docs/architecture.md`` exists at the repo root, alongside the
     other contributor-facing docs (``release-policy.md``, ``release-gates.md``).
  2. The doc contains the eight H2 sections sketched by the Scout
     (matched flexibly so the Warrior can phrase headings naturally).
  3. The doc is at least 100 lines long — newcomer orientation needs
     substance, not a stub.

The eight H2 anchors (substring match against ``^## `` headings):

  * "What Bonfire is"
  * "Module map"
  * "Pipeline flow"
  * "Event bus" (or "Event bus and consumers")
  * "Extension"
  * "Gate" (or "Gates and quality")
  * "Security"
  * "read next" / "Next reading"

Expected RED state at HEAD: file does not exist; all three assertions
fail (or a single early-return assertion fails depending on order).
"""

from __future__ import annotations

from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_PATH = _REPO_ROOT / "docs" / "architecture.md"

_MIN_DOC_LINES = 100

# Each tuple = (human-readable-name, list-of-acceptable-substrings).
# A heading is satisfied if ANY of its acceptable substrings appears
# in any line that starts with ``## `` (case-insensitive).
_REQUIRED_SECTIONS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("What Bonfire is", ("what bonfire is",)),
    ("Module map", ("module map",)),
    ("Pipeline flow", ("pipeline flow",)),
    ("Event bus", ("event bus",)),
    ("Extension points", ("extension",)),
    ("Gates", ("gate",)),
    ("Security model", ("security",)),
    ("Where to read next", ("read next", "next reading")),
)


def _h2_headings(text: str) -> list[str]:
    """Return all H2 heading lines (those starting with ``## ``) lower-cased."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## ") and not stripped.startswith("###"):
            out.append(stripped.lower())
    return out


def test_architecture_doc_exists() -> None:
    """``docs/architecture.md`` must exist at the repo root."""
    assert _DOC_PATH.is_file(), (
        f"Expected newcomer-orientation doc at {_DOC_PATH} (BON-353 audit "
        "item C1). Sits next to docs/release-policy.md and docs/release-gates.md."
    )


def test_architecture_doc_has_substance() -> None:
    """``docs/architecture.md`` must be at least 100 lines long.

    A stub is worse than nothing — newcomers expect orientation, not a
    placeholder. Length budget per Scout: 250–400 lines.
    """
    assert _DOC_PATH.is_file(), (
        f"{_DOC_PATH} does not exist — cannot check length. See "
        "test_architecture_doc_exists."
    )
    line_count = len(_DOC_PATH.read_text(encoding="utf-8").splitlines())
    assert line_count >= _MIN_DOC_LINES, (
        f"docs/architecture.md is only {line_count} lines — the Scout "
        f"recommends 250–400 lines for a newcomer doc; minimum is "
        f"{_MIN_DOC_LINES}."
    )


def test_architecture_doc_has_required_sections() -> None:
    """``docs/architecture.md`` must contain the eight required H2 sections.

    Match is case-insensitive substring against H2 heading lines so the
    Warrior can phrase headings naturally (e.g. ``## Event bus and
    consumers`` or ``## Where to read next`` both work).
    """
    assert _DOC_PATH.is_file(), (
        f"{_DOC_PATH} does not exist — cannot check sections. See "
        "test_architecture_doc_exists."
    )
    text = _DOC_PATH.read_text(encoding="utf-8")
    headings = _h2_headings(text)

    missing: list[str] = []
    for name, accepted in _REQUIRED_SECTIONS:
        found = any(any(sub in heading for sub in accepted) for heading in headings)
        if not found:
            missing.append(name)

    assert not missing, (
        "docs/architecture.md is missing required H2 sections "
        "(BON-353 audit item C1):\n"
        + "\n".join(f"  - {name}" for name in missing)
        + "\n\nFound H2 headings:\n"
        + ("\n".join(f"  {h}" for h in headings) if headings else "  <none>")
    )
