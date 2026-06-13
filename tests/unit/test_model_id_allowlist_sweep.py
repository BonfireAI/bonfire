"""Sweep test — every Claude model id in src/ + config is a real, current id.

Walks every ``.py`` file under ``src/bonfire/`` plus the user-facing config
surfaces (``.env.example``, ``README.md``, ``pyproject.toml``) and extracts
every token shaped like a Claude *model* id. Each one must be a member of
the explicit allowlist of real, currently-served model ids below.

Why this exists: model ids rot silently. A deprecated tier keeps working
until the provider retires it, then every call 404s at once; worse, an id
that was never real (a hallucinated date-suffixed variant) 404s on first
use while looking perfectly plausible in review. This sweep makes every
model-id literal in the shipped surface cost an explicit allowlist entry,
so a model ratchet is a deliberate, reviewed event instead of drift.

Scope notes:

* Only *model-family* tokens are checked (``claude-opus*``, ``claude-sonnet*``,
  ``claude-haiku*``, ``claude-fable*``, ``claude-mythos*``). Other ``claude-*``
  tokens — package names (``claude-agent-sdk``), tool names (``claude-cli``,
  ``claude-code``), editor dirs (``claude-dev``, ``claude-plugin``) — are not
  model ids and are exempt.
* ``tests/`` is intentionally out of scope: fixtures use deliberately fake
  tier placeholders (``claude-sonnet``, ``claude-opus``) that never reach a
  provider. ``docs/audit/`` is frozen decision history and is never edited.

Reads files on disk only — no subprocess, no network.
"""

from __future__ import annotations

import re
from pathlib import Path

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC_DIR = _REPO_ROOT / "src" / "bonfire"

# User-facing config surfaces that carry live defaults.
_CONFIG_FILES: tuple[str, ...] = (
    ".env.example",
    "README.md",
    "pyproject.toml",
)

# Tokens shaped like a Claude id. The follow-up family filter decides
# whether a token is a *model* id (vs a package/tool name).
_CLAUDE_TOKEN = re.compile(r"claude-[a-z0-9][a-z0-9-]*")
_MODEL_FAMILY = re.compile(r"^claude-(opus|sonnet|haiku|fable|mythos)(-|$)")

# ---------------------------------------------------------------------------
# Allowlist — real, currently-served model ids ONLY.
# ---------------------------------------------------------------------------
# Extending this set is a deliberate act: add an id only when the provider
# actually serves it. Dated variants are allowed only when they are real
# published snapshot ids (none are currently needed in this repo).
_ALLOWED_MODEL_IDS: frozenset[str] = frozenset(
    {
        "claude-fable-5",
        "claude-opus-4-8",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    }
)


def _iter_scanned_files() -> list[Path]:
    """All files in scope: src/bonfire/**/*.py + the config surfaces."""
    files = [p for p in sorted(_SRC_DIR.rglob("*.py")) if "__pycache__" not in p.parts]
    for name in _CONFIG_FILES:
        candidate = _REPO_ROOT / name
        if candidate.is_file():
            files.append(candidate)
    return files


def _model_tokens(line: str) -> list[str]:
    """Extract model-family claude tokens from one line of text."""
    return [token for token in _CLAUDE_TOKEN.findall(line) if _MODEL_FAMILY.match(token)]


def test_all_model_ids_in_src_and_config_are_allowlisted() -> None:
    """Every model-id literal in src/ + config must be a real current id.

    Failure message lists every offender as ``path:line: token`` so the
    fixer can navigate directly. A new model generation means bumping the
    literals AND the allowlist in the same change.
    """
    offenders: list[str] = []
    for path in _iter_scanned_files():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            for token in _model_tokens(line):
                if token not in _ALLOWED_MODEL_IDS:
                    offenders.append(f"  {rel}:{i}: {token}")

    assert not offenders, (
        "Found Claude model ids outside the current-id allowlist.\n"
        "Each is deprecated, retired, or was never a real model id. "
        "Bump it to a current id (or, for a genuinely new real id, extend "
        "_ALLOWED_MODEL_IDS in this test with rationale).\n" + "\n".join(offenders)
    )


def test_allowlist_ids_look_like_model_ids() -> None:
    """Self-check: every allowlist entry matches the model-id shape.

    Guards against typos in the allowlist itself (an entry that the
    extractor could never produce would silently never match anything).
    """
    malformed = [
        model_id
        for model_id in _ALLOWED_MODEL_IDS
        if not (_CLAUDE_TOKEN.fullmatch(model_id) and _MODEL_FAMILY.match(model_id))
    ]
    assert not malformed, f"Malformed allowlist entries: {malformed}"
