"""GitHub API integration — PR creation, issue management."""

from bonfire.github.client import GitHubClient, PRInfo, PRSummary, detect_github_repo
from bonfire.github.mock import MockGitHubClient

__all__ = [
    "GitHubClient",
    "MockGitHubClient",
    "PRInfo",
    "PRSummary",
    "detect_github_repo",
]
