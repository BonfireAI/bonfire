# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

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
