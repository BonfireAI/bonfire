# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Turn an agent's file-mutating tool calls into :class:`Artifact` records.

``Envelope.artifacts`` had a declared field, a reset, and exactly one
reader -- :class:`~bonfire.handlers.bard.BardHandler`, which refuses to
commit when the list is empty. It had no producer at all, so the flagship
``standard_build`` workflow could not reach its publishing stage on any
run.

This module is that producer, and it lives at the dispatch layer on
purpose. The alternatives were considered and are worse:

*Each handler.* A handler receives the stage's result *text* and the
prior stages' result text. It is never told which files were touched, so
it would have to guess from prose -- the same mistake the prose-matching
quality gates already make.

*A shared post-dispatch step that diffs the working tree.* This cannot
separate the agent's writes from anything else dirty in the tree: a
stale build artefact, an editor swap file, or the previous stage's work
would all be attributed to whichever stage happened to run last.

The tool-use stream is the only ground truth about what the agent did,
and it already flows through ``ClaudeSDKBackend._do_execute``'s message
loop -- which reads ``.text`` off every block and drops the rest.

Tool-name mapping is deliberately explicit rather than pattern-matched.
An unknown tool records nothing, so a future SDK tool that writes files
is a missing artifact (the publisher refuses, loudly) rather than a
mystery entry the publisher tries to ``git add``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from bonfire.models.envelope import Artifact

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

__all__ = ["FILE_TOOL_ARTIFACT_TYPES", "artifacts_from_tool_uses"]

# SDK tool name -> the artifact type the publisher filters on. The values
# are written out rather than derived from ``bard._FILE_ARTIFACT_TYPES``:
# a shared constant would make the cross-module test in
# ``test_dispatch_artifact_capture.py`` assert a tautology, and the point
# of that test is that these two modules agreed on nothing before.
FILE_TOOL_ARTIFACT_TYPES: dict[str, str] = {
    "Write": "file_written",
    "Edit": "file_modified",
    "MultiEdit": "file_modified",
    "NotebookEdit": "file_modified",
}

_PATH_KEY = "file_path"


def _relativize(raw: str, root: str | Path | None) -> str:
    """Return *raw* relative to *root* when it sits underneath it.

    A path outside *root* is returned verbatim. Rebasing it would hand the
    publisher a repo-relative path the agent never wrote, and ``git add``
    would either fail or -- worse -- stage a same-named file that happens
    to exist.
    """
    if not root:
        return raw
    from pathlib import Path as _Path

    candidate = _Path(raw)
    if not candidate.is_absolute():
        return raw
    try:
        return candidate.relative_to(root).as_posix()
    except ValueError:
        return raw


def artifacts_from_tool_uses(
    blocks: Iterable[Any],
    *,
    root: str | Path | None = None,
) -> list[Artifact]:
    """Build the artifact list for one dispatch from its tool-use blocks.

    *blocks* is any iterable of objects carrying ``.name`` and ``.input``
    (the SDK's ``ToolUseBlock`` shape); anything without both is skipped,
    so the caller can pass the raw content list.

    One file yields one artifact no matter how many times the agent
    touched it, and the first action wins: a file that is created and
    then edited is ``file_written``, which is the truthful description of
    what happened to it over the dispatch. Order follows first touch, so
    the commit's file list reads in the order the agent worked.
    """
    artifacts: list[Artifact] = []
    seen: set[str] = set()

    for block in blocks:
        tool_name = getattr(block, "name", None)
        artifact_type = FILE_TOOL_ARTIFACT_TYPES.get(tool_name or "")
        if artifact_type is None:
            continue

        tool_input = getattr(block, "input", None)
        if not isinstance(tool_input, dict):
            continue
        raw_path = tool_input.get(_PATH_KEY)
        if not raw_path or not isinstance(raw_path, str):
            continue

        name = _relativize(raw_path, root)
        if name in seen:
            continue
        seen.add(name)
        artifacts.append(
            Artifact(
                name=name,
                content="",
                artifact_type=artifact_type,
                metadata={"tool": tool_name},
            )
        )

    return artifacts
