# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: the committed cadre plugin definitions stay in lockstep with canon.

Bonfire ships as a Claude Code plugin: a static ``.claude-plugin/plugin.json``
manifest plus a set of frontmatter-stamped subagent files under ``agents/``.
Those agent files are NOT hand-authored — they are *generated* from the
canonical role bodies in ``src/bonfire/prompts/<role>.md`` and the per-role
metadata in ``src/bonfire/agent/role_metadata.py`` via ``bonfire build-agents``.

The risk this module guards against: someone edits a canonical prompt or a
role's metadata but forgets to regenerate, so the committed ``agents/*.md``
silently diverge from their sources. A plugin consumer would then load stale
subagent descriptions that no longer match the runtime contract.

The guard is the generator's own ``--check`` mode, pointed at the committed
``agents/`` directory. If the committed files no longer match what the
generator would emit from canon, ``--check`` exits non-zero and this test
fails — the fix is ``bonfire build-agents --force``.

This module pins:

1. ``bonfire build-agents --check`` against the committed ``agents/`` exits 0
   (committed files match canonical prompts + metadata).
2. ``.claude-plugin/plugin.json`` is valid JSON naming the ``bonfire`` plugin.
3. Every agent path the manifest references resolves to a file that exists.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app

runner = CliRunner()

_REPO_ROOT = Path(__file__).resolve().parents[2]
_AGENTS_DIR = _REPO_ROOT / "agents"
_MANIFEST_PATH = _REPO_ROOT / ".claude-plugin" / "plugin.json"


# ---------------------------------------------------------------------------
# Assertion 1: committed agent files match canonical sources.
# ---------------------------------------------------------------------------


def test_committed_agents_match_canonical_sources() -> None:
    """``build-agents --check`` against the committed ``agents/`` exits 0.

    The committed subagent files must be exactly what the generator emits
    from the canonical prompts and role metadata. A non-zero exit means a
    prompt or metadata edit landed without a regenerate — run
    ``bonfire build-agents --force`` to bring them back in lockstep.
    """
    if not _AGENTS_DIR.exists():
        pytest.skip(f"{_AGENTS_DIR} does not exist — no committed agents to check.")

    result = runner.invoke(app, ["build-agents", "--check", "--output-dir", str(_AGENTS_DIR)])

    assert result.exit_code == 0, (
        "committed agents/*.md have drifted from canonical prompts + "
        "role metadata; run `bonfire build-agents --force` to regenerate. "
        f"check output: {result.output!r}"
    )


# ---------------------------------------------------------------------------
# Assertion 2: the plugin manifest is valid and names the bonfire plugin.
# ---------------------------------------------------------------------------


def test_plugin_manifest_is_valid_bonfire_plugin() -> None:
    """``.claude-plugin/plugin.json`` parses and declares the bonfire plugin."""
    if not _MANIFEST_PATH.exists():
        pytest.skip(f"{_MANIFEST_PATH} does not exist — no manifest to check.")

    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

    assert manifest.get("name") == "bonfire", (
        f"plugin manifest must declare name 'bonfire'; got {manifest.get('name')!r}"
    )
    assert isinstance(manifest.get("agents"), list) and manifest["agents"], (
        f"plugin manifest must declare a non-empty list of agents; got {manifest.get('agents')!r}"
    )


# ---------------------------------------------------------------------------
# Assertion 3: every referenced agent file exists.
# ---------------------------------------------------------------------------


def test_plugin_manifest_agent_paths_resolve() -> None:
    """Every agent path in the manifest points at a file that exists.

    A dangling reference would make the plugin fail to load the named
    subagent. The manifest paths are repo-root-relative (``./agents/...``).
    """
    if not _MANIFEST_PATH.exists():
        pytest.skip(f"{_MANIFEST_PATH} does not exist — no manifest to check.")

    manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))

    missing: list[str] = []
    for rel in manifest.get("agents", []):
        agent_path = (_REPO_ROOT / rel).resolve()
        if not agent_path.is_file():
            missing.append(rel)

    assert not missing, f"plugin manifest references agent files that do not exist: {missing!r}"
