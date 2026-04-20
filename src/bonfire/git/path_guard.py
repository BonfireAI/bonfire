"""Path guard — absolute path detection and isolation for worktree safety.

Agents running in git worktrees can bypass isolation by using absolute paths.
PathGuard detects, reports, and optionally blocks absolute paths in agent output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "IsolationViolation",
    "PathGuard",
    "PathGuardError",
    "sanitize_prompt_paths",
]

# Dot-dot traversal patterns (Unix and Windows, including URL-encoded)
_TRAVERSAL_RE = re.compile(
    r"(?:^|[\\/])"  # start of string or separator
    r"(?:\.\.|%2[eE]%2[eE])"  # literal .. or URL-encoded %2e%2e
    r"(?:[\\/]|$)"  # separator or end of string
)


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IsolationViolation:
    """A single absolute-path violation detected in agent output."""

    path: str
    line_number: int | None
    severity: str  # "error" | "warning"


class PathGuardError(Exception):
    """Raised when PathGuard in 'block' mode detects absolute paths."""

    def __init__(self, message: str, violations: list[IsolationViolation]) -> None:
        super().__init__(message)
        self.violations = violations


# ---------------------------------------------------------------------------
# Detection patterns
# ---------------------------------------------------------------------------

# Unix absolute paths — requires a known directory anchor after the leading /
# Negative lookbehind prevents matching URLs (https://..., ftp://..., etc.)
_UNIX_PATH_RE = re.compile(
    r"(?<![a-zA-Z0-9+\-.:])"
    r"(/(?:home|tmp|var|etc|usr|opt|root|mnt|srv|proc|sys|dev|run|boot|lib|sbin|bin|snap|media|nix)/\S+)"
)

# Windows absolute paths — drive letter + backslash
_WINDOWS_PATH_RE = re.compile(r"([A-Z]:\\\S+)")


# ---------------------------------------------------------------------------
# PathGuard
# ---------------------------------------------------------------------------


class PathGuard:
    """Detects and guards against absolute paths in agent output."""

    @classmethod
    def is_traversal(cls, path: str) -> bool:
        """Return True if *path* contains ``..`` directory traversal.

        Detects:
        - Unix-style ``../`` or ``/..``
        - Windows-style ``..\\`` or ``\\..``
        - URL-encoded ``%2e%2e``
        """
        return bool(_TRAVERSAL_RE.search(path))

    @classmethod
    def contains_absolute_paths(cls, text: str) -> bool:
        """Return True if text contains any absolute path pattern."""
        return bool(cls.find_absolute_paths(text))

    @classmethod
    def find_absolute_paths(cls, text: str) -> list[str]:
        """Return deduplicated list of absolute paths found, in first-occurrence order."""
        if not text:
            return []

        found: list[str] = []
        seen: set[str] = set()

        for match in _UNIX_PATH_RE.finditer(text):
            path = match.group(1)
            if path not in seen:
                found.append(path)
                seen.add(path)

        for match in _WINDOWS_PATH_RE.finditer(text):
            path = match.group(1)
            if path not in seen:
                found.append(path)
                seen.add(path)

        return found

    @classmethod
    def make_relative(cls, absolute: str, project_root: Path) -> str:
        """Convert an absolute path to a project-relative string.

        Raises ValueError if path is outside the project root.
        """
        abs_path = Path(absolute.rstrip("/")).resolve()
        root = project_root.resolve()

        if abs_path == root:
            return "."

        try:
            relative = abs_path.relative_to(root)
        except ValueError:
            msg = f"Path '{absolute}' is outside the project root"
            raise ValueError(msg) from None

        return str(relative)


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def sanitize_prompt_paths(text: str, project_root: Path) -> str:
    """Replace absolute paths in text with project-relative equivalents.

    Paths outside project_root are left unchanged.
    """
    paths = PathGuard.find_absolute_paths(text)
    for path in paths:
        try:
            relative = PathGuard.make_relative(path, project_root)
            text = text.replace(path, relative)
        except ValueError:
            pass
    return text
