# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The dispatch layer must record what the agent wrote onto the envelope.

``Envelope.artifacts`` was declared, reset to ``[]`` on every derive, and
read by exactly one consumer -- ``BardHandler``, which refuses to commit
when it is empty. Nothing anywhere produced an entry, so the publishing
stage of the flagship workflow could never run.

These tests pin the producer at the SDK boundary. That is the only layer
that sees which files the agent actually touched: a handler is told the
result text and nothing else, and diffing the working tree afterwards
cannot separate the agent's writes from whatever else is dirty.

The load-bearing test here is
:func:`test_emitted_types_are_the_types_the_publisher_stages`. Asserting
that a ``Write`` produces ``"file_written"`` proves only that this module
agrees with itself; the defect being closed is a *cross-module* one, so
the relationship to ``BardHandler``'s filter is asserted directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bonfire.dispatch.artifacts import artifacts_from_tool_uses
from bonfire.handlers.bard import _FILE_ARTIFACT_TYPES


class _ToolUse:
    """Minimal stand-in for the SDK's ``ToolUseBlock``."""

    def __init__(self, name: str, tool_input: dict) -> None:
        self.name = name
        self.input = tool_input


def _uses(*pairs: tuple[str, str]) -> list[_ToolUse]:
    return [_ToolUse(name, {"file_path": path}) for name, path in pairs]


class TestToolUseToArtifact:
    def test_write_records_a_written_file(self) -> None:
        arts = artifacts_from_tool_uses(_uses(("Write", "/repo/src/a.py")), root=Path("/repo"))
        assert [(a.name, a.artifact_type) for a in arts] == [("src/a.py", "file_written")]

    def test_edit_records_a_modified_file(self) -> None:
        arts = artifacts_from_tool_uses(_uses(("Edit", "/repo/src/a.py")), root=Path("/repo"))
        assert [(a.name, a.artifact_type) for a in arts] == [("src/a.py", "file_modified")]

    @pytest.mark.parametrize("tool", ["MultiEdit", "NotebookEdit"])
    def test_other_edit_tools_record_a_modification(self, tool: str) -> None:
        arts = artifacts_from_tool_uses(_uses((tool, "/repo/src/a.py")), root=Path("/repo"))
        assert [a.artifact_type for a in arts] == ["file_modified"]

    @pytest.mark.parametrize("tool", ["Read", "Bash", "Grep", "Glob", "WebFetch"])
    def test_non_mutating_tools_record_nothing(self, tool: str) -> None:
        assert artifacts_from_tool_uses(_uses((tool, "/repo/src/a.py")), root=Path("/repo")) == []

    def test_a_tool_use_without_a_path_is_ignored(self) -> None:
        block = _ToolUse("Write", {"content": "no path here"})
        assert artifacts_from_tool_uses([block], root=Path("/repo")) == []

    def test_repeated_edits_to_one_file_collapse_to_one_artifact(self) -> None:
        arts = artifacts_from_tool_uses(
            _uses(
                ("Write", "/repo/src/a.py"),
                ("Edit", "/repo/src/a.py"),
                ("Edit", "/repo/src/a.py"),
            ),
            root=Path("/repo"),
        )
        # One file, one artifact. The publisher stages paths; staging the
        # same path three times would put it in the commit metadata thrice.
        assert [a.name for a in arts] == ["src/a.py"]

    def test_first_action_wins_when_a_file_is_written_then_edited(self) -> None:
        arts = artifacts_from_tool_uses(
            _uses(("Write", "/repo/src/a.py"), ("Edit", "/repo/src/a.py")),
            root=Path("/repo"),
        )
        assert arts[0].artifact_type == "file_written"

    def test_order_is_the_order_the_agent_touched_them(self) -> None:
        arts = artifacts_from_tool_uses(
            _uses(("Write", "/repo/b.py"), ("Write", "/repo/a.py")),
            root=Path("/repo"),
        )
        assert [a.name for a in arts] == ["b.py", "a.py"]


class TestPathHandling:
    def test_paths_are_relative_to_the_project_root(self) -> None:
        arts = artifacts_from_tool_uses(
            _uses(("Write", "/repo/src/pkg/mod.py")), root=Path("/repo")
        )
        assert arts[0].name == "src/pkg/mod.py"
        assert not Path(arts[0].name).is_absolute()

    def test_a_path_outside_the_root_is_kept_verbatim(self) -> None:
        # Not silently rebased onto the root: the publisher would then stage
        # a path inside the repo that the agent never touched.
        arts = artifacts_from_tool_uses(_uses(("Write", "/elsewhere/x.py")), root=Path("/repo"))
        assert arts[0].name == "/elsewhere/x.py"

    def test_a_relative_path_survives_unchanged(self) -> None:
        block = _ToolUse("Write", {"file_path": "src/a.py"})
        assert artifacts_from_tool_uses([block], root=Path("/repo"))[0].name == "src/a.py"

    def test_no_root_leaves_the_path_alone(self) -> None:
        arts = artifacts_from_tool_uses(_uses(("Write", "/repo/src/a.py")), root=None)
        assert arts[0].name == "/repo/src/a.py"


class TestCrossModuleContract:
    """The half that a same-module assertion cannot reach."""

    def test_emitted_types_are_the_types_the_publisher_stages(self) -> None:
        arts = artifacts_from_tool_uses(
            _uses(("Write", "/repo/a.py"), ("Edit", "/repo/b.py")),
            root=Path("/repo"),
        )
        emitted = {a.artifact_type for a in arts}
        assert emitted, "producer emitted nothing -- the coupling below would be vacuous"
        # BardHandler derives staged_paths by filtering on this exact set.
        # A producer that emitted "file" or "written" would satisfy every
        # other test in this file and still leave the publisher refusing.
        assert emitted <= _FILE_ARTIFACT_TYPES

    def test_the_publisher_would_stage_every_file_the_producer_reports(self) -> None:
        arts = artifacts_from_tool_uses(
            _uses(("Write", "/repo/a.py"), ("Edit", "/repo/b.py")),
            root=Path("/repo"),
        )
        staged = [a.name for a in arts if a.artifact_type in _FILE_ARTIFACT_TYPES]
        assert staged == ["a.py", "b.py"]
