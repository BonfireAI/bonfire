# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Structural guard — every handler-seam dispatch routes through a
sanctioned dispatch helper that emits ``Dispatch*`` events and stamps cost.

Why this guard exists
---------------------
Pipeline stages reach the agent backend two ways:

* the engine main path, ``dispatch.runner.execute_with_retry``, and
* handler-owned dispatches.

Both must emit ``DispatchStarted`` / ``DispatchCompleted`` /
``DispatchFailed`` and thread the backend's ``cost_usd`` so bus observers
(``CostTracker``, ``CostLedgerConsumer``, ``KnowledgeIngestConsumer``, the
budget watchdog) see every dollar. A handler that calls the backend's
``execute`` directly silently re-opens that parity gap.

The sibling helper test already carries a *substring* grep
(``test_grep_reports_only_allowed_call_sites``) that flags the literal
``backend.execute(`` token outside the runner / helper. That guard is real
but blunt: it is a pure text search, so it does NOT catch a backend that is
aliased to a differently-named local, nor a backend bound to a field whose
name does not contain the substring ``backend``. For example::

    be = self._backend
    await be.execute(envelope, options=opts)   # substring grep BYPASSED

This guard closes that hole structurally. It parses each handler module
with :mod:`ast`, resolves which call receivers are the handler's backend
(the ``self._backend`` attribute and any local aliased to it), and asserts
that EVERY ``.execute(...)`` call on such a receiver routes through a
sanctioned seam instead of being invoked raw inside the handler. The two
sanctioned seams are:

* :func:`bonfire.dispatch.handler_runner.run_handler_dispatch` (the
  single-shot handler helper), and
* :func:`bonfire.dispatch.runner.execute_with_retry` (the engine main-path
  runner, which the reviewer handler uses).

A raw ``backend.execute(...)`` (under any receiver name) inside a handler
is the parity regression and fails this guard.

It also positively asserts the current routing: the synthesizer-correction
handler imports ``run_handler_dispatch`` and the reviewer handler imports
``execute_with_retry`` — so a future port that drops either import (and
hand-rolls a raw call) is caught even if the call form slips past the
receiver heuristic.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

# The package source tree, regardless of where pytest is invoked from.
_SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "bonfire"
_HANDLERS_DIR = _SRC_ROOT / "handlers"

# Helpers that satisfy the seam contract (emit Dispatch* + stamp cost).
# A handler-owned ``.execute`` must go through one of these — never raw.
_SANCTIONED_SEAM_CALLEES = frozenset(
    {
        "run_handler_dispatch",
        "execute_with_retry",
    }
)


def _handler_modules() -> list[Path]:
    """Every importable handler module (skips ``__init__`` and dunders)."""
    assert _HANDLERS_DIR.is_dir(), f"handlers dir not found at {_HANDLERS_DIR}"
    return sorted(p for p in _HANDLERS_DIR.glob("*.py") if not p.name.startswith("_"))


def _backend_receiver_names(tree: ast.Module) -> set[str]:
    """Names that, within *tree*, refer to the handler's agent backend.

    Always includes the canonical receivers ``self._backend`` (matched via
    its attribute name ``_backend``) and the bare ``backend`` parameter
    name. Additionally resolves simple aliases of the form
    ``local = self._backend`` / ``local = backend`` so an aliased call
    ``local.execute(...)`` is still recognised as a backend dispatch.
    """
    aliases: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        value = node.value
        is_backend_value = (isinstance(value, ast.Attribute) and value.attr == "_backend") or (
            isinstance(value, ast.Name) and value.id == "backend"
        )
        if not is_backend_value:
            continue
        for target in node.targets:
            if isinstance(target, ast.Name):
                aliases.add(target.id)
    return aliases


def _execute_calls_on_backend(tree: ast.Module, alias_names: set[str]) -> list[ast.Call]:
    """Every ``<backend>.execute(...)`` call in *tree*.

    A receiver counts as the backend when it is:

    * ``self._backend`` (attribute access whose ``.attr`` is ``_backend``),
    * a bare ``backend`` name, or
    * a local aliased to either of the above (see
      :func:`_backend_receiver_names`).
    """
    calls: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute) or func.attr != "execute":
            continue
        receiver = func.value
        is_backend_receiver = (
            # self._backend.execute(...)
            (isinstance(receiver, ast.Attribute) and receiver.attr == "_backend")
            # backend.execute(...)
            or (isinstance(receiver, ast.Name) and receiver.id == "backend")
            # aliased local: be = self._backend; be.execute(...)
            or (isinstance(receiver, ast.Name) and receiver.id in alias_names)
        )
        if is_backend_receiver:
            calls.append(node)
    return calls


def _sanctioned_seam_call_count(tree: ast.Module) -> int:
    """Count calls to a sanctioned seam helper in *tree*.

    Matches both bare-name (``run_handler_dispatch(...)``) and
    attribute (``mod.execute_with_retry(...)``) call forms.
    """
    count = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id in _SANCTIONED_SEAM_CALLEES:
            count += 1
        elif isinstance(func, ast.Attribute) and func.attr in _SANCTIONED_SEAM_CALLEES:
            count += 1
    return count


