"""Tests asserting the package docstring names the extension surface.

Locks the contract that ``bonfire.__doc__`` declaratively names the
four protocols (``AgentBackend``, ``VaultBackend``, ``QualityGate``,
``StageHandler``), the two supporting value types (``DispatchOptions``,
``VaultEntry``), and points at the canonical module
``bonfire.protocols``.

No imports are added at the package root; this is documentation only.
"""

from __future__ import annotations

import bonfire


class TestPackageDocstring:
    """The package-root docstring exposes the extension surface."""

    def test_docstring_is_present(self) -> None:
        assert bonfire.__doc__, "bonfire.__doc__ must be non-empty"

    def test_docstring_names_agent_backend(self) -> None:
        assert "AgentBackend" in bonfire.__doc__

    def test_docstring_names_vault_backend(self) -> None:
        assert "VaultBackend" in bonfire.__doc__

    def test_docstring_names_quality_gate(self) -> None:
        assert "QualityGate" in bonfire.__doc__

    def test_docstring_names_stage_handler(self) -> None:
        assert "StageHandler" in bonfire.__doc__

    def test_docstring_names_dispatch_options(self) -> None:
        assert "DispatchOptions" in bonfire.__doc__

    def test_docstring_names_vault_entry(self) -> None:
        assert "VaultEntry" in bonfire.__doc__

    def test_docstring_distinguishes_protocols_from_value_types(self) -> None:
        doc = bonfire.__doc__.lower()
        assert "protocols" in doc
        assert "value types" in doc

    def test_docstring_points_at_canonical_module(self) -> None:
        assert "bonfire.protocols" in bonfire.__doc__
