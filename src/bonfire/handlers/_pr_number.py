# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Shared PR-number extraction for pipeline stage handlers.

Three handlers (wizard, steward, merge_preflight) carried identical
``_extract_pr_number`` definitions. This module is the single source of
truth. The resolution chain is:

    1. ``prior_results[META_PR_NUMBER]`` — int-coerce (str-tolerant).
    2. ``prior_results["bard"]`` — ``/pull/(\\d+)`` URL regex fallback.
    3. ``envelope.metadata[META_PR_NUMBER]`` — int-coerce; consulted ONLY
       when ``envelope`` is not ``None``.

Steward's historical behaviour had no envelope fallback, so callers that
must preserve that pass ``envelope=None`` (the default) — the metadata
path is then skipped entirely.
"""

from __future__ import annotations

import re
from typing import Any

from bonfire.models.envelope import META_PR_NUMBER

_PULL_URL_RE = re.compile(r"/pull/(\d+)")


def extract_pr_number(
    prior_results: dict[str, Any],
    envelope: Any = None,
) -> int | None:
    """Extract a PR number from prior_results, optionally falling back to envelope.

    Returns ``None`` when no PR number is recoverable. Int-coerce failures
    fall through to the next path (never raise).
    """
    raw = prior_results.get(META_PR_NUMBER)
    if raw is not None:
        try:
            return int(raw)
        except (ValueError, TypeError):
            pass

    bard_val = prior_results.get("bard", "")
    if bard_val:
        m = _PULL_URL_RE.search(str(bard_val))
        if m:
            return int(m.group(1))

    if envelope is not None:
        meta_val = envelope.metadata.get(META_PR_NUMBER)
        if meta_val is not None:
            try:
                return int(meta_val)
            except (ValueError, TypeError):
                pass

    return None


__all__ = ["extract_pr_number"]
