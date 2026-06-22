# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Content hashing utilities for vault dedup.

SHA-256 of normalized content. Used by VaultEntry.content_hash and
incremental ingestion to detect duplicates.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path  # noqa: TC003 — used at runtime in file_hash()


def content_hash(text: str) -> str:
    """SHA-256 hex digest of normalized text.

    Normalization: strip leading/trailing whitespace, collapse internal
    whitespace runs to single space.
    """
    normalized = re.sub(r"\s+", " ", text.strip())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def file_hash(path: Path) -> str:
    """SHA-256 hex digest of a file's content, normalized.

    Raises ``FileNotFoundError`` if *path* does not exist.
    """
    if not path.is_file():
        raise FileNotFoundError(path)
    return content_hash(path.read_text(encoding="utf-8"))
