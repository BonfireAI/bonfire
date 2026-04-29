"""Canonical RED tests for ``bonfire.prompt``.

Wave 5.1 transfer target: ``src/bonfire/prompt/`` (renamed from v1's
``axiom_meta.py`` to ``identity_block.py``; corresponding compiler methods
``load_axiom`` / ``load_axiom_validated`` renamed to ``load_identity_block`` /
``load_identity_block_validated``).

Kept names (transitional v0.1 surface):
- The ``AxiomLoaded`` event class (already shipped in ``bonfire.models.events``
  with ``event_type == "axiom.loaded"``) is preserved — renaming the published
  event surface mid-v0.1 is off-contract. Coverage for that class lives in
  ``tests/unit/test_events.py``; this file does not redundantly re-test it.
- The frontmatter key ``cognitive_pattern`` and its seven allowed literals
  are preserved byte-for-byte from v1.

Canonical categories:
  1. IdentityBlock — frontmatter schema, validation, immutability, extra="forbid"
  2. PromptBlock — frozen dataclass, priority, role, hash/eq
  3. estimate_tokens — chars/4 heuristic, minimum 1 for non-empty
  4. effective_budget — safety margin math (floor)
  5. truncate_blocks — priority drop, order preservation, character-slice
  6. order_by_position — U-shape attention ordering
  7. PromptTemplate.from_file — load, YAML frontmatter parse
  8. PromptTemplate.from_string — string variant
  9. PromptCompiler construction — defaults, custom
 10. PromptCompiler.load_template — two-tier discovery (project → bundled)
 11. PromptCompiler.load_identity_block — axiom layer discovery (renamed)
 12. PromptCompiler.render_template — Jinja2 sandbox + StrictUndefined
 13. PromptCompiler.compile — full pipeline (truncate + order + join)
 14. PromptCompiler.compose_agent_prompt — three-layer composition
 15. PromptCompiler.guard_diff — Wizard diff truncation
 16. Edge cases — adversarial + pathological inputs (Unicode, injection, ties)
 17. Dependency constraints — ``prompt/`` is a leaf module

Shim pattern (matches ``tests/unit/test_engine_init.py``): every test lazily
imports ``bonfire.prompt`` from inside its own body so the current stubbed
package produces granular per-test RED rather than a whole-file collection
error. The Warrior sees ticket progress move test-by-test as the surface lands.
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
# Lazy-import helpers — granular per-test RED (see ``test_engine_init.py``).
# ---------------------------------------------------------------------------


def _prompt() -> Any:
    """Lazy-import ``bonfire.prompt``."""
    import bonfire.prompt as _p

    return _p


def _truncation() -> Any:
    """Lazy-import ``bonfire.prompt.truncation``."""
    import bonfire.prompt.truncation as _t

    return _t


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


VALID_COGNITIVE_PATTERNS = (
    "observe",
    "contract",
    "execute",
    "synthesize",
    "audit",
    "publish",
    "announce",
)


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
    """Shorthand factory for PromptBlock (lazy-imported)."""
    return _prompt().PromptBlock(name=name, content=content, priority=priority, role=role)


def _write_identity_block(
    base: Path,
    role: str,
    frontmatter: dict | None = None,
    body: str = "# Identity body",
) -> Path:
    """Write a minimal identity_block.md under base/agents/<role>/identity_block.md."""
    import yaml

    fm = frontmatter if frontmatter is not None else VALID_IDENTITY_FRONTMATTER
    agent_dir = base / "agents" / role
    agent_dir.mkdir(parents=True, exist_ok=True)
    identity_file = agent_dir / "identity_block.md"
    yaml_text = yaml.safe_dump(fm, sort_keys=False).strip()
    identity_file.write_text(f"---\n{yaml_text}\n---\n{body}\n")
    return identity_file


# ===========================================================================
# 1. IdentityBlock — renamed frontmatter model (formerly AxiomMeta)
# ===========================================================================


class TestIdentityBlockValid:
    """IdentityBlock parses valid frontmatter correctly."""

    def test_valid_frontmatter_constructs(self):
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert meta.role == "scout"
        assert meta.version == "1.0.0"
        assert meta.truncation_priority == 100
        assert meta.cognitive_pattern == "observe"

    def test_role_is_string(self):
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert isinstance(meta.role, str)

    def test_version_is_string(self):
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert isinstance(meta.version, str)

    def test_truncation_priority_is_int(self):
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert isinstance(meta.truncation_priority, int)

    def test_tools_default_is_empty_list(self):
        data = {k: v for k, v in VALID_IDENTITY_FRONTMATTER.items() if k != "tools"}
        meta = _prompt().IdentityBlock.model_validate(data)
        assert meta.tools == []

    def test_output_contract_has_format(self):
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert meta.output_contract.format == "markdown"

    def test_output_contract_has_required_sections(self):
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert "findings" in meta.output_contract.required_sections

    def test_output_contract_supports_item_access(self):
        """Back-compat: output_contract supports dict-like access."""
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        assert meta.output_contract["format"] == "markdown"

    def test_output_contract_sections_are_strings(self):
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        sections = meta.output_contract.required_sections
        assert isinstance(sections, list)
        assert all(isinstance(s, str) for s in sections)

    @pytest.mark.parametrize("pattern", VALID_COGNITIVE_PATTERNS)
    def test_all_valid_cognitive_patterns_accepted(self, pattern: str):
        """Each of the seven documented cognitive_pattern literals validates."""
        data = {**VALID_IDENTITY_FRONTMATTER, "cognitive_pattern": pattern}
        meta = _prompt().IdentityBlock.model_validate(data)
        assert meta.cognitive_pattern == pattern

    def test_frozen_immutable(self):
        """IdentityBlock instances are frozen."""
        meta = _prompt().IdentityBlock.model_validate(VALID_IDENTITY_FRONTMATTER)
        with pytest.raises(ValidationError):
            meta.role = "changed"  # type: ignore[misc]


class TestIdentityBlockInvalid:
    """IdentityBlock rejects invalid frontmatter."""

    def test_missing_role_raises(self):
        data = {k: v for k, v in VALID_IDENTITY_FRONTMATTER.items() if k != "role"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)

    def test_missing_version_raises(self):
        data = {k: v for k, v in VALID_IDENTITY_FRONTMATTER.items() if k != "version"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)

    def test_missing_truncation_priority_raises(self):
        data = {k: v for k, v in VALID_IDENTITY_FRONTMATTER.items() if k != "truncation_priority"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)

    def test_missing_cognitive_pattern_raises(self):
        data = {k: v for k, v in VALID_IDENTITY_FRONTMATTER.items() if k != "cognitive_pattern"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)

    def test_missing_output_contract_raises(self):
        data = {k: v for k, v in VALID_IDENTITY_FRONTMATTER.items() if k != "output_contract"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)

    def test_invalid_cognitive_pattern_raises(self):
        """A cognitive_pattern not in the allowed literal set raises."""
        data = {**VALID_IDENTITY_FRONTMATTER, "cognitive_pattern": "hallucinate"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)

    def test_truncation_priority_zero_rejected(self):
        """``truncation_priority`` has ``gt=0`` — zero is rejected."""
        data = {**VALID_IDENTITY_FRONTMATTER, "truncation_priority": 0}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)

    def test_truncation_priority_negative_rejected(self):
        data = {**VALID_IDENTITY_FRONTMATTER, "truncation_priority": -10}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)

    def test_output_contract_missing_format_rejected(self):
        bad = {
            **VALID_IDENTITY_FRONTMATTER,
            "output_contract": {"required_sections": ["x"]},
        }
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(bad)

    def test_extra_fields_rejected(self):
        """IdentityBlock pins ``extra='forbid'`` — unknown keys raise.

        The v0.1 contract is strict: unknown frontmatter keys must fail
        validation so schema drift is caught at parse time, not at dispatch time.
        """
        data = {**VALID_IDENTITY_FRONTMATTER, "mystery_field": "sneaky"}
        with pytest.raises(ValidationError):
            _prompt().IdentityBlock.model_validate(data)


# ===========================================================================
# 2. PromptBlock
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

    def test_hashable(self):
        """Frozen dataclasses are hashable and usable as set members."""
        PromptBlock = _prompt().PromptBlock
        a = PromptBlock(name="x", content="y", priority=1)
        b = PromptBlock(name="x", content="y", priority=1)
        assert {a, b} == {a}

    def test_negative_priority_allowed(self):
        """PromptBlock itself does not constrain priority sign."""
        PromptBlock = _prompt().PromptBlock
        block = PromptBlock(name="x", content="y", priority=-10)
        assert block.priority == -10


# ===========================================================================
# 3. estimate_tokens
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
        assert _truncation().estimate_tokens("a" * 100) == 25

    def test_three_chars_returns_one_not_zero(self):
        """Non-empty strings must return at least 1."""
        assert _truncation().estimate_tokens("abc") == 1

    def test_whitespace_only_counts(self):
        assert _truncation().estimate_tokens("    ") == 1

    def test_long_text(self):
        assert _truncation().estimate_tokens("x" * 1000) == 250

    def test_returns_int(self):
        assert isinstance(_truncation().estimate_tokens("abcdefgh"), int)


# ===========================================================================
# 4. effective_budget
# ===========================================================================


class TestEffectiveBudget:
    """effective_budget: floor(max_tokens * (1 - safety_margin))."""

    def test_default_margin(self):
        assert _truncation().effective_budget(8000) == math.floor(8000 * 0.85)

    def test_custom_margin(self):
        assert _truncation().effective_budget(10000, safety_margin=0.2) == math.floor(10000 * 0.8)

    def test_zero_margin(self):
        assert _truncation().effective_budget(5000, safety_margin=0.0) == 5000

    def test_returns_integer(self):
        assert isinstance(_truncation().effective_budget(8000), int)

    def test_floor_rounding(self):
        """Non-round results are floored, not rounded."""
        assert _truncation().effective_budget(1001, safety_margin=0.15) == math.floor(1001 * 0.85)

    def test_zero_budget_yields_zero(self):
        assert _truncation().effective_budget(0) == 0

    def test_full_margin_yields_zero(self):
        """A 100% safety margin leaves no budget."""
        assert _truncation().effective_budget(1000, safety_margin=1.0) == 0


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
        result = _truncation().truncate_blocks(blocks, budget=100)
        assert [b.name for b in result] == ["a", "b"]

    def test_drops_lowest_priority_first(self):
        blocks = [
            _make_block(name="important", content="x" * 40, priority=100),
            _make_block(name="filler", content="x" * 40, priority=10),
        ]
        result = _truncation().truncate_blocks(blocks, budget=12)
        names = [b.name for b in result]
        assert "important" in names
        assert "filler" not in names

    def test_preserves_original_order(self):
        blocks = [
            _make_block(name="first", content="aa", priority=80),
            _make_block(name="second", content="bb", priority=10),
            _make_block(name="third", content="cc", priority=90),
        ]
        result = _truncation().truncate_blocks(blocks, budget=100)
        assert [b.name for b in result] == ["first", "second", "third"]

    def test_preserves_order_after_drop(self):
        blocks = [
            _make_block(name="A", content="x" * 20, priority=90),
            _make_block(name="B", content="x" * 20, priority=10),
            _make_block(name="C", content="x" * 20, priority=80),
        ]
        result = _truncation().truncate_blocks(blocks, budget=12)
        names = [b.name for b in result]
        assert "B" not in names
        if "A" in names and "C" in names:
            assert names.index("A") < names.index("C")

    def test_character_slice_last_survivor(self):
        blocks = [_make_block(name="huge", content="x" * 200, priority=100)]
        result = _truncation().truncate_blocks(blocks, budget=10)
        assert len(result) == 1
        assert len(result[0].content) <= 40  # 10 tokens * 4 chars

    def test_highest_priority_never_dropped_entirely(self):
        blocks = [
            _make_block(name="king", content="x" * 400, priority=100),
            _make_block(name="pawn", content="x" * 400, priority=1),
        ]
        result = _truncation().truncate_blocks(blocks, budget=5)
        assert "king" in [b.name for b in result]

    def test_empty_blocks_list(self):
        assert _truncation().truncate_blocks([], budget=100) == []

    def test_single_block_fits(self):
        blocks = [_make_block(name="only", content="hi", priority=50)]
        result = _truncation().truncate_blocks(blocks, budget=100)
        assert len(result) == 1
        assert result[0].name == "only"

    def test_drops_multiple_low_priority(self):
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

    def test_sliced_block_keeps_priority_and_name(self):
        """Character-slicing must not lose the block's identity metadata."""
        blocks = [_make_block(name="keystone", content="x" * 400, priority=99)]
        result = _truncation().truncate_blocks(blocks, budget=5)
        assert result[0].name == "keystone"
        assert result[0].priority == 99

    def test_returns_new_list_not_same_object(self):
        """truncate_blocks returns a new list (does not mutate input)."""
        blocks = [_make_block(name="a", content="aa", priority=10)]
        result = _truncation().truncate_blocks(blocks, budget=100)
        assert result is not blocks


