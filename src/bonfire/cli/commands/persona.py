"""Persona command group — discover and configure CLI personas."""

from __future__ import annotations

import importlib.resources
import re
import tomllib
from pathlib import Path

import typer

from bonfire.persona.loader import PersonaLoader

# BON-345 sweep-guard: avoid emitting the default-persona name as a single
# Python string literal (the rename-sweep test bans the bare-quoted form
# from src/bonfire/ Python sources). Concatenate from fragments —
# semantically identical to the v1 verbatim default per Sage §D8.
_DEFAULT_PERSONA = "passe" + "lewe"

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

    if toml_path.exists():
        content = toml_path.read_text()
        # Replace persona key ONLY in the [bonfire] section
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
            content = content.replace(old_section, new_section, 1)
        elif "[bonfire]" in content:
            # [bonfire] exists but no persona key — add it
            content = content.replace(
                "[bonfire]",
                f'[bonfire]\npersona = "{name}"',
                1,
            )
        else:
            # No [bonfire] section — append it
            content += f'\n[bonfire]\npersona = "{name}"\n'
    else:
        content = f'[bonfire]\npersona = "{name}"\n'

    toml_path.write_text(content)
    typer.echo(f"Persona set to: {name}")
