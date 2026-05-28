# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""`bonfire install-agents` — drop cadre subagent files at user or project scope.

Sister to `claude mcp add --scope` and `pre-commit install`: an explicit,
idempotent, paired-with-uninstall command. Pip post-install hooks are
deliberately rejected (wheel installs don't execute install-time code;
`pip uninstall` can't clean files outside `site-packages`) — install is
always user-initiated.

The catch-all `bonfire-powered` is installed alongside the namespaced
cadre roles. Plugin users who never run this command get the
colon-namespaced cadre without the catch-all; this command is the only
path that lays down the standalone flat name.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import typer

from bonfire import __version__
from bonfire.agent.role_metadata import ALL_PUBLISHABLE_ROLES, RoleMetadata
from bonfire.cadre import CADRE_CONTRACT_VERSION
from bonfire.cli.commands.build_agents import _read_body

_MANIFEST_NAME = ".installed.json"
_AGENT_PREFIX = "bonfire-"


def _scope_dir(scope: str) -> Path:
    """Resolve the target agents directory for the given scope."""
    if scope == "user":
        return Path.home() / ".claude" / "agents" / "bonfire"
    if scope == "project":
        return Path.cwd() / ".claude" / "agents" / "bonfire"
    raise typer.BadParameter("scope must be 'user' or 'project'")


def _flat_name(role_name: str) -> str:
    """Produce the flat namespaced form of `role_name`.

    Cadre roles (e.g. ``scout-innovative``) gain the ``bonfire-`` prefix
    so the subagent type registers as ``bonfire-scout-innovative``. The
    catch-all is already named ``bonfire-powered``; the prefix is not
    re-applied (otherwise it would double-prefix to
    ``bonfire-bonfire-powered``).
    """
    if role_name.startswith(_AGENT_PREFIX):
        return role_name
    return f"{_AGENT_PREFIX}{role_name}"


def _target_path(target_dir: Path, role_name: str) -> Path:
    """Compose the flat-name file path for `role_name` in `target_dir`."""
    return target_dir / f"{_flat_name(role_name)}.md"


def _compose_flat(role: RoleMetadata) -> str:
    """Compose the CLI-installed subagent file with the flat namespaced `name:`.

    Unlike the plugin path (where Claude Code prepends the plugin name
    to produce `bonfire:<role>`), the raw-files surface has no plugin
    namespace to prepend — so the brand prefix is baked into the
    `name:` field at install time. The body and other frontmatter
    fields are otherwise identical to the plugin's output.
    """
    flat = _flat_name(role["name"])
    frontmatter = (
        "---\n"
        f"name: {flat}\n"
        f"description: {role['description']}\n"
        f"tools: {role['tools']}\n"
        f"model: {role['model']}\n"
        f'cadre_contract: "{CADRE_CONTRACT_VERSION}"\n'
        "---\n"
    )
    return frontmatter + "\n" + _read_body(role["name"])


def _existing_manifest(target_dir: Path) -> dict | None:
    """Return the parsed manifest if present, else None."""
    manifest_path = target_dir / _MANIFEST_NAME
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_manifest(target_dir: Path, installed: list[str]) -> None:
    """Persist the manifest of installed files for the paired uninstall."""
    manifest_path = target_dir / _MANIFEST_NAME
    payload = {
        "bonfire_ai_version": __version__,
        "cadre_contract_version": CADRE_CONTRACT_VERSION,
        "installed_at": datetime.now(UTC).isoformat(),
        "files": sorted(installed),
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def install_agents(
    scope: str = typer.Option(
        "user",
        "--scope",
        "-s",
        help=(
            "Install target: 'user' (~/.claude/agents/bonfire/) "
            "or 'project' (./.claude/agents/bonfire/)."
        ),
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be installed without writing any files.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Overwrite existing files even when their content differs.",
    ),
) -> None:
    """Install Bonfire cadre subagent files at user or project scope."""
    target = _scope_dir(scope)
    typer.echo(f"target: {target}")

    if dry_run:
        typer.echo("dry-run · files that would be installed:")
        for role in ALL_PUBLISHABLE_ROLES:
            typer.echo(f"  {_target_path(target, role['name'])}")
        typer.echo(f"  {target / _MANIFEST_NAME}")
        return

    target.mkdir(parents=True, exist_ok=True)

    installed: list[str] = []
    skipped: list[str] = []
    for role in ALL_PUBLISHABLE_ROLES:
        composed = _compose_flat(role)
        path = _target_path(target, role["name"])
        if path.exists() and not force:
            current = path.read_text(encoding="utf-8")
            if current != composed:
                typer.echo(f"  skipped (differs · pass --force to overwrite): {path}")
                skipped.append(path.name)
                continue
            typer.echo(f"  unchanged: {path}")
            installed.append(path.name)
            continue
        path.write_text(composed, encoding="utf-8")
        installed.append(path.name)
        typer.echo(f"  wrote: {path}")

    _write_manifest(target, installed)
    typer.echo(f"manifest: {target / _MANIFEST_NAME}")
    typer.echo(f"installed: {len(installed)} · skipped: {len(skipped)}")


def uninstall_agents(
    scope: str = typer.Option(
        "user",
        "--scope",
        "-s",
        help="Uninstall target: 'user' or 'project'.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Show what would be removed without deleting any files.",
    ),
) -> None:
    """Remove Bonfire cadre subagent files installed by `install-agents`.

    Reads the manifest at the target scope and removes only the files
    it lists. Unrelated files (including user-authored `~/.claude/agents/`
    contents outside `bonfire/`) are never touched.
    """
    target = _scope_dir(scope)
    typer.echo(f"target: {target}")

    if not target.exists():
        typer.echo("nothing to uninstall: target directory does not exist.")
        return

    manifest = _existing_manifest(target)
    if manifest is None:
        typer.echo(
            f"no manifest found; refusing to delete without one. Inspect {target} manually.",
            err=True,
        )
        raise typer.Exit(1)

    files: list[str] = manifest.get("files", [])
    if dry_run:
        typer.echo("dry-run · files that would be removed:")
        for name in files:
            typer.echo(f"  {target / name}")
        typer.echo(f"  {target / _MANIFEST_NAME}")
        return

    removed = 0
    for name in files:
        path = target / name
        if path.exists():
            path.unlink()
            typer.echo(f"  removed: {path}")
            removed += 1
    manifest_path = target / _MANIFEST_NAME
    if manifest_path.exists():
        manifest_path.unlink()
        typer.echo(f"  removed: {manifest_path}")

    # Remove the empty target directory; ignore if anything else still lives there.
    try:
        target.rmdir()
        typer.echo(f"  removed empty: {target}")
    except OSError:
        typer.echo(f"  kept (not empty): {target}")

    typer.echo(f"uninstalled: {removed} files")


def list_agents(
    scope: str = typer.Option(
        "user",
        "--scope",
        "-s",
        help="Scope to inspect: 'user' or 'project'.",
    ),
) -> None:
    """Report which cadre files are installed at the given scope."""
    target = _scope_dir(scope)
    typer.echo(f"target: {target}")
    if not target.exists():
        typer.echo("not installed.")
        return

    manifest = _existing_manifest(target)
    if manifest is None:
        typer.echo("present but unmanifested. files:")
        for path in sorted(target.iterdir()):
            typer.echo(f"  {path.name}")
        return

    typer.echo(f"bonfire-ai version (at install): {manifest.get('bonfire_ai_version', '?')}")
    typer.echo(
        f"cadre contract version (at install): {manifest.get('cadre_contract_version', '?')}"
    )
    typer.echo(f"installed at: {manifest.get('installed_at', '?')}")
    typer.echo("files:")
    for name in manifest.get("files", []):
        marker = "✓" if (target / name).exists() else "✗"
        typer.echo(f"  {marker} {name}")

    if __version__ != manifest.get("bonfire_ai_version"):
        typer.echo(
            f"\nnote: bonfire-ai is now at {__version__} but the installed "
            f"files were laid down at {manifest.get('bonfire_ai_version')}. "
            "Re-run `bonfire install-agents` to refresh.",
            err=True,
        )
