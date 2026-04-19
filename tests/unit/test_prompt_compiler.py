"""Tests for bonfire.prompt — compiler, truncation, templates, IdentityBlock.

Knight-B conservative lens for BON-340. Mirrors the established coverage for
the prompt module: PromptBlock, token estimation, budget math, priority-based
truncation, U-shape ordering, YAML-frontmatter template parsing, Jinja2
rendering, the full compile pipeline, the diff guard, and IdentityBlock
(Pydantic frontmatter validation, formerly AxiomMeta) plus the AxiomLoaded
event integration.

All tests import from ``bonfire.prompt`` lazily (per-test, matching the
v0.1 public-test idiom in ``tests/unit/test_engine_init.py``) so each
currently-missing symbol produces a granular per-test RED rather than a
whole-file collection error. Warrior fills GREEN later.

Categories:
  1.  PromptBlock                — construction, frozen, default role, equality
  2.  estimate_tokens            — chars/4, empty, non-empty, minimum 1
  3.  effective_budget           — safety margin math
  4.  truncate_blocks            — priority-based dropping, order preservation
  5.  order_by_position          — U-shaped attention ordering
  6.  PromptTemplate.from_file   — load, frontmatter parse, errors
  7.  PromptTemplate.from_string — same without file
  8.  PromptCompiler construction
  9.  PromptCompiler.load_template — two-tier discovery, errors
 10.  PromptCompiler.render_template — Jinja2, StrictUndefined
 11.  PromptCompiler.compile      — full pipeline: truncate + order + join
 12.  PromptCompiler.guard_diff   — diff size guard for Wizard reviews
 13.  Dependency constraints      — prompt/ imports stay inside its layer
 14.  IdentityBlock valid         — frontmatter parsing (was AxiomMeta)
 15.  IdentityBlock invalid       — validation rejections
 16.  AxiomLoaded event           — BonfireEvent conformance
 17.  load_axiom_validated        — compiler integration with IdentityBlock
"""

from __future__ import annotations

import dataclasses
import math
import textwrap
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Lazy-import shims — each test re-imports ``bonfire.prompt`` from inside its
# body so that a missing symbol produces a granular per-test RED rather than
# a single whole-file collection error. Matches the v0.1 public idiom in
# ``tests/unit/test_engine_init.py``.
# ---------------------------------------------------------------------------


def _prompt() -> Any:
    """Lazy-import ``bonfire.prompt``."""
    import bonfire.prompt as _p

    return _p


def _truncation() -> Any:
    """Lazy-import ``bonfire.prompt.truncation``."""
    import bonfire.prompt.truncation as _t

    return _t


def _events() -> Any:
    """Lazy-import ``bonfire.models.events``."""
    import bonfire.models.events as _e

    return _e


# ---------------------------------------------------------------------------
# Helpers & fixtures
# ---------------------------------------------------------------------------

SAMPLE_FRONTMATTER_TEMPLATE = textwrap.dedent("""\
    ---
    max_context_tokens: 4000
    role: scout
    ---
    # {{ role_name }}
    Your mission: {{ task }}
""")


VALID_COGNITIVE_PATTERNS = {
    "observe",
    "contract",
    "execute",
    "synthesize",
    "audit",
    "publish",
    "announce",
}


VALID_FRONTMATTER: dict = {
    "role": "scout",
    "version": "1.0.0",
    "truncation_priority": 100,
    "cognitive_pattern": "observe",
    "output_contract": {
        "format": "structured",
        "required_sections": ["terrain_map", "key_findings", "risks", "open_questions"],
    },
}


def _make_block(
    name: str = "test",
    content: str = "hello world",
    priority: int = 50,
    role: str = "system",
) -> Any:
    """Shorthand factory for PromptBlock (lazy-imported)."""
    return _prompt().PromptBlock(name=name, content=content, priority=priority, role=role)


def _write_axiom(
    base: Path,
    role: str,
    frontmatter: dict | None = None,
    body: str = "# Axiom body",
) -> Path:
    """Write a minimal axiom.md under base/agents/<role>/axiom.md."""
    import yaml

    fm = frontmatter if frontmatter is not None else VALID_FRONTMATTER
    agent_dir = base / "agents" / role
    agent_dir.mkdir(parents=True, exist_ok=True)
    axiom_file = agent_dir / "axiom.md"
    yaml_text = yaml.safe_dump(fm, sort_keys=False).strip()
    axiom_file.write_text(f"---\n{yaml_text}\n---\n{body}\n")
    return axiom_file


