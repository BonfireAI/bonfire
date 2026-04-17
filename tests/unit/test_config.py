"""RED tests for bonfire.models.config.

Contract derived from the hardened v1 engine. Public v0.1 drops
internal-only fields and cross-module dependencies — see
docs/release-gates.md for the transfer-target discipline.

Notably: v0.1 BonfireSettings has no ``workflow`` field (the v1 engine
owns a ProjectWorkflowConfig that is not part of the public surface).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

# RED-phase import shim: see test_envelope.py for the rationale.
try:
    from bonfire.models.config import (
        AgentConfig,
        BonfireSettings,
        GitConfig,
        PipelineConfig,
        VaultConfig,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    AgentConfig = BonfireSettings = GitConfig = PipelineConfig = VaultConfig = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test with the import error while bonfire.models.config is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.models.config not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# AgentConfig
# ---------------------------------------------------------------------------


class TestAgentConfig:
    def test_default_construction(self):
        a = AgentConfig()
        assert a.prompt == ""
        assert a.role == ""
        assert a.description == ""
        assert a.temperature == 0.7
        assert a.max_tokens == 4096

    def test_custom_values(self):
        a = AgentConfig(
            prompt="you are a knight",
            role="knight",
            description="writes RED tests",
            temperature=0.2,
            max_tokens=8192,
        )
        assert a.prompt == "you are a knight"
        assert a.role == "knight"
        assert a.temperature == 0.2
        assert a.max_tokens == 8192


# ---------------------------------------------------------------------------
# PipelineConfig
# ---------------------------------------------------------------------------


class TestPipelineConfig:
    def test_default_construction(self):
        p = PipelineConfig()
        assert p.tier == "free"
        assert p.model == "claude-sonnet-4-6"
        assert p.max_turns == 10
        assert p.max_budget_usd == 5.0
        assert p.persona == "passelewe"

    def test_custom_values(self):
        p = PipelineConfig(
            tier="pro",
            model="claude-opus-4",
            max_turns=20,
            max_budget_usd=50.0,
            persona="anta",
        )
        assert p.tier == "pro"
        assert p.model == "claude-opus-4"
        assert p.max_turns == 20
        assert p.max_budget_usd == 50.0
        assert p.persona == "anta"

    def test_zero_budget_allowed(self):
        p = PipelineConfig(max_budget_usd=0.0)
        assert p.max_budget_usd == 0.0

    def test_negative_budget_rejected(self):
        with pytest.raises(ValidationError) as exc:
            PipelineConfig(max_budget_usd=-0.01)
        assert "budget" in str(exc.value).lower() or "non-negative" in str(exc.value)

    def test_zero_max_turns_rejected(self):
        with pytest.raises(ValidationError) as exc:
            PipelineConfig(max_turns=0)
        assert "turns" in str(exc.value).lower() or "positive" in str(exc.value)

    def test_negative_max_turns_rejected(self):
        with pytest.raises(ValidationError) as exc:
            PipelineConfig(max_turns=-5)
        assert "turns" in str(exc.value).lower() or "positive" in str(exc.value)


# ---------------------------------------------------------------------------
# VaultConfig
# ---------------------------------------------------------------------------


class TestVaultConfig:
    def test_default_construction(self):
        v = VaultConfig()
        assert v.session_dir == ".bonfire/sessions"
        assert v.context_file == ".bonfire/context.json"

    def test_custom_paths(self):
        v = VaultConfig(session_dir="/var/sessions", context_file="/var/ctx.json")
        assert v.session_dir == "/var/sessions"
        assert v.context_file == "/var/ctx.json"


# ---------------------------------------------------------------------------
# GitConfig
# ---------------------------------------------------------------------------


class TestGitConfig:
    def test_default_construction(self):
        g = GitConfig()
        assert g.auto_branch is True
        assert g.auto_commit_on_green is True
        assert g.require_pr is True

    def test_all_false(self):
        g = GitConfig(auto_branch=False, auto_commit_on_green=False, require_pr=False)
        assert g.auto_branch is False
        assert g.auto_commit_on_green is False
        assert g.require_pr is False


# ---------------------------------------------------------------------------
# BonfireSettings — shape (no `workflow` field per public v0.1 adaptation)
# ---------------------------------------------------------------------------


class TestBonfireSettingsShape:
    def test_top_level_fields_exactly_these(self):
        """Public v0.1 contract: config_version, bonfire, memory, git, agents."""
        expected = {"config_version", "bonfire", "memory", "git", "agents"}
        assert set(BonfireSettings.model_fields.keys()) == expected

    def test_no_workflow_field(self):
        assert "workflow" not in BonfireSettings.model_fields

    def test_default_construction_with_no_file(self, tmp_path, monkeypatch):
        """With no bonfire.toml present, defaults apply."""
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert isinstance(s.bonfire, PipelineConfig)
        assert isinstance(s.memory, VaultConfig)
        assert isinstance(s.git, GitConfig)
        assert s.agents == {}

    def test_config_version_is_integer(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert isinstance(s.config_version, int)
        assert s.config_version >= 1

    def test_default_bonfire_section_is_pipeline_config(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert s.bonfire.tier == "free"
        assert s.bonfire.max_budget_usd == 5.0


# ---------------------------------------------------------------------------
# BonfireSettings — init kwargs priority
# ---------------------------------------------------------------------------


class TestBonfireSettingsInitPriority:
    def test_init_kwargs_override_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings(bonfire=PipelineConfig(tier="pro", max_budget_usd=50.0))
        assert s.bonfire.tier == "pro"
        assert s.bonfire.max_budget_usd == 50.0

    def test_init_kwargs_override_toml(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\ntier = "toml-tier"\nmax_budget_usd = 99.0\n')
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings(bonfire=PipelineConfig(tier="init-tier", max_budget_usd=1.0))
        assert s.bonfire.tier == "init-tier"
        assert s.bonfire.max_budget_usd == 1.0

    def test_init_kwargs_override_env(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BONFIRE_BONFIRE__TIER", "env-tier")
        s = BonfireSettings(bonfire=PipelineConfig(tier="init-tier"))
        assert s.bonfire.tier == "init-tier"


# ---------------------------------------------------------------------------
# BonfireSettings — TOML loading
# ---------------------------------------------------------------------------


class TestBonfireSettingsTomlLoading:
    def test_toml_loaded_from_cwd(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\ntier = "loaded-from-toml"\nmax_budget_usd = 12.5\n')
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert s.bonfire.tier == "loaded-from-toml"
        assert s.bonfire.max_budget_usd == 12.5

    def test_toml_overrides_defaults(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[memory]\nsession_dir = "/custom/sessions"\n')
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert s.memory.session_dir == "/custom/sessions"

    def test_toml_partial_merge_preserves_defaults(self, tmp_path, monkeypatch):
        """TOML only overriding one field; others keep defaults."""
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\ntier = "partial"\n')
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert s.bonfire.tier == "partial"
        # Not set in TOML — falls back to defaults
        assert s.bonfire.max_budget_usd == 5.0
        assert s.bonfire.persona == "passelewe"


# ---------------------------------------------------------------------------
# BonfireSettings — env variable priority
# ---------------------------------------------------------------------------


class TestBonfireSettingsEnvPriority:
    def test_env_overrides_toml(self, tmp_path, monkeypatch):
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\ntier = "toml-tier"\n')
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BONFIRE_BONFIRE__TIER", "env-tier")
        s = BonfireSettings()
        assert s.bonfire.tier == "env-tier"

    def test_env_overrides_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("BONFIRE_BONFIRE__TIER", "from-env")
        s = BonfireSettings()
        assert s.bonfire.tier == "from-env"


# ---------------------------------------------------------------------------
# BonfireSettings — legacy key migration
# ---------------------------------------------------------------------------


class TestLegacyKeyMigration:
    def test_legacy_budget_usd_migrated_to_max_budget_usd(self, tmp_path, monkeypatch):
        """[bonfire] budget_usd should migrate to max_budget_usd."""
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text("[bonfire]\nbudget_usd = 17.5\n")
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert s.bonfire.max_budget_usd == 17.5

    def test_new_key_wins_when_both_present(self, tmp_path, monkeypatch):
        """If both budget_usd and max_budget_usd are present, max_budget_usd wins."""
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text("[bonfire]\nbudget_usd = 99.0\nmax_budget_usd = 7.0\n")
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert s.bonfire.max_budget_usd == 7.0

    def test_migration_direct_kwargs(self, tmp_path, monkeypatch):
        """Init kwargs with legacy nested dict should migrate too."""
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings.model_validate({"bonfire": {"budget_usd": 42.0}})
        assert s.bonfire.max_budget_usd == 42.0


# ---------------------------------------------------------------------------
# BonfireSettings.describe() — diff from defaults
# ---------------------------------------------------------------------------


class TestDescribe:
    def test_describe_returns_dict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        result = s.describe()
        assert isinstance(result, dict)

    def test_describe_empty_when_all_defaults(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        result = s.describe()
        # Each section present with empty dict of diffs
        for section_diff in result.values():
            assert section_diff == {}

    def test_describe_shows_overridden_field(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings(bonfire=PipelineConfig(tier="pro"))
        result = s.describe()
        assert "bonfire" in result
        assert result["bonfire"].get("tier") == "pro"

    def test_describe_omits_unchanged_fields(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings(bonfire=PipelineConfig(tier="pro"))
        result = s.describe()
        # max_budget_usd unchanged from default 5.0; must not appear
        assert "max_budget_usd" not in result.get("bonfire", {})

    def test_describe_does_not_have_workflow_section(self, tmp_path, monkeypatch):
        """Public v0.1: no workflow section in describe() output."""
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        result = s.describe()
        assert "workflow" not in result


# ---------------------------------------------------------------------------
# BonfireSettings — agents dict
# ---------------------------------------------------------------------------


class TestAgentsDict:
    def test_agents_default_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert s.agents == {}

    def test_agents_accepts_custom_entries(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings(
            agents={
                "knight": AgentConfig(role="knight", prompt="write tests"),
                "warrior": AgentConfig(role="warrior", prompt="write code"),
            }
        )
        assert "knight" in s.agents
        assert "warrior" in s.agents
        assert s.agents["knight"].role == "knight"

    def test_agents_from_toml(self, tmp_path, monkeypatch):
        toml_path: Path = tmp_path / "bonfire.toml"
        toml_path.write_text('[agents.knight]\nrole = "knight"\nprompt = "from toml"\n')
        monkeypatch.chdir(tmp_path)
        s = BonfireSettings()
        assert "knight" in s.agents
        assert s.agents["knight"].prompt == "from toml"
