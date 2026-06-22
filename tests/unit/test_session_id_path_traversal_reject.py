# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``session_id`` / ``envelope_id`` reject path-traversal smuggling.

Both identifiers flow into operator-controlled file paths:

* ``Envelope.envelope_id`` is passed as ``session_id`` to
  ``CheckpointManager.save`` (writes ``{session_id}.json``) and to
  ``SessionPersistence.append_event`` (writes ``{session_id}.jsonl``).
* ``BonfireEvent.session_id`` is read by event-consumer code paths that
  forward it to the same persistence sinks.

Without validation, an attacker-controlled identifier of
``../../etc/passwd`` (POSIX) or ``..\\..\\Windows\\System32`` (Windows
shape) would smuggle the write outside the operator-controlled
directory. The validator added in Wave 9 Lane C rejects every shape that
contains a path separator, parent-traversal segment, null byte, or other
shell-meaningful character.

The pattern (``^[a-zA-Z0-9_-]{1,64}$`` for ``envelope_id``, plus the
empty-string sentinel for ``BonfireEvent.session_id`` — used by
``AxiomLoaded`` for outside-session emission) is permissive enough for
the existing test fixtures and the default ``uuid4().hex[:12]`` shape
while strict enough to refuse every adversarial smuggling shape covered
below.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bonfire.models.envelope import Envelope
from bonfire.models.events import AxiomLoaded, PipelineStarted

# ---------------------------------------------------------------------------
# Envelope.envelope_id — adversarial path-traversal shapes
# ---------------------------------------------------------------------------


class TestEnvelopeIdRejectsPathTraversal:
    """``Envelope(envelope_id=<traversal-shape>)`` raises ValidationError."""

    @pytest.mark.parametrize(
        "bad_id",
        [
            "..",  # parent-traversal segment
            "../../etc/passwd",  # POSIX traversal payload
            "..\\..\\Windows",  # Windows-shape traversal payload
            "foo/bar",  # forward-slash separator
            "foo\\bar",  # backslash separator
            "/abs/path",  # absolute POSIX path
            "C:\\path",  # absolute Windows path
            "foo\x00bar",  # null-byte truncation attempt
            "foo\nbar",  # newline injection
            "foo bar",  # space — outside the allow-list
            "",  # empty — Envelope requires a non-empty id
            "a" * 65,  # over the 64-char cap
            "foo.bar",  # dot — outside the allow-list (no extension smuggling)
            "..foo",  # leading dots — still rejected by the regex
        ],
    )
    def test_traversal_shape_rejected(self, bad_id: str) -> None:
        """Every adversarial shape raises ValidationError."""
        with pytest.raises(ValidationError):
            Envelope(envelope_id=bad_id, task="t")

    @pytest.mark.parametrize(
        "good_id",
        [
            "abcdef012345",  # uuid4.hex[:12] default shape
            "abc123456789",  # bard test fixture
            "aaaaaaaaaaaa",  # bard test fixture
            "session_under_attack",  # safe_write test fixture
            "sess-1",  # event_bus test fixture
            "ses_001",  # cost_analyzer test fixture
            "a",  # 1-char minimum
            "a" * 64,  # 64-char maximum
            "X-Y_Z-0",  # mixed allow-list
        ],
    )
    def test_legitimate_shape_accepted(self, good_id: str) -> None:
        """Every legitimate shape is accepted unchanged."""
        env = Envelope(envelope_id=good_id, task="t")
        assert env.envelope_id == good_id


# ---------------------------------------------------------------------------
# BonfireEvent.session_id — same adversarial shapes via concrete subclass
# ---------------------------------------------------------------------------


class TestBonfireEventSessionIdRejectsPathTraversal:
    """``BonfireEvent`` subclass with adversarial ``session_id`` raises."""

    @pytest.mark.parametrize(
        "bad_id",
        [
            "..",
            "../../etc/passwd",
            "..\\..\\Windows",
            "foo/bar",
            "foo\\bar",
            "/abs",
            "foo\x00bar",
            "foo\nbar",
            "a" * 65,
        ],
    )
    def test_pipeline_started_rejects(self, bad_id: str) -> None:
        """PipelineStarted (concrete BonfireEvent subclass) rejects traversal shapes."""
        with pytest.raises(ValidationError):
            PipelineStarted(
                session_id=bad_id,
                sequence=0,
                plan_name="p",
                budget_usd=1.0,
            )

    def test_empty_session_id_accepted_on_pipeline_started(self) -> None:
        """Empty string is the outside-session sentinel; ``PipelineStarted`` accepts it too.

        BonfireEvent's validator allows ``""`` because ``AxiomLoaded``
        (and any other event emitted outside session context) needs it.
        Per-subclass narrowing is not enforced at the model layer.
        """
        # No raise — empty session_id is allowed via the sentinel branch.
        event = PipelineStarted(
            session_id="",
            sequence=0,
            plan_name="p",
            budget_usd=1.0,
        )
        assert event.session_id == ""

    def test_axiom_loaded_preserves_empty_session_id_default(self) -> None:
        """AxiomLoaded's documented empty-default contract is preserved."""
        # The whole point of the empty-sentinel branch — AxiomLoaded emits
        # outside session context and must keep this default behavior.
        event = AxiomLoaded(role="knight", axiom_version="v1")
        assert event.session_id == ""

    @pytest.mark.parametrize(
        "good_id",
        [
            "abcdef012345",
            "sess-1",
            "ses_001",
            "session_under_attack",
            "a" * 64,
        ],
    )
    def test_pipeline_started_accepts_legitimate_shapes(self, good_id: str) -> None:
        """Legitimate session_id shapes are accepted unchanged."""
        event = PipelineStarted(
            session_id=good_id,
            sequence=0,
            plan_name="p",
            budget_usd=1.0,
        )
        assert event.session_id == good_id


# ---------------------------------------------------------------------------
# End-to-end: rejecting Envelope blocks downstream path interpolation
# ---------------------------------------------------------------------------


class TestEnvelopeRejectionBlocksDownstreamInterpolation:
    """A rejected envelope_id never reaches checkpoint / persistence paths."""

    def test_envelope_construction_fails_before_any_path_built(self) -> None:
        """Validator fires at model-construction time.

        If the validator did not fire here, the malicious id would flow
        into ``CheckpointManager.save`` and produce
        ``{checkpoint_dir}/../../etc/passwd.json`` — arbitrary write
        outside the checkpoint directory.
        """
        with pytest.raises(ValidationError):
            Envelope(envelope_id="../../etc/passwd", task="boom")