# ===========================================================================
# 1. PromptBlock
# ===========================================================================


class TestPromptBlock:
    """PromptBlock is a frozen dataclass with name, content, priority, role."""

    def test_construction_all_fields(self):
        PromptBlock = _prompt().PromptBlock
        block = PromptBlock(name="task", content="Do the thing", priority=100, role="user")
        assert block.name == "task"
        assert block.content == "Do the thing"
        assert block.priority == 100
        assert block.role == "user"

    def test_default_role_is_system(self):
        PromptBlock = _prompt().PromptBlock
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
        PromptBlock = _prompt().PromptBlock
        a = PromptBlock(name="x", content="y", priority=1)
        b = PromptBlock(name="x", content="y", priority=1)
        assert a == b

    def test_inequality_different_priority(self):
        PromptBlock = _prompt().PromptBlock
        a = PromptBlock(name="x", content="y", priority=1)
        b = PromptBlock(name="x", content="y", priority=2)
        assert a != b


# ===========================================================================
# 2. estimate_tokens
# ===========================================================================


class TestEstimateTokens:
    """estimate_tokens: chars // 4, minimum 1 for non-empty, 0 for empty."""

    def test_empty_string_returns_zero(self):
        assert _truncation().estimate_tokens("") == 0

    def test_single_char_returns_one(self):
        assert _truncation().estimate_tokens("x") == 1

    def test_four_chars_returns_one(self):
        assert _truncation().estimate_tokens("abcd") == 1

    def test_five_chars_returns_one(self):
        assert _truncation().estimate_tokens("abcde") == 1

    def test_eight_chars_returns_two(self):
        assert _truncation().estimate_tokens("abcdefgh") == 2

    def test_hundred_chars(self):
        text = "a" * 100
        assert _truncation().estimate_tokens(text) == 25

    def test_three_chars_returns_one_not_zero(self):
        """Non-empty strings must return at least 1."""
        assert _truncation().estimate_tokens("abc") == 1

    def test_whitespace_only_counts(self):
        assert _truncation().estimate_tokens("    ") == 1

    def test_long_text(self):
        text = "x" * 1000
        assert _truncation().estimate_tokens(text) == 250


# ===========================================================================
# 3. effective_budget
# ===========================================================================


class TestEffectiveBudget:
    """effective_budget: floor(max_tokens * (1 - safety_margin))."""

    def test_default_margin(self):
        result = _truncation().effective_budget(8000)
        assert result == math.floor(8000 * 0.85)

    def test_custom_margin(self):
        result = _truncation().effective_budget(10000, safety_margin=0.2)
        assert result == math.floor(10000 * 0.8)

    def test_zero_margin(self):
        result = _truncation().effective_budget(5000, safety_margin=0.0)
        assert result == 5000

    def test_returns_integer(self):
        result = _truncation().effective_budget(8000)
        assert isinstance(result, int)

    def test_floor_rounding(self):
        """Non-round results are floored, not rounded."""
        result = _truncation().effective_budget(1001, safety_margin=0.15)
        expected = math.floor(1001 * 0.85)
        assert result == expected


# ===========================================================================
# 4. truncate_blocks
# ===========================================================================


