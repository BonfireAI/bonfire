# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Knight contract for the Caronte bracket's tool-policy floor.

The ``DefaultToolPolicy._FLOOR`` map binds gamified role names to the
SDK tool allow-list each role is permitted to invoke. Per W1.5.3 the
floor is the security baseline; per-user TOML overrides (W4.1) are
additive.

This test adds two new entries:

- ``inquisitor`` — judge minimum. Read-only tools (``Read``, ``Grep``,
  ``Glob``) PLUS the Lexicon MCP tools needed to surface verdict
  context and persist muscle-write provenance (search/read on the
  read path; write/supersede on the write path).
- ``loremaster`` — promoter. Same Lexicon read tools as the
  Inquisitor, plus the cross-project supersede surface used for
  muscle->tech promotion.

The Lexicon MCP tool names are pinned in this contract so any future
rename surfaces the drift at this gate. The names mirror the
``bonfire-lexicon`` MCP handler surface
(``memory_search``, ``memory_read``, ``memory_list``,
``memory_write``, ``memory_supersede``, ``memory_write_batch``).

Reference: ``bonfire-public-bon-954-vendor/src/bonfire/dispatch/tool_policy.py``
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Pinned MCP tool names — Lexicon read + write surfaces
# ---------------------------------------------------------------------------

LEXICON_READ_TOOLS: list[str] = [
    "mcp__bonfire_lexicon__memory_search",
    "mcp__bonfire_lexicon__memory_read",
    "mcp__bonfire_lexicon__memory_list",
]

LEXICON_WRITE_TOOLS: list[str] = [
    "mcp__bonfire_lexicon__memory_write",
    "mcp__bonfire_lexicon__memory_supersede",
    "mcp__bonfire_lexicon__memory_write_batch",
]


# ===========================================================================
# 1. Inquisitor — judge minimum
# ===========================================================================


class TestInquisitorFloor:
    def test_inquisitor_in_floor_map(self) -> None:
        """``DefaultToolPolicy._FLOOR`` declares an ``inquisitor`` key.

        The role string ``"inquisitor"`` matches what the Caronte
        post-bracket stage's ``StageSpec.role`` will emit (gamified
        passthrough at executor + pipeline, per the existing
        ``knight``/``warrior`` pattern in the floor map)."""
        from bonfire.dispatch.tool_policy import DefaultToolPolicy

        assert "inquisitor" in DefaultToolPolicy._FLOOR, (
            f"DefaultToolPolicy._FLOOR must declare 'inquisitor'. "
            f"Got keys: {sorted(DefaultToolPolicy._FLOOR.keys())!r}"
        )

    def test_inquisitor_floor_contains_judge_minimum(self) -> None:
        """The judge minimum: ``Read``, ``Grep``, ``Glob`` — read-only
        codebase access for verdict construction."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("inquisitor")
        for required in ("Read", "Grep", "Glob"):
            assert required in tools, f"Inquisitor floor must include `{required}`. Got: {tools!r}"

    def test_inquisitor_floor_contains_lexicon_read_tools(self) -> None:
        """Inquisitor reads the Lexicon to surface prior verdicts /
        muscle context. The full MCP-namespaced names are pinned
        here so a future rename surfaces here too."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("inquisitor")
        for required in LEXICON_READ_TOOLS:
            assert required in tools, (
                f"Inquisitor floor must include Lexicon read tool `{required}`. Got: {tools!r}"
            )

    def test_inquisitor_floor_contains_lexicon_write_tools(self) -> None:
        """Inquisitor writes muscle-pattern entries on CONCERNS / FAIL
        verdicts (search-then-write per the axiom). The write surface
        — ``memory_write``, ``memory_supersede``, ``memory_write_batch``
        — must be in the floor."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("inquisitor")
        for required in LEXICON_WRITE_TOOLS:
            assert required in tools, (
                f"Inquisitor floor must include Lexicon write tool `{required}`. Got: {tools!r}"
            )

    def test_inquisitor_floor_excludes_unrestricted_shell(self) -> None:
        """The judge does NOT need shell access. Excluding ``Bash`` and
        ``Edit`` keeps the floor minimal — anyone widening the
        inquisitor's tool surface must do so via a per-user override,
        not via the security baseline."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("inquisitor")
        for forbidden in ("Bash", "Edit", "Write"):
            assert forbidden not in tools, (
                f"Inquisitor floor must NOT include `{forbidden}`. Got: {tools!r}"
            )