def _imports_a_sanctioned_seam(tree: ast.Module) -> bool:
    """Does *tree* import at least one sanctioned seam helper by name?"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name in _SANCTIONED_SEAM_CALLEES:
                    return True
    return False


class TestNoRawBackendExecuteInsideHandlers:
    """Structural (AST) sweep — closes the aliasing hole the substring grep
    in ``test_wave_11_handler_dispatch_helper`` cannot see.
    """

    def test_no_handler_calls_backend_execute_raw(self) -> None:
        offenders: list[str] = []
        for module in _handler_modules():
            tree = ast.parse(module.read_text(), filename=str(module))
            alias_names = _backend_receiver_names(tree)
            raw_calls = _execute_calls_on_backend(tree, alias_names)
            for call in raw_calls:
                offenders.append(f"{module.name}:{call.lineno}")

        assert offenders == [], (
            "Handler-seam parity regression: a handler calls the backend's "
            f"`.execute(...)` raw at {offenders}. Every handler-owned "
            "dispatch must route through a sanctioned seam helper "
            "(`bonfire.dispatch.handler_runner.run_handler_dispatch` or "
            "`bonfire.dispatch.runner.execute_with_retry`) so the "
            "Dispatch* events fire and the backend cost reaches the bus."
        )


class TestBackendBearingHandlersRouteThroughASeam:
    """Positive lock: every handler that owns a backend must import AND call
    a sanctioned seam helper. A port that drops the import and hand-rolls a
    raw dispatch is caught here even if the raw call slips the receiver
    heuristic above.
    """

    def test_each_backend_handler_imports_and_calls_a_seam(self) -> None:
        unrouted: list[str] = []
        for module in _handler_modules():
            text = module.read_text()
            # Only handlers that actually bind a backend are in scope.
            if "self._backend = " not in text:
                continue
            tree = ast.parse(text, filename=str(module))
            if not _imports_a_sanctioned_seam(tree):
                unrouted.append(f"{module.name}: no sanctioned-seam import")
                continue
            if _sanctioned_seam_call_count(tree) < 1:
                unrouted.append(f"{module.name}: imports but never calls a seam")

        assert unrouted == [], (
            "Backend-bearing handler does not route through a sanctioned "
            f"dispatch seam: {unrouted}. Expected `run_handler_dispatch` "
            "(handler helper) or `execute_with_retry` (engine runner)."
        )

    def test_guard_covers_the_known_backend_handlers(self) -> None:
        # Sanity: the sweep must actually see the two backend-bearing
        # handlers. If a refactor renames them and this drops to zero, the
        # positive guard above would vacuously pass — so assert non-empty
        # scope here to keep that guard honest.
        backend_handlers = {
            module.name for module in _handler_modules() if "self._backend = " in module.read_text()
        }
        assert "sage_correction_bounce.py" in backend_handlers
        assert "wizard.py" in backend_handlers


class TestGuardHasTeeth:
    """Meta-test: prove the AST receiver-resolver flags the exact bypass
    forms the substring grep misses, so the guard above is not a paper
    tiger. Synthetic source only — never touches the real tree.
    """

    @pytest.mark.parametrize(
        "snippet",
        [
            # Canonical raw call.
            "async def h(self):\n    await self._backend.execute(env, options=o)\n",
            # Bare-parameter raw call.
            "async def h(backend):\n    await backend.execute(env, options=o)\n",
            # Aliased receiver — the form the substring grep BYPASSES.
            "async def h(self):\n    be = self._backend\n    await be.execute(env, options=o)\n",
        ],
    )
    def test_resolver_flags_raw_backend_execute(self, snippet: str) -> None:
        tree = ast.parse(snippet)
        alias_names = _backend_receiver_names(tree)
        raw_calls = _execute_calls_on_backend(tree, alias_names)
        assert len(raw_calls) == 1, (
            "receiver-resolver failed to flag a raw backend.execute form it must catch"
        )

    def test_resolver_ignores_non_backend_execute(self) -> None:
        # A ``.execute`` on something that is plainly not the backend
        # (e.g. a DB cursor) must NOT be flagged — no false positives.
        snippet = "async def h(self):\n    await self._cursor.execute(sql)\n"
        tree = ast.parse(snippet)
        alias_names = _backend_receiver_names(tree)
        raw_calls = _execute_calls_on_backend(tree, alias_names)
        assert raw_calls == []

    def test_seam_routing_is_not_counted_as_raw(self) -> None:
        # Routing through the helper must NOT be flagged as a raw call.
        snippet = (
            "async def h(self):\n"
            "    return await run_handler_dispatch(\n"
            "        backend=self._backend, envelope=env, options=o\n"
            "    )\n"
        )
        tree = ast.parse(snippet)
        alias_names = _backend_receiver_names(tree)
        raw_calls = _execute_calls_on_backend(tree, alias_names)
        assert raw_calls == []
        assert _sanctioned_seam_call_count(tree) == 1