class TestTruncateBlocks:
    """truncate_blocks: drop lowest-priority first until budget fits."""

    def test_all_fit_returns_unchanged(self):
        """If total tokens <= budget, return all blocks as-is."""
        blocks = [
            _make_block(name="a", content="short", priority=50),
            _make_block(name="b", content="tiny", priority=80),
        ]
        result = _truncation().truncate_blocks(blocks, budget=100)
        assert len(result) == 2
        assert [b.name for b in result] == ["a", "b"]

    def test_drops_lowest_priority_first(self):
        """Lowest priority block is dropped before higher ones."""
        blocks = [
            _make_block(name="important", content="x" * 40, priority=100),
            _make_block(name="filler", content="x" * 40, priority=10),
        ]
        # Budget fits only one block worth of tokens
        result = _truncation().truncate_blocks(blocks, budget=12)
        names = [b.name for b in result]
        assert "important" in names
        assert "filler" not in names

    def test_preserves_original_order(self):
        """Surviving blocks keep their original insertion order."""
        blocks = [
            _make_block(name="first", content="aa", priority=80),
            _make_block(name="second", content="bb", priority=10),
            _make_block(name="third", content="cc", priority=90),
        ]
        result = _truncation().truncate_blocks(blocks, budget=100)
        names = [b.name for b in result]
        # All fit at budget=100, order preserved
        assert names == ["first", "second", "third"]

    def test_preserves_order_after_drop(self):
        """After dropping low-priority blocks, remaining keep original order."""
        blocks = [
            _make_block(name="A", content="x" * 20, priority=90),
            _make_block(name="B", content="x" * 20, priority=10),
            _make_block(name="C", content="x" * 20, priority=80),
        ]
        # Budget fits ~2 blocks (each ~5 tokens), not 3 (~15)
        result = _truncation().truncate_blocks(blocks, budget=12)
        names = [b.name for b in result]
        assert "B" not in names
        # A comes before C in original order
        if "A" in names and "C" in names:
            assert names.index("A") < names.index("C")

    def test_character_slice_last_survivor(self):
        """If single block exceeds budget, character-slice from end."""
        blocks = [
            _make_block(name="huge", content="x" * 200, priority=100),
        ]
        result = _truncation().truncate_blocks(blocks, budget=10)
        assert len(result) == 1
        # 10 tokens * 4 chars = 40 chars max
        assert len(result[0].content) <= 40

    def test_highest_priority_never_dropped_entirely(self):
        """The highest-priority block is NEVER fully dropped."""
        blocks = [
            _make_block(name="king", content="x" * 400, priority=100),
            _make_block(name="pawn", content="x" * 400, priority=1),
        ]
        result = _truncation().truncate_blocks(blocks, budget=5)
        names = [b.name for b in result]
        assert "king" in names

    def test_empty_blocks_list(self):
        result = _truncation().truncate_blocks([], budget=100)
        assert result == []

    def test_single_block_fits(self):
        blocks = [_make_block(name="only", content="hi", priority=50)]
        result = _truncation().truncate_blocks(blocks, budget=100)
        assert len(result) == 1
        assert result[0].name == "only"

    def test_drops_multiple_low_priority(self):
        """Can drop more than one block to fit budget."""
        blocks = [
            _make_block(name="keep", content="x" * 20, priority=100),
            _make_block(name="drop1", content="x" * 20, priority=20),
            _make_block(name="drop2", content="x" * 20, priority=10),
        ]
        result = _truncation().truncate_blocks(blocks, budget=6)
        names = [b.name for b in result]
        assert "keep" in names
        assert "drop1" not in names
        assert "drop2" not in names


# ===========================================================================
# 5. order_by_position — U-shape attention
# ===========================================================================


class TestOrderByPosition:
    """order_by_position: highest first, lowest middle, second-highest last."""

    def test_u_shape_four_blocks(self):
        """Given priorities [100, 50, 30, 80], order = [100, 30, 50, 80]."""
        blocks = [
            _make_block(name="p100", priority=100),
            _make_block(name="p50", priority=50),
            _make_block(name="p30", priority=30),
            _make_block(name="p80", priority=80),
        ]
        result = _truncation().order_by_position(blocks)
        names = [b.name for b in result]
        assert names == ["p100", "p30", "p50", "p80"]

    def test_single_block(self):
        blocks = [_make_block(name="only", priority=50)]
        result = _truncation().order_by_position(blocks)
        assert [b.name for b in result] == ["only"]

    def test_two_blocks(self):
        """Two blocks: highest first, second last."""
        blocks = [
            _make_block(name="low", priority=10),
            _make_block(name="high", priority=90),
        ]
        result = _truncation().order_by_position(blocks)
        names = [b.name for b in result]
        assert names[0] == "high"
        assert names[-1] == "low"

    def test_three_blocks(self):
        """Three blocks: highest first, lowest middle, second-highest last."""
        blocks = [
            _make_block(name="mid", priority=50),
            _make_block(name="top", priority=100),
            _make_block(name="bot", priority=10),
        ]
        result = _truncation().order_by_position(blocks)
        names = [b.name for b in result]
        assert names[0] == "top"
        assert names[-1] == "mid"
        assert names[1] == "bot"

    def test_empty_list(self):
        assert _truncation().order_by_position([]) == []

    def test_does_not_mutate_input(self):
        blocks = [
            _make_block(name="a", priority=10),
            _make_block(name="b", priority=90),
        ]
        original = list(blocks)
        _truncation().order_by_position(blocks)
        assert blocks == original


# ===========================================================================
# 6. PromptTemplate.from_file
# ===========================================================================


