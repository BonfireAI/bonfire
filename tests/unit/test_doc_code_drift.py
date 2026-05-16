# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Lock the architecture doc to the shipped roster — no silent drift.

Probe N+5 Scout 2 surfaced four drift findings between ``docs/architecture.md``
and ``src/bonfire/``:

  * D1 — gate count mismatch (doc claimed six; code shipped eight).
  * D2 — handler roster mismatch (doc claimed four; code shipped six).
  * D3 — ``bonfire run`` opening line described a CLI verb that does not
    exist in v0.1.
  * D4 (Probe N+4 carry-over) — ``ROLE_DISPLAY`` had no entry for the
    workflow-factory ``"prover"`` role; ADR-001 § Ratified Exceptions
    did not enumerate the gamified-keyed display surface.

The first three doc-side claims are reconciled by this PR; the regression
tests in this module prevent the same family of drift from recurring at
CI time. Each test compares a code-side ground-truth roster against the
architecture.md table that mirrors it.

The tests are deliberately small and AST-/regex-based — they do not
import the shipped factory closures (parsing source text is cheaper and
exposes the actual wire-format strings used at factory build time).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from bonfire.agent.roles import AgentRole
from bonfire.agent.tiers import GAMIFIED_TO_GENERIC
from bonfire.naming import ROLE_DISPLAY

# Repo root = ``repo/tests/unit/<this file>`` → ``repo/``.
_REPO_ROOT = Path(__file__).resolve().parents[2]
_DOC_PATH = _REPO_ROOT / "docs" / "architecture.md"
_GATES_SRC = _REPO_ROOT / "src" / "bonfire" / "engine" / "gates.py"
_HANDLERS_PKG = _REPO_ROOT / "src" / "bonfire" / "handlers"
_WORKFLOW_PKG = _REPO_ROOT / "src" / "bonfire" / "workflow"


# ---------------------------------------------------------------------------
# Helpers — parse the architecture.md gate/handler tables and the shipped
# source rosters. Each helper is small and one-purpose; failures point
# directly at the surface that drifted.
# ---------------------------------------------------------------------------


