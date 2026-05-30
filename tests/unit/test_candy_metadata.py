# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract tests for lane L8 — "Candyfy the Dispatched Categories".

These pin the Sage-locked candy/parlor branding that the Warrior will add to:

  * ``bonfire.agent.role_metadata`` — every role gains ``candy_name``,
    ``candy_icon``, ``parlor_color``, ``parlor_hex``, ``candy_variant``.
  * ``bonfire.cli.commands.install_agents._compose_flat`` — flat-name CLI
    renderer emits candy frontmatter lines.
  * ``bonfire.cli.commands.build_agents._frontmatter`` / ``_compose`` — plugin
    ``agents/*.md`` generator emits the same candy frontmatter lines.
  * ``.claude-plugin/plugin.json`` — agents array byte-stable; description
    grows the cadre candy vocabulary.

The candy never substitutes the role's ``name``/``tools``/``model``; ``parlor_hex``
is metadata only and is NOT rendered into the frontmatter block.
"""

from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

# --- bound from real source -------------------------------------------------
# importlib so the module is loaded fresh against whatever the Warrior ships.
_role_metadata = importlib.import_module("bonfire.agent.role_metadata")
CADRE_ROLES = _role_metadata.CADRE_ROLES
CATCHALL_ROLE = _role_metadata.CATCHALL_ROLE
ALL_PUBLISHABLE_ROLES = _role_metadata.ALL_PUBLISHABLE_ROLES

_install_agents = importlib.import_module("bonfire.cli.commands.install_agents")
_compose_flat = _install_agents._compose_flat

_build_agents = importlib.import_module("bonfire.cli.commands.build_agents")
_build_frontmatter = _build_agents._frontmatter
_build_compose = _build_agents._compose


# Sage-locked per-role candy spec.
# role name -> (candy_name, candy_icon, parlor_color, parlor_hex, candy_variant)
CANDY_SPEC: dict[str, tuple[str, str, str, str, str]] = {
    "scout-innovative": ("LICORICE", "\U0001f441", "var(--brand-a)", "#ff5fa2", "innovative"),
    "scout-conservative": ("LICORICE", "\U0001f441", "var(--brand-a)", "#ff5fa2", "conservative"),
    "knight": ("BRITTLE", "\U0001f6e1", "var(--brand-c)", "#5fb8ff", ""),
    "warrior": ("JAWBREAKER", "⚔", "var(--brand-pop)", "#a96bff", ""),
    "sage": ("TRUFFLE", "\U0001f52e", "var(--brand-pop)", "#a96bff", ""),
    "wizard": ("MARSHMALLOW", "✨", "var(--brand-hot)", "#ff3b6b", ""),
}

CADRE_CANDY_SET = {"LICORICE", "BRITTLE", "JAWBREAKER", "TRUFFLE", "MARSHMALLOW"}

_CANDY_KEYS = ("candy_name", "candy_icon", "parlor_color", "parlor_hex", "candy_variant")


def _role_by_name(name: str) -> dict:
    for role in ALL_PUBLISHABLE_ROLES:
        if role["name"] == name:
            return role
    raise AssertionError(f"role {name!r} not found in ALL_PUBLISHABLE_ROLES")


def _plugin_json_path() -> Path:
    """Locate `.claude-plugin/plugin.json` at the repo root via the source tree."""
    # role_metadata.py lives at <root>/src/bonfire/agent/role_metadata.py
    root = Path(_role_metadata.__file__).resolve().parents[3]
    return root / ".claude-plugin" / "plugin.json"


# --- ROLE_METADATA: candy keys present on every role ------------------------


class TestRoleMetadataCandyKeys:
    @pytest.mark.parametrize("role", ALL_PUBLISHABLE_ROLES, ids=lambda r: r["name"])
    def test_every_role_carries_all_five_candy_keys(self, role: dict) -> None:
        for key in _CANDY_KEYS:
            assert key in role, f"role {role['name']} missing {key}"

    @pytest.mark.parametrize("name", sorted(CANDY_SPEC))
    def test_cadre_role_candy_values_exact(self, name: str) -> None:
        candy_name, candy_icon, parlor_color, parlor_hex, candy_variant = CANDY_SPEC[name]
        role = _role_by_name(name)
        assert role["candy_name"] == candy_name
        assert role["candy_icon"] == candy_icon
        assert role["parlor_color"] == parlor_color
        assert role["parlor_hex"] == parlor_hex
        assert role["candy_variant"] == candy_variant

    def test_catchall_is_gumball_with_empty_variant(self) -> None:
        catchall = _role_by_name("bonfire-powered")
        assert catchall["candy_name"] == "GUMBALL"
        assert catchall["candy_variant"] == ""
        for key in _CANDY_KEYS:
            assert key in catchall, f"catch-all missing {key}"

    def test_gumball_is_not_a_cadre_candy(self) -> None:
        assert "GUMBALL" not in CADRE_CANDY_SET
        cadre_candies = {r["candy_name"] for r in CADRE_ROLES}
        assert "GUMBALL" not in cadre_candies

    def test_two_scouts_share_candy_but_differ_on_variant(self) -> None:
        innov = _role_by_name("scout-innovative")
        cons = _role_by_name("scout-conservative")
        assert innov["candy_name"] == cons["candy_name"] == "LICORICE"
        assert innov["candy_icon"] == cons["candy_icon"]
        assert innov["parlor_color"] == cons["parlor_color"]
        assert innov["parlor_hex"] == cons["parlor_hex"]
        assert innov["candy_variant"] == "innovative"
        assert cons["candy_variant"] == "conservative"
        assert innov["candy_variant"] != cons["candy_variant"]

    def test_cadre_candy_names_match_locked_set(self) -> None:
        cadre_candies = {r["candy_name"] for r in CADRE_ROLES}
        assert cadre_candies == CADRE_CANDY_SET

    def test_no_taffy_or_gumdrop_in_cadre(self) -> None:
        cadre_candies = {r["candy_name"] for r in CADRE_ROLES}
        assert "TAFFY" not in cadre_candies
        assert "GUMDROP" not in cadre_candies

    def test_publishable_role_count_unchanged(self) -> None:
        assert len(ALL_PUBLISHABLE_ROLES) == 7

    def test_sage_and_warrior_intentionally_share_color(self) -> None:
        # Explicitly NOT a uniqueness assertion — locked shared --brand-pop/#a96bff.
        sage = _role_by_name("sage")
        warrior = _role_by_name("warrior")
        assert sage["parlor_color"] == warrior["parlor_color"] == "var(--brand-pop)"
        assert sage["parlor_hex"] == warrior["parlor_hex"] == "#a96bff"


# --- NO-REGRESSION: name/tools/model untouched ------------------------------


class TestNoRegression:
    """Candy is additive: existing identity fields are byte-for-byte unchanged."""

    _BASELINE = {
        "scout-innovative": ("scout-innovative", "Read, Grep, Glob, WebSearch, WebFetch", "sonnet"),
        "scout-conservative": (
            "scout-conservative",
            "Read, Grep, Glob, WebSearch, WebFetch",
            "sonnet",
        ),
        "knight": ("knight", "Read, Grep, Glob, Write, Edit", "sonnet"),
        "warrior": ("warrior", "Read, Grep, Glob, Write, Edit, Bash", "sonnet"),
        "sage": ("sage", "Read, Grep, Glob, Write, Edit", "sonnet"),
        "wizard": ("wizard", "Read, Grep, Glob", "sonnet"),
        "bonfire-powered": (
            "bonfire-powered",
            "Read, Grep, Glob, WebSearch, WebFetch",
            "sonnet",
        ),
    }

    @pytest.mark.parametrize("name", sorted(_BASELINE))
    def test_name_tools_model_unchanged(self, name: str) -> None:
        role = _role_by_name(name)
        exp_name, exp_tools, exp_model = self._BASELINE[name]
        assert role["name"] == exp_name
        assert role["tools"] == exp_tools
        assert role["model"] == exp_model

    @pytest.mark.parametrize("name", sorted(CANDY_SPEC))
    def test_candy_never_substituted_into_name(self, name: str) -> None:
        role = _role_by_name(name)
        assert role["candy_name"] not in role["name"]


# --- RENDERED FRONTMATTER: both renderers emit candy lines ------------------


def _candy_lines(role: dict) -> dict[str, str]:
    """Expected literal frontmatter lines for a role's candy keys.

    candy_icon & parlor_color double-quoted; parlor_hex NOT rendered.
    candy_name rendered bare (matches `name:`/`tools:` bare style).
    """
    return {
        "candy_name": f"candy_name: {role['candy_name']}\n",
        "candy_icon": f'candy_icon: "{role["candy_icon"]}"\n',
        "parlor_color": f'parlor_color: "{role["parlor_color"]}"\n',
        "candy_variant": f'candy_variant: "{role["candy_variant"]}"\n',
    }


class TestRenderedFrontmatterComposeFlat:
    """`_compose_flat` (CLI flat-name surface) emits candy frontmatter."""

    @pytest.mark.parametrize("name", sorted(CANDY_SPEC))
    def test_compose_flat_contains_candy_lines(self, name: str) -> None:
        role = _role_by_name(name)
        rendered = _compose_flat(role)
        for key, line in _candy_lines(role).items():
            assert line in rendered, f"{name}: missing {key} line {line!r}"

    def test_compose_flat_does_not_render_parlor_hex(self) -> None:
        role = _role_by_name("warrior")
        rendered = _compose_flat(role)
        front = rendered.split("\n---\n", 1)[0]
        assert "parlor_hex" not in front

    def test_compose_flat_keeps_flat_role_name(self) -> None:
        role = _role_by_name("knight")
        rendered = _compose_flat(role)
        # flat surface stamps the brand-prefixed name, NOT the candy name.
        assert "name: bonfire-knight\n" in rendered
        assert "\nname: BRITTLE" not in rendered

    def test_compose_flat_still_has_cadre_contract(self) -> None:
        role = _role_by_name("sage")
        rendered = _compose_flat(role)
        assert "cadre_contract:" in rendered


class TestRenderedFrontmatterBuildAgents:
    """`build_agents._frontmatter`/`_compose` (plugin surface) emits candy frontmatter."""

    @pytest.mark.parametrize("name", sorted(CANDY_SPEC))
    def test_build_frontmatter_contains_candy_lines(self, name: str) -> None:
        role = _role_by_name(name)
        rendered = _build_frontmatter(role)
        for key, line in _candy_lines(role).items():
            assert line in rendered, f"{name}: missing {key} line {line!r}"

    def test_build_frontmatter_does_not_render_parlor_hex(self) -> None:
        role = _role_by_name("wizard")
        rendered = _build_frontmatter(role)
        assert "parlor_hex" not in rendered

    def test_build_compose_keeps_role_based_name(self) -> None:
        role = _role_by_name("knight")
        rendered = _build_compose(role)
        # plugin surface uses the bare role name (plugin loader adds bonfire:).
        assert "name: knight\n" in rendered
        assert "\nname: BRITTLE" not in rendered

    def test_build_frontmatter_still_has_cadre_contract(self) -> None:
        role = _role_by_name("warrior")
        rendered = _build_frontmatter(role)
        assert "cadre_contract:" in rendered

    def test_build_frontmatter_icon_and_color_double_quoted(self) -> None:
        role = _role_by_name("scout-innovative")
        rendered = _build_frontmatter(role)
        assert f'candy_icon: "{role["candy_icon"]}"' in rendered
        assert f'parlor_color: "{role["parlor_color"]}"' in rendered

    def test_build_frontmatter_candy_name_bare(self) -> None:
        role = _role_by_name("sage")
        rendered = _build_frontmatter(role)
        # candy_name is unquoted (bare), like name:/tools:
        assert "candy_name: TRUFFLE\n" in rendered
        assert 'candy_name: "TRUFFLE"' not in rendered


# --- Frontmatter parses as valid YAML with candy keys -----------------------


class TestFrontmatterParsesAsYaml:
    def _front_block(self, rendered: str) -> str:
        # rendered begins with "---\n" and the block closes at "\n---\n".
        assert rendered.startswith("---\n")
        body = rendered[len("---\n") :]
        end = body.index("\n---\n")
        return body[:end]

    @pytest.mark.parametrize("name", sorted(CANDY_SPEC))
    def test_compose_flat_front_block_is_valid_yaml(self, name: str) -> None:
        yaml = pytest.importorskip("yaml")
        role = _role_by_name(name)
        block = self._front_block(_compose_flat(role))
        parsed = yaml.safe_load(block)
        assert isinstance(parsed, dict)
        assert parsed["candy_name"] == role["candy_name"]
        assert parsed["candy_icon"] == role["candy_icon"]
        assert parsed["parlor_color"] == role["parlor_color"]
        assert parsed["candy_variant"] == role["candy_variant"]
        assert "parlor_hex" not in parsed

    @pytest.mark.parametrize("name", sorted(CANDY_SPEC))
    def test_build_front_block_is_valid_yaml(self, name: str) -> None:
        yaml = pytest.importorskip("yaml")
        role = _role_by_name(name)
        block = self._front_block(_build_frontmatter(role) + "\n")
        parsed = yaml.safe_load(block)
        assert isinstance(parsed, dict)
        assert parsed["candy_name"] == role["candy_name"]
        assert parsed["candy_variant"] == role["candy_variant"]
        assert "parlor_hex" not in parsed


# --- PLUGIN.JSON: agents array byte-stable; description grows candy vocab ----


class TestPluginJson:
    def _load(self) -> dict:
        return json.loads(_plugin_json_path().read_text(encoding="utf-8"))

    def test_agents_array_unchanged(self) -> None:
        plugin = self._load()
        assert plugin["agents"] == [
            "./agents/scout-innovative.md",
            "./agents/scout-conservative.md",
            "./agents/knight.md",
            "./agents/warrior.md",
            "./agents/sage.md",
            "./agents/wizard.md",
        ]

    def test_identity_fields_unchanged(self) -> None:
        plugin = self._load()
        assert plugin["name"] == "bonfire"
        assert plugin["version"] == "0.1.0"
        assert plugin["license"] == "Apache-2.0"
        assert plugin["author"]["name"] == "BonfireAI"
        assert plugin["author"]["email"] == "antawari@gmail.com"

    def test_description_contains_all_cadre_candy_names(self) -> None:
        plugin = self._load()
        desc = plugin["description"]
        for candy in CADRE_CANDY_SET:
            assert candy in desc, f"description missing candy {candy}"

    def test_description_retains_role_tokens_and_namespace(self) -> None:
        plugin = self._load()
        desc = plugin["description"]
        assert "bonfire:<role>" in desc
        for token in ("scout", "knight", "warrior", "sage", "wizard"):
            assert token in desc, f"description dropped role token {token!r}"