# ===========================================================================
# 2. Loremaster — promoter
# ===========================================================================


class TestLoremasterFloor:
    def test_loremaster_in_floor_map(self) -> None:
        from bonfire.dispatch.tool_policy import DefaultToolPolicy

        assert "loremaster" in DefaultToolPolicy._FLOOR, (
            f"DefaultToolPolicy._FLOOR must declare 'loremaster'. "
            f"Got keys: {sorted(DefaultToolPolicy._FLOOR.keys())!r}"
        )

    def test_loremaster_floor_contains_promoter_minimum(self) -> None:
        """Loremaster reads source code to verify essence-articulability
        of promotion candidates — ``Read``, ``Grep``, ``Glob`` at
        floor."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("loremaster")
        for required in ("Read", "Grep", "Glob"):
            assert required in tools, f"Loremaster floor must include `{required}`. Got: {tools!r}"

    def test_loremaster_floor_contains_lexicon_read_tools(self) -> None:
        """Loremaster's global tech survey + per-project muscle
        enumeration both read the Lexicon."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("loremaster")
        for required in LEXICON_READ_TOOLS:
            assert required in tools, (
                f"Loremaster floor must include Lexicon read tool `{required}`. Got: {tools!r}"
            )

    def test_loremaster_floor_contains_lexicon_supersede_tool(self) -> None:
        """The supersede surface is the canonical promotion verb —
        muscle entry in project X is superseded by a global concept
        entry. ``memory_supersede`` must appear in the floor."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("loremaster")
        assert "mcp__bonfire_lexicon__memory_supersede" in tools, (
            f"Loremaster floor must include `memory_supersede`. Got: {tools!r}"
        )

    def test_loremaster_floor_contains_lexicon_write_tools(self) -> None:
        """Promotion writes the global concept entry (``memory_write``)
        AND batches the supersede+write for atomicity
        (``memory_write_batch`` — preserves BON-981 atomic-commit
        semantics)."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("loremaster")
        for required in LEXICON_WRITE_TOOLS:
            assert required in tools, (
                f"Loremaster floor must include Lexicon write tool `{required}`. Got: {tools!r}"
            )

    def test_loremaster_floor_excludes_unrestricted_shell(self) -> None:
        """Promoter does not need shell or edit access."""
        policy = _instantiate_default_policy()
        tools = policy.tools_for("loremaster")
        for forbidden in ("Bash", "Edit", "Write"):
            assert forbidden not in tools, (
                f"Loremaster floor must NOT include `{forbidden}`. Got: {tools!r}"
            )


# ===========================================================================
# 3. Policy purity — fresh list per call, unmapped role -> empty
# ===========================================================================


class TestPolicyPurity:
    def test_tools_for_returns_fresh_list_each_call(self) -> None:
        """Mutation of one returned list must NOT affect subsequent
        calls — the ToolPolicy Protocol contract."""
        policy = _instantiate_default_policy()
        first = policy.tools_for("inquisitor")
        first.append("BOGUS")
        second = policy.tools_for("inquisitor")
        assert "BOGUS" not in second, (
            "tools_for() must return a fresh list each call so callers "
            "may mutate without polluting subsequent reads."
        )

    def test_unmapped_role_returns_empty_list(self) -> None:
        policy = _instantiate_default_policy()
        assert policy.tools_for("not-a-real-role") == []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _instantiate_default_policy():  # noqa: ANN201
    from bonfire.dispatch.tool_policy import DefaultToolPolicy

    return DefaultToolPolicy()
