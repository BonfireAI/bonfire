#!/usr/bin/env python3
"""Release version-truth guard: a pushed tag must equal 'v' + declared version.

Run by ``release.yml`` before anything is built or published. Exits 0 iff the
tag (argv or ``GITHUB_REF``) matches ``pyproject.toml``'s ``project.version``.
Every failure is closed and typed: a stable code, both observed values, and
what to do next. Stdlib only."""

from __future__ import annotations

import argparse
import os
import sys
import tomllib


def _fail(code: str, message: str, remedy: str) -> int:
    """Print a typed, self-describing error to stderr and return exit code 1."""
    print(f"{code}: {message}", file=sys.stderr)
    print(f"  what to do: {remedy}", file=sys.stderr)
    print("  retryable: false (fix the inputs, then re-tag or re-run)", file=sys.stderr)
    return 1


def _resolve_tag(cli_tag: str | None) -> str:
    """Tag from argv wins; otherwise strip the GITHUB_REF tag prefix."""
    if cli_tag is not None:
        return cli_tag
    ref = os.environ.get("GITHUB_REF", "")
    prefix = "refs/tags/"
    return ref.removeprefix(prefix) if ref.startswith(prefix) else ""


def _read_declared_version(pyproject_path: str) -> str | None:
    """Return ``project.version`` from pyproject.toml, or None if unreadable."""
    try:
        with open(pyproject_path, "rb") as fh:
            data = tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError):
        return None
    version = data.get("project", {}).get("version")
    return version if isinstance(version, str) and version else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", nargs="?", default=None, help="tag name (e.g. v0.1.0a2)")
    parser.add_argument("--pyproject", default="pyproject.toml", help="path to pyproject.toml")
    args = parser.parse_args(argv)

    tag = _resolve_tag(args.tag)
    if not tag or not tag.startswith("v") or len(tag) < 2:
        return _fail(
            "RELEASE_TAG_MALFORMED",
            f"release tag {tag!r} is not a 'v'-prefixed version tag",
            "push a tag shaped like vX.Y.Z (or set GITHUB_REF to refs/tags/vX.Y.Z)",
        )

    version = _read_declared_version(args.pyproject)
    if version is None:
        return _fail(
            "RELEASE_PYPROJECT_UNREADABLE",
            f"could not read project.version from {args.pyproject!r}",
            "run from the repo root with a valid pyproject.toml declaring project.version",
        )

    expected = f"v{version}"
    if tag != expected:
        return _fail(
            "RELEASE_TAG_VERSION_MISMATCH",
            f"tag {tag!r} != declared version {version!r} (expected tag {expected!r})",
            "either re-tag with the declared version, or bump pyproject.toml and tag that commit",
        )

    print(f"release version-truth guard OK: tag {tag!r} == 'v' + project.version {version!r}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