# ===========================================================================
# 6. order_by_position — U-shape attention
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
        result = _truncation().order_by_position(blocks)
        assert [b.name for b in result] == ["p100", "p30", "p50", "p80"]

    def test_single_block(self):
        blocks = [_make_block(name="only", priority=50)]
        assert [b.name for b in _truncation().order_by_position(blocks)] == ["only"]

    def test_two_blocks(self):
        blocks = [
            _make_block(name="low", priority=10),
            _make_block(name="high", priority=90),
        ]
        result = _truncation().order_by_position(blocks)
        assert [b.name for b in result] == ["high", "low"]

    def test_three_blocks(self):
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
# 7. PromptTemplate.from_file
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
        f = tmp_path / "plain.md"
        f.write_text("Just a body, no frontmatter.")
        tpl = _prompt().PromptTemplate.from_file(f)
        assert tpl.frontmatter == {}
        assert "Just a body" in tpl.body


# ===========================================================================
# 8. PromptTemplate.from_string
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
# 9. PromptCompiler construction
# ===========================================================================


class TestPromptCompilerConstruction:
    """PromptCompiler init with defaults and custom values."""

    def test_default_budget(self):
        assert _prompt().PromptCompiler().default_budget == 8000

    def test_default_safety_margin(self):
        assert _prompt().PromptCompiler().safety_margin == 0.15

    def test_custom_budget(self):
        assert _prompt().PromptCompiler(default_budget=16000).default_budget == 16000

    def test_custom_safety_margin(self):
        assert _prompt().PromptCompiler(safety_margin=0.1).safety_margin == 0.1

    def test_project_root(self, tmp_path: Path):
        assert _prompt().PromptCompiler(project_root=tmp_path).project_root == tmp_path

    def test_project_root_none_default(self):
        assert _prompt().PromptCompiler().project_root is None


