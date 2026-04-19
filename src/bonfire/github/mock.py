"""MockGitHubClient — in-memory fake with call recording.

Same async interface as GitHubClient. Auto-incrementing PR numbers.
No bonfire imports beyond github/.
"""

from __future__ import annotations

from typing import Literal

from bonfire.github.client import PRInfo


class MockGitHubClient:
    """In-memory mock of GitHubClient for testing.

    Attributes
    ----------
    actions:
        Ordered list of action dicts recording every operation.
    """

    def __init__(self) -> None:
        self._prs: dict[int, PRInfo] = {}
        self._next_number: int = 1
        self.actions: list[dict] = []

    async def create_pr(
        self,
        title: str,
        head: str,
        base: str,
        body: str = "",
    ) -> PRInfo:
        """Create a fake PR, store it, and return PRInfo."""
        if not title.strip():
            raise ValueError("title must not be empty")
        if not head.strip():
            raise ValueError("head must not be empty")

        number = self._next_number
        self._next_number += 1
        url = f"https://github.com/mock/repo/pull/{number}"

        pr = PRInfo(
            number=number,
            url=url,
            title=title,
            state="open",
            head_branch=head,
            base_branch=base,
        )
        self._prs[number] = pr
        self.actions.append(
            {
                "type": "create_pr",
                "number": number,
                "title": title,
                "head": head,
                "base": base,
                "body": body,
            }
        )
        return pr

    async def get_pr(self, number: int) -> PRInfo:
        """Retrieve a stored PR by number. Raises KeyError if not found."""
        if number not in self._prs:
            raise KeyError(f"PR #{number} not found")
        return self._prs[number]

    async def merge_pr(self, number: int) -> None:
        """Mark a PR as merged. Raises KeyError/ValueError as appropriate."""
        if number not in self._prs:
            raise KeyError(f"PR #{number} not found")
        pr = self._prs[number]
        if pr.state == "merged":
            raise ValueError(f"PR #{number} already merged")
        if pr.state != "open":
            raise ValueError(f"PR #{number} not open")
        self._prs[number] = pr.model_copy(update={"state": "merged"})
        self.actions.append({"type": "merge_pr", "number": number})

    async def close_issue(self, issue_number: int) -> None:
        """Record an issue close action."""
        self.actions.append(
            {
                "type": "close_issue",
                "issue_number": issue_number,
            }
        )

    async def add_comment(self, issue_number: int, body: str) -> None:
        """Record a comment action."""
        self.actions.append(
            {
                "type": "add_comment",
                "issue_number": issue_number,
                "body": body,
            }
        )

    async def get_pr_diff(self, number: int) -> str:
        """Return a canned diff for testing."""
        self.actions.append({"type": "get_pr_diff", "number": number})
        return (
            "diff --git a/src/example.py b/src/example.py\n"
            "--- a/src/example.py\n"
            "+++ b/src/example.py\n"
            "@@ -1,3 +1,5 @@\n"
            " def hello():\n"
            "-    pass\n"
            "+    return 'world'\n"
            "+\n"
            "+def goodbye():\n"
            "+    return 'farewell'\n"
        )

    async def get_pr_files(self, number: int) -> list[dict]:
        """Return canned file metadata for testing."""
        self.actions.append({"type": "get_pr_files", "number": number})
        return [{"path": "src/example.py", "additions": 3, "deletions": 1}]

    async def post_review(
        self,
        number: int,
        body: str,
        *,
        event: Literal["APPROVE", "REQUEST_CHANGES", "COMMENT"] = "COMMENT",
    ) -> None:
        """Record a review action."""
        self.actions.append(
            {
                "type": "post_review",
                "number": number,
                "body": body,
                "event": event,
            }
        )
