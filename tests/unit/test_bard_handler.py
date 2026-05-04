"""BON-342 W5.3 RED — BardHandler canonical synthesis.

Sage-synthesized from Knight A (Conservative Porter) + Knight B
(Generic-Vocabulary Modernizer).

Decisions locked here (see docs/audit/sage-decisions/bon-342-sage.md):

- D2 ADOPT: module-level ``ROLE: AgentRole = AgentRole.PUBLISHER`` constant.
- D3 ADOPT: no hardcoded ``"Bard"`` string literal in code body
  (docstrings/comments exempted; no exemption needed for bard.py itself).
- D4 DEFER: META_BARD_* metadata keys not in v0.1 envelope — dependent
  assertions use ``xfail(reason="...deferred to BON-W5.3-meta-ports")``.

Contract preserved from v1:

- Empty ``envelope.artifacts`` short-circuits BEFORE any git call with
  ``error_type="empty_artifacts"``.
- Branch name is ``<stage.name>/<slug>`` with NO ``"bonfire/"`` literal
  prefix (the GitWorkflow owns the prefix).
- Post-commit SHA compared to base SHA captured at handler entry; equality
  triggers ``error_type="no_diff_after_commit"``.
- ``push()`` is called keyword-only (``branch=``).
- Bard is not an LLM caller; imports no DispatchOptions / execute_with_retry
  / EventBus.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import re
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

import pytest

# --- v0.1-tolerant imports ---------------------------------------------------

try:
    from bonfire.github.mock import MockGitHubClient  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    MockGitHubClient = None  # type: ignore[assignment,misc]

try:
    from bonfire.handlers.bard import BardHandler  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    BardHandler = None  # type: ignore[assignment,misc]

try:
    from bonfire.handlers.bard import _slugify_task  # type: ignore[import-not-found]
except ImportError:  # pragma: no cover
    _slugify_task = None  # type: ignore[assignment]

from bonfire.agent.roles import AgentRole
from bonfire.models.config import PipelineConfig
from bonfire.models.envelope import (
    META_PR_NUMBER,
    Artifact,
    Envelope,
    TaskStatus,
)
from bonfire.models.plan import StageSpec
from bonfire.naming import ROLE_DISPLAY

# META_BARD_* keys — v0.1 gap. DEFER per D4.
try:
    from bonfire.models.envelope import (  # type: ignore[attr-defined]
        META_BARD_BASE_SHA,
        META_BARD_BRANCH,
        META_BARD_COMMIT_SHA,
        META_BARD_STAGED_FILES,
        META_BARD_STAGING_FAILURE_REASON,
    )

    _BARD_META_PRESENT = True
except ImportError:  # pragma: no cover
    META_BARD_BASE_SHA = "bard_base_sha"
    META_BARD_BRANCH = "bard_branch"
    META_BARD_COMMIT_SHA = "bard_commit_sha"
    META_BARD_STAGED_FILES = "bard_staged_files"
    META_BARD_STAGING_FAILURE_REASON = "bard_staging_failure_reason"
    _BARD_META_PRESENT = False


pytestmark = pytest.mark.skipif(
    BardHandler is None or MockGitHubClient is None,
    reason="v0.1 handler not yet ported: BardHandler / MockGitHubClient missing",
)


_BARD_META_XFAIL = pytest.mark.xfail(
    condition=not _BARD_META_PRESENT,
    reason=(
        "v0.1 gap: META_BARD_* keys not yet in bonfire.models.envelope — "
        "deferred to BON-W5.3-meta-ports"
    ),
    strict=False,
)

_SLUG_HELPER_XFAIL = pytest.mark.xfail(
    condition=_slugify_task is None,
    reason="v0.1 gap: bonfire.handlers.bard._slugify_task not yet ported",
    strict=False,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def bard_stage() -> StageSpec:
    """Canonical Publisher stage (file-stem: bard)."""
    return StageSpec(name="bard", agent_name="pr-creator", role="publisher")


@pytest.fixture()
def github_client():  # noqa: ANN201
    return MockGitHubClient()


@pytest.fixture()
def git_workflow() -> AsyncMock:
    """AsyncMock GitWorkflow stub with rev_parse/create_branch/commit/push."""
    wf = AsyncMock()
    wf.rev_parse = AsyncMock(return_value="a" * 40)
    wf.create_branch = AsyncMock(return_value=None)
    wf.commit = AsyncMock(return_value="b" * 40)
    wf.push = AsyncMock(return_value=None)
    return wf


@pytest.fixture()
def artifacts_envelope() -> Envelope:
    """Happy-path envelope with two file artifacts."""
    return Envelope(
        task="Implement auth module",
        artifacts=[
            Artifact(name="src/bonfire/auth.py", content="", artifact_type="file_written"),
            Artifact(name="tests/unit/test_auth.py", content="", artifact_type="file_modified"),
        ],
    )


@pytest.fixture()
def empty_envelope() -> Envelope:
    return Envelope(task="Implement something")


@pytest.fixture()
def handler(git_workflow: AsyncMock, github_client) -> Any:  # noqa: ANN001
    return BardHandler(git_workflow=git_workflow, github_client=github_client)


def _make_envelope(task: str, artifacts: list[Artifact] | None = None) -> Envelope:
    if artifacts is None:
        artifacts = [Artifact(name="src/foo.py", content="", artifact_type="file_written")]
    return Envelope(task=task, artifacts=artifacts)


# ---------------------------------------------------------------------------
# GENERIC-VOCABULARY DISCIPLINE (D2, D3)
# ---------------------------------------------------------------------------


class TestGenericVocabularyDiscipline:
    """D2: module exposes ROLE=AgentRole.PUBLISHER; D3: no gamified literals."""

    def test_module_exposes_role_constant_bound_to_publisher(self) -> None:
        """D2: ``bard.ROLE is AgentRole.PUBLISHER``."""
        import bonfire.handlers.bard as bard_mod

        assert hasattr(bard_mod, "ROLE"), (
            "bard.py must expose a module-level ROLE constant for generic-vocab "
            "discipline; display translation is the display layer's job."
        )
        assert bard_mod.ROLE is AgentRole.PUBLISHER
        assert isinstance(bard_mod.ROLE, AgentRole)

    def test_role_constant_value_is_publisher_string(self) -> None:
        """StrEnum value equality: ROLE == 'publisher'."""
        import bonfire.handlers.bard as bard_mod

        assert bard_mod.ROLE == "publisher"

    def test_handler_class_docstring_cites_generic_role(self) -> None:
        """BardHandler.__doc__ must cite 'publisher'."""
        assert BardHandler.__doc__ is not None
        assert "publisher" in BardHandler.__doc__.lower()

    def test_handler_module_docstring_cites_generic_role(self) -> None:
        import bonfire.handlers.bard as bard_mod

        assert bard_mod.__doc__ is not None
        assert "publisher" in bard_mod.__doc__.lower()

    def test_role_in_display_map_translates_to_bard(self) -> None:
        """ROLE_DISPLAY['publisher'].gamified == 'Bard'."""
        assert ROLE_DISPLAY["publisher"].gamified == "Bard"
        assert ROLE_DISPLAY["publisher"].professional == "Publish Agent"

    def test_handler_source_does_not_hardcode_gamified_display(self) -> None:
        """D3: no ``"Bard"`` string literal in code body (docstrings exempt)."""
        import bonfire.handlers.bard as bard_mod

        src = Path(bard_mod.__file__).read_text()
        lines = src.splitlines()
        offenders: list[tuple[int, str]] = []
        in_docstring = False
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.endswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            if '"Bard"' in line or "'Bard'" in line:
                offenders.append((idx, line))
        assert not offenders, (
            f"BardHandler source must not hardcode the gamified display 'Bard' "
            f"in code -- use ROLE_DISPLAY[ROLE].gamified. Offenders: {offenders}"
        )

    def test_role_constant_matches_stage_spec_role_field(self, bard_stage: StageSpec) -> None:
        """Integration: stage.role == handler module ROLE."""
        import bonfire.handlers.bard as bard_mod

        assert bard_stage.role == bard_mod.ROLE


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestHappyPath:
    @pytest.mark.asyncio
    async def test_returns_completed_envelope(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
    ) -> None:
        """COMPLETED is the enum + META_PR_NUMBER populated."""
        result = await handler.handle(bard_stage, artifacts_envelope, {})
        assert result.status is TaskStatus.COMPLETED
        assert META_PR_NUMBER in result.metadata

    @pytest.mark.asyncio
    async def test_stages_artifact_paths_to_commit(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        git_workflow: AsyncMock,
    ) -> None:
        """commit() called with paths= kwarg containing both files."""
        await handler.handle(bard_stage, artifacts_envelope, {})
        kwargs = git_workflow.commit.await_args.kwargs
        assert kwargs["paths"] == ["src/bonfire/auth.py", "tests/unit/test_auth.py"]

    @_BARD_META_XFAIL
    @pytest.mark.asyncio
    async def test_populates_bard_metadata(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
    ) -> None:
        """All five META_BARD_* keys populated on success."""
        result = await handler.handle(bard_stage, artifacts_envelope, {})
        assert result.metadata[META_BARD_BRANCH].startswith("bard/")
        assert result.metadata[META_BARD_BASE_SHA] == "a" * 40
        assert result.metadata[META_BARD_COMMIT_SHA] == "b" * 40
        assert json.loads(result.metadata[META_BARD_STAGED_FILES]) == [
            "src/bonfire/auth.py",
            "tests/unit/test_auth.py",
        ]

    @pytest.mark.asyncio
    async def test_rev_parse_called_before_create_branch(
        self,
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """Call ordering: rev_parse -> create_branch -> commit -> push."""
        call_log: list[str] = []

        git_workflow = AsyncMock()

        async def _track_rev_parse(_ref: str) -> str:
            call_log.append("rev_parse")
            return "a" * 40

        async def _track_create_branch(_name: str) -> None:
            call_log.append("create_branch")

        async def _track_commit(_msg: str, **_kwargs: object) -> str:
            call_log.append("commit")
            return "b" * 40

        async def _track_push(**_kwargs: object) -> None:
            call_log.append("push")

        git_workflow.rev_parse = _track_rev_parse
        git_workflow.create_branch = _track_create_branch
        git_workflow.commit = _track_commit
        git_workflow.push = _track_push

        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        await handler.handle(bard_stage, artifacts_envelope, {})

        assert call_log == ["rev_parse", "create_branch", "commit", "push"]
        assert any(a["type"] == "create_pr" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_status_is_enum_not_string(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
    ) -> None:
        """``is`` TaskStatus.COMPLETED (enum identity, not str equality)."""
        envelope = _make_envelope("enum-check")
        result = await handler.handle(bard_stage, envelope, {})
        assert result.status is TaskStatus.COMPLETED


# ---------------------------------------------------------------------------
# Empty-artifacts short-circuit
# ---------------------------------------------------------------------------


class TestEmptyArtifactsShortCircuit:
    @pytest.mark.asyncio
    async def test_empty_returns_failed_with_structured_token(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        empty_envelope: Envelope,
    ) -> None:
        """Empty envelope fails fast with error_type='empty_artifacts'."""
        result = await handler.handle(bard_stage, empty_envelope, {})
        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "empty_artifacts"
        assert result.error.message.startswith("BardHandler refused to commit")

    @pytest.mark.asyncio
    async def test_empty_message_identifies_envelope_and_stage(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        empty_envelope: Envelope,
    ) -> None:
        """Forensic message mentions envelope_id + stage.name."""
        result = await handler.handle(bard_stage, empty_envelope, {})
        assert result.error is not None
        assert empty_envelope.envelope_id in result.error.message
        assert "bard" in result.error.message

    @_BARD_META_XFAIL
    @pytest.mark.asyncio
    async def test_empty_writes_staging_failure_reason_metadata(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        empty_envelope: Envelope,
    ) -> None:
        """Only META_BARD_STAGING_FAILURE_REASON populated on empty path."""
        result = await handler.handle(bard_stage, empty_envelope, {})
        assert result.metadata[META_BARD_STAGING_FAILURE_REASON] == "empty_artifacts"
        assert META_BARD_BRANCH not in result.metadata
        assert META_BARD_COMMIT_SHA not in result.metadata
        assert META_BARD_BASE_SHA not in result.metadata
        assert META_BARD_STAGED_FILES not in result.metadata

    @pytest.mark.asyncio
    async def test_empty_preserves_upstream_metadata(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """Upstream metadata keys survive into the FAILED envelope."""
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = Envelope(
            task="noop",
            metadata={"ticket_ref": "REF-999", "upstream_note": "hi"},
            artifacts=[],
        )
        result = await handler.handle(bard_stage, envelope, {})

        assert result.status is TaskStatus.FAILED
        assert result.metadata["ticket_ref"] == "REF-999"
        assert result.metadata["upstream_note"] == "hi"

    @pytest.mark.asyncio
    async def test_empty_makes_no_git_calls(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        empty_envelope: Envelope,
        git_workflow: AsyncMock,
    ) -> None:
        """No rev_parse/create_branch/commit/push on the empty path."""
        await handler.handle(bard_stage, empty_envelope, {})
        git_workflow.rev_parse.assert_not_awaited()
        git_workflow.create_branch.assert_not_awaited()
        git_workflow.commit.assert_not_awaited()
        git_workflow.push.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_empty_makes_no_github_calls(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        empty_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """No create_pr on the empty path."""
        await handler.handle(bard_stage, empty_envelope, {})
        assert not any(a["type"] == "create_pr" for a in github_client.actions)


# ---------------------------------------------------------------------------
# Artifact filtering + order
# ---------------------------------------------------------------------------


class TestArtifactFiltering:
    @pytest.mark.asyncio
    async def test_mixed_types_filter_to_file_written_and_file_modified(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """Only file_written/file_modified survive filtering."""
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope(
            "mix",
            artifacts=[
                Artifact(name="a.py", content="", artifact_type="file_written"),
                Artifact(name="b.md", content="", artifact_type="spike_doc"),
                Artifact(name="c.py", content="", artifact_type="file_modified"),
                Artifact(name="d.py", content="", artifact_type="file_deleted"),
                Artifact(name="e.log", content="", artifact_type="log"),
            ],
        )
        await handler.handle(bard_stage, envelope, {})

        git_workflow.commit.assert_awaited_once()
        staged = git_workflow.commit.await_args.kwargs["paths"]
        assert staged == ["a.py", "c.py"]

    @pytest.mark.asyncio
    async def test_all_non_file_types_treated_as_empty(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """Zero survivors after filtering -> empty_artifacts."""
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope(
            "filtered",
            artifacts=[
                Artifact(name="a.md", content="", artifact_type="spike_doc"),
                Artifact(name="b.log", content="", artifact_type="log"),
            ],
        )
        result = await handler.handle(bard_stage, envelope, {})

        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "empty_artifacts"
        git_workflow.rev_parse.assert_not_awaited()
        git_workflow.create_branch.assert_not_awaited()
        git_workflow.commit.assert_not_awaited()
        git_workflow.push.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_order_preserved_into_commit_paths(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """Artifact order preserved through filtering."""
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope(
            "ordered",
            artifacts=[
                Artifact(name="z.py", content="", artifact_type="file_written"),
                Artifact(name="a.py", content="", artifact_type="file_modified"),
                Artifact(name="m.py", content="", artifact_type="file_written"),
            ],
        )
        await handler.handle(bard_stage, envelope, {})
        staged = git_workflow.commit.await_args.kwargs["paths"]
        assert staged == ["z.py", "a.py", "m.py"]

    @pytest.mark.asyncio
    async def test_duplicate_paths_pass_through_unchanged(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """No dedup — duplicates reach commit (git add is idempotent)."""
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope(
            "dupes",
            artifacts=[
                Artifact(name="src/x.py", content="", artifact_type="file_written"),
                Artifact(name="src/x.py", content="", artifact_type="file_written"),
            ],
        )
        await handler.handle(bard_stage, envelope, {})
        staged = git_workflow.commit.await_args.kwargs["paths"]
        assert staged == ["src/x.py", "src/x.py"]


# ---------------------------------------------------------------------------
# Branch-naming
# ---------------------------------------------------------------------------


class TestBranchNaming:
    @pytest.mark.asyncio
    async def test_excludes_bonfire_prefix(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        git_workflow: AsyncMock,
    ) -> None:
        """Handler passes unprefixed name; workflow owns the prefix."""
        await handler.handle(bard_stage, artifacts_envelope, {})
        branch_arg = git_workflow.create_branch.await_args.args[0]
        assert not branch_arg.startswith("bonfire/")
        assert branch_arg.startswith("bard/")

    @_SLUG_HELPER_XFAIL
    @pytest.mark.asyncio
    async def test_exact_slug_form(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        git_workflow: AsyncMock,
    ) -> None:
        """Exact form ``bard/<slug>-<id12>``."""
        await handler.handle(bard_stage, artifacts_envelope, {})
        branch_arg = git_workflow.create_branch.await_args.args[0]
        expected = f"bard/{_slugify_task(artifacts_envelope.task, artifacts_envelope.envelope_id)}"
        assert branch_arg == expected


# ---------------------------------------------------------------------------
# Slug builder — pure-function unit tests
# ---------------------------------------------------------------------------


class TestSlugifyTask:
    """All tests gated on _slugify_task being present in bard.py."""

    @_SLUG_HELPER_XFAIL
    def test_suffix_is_full_envelope_id(self) -> None:
        """12-char envelope_id suffix after final '-'."""
        envelope_id = "abc123456789"
        output = _slugify_task("foo", envelope_id)
        assert output.endswith(f"-{envelope_id}")
        _, _, suffix = output.rpartition("-")
        assert len(suffix) == 12

    @_SLUG_HELPER_XFAIL
    def test_envelope_id_preserves_leading_zero_hex(self) -> None:
        """Envelope_id slice must not reinterpret leading-zero hex."""
        out = _slugify_task("hello", "0000abcd1234")
        assert out == "hello-0000abcd1234"

    @_SLUG_HELPER_XFAIL
    def test_special_chars_collapse_to_dashes(self) -> None:
        """Non-[a-z0-9] -> dashes; stripped at ends."""
        out = _slugify_task("!!! hello WORLD !!!", "a" * 12)
        assert out == "hello-world-aaaaaaaaaaaa"

    @_SLUG_HELPER_XFAIL
    def test_control_chars_treated_as_delimiters(self) -> None:
        """Tab, newline, carriage return collapse to dashes."""
        out = _slugify_task("foo\tbar\nbaz\rqux", "d" * 12)
        assert out == "foo-bar-baz-qux-dddddddddddd"

    @_SLUG_HELPER_XFAIL
    def test_null_byte_does_not_survive(self) -> None:
        """Null byte collapses to dash; no NUL in output."""
        out = _slugify_task("foo\x00bar", "e" * 12)
        assert "\x00" not in out
        assert out == "foo-bar-eeeeeeeeeeee"

    @_SLUG_HELPER_XFAIL
    def test_mixed_unicode_whitespace_collapses(self) -> None:
        """NBSP and EM-SPACE collapse to dash."""
        task = "foo\u00a0bar\u2003baz"
        out = _slugify_task(task, "1" * 12)
        assert out == "foo-bar-baz-111111111111"

    @_SLUG_HELPER_XFAIL
    def test_special_chars_only_uses_fallback(self) -> None:
        """Pure non-alphanumeric input collapses to fallback 'task'."""
        out = _slugify_task("!!!@@@###", "c" * 12)
        assert out == "task-cccccccccccc"

    @_SLUG_HELPER_XFAIL
    def test_whitespace_only_task_uses_fallback(self) -> None:
        """Whitespace-only sanitizes to empty -> fallback 'task'."""
        out = _slugify_task("    \t\n  ", "9" * 12)
        assert out == "task-999999999999"

    @_SLUG_HELPER_XFAIL
    def test_is_deterministic(self) -> None:
        """Same (task, envelope_id) -> identical output every call."""
        task = "same input"
        envelope_id = "abcdef012345"
        first = _slugify_task(task, envelope_id)
        second = _slugify_task(task, envelope_id)
        third = _slugify_task(task, envelope_id)
        assert first == second == third

    @_SLUG_HELPER_XFAIL
    def test_unicode_emoji_stripped_deterministic(self) -> None:
        """Emoji collapse to dashes; ASCII-only output."""
        task = "\U0001f525 build the forge \U0001f3f0"
        out1 = _slugify_task(task, "a" * 12)
        out2 = _slugify_task(task, "a" * 12)
        assert out1 == out2
        assert all(ord(c) < 128 for c in out1)
        assert out1.endswith("-aaaaaaaaaaaa")

    @_SLUG_HELPER_XFAIL
    def test_very_long_task_truncates_to_53_chars_max(self) -> None:
        """1000-char task must not produce a 1000-char branch."""
        out = _slugify_task("x" * 1000, "f" * 12)
        assert len(out) <= 53
        prefix, _, suffix = out.rpartition("-")
        assert len(prefix) <= 40
        assert len(suffix) == 12

    @_SLUG_HELPER_XFAIL
    @pytest.mark.parametrize("n", [39, 40, 41, 42])
    def test_prefix_length_at_boundary(self, n: int) -> None:
        """Prefix cap is 40; exactly-40 must not lose data."""
        task = "a" * n
        out = _slugify_task(task, "0" * 12)
        prefix, _, suffix = out.rpartition("-")
        assert len(prefix) <= 40
        if n == 39:
            assert prefix == "a" * 39
        if n >= 40:
            assert prefix == "a" * 40
        assert suffix == "0" * 12

    @_SLUG_HELPER_XFAIL
    def test_truncation_rstrips_trailing_dash(self) -> None:
        """``sanitized[:40].rstrip('-')`` removes trailing dash at cut."""
        task = "a" * 39 + "!" + "b"
        out = _slugify_task(task, "2" * 12)
        prefix, _, _ = out.rpartition("-")
        assert not prefix.endswith("-")
        assert prefix == "a" * 39

    @_SLUG_HELPER_XFAIL
    def test_output_matches_character_set_regex(self) -> None:
        """Output matches locked character-set regex."""
        non_empty = _slugify_task("Implement auth module", "abcdef012345")
        assert re.fullmatch(r"^[a-z0-9](-?[a-z0-9]+)*-[0-9a-f]{12}$", non_empty)

        fallback = _slugify_task("!!!", "abcdef012345")
        assert re.fullmatch(r"^[a-z0-9]+-[0-9a-f]{12}$", fallback)

    @_SLUG_HELPER_XFAIL
    def test_differs_when_envelope_ids_differ(self) -> None:
        """Distinct envelope_ids -> distinct slugs."""
        slug_a = _slugify_task("same task", "0123456789ab")
        slug_b = _slugify_task("same task", "fedcba987654")
        assert slug_a != slug_b
        assert slug_a.endswith("-0123456789ab")
        assert slug_b.endswith("-fedcba987654")

    @_SLUG_HELPER_XFAIL
    def test_identical_inputs_produce_identical_slugs(self) -> None:
        slug_a = _slugify_task("same task", "0123456789ab")
        slug_b = _slugify_task("same task", "0123456789ab")
        assert slug_a == slug_b

    @pytest.mark.asyncio
    async def test_slug_differs_when_envelope_id_differs_at_handler(
        self,
        bard_stage: StageSpec,
        github_client,  # noqa: ANN001
    ) -> None:
        """Integration: two envelopes -> two distinct branch names."""
        artifacts = [Artifact(name="src/a.py", content="", artifact_type="file_written")]
        env_one = Envelope(task="same", artifacts=artifacts, envelope_id="aaaaaaaaaaaa")
        env_two = Envelope(task="same", artifacts=artifacts, envelope_id="bbbbbbbbbbbb")

        captured: list[str] = []

        def _mk_wf() -> AsyncMock:
            wf = AsyncMock()
            wf.rev_parse = AsyncMock(return_value="f" * 40)

            async def _capture(name: str) -> None:
                captured.append(name)

            wf.create_branch = _capture
            wf.commit = AsyncMock(return_value="c" * 40)
            wf.push = AsyncMock(return_value=None)
            return wf

        h_one = BardHandler(git_workflow=_mk_wf(), github_client=github_client)
        h_two = BardHandler(git_workflow=_mk_wf(), github_client=github_client)
        await h_one.handle(bard_stage, env_one, {})
        await h_two.handle(bard_stage, env_two, {})

        assert len(captured) == 2
        assert captured[0] != captured[1]

    @_SLUG_HELPER_XFAIL
    @pytest.mark.parametrize(
        ("task", "envelope_id", "expected"),
        [
            ("hello", "a" * 12, "hello-" + "a" * 12),
            ("a" * 40, "b" * 12, "a" * 40 + "-" + "b" * 12),
            ("a" * 41, "c" * 12, "a" * 40 + "-" + "c" * 12),
            ("  foo   bar  ", "d" * 12, "foo-bar-" + "d" * 12),
            ("!!!", "e" * 12, "task-" + "e" * 12),
            ("café résumé", "f" * 12, "caf-r-sum-" + "f" * 12),
        ],
    )
    def test_parametric_table(self, task: str, envelope_id: str, expected: str) -> None:
        """Exhaustive coverage across character-class families."""
        assert _slugify_task(task, envelope_id) == expected


# ---------------------------------------------------------------------------
# Phantom commit — base SHA == post-commit SHA
# ---------------------------------------------------------------------------


class TestPhantomCommitDetection:
    @pytest.mark.asyncio
    async def test_commit_sha_equals_base_sha_returns_failed_no_diff(
        self,
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """SHA equality -> FAILED + error_type=no_diff_after_commit."""
        phantom = "x" * 40
        wf = AsyncMock()
        wf.rev_parse = AsyncMock(return_value=phantom)
        wf.create_branch = AsyncMock(return_value=None)
        wf.commit = AsyncMock(return_value=phantom)
        wf.push = AsyncMock(return_value=None)

        handler = BardHandler(git_workflow=wf, github_client=github_client)
        result = await handler.handle(bard_stage, artifacts_envelope, {})
        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "no_diff_after_commit"
        assert result.error.message.startswith("BardHandler detected phantom commit:")

    @_BARD_META_XFAIL
    @pytest.mark.asyncio
    async def test_phantom_commit_writes_all_metadata(
        self,
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """Every Bard metadata key present on phantom path; no PR."""
        phantom = "x" * 40
        wf = AsyncMock()
        wf.rev_parse = AsyncMock(return_value=phantom)
        wf.create_branch = AsyncMock(return_value=None)
        wf.commit = AsyncMock(return_value=phantom)
        wf.push = AsyncMock(return_value=None)

        handler = BardHandler(git_workflow=wf, github_client=github_client)
        result = await handler.handle(bard_stage, artifacts_envelope, {})
        meta = result.metadata
        assert META_BARD_BRANCH in meta
        assert meta[META_BARD_BASE_SHA] == phantom
        assert meta[META_BARD_COMMIT_SHA] == phantom
        assert json.loads(meta[META_BARD_STAGED_FILES]) == [
            "src/bonfire/auth.py",
            "tests/unit/test_auth.py",
        ]
        assert meta[META_BARD_STAGING_FAILURE_REASON] == "no_diff_after_commit"
        assert META_PR_NUMBER not in meta

    @pytest.mark.asyncio
    async def test_phantom_commit_does_not_push_or_create_pr(
        self,
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """SHA-match short-circuits pre-push and pre-PR."""
        phantom = "x" * 40
        wf = AsyncMock()
        wf.rev_parse = AsyncMock(return_value=phantom)
        wf.create_branch = AsyncMock(return_value=None)
        wf.commit = AsyncMock(return_value=phantom)
        wf.push = AsyncMock(return_value=None)

        handler = BardHandler(git_workflow=wf, github_client=github_client)
        await handler.handle(bard_stage, artifacts_envelope, {})
        wf.push.assert_not_awaited()
        assert not any(a["type"] == "create_pr" for a in github_client.actions)

    @_BARD_META_XFAIL
    @pytest.mark.asyncio
    async def test_phantom_commit_staged_files_is_json_string(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """staged_files is ``json.dumps(list)`` — string, not a list literal."""
        git_workflow.rev_parse = AsyncMock(return_value="f" * 40)
        git_workflow.commit = AsyncMock(return_value="f" * 40)
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope(
            "phantom",
            artifacts=[Artifact(name="a.py", content="", artifact_type="file_written")],
        )
        result = await handler.handle(bard_stage, envelope, {})

        assert META_BARD_STAGED_FILES in result.metadata
        raw = result.metadata[META_BARD_STAGED_FILES]
        assert isinstance(raw, str)
        assert json.loads(raw) == ["a.py"]


# ---------------------------------------------------------------------------
# Branch collision — create_branch raises "already exists"
# ---------------------------------------------------------------------------


class TestBranchCollision:
    @_BARD_META_XFAIL
    @pytest.mark.asyncio
    async def test_collision_returns_structured_token(
        self,
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        github_client,  # noqa: ANN001
    ) -> None:
        """create_branch RuntimeError -> branch_collision token."""
        wf = AsyncMock()
        wf.rev_parse = AsyncMock(return_value="a" * 40)
        wf.create_branch = AsyncMock(
            side_effect=RuntimeError("fatal: A branch named 'bonfire/bard/x' already exists.")
        )
        wf.commit = AsyncMock(return_value="b" * 40)
        wf.push = AsyncMock(return_value=None)

        handler = BardHandler(git_workflow=wf, github_client=github_client)
        result = await handler.handle(bard_stage, artifacts_envelope, {})
        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "branch_collision"
        assert result.metadata[META_BARD_STAGING_FAILURE_REASON] == "branch_collision"

    @_BARD_META_XFAIL
    @pytest.mark.asyncio
    async def test_collision_populates_partial_metadata_only(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """Collision path has BRANCH + BASE_SHA but NO COMMIT_SHA."""
        git_workflow.create_branch = AsyncMock(
            side_effect=RuntimeError("fatal: A branch named 'bonfire/bard/x' already exists."),
        )
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope("Implement r")
        result = await handler.handle(bard_stage, envelope, {})

        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "branch_collision"
        assert result.metadata[META_BARD_STAGING_FAILURE_REASON] == "branch_collision"
        assert META_BARD_BRANCH in result.metadata
        assert META_BARD_BASE_SHA in result.metadata
        assert META_BARD_COMMIT_SHA not in result.metadata
        assert META_BARD_STAGED_FILES not in result.metadata
        git_workflow.commit.assert_not_awaited()


# ---------------------------------------------------------------------------
# Mid-pipeline failures
# ---------------------------------------------------------------------------


class TestMidPipelineFailures:
    @pytest.mark.asyncio
    async def test_rev_parse_failure_means_no_branch_created(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """rev_parse raises -> FAILED; no create_branch/commit/push/create_pr."""
        git_workflow.rev_parse = AsyncMock(side_effect=RuntimeError("fatal: unknown revision"))
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope("Implement q")
        result = await handler.handle(bard_stage, envelope, {})

        assert result.status is TaskStatus.FAILED
        git_workflow.create_branch.assert_not_awaited()
        git_workflow.commit.assert_not_awaited()
        git_workflow.push.assert_not_awaited()
        assert not any(a["type"] == "create_pr" for a in github_client.actions)

    @pytest.mark.asyncio
    async def test_commit_failure_blocks_push_and_pr(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """commit() raises -> FAILED; push + create_pr NOT invoked."""
        git_workflow.commit = AsyncMock(side_effect=RuntimeError("fatal: permission denied"))
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope("Implement x")
        result = await handler.handle(bard_stage, envelope, {})

        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "RuntimeError"
        git_workflow.push.assert_not_awaited()
        assert not any(a["type"] == "create_pr" for a in github_client.actions)

    @_BARD_META_XFAIL
    @pytest.mark.asyncio
    async def test_push_failure_blocks_pr_creation(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """push() raises -> FAILED; partial metadata kept."""
        git_workflow.push = AsyncMock(side_effect=RuntimeError("remote rejected"))
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        envelope = _make_envelope("Implement y")
        result = await handler.handle(bard_stage, envelope, {})

        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "RuntimeError"
        assert not any(a["type"] == "create_pr" for a in github_client.actions)
        assert META_BARD_BRANCH in result.metadata
        assert META_BARD_BASE_SHA in result.metadata
        assert META_BARD_COMMIT_SHA in result.metadata

    @_BARD_META_XFAIL
    @pytest.mark.asyncio
    async def test_pr_creation_failure_leaves_pushed_branch_documented(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
    ) -> None:
        """create_pr raises -> FAILED; branch already pushed."""

        class ExplodingClient:
            actions: list[dict[str, Any]] = []

            async def create_pr(self, *args: Any, **kwargs: Any) -> Any:
                raise KeyError("gh api error")

        handler = BardHandler(git_workflow=git_workflow, github_client=ExplodingClient())
        envelope = _make_envelope("Implement z")
        result = await handler.handle(bard_stage, envelope, {})

        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "KeyError"
        git_workflow.push.assert_awaited_once()
        assert META_BARD_BRANCH in result.metadata
        assert META_BARD_BASE_SHA in result.metadata
        assert META_BARD_COMMIT_SHA in result.metadata
        assert META_BARD_STAGED_FILES in result.metadata


# ---------------------------------------------------------------------------
# Hostile-input survival
# ---------------------------------------------------------------------------


class TestHostileInputSurvival:
    @pytest.mark.asyncio
    async def test_hostile_task_reaches_pr(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """Unicode/special chars in task reach create_pr; branch slug ASCII-only."""
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        hostile_task = "\U0001f525 !!! hack the forge !!!"
        envelope = _make_envelope(hostile_task)
        result = await handler.handle(bard_stage, envelope, {})

        assert result.status is TaskStatus.COMPLETED
        assert any(
            a["type"] == "create_pr" and a["title"] == hostile_task for a in github_client.actions
        )
        branch_arg = git_workflow.create_branch.await_args.args[0]
        assert all(ord(c) < 128 for c in branch_arg)


# ---------------------------------------------------------------------------
# Config threading
# ---------------------------------------------------------------------------


class TestConfigThreading:
    def test_config_kwarg_accepted_and_stored(
        self,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """``config=`` threaded onto ``self._config``."""
        cfg = PipelineConfig(model="X")
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client, config=cfg)
        assert handler._config is cfg
        assert handler._config.model == "X"

    def test_explicit_none_config_stored_as_none(
        self,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client, config=None)
        assert handler._config is None

    @pytest.mark.asyncio
    async def test_custom_config_does_not_override_slug_constants(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """slug_max_len + suffix_chars are module-scope constants, not config knobs."""
        cfg = PipelineConfig(model="claude-opus-4-7")
        handler = BardHandler(
            git_workflow=git_workflow,
            github_client=github_client,
            config=cfg,
        )
        envelope = _make_envelope("x" * 200)
        await handler.handle(bard_stage, envelope, {})
        branch_arg = git_workflow.create_branch.await_args.args[0]
        assert branch_arg.startswith("bard/")
        slug_part = branch_arg[len("bard/") :]
        prefix, _, suffix = slug_part.rpartition("-")
        assert len(prefix) <= 40
        assert len(suffix) == 12

    @pytest.mark.asyncio
    async def test_config_not_consumed_on_empty_artifacts_path(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """config stored but unused; empty path survives exotic values."""
        cfg = PipelineConfig(model="", max_turns=1, max_budget_usd=0.0)
        handler = BardHandler(
            git_workflow=git_workflow,
            github_client=github_client,
            config=cfg,
        )
        envelope = Envelope(task="noop")
        result = await handler.handle(bard_stage, envelope, {})
        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "empty_artifacts"


# ---------------------------------------------------------------------------
# push() keyword-only branch arg
# ---------------------------------------------------------------------------


class TestPushKeywordOnly:
    @pytest.mark.asyncio
    async def test_push_uses_keyword_only_branch(
        self,
        handler,  # noqa: ANN001
        bard_stage: StageSpec,
        artifacts_envelope: Envelope,
        git_workflow: AsyncMock,
    ) -> None:
        """push() is keyword-only; pass branch=."""
        await handler.handle(bard_stage, artifacts_envelope, {})
        await_args = git_workflow.push.await_args
        assert await_args.args == ()
        assert "branch" in await_args.kwargs
        assert await_args.kwargs["branch"].startswith("bard/")


# ---------------------------------------------------------------------------
# FAILED-path enum identity
# ---------------------------------------------------------------------------


class TestFailedPathEnumIdentity:
    @pytest.mark.asyncio
    async def test_all_failed_paths_use_enum(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """Every FAILED path uses TaskStatus.FAILED enum, not string literal."""
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
        result_empty = await handler.handle(bard_stage, Envelope(task="noop"), {})
        assert result_empty.status is TaskStatus.FAILED

        git_workflow.rev_parse = AsyncMock(return_value="9" * 40)
        git_workflow.commit = AsyncMock(return_value="9" * 40)
        result_phantom = await handler.handle(bard_stage, _make_envelope("phantom"), {})
        assert result_phantom.status is TaskStatus.FAILED


# ---------------------------------------------------------------------------
# Negative drift guards
# ---------------------------------------------------------------------------


class TestNegativeDriftGuards:
    """Bard is NOT an LLM caller; no EventBus wiring."""

    def test_module_does_not_import_execute_with_retry(self) -> None:
        import bonfire.handlers.bard as bard_mod

        src = Path(bard_mod.__file__).read_text()
        assert "execute_with_retry" not in src, (
            "BardHandler must not wrap dispatch in execute_with_retry — it has no .execute."
        )

    def test_module_does_not_import_dispatch_options(self) -> None:
        import bonfire.handlers.bard as bard_mod

        src = Path(bard_mod.__file__).read_text()
        assert "DispatchOptions" not in src, (
            "BardHandler must not construct DispatchOptions — it is not an LLM caller."
        )

    def test_handler_has_no_event_bus_attribute(self) -> None:
        """BardHandler must not hold an _event_bus attribute."""
        handler = BardHandler(git_workflow=AsyncMock(), github_client=MockGitHubClient())
        assert not hasattr(handler, "_event_bus")

    def test_init_does_not_accept_event_bus_kwarg(self) -> None:
        """BardHandler.__init__ signature excludes event_bus."""
        sig = inspect.signature(BardHandler.__init__)
        assert "event_bus" not in sig.parameters

    def test_module_does_not_import_event_bus(self) -> None:
        import bonfire.handlers.bard as bard_mod

        src = Path(bard_mod.__file__).read_text()
        assert "EventBus" not in src


# ---------------------------------------------------------------------------
# Identity Seal invariants
# ---------------------------------------------------------------------------


class TestIdentitySealInvariants:
    @pytest.mark.asyncio
    async def test_handle_always_returns_envelope(
        self,
        bard_stage: StageSpec,
        git_workflow: AsyncMock,
        github_client,  # noqa: ANN001
    ) -> None:
        """Every code path returns an Envelope."""
        handler = BardHandler(git_workflow=git_workflow, github_client=github_client)

        result_ok = await handler.handle(bard_stage, _make_envelope("happy"), {})
        assert isinstance(result_ok, Envelope)

        result_empty = await handler.handle(bard_stage, Envelope(task="empty"), {})
        assert isinstance(result_empty, Envelope)

        git_workflow.rev_parse = AsyncMock(return_value="z" * 40)
        git_workflow.commit = AsyncMock(return_value="z" * 40)
        result_phantom = await handler.handle(bard_stage, _make_envelope("phantom"), {})
        assert isinstance(result_phantom, Envelope)

    def test_handle_signature_matches_stage_handler_protocol(self) -> None:
        """handle(stage, envelope, prior_results) -> Envelope is sealed."""
        sig = inspect.signature(BardHandler.handle)
        params = list(sig.parameters.keys())
        assert params == ["self", "stage", "envelope", "prior_results"]
        assert asyncio.iscoroutinefunction(BardHandler.handle)

    def test_handle_never_mutates_input_envelope(
        self,
        bard_stage: StageSpec,
    ) -> None:
        """Envelope is frozen; returned envelope must be a new instance."""
        git_workflow = AsyncMock()
        git_workflow.rev_parse = AsyncMock(return_value="a" * 40)
        git_workflow.create_branch = AsyncMock()
        git_workflow.commit = AsyncMock(return_value="b" * 40)
        git_workflow.push = AsyncMock()
        handler = BardHandler(git_workflow=git_workflow, github_client=MockGitHubClient())
        envelope = _make_envelope("seal")
        original_metadata_snapshot = dict(envelope.metadata)

        result = asyncio.run(handler.handle(bard_stage, envelope, {}))
        assert result is not envelope
        assert dict(envelope.metadata) == original_metadata_snapshot


# ---------------------------------------------------------------------------
# StageHandler protocol conformance
# ---------------------------------------------------------------------------


def test_bard_handler_satisfies_stage_handler_protocol(
    git_workflow: AsyncMock,
    github_client,  # noqa: ANN001
) -> None:
    """BardHandler instances pass runtime_checkable StageHandler isinstance."""
    from bonfire.protocols import StageHandler

    handler = BardHandler(git_workflow=git_workflow, github_client=github_client)
    assert isinstance(handler, StageHandler)
