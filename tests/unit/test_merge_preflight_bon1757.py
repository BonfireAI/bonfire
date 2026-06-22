"""BON-1757: narrowed broad-except sites in merge_preflight.

Covers the three BLE001 sites that were narrowed/deleted:

- SITE 2 (``detect_sibling_prs``): the broad arm was folded into
  ``except (RuntimeError, OSError)``. Proves an ``OSError`` from
  ``list_open_prs`` still yields the fail-safe ``({}, "error")`` return.
- SITE 3 (``_classify_preflight_run`` sibling-diff fetch loop): narrowed to
  ``except (RuntimeError, OSError)``. Proves a ``RuntimeError`` raised while
  fetching ONE sibling's diff is caught and the preflight gracefully skips
  that sibling and continues to classification instead of crashing.

SITE 1 (``parse_pytest_junit_xml``) deleted its redundant broad arm entirely
(the prior ``OSError`` + ``ET.ParseError`` arms already cover realistic parse
failures), so there is no narrowed type left to prove for it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

try:
    from bonfire.handlers.merge_preflight import (  # type: ignore[import-not-found]  # type: ignore[import-not-found]
        MergePreflightHandler,
        PreflightVerdict,
        _PytestResult,
        detect_sibling_prs,
    )
except ImportError:  # pragma: no cover
    MergePreflightHandler = None  # type: ignore[assignment,misc]

pytestmark = pytest.mark.skipif(
    MergePreflightHandler is None,
    reason="v0.1 RED: MergePreflightHandler not yet implemented",
)


@dataclass
class _Info:
    """Duck-typed ScratchWorktreeInfo (only .path + .base_sha are read)."""

    path: Path = Path("/tmp/preflight-bon1757")  # noqa: S108
    branch_name: str = "bonfire/preflight-pr-42-deadbeef"
    base_sha: str = "a" * 40


# --- SITE 2: detect_sibling_prs OSError -> fail-safe ({}, "error") ----------


class TestDetectSiblingPrsOSError:
    async def test_oserror_from_client_returns_error_status(self) -> None:
        """OSError from list_open_prs is caught by the folded
        ``(RuntimeError, OSError)`` arm and yields the fail-safe return."""

        class _OSErrorClient:
            async def list_open_prs(self, base: str, *, exclude: int | None = None) -> Any:
                raise OSError("gh socket gone")

        files_by_pr, status = await detect_sibling_prs(
            _OSErrorClient(), "master", current_pr_number=1
        )
        assert files_by_pr == {}
        assert status == "error"


# --- SITE 3: sibling-diff fetch RuntimeError -> graceful skip + continue ----


class _GithubClientRaisingOnSibling:
    """get_pr_diff succeeds for the current PR, raises for the sibling."""

    def __init__(self, *, current_pr: int, sibling_pr: int) -> None:
        self._current_pr = current_pr
        self._sibling_pr = sibling_pr
        self.diff_calls: list[int] = []

    async def get_pr_diff(self, pr_number: int) -> str:
        self.diff_calls.append(pr_number)
        if pr_number == self._sibling_pr:
            raise RuntimeError("gh pr diff exploded for sibling")
        return "diff --git a/x b/x\n"


def _make_handler(github_client: Any) -> Any:
    return MergePreflightHandler(
        github_client=github_client,
        scratch_worktree_factory=object(),
        repo_path=Path("/tmp/repo"),  # noqa: S108
        base_branch="master",
    )


class TestSiblingDiffFetchGracefulSkip:
    async def test_sibling_runtime_error_skips_and_continues(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A RuntimeError from get_pr_diff(sibling) is caught; the sibling is
        skipped (its diff never applied) and the run reaches classification
        rather than crashing the preflight."""
        current_pr, sibling_pr = 42, 17
        gh = _GithubClientRaisingOnSibling(current_pr=current_pr, sibling_pr=sibling_pr)
        handler = _make_handler(gh)

        applied_diffs: list[str] = []

        async def _fake_apply(self: Any, diff_text: str, path: Path) -> None:
            applied_diffs.append(diff_text)

        async def _fake_run_pytest(self: Any, path: Path) -> Any:
            return _PytestResult(
                returncode=0,
                duration_seconds=0.0,
                stdout_tail="",
                junit_xml_path=Path("/nonexistent/junit.xml"),
            )

        async def _fake_baseline(self: Any, base_sha: str) -> frozenset[Any]:
            return frozenset()

        monkeypatch.setattr(MergePreflightHandler, "_apply_diff_to_worktree", _fake_apply)
        monkeypatch.setattr(MergePreflightHandler, "_run_pytest_in_worktree", _fake_run_pytest)
        monkeypatch.setattr(MergePreflightHandler, "_get_baseline_failures", _fake_baseline)

        # Must NOT raise even though the sibling's get_pr_diff raises.
        result = await handler._classify_preflight_run(
            info=_Info(),
            pr_number=current_pr,
            sibling_files={sibling_pr: frozenset({"src/x.py"})},
            sibling_status="ok",
        )

        # Reached classification (empty failures + rc 0 -> GREEN).
        assert result.verdict is PreflightVerdict.GREEN
        # The sibling was attempted but its diff was never applied (skipped).
        assert sibling_pr in gh.diff_calls
        assert applied_diffs == ["diff --git a/x b/x\n"]  # only the current PR's diff
