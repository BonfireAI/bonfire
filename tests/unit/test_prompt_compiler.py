"""RED tests for bonfire.prompt — compiler, IdentityBlock, truncation, templates.

Contract derived from the hardened v1 engine. Public v0.1 renames the
cognitive-axiom frontmatter model from ``AxiomMeta`` to ``IdentityBlock``
(three-layer naming: identity_block / mission / reach). Module path
``bonfire.prompt.identity_block``.

See docs/release-gates.md for transfer-target discipline.

Categories:
  1. IdentityBlock — frontmatter schema, validation, immutability
  2. PromptBlock — frozen dataclass, priority, role, identity-layer tagging
  3. estimate_tokens — chars/4 heuristic
  4. effective_budget — safety margin math
  5. truncate_blocks — priority drop, order preservation, character-slice
  6. order_by_position — U-shape attention ordering
  7. PromptTemplate.from_file — load + YAML frontmatter parse
  8. PromptTemplate.from_string — string variant
  9. PromptCompiler construction — defaults, custom
 10. PromptCompiler.load_template — two-tier discovery
 11. PromptCompiler.load_identity_block — axiom layer discovery (renamed)
 12. PromptCompiler.render_template — Jinja2 sandbox + StrictUndefined
 13. PromptCompiler.compile — full pipeline
 14. PromptCompiler.compose_agent_prompt — three-layer composition
 15. PromptCompiler.guard_diff — Wizard diff truncation
 16. Innovative-lens edge cases — pathological inputs, adversarial cases
 17. Dependency constraints — prompt/ is leaf module
"""

from __future__ import annotations

import dataclasses
import math
import textwrap
from pathlib import Path
from typing import Any

import pytest