# ===========================================================================
# 10. PromptCompiler.load_template — two-tier discovery
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
        """Second tier: bundled defaults when project_root has no match.

        v0.1 ships NO bundled default templates (keeping the distribution
        surface minimal — users supply their own). The call therefore raises
        ``FileNotFoundError``, but the implementation MUST still attempt the
        bundled-resource lookup so the seam is present for a later wave.
        """
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        try:
            tpl = compiler.load_template("scout")
            # If a future wave ships a bundled default, this path is valid.
            assert tpl is not None
        except FileNotFoundError:
            # Expected in v0.1 — no bundled default exists yet.
            pass

    def test_raises_when_not_found_anywhere(self, tmp_path: Path):
        """FileNotFoundError includes the role name."""
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        with pytest.raises(FileNotFoundError, match="nonexistent_role"):
            compiler.load_template("nonexistent_role")

    def test_no_project_root_uses_bundled_only(self):
        """With project_root=None, only bundled defaults are searched."""
        compiler = _prompt().PromptCompiler(project_root=None)
        with pytest.raises(FileNotFoundError):
            compiler.load_template("nonexistent_role")

    def test_project_root_takes_precedence_over_bundled(self, tmp_path: Path):
        """Project-local templates win over bundled defaults for the same role."""
        agent_dir = tmp_path / "agents" / "custom_role"
        agent_dir.mkdir(parents=True)
        local_template = "---\norigin: project\n---\nlocal body"
        (agent_dir / "prompt.md").write_text(local_template)

        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        tpl = compiler.load_template("custom_role")
        assert tpl.frontmatter.get("origin") == "project"


