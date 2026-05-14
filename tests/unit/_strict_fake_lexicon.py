# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Strict-Protocol Lexicon test double for the Caronte vendor port.

This helper is the load-bearing canon-grade lesson from the private tree:
permissive ``**kwargs`` test doubles absorb handler-vs-backend Protocol
drift silently, leaving the test bracket GREEN while production wire-up
crashes (see ``feedback_fake_lexicon_hides_vendor_mismatch_2026_05_12``).

The strict fake declares every Lexicon method with an EXPLICIT keyword
signature. Unknown kwargs raise ``TypeError`` at the Python call site so
vendor-seam drift surfaces in the test bracket BEFORE it reaches the
real backend.

This double is imported by:

* ``tests/unit/test_inquisitor_handler.py``
* ``tests/unit/test_loremaster_handler.py``

It mirrors the post-d72903b ``memory_supersede`` MCP handler shape on
``bonfire-lexicon`` master: both the legacy same-project ``project=``
shorthand AND the explicit cross-project ``project_old=``/``project_new=``
pair are accepted; mixing them raises ``ValueError``.

Source reference: ``ishtar/tests/handlers/test_phase_d_1_design_vendor_seam.py``
``_StrictFakeLexicon`` definition (night-3 PR #100 architectural close).
"""

from __future__ import annotations

from typing import Any


class StrictFakeLexicon:
    """Strict-Protocol Lexicon test double — explicit kwargs, no ``**kwargs``.

    Any kwarg not in an explicit signature raises ``TypeError`` at the
    Python call site. The fake records every call against the
    appropriate ``*_calls`` list so contract tests can introspect.

    Both same-project ``supersede(project=...)`` and cross-project
    ``supersede(project_old=..., project_new=...)`` forms are accepted;
    mixing them raises ``ValueError``. This mirrors the
    ``bonfire-lexicon`` master ``d72903b`` ``memory_supersede`` XOR
    validation.

    The fake's ``write`` and ``supersede`` ``frontmatter`` kwargs are
    REQUIRED — the Caronte handler's ``_build_frontmatter`` ALWAYS
    produces a dict and the production wire-up ALWAYS forwards it.
    Letting it default to ``None`` would re-create the BC mask the
    architectural fix removes.
    """

    def __init__(
        self,
        *,
        search_returns: list[list[dict]] | None = None,
        list_returns: list[list[dict]] | None = None,
        read_index: dict[str, dict] | None = None,
    ) -> None:
        self.search_returns: list[list[dict]] = list(search_returns or [])
        self.list_returns: list[list[dict]] = list(list_returns or [])
        self.read_index: dict[str, dict] = dict(read_index or {})
        self.search_calls: list[dict] = []
        self.list_calls: list[dict] = []
        self.read_calls: list[dict] = []
        self.write_calls: list[dict] = []
        self.supersede_calls: list[dict] = []

    # -- search / list / read ------------------------------------------------

    def search(self, *, query: str, scope: str, kind: str) -> list[dict]:
        self.search_calls.append({"query": query, "scope": scope, "kind": kind})
        if self.search_returns:
            return self.search_returns.pop(0)
        return []

    def list(
        self,
        *,
        scope: str,
        kind: str | None = None,
        limit: int | None = None,
        since: Any = None,
    ) -> list[dict]:
        self.list_calls.append({"scope": scope, "kind": kind, "limit": limit, "since": since})
        if self.list_returns:
            return self.list_returns.pop(0)
        return []

    def read(self, *, key: str, project: str, kind: str | None = None) -> dict | None:
        self.read_calls.append({"key": key, "project": project, "kind": kind})
        return self.read_index.get(key)

    # -- write — strict signature, frontmatter REQUIRED ----------------------

    def write(
        self,
        *,
        project: str,
        key: str,
        kind: str,
        content: str,
        tags: list[str],
        frontmatter: dict,
    ) -> None:
        """Strict-Protocol write. Unknown kwargs surface as TypeError."""
        self.write_calls.append(
            {
                "project": project,
                "key": key,
                "kind": kind,
                "content": content,
                "tags": tags,
                "frontmatter": frontmatter,
            }
        )

    # -- supersede — the vendor-seam closure ---------------------------------

    def supersede(
        self,
        *,
        key_old: str,
        key_new: str,
        kind: str,
        content: str,
        tags: list[str],
        frontmatter: dict,
        project: str | None = None,
        project_old: str | None = None,
        project_new: str | None = None,
    ) -> None:
        """Strict-Protocol supersede with XOR project / project_old+new.

        - Legacy: ``project=`` fills both sides (same-project supersede
          used by the Inquisitor's muscle writes; preserved for BC).
        - Cross-project: ``project_old=`` + ``project_new=`` explicit
          (Loremaster's tech-promotion path).
        - Mixed: ``ValueError``.
        - Neither: ``ValueError``.
        - Half cross-project (``project_old`` without ``project_new`` or
          vice-versa): ``ValueError``.

        Unknown kwargs surface as ``TypeError`` at the Python call site.
        """
        explicit_form = (project_old is not None) or (project_new is not None)
        shorthand_form = project is not None
        if shorthand_form and explicit_form:
            raise ValueError(
                "supersede accepts either project= (legacy shorthand) OR "
                "project_old=/project_new= (explicit cross-project form), "
                "not both"
            )
        if not shorthand_form and not explicit_form:
            raise ValueError(
                "supersede requires project= (legacy shorthand) or "
                "project_old=/project_new= (explicit cross-project form)"
            )
        if explicit_form and (project_old is None or project_new is None):
            raise ValueError(
                "explicit cross-project form requires BOTH project_old= and project_new="
            )

        if shorthand_form:
            proj_old = project
            proj_new = project
        else:
            proj_old = project_old
            proj_new = project_new

        self.supersede_calls.append(
            {
                "key_old": key_old,
                "key_new": key_new,
                "kind": kind,
                "content": content,
                "tags": tags,
                "frontmatter": frontmatter,
                "project": project,
                "project_old": proj_old,
                "project_new": proj_new,
            }
        )


__all__ = ["StrictFakeLexicon"]
