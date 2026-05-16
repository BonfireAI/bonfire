# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""BonfireSettings — Pydantic Settings with TOML source.

Hierarchy:
    BonfireSettings (root, BaseSettings)
    ├── AgentConfig
    ├── PipelineConfig  (with field validators)
    ├── VaultConfig
    └── GitConfig

Settings are loaded with this priority (highest wins):
    1. init_settings (constructor kwargs)
    2. Environment variables  (BONFIRE_ prefix, __ delimiter)
    3. bonfire.toml in cwd
    4. Field defaults
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, field_validator, model_validator
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource, TomlConfigSettingsSource

# ---------------------------------------------------------------------------
# Sub-models (plain BaseModel, not Settings)
# ---------------------------------------------------------------------------


class AgentConfig(BaseModel):
    """Per-agent configuration block."""

    prompt: str = ""
    role: str = ""
    description: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096


class PipelineConfig(BaseModel):
    """Core pipeline / bonfire settings — validated for safety."""

    tier: str = "free"
    model: str = "claude-sonnet-4-6"
    max_turns: int = 10
    max_budget_usd: float = 5.0
    persona: str = "falcor"
    # Explicit opt-in to ingest the project's ``CLAUDE.md`` /
    # ``.claude/settings.json`` into the dispatched agent's system prompt.
    # File presence alone is NOT enough; this key MUST be ``true``.
    # See ``bonfire.dispatch.sdk_backend._resolve_setting_sources`` for the
    # canonical gate.
    trust_project_settings: bool = False

    @field_validator("max_budget_usd")
    @classmethod
    def _budget_non_negative(cls, v: float) -> float:
        if v < 0:
            msg = f"budget must be non-negative (got {v})"
            raise ValueError(msg)
        return v

    @field_validator("max_turns")
    @classmethod
    def _turns_positive(cls, v: int) -> int:
        if v <= 0:
            msg = f"max_turns must be positive (got {v})"
            raise ValueError(msg)
        return v


class VaultConfig(BaseModel):
    """Memory / session storage paths."""

    session_dir: str = ".bonfire/sessions"
    context_file: str = ".bonfire/context.json"


class GitConfig(BaseModel):
    """Git workflow toggles."""

    auto_branch: bool = True
    auto_commit_on_green: bool = True
    require_pr: bool = True


class ModelsConfig(BaseModel):
    """Per-tier model strings -- BYOK provider model identifiers.

    Maps the three capability tiers (reasoning/fast/balanced) to the
    user's chosen model. Defaults are the Anthropic catalogue; users may
    swap to any provider model string by editing ``[models]`` in
    ``bonfire.toml`` -- Bonfire passes the string verbatim to the
    configured backend.
    """

    reasoning: str = "claude-opus-4-7"
    fast: str = "claude-haiku-4-5"
    balanced: str = "claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Legacy key migration
# ---------------------------------------------------------------------------

_LEGACY_MIGRATIONS: dict[str, dict[str, str]] = {
    "bonfire": {
        "budget_usd": "max_budget_usd",
    },
}


def _migrate_legacy_keys(data: dict[str, Any]) -> dict[str, Any]:
    """Rename legacy keys to their current equivalents.

    Only applies when the new key is NOT already present (new key wins).
    """
    for section, renames in _LEGACY_MIGRATIONS.items():
        if section not in data:
            continue
        sec = data[section]
        if not isinstance(sec, dict):
            continue
        for old_key, new_key in renames.items():
            if old_key in sec and new_key not in sec:
                sec[new_key] = sec.pop(old_key)
            elif old_key in sec and new_key in sec:
                del sec[old_key]
    return data


# ---------------------------------------------------------------------------
# Root settings
# ---------------------------------------------------------------------------

_CURRENT_SCHEMA_VERSION: int = 4

# Build default instances once for describe() comparison
_DEFAULTS = {
    "bonfire": PipelineConfig(),
    "memory": VaultConfig(),
    "git": GitConfig(),
    "models": ModelsConfig(),
}


class BonfireSettings(BaseSettings):
    """Root configuration loaded from bonfire.toml + env + init kwargs.

    Priority (highest to lowest):
        1. init_settings (constructor kwargs)
        2. environment variables
        3. bonfire.toml (TOML file)
        4. field defaults
    """

    model_config: ClassVar[dict[str, Any]] = {  # type: ignore[misc]
        "toml_file": "bonfire.toml",
        "env_prefix": "BONFIRE_",
        "env_nested_delimiter": "__",
    }

    config_version: int = _CURRENT_SCHEMA_VERSION
    bonfire: PipelineConfig = PipelineConfig()
    memory: VaultConfig = VaultConfig()
    git: GitConfig = GitConfig()
    models: ModelsConfig = ModelsConfig()
    agents: dict[str, AgentConfig] = {}

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Wire TOML loading into the settings source chain.

        Priority (first wins): init -> env -> toml.
        """
        return (
            init_settings,
            env_settings,
            TomlConfigSettingsSource(settings_cls),
        )

    @model_validator(mode="before")
    @classmethod
    def _migrate_schema(cls, data: Any) -> Any:
        """Apply legacy key migrations before validation."""
        if isinstance(data, dict):
            return _migrate_legacy_keys(data)
        return data

    def describe(self) -> dict[str, dict[str, Any]]:
        """Return a dict of only non-default values, grouped by section.

        Useful for CLI ``bonfire config show`` and debug logging.
        """
        result: dict[str, dict[str, Any]] = {}
        for section_name, default_model in _DEFAULTS.items():
            current = getattr(self, section_name)
            diff: dict[str, Any] = {}
            for field_name in type(default_model).model_fields:
                current_val = getattr(current, field_name)
                default_val = getattr(default_model, field_name)
                if current_val != default_val:
                    diff[field_name] = current_val
            result[section_name] = diff
        return result