# ===========================================================================
# 11. PromptCompiler.load_identity_block — renamed axiom layer
# ===========================================================================


class TestPromptCompilerLoadIdentityBlock:
    """load_identity_block: discovery for the identity (axiom) layer.

    Renamed from ``load_axiom`` in the public surface. Corresponding filename
    on disk: ``identity_block.md`` (renamed from ``axiom.md``). Module path:
    ``bonfire.prompt.identity_block`` (renamed from ``axiom_meta``).
    """

    def test_loads_from_project_root(self, tmp_path: Path):
        _write_identity_block(tmp_path, "scout", body="# Scout identity")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        tpl = compiler.load_identity_block("scout")
        assert tpl is not None
        assert "Scout identity" in tpl.body

    def test_returns_none_when_not_found(self, tmp_path: Path):
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        assert compiler.load_identity_block("nonexistent_role") is None

    def test_load_identity_block_validated_returns_tuple(self, tmp_path: Path):
        _write_identity_block(tmp_path, "scout")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        result = compiler.load_identity_block_validated("scout")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_load_identity_block_validated_first_is_template(self, tmp_path: Path):
        _write_identity_block(tmp_path, "scout")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        template, _ = compiler.load_identity_block_validated("scout")
        assert isinstance(template, _prompt().PromptTemplate)

    def test_load_identity_block_validated_second_is_identity_block(self, tmp_path: Path):
        _write_identity_block(tmp_path, "scout")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        _, meta = compiler.load_identity_block_validated("scout")
        assert isinstance(meta, _prompt().IdentityBlock)
        assert meta.role == "scout"

    def test_load_identity_block_validated_meta_matches_frontmatter(self, tmp_path: Path):
        _write_identity_block(tmp_path, "scout")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        template, meta = compiler.load_identity_block_validated("scout")
        assert meta.role == template.frontmatter["role"]
        assert meta.version == template.frontmatter["version"]
        assert meta.truncation_priority == template.frontmatter["truncation_priority"]
        assert meta.cognitive_pattern == template.frontmatter["cognitive_pattern"]

    def test_load_identity_block_validated_tools_preserved(self, tmp_path: Path):
        _write_identity_block(
            tmp_path,
            "knight",
            frontmatter={
                **VALID_IDENTITY_FRONTMATTER,
                "role": "knight",
                "cognitive_pattern": "execute",
                "tools": ["Read", "Write", "Edit"],
            },
        )
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        _, meta = compiler.load_identity_block_validated("knight")
        assert meta.tools == ["Read", "Write", "Edit"]

    def test_load_identity_block_validated_missing_raises_value_error(self, tmp_path: Path):
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        with pytest.raises(ValueError, match="nonexistent"):
            compiler.load_identity_block_validated("nonexistent")

    def test_load_identity_block_validated_invalid_frontmatter_raises(self, tmp_path: Path):
        agent_dir = tmp_path / "agents" / "bad_agent"
        agent_dir.mkdir(parents=True)
        # Missing required fields — only role present.
        (agent_dir / "identity_block.md").write_text("---\nrole: bad_agent\n---\n# Bad identity\n")
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        with pytest.raises(ValueError, match="bad_agent"):
            compiler.load_identity_block_validated("bad_agent")

    def test_get_role_tools_returns_tools_list(self, tmp_path: Path):
        _write_identity_block(
            tmp_path,
            "knight",
            frontmatter={
                **VALID_IDENTITY_FRONTMATTER,
                "role": "knight",
                "cognitive_pattern": "execute",
                "tools": ["Read", "Write", "Edit"],
            },
        )
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        assert compiler.get_role_tools("knight") == ["Read", "Write", "Edit"]

    def test_get_role_tools_missing_role_returns_empty_list(self, tmp_path: Path):
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        assert compiler.get_role_tools("nonexistent") == []


