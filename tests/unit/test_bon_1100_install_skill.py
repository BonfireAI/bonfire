# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire install-skill`` copies the bundled Claude Code skill.

BON-1100 ships Bonfire as the opinion package for Claude Code: pip-install
drops a Python runtime AND a Claude Code skill at
``~/.claude/skills/bonfire/``. The skill content (``SKILL.md`` and any
companion files) is bundled into the wheel under
``bonfire/skill/`` and discovered via ``importlib.resources``.

The CLI verb ``bonfire install-skill [--target PATH] [--force]`` copies
that bundled content to a user-writable location. Copies are deliberate
(not symlinks): users may edit the installed file, and the install survives
a Bonfire package upgrade. The trade-off is divergence detection — re-running
``install-skill`` when the installed file no longer matches the bundle must
refuse to overwrite without ``--force``, so a user's local edits are never
silently clobbered by a routine ``pip install -U bonfire-ai``.

This module pins the contract:

1. After ``bonfire install-skill --target <tmp_path>``, ``<tmp_path>/SKILL.md`` exists.
2. The installed SKILL.md is byte-for-byte identical to the bundled file.
3. Idempotent re-install: second invocation against the same target exits 0.
4. Refuse-to-overwrite: if the target file diverges from the bundle, exit non-zero.
5. ``--force`` overrides the refuse-to-overwrite check.
6. The bundled SKILL.md frontmatter declares ``name: bonfire`` and a
   non-empty ``description`` field.
7. The bundled SKILL.md body contains the load-bearing strings the v1.0.0
   opinion-package spec requires (the naming greeting, the cadre roles,
   the structural-discipline framing).
"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

from typer.testing import CliRunner

from bonfire.cli.app import app

runner = CliRunner()


def _bundled_skill_md_bytes() -> bytes:
    """Return the bundled ``SKILL.md`` content as raw bytes.

    Source of truth for "what does the wheel ship". The
    ``install-skill`` command MUST end up with byte-identical content
    at the target path; a diff between these bytes and the on-disk
    bytes means the copy step is buggy (or the resource discovery is).
    """
    resource = importlib.resources.files("bonfire.skill") / "SKILL.md"
    return resource.read_bytes()


# ---------------------------------------------------------------------------
# Assertion 1: command creates the SKILL.md at the target.
# ---------------------------------------------------------------------------


def test_install_skill_creates_skill_md(tmp_path: Path) -> None:
    """``bonfire install-skill --target <tmp_path>`` writes ``SKILL.md``.

    The minimum success contract: after a fresh invocation against an
    empty directory, the target carries a ``SKILL.md`` file. Anything
    less is a broken install — the user opens Claude Code and the
    skill is not there.
    """
    target = tmp_path / "skill-target"

    result = runner.invoke(app, ["install-skill", "--target", str(target)])

    assert result.exit_code == 0, (
        f"install-skill must exit 0 on a fresh target; "
        f"got exit_code={result.exit_code}, output={result.output!r}"
    )
    skill_md = target / "SKILL.md"
    assert skill_md.exists(), (
        f"install-skill must create SKILL.md at {skill_md}; "
        f"directory contents: {list(target.iterdir()) if target.exists() else 'target missing'}"
    )


# ---------------------------------------------------------------------------
# Assertion 2: installed content matches bundled content byte-for-byte.
# ---------------------------------------------------------------------------


def test_install_skill_content_matches_bundle(tmp_path: Path) -> None:
    """Installed SKILL.md is byte-for-byte identical to the wheel bundle.

    Any difference means either the wheel is missing the file (the
    importlib.resources read would fail differently) or the copy step
    is mangling encoding. Pin byte equality, not text equality, so a
    BOM or trailing-newline drift would also fire.
    """
    target = tmp_path / "skill-target"
    result = runner.invoke(app, ["install-skill", "--target", str(target)])
    assert result.exit_code == 0, f"install failed: {result.output!r}"

    installed = (target / "SKILL.md").read_bytes()
    bundled = _bundled_skill_md_bytes()
    assert installed == bundled, (
        f"installed SKILL.md ({len(installed)} bytes) must match bundled "
        f"({len(bundled)} bytes) byte-for-byte"
    )


# ---------------------------------------------------------------------------
# Assertion 3: idempotency on identical content.
# ---------------------------------------------------------------------------


def test_install_skill_is_idempotent(tmp_path: Path) -> None:
    """Two consecutive ``install-skill`` calls both exit 0.

    The second invocation finds the target already populated with
    byte-identical content. It must NOT refuse (the file is exactly
    what we'd write) and must NOT raise. Re-installing after a
    ``pip install -U bonfire-ai`` that didn't change the skill MUST
    be a silent no-op.
    """
    target = tmp_path / "skill-target"

    first = runner.invoke(app, ["install-skill", "--target", str(target)])
    assert first.exit_code == 0, f"first install failed: {first.output!r}"

    second = runner.invoke(app, ["install-skill", "--target", str(target)])
    assert second.exit_code == 0, (
        f"second install (idempotent re-run) must exit 0 on byte-identical "
        f"existing content; got exit_code={second.exit_code}, "
        f"output={second.output!r}"
    )


# ---------------------------------------------------------------------------
# Assertion 4: refuse to overwrite divergent content.
# ---------------------------------------------------------------------------


