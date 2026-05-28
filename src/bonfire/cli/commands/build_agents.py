# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""`bonfire build-agents` — generate Claude Code-shaped subagent files.

Reads canonical role bodies from `src/bonfire/prompts/<role>.md` and
per-role metadata from `src/bonfire/agent/role_metadata.py`, emits
frontmatter-stamped files into `agents/<role>.md` for the plugin
manifest to reference. The catch-all `bonfire-powered` is emitted into
the same `agents/` directory so the install_agents CLI can find it,
but it is NOT registered in `plugin.json` — the catch-all ships
standalone via the CLI rail, not via the plugin namespace, to provide
a head-to-head brand contrast with `general-purpose` in the picker.

Use `--check` in CI to fail if the generated files drift from the
canonical sources. Use `--force` to overwrite without prompting; the
default is overwrite-with-confirmation when not in `--check` mode.
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import typer

from bonfire.agent.role_metadata import ALL_PUBLISHABLE_ROLES, RoleMetadata
from bonfire.cadre import CADRE_CONTRACT_VERSION


def _frontmatter(role: RoleMetadata) -> str:
    """Render the YAML frontmatter block for one role."""
    return (
        "---\n"
        f"name: {role['name']}\n"
        f"description: {role['description']}\n"
        f"tools: {role['tools']}\n"
        f"model: {role['model']}\n"
        f'cadre_contract: "{CADRE_CONTRACT_VERSION}"\n'
        "---\n"
    )


def _read_body(role_name: str) -> str:
    """Read the canonical prompt body for `role_name`."""
    prompt_path = importlib.resources.files("bonfire") / "prompts" / f"{role_name}.md"
    return prompt_path.read_text(encoding="utf-8")


def _compose(role: RoleMetadata) -> str:
    """Compose the full subagent file (frontmatter + body)."""
    return _frontmatter(role) + "\n" + _read_body(role["name"])


def _default_output_dir() -> Path:
    """Locate the `agents/` directory at the repo root.

    The generator is invoked from the repo root in dev; the output
    directory is `agents/` adjacent to `.claude-plugin/plugin.json`.
    """
    return Path.cwd() / "agents"


def build_agents(
    output_dir: Path = typer.Option(
        None,
        "--output-dir",
        "-o",
        help="Directory to write generated agent files (default: ./agents/).",
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help="Exit non-zero if generated files differ from canonical sources. CI-friendly.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing files without prompting.",
    ),
) -> None:
    """Generate Claude Code-shaped subagent files from canonical prompts + metadata."""
    target = output_dir if output_dir is not None else _default_output_dir()

    if not check:
        target.mkdir(parents=True, exist_ok=True)

    drift: list[tuple[str, str]] = []
    for role in ALL_PUBLISHABLE_ROLES:
        composed = _compose(role)
        path = target / f"{role['name']}.md"

        if check:
            if not path.exists():
                drift.append((role["name"], "missing"))
                continue
            current = path.read_text(encoding="utf-8")
            if current != composed:
                drift.append((role["name"], "drift"))
            continue

        if path.exists() and not force:
            current = path.read_text(encoding="utf-8")
            if current == composed:
                typer.echo(f"  unchanged: {path}")
                continue
            typer.echo(f"  ! existing differs; pass --force to overwrite: {path}")
            continue

        path.write_text(composed, encoding="utf-8")
        typer.echo(f"  wrote: {path}")

    if check:
        if drift:
            typer.echo("build-agents --check FAILED:", err=True)
            for name, kind in drift:
                typer.echo(f"  {kind}: {name}", err=True)
            typer.echo(
                "Run `bonfire build-agents --force` to regenerate.",
                err=True,
            )
            raise typer.Exit(1)
        typer.echo("build-agents --check OK: generated files match canonical sources.")