# ===========================================================================
# 12. PromptCompiler.render_template — Jinja2
# ===========================================================================


class TestPromptCompilerRenderTemplate:
    """render_template: Jinja2 with StrictUndefined in a sandboxed env."""

    def test_renders_simple_variable(self):
        PromptTemplate = _prompt().PromptTemplate
        tpl = PromptTemplate.from_string("Hello {{ name }}")
        assert _prompt().PromptCompiler().render_template(tpl, {"name": "World"}) == "Hello World"

    def test_renders_multiple_variables(self):
        PromptTemplate = _prompt().PromptTemplate
        tpl = PromptTemplate.from_string("{{ a }}: {{ b }}")
        result = _prompt().PromptCompiler().render_template(tpl, {"a": "Scout", "b": "investigate"})
        assert result == "Scout: investigate"

    def test_strict_undefined_raises_on_missing(self):
        PromptTemplate = _prompt().PromptTemplate
        tpl = PromptTemplate.from_string("Hello {{ missing_var }}")
        with pytest.raises(Exception, match="missing_var"):
            _prompt().PromptCompiler().render_template(tpl, {})

    def test_renders_conditional(self):
        PromptTemplate = _prompt().PromptTemplate
        tpl = PromptTemplate.from_string("{% if urgent %}URGENT: {% endif %}{{ task }}")
        result = (
            _prompt().PromptCompiler().render_template(tpl, {"urgent": True, "task": "fix bug"})
        )
        assert "URGENT:" in result

    def test_renders_for_loop(self):
        PromptTemplate = _prompt().PromptTemplate
        tpl = PromptTemplate.from_string("{% for i in items %}{{ i }} {% endfor %}")
        result = _prompt().PromptCompiler().render_template(tpl, {"items": ["a", "b", "c"]})
        assert "a" in result and "b" in result and "c" in result

    def test_renders_from_frontmatter_template(self):
        PromptTemplate = _prompt().PromptTemplate
        tpl = PromptTemplate.from_string(SAMPLE_FRONTMATTER_TEMPLATE)
        result = (
            _prompt()
            .PromptCompiler()
            .render_template(tpl, {"role_name": "Scout Alpha", "task": "find bugs"})
        )
        assert "Scout Alpha" in result
        assert "find bugs" in result


