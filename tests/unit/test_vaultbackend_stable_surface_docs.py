"""Content-sweep test — VaultBackend framed as the stable memory-layer contract.

Locks in the docs framing from the Wave 4 cross-surface audit: ``docs/architecture.md``
must describe the ``VaultBackend`` protocol as the *stable public contract* that future
memory implementations conform to, in two locations:

  1. The ``bonfire.knowledge`` integrations-table row.
  2. The ``VaultBackend`` Extension-points bullet (stable-surface narrative).

And ``README.md`` "What's Not There Yet" must carry the same future-memory-tier framing.

Hard constraint (Acceptance Criteria): the new framing must describe ONLY the public
protocol surface — it must NOT name any closed-tier product. This test enforces that the
framing docs contain none of the forbidden closed-tier names (case-insensitive).
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_ARCH_PATH = _REPO_ROOT / "docs" / "architecture.md"
_README_PATH = _REPO_ROOT / "README.md"

# Closed-tier product names that must never appear in these public docs.
_FORBIDDEN_NAMES = ("arachne", "lexicon", "pantheon")


def _line_containing(text: str, needle: str) -> str:
    """Return the first line that contains ``needle`` (case-insensitive), or ""."""
    needle_low = needle.lower()
    for line in text.splitlines():
        if needle_low in line.lower():
            return line
    return ""


def test_architecture_knowledge_row_frames_protocol_as_stable_contract() -> None:
    """The ``bonfire.knowledge`` table row must frame VaultBackend as the stable contract."""
    text = _ARCH_PATH.read_text(encoding="utf-8")
    row = _line_containing(text, "| `bonfire.knowledge` |")
    assert row, "Could not find the `bonfire.knowledge` integrations-table row."
    row_low = row.lower()
    assert "vaultbackend" in row_low and "stable" in row_low and "contract" in row_low, (
        "The `bonfire.knowledge` row must frame the VaultBackend protocol as the "
        f"stable public contract. Found row:\n  {row}"
    )
    # Single table cell — no line breaks inside the markdown row.
    assert row.count("|") >= 3, f"Row must remain a single markdown table row:\n  {row}"


def test_architecture_extension_point_frames_future_memory_tiers() -> None:
    """The VaultBackend Extension-points bullet must frame it as the stable interface
    future memory tiers conform to."""
    raw = _ARCH_PATH.read_text(encoding="utf-8").lower()
    # Collapse all whitespace (incl. markdown line-wraps and backticks) so the
    # assertions are robust to where the prose happens to wrap.
    text = " ".join(raw.replace("`", "").split())
    assert "stable public interface" in text, (
        "architecture.md must call VaultBackend the stable public interface for the memory layer."
    )
    assert "future memory tiers" in text, (
        "architecture.md extension-point narrative must reference 'future memory tiers'."
    )
    assert "depend on vaultbackend" in text, (
        "architecture.md must advise depending on VaultBackend, not a concrete implementation."
    )


def test_readme_whats_not_there_yet_frames_future_memory_tiers() -> None:
    """README 'What's Not There Yet' must frame VaultBackend as the stable interface
    future memory tiers will implement."""
    raw = _README_PATH.read_text(encoding="utf-8").lower()
    text = " ".join(raw.replace("`", "").split())
    assert "future memory tiers" in text, (
        "README must note VaultBackend is the stable interface future memory tiers implement."
    )
    assert "swappable" in text, (
        "README should note today's in-memory/LanceDB backends are swappable without "
        "touching callers."
    )


def test_no_closed_tier_names_in_public_docs() -> None:
    """Neither architecture.md nor README.md may name closed-tier products."""
    offenders: list[str] = []
    for path in (_ARCH_PATH, _README_PATH):
        low = path.read_text(encoding="utf-8").lower()
        for name in _FORBIDDEN_NAMES:
            if name in low:
                offenders.append(f"{path.name}: '{name}'")
    assert not offenders, "Closed-tier product names must not appear in public docs:\n" + "\n".join(
        f"  - {o}" for o in offenders
    )
