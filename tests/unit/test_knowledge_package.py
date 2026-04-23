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


class TestKnowledgeSubmodulesImport:
    """Innovative: every Sage D2 submodule importable."""

    def test_knowledge_hasher_importable(self) -> None:
        from bonfire.knowledge import hasher

        assert hasattr(hasher, "content_hash")
        assert hasattr(hasher, "file_hash")

    def test_knowledge_memory_importable(self) -> None:
        from bonfire.knowledge import memory

        assert hasattr(memory, "InMemoryVaultBackend")

    def test_knowledge_chunker_importable(self) -> None:
        from bonfire.knowledge import chunker

        assert hasattr(chunker, "chunk_markdown")
        assert hasattr(chunker, "chunk_source_file")

    def test_knowledge_scanner_importable(self) -> None:
        from bonfire.knowledge import scanner

        assert hasattr(scanner, "ProjectScanner")
        assert hasattr(scanner, "FileInfo")
        assert hasattr(scanner, "ModuleSignature")
        assert hasattr(scanner, "ProjectManifest")

    def test_knowledge_embeddings_importable(self) -> None:
        from bonfire.knowledge import embeddings

        assert hasattr(embeddings, "EmbeddingProvider")
        assert hasattr(embeddings, "get_embedder")

    def test_knowledge_mock_embedder_importable(self) -> None:
        from bonfire.knowledge import mock_embedder

        assert hasattr(mock_embedder, "MockEmbedder")

    def test_knowledge_ingest_importable(self) -> None:
        from bonfire.knowledge import ingest

        assert hasattr(ingest, "ingest_markdown")
        assert hasattr(ingest, "ingest_session")
        assert hasattr(ingest, "retrieve_context")

    def test_knowledge_consumer_importable(self) -> None:
        from bonfire.knowledge import consumer

        assert hasattr(consumer, "KnowledgeIngestConsumer")

    def test_knowledge_backfill_importable(self) -> None:
        from bonfire.knowledge import backfill

        assert hasattr(backfill, "backfill_sessions")
        assert hasattr(backfill, "backfill_memory")
        assert hasattr(backfill, "backfill_all")