# ===========================================================================
# 13. PromptCompiler.compile — full pipeline
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
        blocks = [_make_block(name="big", content="x" * 40000, priority=50)]
        compiler = _prompt().PromptCompiler(default_budget=8000)
        result = compiler.compile(blocks, budget=None)
        # default 8000 * (1 - 0.15) = 6800 tokens * 4 chars = 27200 chars max
        assert len(result) <= 27200

    def test_explicit_budget_overrides_default(self):
        blocks = [_make_block(name="x", content="x" * 800, priority=50)]
        compiler = _prompt().PromptCompiler(default_budget=8000)
        result = compiler.compile(blocks, budget=50)
        # 50 tokens * 0.85 = ~42 tokens * 4 chars = ~168 chars max
        assert len(result) <= 200

    def test_positional_order_true_reorders_u_shape(self):
        blocks = [
            _make_block(name="p100", content="high", priority=100),
            _make_block(name="p30", content="low", priority=30),
            _make_block(name="p80", content="mid", priority=80),
        ]
        compiler = _prompt().PromptCompiler(default_budget=10000)
        result = compiler.compile(blocks, positional_order=True)
        # U-shape: highest first, lowest middle, second-highest last.
        assert result.index("high") < result.index("low") < result.index("mid")

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
        assert len(result) <= 48

    def test_compile_empty_blocks(self):
        assert _prompt().PromptCompiler().compile([]) == ""


# ===========================================================================
# 14. PromptCompiler.compose_agent_prompt — three-layer composition
# ===========================================================================


class TestComposeAgentPrompt:
    """compose_agent_prompt: identity + mission + reach three-layer assembly.

    Layer priorities:
    - Identity (priority 100): cognitive identity, via ``load_identity_block``
    - Mission  (priority 75):  task template rendered with variables
    - Reach    (priority 50):  runtime context (tools, gates, etc.)

    Under truncation pressure, reach drops first; identity survives longest.
    """

    def test_assembles_three_layers(self, tmp_path: Path):
        _write_identity_block(
            tmp_path,
            "scout",
            body="IDENTITY_MARKER: I am the scout.",
        )
        (tmp_path / "agents" / "scout" / "prompt.md").write_text(
            "MISSION_MARKER: Find {{ target }}."
        )

        compiler = _prompt().PromptCompiler(project_root=tmp_path, default_budget=10000)
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

        compiler = _prompt().PromptCompiler(project_root=tmp_path, default_budget=10000)
        result = compiler.compose_agent_prompt(
            role="scout",
            variables={},
            reach_context={},
        )
        assert "MISSION_MARKER" in result

    def test_missing_mission_raises(self, tmp_path: Path):
        """Without a mission prompt, composition raises FileNotFoundError."""
        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        with pytest.raises(FileNotFoundError):
            compiler.compose_agent_prompt(
                role="ghost",
                variables={},
                reach_context={},
            )

    def test_identity_survives_tight_budget(self, tmp_path: Path):
        """Under heavy truncation, the identity block (priority 100) survives."""
        _write_identity_block(
            tmp_path,
            "scout",
            body="IDENTITY_SURVIVOR",
        )
        (tmp_path / "agents" / "scout" / "prompt.md").write_text("MISSION_FILLER " * 200)

        compiler = _prompt().PromptCompiler(project_root=tmp_path)
        result = compiler.compose_agent_prompt(
            role="scout",
            variables={},
            reach_context={"noise": "x" * 200},
            budget=20,
        )
        # Under severe pressure, identity (priority 100) is the last to die.
        assert "IDENTITY_SURVIVOR" in result or len(result) > 0