class TestPromptTemplateFromFile:
    """PromptTemplate.from_file loads and parses YAML frontmatter."""

    def test_loads_file(self, tmp_path: Path):
        f = tmp_path / "prompt.md"
        f.write_text(SAMPLE_FRONTMATTER_TEMPLATE)
        tpl = _prompt().PromptTemplate.from_file(f)
        assert tpl.path == f

    def test_parses_frontmatter(self, tmp_path: Path):
        f = tmp_path / "prompt.md"
        f.write_text(SAMPLE_FRONTMATTER_TEMPLATE)
        tpl = _prompt().PromptTemplate.from_file(f)
        assert tpl.frontmatter["max_context_tokens"] == 4000
        assert tpl.frontmatter["role"] == "scout"

    def test_splits_body_from_frontmatter(self, tmp_path: Path):
        f = tmp_path / "prompt.md"
        f.write_text(SAMPLE_FRONTMATTER_TEMPLATE)
        tpl = _prompt().PromptTemplate.from_file(f)
        assert "{{ role_name }}" in tpl.body
        assert "---" not in tpl.body

    def test_raw_content_preserved(self, tmp_path: Path):
        f = tmp_path / "prompt.md"
        f.write_text(SAMPLE_FRONTMATTER_TEMPLATE)
        tpl = _prompt().PromptTemplate.from_file(f)
        assert tpl.raw_content == SAMPLE_FRONTMATTER_TEMPLATE

    def test_missing_file_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            _prompt().PromptTemplate.from_file(Path("/nonexistent/prompt.md"))

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
            _prompt().PromptTemplate.from_file(f)

    def test_no_frontmatter_empty_dict(self, tmp_path: Path):
        """A file with no frontmatter should have empty frontmatter dict."""
        f = tmp_path / "plain.md"
        f.write_text("Just a body, no frontmatter.")
        tpl = _prompt().PromptTemplate.from_file(f)
        assert tpl.frontmatter == {}
        assert "Just a body" in tpl.body


# ===========================================================================
# 7. PromptTemplate.from_string
# ===========================================================================


class TestPromptTemplateFromString:
    """PromptTemplate.from_string works without a file."""

    def test_creates_template(self):
        tpl = _prompt().PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        assert tpl.path is None

    def test_parses_frontmatter(self):
        tpl = _prompt().PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        assert tpl.frontmatter["role"] == "scout"

    def test_body_separated(self):
        tpl = _prompt().PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        assert "{{ task }}" in tpl.body
        assert "---" not in tpl.body

    def test_plain_string_no_frontmatter(self):
        tpl = _prompt().PromptTemplate.from_string("Hello {{ name }}")
        assert tpl.frontmatter == {}
        assert "Hello" in tpl.body


# ===========================================================================
# 8. PromptCompiler construction
# ===========================================================================


class TestPromptCompilerConstruction:
    """PromptCompiler init with defaults and custom values."""

    def test_default_budget(self):
        compiler = _prompt().PromptCompiler()
        assert compiler.default_budget == 8000

    def test_default_safety_margin(self):
        compiler = _prompt().PromptCompiler()
        assert compiler.safety_margin == 0.15

    def test_custom_budget(self):
        compiler = _prompt().PromptCompiler(default_budget=16000)
        assert compiler.default_budget == 16000

    def test_custom_safety_margin(self):
        compiler = _prompt().PromptCompiler(safety_margin=0.1)
        assert compiler.safety_margin == 0.1

    def test_project_root(self, tmp_path: Path):
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        assert compiler.project_root == tmp_path

    def test_project_root_none_default(self):
        compiler = _prompt().PromptCompiler()
        assert compiler.project_root is None


# ===========================================================================
# 9. PromptCompiler.load_template — two-tier discovery
# ===========================================================================


class TestPromptCompilerLoadTemplate:
    """load_template: project_root/agents/{role}/prompt.md -> bundled defaults."""

    def test_loads_from_project_root(self, tmp_path: Path):
        """First tier: project_root/agents/{role}/prompt.md."""
        agent_dir = tmp_path / "agents" / "scout"
        agent_dir.mkdir(parents=True)
        prompt_file = agent_dir / "prompt.md"
        prompt_file.write_text(SAMPLE_FRONTMATTER_TEMPLATE)

        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        tpl = compiler.load_template("scout")
        assert tpl.path == prompt_file

    def test_falls_back_to_bundled_defaults(self, tmp_path: Path):
        """Second tier: bundled defaults when project_root has no match."""
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        # No agents/ directory in tmp_path, should try bundled defaults
        # This may raise if bundled default also doesn't exist — that's fine
        # The point is it TRIES the fallback path
        try:
            tpl = compiler.load_template("scout")
            # If bundled default exists, template should load
            assert tpl is not None
        except FileNotFoundError:
            # Expected if no bundled default either — that's the test below
            pass

    def test_raises_when_not_found_anywhere(self, tmp_path: Path):
        """FileNotFoundError lists both search paths."""
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="nonexistent_role"):
            compiler.load_template("nonexistent_role")

    def test_no_project_root_uses_bundled_only(self):
        """With project_root=None, only bundled defaults are searched."""
        compiler = _prompt().PromptCompiler(project_root=None)
        with pytest.raises(FileNotFoundError):
            compiler.load_template("nonexistent_role")


