# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""JSONL-based session event persistence."""

from __future__ import annotations

import json
from pathlib import Path

from bonfire._safe_read import MAX_CHECKPOINT_BYTES, safe_read_capped_text
from bonfire._safe_write import safe_append_text
from bonfire.models.events import (
    BonfireEvent,  # noqa: TC001 — runtime use for model_dump()
    _validate_session_id,
)


def _validate_session_id_at_boundary(session_id: str) -> str:
    """Defense-in-depth: validate ``session_id`` at the persistence
    class boundary.

    ``BonfireEvent.session_id`` is already validated by ``_validate_session_id``
    at the model layer (allowing the empty-string sentinel for
    ``AxiomLoaded``). But ``SessionPersistence`` is in
    ``bonfire.session.__all__`` and external library consumers can call
    every public method with a user-controlled string that NEVER
    transits a ``BonfireEvent`` model. Without this check, a value like
    ``"../../etc/passwd"`` interpolates into ``{session_id}.jsonl`` and
    becomes a path-traversal write/read primitive at the filesystem
    boundary (W11 H2 defense-in-depth gap).

    The empty-string sentinel is REJECTED at the persistence boundary
    even though the model accepts it: an empty ``session_id`` produces
    ``.jsonl`` as the filename — a write/read against the parent
    directory's hidden file. ``AxiomLoaded`` is a domain event that
    legitimately omits ``session_id``; it MUST NOT be persisted under
    that sentinel value via ``SessionPersistence.append_event``. The
    layered check (model accepts ``""`` for ``AxiomLoaded`` ergonomics;
    persistence refuses ``""`` to keep the on-disk shape sane) preserves
    both contracts.
    """
    if session_id == "":
        msg = (
            "invalid session_id '': empty string is the BonfireEvent "
            "outside-session sentinel and MUST NOT be persisted (would "
            "produce '.jsonl' as the filename)."
        )
        raise ValueError(msg)
    return _validate_session_id(session_id)


class SessionPersistence:
    """Append-only JSONL storage for session events."""

    def __init__(self, session_dir: Path) -> None:
        self._session_dir = Path(session_dir)

    def _session_path(self, session_id: str) -> Path:
        return self._session_dir / f"{session_id}.jsonl"

    def append_event(self, session_id: str, event: BonfireEvent) -> None:
        """Append a single event as a JSON line.

        Uses ``safe_append_text`` to refuse symlinks at the target path
        (via ``is_symlink()`` pre-check + ``O_NOFOLLOW`` defense-in-
        depth). The W7.M ``safe_write_text`` rollout closed truncate-
        mode write sites but missed this append-mode site; a planted
        symlink at ``{session_id}.jsonl`` would otherwise redirect
        every JSONL event line to an attacker-controlled target.

        W11 H2: ``_validate_session_id_at_boundary`` rejects path-
        traversal shapes (``..``, ``/``, ``\\``, null, control chars,
        oversized, empty) at this class boundary so external callers
        passing user-controlled ``session_id`` cannot smuggle a write
        outside ``self._session_dir``. The event itself already has its
        ``session_id`` validated at the model layer; this is the parallel
        defense for the kwarg, which a library consumer can pass
        independently of any event.
        """
        _validate_session_id_at_boundary(session_id)
        self._session_dir.mkdir(parents=True, exist_ok=True)
        path = self._session_path(session_id)
        line = json.dumps(event.model_dump(mode="json"))
        safe_append_text(path, line + "\n")

    def read_events(self, session_id: str) -> list[dict]:
        """Read all events for a session. Raises FileNotFoundError if missing.

        Uses ``safe_read_capped_text`` (W7.M read-side helper) to refuse
        symlinks at the JSONL path via ``is_symlink()`` pre-check +
        ``O_NOFOLLOW`` defense-in-depth, and to cap reads at
        ``MAX_CHECKPOINT_BYTES`` (10 MiB). Symmetric mirror of the
        ``safe_append_text`` write-side hardening on ``append_event``:
        Wave 9 closed the write half of the operator-controlled JSONL
        attack surface; this closes the read half.

        Distinguish missing-file (legitimate "session never ran") from
        symlink/oversize refusal (security signal) by ``Path.exists()``
        BEFORE the safe-read call. ``Path.exists()`` follows symlinks,
        so a dangling symlink at the JSONL path returns ``False`` and
        would otherwise be reported as "no session file" — masking the
        attack. Use ``Path.is_symlink()`` first to route any symlink
        (live, dangling, looping) into the safe-read helper, which
        raises ``FileExistsError`` with the W7.M ``"symlink"`` log-grep
        substring.

        W11 H2: ``_validate_session_id_at_boundary`` rejects path-
        traversal shapes at this class boundary BEFORE the path is
        constructed so a hostile ``session_id`` like ``"../../etc/passwd"``
        never reaches ``Path.is_symlink`` against an attacker-chosen
        location.
        """
        _validate_session_id_at_boundary(session_id)
        path = self._session_path(session_id)
        if not path.is_symlink() and not path.exists():
            msg = f"No session file: {path}"
            raise FileNotFoundError(msg)
        text = safe_read_capped_text(path, max_bytes=MAX_CHECKPOINT_BYTES)
        lines = text.strip().splitlines()
        return [json.loads(line) for line in lines]

    def list_sessions(self) -> list[str]:
        """Return sorted list of session IDs from .jsonl filenames."""
        if not self._session_dir.exists():
            return []
        return sorted(p.stem for p in self._session_dir.glob("*.jsonl"))

    def session_exists(self, session_id: str) -> bool:
        """Check whether a session file exists.

        W11 H2: ``_validate_session_id_at_boundary`` rejects path-traversal
        shapes BEFORE any filesystem call so a hostile ``session_id`` like
        ``"../../etc/passwd"`` never produces a positive ``exists()``
        return for an attacker-controlled path.
        """
        _validate_session_id_at_boundary(session_id)
        return self._session_path(session_id).exists()