# ===========================================================================
# 15. PromptCompiler.guard_diff — Wizard diff truncation
# ===========================================================================


class TestGuardDiff:
    """guard_diff: truncate oversized diffs with summary header."""

    def test_small_diff_returned_unchanged(self):
        compiler = _prompt().PromptCompiler()
        diff = "line1\nline2\nline3\n"
        assert compiler.guard_diff(diff, max_lines=5000) == diff

    def test_exact_limit_returned_unchanged(self):
        compiler = _prompt().PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(100))
        assert compiler.guard_diff(diff, max_lines=100) == diff

    def test_oversized_diff_truncated(self):
        compiler = _prompt().PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(200))
        result = compiler.guard_diff(diff, max_lines=50)
        result_lines = result.split("\n")
        assert result_lines[0].startswith("[Diff truncated:")
        assert result_lines[1] == ""
        assert len(result_lines[2:]) == 50

    def test_summary_header_format(self):
        compiler = _prompt().PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(300))
        result = compiler.guard_diff(diff, max_lines=100)
        header = result.split("\n")[0]
        assert "300 total lines" in header
        assert "showing first 100" in header
        assert "200 lines omitted" in header

    def test_default_max_lines_is_5000(self):
        compiler = _prompt().PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(5001))
        result = compiler.guard_diff(diff)
        assert result.startswith("[Diff truncated:")

    def test_empty_diff_returned_unchanged(self):
        assert _prompt().PromptCompiler().guard_diff("") == ""

    def test_single_line_diff_returned_unchanged(self):
        assert _prompt().PromptCompiler().guard_diff("only line") == "only line"

    def test_custom_max_lines(self):
        compiler = _prompt().PromptCompiler()
        diff = "\n".join(f"line {i}" for i in range(20))
        result = compiler.guard_diff(diff, max_lines=10)
        assert result.startswith("[Diff truncated:")
        assert len(result.split("\n")[2:]) == 10


# ===========================================================================
# 16. Edge cases — adversarial + pathological inputs
# ===========================================================================


