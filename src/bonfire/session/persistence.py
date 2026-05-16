# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""JSONL-based session event persistence."""

from __future__ import annotations

import json
from pathlib import Path

from bonfire._safe_write import safe_append_text
from bonfire.models.events import BonfireEvent  # noqa: TC001 — runtime use for model_dump()


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
        """
        self._session_dir.mkdir(parents=True, exist_ok=True)
        path = self._session_path(session_id)
        line = json.dumps(event.model_dump(mode="json"))
        safe_append_text(path, line + "\n")

    def read_events(self, session_id: str) -> list[dict]:
        """Read all events for a session. Raises FileNotFoundError if missing."""
        path = self._session_path(session_id)
        if not path.exists():
            msg = f"No session file: {path}"
            raise FileNotFoundError(msg)
        lines = path.read_text().strip().splitlines()
        return [json.loads(line) for line in lines]

    def list_sessions(self) -> list[str]:
        """Return sorted list of session IDs from .jsonl filenames."""
        if not self._session_dir.exists():
            return []
        return sorted(p.stem for p in self._session_dir.glob("*.jsonl"))

    def session_exists(self, session_id: str) -> bool:
        """Check whether a session file exists."""
        return self._session_path(session_id).exists()
