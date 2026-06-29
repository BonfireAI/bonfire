# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

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
from pathlib import Path
from typing import Any

from bonfire.prompt.identity_block import IdentityBlock
from bonfire.prompt.templates import (
    _JINJA_ENV,
    PromptBlock,
    PromptTemplate,
    _parse_frontmatter,
)
from bonfire.prompt.truncation import (
    effective_budget,
    order_by_position,
    truncate_blocks,
)

__all__ = [
    "PromptBlock",
    "PromptCompiler",
    "PromptTemplate",
    "_parse_frontmatter",
]


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
        2. Bundled default in the ``bonfire/prompt/templates/`` package data
           directory as ``{role}_identity.md``.

        The bundled tier anchors on the ``bonfire.prompt`` package and then
        descends into the ``templates`` data directory. It deliberately does
        NOT anchor on ``bonfire.prompt.templates`` directly: that name is
        shadowed by the sibling ``templates.py`` module, so resolving it would
        point at the package root instead of the data directory.

        Args:
            role: The agent role name (e.g., "researcher", "tester").

        Returns:
            A parsed PromptTemplate, or ``None`` if no identity block exists.
        """
        # Tier 1: project-local
        if self.project_root is not None:
            local_path = Path(self.project_root) / "agents" / role / "identity_block.md"
            if local_path.exists():
                return PromptTemplate.from_file(local_path)

        # Tier 2: bundled defaults (templates/ data dir, anchored on the package)
        try:
            resource = (
                importlib.resources.files("bonfire.prompt") / "templates" / f"{role}_identity.md"
            )
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
        2. Bundled default in the ``bonfire/prompt/templates/`` package data
           directory as ``{role}.md``.

        Like ``load_identity_block``, the bundled tier anchors on the
        ``bonfire.prompt`` package and descends into the ``templates`` data
        directory. It deliberately does NOT anchor on
        ``bonfire.prompt.templates`` directly: that name is shadowed by the
        sibling ``templates.py`` module, so resolving it would point at the
        package root instead of the data directory.

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

        # Tier 2: bundled defaults (templates/ data dir, anchored on the package)
        try:
            resource = importlib.resources.files("bonfire.prompt") / "templates" / f"{role}.md"
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