def _classes_in_module(path: Path, suffix: str) -> set[str]:
    """Return every top-level class name in *path* whose name ends with *suffix*."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.name
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.ClassDef) and node.name.endswith(suffix)
    }


def _doc_table_first_column(doc_text: str, header_substring: str) -> list[str]:
    """Return the first-column entries of the markdown table whose header row
    contains *header_substring*. First-column entries have their backticks
    stripped so the returned values are bare identifiers.

    Markdown tables here are:

        | Gate | Passes when… |
        |---|---|
        | `CompletionGate` | The envelope's `TaskStatus` is `COMPLETED`. |
        ...

    The function finds the header line containing *header_substring*,
    skips the separator row, then collects rows until a non-table line.
    """
    lines = doc_text.splitlines()
    header_idx: int | None = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if (
            stripped.startswith("|")
            and stripped.endswith("|")
            and header_substring.lower() in stripped.lower()
        ):
            header_idx = i
            break
    if header_idx is None:
        return []

    # Skip the separator row (---).
    rows_start = header_idx + 2
    out: list[str] = []
    for line in lines[rows_start:]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if not cells:
            break
        first = cells[0].strip("`").strip()
        if first:
            out.append(first)
    return out


def _doc_handler_roster() -> set[str]:
    """Return the handler stems enumerated in architecture.md.

    The handler list lives inline in the ``bonfire.handlers`` row of the
    Module map table, formatted as backticked class stems (no ``Handler``
    suffix in the doc — e.g. ``Bard``, ``MergePreflight``).
    """
    text = _DOC_PATH.read_text(encoding="utf-8")
    # Match the inline backticked list inside the bonfire.handlers row.
    # Pull the row text from the start of "Pipeline-stage handlers" up to
    # the next pipe.
    handlers_row_pattern = re.compile(
        r"Pipeline-stage handlers \(([^)]+)\)",
        re.DOTALL,
    )
    m = handlers_row_pattern.search(text)
    if not m:
        return set()
    inner = m.group(1)
    # Extract every backticked token.
    return set(re.findall(r"`([A-Za-z_][A-Za-z0-9_]*)`", inner))


def _factory_role_strings() -> set[str]:
    """Return every literal string passed to ``StageSpec(role=...)`` (directly
    or via the ``_stage(name, role, ...)`` wrapper) in the workflow factories.

    Walks the AST of every ``.py`` file under ``src/bonfire/workflow/``.
    The two emission shapes:

      * ``_stage("name", "role", ...)`` — the second positional arg is the
        role string (``bonfire.workflow.standard``).
      * ``StageSpec(name=..., role="value", ...)`` — keyword ``role=``
        (``bonfire.workflow.research`` _scout/_sage helpers).

    Skips the ``_stage(name, role, ...)`` helper definition itself (its
    ``role`` is a parameter, not a literal).
    """
    role_strings: set[str] = set()
    for py_file in sorted(_WORKFLOW_PKG.glob("*.py")):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            # _stage("name", "role", ...) — positional shape.
            if isinstance(func, ast.Name) and func.id == "_stage":
                if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                    if isinstance(node.args[1].value, str):
                        role_strings.add(node.args[1].value)
            # StageSpec(..., role="value", ...) — keyword shape.
            elif isinstance(func, ast.Name) and func.id == "StageSpec":
                for kw in node.keywords:
                    if (
                        kw.arg == "role"
                        and isinstance(kw.value, ast.Constant)
                        and isinstance(kw.value.value, str)
                    ):
                        role_strings.add(kw.value.value)
    return role_strings


# ---------------------------------------------------------------------------
# D1 — gate count + roster matches
# ---------------------------------------------------------------------------


def test_gate_count_matches_doc() -> None:
    """The Gate roster in ``engine/gates.py`` must match architecture.md's table.

    Counts every top-level class ending with ``Gate`` in ``engine/gates.py``
    excluding the ``GateChain`` composer (matched by exact name), then
    parses the markdown table whose header begins with ``| Gate |`` in
    architecture.md and asserts the two rosters are identical.

    Probe N+5 Scout 2 D1: doc claimed six; code shipped eight
    (``MergePreflightGate`` and ``SageCorrectionResolvedGate`` were
    missing from the doc).
    """
    code_classes = _classes_in_module(_GATES_SRC, "Gate")
    # Strip the composer — it's not a QualityGate implementation, just
    # the chain runner.
    code_classes.discard("GateChain")

    doc_text = _DOC_PATH.read_text(encoding="utf-8")
    doc_entries = set(_doc_table_first_column(doc_text, "| Gate "))

    missing_from_doc = code_classes - doc_entries
    extra_in_doc = doc_entries - code_classes
    assert not missing_from_doc and not extra_in_doc, (
        "docs/architecture.md gate roster has drifted from "
        "src/bonfire/engine/gates.py:\n"
        f"  Missing from doc (shipped in code, absent from table): "
        f"{sorted(missing_from_doc) or '<none>'}\n"
        f"  Extra in doc (in table, not a Gate class in code): "
        f"{sorted(extra_in_doc) or '<none>'}\n"
        "Reconcile the doc table when adding/removing a gate class."
    )


# ---------------------------------------------------------------------------
# D2 — handler roster matches
# ---------------------------------------------------------------------------


def test_handler_roster_matches_doc() -> None:
    """The Handler roster in ``src/bonfire/handlers/`` must match architecture.md.

    Walks every ``.py`` module under ``src/bonfire/handlers/`` (excluding
    ``__init__.py``) for top-level classes ending in ``Handler``. The
    doc enumerates handler class stems (without the ``Handler`` suffix)
    inline in the ``bonfire.handlers`` row of the Module map table.

    Probe N+5 Scout 2 D2: doc claimed four; code shipped six
    (``MergePreflightHandler`` and ``SageCorrectionBounceHandler`` were
    missing).
    """
    code_classes: set[str] = set()
    for py_file in sorted(_HANDLERS_PKG.glob("*.py")):
        if py_file.name == "__init__.py":
            continue
        code_classes |= _classes_in_module(py_file, "Handler")

    # Doc lists stems without the "Handler" suffix.
    code_stems = {name[: -len("Handler")] for name in code_classes}
    doc_stems = _doc_handler_roster()

    missing_from_doc = code_stems - doc_stems
    extra_in_doc = doc_stems - code_stems
    assert not missing_from_doc and not extra_in_doc, (
        "docs/architecture.md handler roster has drifted from "
        "src/bonfire/handlers/:\n"
        f"  Missing from doc (shipped in code, absent from list): "
        f"{sorted(missing_from_doc) or '<none>'}\n"
        f"  Extra in doc (in list, no matching <Stem>Handler class): "
        f"{sorted(extra_in_doc) or '<none>'}\n"
        "Reconcile the doc's bonfire.handlers row when adding/removing "
        "a handler module."
    )


# ---------------------------------------------------------------------------
# D4 (carry-over) — every factory-emitted role resolves through ROLE_DISPLAY
# ---------------------------------------------------------------------------


def test_role_display_covers_all_factory_roles() -> None:
    """Every ``role=`` string emitted by the workflow factories must resolve
    through ``ROLE_DISPLAY`` — directly, or via ``GAMIFIED_TO_GENERIC`` to a
    canonical ``AgentRole`` value that is itself a ``ROLE_DISPLAY`` key.

    Walks the AST of every module under ``src/bonfire/workflow/`` and
    collects every literal string passed to ``StageSpec(role=...)`` or
    to the ``_stage(name, role, ...)`` helper. Each collected role must
    resolve to a ``ROLE_DISPLAY`` entry through one of two paths:

      1. ``role in ROLE_DISPLAY`` directly.
      2. ``role`` is a key in ``GAMIFIED_TO_GENERIC`` whose mapped
         ``AgentRole.value`` is in ``ROLE_DISPLAY``.

    Probe N+4 Scout 2 F7 / Probe N+5 Scout 2 D4: ``standard_build()``
    emits ``StageSpec(role="prover", ...)`` but ``ROLE_DISPLAY`` had no
    ``"prover"`` entry, leaking the raw wire-format string into any
    consumer that looked up display strings against the factory output.
    """
    role_strings = _factory_role_strings()
    assert role_strings, (
        "AST walk of src/bonfire/workflow/ returned no role strings — "
        "the helper has drifted. Check _factory_role_strings() against "
        "the factory call shapes in bonfire.workflow.{standard,research}."
    )

    canonical_role_values = {r.value for r in AgentRole}

    unresolved: list[str] = []
    for role in sorted(role_strings):
        if role in ROLE_DISPLAY:
            continue
        canonical = GAMIFIED_TO_GENERIC.get(role)
        if canonical is not None and canonical.value in ROLE_DISPLAY:
            continue
        if role in canonical_role_values:
            # Defensive: canonical AgentRole value is always in
            # ROLE_DISPLAY per test_roles.py; this branch keeps the
            # failure message precise if that ever breaks.
            continue
        unresolved.append(role)

    assert not unresolved, (
        "Workflow factories emit role strings that do not resolve through "
        "ROLE_DISPLAY (directly or via GAMIFIED_TO_GENERIC):\n"
        f"  Unresolved: {unresolved}\n"
        "Either add the role to ROLE_DISPLAY (amend ADR-001 § Ratified "
        "Exceptions for any new gamified-keyed entry) or add a "
        "GAMIFIED_TO_GENERIC alias that maps to a canonical AgentRole."
    )


# ---------------------------------------------------------------------------
# Sanity — helpers do not silently return empty rosters
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("gate code classes", _classes_in_module(_GATES_SRC, "Gate") - {"GateChain"}),
        (
            "doc gate table",
            set(_doc_table_first_column(_DOC_PATH.read_text(encoding="utf-8"), "| Gate ")),
        ),
        ("doc handler roster", _doc_handler_roster()),
        ("factory role strings", _factory_role_strings()),
    ],
)
def test_helper_rosters_are_nonempty(name: str, value: set[str]) -> None:
    """Each helper returns a non-empty roster on the shipped tree.

    Guards against a false-negative pass when a parser silently misses
    everything (e.g. table-format change, factory rename) — an empty set
    on both sides of the comparison would pass the equality assertion
    above without surfacing the breakage.
    """
    assert value, f"{name} parser returned an empty set — parser may have drifted"
