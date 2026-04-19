"""Prompt compilation: blocks, templates, and the compile pipeline.

This module provides the core prompt engineering primitives for Bonfire:

- **PromptBlock** — an immutable unit of prompt content with priority metadata
- **PromptTemplate** — a parsed template with YAML frontmatter and Jinja2 body
- **PromptCompiler** — the pipeline that loads, renders, truncates, orders,
  and joins prompt blocks into a final string ready for an LLM

The compile pipeline: blocks → truncate by priority → U-shape reorder → join.
"""

from __future__ import annotations

import importlib.resources
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from jinja2 import BaseLoader, StrictUndefined
from jinja2.sandbox import SandboxedEnvironment

from bonfire.prompt.identity_block import IdentityBlock
from bonfire.prompt.truncation import (
    effective_budget,
    order_by_position,
    truncate_blocks,
)

__all__ = [
    "PromptBlock",
    "PromptCompiler",
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


# ===========================================================================
# PromptCompiler
# ===========================================================================


class PromptCompiler:
    """Loads, renders, truncates, and joins prompt blocks into final text.

    The compiler provides a two-tier template discovery system:
    1. Project-local templates at ``project_root/agents/{role}/prompt.md``
    2. Bundled default templates shipped with the bonfire package

    The compile pipeline:
    1. Apply ``effective_budget`` with the configured safety margin
    2. ``truncate_blocks`` to fit within budget (priority-based dropping)
    3. Optionally ``order_by_position`` for U-shaped attention ordering
    4. Join surviving block contents with double newlines

    Attributes:
        project_root: Optional path to project root for template discovery.
        default_budget: Default token budget when none specified. Defaults to 8000.
        safety_margin: Fraction reserved as safety buffer. Defaults to 0.15.
    """

    def __init__(
        self,
        project_root: Path | None = None,
        default_budget: int = 8000,
        safety_margin: float = 0.15,
    ) -> None:
        self.project_root = project_root
        self.default_budget = default_budget
        self.safety_margin = safety_margin

    def load_identity_block(self, role: str) -> PromptTemplate | None:
        """Load the identity block for the given agent role.

        Two-tier discovery (same as templates):
        1. ``self.project_root / "agents" / role / "identity_block.md"``
        2. Bundled default at ``bonfire.prompt.templates/{role}_identity.md``

        Args:
            role: The agent role name (e.g., "scout", "knight").

        Returns:
            A parsed PromptTemplate, or ``None`` if no identity block exists.
        """
        # Tier 1: project-local
        if self.project_root is not None:
            local_path = Path(self.project_root) / "agents" / role / "identity_block.md"
            if local_path.exists():
                return PromptTemplate.from_file(local_path)

        # Tier 2: bundled defaults
        try:
            resource = importlib.resources.files("bonfire.prompt.templates") / f"{role}_identity.md"
            with importlib.resources.as_file(resource) as bundled_path:
                if bundled_path.exists():
                    return PromptTemplate.from_file(bundled_path)
        except (FileNotFoundError, TypeError, ModuleNotFoundError):
            pass

        return None

    def load_identity_block_validated(self, role: str) -> tuple[PromptTemplate, IdentityBlock]:
        """Load and validate the identity block for the given role.

        Args:
            role: The agent role name (e.g., "scout", "knight").

        Returns:
            Tuple of (PromptTemplate, IdentityBlock).

        Raises:
            ValueError: If no identity block exists or frontmatter validation fails.
        """
        template = self.load_identity_block(role)
        if template is None:
            msg = f"No identity block found for role '{role}'"
            raise ValueError(msg)

        try:
            meta = IdentityBlock.model_validate(template.frontmatter)
        except Exception as exc:
            msg = f"Invalid identity-block frontmatter for role '{role}': {exc}"
            raise ValueError(msg) from exc

        return template, meta

    def get_role_tools(self, role: str) -> list[str]:
        """Load tools declared in a role's identity-block frontmatter.

        Args:
            role: The agent role name (e.g., "scout", "knight").

        Returns:
            List of tool names, or empty list if role/identity block not found.
        """
        try:
            _, meta = self.load_identity_block_validated(role)
            return list(meta.tools)
        except ValueError:
            return []

    def load_template(self, role: str) -> PromptTemplate:
        """Load a prompt template for the given agent role.

        Two-tier discovery:
        1. ``self.project_root / "agents" / role / "prompt.md"``
        2. Bundled default at ``bonfire.prompt.templates/{role}.md``

        Args:
            role: The agent role name (e.g., "scout", "knight").

        Returns:
            A parsed PromptTemplate.

        Raises:
            FileNotFoundError: If no template found in either tier,
                with the role name in the error message.
        """
        # Tier 1: project-local
        if self.project_root is not None:
            local_path = Path(self.project_root) / "agents" / role / "prompt.md"
            if local_path.exists():
                return PromptTemplate.from_file(local_path)

        # Tier 2: bundled defaults
        try:
            resource = importlib.resources.files("bonfire.prompt.templates") / f"{role}.md"
            with importlib.resources.as_file(resource) as bundled_path:
                if bundled_path.exists():
                    return PromptTemplate.from_file(bundled_path)
        except (FileNotFoundError, TypeError, ModuleNotFoundError):
            pass

        msg = (
            f"No prompt template found for role '{role}'. "
            f"Searched project agents/ and bundled defaults."
        )
        raise FileNotFoundError(msg)

    def render_template(
        self,
        template: PromptTemplate,
        variables: dict[str, Any],
    ) -> str:
        """Render a template body with Jinja2 variable substitution.

        Uses a sandboxed Jinja2 environment with StrictUndefined — any
        referenced variable not in ``variables`` will raise an error.

        Args:
            template: The parsed prompt template.
            variables: Variable name → value mapping for substitution.

        Returns:
            The rendered template body as a string.

        Raises:
            jinja2.UndefinedError: If the template references a variable
                not present in ``variables``.
        """
        jinja_template = _JINJA_ENV.from_string(template.body)
        return jinja_template.render(**variables)

    def compose_agent_prompt(
        self,
        role: str,
        variables: dict[str, Any],
        reach_context: dict[str, Any],
        budget: int | None = None,
    ) -> str:
        """Compose a three-layer agent prompt: identity + mission + reach.

        Layers and their priorities:
        - **Identity** (priority 100): cognitive identity, loaded via
          ``load_identity_block``
        - **Mission** (priority 75): task template rendered with variables
        - **Reach** (priority 50): runtime context (tools, gates, etc.)

        Under truncation pressure, reach drops first (lowest priority),
        identity survives longest (highest priority).

        Args:
            role: Agent role name (e.g., "scout", "knight").
            variables: Template variables for the mission layer.
            reach_context: Key-value pairs for the reach layer.
            budget: Optional token budget override.

        Returns:
            The compiled prompt string.
        """
        blocks: list[PromptBlock] = []

        # Layer 1: Identity (priority 100)
        identity = self.load_identity_block(role)
        if identity is not None:
            identity_text = self.render_template(identity, {})
            blocks.append(
                PromptBlock(
                    name=f"{role}_identity",
                    content=identity_text,
                    priority=100,
                )
            )

        # Layer 2: Mission (priority 75)
        template = self.load_template(role)
        mission_text = self.render_template(template, variables)
        blocks.append(
            PromptBlock(
                name=f"{role}_mission",
                content=mission_text,
                priority=75,
            )
        )

        # Layer 3: Reach (priority 50) — skip if empty
        if reach_context:
            reach_text = "\n".join(
                f"{key}: {', '.join(value) if isinstance(value, list) else value}"
                for key, value in reach_context.items()
            )
            blocks.append(
                PromptBlock(
                    name=f"{role}_reach",
                    content=reach_text,
                    priority=50,
                )
            )

        return self.compile(blocks, budget=budget)

    def compose_task_prompt(
        self,
        role: str,
        variables: dict[str, Any],
        reach_context: dict[str, Any],
        budget: int | None = None,
    ) -> str:
        """Compile mission + reach layers without identity.

        For use with SDK system_prompt split: identity is loaded separately
        and passed as ClaudeAgentOptions.system_prompt, while this method
        produces the task prompt passed to query(prompt=...).

        Layers:
        - Mission (priority 75): task template rendered with variables
        - Reach (priority 50): runtime context key-value pairs
        """
        blocks: list[PromptBlock] = []

        template = self.load_template(role)
        mission_text = self.render_template(template, variables)
        blocks.append(PromptBlock(name=f"{role}_mission", content=mission_text, priority=75))

        if reach_context:
            reach_text = "\n".join(
                f"{key}: {', '.join(value) if isinstance(value, list) else value}"
                for key, value in reach_context.items()
            )
            blocks.append(PromptBlock(name=f"{role}_reach", content=reach_text, priority=50))

        return self.compile(blocks, budget=budget)

    def compile(
        self,
        blocks: list[PromptBlock],
        budget: int | None = None,
        positional_order: bool = True,
    ) -> str:
        """Run the full prompt compilation pipeline.

        Pipeline:
        1. Calculate effective budget (with safety margin)
        2. Truncate blocks by priority to fit budget
        3. Optionally reorder using U-shaped attention ordering
        4. Join with double newlines

        Args:
            blocks: The prompt blocks to compile.
            budget: Token budget override. Uses ``default_budget`` if None.
            positional_order: If True, apply U-shape reordering. Defaults to True.

        Returns:
            The compiled prompt string. Empty string if no blocks provided.
        """
        if not blocks:
            return ""

        token_budget = budget if budget is not None else self.default_budget
        usable = effective_budget(token_budget, self.safety_margin)

        surviving = truncate_blocks(blocks, usable)

        if positional_order:
            surviving = order_by_position(surviving)

        return "\n\n".join(block.content for block in surviving)

    def guard_diff(self, diff: str, *, max_lines: int = 5000) -> str:
        """Truncate an oversized diff for Wizard review prompts.

        If *diff* exceeds *max_lines*, the first *max_lines* lines are kept
        and a summary header is prepended describing the truncation.

        Args:
            diff: The raw diff text.
            max_lines: Maximum number of diff lines to keep. Defaults to 5000.

        Returns:
            The original diff if within limits, or the truncated diff with
            a summary header.
        """
        lines = diff.split("\n")
        total = len(lines)
        if total <= max_lines:
            return diff

        kept = lines[:max_lines]
        dropped = total - max_lines
        header = (
            f"[Diff truncated: {total} total lines, "
            f"showing first {max_lines}, {dropped} lines omitted]"
        )
        return header + "\n\n" + "\n".join(kept)