# ===========================================================================
# 10. PromptCompiler.render_template — Jinja2
# ===========================================================================


class TestPromptCompilerRenderTemplate:
    """render_template: Jinja2 with StrictUndefined."""

    def test_renders_simple_variable(self):
        tpl = _prompt().PromptTemplate.from_string("Hello {{ name }}")
        compiler = _prompt().PromptCompiler()
        result = compiler.render_template(tpl, {"name": "World"})
        assert result == "Hello World"

    def test_renders_multiple_variables(self):
        tpl = _prompt().PromptTemplate.from_string("{{ role_name }}: {{ task }}")
        compiler = _prompt().PromptCompiler()
        result = compiler.render_template(tpl, {"role_name": "Scout", "task": "investigate"})
        assert result == "Scout: investigate"

    def test_strict_undefined_raises_on_missing(self):
        tpl = _prompt().PromptTemplate.from_string("Hello {{ missing_var }}")
        compiler = _prompt().PromptCompiler()
        with pytest.raises(Exception, match="missing_var"):
            compiler.render_template(tpl, {})

    def test_renders_conditional(self):
        template_str = "{% if urgent %}URGENT: {% endif %}{{ task }}"
        tpl = _prompt().PromptTemplate.from_string(template_str)
        compiler = _prompt().PromptCompiler()
        result = compiler.render_template(tpl, {"urgent": True, "task": "fix bug"})
        assert "URGENT:" in result

    def test_renders_for_loop(self):
        template_str = "{% for item in items %}{{ item }} {% endfor %}"
        tpl = _prompt().PromptTemplate.from_string(template_str)
        compiler = _prompt().PromptCompiler()
        result = compiler.render_template(tpl, {"items": ["a", "b", "c"]})
        assert "a" in result
        assert "b" in result
        assert "c" in result

    def test_renders_from_frontmatter_template(self):
        tpl = _prompt().PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        compiler = _prompt().PromptCompiler()
        result = compiler.render_template(tpl, {"role_name": "Scout Alpha", "task": "find bugs"})
        assert "Scout Alpha" in result
        assert "find bugs" in result


# ===========================================================================
# 11. PromptCompiler.compile — full pipeline
# ===========================================================================


class TestPromptCompilerCompile:
    """compile: truncate + order + join."""

    def test_joins_blocks_with_double_newline(self):
        blocks = [
            _make_block(name="a", content="First", priority=80),
            _make_block(name="b", content="Second", priority=60),
        ]
        compiler = _prompt().PromptCompiler(default_budget=10000)
        result = compiler.compile(blocks, positional_order=False)
        assert "First\n\nSecond" in result

    def test_uses_default_budget_when_none(self):
        blocks = [
            _make_block(name="big", content="x" * 40000, priority=50),
        ]
        compiler = _prompt().PromptCompiler(default_budget=8000)
        result = compiler.compile(blocks, budget=None)
        # With default budget of 8000, effective ~6800, big block should be truncated
        # 6800 tokens * 4 chars = 27200 chars max
        assert len(result) <= 27200

    def test_explicit_budget_overrides_default(self):
        blocks = [
            _make_block(name="x", content="x" * 800, priority=50),
        ]
        compiler = _prompt().PromptCompiler(default_budget=8000)
        result = compiler.compile(blocks, budget=50)
        # 50 token budget, effective ~42 tokens = 168 chars max
        assert len(result) <= 200

    def test_positional_order_true_reorders_u_shape(self):
        blocks = [
            _make_block(name="p100", content="high", priority=100),
            _make_block(name="p30", content="low", priority=30),
            _make_block(name="p80", content="mid", priority=80),
        ]
        compiler = _prompt().PromptCompiler(default_budget=10000)
        result = compiler.compile(blocks, positional_order=True)
        # U-shape: p100 first, p30 middle, p80 last
        idx_high = result.index("high")
        idx_low = result.index("low")
        idx_mid = result.index("mid")
        assert idx_high < idx_low < idx_mid

    def test_positional_order_false_preserves_original(self):
        blocks = [
            _make_block(name="first", content="AAA", priority=30),
            _make_block(name="second", content="BBB", priority=100),
            _make_block(name="third", content="CCC", priority=60),
        ]
        compiler = _prompt().PromptCompiler(default_budget=10000)
        result = compiler.compile(blocks, positional_order=False)
        assert result.index("AAA") < result.index("BBB") < result.index("CCC")

    def test_truncates_blocks_by_priority(self):
        blocks = [
            _make_block(name="keep", content="x" * 40, priority=100),
            _make_block(name="drop", content="x" * 40, priority=10),
        ]
        compiler = _prompt().PromptCompiler(default_budget=100)
        result = compiler.compile(blocks, budget=12)
        # Only ~12 tokens budget, one block's worth
        # "keep" should survive, "drop" should be gone
        # We can't check by content since both are "x"s,
        # but result should be short enough for one block
        assert len(result) <= 48  # 12 tokens * 4 chars

    def test_compile_empty_blocks(self):
        compiler = _prompt().PromptCompiler()
        result = compiler.compile([])
        assert result == ""


