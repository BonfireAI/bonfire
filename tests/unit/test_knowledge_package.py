"""BON-341 RED — Knight B (conservative) — bonfire.knowledge package.

Package-level surface: ``__all__``, factory import, signature defaults.
Validates D3.1 + D3.2 defaults and D3.3 factory name preservation.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations

import inspect


class TestKnowledgePackage:
    def test_package_imports_without_error(self):
        import bonfire.knowledge

        assert bonfire.knowledge is not None

    def test_exports_get_vault_backend(self):
        import bonfire.knowledge

        assert hasattr(bonfire.knowledge, "get_vault_backend")
        assert callable(bonfire.knowledge.get_vault_backend)

    def test_get_vault_backend_default_signature(self):
        from bonfire.knowledge import get_vault_backend

        sig = inspect.signature(get_vault_backend)
        # Locked defaults per D3.1 + D3.2.
        assert sig.parameters["backend"].default == "memory"
        assert sig.parameters["embedding_provider"].default == "mock"