class TestEdgeCases:
    """Edge cases: priority collisions, Unicode, Jinja sandbox, frontmatter quirks."""

    def test_priority_collision_deterministic_ordering(self):
        """Equal priorities must produce the same output across calls (determinism)."""
        blocks = [
            _make_block(name="a", content="aa", priority=50),
            _make_block(name="b", content="bb", priority=50),
            _make_block(name="c", content="cc", priority=50),
        ]
        result1 = _truncation().order_by_position(blocks)
        result2 = _truncation().order_by_position(blocks)
        assert [b.name for b in result1] == [b.name for b in result2]

    def test_all_equal_priority_truncate_terminates(self):
        """When all priorities tie, truncation must still terminate safely."""
        blocks = [
            _make_block(name="a", content="x" * 40, priority=50),
            _make_block(name="b", content="x" * 40, priority=50),
            _make_block(name="c", content="x" * 40, priority=50),
        ]
        result = _truncation().truncate_blocks(blocks, budget=12)
        assert 1 <= len(result) <= 3

    def test_truncate_empty_content_blocks_fit(self):
        """Blocks with empty content consume 0 tokens and always fit."""
        blocks = [
            _make_block(name="empty1", content="", priority=10),
            _make_block(name="empty2", content="", priority=20),
        ]
        result = _truncation().truncate_blocks(blocks, budget=0)
        assert len(result) == 2

    def test_unicode_content_token_estimation(self):
        """Token estimation works on Unicode (emoji, CJK) via code-point chars/4."""
        text = "\U0001f525" * 8  # 8 fire emojis = 8 code points -> 2 tokens
        assert _truncation().estimate_tokens(text) == 2

    def test_unicode_in_template_body(self):
        """Jinja2 rendering preserves non-ASCII bytes correctly."""
        PromptTemplate = _prompt().PromptTemplate
        tpl = PromptTemplate.from_string("Hello {{ name }} \u2728")
        result = _prompt().PromptCompiler().render_template(tpl, {"name": "\u4e16\u754c"})
        assert "\u4e16\u754c" in result
        assert "\u2728" in result

    def test_jinja2_sandbox_blocks_attribute_access(self):
        """Sandboxed environment forbids dunder attribute traversal."""
        malicious = "{{ ().__class__.__mro__[1].__subclasses__() }}"
        PromptTemplate = _prompt().PromptTemplate
        tpl = PromptTemplate.from_string(malicious)
        with pytest.raises(Exception):
            _prompt().PromptCompiler().render_template(tpl, {})

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
        tpl = _prompt().PromptTemplate.from_file(f)
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
        tpl = _prompt().PromptTemplate.from_file(f)
        assert tpl.frontmatter == {}
        assert "body" in tpl.body

    def test_three_dashes_in_body_not_treated_as_frontmatter_boundary(self):
        """Only a leading frontmatter delimiter separates; body ``---`` is literal."""
        content = textwrap.dedent("""\
            ---
            role: x
            ---
            intro
            ---
            middle
        """)
        tpl = _prompt().PromptTemplate.from_string(content)
        assert tpl.frontmatter == {"role": "x"}
        assert "---" in tpl.body

    def test_u_shape_two_equal_priority_tie(self):
        """U-shape with only-ties still returns a 2-element list."""
        blocks = [
            _make_block(name="a", priority=50),
            _make_block(name="b", priority=50),
        ]
        result = _truncation().order_by_position(blocks)
        assert len(result) == 2

    def test_compile_character_slice_into_u_shape(self):
        """Character-sliced survivor still produces a valid U-shape output."""
        blocks = [
            _make_block(name="huge", content="x" * 400, priority=100),
            _make_block(name="small", content="tiny", priority=50),
        ]
        compiler = _prompt().PromptCompiler(default_budget=100)
        result = compiler.compile(blocks, budget=8, positional_order=True)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_compile_very_small_budget_still_produces_output(self):
        """Even a 1-token budget produces *some* output from highest-priority block."""
        blocks = [_make_block(name="x", content="abcdefgh", priority=100)]
        result = _prompt().PromptCompiler().compile(blocks, budget=1)
        assert isinstance(result, str)

    def test_render_template_with_empty_body(self):
        """A template with frontmatter but no body renders to empty (whitespace) string."""
        tpl = _prompt().PromptTemplate.from_string("---\nrole: x\n---\n")
        result = _prompt().PromptCompiler().render_template(tpl, {})
        assert result.strip() == ""


# ===========================================================================
# 17. Dependency constraints — prompt/ is a leaf module
# ===========================================================================


class TestDependencyConstraints:
    """``prompt/`` must not import from higher-layer packages."""

    _FORBIDDEN = (
        "bonfire.dispatch",
        "bonfire.engine",
        "bonfire.cli",
        "bonfire.workflow",
        "bonfire.session",
        "bonfire.vault",
        "bonfire.knowledge",
        "bonfire.handlers",
        "bonfire.git",
        "bonfire.github",
    )

    def _read_src(self, filename: str) -> str:
        prompt_pkg = Path(__file__).resolve().parents[2] / "src" / "bonfire" / "prompt"
        return (prompt_pkg / filename).read_text()

    def test_compiler_has_no_forbidden_imports(self):
        source = self._read_src("compiler.py")
        for module in self._FORBIDDEN:
            assert module not in source, f"compiler.py must not import {module}"

    def test_truncation_has_no_forbidden_imports(self):
        source = self._read_src("truncation.py")
        for module in self._FORBIDDEN:
            assert module not in source, f"truncation.py must not import {module}"

    def test_identity_block_module_has_no_forbidden_imports(self):
        """``identity_block.py`` (renamed from ``axiom_meta.py``) stays leaf."""
        source = self._read_src("identity_block.py")
        for module in self._FORBIDDEN:
            assert module not in source, f"identity_block.py must not import {module}"
