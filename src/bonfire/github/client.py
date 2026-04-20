"""GitHubClient — async wrapper around the gh CLI.

Thin client: no ABC, no intermediate models. Parses gh JSON directly.
"""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

from pydantic import BaseModel, Field


class PRInfo(BaseModel, frozen=True, extra="forbid"):
    """Immutable pull-request metadata.

    Fields map to the output of ``gh pr view --json``.
    """

    number: int = Field(gt=0)
    url: str
    title: str
    state: Literal["open", "closed", "merged"]
    head_branch: str
    base_branch: str


# Map gh CLI state strings (uppercase) to normalized lowercase values.
_STATE_MAP = {
    "OPEN": "open",
    "CLOSED": "closed",
    "MERGED": "merged",
}


def _parse_pr(data: dict) -> PRInfo:
    """Convert gh CLI JSON output into a PRInfo model."""
    raw_state = data.get("state", "OPEN")
    state = _STATE_MAP.get(raw_state, raw_state.lower())
    return PRInfo(
        number=data["number"],
        url=data.get("url", ""),
        title=data.get("title", ""),
        state=state,
        head_branch=data.get("headRefName", ""),
        base_branch=data.get("baseRefName", ""),
    )


def detect_github_repo(repo_path: str | Path = ".") -> str:
    """Detect the GitHub ``owner/repo`` slug from the git remote.

    Returns an empty string if detection fails (no remote, not GitHub, etc.).
    """
    import re
    import subprocess

    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True,
            text=True,
            cwd=str(repo_path),
        )
        if result.returncode != 0:
            return ""
        match = re.search(r"github\.com[:/](.+?)(?:\.git)?$", result.stdout.strip())
        return match.group(1) if match else ""
    except FileNotFoundError:
        return ""


class GitHubClient:
    """Async GitHub client that shells out to the gh CLI.

    Parameters
    ----------
    repo:
        GitHub repository in ``owner/repo`` format.
    """

    def __init__(self, repo: str) -> None:
        self._repo = repo

    async def _run_gh(self, args: list[str]) -> tuple[int, str, str]:
        """Execute a gh CLI command and return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            "gh",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout_bytes, stderr_bytes = await proc.communicate()
        return (
            proc.returncode or 0,
            stdout_bytes.decode(),
            stderr_bytes.decode(),
        )

    def _check(self, returncode: int, stderr: str) -> None:
        """Raise RuntimeError if the gh command failed."""
        if returncode != 0:
            raise RuntimeError(stderr.strip() or f"gh exited with code {returncode}")

    async def create_pr(
        self,
        title: str,
        head: str,
        base: str,
        body: str = "",
    ) -> PRInfo:
        """Create a pull request via ``gh pr create``."""
        args = [
            "pr",
            "create",
            "-R",
            self._repo,
            "--title",
            title,
            "--head",
            head,
            "--base",
            base,
            "--json",
            "number,url,title,state,headRefName,baseRefName",
        ]
        if body:
            args.extend(["--body", body])
        rc, stdout, stderr = await self._run_gh(args)
        self._check(rc, stderr)
        return _parse_pr(json.loads(stdout))

    async def get_pr(self, number: int) -> PRInfo:
        """Fetch a pull request by number via ``gh pr view``."""
        args = [
            "pr",
            "view",
            str(number),
            "-R",
            self._repo,
            "--json",
            "number,url,title,state,headRefName,baseRefName",
        ]
        rc, stdout, stderr = await self._run_gh(args)
        self._check(rc, stderr)
        return _parse_pr(json.loads(stdout))

    async def merge_pr(self, number: int) -> None:
        """Merge a pull request via ``gh pr merge``."""
        args = [
            "pr",
            "merge",
            str(number),
            "-R",
            self._repo,
            "--merge",
        ]
        rc, _, stderr = await self._run_gh(args)
        self._check(rc, stderr)

    async def close_issue(self, issue_number: int) -> None:
        """Close an issue via ``gh issue close``."""
        args = [
            "issue",
            "close",
            str(issue_number),
            "-R",
            self._repo,
        ]
        rc, _, stderr = await self._run_gh(args)
        self._check(rc, stderr)

    async def add_comment(self, issue_number: int, body: str) -> None:
        """Add a comment to an issue or PR via ``gh issue comment``."""
        args = [
            "issue",
            "comment",
            str(issue_number),
            "-R",
            self._repo,
            "--body",
            body,
        ]
        rc, _, stderr = await self._run_gh(args)
        self._check(rc, stderr)

    async def get_pr_diff(self, number: int) -> str:
        """Get the unified diff for a PR via ``gh pr diff``."""
        args = [
            "pr",
            "diff",
            str(number),
            "-R",
            self._repo,
        ]
        rc, stdout, stderr = await self._run_gh(args)
        self._check(rc, stderr)
        return stdout

    async def get_pr_files(self, number: int) -> list[dict]:
        """Get changed files metadata for a PR via ``gh pr view --json files``."""
        args = [
            "pr",
            "view",
            str(number),
            "-R",
            self._repo,
            "--json",
            "files",
        ]
        rc, stdout, stderr = await self._run_gh(args)
        self._check(rc, stderr)
        data = json.loads(stdout)
        return data.get("files", [])

    async def post_review(
        self,
        number: int,
        body: str,
        *,
        event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"] = "COMMENT",
    ) -> None:
        """Post a structured review on a PR via ``gh pr review``.

        Parameters
        ----------
        event:
            APPROVE, REQUEST_CHANGES, or COMMENT.
        """
        flag_map = {
            "APPROVE": "--approve",
            "REQUEST_CHANGES": "--request-changes",
            "COMMENT": "--comment",
        }
        args = [
            "pr",
            "review",
            str(number),
            "-R",
            self._repo,
            flag_map[event],
            "--body",
            body,
        ]
        rc, _, stderr = await self._run_gh(args)
        self._check(rc, stderr)
