# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the bundled default identity-block templates.

The package ships a default cognitive identity block for the core agent
roles so a fresh install gets a sensible identity layer without the user
authoring one. These templates live as markdown-with-frontmatter under
``src/bonfire/prompt/templates/{role}_identity.md`` and are discovered by
``PromptCompiler.load_identity_block`` through its bundled-default (tier 2)
path — i.e. with ``project_root=None``.

Each bundled role name here is the canonical generic ``AgentRole`` value
(``researcher``/``tester``/``implementer``/``reviewer``); the gamified
display names (Scout/Knight/Warrior/Wizard) belong to the persona layer,
never the on-disk filename.
"""

from __future__ import annotations

from typing import Any

import pytest

# Generic role -> gamified display name (for documentation / cross-check only).
BUNDLED_ROLES: dict[str, str] = {
    "researcher": "Scout",
    "tester": "Knight",
    "implementer": "Warrior",
    "reviewer": "Wizard",
}


def _prompt() -> Any:
    import bonfire.prompt as _p

    return _p


# ---------------------------------------------------------------------------
# Bundled identity blocks load through the bundled (tier-2) path.
# ---------------------------------------------------------------------------


class TestBundledIdentityBlocksLoad:
    """Every bundled role resolves a default identity block with no project."""

    @pytest.mark.parametrize("role", sorted(BUNDLED_ROLES))
    def test_bundled_identity_block_loads(self, role: str):
        """``load_identity_block`` finds the bundled template with no project_root."""
        compiler = _prompt().PromptCompiler(project_root=None)
        template = compiler.load_identity_block(role)
        assert template is not None, f"no bundled identity block for role {role!r}"

    @pytest.mark.parametrize("role", sorted(BUNDLED_ROLES))
    def test_bundled_identity_block_has_nonempty_body(self, role: str):
        compiler = _prompt().PromptCompiler(project_root=None)
        template = compiler.load_identity_block(role)
        assert template is not None
        assert template.body.strip(), f"bundled identity body for {role!r} is empty"


class TestBundledIdentityBlocksValidate:
    """Bundled frontmatter validates against the IdentityBlock schema."""

    @pytest.mark.parametrize("role", sorted(BUNDLED_ROLES))
    def test_bundled_identity_block_validates(self, role: str):
        compiler = _prompt().PromptCompiler(project_root=None)
        template, meta = compiler.load_identity_block_validated(role)
        assert isinstance(meta, _prompt().IdentityBlock)
        assert isinstance(template, _prompt().PromptTemplate)

    @pytest.mark.parametrize("role", sorted(BUNDLED_ROLES))
    def test_bundled_role_matches_filename(self, role: str):
        """The ``role`` frontmatter key equals the bundled role name."""
        compiler = _prompt().PromptCompiler(project_root=None)
        _, meta = compiler.load_identity_block_validated(role)
        assert meta.role == role

    @pytest.mark.parametrize("role", sorted(BUNDLED_ROLES))
    def test_bundled_truncation_priority_positive(self, role: str):
        compiler = _prompt().PromptCompiler(project_root=None)
        _, meta = compiler.load_identity_block_validated(role)
        assert meta.truncation_priority > 0

    @pytest.mark.parametrize("role", sorted(BUNDLED_ROLES))
    def test_bundled_output_contract_has_sections(self, role: str):
        compiler = _prompt().PromptCompiler(project_root=None)
        _, meta = compiler.load_identity_block_validated(role)
        assert meta.output_contract.format
        assert len(meta.output_contract.required_sections) >= 1

    def test_get_role_tools_nonempty_for_bundled(self):
        """At least one bundled role declares tools in its identity frontmatter."""
        compiler = _prompt().PromptCompiler(project_root=None)
        all_tools = {role: compiler.get_role_tools(role) for role in BUNDLED_ROLES}
        assert any(tools for tools in all_tools.values()), all_tools


class TestBundledIdentityCognitivePatterns:
    """Each bundled role carries a distinct, role-appropriate cognitive pattern."""

    EXPECTED_PATTERN = {
        "researcher": "observe",
        "tester": "contract",
        "implementer": "execute",
        "reviewer": "audit",
    }

    @pytest.mark.parametrize("role", sorted(BUNDLED_ROLES))
    def test_expected_cognitive_pattern(self, role: str):
        compiler = _prompt().PromptCompiler(project_root=None)
        _, meta = compiler.load_identity_block_validated(role)
        assert meta.cognitive_pattern == self.EXPECTED_PATTERN[role]


class TestProjectOverrideBeatsBundled:
    """A project-local identity block still wins over the bundled default."""

    def test_project_identity_overrides_bundled(self, tmp_path):
        agent_dir = tmp_path / "agents" / "researcher"
        agent_dir.mkdir(parents=True)
        (agent_dir / "identity_block.md").write_text(
            "---\n"
            "role: researcher\n"
            "version: 9.9.9\n"
            "truncation_priority: 100\n"
            "cognitive_pattern: observe\n"
            "tools: []\n"
            "output_contract:\n"
            "  format: markdown\n"
            "  required_sections: [findings]\n"
            "---\n"
            "PROJECT_LOCAL_IDENTITY\n"
        )
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        template = compiler.load_identity_block("researcher")
        assert template is not None
        assert "PROJECT_LOCAL_IDENTITY" in template.body


class TestComposeUsesBundledIdentity:
    """compose_agent_prompt picks up the bundled identity when no project block."""

    def test_compose_includes_bundled_identity(self, tmp_path):
        # Mission template must exist (project-local); identity comes from bundled.
        agent_dir = tmp_path / "agents" / "researcher"
        agent_dir.mkdir(parents=True)
        (agent_dir / "prompt.md").write_text("MISSION: investigate {{ target }}")

        compiler = _prompt().PromptCompiler(project_root=tmp_path, default_budget=10000)
        result = compiler.compose_agent_prompt(
            role="researcher",
            variables={"target": "the data path"},
            reach_context={},
        )
        # Bundled identity body should be present alongside the mission.
        bundled = compiler.load_identity_block("researcher")
        assert bundled is not None
        identity_marker = bundled.body.strip().splitlines()[0]
        assert identity_marker in result
        assert "investigate the data path" in result