# ===========================================================================
# 12. PromptCompiler.guard_diff — diff size guard for Wizard reviews
# ===========================================================================


class TestGuardDiff:
    """guard_diff: truncate oversized diffs with summary header."""

    def test_small_diff_returned_unchanged(self):
        """A diff within max_lines is returned as-is."""
        compiler = _prompt().PromptCompiler()
        diff = "line1\nline2\nline3\n"
        result = compiler.guard_diff(diff, max_lines=5000)
        assert result == diff

    def test_exact_limit_returned_unchanged(self):
        """A diff exactly at max_lines is NOT truncated."""
        compiler = _prompt().PromptCompiler()
        lines = [f"line {i}" for i in range(100)]
        diff = "\n".join(lines)
        result = compiler.guard_diff(diff, max_lines=100)
        assert result == diff

    def test_oversized_diff_truncated(self):
        """A diff exceeding max_lines is truncated to max_lines."""
        compiler = _prompt().PromptCompiler()
        total = 200
        lines = [f"line {i}" for i in range(total)]
        diff = "\n".join(lines)
        result = compiler.guard_diff(diff, max_lines=50)
        # Result should have summary header + 50 lines of content
        result_lines = result.split("\n")
        # First line is summary header
        assert result_lines[0].startswith("[Diff truncated:")
        # Empty line separates header from content
        assert result_lines[1] == ""
        # Content is exactly max_lines lines
        content_lines = result_lines[2:]
        assert len(content_lines) == 50

    def test_summary_header_format(self):
        """Summary header includes total, shown, and dropped counts."""
        compiler = _prompt().PromptCompiler()
        total = 300
        max_lines = 100
        dropped = total - max_lines
        lines = [f"line {i}" for i in range(total)]
        diff = "\n".join(lines)
        result = compiler.guard_diff(diff, max_lines=max_lines)
        header = result.split("\n")[0]
        assert f"{total} total lines" in header
        assert f"showing first {max_lines}" in header
        assert f"{dropped} lines omitted" in header

    def test_default_max_lines_is_5000(self):
        """Default max_lines is 5000."""
        compiler = _prompt().PromptCompiler()
        lines = [f"line {i}" for i in range(5001)]
        diff = "\n".join(lines)
        result = compiler.guard_diff(diff)
        # Should be truncated since 5001 > 5000
        assert result.startswith("[Diff truncated:")

    def test_empty_diff_returned_unchanged(self):
        """Empty diff passes through."""
        compiler = _prompt().PromptCompiler()
        result = compiler.guard_diff("")
        assert result == ""

    def test_single_line_diff_returned_unchanged(self):
        """Single-line diff passes through."""
        compiler = _prompt().PromptCompiler()
        result = compiler.guard_diff("only line")
        assert result == "only line"

    def test_custom_max_lines(self):
        """Custom max_lines parameter is respected."""
        compiler = _prompt().PromptCompiler()
        lines = [f"line {i}" for i in range(20)]
        diff = "\n".join(lines)
        result = compiler.guard_diff(diff, max_lines=10)
        assert result.startswith("[Diff truncated:")
        content_lines = result.split("\n")[2:]
        assert len(content_lines) == 10


# ===========================================================================
# 13. Dependency constraints
# ===========================================================================


class TestDependencyConstraints:
    """prompt/ should only import from models/ and stdlib/jinja2."""

    def test_compiler_has_no_forbidden_imports(self):
        """compiler.py should not import from dispatch, engine, cli, etc."""
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
        """truncation.py should not import from dispatch, engine, cli, etc."""
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


