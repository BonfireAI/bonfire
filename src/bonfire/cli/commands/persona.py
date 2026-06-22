# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Persona command group — discover and configure CLI personas."""

from __future__ import annotations

import importlib.resources
import re
import tomllib
from pathlib import Path

import typer

from bonfire._safe_read import safe_read_capped_text
from bonfire._safe_write import safe_write_text
from bonfire.persona._toml_writer import emit_persona_assignment
from bonfire.persona.loader import PersonaLoader

# Hard byte cap on the bonfire.toml read in ``persona set``. The file
# carries a small TOML config; 1 MiB is comfortably beyond any honest
# payload while bounding the damage from a planted oversized file. The
# symmetric cap appears in ``cli/commands/init.py``.
_PERSONA_READ_MAX_BYTES: int = 1 * 1024 * 1024

# Bonfire ships with Falcor as the companion persona; users can swap
# via `bonfire persona set <name>`.
_DEFAULT_PERSONA = "falcor"

persona_app = typer.Typer(name="persona", help="Discover and configure CLI personas.")


def _get_loader() -> PersonaLoader:
    """Build a PersonaLoader with standard discovery paths."""
    builtin_dir = importlib.resources.files("bonfire") / "persona" / "builtins"
    user_dir = Path.home() / ".bonfire" / "personas"
    return PersonaLoader(builtin_dir=builtin_dir, user_dir=user_dir)


def _get_active_persona() -> str:
    """Read the active persona from bonfire.toml, or return default."""
    toml_path = Path.cwd() / "bonfire.toml"
    if toml_path.exists():
        try:
            with toml_path.open("rb") as f:
                data = tomllib.load(f)
            return data.get("bonfire", {}).get("persona", _DEFAULT_PERSONA)
        except (tomllib.TOMLDecodeError, OSError):
            typer.echo(
                "Warning: bonfire.toml failed to parse; falling back to default persona.",
                err=True,
            )
    return _DEFAULT_PERSONA


@persona_app.command("list")
def persona_list() -> None:
    """List available personas."""
    loader = _get_loader()
    available = loader.available()
    active = _get_active_persona()

    if not available:
        typer.echo("No personas found.")
        raise typer.Exit(0)

    typer.echo("Available personas:")
    for name in available:
        if name == active:
            typer.echo(f"  ▸ {name} (active)")
        else:
            typer.echo(f"    {name}")

    user_dir = Path.home() / ".bonfire" / "personas"
    typer.echo(f"\nInstall custom personas to: {user_dir}")


@persona_app.command("set")
def persona_set(
    name: str = typer.Argument(..., help="Persona name to activate."),
) -> None:
    """Set the active persona in bonfire.toml."""
    loader = _get_loader()
    available = loader.available()

    if name not in available:
        typer.echo(
            f"Error: persona '{name}' not found. "
            f"Run 'bonfire persona list' to see available personas.",
            err=True,
        )
        raise typer.Exit(1)

    toml_path = Path.cwd() / "bonfire.toml"

    persona_line = emit_persona_assignment(name)

    # Refuse symlinks at bonfire.toml — both branches below (read+mutate
    # OR fresh-stub) end with a write_text that would follow a symlink
    # and open the attacker-controlled target in write mode. We refuse
    # at the top so neither branch can leak. ``Path.is_symlink()`` does
    # NOT follow the link (unlike ``exists()``), so a dangling symlink
    # planted to redirect the write is correctly identified here.
    if toml_path.is_symlink():
        typer.echo(
            f"bonfire.toml at {toml_path} is a symlink. Refusing to follow "
            "or overwrite a symlinked config. Remove the symlink and re-run.",
            err=True,
        )
        raise typer.Exit(code=1)

    if toml_path.exists():
        # W11 M3: route through ``safe_read_capped_text`` so the read uses
        # ``O_NOFOLLOW`` defense-in-depth against a race-planted symlink
        # between the ``is_symlink`` pre-check above and this read. The
        # content is partially echoed back through ``re.sub`` into the
        # subsequent ``safe_write_text(..., allow_existing=True)`` — a
        # symlink-followed read here would mix attacker-controlled bytes
        # into the rewritten bonfire.toml.
        try:
            content = safe_read_capped_text(toml_path, max_bytes=_PERSONA_READ_MAX_BYTES)
        except FileExistsError:
            # Race-planted symlink defeated the pre-check. Surface the
            # operator-facing message that matches the pre-check branch.
            typer.echo(
                f"bonfire.toml at {toml_path} is a symlink. Refusing to follow "
                "or overwrite a symlinked config. Remove the symlink and re-run.",
                err=True,
            )
            raise typer.Exit(code=1) from None
        except ValueError as exc:
            # Cap-exceeded. A multi-MiB bonfire.toml is not a legitimate
            # operator shape; refuse to mutate it rather than partial-
            # rewriting a giant file.
            typer.echo(
                f"bonfire.toml at {toml_path} exceeds size cap: {exc}. "
                "Refusing to rewrite; inspect the file and trim it.",
                err=True,
            )
            raise typer.Exit(code=1) from exc
        # Replace persona key ONLY in the [bonfire] section
        bonfire_section = re.search(r"(\[bonfire\][^\[]*)", content, re.DOTALL)
        if bonfire_section and re.search(r"^persona\s*=", bonfire_section.group(), re.MULTILINE):
            # Replace persona within the [bonfire] section. Use a
            # callable replacement so backslashes in the escaped name
            # are NOT interpreted as re backreferences.
            old_section = bonfire_section.group()
            new_section = re.sub(
                r'^persona\s*=\s*"[^"]*"',
                lambda _m: persona_line,
                old_section,
                count=1,
                flags=re.MULTILINE,
            )
            content = content.replace(old_section, new_section, 1)
        elif "[bonfire]" in content:
            # [bonfire] exists but no persona key — add it
            content = content.replace(
                "[bonfire]",
                f"[bonfire]\n{persona_line}",
                1,
            )
        else:
            # No [bonfire] section — append it
            content += f"\n[bonfire]\n{persona_line}\n"
        # ``allow_existing=True`` — we read this file's content one
        # line above and are deliberately rewriting it. The symlink
        # refusal is unconditional inside ``safe_write_text``; only
        # the existing-file refusal is gated by this flag.
        safe_write_text(toml_path, content, allow_existing=True)
    else:
        content = f"[bonfire]\n{persona_line}\n"
        # Fresh write — keep O_EXCL semantics so a regular file racing
        # in between is_symlink() and the open is still refused.
        safe_write_text(toml_path, content)
    typer.echo(f"Persona set to: {name}")
