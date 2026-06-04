# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Packaging contract guard — freeze the version-truth + wheel-include surface.

This test parses ``pyproject.toml`` as text (no build, no install) and
asserts the load-bearing packaging facts that the reconcile staged-replay
locked in:

* The package version is the shipped truth ``1.0.1`` — NOT a pre-release
  label. PyPI ``bonfire-ai`` 1.0.1 is the authoritative version; the
  ``pyproject.toml`` must agree so the editable fallback in
  ``src/bonfire/__init__.py`` stays in lockstep.
* The trove classifier declares ``Development Status :: 5 -
  Production/Stable`` — the package is not alpha/beta.
* The dev-extra pins ``ruff==0.15.13`` exactly. CI's lint job runs both
  ``ruff check`` and ``ruff format --check``; a floating ruff version would
  silently re-format the tree under a newer release.
* The wheel-include list carries the non-Python data files that the
  package needs at runtime: the skill markdown, the integration ``.ism.md``
  manifests, the onboarding UI page, and the ``py.typed`` marker. Without
  these the built wheel ships an incomplete package.

The guard is deliberately string-based so it runs without a toml parser
on the test path and fails loudly the moment any of these contract facts
drift.
"""

from __future__ import annotations

from pathlib import Path

# Repo root: tests/unit/test_packaging_contract.py -> repo root is parents[2].
_PYPROJECT = Path(__file__).resolve().parents[2] / "pyproject.toml"


def _pyproject_text() -> str:
    return _PYPROJECT.read_text(encoding="utf-8")


def test_pyproject_exists() -> None:
    assert _PYPROJECT.is_file(), f"pyproject.toml not found at {_PYPROJECT}"


def test_version_is_shipped_truth() -> None:
    """Version must be 1.0.1 — the shipped PyPI truth, not a pre-release."""
    text = _pyproject_text()
    assert 'version = "1.0.1"' in text, (
        "pyproject.toml version must be exactly 1.0.1 (the shipped PyPI truth); "
        "do not regress to an alpha/beta label."
    )


def test_development_status_production_stable() -> None:
    """The trove classifier must declare Production/Stable, not alpha/beta."""
    text = _pyproject_text()
    assert "Development Status :: 5 - Production/Stable" in text, (
        "pyproject.toml must carry the 'Development Status :: 5 - Production/Stable' classifier."
    )


def test_ruff_pinned_exactly() -> None:
    """The dev-extra must pin ruff to the exact CI-matched version."""
    text = _pyproject_text()
    assert "ruff==0.15.13" in text, (
        "pyproject.toml dev-extra must pin 'ruff==0.15.13' exactly so local "
        "and CI lint/format agree."
    )


def test_wheel_include_carries_runtime_data_files() -> None:
    """The wheel-include list must carry every non-Python runtime data file."""
    text = _pyproject_text()
    required_includes = (
        "src/bonfire/skill/*.md",
        "src/bonfire/integrations/builtins/*.ism.md",
        "src/bonfire/onboard/ui.html",
        "src/bonfire/py.typed",
    )
    missing = [entry for entry in required_includes if entry not in text]
    assert not missing, (
        f"pyproject.toml wheel-include is missing required data files: {missing}. "
        "These must ship in the built wheel."
    )