# ===========================================================================
# 14. IdentityBlock — valid parsing (renamed from AxiomMeta)
# ===========================================================================


class TestIdentityBlockValid:
    """IdentityBlock parses valid frontmatter correctly."""

    def test_valid_frontmatter_parses(self):
        """A complete valid frontmatter dict creates an IdentityBlock."""
        meta = _prompt().IdentityBlock(**VALID_FRONTMATTER)
        assert meta.role == "scout"
        assert meta.version == "1.0.0"
        assert meta.truncation_priority == 100
        assert meta.cognitive_pattern == "observe"
        assert meta.output_contract["format"] == "structured"
        assert "terrain_map" in meta.output_contract["required_sections"]

    def test_role_is_string(self):
        """role field is a string."""
        meta = _prompt().IdentityBlock(**VALID_FRONTMATTER)
        assert isinstance(meta.role, str)

    def test_version_is_string(self):
        """version field is a string."""
        meta = _prompt().IdentityBlock(**VALID_FRONTMATTER)
        assert isinstance(meta.version, str)

    def test_truncation_priority_is_int(self):
        """truncation_priority field is an int."""
        meta = _prompt().IdentityBlock(**VALID_FRONTMATTER)
        assert isinstance(meta.truncation_priority, int)

    def test_output_contract_has_format(self):
        """output_contract contains a 'format' string."""
        meta = _prompt().IdentityBlock(**VALID_FRONTMATTER)
        assert isinstance(meta.output_contract["format"], str)

    def test_output_contract_has_required_sections(self):
        """output_contract contains a 'required_sections' list of strings."""
        meta = _prompt().IdentityBlock(**VALID_FRONTMATTER)
        sections = meta.output_contract["required_sections"]
        assert isinstance(sections, list)
        assert all(isinstance(s, str) for s in sections)

    @pytest.mark.parametrize("pattern", sorted(VALID_COGNITIVE_PATTERNS))
    def test_all_valid_cognitive_patterns_accepted(self, pattern: str):
        """Each allowed cognitive_pattern value parses without error."""
        data = {**VALID_FRONTMATTER, "cognitive_pattern": pattern}
        meta = _prompt().IdentityBlock(**data)
        assert meta.cognitive_pattern == pattern


# ===========================================================================
# 15. IdentityBlock — validation failures
# ===========================================================================


