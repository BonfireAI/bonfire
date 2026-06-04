"""Regression guard — the safe-IO hardening stays wired across consumers.

The two helper modules ``src/bonfire/_safe_read.py`` and
``src/bonfire/_safe_write.py`` provide symlink-refusing, size-capped
file IO. They are the only sanctioned way for first-party code to touch
untrusted on-disk paths (scanner inputs, checkpoints, persona files,
session logs). A later edit that silently swaps a ``safe_*`` call back
to a bare ``open()`` / ``Path.read_text()`` would re-open the symlink
TOCTOU and unbounded-read holes the helpers exist to close.

This test pins three properties so such a regression fails loudly:

1. Both helper modules exist on disk.
2. Every module in the expected consumer set still references a safe
   helper (``safe_read_text`` / ``safe_read_capped_text`` /
   ``safe_write_text`` / ``safe_append_text``). The actual consumer set
   is rebuilt from the live source tree on every run, so the guard
   tracks reality rather than a frozen count — but each *expected*
   consumer must still be present, so a silent strip is caught.
3. The security primitives stay in the helper source: ``_safe_write``
   uses ``O_NOFOLLOW`` + ``O_EXCL``; ``_safe_read`` caps the read size.

Reads files on disk only — no subprocess, no import side effects.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` -> ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src" / "bonfire"

# The four public safe-IO helpers. A consumer "uses the hardening" iff
# its source references at least one of these names.
_SAFE_HELPER_PATTERN = re.compile(
    r"safe_read_text|safe_read_capped_text|safe_write_text|safe_append_text"
)

# Expected consumers, relative to ``src/bonfire/``. Each MUST be present
# in the live consumer set (a missing entry = the hardening was stripped
# from a module that needs it). The live grep may surface MORE consumers
# than this list as new code lands — that is fine and not a failure.
_EXPECTED_CONSUMERS: frozenset[str] = frozenset(
    {
        "cli/commands/init.py",
        "cli/commands/install_skill.py",
        "cli/commands/persona.py",
        "cost/consumer.py",
        "engine/checkpoint.py",
        "onboard/config_generator.py",
        "onboard/scanners/claude_memory.py",
        "onboard/scanners/vault_seed.py",
        "scan/tech_scanner.py",
        "session/persistence.py",
        "xp/tracker.py",
    }
)


def _live_consumers() -> set[str]:
    """Rebuild the safe-IO consumer set from the live source tree.

    Returns module paths relative to ``src/bonfire/`` for every ``.py``
    file (excluding the helper modules themselves) whose source
    references a safe helper. This is the on-disk equivalent of
    ``git grep -l 'safe_read_text\\|safe_write' -- src/bonfire``.
    """
    helper_files = {_SRC_DIR / "_safe_read.py", _SRC_DIR / "_safe_write.py"}
    consumers: set[str] = set()
    for path in _SRC_DIR.rglob("*.py"):
        if path in helper_files:
            continue
        text = path.read_text(encoding="utf-8")
        if _SAFE_HELPER_PATTERN.search(text):
            consumers.add(path.relative_to(_SRC_DIR).as_posix())
    return consumers


def test_safe_io_helper_modules_exist() -> None:
    """Both safe-IO helper modules are present on disk."""
    assert (_SRC_DIR / "_safe_read.py").is_file()
    assert (_SRC_DIR / "_safe_write.py").is_file()


def test_live_consumer_set_is_non_empty() -> None:
    """The live source tree still has modules wired to the safe helpers."""
    assert _live_consumers(), (
        "no module under src/bonfire/ references a safe-IO helper — the "
        "hardening appears to have been stripped wholesale"
    )


def test_every_expected_consumer_still_uses_safe_io() -> None:
    """Each expected consumer still references a safe-IO helper.

    A missing entry means a module that previously routed file IO
    through the symlink-refusing / size-capped helpers no longer does —
    a silent regression of the security property this guard protects.
    """
    live = _live_consumers()
    missing = sorted(_EXPECTED_CONSUMERS - live)
    assert not missing, (
        "expected safe-IO consumers no longer reference a safe helper "
        f"(hardening stripped?): {missing}"
    )


def test_safe_write_keeps_nofollow_and_excl() -> None:
    """``_safe_write`` source still wires ``O_NOFOLLOW`` + ``O_EXCL``.

    These flags are the kernel-atomic symlink-refusal (``O_NOFOLLOW``)
    and create-exclusive (``O_EXCL``) primitives that close the write
    TOCTOU race. Their disappearance would silently weaken the writer.
    """
    source = (_SRC_DIR / "_safe_write.py").read_text(encoding="utf-8")
    assert "O_NOFOLLOW" in source
    assert "O_EXCL" in source


def test_safe_read_keeps_size_cap() -> None:
    """``_safe_read`` source still enforces a byte cap on reads.

    The bounded read is the sole mechanism gating output size — losing
    the cap re-opens the unbounded-read / memory-exhaustion hole.
    """
    source = (_SRC_DIR / "_safe_read.py").read_text(encoding="utf-8")
    assert "O_NOFOLLOW" in source
    assert re.search(r"\bcap\b", source), "read-size cap vocabulary missing"
    assert "MAX_CHECKPOINT_BYTES" in source