def test_install_skill_refuses_to_overwrite_divergent(tmp_path: Path) -> None:
    """If target SKILL.md diverges from bundle, exit non-zero without overwriting.

    Simulates the common shape: user edited their installed skill,
    then ran ``bonfire install-skill`` again (perhaps after a package
    upgrade). The user's edits MUST be preserved; the command MUST
    refuse with an actionable message naming ``--force`` as the
    override.
    """
    target = tmp_path / "skill-target"
    target.mkdir()
    user_content = "---\nname: bonfire\n---\n# User-edited\n"
    (target / "SKILL.md").write_text(user_content)

    result = runner.invoke(app, ["install-skill", "--target", str(target)])

    assert result.exit_code != 0, (
        f"install-skill must exit non-zero when target diverges; "
        f"got exit_code={result.exit_code}, output={result.output!r}"
    )
    # User content MUST be preserved untouched.
    on_disk = (target / "SKILL.md").read_text()
    assert on_disk == user_content, (
        f"divergent SKILL.md must NOT be overwritten; "
        f"on-disk content changed from {user_content!r} to {on_disk!r}"
    )
    # The message must mention --force so the user knows the escape hatch.
    assert "--force" in result.output, (
        f"refuse-to-overwrite message must name --force; got output={result.output!r}"
    )


# ---------------------------------------------------------------------------
# Assertion 5: --force override succeeds where the bare command refused.
# ---------------------------------------------------------------------------


def test_install_skill_force_overwrites_divergent(tmp_path: Path) -> None:
    """``--force`` overrides the refuse-to-overwrite gate.

    After the bare command refuses on divergent content, the same
    invocation with ``--force`` must succeed AND replace the target
    with the bundled content (so the user explicitly opting in gets a
    clean install).
    """
    target = tmp_path / "skill-target"
    target.mkdir()
    user_content = "---\nname: bonfire\n---\n# User-edited\n"
    (target / "SKILL.md").write_text(user_content)

    # Bare invocation must refuse (sanity guard — paired with assertion 4).
    refusal = runner.invoke(app, ["install-skill", "--target", str(target)])
    assert refusal.exit_code != 0

    # --force succeeds and overwrites.
    result = runner.invoke(app, ["install-skill", "--target", str(target), "--force"])
    assert result.exit_code == 0, (
        f"--force must succeed on divergent target; "
        f"got exit_code={result.exit_code}, output={result.output!r}"
    )
    installed = (target / "SKILL.md").read_bytes()
    assert installed == _bundled_skill_md_bytes(), (
        "--force must replace divergent content with the bundle; on-disk bytes do not match bundle"
    )


# ---------------------------------------------------------------------------
# Assertion 6: bundled SKILL.md frontmatter declares the expected fields.
# ---------------------------------------------------------------------------


def test_bundled_skill_md_frontmatter(tmp_path: Path) -> None:
    """The bundled ``SKILL.md`` declares ``name: bonfire`` and a description.

    The Claude Code skill loader keys on the frontmatter ``name`` and
    matches the user's invocation against the ``description``. Both
    fields MUST be present. ``name`` MUST be the literal ``bonfire``
    (that is the slash-command the user types). ``description`` MUST
    be non-empty.
    """
    body = _bundled_skill_md_bytes().decode("utf-8")
    lines = body.splitlines()

    # Frontmatter is a YAML block between two ``---`` fences at the
    # top of the file. Parse it directly without pulling a YAML
    # dependency — the format is fixed-shape (key: value per line).
    assert lines[0] == "---", f"SKILL.md must open with '---' fence; got {lines[0]!r}"
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i] == "---":
            end_idx = i
            break
    assert end_idx is not None, "SKILL.md frontmatter must close with '---' fence"

    fm: dict[str, str] = {}
    for raw in lines[1:end_idx]:
        if ":" not in raw:
            continue
        key, _, value = raw.partition(":")
        fm[key.strip()] = value.strip()

    assert fm.get("name") == "bonfire", (
        f"SKILL.md frontmatter must declare name: bonfire; got name={fm.get('name')!r}"
    )
    description = fm.get("description", "")
    assert description, (
        f"SKILL.md frontmatter must declare a non-empty description; got {description!r}"
    )


# ---------------------------------------------------------------------------
# Assertion 7: bundled body carries the load-bearing strings.
# ---------------------------------------------------------------------------


def test_bundled_skill_md_body_load_bearing_strings(tmp_path: Path) -> None:
    """The bundled body contains the v1.0.0 spec's load-bearing strings.

    These are the substrings whose presence we can grep for in any
    future audit of "is this still the opinion-package skill":

    - The naming greeting: the literal question Bonfire asks itself.
    - The nine generic role names: each appears at least once.
    - The structural-discipline framing: the word "structural" appears
      describing the role-boundary contract.

    If any of these go missing, the skill has drifted off-spec and
    should re-pass the BON-1100 author lens before shipping.
    """
    body = _bundled_skill_md_bytes().decode("utf-8")

    # Naming greeting — the first conversation's opening line.
    assert "what do you want to call me?" in body, (
        "SKILL.md body must contain the naming greeting 'what do you want to call me?'"
    )

    # The nine generic role names (per ADR-001 cadre).
    for role in (
        "researcher",
        "tester",
        "implementer",
        "verifier",
        "publisher",
        "reviewer",
        "closer",
        "synthesizer",
        "analyst",
    ):
        assert role in body, f"SKILL.md body must name the {role!r} cadre role"

    # Structural-discipline framing — "structural" (not "advisory") is
    # the load-bearing word for "the role boundary is enforced by the
    # protocol, not by good intentions".
    assert "structural" in body.lower(), (
        "SKILL.md body must frame discipline as 'structural' (not 'advisory')"
    )