class TestIdentityBlockInvalid:
    """IdentityBlock rejects invalid frontmatter."""

    def test_missing_role_raises(self):
        """Omitting 'role' raises ValidationError."""
        data = {k: v for k, v in VALID_FRONTMATTER.items() if k != "role"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock(**data)

    def test_missing_version_raises(self):
        """Omitting 'version' raises ValidationError."""
        data = {k: v for k, v in VALID_FRONTMATTER.items() if k != "version"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock(**data)

    def test_missing_truncation_priority_raises(self):
        """Omitting 'truncation_priority' raises ValidationError."""
        data = {k: v for k, v in VALID_FRONTMATTER.items() if k != "truncation_priority"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock(**data)

    def test_missing_cognitive_pattern_raises(self):
        """Omitting 'cognitive_pattern' raises ValidationError."""
        data = {k: v for k, v in VALID_FRONTMATTER.items() if k != "cognitive_pattern"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock(**data)

    def test_missing_output_contract_raises(self):
        """Omitting 'output_contract' raises ValidationError."""
        data = {k: v for k, v in VALID_FRONTMATTER.items() if k != "output_contract"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock(**data)

    def test_invalid_cognitive_pattern_raises(self):
        """A cognitive_pattern not in the allowed set raises ValidationError."""
        data = {**VALID_FRONTMATTER, "cognitive_pattern": "meditate"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock(**data)

    def test_truncation_priority_zero_raises(self):
        """truncation_priority of 0 raises ValidationError (must be > 0)."""
        data = {**VALID_FRONTMATTER, "truncation_priority": 0}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock(**data)

    def test_truncation_priority_negative_raises(self):
        """truncation_priority of -1 raises ValidationError (must be > 0)."""
        data = {**VALID_FRONTMATTER, "truncation_priority": -1}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock(**data)


# ===========================================================================
# 16. AxiomLoaded event
# ===========================================================================


class TestAxiomLoadedEvent:
    """AxiomLoaded event follows BonfireEvent conventions."""

    def _make_event(self, **overrides: Any) -> Any:
        defaults = {
            "session_id": "test-session-001",
            "sequence": 1,
            "role": "scout",
            "axiom_version": "1.0.0",
            "cognitive_pattern": "observe",
        }
        defaults.update(overrides)
        return _events().AxiomLoaded(**defaults)

    def test_event_type_is_axiom_loaded(self):
        """event_type is the literal 'axiom.loaded'."""
        event = self._make_event()
        assert event.event_type == "axiom.loaded"

    def test_has_role_field(self):
        """AxiomLoaded carries the role string."""
        event = self._make_event(role="knight")
        assert event.role == "knight"

    def test_has_axiom_version_field(self):
        """AxiomLoaded carries the axiom version."""
        event = self._make_event(axiom_version="2.0.0")
        assert event.axiom_version == "2.0.0"

    def test_has_cognitive_pattern_field(self):
        """AxiomLoaded carries the cognitive pattern."""
        event = self._make_event(cognitive_pattern="contract")
        assert event.cognitive_pattern == "contract"

    def test_is_bonfire_event_subclass(self):
        """AxiomLoaded inherits from BonfireEvent."""
        event = self._make_event()
        assert isinstance(event, _events().BonfireEvent)

    def test_has_session_id(self):
        """Inherited session_id from BonfireEvent."""
        event = self._make_event(session_id="abc-123")
        assert event.session_id == "abc-123"

    def test_has_sequence(self):
        """Inherited sequence from BonfireEvent."""
        event = self._make_event(sequence=42)
        assert event.sequence == 42

    def test_has_event_id(self):
        """Inherited auto-generated event_id from BonfireEvent."""
        event = self._make_event()
        assert event.event_id is not None
        assert len(event.event_id) == 12

    def test_has_timestamp(self):
        """Inherited auto-generated timestamp from BonfireEvent."""
        event = self._make_event()
        assert event.timestamp > 0

    def test_is_frozen(self):
        """AxiomLoaded is immutable (frozen model)."""
        event = self._make_event()
        with pytest.raises(ValidationError):
            event.role = "warrior"


# ===========================================================================
# 17. Integration — load_axiom_validated
# ===========================================================================


class TestLoadAxiomValidated:
    """PromptCompiler.load_axiom_validated returns validated (template, meta) tuples.

    These tests synthesise role axioms under tmp_path rather than relying on
    bundled defaults, so they exercise the compiler integration independently
    of real template files shipped with the package.
    """

    def test_returns_tuple(self, tmp_path: Path):
        """load_axiom_validated returns a (PromptTemplate, IdentityBlock) tuple."""
        _write_axiom(tmp_path, "scout")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        result = compiler.load_axiom_validated("scout")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_first_element_is_prompt_template(self, tmp_path: Path):
        """First element of the tuple is a PromptTemplate."""
        _write_axiom(tmp_path, "scout")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        template, _ = compiler.load_axiom_validated("scout")
        assert isinstance(template, _prompt().PromptTemplate)

    def test_second_element_is_identity_block(self, tmp_path: Path):
        """Second element of the tuple is an IdentityBlock."""
        _write_axiom(tmp_path, "scout")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        _, meta = compiler.load_axiom_validated("scout")
        assert isinstance(meta, _prompt().IdentityBlock)

    def test_meta_matches_frontmatter(self, tmp_path: Path):
        """IdentityBlock fields match the parsed frontmatter values."""
        _write_axiom(tmp_path, "scout")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        template, meta = compiler.load_axiom_validated("scout")
        assert meta.role == template.frontmatter["role"]
        assert meta.version == template.frontmatter["version"]
        assert meta.truncation_priority == template.frontmatter["truncation_priority"]
        assert meta.cognitive_pattern == template.frontmatter["cognitive_pattern"]

    def test_invalid_axiom_raises_valueerror(self, tmp_path: Path):
        """An axiom with invalid frontmatter raises ValueError."""
        # Create a malformed axiom file (missing version, priority)
        agent_dir = tmp_path / "agents" / "bad_agent"
        agent_dir.mkdir(parents=True)
        axiom_file = agent_dir / "axiom.md"
        axiom_file.write_text("---\nrole: bad_agent\n---\n# Bad Axiom\nNo version, no priority.\n")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        with pytest.raises(ValueError, match="bad_agent"):
            compiler.load_axiom_validated("bad_agent")

    def test_missing_role_axiom_raises_valueerror(self, tmp_path: Path):
        """A role with no axiom file raises ValueError from load_axiom_validated."""
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        with pytest.raises(ValueError):
            compiler.load_axiom_validated("nonexistent_role")
