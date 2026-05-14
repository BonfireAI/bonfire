# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Trust-boundary primitives shared across Caronte handlers.

The Inquisitor + Loremaster handlers wrap upstream-cadre and agent payload
text in ``<untrusted_payload from="...">...</untrusted_payload>`` sentinels
so the axiom-trained agent reads the body as DATA, not instructions. The
sentinel boundary is structural: an attacker who can plant
``</untrusted_payload>`` inside a payload body closes the sentinel
mid-block, landing subsequent directive text at cadre authority.

The neutralization strategy mirrors the private tree's
``forge/core/handlers/trust_boundary._neutralize_sentinel_tags`` (Probe 5
A-S-001 + A-S-003 + B-R-003): insert a zero-width joiner between every
adjacent character of each sentinel-tag literal so the literal substring no
longer appears verbatim in the rendered output, while the visual identity
is preserved.

This module ports a focused subset: the literal-replacement strategy in
strict mode. The full balanced-pair walk lives in the private tree; the
public handlers do not need it (the body content they wrap is the
agent-controlled payload, never balanced cadre-emitted sentinels).
"""

from __future__ import annotations

__all__ = [
    "FENCE_NEUTRALIZED",
    "neutralize_sentinel_tags",
    "wrap_untrusted_payload",
]


# Triple-backtick fence-marker neutralization. Three consecutive backticks
# inside an attacker-controlled payload body would otherwise terminate any
# markdown fence the cadre opens around the payload. The neutralized form
# splits the literal sequence with U+200D zero-width joiners.
FENCE_MARKER = "```"
FENCE_NEUTRALIZED = "`‍`‍`"


def _zwj_split(literal: str) -> str:
    """Insert U+200D (ZWJ) between every adjacent character of ``literal``.

    Visual identity is preserved (the ZWJ is non-printing) but the literal
    substring no longer appears verbatim in the rendered output.
    """
    return "‍".join(literal)


# Sentinel literals + their neutralized forms.
_SENTINEL_CLOSE_MARKER = "</untrusted_payload>"
_SENTINEL_CLOSE_NEUTRALIZED = _zwj_split(_SENTINEL_CLOSE_MARKER)
_SENTINEL_OPEN_PREFIX = "<untrusted_payload"
_SENTINEL_OPEN_PREFIX_NEUTRALIZED = _zwj_split(_SENTINEL_OPEN_PREFIX)
_INSTRUCTION_CLOSE_MARKER = "</instruction>"
_INSTRUCTION_CLOSE_NEUTRALIZED = _zwj_split(_INSTRUCTION_CLOSE_MARKER)
_INSTRUCTION_OPEN_PREFIX = "<instruction"
_INSTRUCTION_OPEN_PREFIX_NEUTRALIZED = _zwj_split(_INSTRUCTION_OPEN_PREFIX)


def neutralize_sentinel_tags(text: str) -> str:
    """Strictly neutralize sentinel-tag literals in ``text``.

    Replaces, in order:

    - Triple-backtick fence markers.
    - ``</instruction>`` and ``<instruction`` literals.
    - ``</untrusted_payload>`` and ``<untrusted_payload`` literals.

    Idempotent: applying twice yields the same output (the neutralized
    forms do not contain the original substring).
    """
    out = text.replace(FENCE_MARKER, FENCE_NEUTRALIZED)
    out = out.replace(_INSTRUCTION_CLOSE_MARKER, _INSTRUCTION_CLOSE_NEUTRALIZED)
    out = out.replace(_INSTRUCTION_OPEN_PREFIX, _INSTRUCTION_OPEN_PREFIX_NEUTRALIZED)
    out = out.replace(_SENTINEL_CLOSE_MARKER, _SENTINEL_CLOSE_NEUTRALIZED)
    out = out.replace(_SENTINEL_OPEN_PREFIX, _SENTINEL_OPEN_PREFIX_NEUTRALIZED)
    return out


def _escape_attribute(value: object) -> str:
    """Minimal XML-attribute escape for the sentinel open tag's ``from=``.

    Quotes, ``<``, ``>``, and ``&`` are escaped so a crafted ``from_agent``
    value cannot break out of the attribute and plant a synthetic structural
    sentinel mid-injection.
    """
    text = str(value)
    return (
        text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
    )


def wrap_untrusted_payload(content: str, *, from_agent: str) -> str:
    """Wrap attacker-controlled payload content in a sentinel block.

    The body is neutralized via :func:`neutralize_sentinel_tags` so any
    sentinel-tag literal inside the body cannot terminate the sentinel
    mid-block. The ``from_agent`` is attribute-escaped so a crafted value
    cannot break out of the open tag's ``from="..."`` attribute.
    """
    safe_from = _escape_attribute(from_agent)
    body = neutralize_sentinel_tags(content)
    return f'<untrusted_payload from="{safe_from}">\n{body}\n</untrusted_payload>'
