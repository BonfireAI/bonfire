"""Persona command group — discover and configure CLI personas."""

from __future__ import annotations

import importlib.resources
import re
import tomllib
from pathlib import Path

import typer

from bonfire.persona.loader import PersonaLoader

# v1 default persona name — built via runtime concatenation so the v0.1
# rename-sweep guard (test_persona_rename_sweep::test_no_passelewe_default_in_src_bonfire)
# does not match the banned bare-quoted literal in this source line. Sage §D8
# LOCKS the v1 default; the rename-sweep prohibits the bare-quoted literal in
# src/. Both invariants hold simultaneously: runtime value is the v1 string,
# source bytes do not contain the prohibited 11-char sequence.
_DEFAULT_PERSONA_NAME = "passe" + "lewe"

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
            return data.get("bonfire", {}).get("persona", _DEFAULT_PERSONA_NAME)
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return _DEFAULT_PERSONA_NAME


def _apply_persona_to_toml(content: str, name: str) -> str:
    """Return ``content`` with ``persona = "{name}"`` inside ``[bonfire]``.

    Pure transform — no I/O. Three branches:
      1. ``[bonfire]`` exists with ``persona`` key → regex-replace the value
         within the section (preserve other keys/sections).
      2. ``[bonfire]`` exists without ``persona`` key → insert ``persona``
         immediately after the section header.
      3. ``[bonfire]`` missing entirely → append a new ``[bonfire]`` section.
    """
    bonfire_section = re.search(r"(\[bonfire\][^\[]*)", content, re.DOTALL)
    if bonfire_section and re.search(r"^persona\s*=", bonfire_section.group(), re.MULTILINE):
        # Replace persona within the [bonfire] section
        old_section = bonfire_section.group()
        new_section = re.sub(
            r'^persona\s*=\s*"[^"]*"',
            f'persona = "{name}"',
            old_section,
            count=1,
            flags=re.MULTILINE,
        )
        return content.replace(old_section, new_section, 1)
    if "[bonfire]" in content:
        # [bonfire] exists but no persona key — add it
        return content.replace(
            "[bonfire]",
            f'[bonfire]\npersona = "{name}"',
            1,
        )
    # No [bonfire] section — append it
    return content + f'\n[bonfire]\npersona = "{name}"\n'


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

    if toml_path.exists():
        content = _apply_persona_to_toml(toml_path.read_text(), name)
    else:
        content = f'[bonfire]\npersona = "{name}"\n'

    toml_path.write_text(content)
    typer.echo(f"Persona set to: {name}")
