# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Minimal TOML basic-string escape for persona-name emission.

The persona CLI writes a user-supplied (or directory-name-supplied)
persona name into ``bonfire.toml`` as the value of
``[bonfire].persona``. Without escaping, a name containing ``"``,
``\\n``, or a ``[malicious]`` substring corrupts the TOML or smuggles
in attacker-chosen tables. This module provides the basic-string
escape that the three write sites route through.

The escape follows the TOML 1.0 spec for basic strings (between
``"..."``): backslash, double-quote, and the named control escapes
(``\\b`` ``\\t`` ``\\n`` ``\\f`` ``\\r``). Other control characters
(``U+0000``..``U+001F`` and ``U+007F``) are emitted as ``\\uXXXX``.
"""

from __future__ import annotations

__all__ = ["escape_basic_string", "emit_persona_assignment"]


def escape_basic_string(value: str) -> str:
    """Escape *value* for safe inclusion inside a TOML basic string.

    The result is suitable to splice directly between ``"`` markers in
    a TOML document. Round-tripping through ``tomllib.loads`` yields
    the original *value* verbatim.
    """
    out: list[str] = []
    for ch in value:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\f":
            out.append("\\f")
        elif ch == "\r":
            out.append("\\r")
        elif 0x00 <= ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return "".join(out)


def emit_persona_assignment(name: str) -> str:
    """Return a ``persona = "<escaped>"`` assignment line (no trailing newline)."""
    return f'persona = "{escape_basic_string(name)}"'
