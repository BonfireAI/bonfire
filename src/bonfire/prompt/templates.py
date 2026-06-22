# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Prompt template primitives: blocks, templates, and frontmatter parsing.

This module provides the leaf-level prompt-engineering primitives for Bonfire,
sitting below the compile pipeline in ``bonfire.prompt.compiler``:

- **PromptBlock** — an immutable unit of prompt content with priority metadata
- **PromptTemplate** — a parsed template with YAML frontmatter and Jinja2 body
- **_parse_frontmatter** — splits YAML frontmatter from the template body

These types carry no dependency on the compiler; the compiler depends on them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import BaseLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

__all__ = [
    "PromptBlock",
    "PromptTemplate",
]

# ---------------------------------------------------------------------------
# Jinja2 environment — sandboxed, strict, no autoescape
# ---------------------------------------------------------------------------

_JINJA_ENV = SandboxedEnvironment(
    loader=BaseLoader(),
    undefined=StrictUndefined,
    keep_trailing_newline=True,
    autoescape=False,
)

# Regex to split YAML frontmatter from body
_FRONTMATTER_RE = re.compile(
    r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z",
    re.DOTALL,
)


# ===========================================================================
# PromptBlock
# ===========================================================================


@dataclass(frozen=True)
class PromptBlock:
    """An immutable unit of prompt content with priority and role metadata.

    Blocks are the atomic building blocks of a compiled prompt. Each block
    has a name (for debugging/logging), content (the actual text), a priority
    (higher = more important, less likely to be truncated), and a role
    (matching the LLM message role: system, user, assistant).

    Attributes:
        name: Human-readable identifier for this block.
        content: The prompt text content.
        priority: Importance weight (higher = kept during truncation).
        role: LLM message role. Defaults to ``"system"``.
    """

    name: str
    content: str
    priority: int
    role: str = "system"


# ===========================================================================
# PromptTemplate
# ===========================================================================


@dataclass
class PromptTemplate:
    """A parsed prompt template with YAML frontmatter and Jinja2 body.

    Templates are loaded from files or strings. The frontmatter (delimited
    by ``---``) contains metadata (max tokens, role hints, etc.), while the
    body contains Jinja2 template syntax for variable interpolation.

    Attributes:
        path: Source file path, or ``None`` if created from a string.
        raw_content: The original unparsed content.
        frontmatter: Parsed YAML frontmatter as a dictionary.
        body: The template body (everything after the frontmatter).
    """

    path: Path | None
    raw_content: str
    frontmatter: dict[str, Any]
    body: str

    @classmethod
    def from_file(cls, path: Path) -> PromptTemplate:
        """Load and parse a prompt template from a file.

        Args:
            path: Path to the template file.

        Returns:
            A parsed PromptTemplate instance.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the YAML frontmatter is malformed.
        """
        path = Path(path)
        if not path.exists():
            msg = f"Template file not found: {path}"
            raise FileNotFoundError(msg)

        raw = path.read_text(encoding="utf-8")
        frontmatter, body = _parse_frontmatter(raw)

        return cls(
            path=path,
            raw_content=raw,
            frontmatter=frontmatter,
            body=body,
        )

    @classmethod
    def from_string(cls, content: str) -> PromptTemplate:
        """Parse a prompt template from a string (no file backing).

        Args:
            content: Raw template content with optional YAML frontmatter.

        Returns:
            A parsed PromptTemplate with ``path=None``.

        Raises:
            ValueError: If the YAML frontmatter is malformed.
        """
        frontmatter, body = _parse_frontmatter(content)

        return cls(
            path=None,
            raw_content=content,
            frontmatter=frontmatter,
            body=body,
        )


def _parse_frontmatter(content: str) -> tuple[dict[str, Any], str]:
    """Split YAML frontmatter from body text.

    Args:
        content: Raw template content.

    Returns:
        Tuple of (frontmatter_dict, body_string).

    Raises:
        ValueError: If YAML parsing fails.
    """
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content

    yaml_text = match.group(1)
    body = match.group(2)

    try:
        parsed = yaml.safe_load(yaml_text)
    except yaml.YAMLError as exc:
        msg = f"Invalid YAML frontmatter: {exc}"
        raise ValueError(msg) from exc

    if not isinstance(parsed, dict):
        parsed = {}

    return parsed, body
