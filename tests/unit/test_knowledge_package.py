"""RED tests — BON-341 W5.2 — `bonfire.knowledge` package surface.

Sage D8.3 required tests:
- test_package_imports_without_error
- test_exports_get_vault_backend
- test_get_vault_backend_default_signature

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

import inspect


class TestKnowledgePackage:
    def test_package_imports_without_error(self) -> None:
        import bonfire.knowledge

        assert bonfire.knowledge is not None

    def test_exports_get_vault_backend(self) -> None:
        """D3.3: factory name preserved."""
        from bonfire.knowledge import get_vault_backend

        assert callable(get_vault_backend)

    def test_get_vault_backend_default_signature(self) -> None:
        """Every param is keyword-only; locked defaults match Sage D3.1/D3.2."""
        from bonfire.knowledge import get_vault_backend

        sig = inspect.signature(get_vault_backend)
        assert sig.parameters["backend"].default == "memory"
        assert sig.parameters["embedding_provider"].default == "mock"
        assert sig.parameters["enabled"].default is True
        assert sig.parameters["embedding_dim"].default == 768
