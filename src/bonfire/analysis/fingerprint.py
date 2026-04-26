"""Project-analysis fingerprint.

Pure sha256 digest over
``(input_fingerprint, budget, versions, schema_version)``. Workspace-
agnostic per §12 C3 so two workspaces with identical files produce the
same fingerprint (Wave 2b cache reuse proof).

Stdlib-only imports at module top. ``CartographerBudget`` is imported
lazily under ``TYPE_CHECKING`` so importing this module does not pull
``pydantic`` or any heavy dependency into ``sys.modules``.
"""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from bonfire.analysis.models import CartographerBudget


def compute_study_fingerprint(
    input_fingerprint: str,
    budget: CartographerBudget,
    versions: dict[str, str],
    schema_version: int,
) -> str:
    """Return a sha256 hex digest of the study's structural inputs.

    The four inputs together form Wave 2b's cache key:

    * ``input_fingerprint`` — sha256 over sorted ``(relpath, sha256(bytes))``
      tuples, pre-computed by ``parser.parse_workspace``.
    * ``budget`` — frozen Pydantic model; serialized via ``model_dump``.
    * ``versions`` — ``{"cartographer": ..., "tree_sitter_language_pack": ...,
      "tiktoken": ..., "networkx": ...}``.
    * ``schema_version`` — ``ProjectAnalysis.study_schema_version``.

    Workspace identity is intentionally NOT part of the fingerprint
    (§12 C3) so the cache can be reused across workspaces that scan the
    same sources.
    """
    payload = {
        "input_fingerprint": input_fingerprint,
        "budget": budget.model_dump(),
        "versions": versions,
        "schema_version": schema_version,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()
