# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Cadre subagent contract surface.

This module is the single read-side dependency on cadre prompt source.
The dispatch path resolves a role's prompt via `resolve_role_prompt(role)`;
the adapter reads the contract stamp from the subagent file; on
mismatch with `CADRE_CONTRACT_VERSION` the dispatch refuses with a
structured `cadre-contract-mismatch` envelope.

The v1 scaffold ships:
- `CADRE_CONTRACT_VERSION` constant (locked at the dispatch boundary)
- `resolve_role_prompt(role)` adapter SKELETON (returns prompt body for
  the canonical Bonfire cadre roles)

The dispatch-path WIRING (refusal-on-mismatch behavior; structured
error envelope) is deliberately deferred to a follow-up — the scaffold
pins the contract; the follow-up enforces it.
"""

from __future__ import annotations

import importlib.resources
from collections.abc import Iterable

__all__ = [
    "CADRE_CONTRACT_VERSION",
    "PUBLISHABLE_ROLE_NAMES",
    "resolve_role_prompt",
    "UnknownCadreRoleError",
]


# Inaugural ship stamp. Advances ONLY on dispatch-boundary breaking
# changes (envelope shape, tool list, role rename). Library bumps that
# touch prompt text but preserve the contract DO NOT advance this
# number; the plugin `version` field in `plugin.json` is the right pin
# for prompt-text-only changes.
CADRE_CONTRACT_VERSION = "0.1.0"


# Canonical bare names. The plugin loader registers these as
# `bonfire:<name>`; the install_agents CLI lays them down as
# `bonfire-<name>.md` flat files at user scope.
PUBLISHABLE_ROLE_NAMES: tuple[str, ...] = (
    "scout-innovative",
    "scout-conservative",
    "knight",
    "warrior",
    "sage",
    "wizard",
    "bonfire-powered",
)


class UnknownCadreRoleError(ValueError):
    """Raised when a caller asks for a role outside the publishable set."""


def resolve_role_prompt(role: str) -> str:
    """Return the canonical prompt body for `role`.

    Reads from `bonfire/prompts/<role>.md` via `importlib.resources`,
    so the lookup works against the installed wheel without leaking
    the file-system layout into callers.

    Raises `UnknownCadreRoleError` for any role not in
    `PUBLISHABLE_ROLE_NAMES`. The dispatch-side refusal-on-contract-
    mismatch behavior is deferred to a follow-up; v1 callers receive
    the prompt body if the role is known and a typed error otherwise.
    """
    if role not in PUBLISHABLE_ROLE_NAMES:
        raise UnknownCadreRoleError(
            f"Unknown cadre role: {role!r}. Publishable roles: {', '.join(PUBLISHABLE_ROLE_NAMES)}"
        )
    prompt_path = importlib.resources.files("bonfire") / "prompts" / f"{role}.md"
    return prompt_path.read_text(encoding="utf-8")


def iter_publishable_roles() -> Iterable[str]:
    """Yield every publishable role name in publication order."""
    return iter(PUBLISHABLE_ROLE_NAMES)
