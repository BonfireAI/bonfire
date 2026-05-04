"""RED tests for bonfire.models.envelope.

Contract derived from the hardened v1 engine. Public v0.1 drops
internal-only fields and cross-module dependencies — see
docs/release-gates.md for the transfer-target discipline.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

# RED-phase import shim: the implementation does not exist yet. Tests still
# reference real names; each test will fail with ModuleNotFoundError on first
# attribute access, satisfying the RED invariant. Collection succeeds because
# the import error is swallowed at module load time.
try:
    from bonfire.models.envelope import (
        META_PR_NUMBER,
        META_PR_URL,
        META_REVIEW_SEVERITY,
        META_REVIEW_VERDICT,
        META_TICKET_REF,
        Artifact,
        Envelope,
        ErrorDetail,
        TaskStatus,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    META_PR_NUMBER = META_PR_URL = META_REVIEW_SEVERITY = None  # type: ignore[assignment]
    META_REVIEW_VERDICT = META_TICKET_REF = None  # type: ignore[assignment]
    Artifact = Envelope = ErrorDetail = TaskStatus = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test with the import error while bonfire.models.envelope is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.models.envelope not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# TaskStatus
# ---------------------------------------------------------------------------


class TestTaskStatus:
    """TaskStatus is a 5-value StrEnum lifecycle indicator."""

    def test_is_str_enum(self):
        from enum import StrEnum

        assert issubclass(TaskStatus, StrEnum)

    def test_exactly_five_values(self):
        assert len(TaskStatus) == 5

    def test_pending_value(self):
        assert TaskStatus.PENDING == "pending"

    def test_running_value(self):
        assert TaskStatus.RUNNING == "running"

    def test_completed_value(self):
        assert TaskStatus.COMPLETED == "completed"

    def test_failed_value(self):
        assert TaskStatus.FAILED == "failed"

    def test_skipped_value(self):
        assert TaskStatus.SKIPPED == "skipped"

    def test_string_equality(self):
        """StrEnum members equal their string values."""
        assert TaskStatus.PENDING == "pending"
        assert "pending" == TaskStatus.PENDING


# ---------------------------------------------------------------------------
# ErrorDetail
# ---------------------------------------------------------------------------


class TestErrorDetail:
    """ErrorDetail is a frozen pydantic model carrying structured error info."""

    def test_construction_minimal(self):
        err = ErrorDetail(error_type="ValueError", message="bad input")
        assert err.error_type == "ValueError"
        assert err.message == "bad input"
        assert err.traceback is None
        assert err.stage_name is None

    def test_construction_full(self):
        err = ErrorDetail(
            error_type="RuntimeError",
            message="boom",
            traceback="line 42",
            stage_name="knight",
        )
        assert err.traceback == "line 42"
        assert err.stage_name == "knight"

    def test_frozen(self):
        err = ErrorDetail(error_type="X", message="y")
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            err.message = "changed"

    def test_missing_required_field(self):
        with pytest.raises(ValidationError):
            ErrorDetail(error_type="X")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Artifact
# ---------------------------------------------------------------------------


class TestArtifact:
    """Artifact is a frozen pydantic model for named outputs."""

    def test_construction_minimal(self):
        a = Artifact(name="report", content="hello", artifact_type="markdown")
        assert a.name == "report"
        assert a.content == "hello"
        assert a.artifact_type == "markdown"
        assert a.metadata == {}

    def test_metadata_defaults_to_empty_dict(self):
        a = Artifact(name="x", content="y", artifact_type="z")
        assert a.metadata == {}

    def test_metadata_is_preserved(self):
        a = Artifact(
            name="x",
            content="y",
            artifact_type="z",
            metadata={"lines": 10, "lang": "py"},
        )
        assert a.metadata == {"lines": 10, "lang": "py"}

    def test_frozen(self):
        a = Artifact(name="x", content="y", artifact_type="z")
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            a.name = "changed"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            Artifact(name="only-name")  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Envelope — construction
# ---------------------------------------------------------------------------


class TestEnvelopeConstruction:
    """Envelope requires only `task`; all other fields have defaults."""

    def test_minimal_construction(self):
        env = Envelope(task="do the thing")
        assert env.task == "do the thing"

    def test_default_status_is_pending(self):
        env = Envelope(task="x")
        assert env.status == TaskStatus.PENDING

    def test_default_context_is_empty(self):
        env = Envelope(task="x")
        assert env.context == ""

    def test_default_agent_name_is_empty(self):
        env = Envelope(task="x")
        assert env.agent_name == ""

    def test_default_model_is_empty(self):
        env = Envelope(task="x")
        assert env.model == ""

    def test_default_result_is_empty(self):
        env = Envelope(task="x")
        assert env.result == ""

    def test_default_error_is_none(self):
        env = Envelope(task="x")
        assert env.error is None

    def test_default_artifacts_is_empty_list(self):
        env = Envelope(task="x")
        assert env.artifacts == []

    def test_default_cost_usd_is_zero(self):
        env = Envelope(task="x")
        assert env.cost_usd == 0.0

    def test_default_parent_id_is_none(self):
        env = Envelope(task="x")
        assert env.parent_id is None

    def test_default_working_dir_is_none(self):
        env = Envelope(task="x")
        assert env.working_dir is None

    def test_default_metadata_is_empty_dict(self):
        env = Envelope(task="x")
        assert env.metadata == {}

    def test_envelope_id_default_is_12_hex_chars(self):
        env = Envelope(task="x")
        assert isinstance(env.envelope_id, str)
        assert len(env.envelope_id) == 12
        # all hex
        int(env.envelope_id, 16)

    def test_envelope_ids_are_unique(self):
        ids = {Envelope(task="x").envelope_id for _ in range(50)}
        assert len(ids) == 50

    def test_missing_task_raises(self):
        with pytest.raises(ValidationError):
            Envelope()  # type: ignore[call-arg]

    def test_working_dir_accepts_path(self):
        env = Envelope(task="x", working_dir=Path("/tmp"))
        assert env.working_dir == Path("/tmp")

    def test_thirteen_declared_fields(self):
        """Envelope must expose exactly 13 fields per the v0.1 contract."""
        expected = {
            "envelope_id",
            "task",
            "context",
            "agent_name",
            "model",
            "status",
            "result",
            "error",
            "artifacts",
            "cost_usd",
            "parent_id",
            "working_dir",
            "metadata",
        }
        assert set(Envelope.model_fields.keys()) == expected


# ---------------------------------------------------------------------------
# Envelope — field validation
# ---------------------------------------------------------------------------


class TestEnvelopeValidation:
    def test_negative_cost_rejected(self):
        with pytest.raises(ValidationError) as exc:
            Envelope(task="x", cost_usd=-0.01)
        assert "cost_usd" in str(exc.value) or ">= 0" in str(exc.value)

    def test_zero_cost_accepted(self):
        env = Envelope(task="x", cost_usd=0.0)
        assert env.cost_usd == 0.0

    def test_positive_cost_accepted(self):
        env = Envelope(task="x", cost_usd=1.23)
        assert env.cost_usd == 1.23


# ---------------------------------------------------------------------------
# Envelope — frozen invariant
# ---------------------------------------------------------------------------


class TestEnvelopeFrozen:
    def test_cannot_mutate_task(self):
        env = Envelope(task="x")
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            env.task = "changed"

    def test_cannot_mutate_status(self):
        env = Envelope(task="x")
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            env.status = TaskStatus.COMPLETED

    def test_cannot_mutate_cost_usd(self):
        env = Envelope(task="x")
        with pytest.raises((ValidationError, AttributeError, TypeError)):
            env.cost_usd = 1.0


# ---------------------------------------------------------------------------
# Envelope — mutation helpers (copy-on-write)
# ---------------------------------------------------------------------------


class TestEnvelopeWithStatus:
    def test_returns_new_instance(self):
        env = Envelope(task="x")
        env2 = env.with_status(TaskStatus.RUNNING)
        assert env2 is not env

    def test_new_instance_has_new_status(self):
        env = Envelope(task="x")
        env2 = env.with_status(TaskStatus.RUNNING)
        assert env2.status == TaskStatus.RUNNING

    def test_original_unchanged(self):
        env = Envelope(task="x")
        env.with_status(TaskStatus.RUNNING)
        assert env.status == TaskStatus.PENDING

    def test_preserves_other_fields(self):
        env = Envelope(task="x", context="ctx", agent_name="knight")
        env2 = env.with_status(TaskStatus.RUNNING)
        assert env2.task == "x"
        assert env2.context == "ctx"
        assert env2.agent_name == "knight"
        assert env2.envelope_id == env.envelope_id


class TestEnvelopeWithResult:
    def test_returns_new_instance(self):
        env = Envelope(task="x")
        env2 = env.with_result("done", cost_usd=0.5)
        assert env2 is not env

    def test_sets_result(self):
        env = Envelope(task="x")
        env2 = env.with_result("done", cost_usd=0.5)
        assert env2.result == "done"

    def test_sets_cost(self):
        env = Envelope(task="x")
        env2 = env.with_result("done", cost_usd=0.5)
        assert env2.cost_usd == 0.5

    def test_sets_status_completed(self):
        env = Envelope(task="x")
        env2 = env.with_result("done", cost_usd=0.5)
        assert env2.status == TaskStatus.COMPLETED

    def test_default_cost_is_zero(self):
        env = Envelope(task="x")
        env2 = env.with_result("done")
        assert env2.cost_usd == 0.0

    def test_negative_cost_rejected(self):
        env = Envelope(task="x")
        with pytest.raises(ValueError, match="cost"):
            env.with_result("done", cost_usd=-1.0)

    def test_original_unchanged(self):
        env = Envelope(task="x")
        env.with_result("done", cost_usd=0.5)
        assert env.result == ""
        assert env.cost_usd == 0.0
        assert env.status == TaskStatus.PENDING


class TestEnvelopeWithError:
    def test_returns_new_instance(self):
        env = Envelope(task="x")
        err = ErrorDetail(error_type="E", message="m")
        env2 = env.with_error(err)
        assert env2 is not env

    def test_sets_error(self):
        env = Envelope(task="x")
        err = ErrorDetail(error_type="E", message="m")
        env2 = env.with_error(err)
        assert env2.error is err

    def test_sets_status_failed(self):
        env = Envelope(task="x")
        err = ErrorDetail(error_type="E", message="m")
        env2 = env.with_error(err)
        assert env2.status == TaskStatus.FAILED

    def test_original_unchanged(self):
        env = Envelope(task="x")
        err = ErrorDetail(error_type="E", message="m")
        env.with_error(err)
        assert env.error is None
        assert env.status == TaskStatus.PENDING


class TestEnvelopeWithMetadata:
    def test_returns_new_instance(self):
        env = Envelope(task="x")
        env2 = env.with_metadata(foo="bar")
        assert env2 is not env

    def test_adds_new_key(self):
        env = Envelope(task="x")
        env2 = env.with_metadata(foo="bar")
        assert env2.metadata == {"foo": "bar"}

    def test_preserves_existing_keys(self):
        env = Envelope(task="x", metadata={"a": 1})
        env2 = env.with_metadata(b=2)
        assert env2.metadata == {"a": 1, "b": 2}

    def test_last_write_wins_on_conflict(self):
        env = Envelope(task="x", metadata={"k": "old"})
        env2 = env.with_metadata(k="new")
        assert env2.metadata == {"k": "new"}

    def test_original_unchanged(self):
        env = Envelope(task="x", metadata={"a": 1})
        env.with_metadata(b=2)
        assert env.metadata == {"a": 1}


# ---------------------------------------------------------------------------
# Envelope.chain — child envelopes
# ---------------------------------------------------------------------------


class TestEnvelopeChain:
    def test_returns_new_instance(self):
        parent = Envelope(task="parent-task")
        child = Envelope.chain(parent)
        assert child is not parent

    def test_child_inherits_task(self):
        parent = Envelope(task="parent-task")
        child = Envelope.chain(parent)
        assert child.task == "parent-task"

    def test_child_inherits_context(self):
        parent = Envelope(task="x", context="ctx")
        child = Envelope.chain(parent)
        assert child.context == "ctx"

    def test_child_inherits_working_dir(self):
        parent = Envelope(task="x", working_dir=Path("/tmp/wd"))
        child = Envelope.chain(parent)
        assert child.working_dir == Path("/tmp/wd")

    def test_child_has_new_envelope_id(self):
        parent = Envelope(task="x")
        child = Envelope.chain(parent)
        assert child.envelope_id != parent.envelope_id
        assert len(child.envelope_id) == 12

    def test_child_parent_id_points_to_parent(self):
        parent = Envelope(task="x")
        child = Envelope.chain(parent)
        assert child.parent_id == parent.envelope_id

    def test_child_status_is_pending(self):
        parent = Envelope(task="x").with_status(TaskStatus.COMPLETED)
        child = Envelope.chain(parent)
        assert child.status == TaskStatus.PENDING

    def test_child_result_is_empty(self):
        parent = Envelope(task="x").with_result("parent-result", cost_usd=1.0)
        child = Envelope.chain(parent)
        assert child.result == ""

    def test_child_error_is_none(self):
        parent_err = ErrorDetail(error_type="E", message="m")
        parent = Envelope(task="x").with_error(parent_err)
        child = Envelope.chain(parent)
        assert child.error is None

    def test_child_artifacts_empty(self):
        art = Artifact(name="n", content="c", artifact_type="t")
        parent = Envelope(task="x", artifacts=[art])
        child = Envelope.chain(parent)
        assert child.artifacts == []

    def test_child_cost_reset(self):
        parent = Envelope(task="x", cost_usd=1.5)
        child = Envelope.chain(parent)
        assert child.cost_usd == 0.0

    def test_overrides_apply(self):
        parent = Envelope(task="parent-task")
        child = Envelope.chain(parent, task="child-task", agent_name="warrior")
        assert child.task == "child-task"
        assert child.agent_name == "warrior"

    def test_overrides_do_not_break_parent_id(self):
        parent = Envelope(task="x")
        child = Envelope.chain(parent, agent_name="warrior")
        assert child.parent_id == parent.envelope_id


# ---------------------------------------------------------------------------
# Envelope.__repr__
# ---------------------------------------------------------------------------


class TestEnvelopeRepr:
    def test_repr_includes_envelope_id(self):
        env = Envelope(task="hello")
        assert env.envelope_id in repr(env)

    def test_repr_includes_status_name(self):
        env = Envelope(task="hello")
        assert "PENDING" in repr(env)

    def test_repr_includes_task_preview(self):
        env = Envelope(task="hello")
        assert "hello" in repr(env)

    def test_repr_truncates_long_task(self):
        long_task = "x" * 100
        env = Envelope(task=long_task)
        # Truncation to 40 chars + "..."
        r = repr(env)
        assert "..." in r
        # The full 100-char task should NOT appear
        assert long_task not in r

    def test_repr_omits_agent_when_empty(self):
        env = Envelope(task="x")
        assert "agent=" not in repr(env)

    def test_repr_includes_agent_when_set(self):
        env = Envelope(task="x", agent_name="knight")
        assert "agent=knight" in repr(env)

    def test_repr_omits_cost_when_zero(self):
        env = Envelope(task="x")
        assert "cost=" not in repr(env)

    def test_repr_includes_cost_when_positive(self):
        env = Envelope(task="x", cost_usd=0.1234)
        r = repr(env)
        assert "cost=$" in r
        assert "0.1234" in r

    def test_repr_starts_with_envelope_class_name(self):
        env = Envelope(task="x")
        assert repr(env).startswith("Envelope(")

    def test_repr_ends_with_close_paren(self):
        env = Envelope(task="x")
        assert repr(env).endswith(")")


# ---------------------------------------------------------------------------
# Metadata constants
# ---------------------------------------------------------------------------


class TestMetaConstants:
    """Well-known metadata keys exported as module-level constants."""

    def test_pr_number(self):
        assert META_PR_NUMBER == "pr_number"

    def test_pr_url(self):
        assert META_PR_URL == "pr_url"

    def test_review_severity(self):
        assert META_REVIEW_SEVERITY == "review_severity"

    def test_review_verdict(self):
        assert META_REVIEW_VERDICT == "review_verdict"

    def test_ticket_ref(self):
        assert META_TICKET_REF == "ticket_ref"

    def test_all_constants_are_strings(self):
        for c in (
            META_PR_NUMBER,
            META_PR_URL,
            META_REVIEW_SEVERITY,
            META_REVIEW_VERDICT,
            META_TICKET_REF,
        ):
            assert isinstance(c, str)

    def test_constants_usable_as_metadata_keys(self):
        env = Envelope(task="x").with_metadata(
            **{
                META_PR_NUMBER: 42,
                META_PR_URL: "https://example.com/pr/42",
                META_REVIEW_SEVERITY: "warning",
                META_REVIEW_VERDICT: "approve",
                META_TICKET_REF: "BON-331",
            }
        )
        assert env.metadata[META_PR_NUMBER] == 42
        assert env.metadata[META_TICKET_REF] == "BON-331"