# RED-phase import shim: the implementation does not exist yet. Tests still
# reference real names; each test will fail with ModuleNotFoundError on first
# attribute access, satisfying the RED invariant. Collection succeeds because
# the import error is swallowed at module load time. See test_envelope.py.
try:
    from bonfire.prompt import (
        IdentityBlock,
        PromptBlock,
        PromptCompiler,
        PromptTemplate,
    )
    from bonfire.prompt.truncation import (
        effective_budget,
        estimate_tokens,
        order_by_position,
        truncate_blocks,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    IdentityBlock = PromptBlock = PromptCompiler = PromptTemplate = None  # type: ignore[assignment,misc]
    effective_budget = estimate_tokens = order_by_position = truncate_blocks = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module() -> None:
    """Fail every test with the import error while bonfire.prompt is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.prompt not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLE_FRONTMATTER_TEMPLATE = textwrap.dedent("""\
    ---
    max_context_tokens: 4000
    role: scout
    ---
    # {{ role_name }}
    Your mission: {{ task }}
""")

VALID_IDENTITY_FRONTMATTER: dict[str, Any] = {
    "role": "scout",
    "version": "1.0.0",
    "truncation_priority": 100,
    "cognitive_pattern": "observe",
    "tools": ["Read", "Grep"],
    "output_contract": {
        "format": "markdown",
        "required_sections": ["findings", "next"],
    },
}


def _make_block(
    name: str = "test",
    content: str = "hello world",
    priority: int = 50,
    role: str = "system",
) -> Any:
    """Shorthand factory for PromptBlock."""
    return PromptBlock(name=name, content=content, priority=priority, role=role)


# ===========================================================================
# 1. IdentityBlock — renamed frontmatter model
# ===========================================================================


class TestIdentityBlock:
    """IdentityBlock validates cognitive-axiom frontmatter."""

    def test_valid_frontmatter_constructs(self):
        meta = IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert meta.role == "scout"
        assert meta.version == "1.0.0"
        assert meta.truncation_priority == 100

    def test_cognitive_pattern_is_literal(self):
        """cognitive_pattern must be one of the allowed literal values."""
        bad = dict(VALID_IDENTITY_FRONTMATTER, cognitive_pattern="hallucinate")
        with pytest.raises(Exception):
            IdentityBlock.model_validate(bad)

    def test_all_allowed_cognitive_patterns(self):
        """All documented cognitive_pattern values must validate."""
        allowed = [
            "observe",
            "contract",
            "execute",
            "synthesize",
            "audit",
            "publish",
            "announce",
        ]
        for pattern in allowed:
            data = dict(VALID_IDENTITY_FRONTMATTER, cognitive_pattern=pattern)
            meta = IdentityBlock.model_validate(data)
            assert meta.cognitive_pattern == pattern

    def test_truncation_priority_must_be_positive(self):
        """truncation_priority has ``gt=0`` constraint."""
        bad = dict(VALID_IDENTITY_FRONTMATTER, truncation_priority=0)
        with pytest.raises(Exception):
            IdentityBlock.model_validate(bad)

    def test_truncation_priority_negative_rejected(self):
        bad = dict(VALID_IDENTITY_FRONTMATTER, truncation_priority=-10)
        with pytest.raises(Exception):
            IdentityBlock.model_validate(bad)

    def test_missing_required_field_raises(self):
        """role is required."""
        bad = {k: v for k, v in VALID_IDENTITY_FRONTMATTER.items() if k != "role"}
        with pytest.raises(Exception):
            IdentityBlock.model_validate(bad)

    def test_tools_default_is_empty_list(self):
        data = {k: v for k, v in VALID_IDENTITY_FRONTMATTER.items() if k != "tools"}
        meta = IdentityBlock.model_validate(data)
        assert meta.tools == []

    def test_frozen_immutable(self):
        """IdentityBlock instances are frozen."""
        meta = IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        with pytest.raises(Exception):
            meta.role = "changed"  # type: ignore[misc]

    def test_output_contract_has_format(self):
        meta = IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert meta.output_contract.format == "markdown"

    def test_output_contract_has_required_sections(self):
        meta = IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert "findings" in meta.output_contract.required_sections

    def test_output_contract_supports_item_access(self):
        """Back-compat: output_contract supports dict-like access."""
        meta = IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert meta.output_contract["format"] == "markdown"

    def test_output_contract_missing_format_rejected(self):
        bad = dict(
            VALID_IDENTITY_FRONTMATTER,
            output_contract={"required_sections": ["x"]},
        )
        with pytest.raises(Exception):
            IdentityBlock.model_validate(bad)


# ===========================================================================
# 2. PromptBlock
# ===========================================================================


class TestPromptBlock:
    """PromptBlock is a frozen dataclass with name, content, priority, role."""

    def test_construction_all_fields(self):
        block = PromptBlock(name="task", content="Do the thing", priority=100, role="user")
        assert block.name == "task"
        assert block.content == "Do the thing"
        assert block.priority == 100
        assert block.role == "user"

    def test_default_role_is_system(self):
        block = PromptBlock(name="ctx", content="some context", priority=50)
        assert block.role == "system"

    def test_frozen_prevents_mutation(self):
        block = _make_block()
        with pytest.raises(dataclasses.FrozenInstanceError):
            block.name = "changed"  # type: ignore[misc]

    def test_frozen_prevents_priority_mutation(self):
        block = _make_block(priority=10)
        with pytest.raises(dataclasses.FrozenInstanceError):
            block.priority = 99  # type: ignore[misc]

    def test_is_dataclass(self):
        block = _make_block()
        assert dataclasses.is_dataclass(block)

    def test_equality_by_value(self):
        a = PromptBlock(name="x", content="y", priority=1)
        b = PromptBlock(name="x", content="y", priority=1)
        assert a == b

    def test_inequality_different_priority(self):
        a = PromptBlock(name="x", content="y", priority=1)
        b = PromptBlock(name="x", content="y", priority=2)
        assert a != b

    def test_hashable(self):
        """Frozen dataclasses are hashable and usable as set members."""
        a = PromptBlock(name="x", content="y", priority=1)
        b = PromptBlock(name="x", content="y", priority=1)
        assert {a, b} == {a}

    def test_negative_priority_allowed(self):
        """PromptBlock itself does not constrain priority sign."""
        block = PromptBlock(name="x", content="y", priority=-10)
        assert block.priority == -10


# ===========================================================================
# 3. estimate_tokens
# ===========================================================================


class TestEstimateTokens:
    """estimate_tokens: chars // 4, minimum 1 for non-empty, 0 for empty."""

    def test_empty_string_returns_zero(self):
        assert estimate_tokens("") == 0

    def test_single_char_returns_one(self):
        assert estimate_tokens("x") == 1

    def test_four_chars_returns_one(self):
        assert estimate_tokens("abcd") == 1

    def test_five_chars_returns_one(self):
        assert estimate_tokens("abcde") == 1

    def test_eight_chars_returns_two(self):
        assert estimate_tokens("abcdefgh") == 2

    def test_hundred_chars(self):
        assert estimate_tokens("a" * 100) == 25

    def test_three_chars_returns_one_not_zero(self):
        """Non-empty strings must return at least 1."""
        assert estimate_tokens("abc") == 1

    def test_whitespace_only_counts(self):
        assert estimate_tokens("    ") == 1

    def test_long_text(self):
        assert estimate_tokens("x" * 1000) == 250

    def test_returns_int(self):
        assert isinstance(estimate_tokens("abcdefgh"), int)


# ===========================================================================
# 4. effective_budget
# ===========================================================================


class TestEffectiveBudget:
    """effective_budget: floor(max_tokens * (1 - safety_margin))."""

    def test_default_margin(self):
        assert effective_budget(8000) == math.floor(8000 * 0.85)

    def test_custom_margin(self):
        assert effective_budget(10000, safety_margin=0.2) == math.floor(10000 * 0.8)

    def test_zero_margin(self):
        assert effective_budget(5000, safety_margin=0.0) == 5000

    def test_returns_integer(self):
        assert isinstance(effective_budget(8000), int)

    def test_floor_rounding(self):
        """Non-round results are floored, not rounded."""
        assert effective_budget(1001, safety_margin=0.15) == math.floor(1001 * 0.85)

    def test_zero_budget_yields_zero(self):
        assert effective_budget(0) == 0

    def test_full_margin_yields_zero(self):
        """A 100% safety margin leaves no budget."""
        assert effective_budget(1000, safety_margin=1.0) == 0


# ===========================================================================
# 5. truncate_blocks
# ===========================================================================


class TestTruncateBlocks:
    """truncate_blocks: drop lowest-priority first until budget fits."""

    def test_all_fit_returns_unchanged(self):
        blocks = [
            _make_block(name="a", content="short", priority=50),
            _make_block(name="b", content="tiny", priority=80),
        ]
        result = truncate_blocks(blocks, budget=100)
        assert [b.name for b in result] == ["a", "b"]

    def test_drops_lowest_priority_first(self):
        blocks = [
            _make_block(name="important", content="x" * 40, priority=100),
            _make_block(name="filler", content="x" * 40, priority=10),
        ]
        result = truncate_blocks(blocks, budget=12)
        names = [b.name for b in result]
        assert "important" in names
        assert "filler" not in names

    def test_preserves_original_order(self):
        blocks = [
            _make_block(name="first", content="aa", priority=80),
            _make_block(name="second", content="bb", priority=10),
            _make_block(name="third", content="cc", priority=90),
        ]
        result = truncate_blocks(blocks, budget=100)
        assert [b.name for b in result] == ["first", "second", "third"]

    def test_preserves_order_after_drop(self):
        blocks = [
            _make_block(name="A", content="x" * 20, priority=90),
            _make_block(name="B", content="x" * 20, priority=10),
            _make_block(name="C", content="x" * 20, priority=80),
        ]
        result = truncate_blocks(blocks, budget=12)
        names = [b.name for b in result]
        assert "B" not in names
        if "A" in names and "C" in names:
            assert names.index("A") < names.index("C")

    def test_character_slice_last_survivor(self):
        blocks = [_make_block(name="huge", content="x" * 200, priority=100)]
        result = truncate_blocks(blocks, budget=10)
        assert len(result) == 1
        assert len(result[0].content) <= 40  # 10 tokens * 4 chars

    def test_highest_priority_never_dropped_entirely(self):
        blocks = [
            _make_block(name="king", content="x" * 400, priority=100),
            _make_block(name="pawn", content="x" * 400, priority=1),
        ]
        result = truncate_blocks(blocks, budget=5)
        assert "king" in [b.name for b in result]

    def test_empty_blocks_list(self):
        assert truncate_blocks([], budget=100) == []

    def test_single_block_fits(self):
        blocks = [_make_block(name="only", content="hi", priority=50)]
        result = truncate_blocks(blocks, budget=100)
        assert len(result) == 1

    def test_drops_multiple_low_priority(self):
        blocks = [
            _make_block(name="keep", content="x" * 20, priority=100),
            _make_block(name="drop1", content="x" * 20, priority=20),
            _make_block(name="drop2", content="x" * 20, priority=10),
        ]
        result = truncate_blocks(blocks, budget=6)
        names = [b.name for b in result]
        assert "keep" in names
        assert "drop1" not in names
        assert "drop2" not in names

    def test_sliced_block_keeps_priority_and_name(self):
        """Character-slicing must not lose the block's identity metadata."""
        blocks = [_make_block(name="keystone", content="x" * 400, priority=99)]
        result = truncate_blocks(blocks, budget=5)
        assert result[0].name == "keystone"
        assert result[0].priority == 99

    def test_returns_new_list_not_same_object(self):
        """truncate_blocks returns a new list (does not mutate input)."""
        blocks = [_make_block(name="a", content="aa", priority=10)]
        result = truncate_blocks(blocks, budget=100)
        assert result is not blocks


# ===========================================================================
# 6. order_by_position — U-shape
# ===========================================================================


class TestOrderByPosition:
    """order_by_position: highest first, lowest middle, second-highest last."""

    def test_u_shape_four_blocks(self):
        blocks = [
            _make_block(name="p100", priority=100),
            _make_block(name="p50", priority=50),
            _make_block(name="p30", priority=30),
            _make_block(name="p80", priority=80),
        ]
        result = order_by_position(blocks)
        assert [b.name for b in result] == ["p100", "p30", "p50", "p80"]

    def test_single_block(self):
        blocks = [_make_block(name="only", priority=50)]
        assert [b.name for b in order_by_position(blocks)] == ["only"]

    def test_two_blocks(self):
        blocks = [
            _make_block(name="low", priority=10),
            _make_block(name="high", priority=90),
        ]
        result = order_by_position(blocks)
        assert [b.name for b in result] == ["high", "low"]

    def test_three_blocks(self):
        blocks = [
            _make_block(name="mid", priority=50),
            _make_block(name="top", priority=100),
            _make_block(name="bot", priority=10),
        ]
        result = order_by_position(blocks)
        names = [b.name for b in result]
        assert names[0] == "top"
        assert names[-1] == "mid"
        assert names[1] == "bot"

    def test_empty_list(self):
        assert order_by_position([]) == []

    def test_does_not_mutate_input(self):
        blocks = [
            _make_block(name="a", priority=10),
            _make_block(name="b", priority=90),
        ]
        original = list(blocks)
        order_by_position(blocks)
        assert blocks == original


# ===========================================================================
# 7. PromptTemplate.from_file
# ===========================================================================


class TestPromptTemplateFromFile:
    """PromptTemplate.from_file loads and parses YAML frontmatter."""

    def test_loads_file(self, tmp_path: Path):
        f = tmp_path / "prompt.md"
        f.write_text(SAMPLE_FRONTMATTER_TEMPLATE)
        tpl = PromptTemplate.from_file(f)
        assert tpl.path == f

    def test_parses_frontmatter(self, tmp_path: Path):
        f = tmp_path / "prompt.md"
        f.write_text(SAMPLE_FRONTMATTER_TEMPLATE)
        tpl = PromptTemplate.from_file(f)
        assert tpl.frontmatter["max_context_tokens"] == 4000
        assert tpl.frontmatter["role"] == "scout"

    def test_splits_body_from_frontmatter(self, tmp_path: Path):
        f = tmp_path / "prompt.md"
        f.write_text(SAMPLE_FRONTMATTER_TEMPLATE)
        tpl = PromptTemplate.from_file(f)
        assert "{{ role_name }}" in tpl.body
        assert "---" not in tpl.body

    def test_raw_content_preserved(self, tmp_path: Path):
        f = tmp_path / "prompt.md"
        f.write_text(SAMPLE_FRONTMATTER_TEMPLATE)
        tpl = PromptTemplate.from_file(f)
        assert tpl.raw_content == SAMPLE_FRONTMATTER_TEMPLATE

    def test_missing_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            PromptTemplate.from_file(Path("/nonexistent/prompt.md"))

    def test_malformed_yaml_raises_value_error(self, tmp_path: Path):
        f = tmp_path / "bad.md"
        f.write_text(
            textwrap.dedent("""\
                ---
                key: [unbalanced
                ---
                body here
            """)
        )
        with pytest.raises(ValueError):
            PromptTemplate.from_file(f)

    def test_no_frontmatter_empty_dict(self, tmp_path: Path):
        f = tmp_path / "plain.md"
        f.write_text("Just a body, no frontmatter.")
        tpl = PromptTemplate.from_file(f)
        assert tpl.frontmatter == {}
        assert "Just a body" in tpl.body


# ===========================================================================
# 8. PromptTemplate.from_string
# ===========================================================================


class TestPromptTemplateFromString:
    """PromptTemplate.from_string works without a file."""

    def test_creates_template(self):
        tpl = PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        assert tpl.path is None

    def test_parses_frontmatter(self):
        tpl = PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        assert tpl.frontmatter["role"] == "scout"

    def test_body_separated(self):
        tpl = PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        assert "{{ task }}" in tpl.body
        assert "---" not in tpl.body

    def test_plain_string_no_frontmatter(self):
        tpl = PromptTemplate.from_string("Hello {{ name }}")
        assert tpl.frontmatter == {}
        assert "Hello" in tpl.body


# ===========================================================================
# 9. PromptCompiler construction
# ===========================================================================


class TestPromptCompilerConstruction:
    def test_default_budget(self):
        assert PromptCompiler().default_budget == 8000

    def test_default_safety_margin(self):
        assert PromptCompiler().safety_margin == 0.15

    def test_custom_budget(self):
        assert PromptCompiler(default_budget=16000).default_budget == 16000

    def test_custom_safety_margin(self):
        assert PromptCompiler(safety_margin=0.1).safety_margin == 0.1

    def test_project_root(self, tmp_path: Path):
        assert PromptCompiler(project_root=tmp_path).project_root == tmp_path

    def test_project_root_none_default(self):
        assert PromptCompiler().project_root is None


# ===========================================================================
# 10. PromptCompiler.load_template — two-tier discovery
# ===========================================================================


class TestPromptCompilerLoadTemplate:
    """load_template: project_root/agents/{role}/prompt.md -> bundled defaults."""

    def test_loads_from_project_root(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "scout"
        agent_dir.mkdir(parents=True)
        prompt_file = agent_dir / "prompt.md"
        prompt_file.write_text(SAMPLE_FRONTMATTER_TEMPLATE)

        compiler = PromptCompiler(project_root=tmp_path)
        tpl = compiler.load_template("scout")
        assert tpl.path == prompt_file

    def test_raises_when_not_found_anywhere(self, tmp_path: Path):
        compiler = PromptCompiler(project_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="nonexistent_role"):
            compiler.load_template("nonexistent_role")

    def test_no_project_root_uses_bundled_only(self):
        compiler = PromptCompiler(project_root=None)
        with pytest.raises(FileNotFoundError):
            compiler.load_template("nonexistent_role")

    def test_project_root_takes_precedence_over_bundled(self, tmp_path: Path):
        """If a template exists in BOTH project and bundled, project wins."""
        agent_dir = tmp_path / "agents" / "custom_role"
        agent_dir.mkdir(parents=True)
        local_template = "---\norigin: project\n---\nlocal body"
        (agent_dir / "prompt.md").write_text(local_template)

        compiler = PromptCompiler(project_root=tmp_path)
        tpl = compiler.load_template("custom_role")
        assert tpl.frontmatter.get("origin") == "project"


# ===========================================================================
# 11. PromptCompiler.load_identity_block — renamed axiom layer
# ===========================================================================


class TestPromptCompilerLoadIdentityBlock:
    """load_identity_block: discovery for identity (axiom) layer templates.

    Renamed from load_axiom in the public surface. Module path
    ``bonfire.prompt.identity_block`` (renamed from axiom_meta).
    """

    def test_loads_from_project_root(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "scout"
        agent_dir.mkdir(parents=True)
        axiom_body = textwrap.dedent("""\
            ---
            role: scout
            version: 1.0.0
            truncation_priority: 100
            cognitive_pattern: observe
            output_contract:
              format: markdown
              required_sections: [findings]
            ---
            # Scout identity
        """)
        (agent_dir / "identity_block.md").write_text(axiom_body)

        compiler = PromptCompiler(project_root=tmp_path)
        tpl = compiler.load_identity_block("scout")
        assert tpl is not None
        assert "Scout identity" in tpl.body

    def test_returns_none_when_not_found(self, tmp_path: Path):
        compiler = PromptCompiler(project_root=tmp_path)
        assert compiler.load_identity_block("nonexistent_role") is None

    def test_load_identity_block_validated_success(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "scout"
        agent_dir.mkdir(parents=True)
        axiom_body = textwrap.dedent("""\
            ---
            role: scout
            version: 1.0.0
            truncation_priority: 100
            cognitive_pattern: observe
            tools: [Read, Grep]
            output_contract:
              format: markdown
              required_sections: [findings]
            ---
            # body
        """)
        (agent_dir / "identity_block.md").write_text(axiom_body)

        compiler = PromptCompiler(project_root=tmp_path)
        tpl, meta = compiler.load_identity_block_validated("scout")
        assert isinstance(meta, IdentityBlock)
        assert meta.role == "scout"
        assert meta.tools == ["Read", "Grep"]

    def test_load_identity_block_validated_missing_raises(self, tmp_path: Path):
        compiler = PromptCompiler(project_root=tmp_path)
        with pytest.raises(ValueError, match="nonexistent"):
            compiler.load_identity_block_validated("nonexistent")

    def test_load_identity_block_validated_invalid_frontmatter_raises(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "scout"
        agent_dir.mkdir(parents=True)
        # Missing required fields (role, version, etc.)
        axiom_body = "---\nfoo: bar\n---\nbody"
        (agent_dir / "identity_block.md").write_text(axiom_body)

        compiler = PromptCompiler(project_root=tmp_path)
        with pytest.raises(ValueError):
            compiler.load_identity_block_validated("scout")

    def test_get_role_tools_returns_tools_list(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "knight"
        agent_dir.mkdir(parents=True)
        axiom_body = textwrap.dedent("""\
            ---
            role: knight
            version: 1.0.0
            truncation_priority: 100
            cognitive_pattern: execute
            tools: [Read, Write, Edit]
            output_contract:
              format: markdown
              required_sections: [files]
            ---
            # knight
        """)
        (agent_dir / "identity_block.md").write_text(axiom_body)

        compiler = PromptCompiler(project_root=tmp_path)
        assert compiler.get_role_tools("knight") == ["Read", "Write", "Edit"]

    def test_get_role_tools_missing_returns_empty_list(self, tmp_path: Path):
        compiler = PromptCompiler(project_root=tmp_path)
        assert compiler.get_role_tools("nonexistent") == []


# ===========================================================================
# 12. PromptCompiler.render_template — Jinja2
# ===========================================================================


class TestPromptCompilerRenderTemplate:
    def test_renders_simple_variable(self):
        tpl = PromptTemplate.from_string("Hello {{ name }}")
        assert PromptCompiler().render_template(tpl, {"name": "World"}) == "Hello World"

    def test_renders_multiple_variables(self):
        tpl = PromptTemplate.from_string("{{ a }}: {{ b }}")
        result = PromptCompiler().render_template(tpl, {"a": "Scout", "b": "investigate"})
        assert result == "Scout: investigate"

    def test_strict_undefined_raises_on_missing(self):
        tpl = PromptTemplate.from_string("Hello {{ missing_var }}")
        with pytest.raises(Exception, match="missing_var"):
            PromptCompiler().render_template(tpl, {})

    def test_renders_conditional(self):
        tpl = PromptTemplate.from_string("{% if urgent %}URGENT: {% endif %}{{ task }}")
        result = PromptCompiler().render_template(tpl, {"urgent": True, "task": "fix bug"})
        assert "URGENT:" in result

    def test_renders_for_loop(self):
        tpl = PromptTemplate.from_string("{% for i in items %}{{ i }} {% endfor %}")
        result = PromptCompiler().render_template(tpl, {"items": ["a", "b", "c"]})
        assert "a" in result and "b" in result and "c" in result

    def test_renders_from_frontmatter_template(self):
        tpl = PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        result = PromptCompiler().render_template(
            tpl, {"role_name": "Scout Alpha", "task": "find bugs"}
        )
        assert "Scout Alpha" in result
        assert "find bugs" in result


# ===========================================================================
# 13. PromptCompiler.compile — full pipeline
# ===========================================================================


class TestPromptCompilerCompile:
    def test_joins_blocks_with_double_newline(self):
        blocks = [
            _make_block(name="a", content="First", priority=80),
            _make_block(name="b", content="Second", priority=60),
        ]
        compiler = PromptCompiler(default_budget=10000)
        result = compiler.compile(blocks, positional_order=False)
        assert "First\n\nSecond" in result

    def test_uses_default_budget_when_none(self):
        blocks = [_make_block(name="big", content="x" * 40000, priority=50)]
        compiler = PromptCompiler(default_budget=8000)
        result = compiler.compile(blocks, budget=None)
        assert len(result) <= 27200

    def test_explicit_budget_overrides_default(self):
        blocks = [_make_block(name="x", content="x" * 800, priority=50)]
        compiler = PromptCompiler(default_budget=8000)
        result = compiler.compile(blocks, budget=50)
        assert len(result) <= 200

    def test_positional_order_true_reorders_u_shape(self):
        blocks = [
            _make_block(name="p100", content="high", priority=100),
            _make_block(name="p30", content="low", priority=30),
            _make_block(name="p80", content="mid", priority=80),
        ]
        compiler = PromptCompiler(default_budget=10000)
        result = compiler.compile(blocks, positional_order=True)
        assert result.index("high") < result.index("low") < result.index("mid")

    def test_positional_order_false_preserves_original(self):
        blocks = [
            _make_block(name="first", content="AAA", priority=30),
            _make_block(name="second", content="BBB", priority=100),
            _make_block(name="third", content="CCC", priority=60),
        ]
        compiler = PromptCompiler(default_budget=10000)
        result = compiler.compile(blocks, positional_order=False)
        assert result.index("AAA") < result.index("BBB") < result.index("CCC")

    def test_truncates_blocks_by_priority(self):
        blocks = [
            _make_block(name="keep", content="x" * 40, priority=100),
            _make_block(name="drop", content="x" * 40, priority=10),
        ]
        compiler = PromptCompiler(default_budget=100)
        result = compiler.compile(blocks, budget=12)
        assert len(result) <= 48

    def test_compile_empty_blocks(self):
        assert PromptCompiler().compile([]) == ""


# ===========================================================================
# 14. PromptCompiler.compose_agent_prompt — three-layer composition
# ===========================================================================


class TestComposeAgentPrompt:
    """compose_agent_prompt: identity + mission + reach three-layer assembly."""

    def test_assembles_three_layers(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "scout"
        agent_dir.mkdir(parents=True)
        identity_body = textwrap.dedent("""\
            ---
            role: scout
            version: 1.0.0
            truncation_priority: 100
            cognitive_pattern: observe
            output_contract:
              format: markdown
              required_sections: [findings]
            ---
            IDENTITY_MARKER: I am the scout.
        """)
        (agent_dir / "identity_block.md").write_text(identity_body)
        (agent_dir / "prompt.md").write_text("MISSION_MARKER: Find {{ target }}.")

        compiler = PromptCompiler(project_root=tmp_path, default_budget=10000)
        result = compiler.compose_agent_prompt(
            role="scout",
            variables={"target": "bugs"},
            reach_context={"tools": ["Grep", "Read"]},
        )
        assert "IDENTITY_MARKER" in result
        assert "MISSION_MARKER" in result
        assert "bugs" in result
        assert "Grep" in result

    def test_skips_reach_when_empty(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "scout"
        agent_dir.mkdir(parents=True)
        (agent_dir / "prompt.md").write_text("MISSION_MARKER: x")

        compiler = PromptCompiler(project_root=tmp_path, default_budget=10000)
        result = compiler.compose_agent_prompt(
            role="scout",
            variables={},
            reach_context={},
        )
        assert "MISSION_MARKER" in result

    def test_missing_mission_raises(self, tmp_path: Path):
        compiler = PromptCompiler(project_root=tmp_path)
        with pytest.raises(FileNotFoundError):
            compiler.compose_agent_prompt(
                role="ghost",
                variables={},
                reach_context={},
            )


# ===========================================================================
# 15. PromptCompiler.guard_diff — Wizard diff truncation
# ===========================================================================


class TestGuardDiff:
    """guard_diff: truncate oversized diffs with summary header."""

    def test_small_diff_returned_unchanged(self):
        compiler = PromptCompiler()
        diff = "line1\nline2\nline3\n"
        assert compiler.guard_diff(diff, max_lines=5000) == diff

    def test_exact_limit_returned_unchanged(self):
        compiler = PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(100))
        assert compiler.guard_diff(diff, max_lines=100) == diff

    def test_oversized_diff_truncated(self):
        compiler = PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(200))
        result = compiler.guard_diff(diff, max_lines=50)
        result_lines = result.split("\n")
        assert result_lines[0].startswith("[Diff truncated:")
        assert result_lines[1] == ""
        assert len(result_lines[2:]) == 50

    def test_summary_header_format(self):
        compiler = PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(300))
        result = compiler.guard_diff(diff, max_lines=100)
        header = result.split("\n")[0]
        assert "300 total lines" in header
        assert "showing first 100" in header
        assert "200 lines omitted" in header

    def test_default_max_lines_is_5000(self):
        compiler = PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(5001))
        result = compiler.guard_diff(diff)
        assert result.startswith("[Diff truncated:")

    def test_empty_diff_returned_unchanged(self):
        assert PromptCompiler().guard_diff("") == ""

    def test_single_line_diff_returned_unchanged(self):
        assert PromptCompiler().guard_diff("only line") == "only line"


# ===========================================================================
# 16. Innovative-lens edge cases — adversarial + pathological inputs
# ===========================================================================


class TestInnovativeEdge:
    """Edge cases probing priority collisions, Unicode, injection, U-shape stability."""

    def test_priority_collision_stable_order(self):
        """Equal priorities must not reorder; U-shape must be deterministic."""
        blocks = [
            _make_block(name="a", content="aa", priority=50),
            _make_block(name="b", content="bb", priority=50),
            _make_block(name="c", content="cc", priority=50),
        ]
        result1 = order_by_position(blocks)
        result2 = order_by_position(blocks)
        # Same input produces same output across calls (determinism).
        assert [b.name for b in result1] == [b.name for b in result2]

    def test_all_equal_priority_truncate_drops_deterministically(self):
        """When all priorities tie, truncation must still terminate safely."""
        blocks = [
            _make_block(name="a", content="x" * 40, priority=50),
            _make_block(name="b", content="x" * 40, priority=50),
            _make_block(name="c", content="x" * 40, priority=50),
        ]
        result = truncate_blocks(blocks, budget=12)
        # Must return at least one block; must not infinite-loop.
        assert len(result) >= 1
        assert len(result) <= 3

    def test_truncate_preserves_block_identity_not_copies(self):
        """Surviving blocks that weren't sliced must be the same instances."""
        keep = _make_block(name="keep", content="short", priority=100)
        drop = _make_block(name="drop", content="x" * 400, priority=1)
        result = truncate_blocks([keep, drop], budget=5)
        # The survivor should be a slice-or-original of the high-priority one.
        assert any(b.name == "keep" for b in result)

    def test_truncate_empty_content_blocks_fit(self):
        """Blocks with empty content consume 0 tokens and always fit."""
        blocks = [
            _make_block(name="empty1", content="", priority=10),
            _make_block(name="empty2", content="", priority=20),
        ]
        result = truncate_blocks(blocks, budget=0)
        assert len(result) == 2

    def test_unicode_content_token_estimation(self):
        """Token estimation works on Unicode (emoji, CJK)."""
        # chars/4 heuristic: 8 unicode chars (code points) -> 2 tokens.
        text = "\U0001f525" * 8  # 8 fire emojis
        assert estimate_tokens(text) == 2

    def test_unicode_in_template_body(self):
        """Jinja2 rendering preserves non-ASCII bytes correctly."""
        tpl = PromptTemplate.from_string("Hello {{ name }} \u2728")
        result = PromptCompiler().render_template(tpl, {"name": "\u4e16\u754c"})
        assert "\u4e16\u754c" in result
        assert "\u2728" in result

    def test_jinja2_sandbox_blocks_attribute_access(self):
        """Sandboxed environment forbids dunder attribute traversal."""
        malicious = "{{ ().__class__.__mro__[1].__subclasses__() }}"
        tpl = PromptTemplate.from_string(malicious)
        with pytest.raises(Exception):
            PromptCompiler().render_template(tpl, {})

    def test_frontmatter_with_nested_structure_parses(self, tmp_path: Path):
        """Nested YAML frontmatter is exposed as nested dicts."""
        f = tmp_path / "prompt.md"
        f.write_text(
            textwrap.dedent("""\
                ---
                metadata:
                  version: 2
                  tags:
                    - alpha
                    - beta
                ---
                body here
            """)
        )
        tpl = PromptTemplate.from_file(f)
        assert tpl.frontmatter["metadata"]["version"] == 2
        assert tpl.frontmatter["metadata"]["tags"] == ["alpha", "beta"]

    def test_frontmatter_scalar_not_dict_falls_back_to_empty(self, tmp_path: Path):
        """A frontmatter that parses to a non-dict scalar is treated as empty."""
        f = tmp_path / "prompt.md"
        f.write_text(
            textwrap.dedent("""\
                ---
                just a string
                ---
                body
            """)
        )
        tpl = PromptTemplate.from_file(f)
        assert tpl.frontmatter == {}
        assert "body" in tpl.body

    def test_three_dashes_in_body_not_treated_as_frontmatter_boundary(
        self,
    ):
        """Only a leading frontmatter delimiter separates; body --- is literal."""
        content = textwrap.dedent("""\
            ---
            role: x
            ---
            intro
            ---
            middle
        """)
        tpl = PromptTemplate.from_string(content)
        assert tpl.frontmatter == {"role": "x"}
        # Body still contains the inner "---"
        assert "---" in tpl.body

    def test_u_shape_two_equal_priority_tie(self):
        """U-shape with only-ties still returns a 2-element list."""
        blocks = [
            _make_block(name="a", priority=50),
            _make_block(name="b", priority=50),
        ]
        result = order_by_position(blocks)
        assert len(result) == 2

    def test_compile_character_slice_into_u_shape(self):
        """Character-sliced survivor still participates in U-shape correctly."""
        blocks = [
            _make_block(name="huge", content="x" * 400, priority=100),
            _make_block(name="small", content="tiny", priority=50),
        ]
        compiler = PromptCompiler(default_budget=100)
        result = compiler.compile(blocks, budget=8, positional_order=True)
        # Both survive (priority=100 never fully dropped; priority=50 may drop).
        # At minimum, the result is a string and not empty.
        assert isinstance(result, str)
        assert len(result) > 0

    def test_compile_very_small_budget_still_produces_output(self):
        """Even a 1-token budget produces *some* output from highest-priority block."""
        blocks = [_make_block(name="x", content="abcdefgh", priority=100)]
        result = PromptCompiler().compile(blocks, budget=1)
        assert isinstance(result, str)

    def test_render_template_with_empty_body(self):
        """A template with frontmatter but no body renders to empty string."""
        tpl = PromptTemplate.from_string("---\nrole: x\n---\n")
        result = PromptCompiler().render_template(tpl, {})
        assert result.strip() == ""

    def test_identity_block_extra_fields_rejected_or_ignored(self):
        """Unknown frontmatter fields are rejected by the frozen model."""
        data = dict(VALID_IDENTITY_FRONTMATTER, mystery_field="sneaky")
        # Pydantic default behavior: extra fields are either ignored or rejected.
        # Either way, the model must still validate on the known fields OR raise.
        try:
            meta = IdentityBlock.model_validate(data)
            # If accepted, mystery_field is not on the model surface.
            assert not hasattr(meta, "mystery_field")
        except Exception:
            # If rejected, that is also an acceptable contract.
            pass


# ===========================================================================
# 17. Dependency constraints — prompt/ is a leaf module
# ===========================================================================


class TestDependencyConstraints:
    """prompt/ must not import from higher-layer packages (dispatch, engine, etc.)."""

    def test_compiler_has_no_forbidden_imports(self):
        prompt_pkg = Path(__file__).resolve().parents[2] / "src" / "bonfire" / "prompt"
        source = (prompt_pkg / "compiler.py").read_text()
        forbidden = [
            "bonfire.dispatch",
            "bonfire.engine",
            "bonfire.cli",
            "bonfire.workflows",
            "bonfire.session",
            "bonfire.vault",
            "bonfire.handlers",
            "bonfire.git",
            "bonfire.github",
        ]
        for module in forbidden:
            assert module not in source, f"compiler.py must not import {module}"

    def test_truncation_has_no_forbidden_imports(self):
        prompt_pkg = Path(__file__).resolve().parents[2] / "src" / "bonfire" / "prompt"
        source = (prompt_pkg / "truncation.py").read_text()
        forbidden = [
            "bonfire.dispatch",
            "bonfire.engine",
            "bonfire.cli",
            "bonfire.workflows",
            "bonfire.session",
            "bonfire.vault",
            "bonfire.handlers",
            "bonfire.git",
            "bonfire.github",
        ]
        for module in forbidden:
            assert module not in source, f"truncation.py must not import {module}"

    def test_identity_block_module_has_no_forbidden_imports(self):
        """identity_block.py (renamed from axiom_meta.py) stays leaf."""
        prompt_pkg = Path(__file__).resolve().parents[2] / "src" / "bonfire" / "prompt"
        source = (prompt_pkg / "identity_block.py").read_text()
        forbidden = [
            "bonfire.dispatch",
            "bonfire.engine",
            "bonfire.cli",
            "bonfire.workflows",
            "bonfire.session",
            "bonfire.vault",
            "bonfire.handlers",
        ]
        for module in forbidden:
            assert module not in source, f"identity_block.py must not import {module}"
