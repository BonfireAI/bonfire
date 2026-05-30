# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Per-role metadata for the cadre subagent-distribution surface.

The canonical role-prompt BODIES live in `src/bonfire/prompts/<role>.md`.
This module carries the per-role FRONTMATTER metadata (description, tools,
model, maxTurns) that the build_agents generator emits alongside each
body when producing Claude Code-shaped subagent files under `agents/`.

Role names align with Claude Code's namespacing rule (lowercase letters
and hyphens). The colon-namespace surface (`bonfire:scout-innovative`,
etc.) is produced by the plugin loader from the bare names below.

The `bonfire-powered` catch-all is INTENTIONALLY not part of the
plugin's `agents/` set — it ships standalone via the `install_agents`
CLI as a flat-named file head-to-head with `general-purpose` in the
picker.
"""

from __future__ import annotations

from typing import TypedDict

__all__ = [
    "RoleMetadata",
    "CADRE_ROLES",
    "CATCHALL_ROLE",
    "ALL_PUBLISHABLE_ROLES",
]


class RoleMetadata(TypedDict):
    """Frontmatter fields shipped with each cadre subagent file.

    `cadre_contract` is stamped from `bonfire.cadre.CADRE_CONTRACT_VERSION`
    by the generator at build time; consumers do not pass it directly.
    """

    name: str
    description: str
    tools: str
    model: str
    candy_name: str
    candy_icon: str
    parlor_color: str
    parlor_hex: str
    candy_variant: str


# Order is the publication order in the plugin manifest's `agents:` list.
CADRE_ROLES: tuple[RoleMetadata, ...] = (
    {
        "name": "scout-innovative",
        "description": (
            "Bonfire cadre · Innovative Scout. Read-only investigator biased "
            "toward bold, unconventional solutions. Use in dual-workflow "
            "alongside scout-conservative for non-trivial design questions."
        ),
        "tools": "Read, Grep, Glob, WebSearch, WebFetch",
        "model": "sonnet",
        "candy_name": "LICORICE",
        "candy_icon": "\U0001f441",
        "parlor_color": "var(--brand-a)",
        "parlor_hex": "#ff5fa2",
        "candy_variant": "innovative",
    },
    {
        "name": "scout-conservative",
        "description": (
            "Bonfire cadre · Conservative Scout. Read-only investigator biased "
            "toward safe, proven, fewer-moving-parts solutions. Use in "
            "dual-workflow alongside scout-innovative for non-trivial design "
            "questions."
        ),
        "tools": "Read, Grep, Glob, WebSearch, WebFetch",
        "model": "sonnet",
        "candy_name": "LICORICE",
        "candy_icon": "\U0001f441",
        "parlor_color": "var(--brand-a)",
        "parlor_hex": "#ff5fa2",
        "candy_variant": "conservative",
    },
    {
        "name": "knight",
        "description": (
            "Bonfire cadre · Knight. Writes RED tests that pin a module's "
            "contract before any implementation exists. Does not write "
            "implementation code; does not run the test suite (the Warrior "
            "drives the RED→GREEN cycle)."
        ),
        "tools": "Read, Grep, Glob, Write, Edit",
        "model": "sonnet",
        "candy_name": "BRITTLE",
        "candy_icon": "\U0001f6e1",
        "parlor_color": "var(--brand-c)",
        "parlor_hex": "#5fb8ff",
        "candy_variant": "",
    },
    {
        "name": "warrior",
        "description": (
            "Bonfire cadre · Warrior. Builds the implementation that turns "
            "the Knight's RED tests GREEN. Iron TDD discipline; never "
            "modifies test files; commits logical units; verifies after "
            "every action."
        ),
        "tools": "Read, Grep, Glob, Write, Edit, Bash",
        "model": "sonnet",
        "candy_name": "JAWBREAKER",
        "candy_icon": "⚔",
        "parlor_color": "var(--brand-pop)",
        "parlor_hex": "#a96bff",
        "candy_variant": "",
    },
    {
        "name": "sage",
        "description": (
            "Bonfire cadre · Sage. Synthesizes across two Scout reports "
            "(Innovative + Conservative) into a single, unified recommendation "
            "the next agent can act on. Names conflicts; picks sides with "
            "rationale; does not introduce new options."
        ),
        "tools": "Read, Grep, Glob, Write, Edit",
        "model": "sonnet",
        "candy_name": "TRUFFLE",
        "candy_icon": "\U0001f52e",
        "parlor_color": "var(--brand-pop)",
        "parlor_hex": "#a96bff",
        "candy_variant": "",
    },
    {
        "name": "wizard",
        "description": (
            "Bonfire cadre · Wizard. Workflow composer and gate-keeper. "
            "Reads the registry, parses user intent, proposes the chain, "
            "composes the first injection, validates input/output "
            "compatibility, gates synthesis verdicts."
        ),
        "tools": "Read, Grep, Glob",
        "model": "sonnet",
        "candy_name": "MARSHMALLOW",
        "candy_icon": "✨",
        "parlor_color": "var(--brand-hot)",
        "parlor_hex": "#ff3b6b",
        "candy_variant": "",
    },
)


CATCHALL_ROLE: RoleMetadata = {
    "name": "bonfire-powered",
    "description": (
        "Bonfire cadre · catch-all. A Bonfire-flavored general-purpose agent "
        "for users who want the cadre's discipline without picking a specific "
        "role. Read-only by default. Use this when the task does not cleanly "
        "match a named role (scout-innovative, scout-conservative, knight, "
        "warrior, sage, wizard)."
    ),
    "tools": "Read, Grep, Glob, WebSearch, WebFetch",
    "model": "sonnet",
    "candy_name": "GUMBALL",
    "candy_icon": "🍬",
    "parlor_color": "var(--ink-soft)",
    "parlor_hex": "#5a4a6a",
    "candy_variant": "",
}


ALL_PUBLISHABLE_ROLES: tuple[RoleMetadata, ...] = CADRE_ROLES + (CATCHALL_ROLE,)
