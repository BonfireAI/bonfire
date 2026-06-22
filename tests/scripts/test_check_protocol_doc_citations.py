# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the protocol-doc citation drift checker.

Covers:

1. The checker resolves every current citation in
   ``docs/scan-front-door-protocol.md`` against the current source —
   the doc and the code are in sync as of this commit, so a clean run
   must report 0 drift (the W11 Lane C postcondition).
2. A deliberately drifted citation (line number bumped past every
   indexed symbol and with no recoverable hint) is flagged as
   ``unverified`` — the checker does not silently treat unknown lines
   as OK.
3. A citation whose doc-hint names a real symbol that has moved is
   flagged as ``drift`` — the checker actually catches the failure
   mode it exists to catch.
4. A citation whose cited line sits inside a real
   class/function/assignment is reported as ``ok`` with the resolved
   symbol name — the containment pass works.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "check_protocol_doc_citations.py"
_spec = importlib.util.spec_from_file_location("check_protocol_doc_citations", _SCRIPT_PATH)
assert _spec is not None and _spec.loader is not None
_module = importlib.util.module_from_spec(_spec)
sys.modules["check_protocol_doc_citations"] = _module
_spec.loader.exec_module(_module)


_REPO = Path(__file__).resolve().parents[2]
_PROTOCOL_PY = _REPO / "src" / "bonfire" / "onboard" / "protocol.py"


def test_current_doc_has_no_drift() -> None:
    """The doc shipped in this commit must match current source exactly."""
    rc = _module.main([])
    assert rc == 0, "protocol doc citations have drifted; re-anchor them"


def test_drift_is_flagged_when_hint_resolves_to_moved_symbol() -> None:
    """A citation that names a symbol but points at the wrong line is drift."""
    idx = _module._index_symbols(_PROTOCOL_PY)
    cite = _module.Citation(doc_line=1, path="onboard/protocol.py", start=15, end=15)
    result = _module._check_citation(cite, hint="ConversationStart", index=idx, tolerance=3)
    assert result.status == "drift"
    # The actual ConversationStart class is well-known to live somewhere
    # past the imports block; the exact line is not what we're testing,
    # only that the checker reported drift and resolved to the right
    # symbol name.
    assert result.resolved_symbol == "ConversationStart"


def test_out_of_range_citation_is_unverified_not_silently_ok() -> None:
    """A cited line past EOF with no hint MUST be ``unverified``."""
    idx = _module._index_symbols(_PROTOCOL_PY)
    cite = _module.Citation(doc_line=1, path="onboard/protocol.py", start=99_999, end=99_999)
    result = _module._check_citation(cite, hint=None, index=idx, tolerance=3)
    assert result.status == "unverified"


def test_containment_pass_resolves_in_body_citation() -> None:
    """A citation that lands inside a class body is OK + names the class."""
    idx = _module._index_symbols(_PROTOCOL_PY)
    # ``ScanUpdate``'s ``detail`` field lives inside the ScanUpdate
    # class. The citation does not have to point at the class header
    # to count as OK.
    scan_update_range = idx.by_name["ScanUpdate"]
    in_body_line = scan_update_range[1]  # last line of the class
    cite = _module.Citation(
        doc_line=1,
        path="onboard/protocol.py",
        start=in_body_line,
        end=in_body_line,
    )
    result = _module._check_citation(cite, hint=None, index=idx, tolerance=3)
    assert result.status == "ok"
    assert result.resolved_symbol == "ScanUpdate"
