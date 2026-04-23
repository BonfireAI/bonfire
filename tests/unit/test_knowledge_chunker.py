"""RED tests — BON-341 W5.2 — `bonfire.knowledge.chunker` (innovative lens).

Sage D8.2 type locks:
- ``chunk_markdown(content, *, source_path, project_name="", git_hash="", max_chunk_size=2000) -> list[VaultEntry]``
- ``chunk_source_file(content, *, source_path, project_name="", git_hash="", max_chunk_size=2000) -> list[VaultEntry]``
- Each entry's ``entry_type == "code_chunk"``.
- Each entry's ``content_hash == content_hash(<its content>)``.
- ``metadata`` keys: ``chunk_index: int``, ``total_chunks: int``, ``header_chain: str``.
- ``tags``: markdown -> ``["chunk", "markdown"]``; .py -> ``["chunk", "python"]``;
  other source -> ``["chunk", "source"]``.

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations

import pytest

from bonfire.knowledge.chunker import chunk_markdown, chunk_source_file
from bonfire.knowledge.hasher import content_hash as _ch
from bonfire.protocols import VaultEntry


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------


class TestChunkMarkdownStructure:
    """Splitting by H1-H3 headers."""

    def test_chunk_markdown_splits_by_h1_h3_headers(self) -> None:
        md = (
            "# Alpha\n\nFirst section body.\n\n"
            "## Beta\n\nSecond section body.\n\n"
            "### Gamma\n\nThird section body.\n"
        )
        chunks = chunk_markdown(md, source_path="doc.md")
        assert len(chunks) == 3
        # Each section appears in exactly one chunk.
        contents = [c.content for c in chunks]
        assert any("Alpha" in c for c in contents)
        assert any("Beta" in c for c in contents)
        assert any("Gamma" in c for c in contents)

    # knight-a(innovative): h4+ headers should NOT split (contract is h1-h3 only).
    def test_chunk_markdown_does_not_split_at_h4(self) -> None:
        """H4+ headers stay within their parent section."""
        md = "# Top\n\nIntro.\n\n#### Deep\n\nDeep content.\n"
        chunks = chunk_markdown(md, source_path="doc.md")
        assert len(chunks) == 1
        assert "Deep" in chunks[0].content


class TestChunkMarkdownFrontmatter:
    def test_chunk_markdown_strips_yaml_frontmatter(self) -> None:
        md = "---\ntitle: test\nauthor: a\n---\n# Real Content\n\nBody.\n"
        chunks = chunk_markdown(md, source_path="doc.md")
        # Frontmatter should not appear in any chunk content.
        assert all("title: test" not in c.content for c in chunks)
        assert all("author: a" not in c.content for c in chunks)
        assert any("Real Content" in c.content for c in chunks)


class TestChunkMarkdownEdgeCases:
    """Empty-input and whitespace-only inputs return empty list."""

    def test_chunk_markdown_empty_returns_empty(self) -> None:
        assert chunk_markdown("", source_path="doc.md") == []

    @pytest.mark.parametrize("whitespace_only", ["", "   ", "\n\n\n", "\t\t", "   \n\n\n   "])
    def test_chunk_markdown_whitespace_only_returns_empty(
        self, whitespace_only: str
    ) -> None:
        """Innovative lens: parametrize multiple whitespace shapes."""
        assert chunk_markdown(whitespace_only, source_path="doc.md") == []

    def test_chunk_markdown_frontmatter_only_returns_empty(self) -> None:
        """Frontmatter stripped -> empty body -> zero chunks."""
        md = "---\ntitle: test\n---\n"
        assert chunk_markdown(md, source_path="doc.md") == []


class TestChunkMarkdownOversized:
    def test_chunk_markdown_oversized_section_splits_at_paragraph(self) -> None:
        """A section over max_chunk_size splits at paragraph boundaries."""
        body = "\n\n".join([f"Paragraph {i}. " + "x" * 500 for i in range(5)])
        md = f"# Big\n\n{body}\n"
        chunks = chunk_markdown(md, source_path="big.md", max_chunk_size=800)
        # Must produce >1 chunk because total body > 800.
        assert len(chunks) > 1


class TestChunkMarkdownMetadata:
    """Sage D8.2 metadata key locks + tag locks."""

    def test_chunk_markdown_entries_carry_header_chain_metadata(self) -> None:
        md = "# Top\n\n## Child\n\nContent.\n"
        chunks = chunk_markdown(md, source_path="doc.md")
        # At least one chunk's header_chain should reflect the nested path.
        chains = [c.metadata["header_chain"] for c in chunks]
        assert any("Top" in ch for ch in chains)

    def test_chunk_markdown_each_entry_has_content_hash(self) -> None:
        md = "# A\n\nContent A.\n\n# B\n\nContent B.\n"
        chunks = chunk_markdown(md, source_path="doc.md")
        assert chunks
        for c in chunks:
            assert c.content_hash, "content_hash must be populated"

    def test_chunk_markdown_content_hash_matches_knowledge_hasher(self) -> None:
        """Byte-stable: content_hash on each entry == hasher.content_hash(entry.content)."""
        md = "# Title\n\nBody text.\n"
        chunks = chunk_markdown(md, source_path="doc.md")
        for c in chunks:
            assert c.content_hash == _ch(c.content)

    def test_chunk_markdown_metadata_keys_are_locked(self) -> None:
        md = "# Heading\n\nParagraph.\n"
        chunks = chunk_markdown(md, source_path="doc.md")
        for c in chunks:
            assert "chunk_index" in c.metadata
            assert "total_chunks" in c.metadata
            assert "header_chain" in c.metadata
            assert isinstance(c.metadata["chunk_index"], int)
            assert isinstance(c.metadata["total_chunks"], int)
            assert isinstance(c.metadata["header_chain"], str)

    # knight-a(innovative): chunk_index invariant — monotonically 0..N-1.
    def test_chunk_markdown_chunk_index_is_contiguous(self) -> None:
        md = "# A\n\naaa\n\n# B\n\nbbb\n\n# C\n\nccc\n"
        chunks = chunk_markdown(md, source_path="doc.md")
        indices = [c.metadata["chunk_index"] for c in chunks]
        assert indices == list(range(len(chunks)))
        assert all(c.metadata["total_chunks"] == len(chunks) for c in chunks)

    def test_chunk_markdown_entry_type_is_code_chunk(self) -> None:
        chunks = chunk_markdown("# T\n\nBody.\n", source_path="doc.md")
        for c in chunks:
            assert c.entry_type == "code_chunk"

    def test_chunk_markdown_tags_are_chunk_markdown(self) -> None:
        chunks = chunk_markdown("# T\n\nBody.\n", source_path="doc.md")
        for c in chunks:
            assert c.tags == ["chunk", "markdown"]

    def test_chunk_markdown_propagates_provenance(self) -> None:
        chunks = chunk_markdown(
            "# T\n\nBody.\n",
            source_path="/src/doc.md",
            project_name="myproj",
            git_hash="deadbeef",
        )
        for c in chunks:
            assert c.source_path == "/src/doc.md"
            assert c.project_name == "myproj"
            assert c.git_hash == "deadbeef"


# ---------------------------------------------------------------------------
# Source
# ---------------------------------------------------------------------------


class TestChunkSourcePython:
    """Python sources split at class/def boundaries."""

    def test_chunk_source_file_splits_python_at_class_and_def(self) -> None:
        src = (
            "import os\n\n"
            "class Alpha:\n    pass\n\n"
            "def beta() -> None:\n    pass\n\n"
            "async def gamma() -> None:\n    pass\n"
        )
        chunks = chunk_source_file(src, source_path="mod.py")
        assert len(chunks) >= 2
        joined = " ".join(c.content for c in chunks)
        assert "class Alpha" in joined
        assert "def beta" in joined
        assert "async def gamma" in joined

    def test_chunk_source_file_tags_python_correctly(self) -> None:
        chunks = chunk_source_file(
            "class A:\n    pass\n\ndef f(): pass\n", source_path="m.py"
        )
        for c in chunks:
            assert c.tags == ["chunk", "python"]


class TestChunkSourceNonPython:
    """Non-Python sources fall back to size-based splitting."""

    def test_chunk_source_file_falls_back_to_size_for_non_python(self) -> None:
        """Long JS source splits purely by size (no class/def pattern)."""
        src = "\n".join([f"const x{i} = {i};" for i in range(200)])
        chunks = chunk_source_file(src, source_path="lib.js", max_chunk_size=400)
        # Size-based splitting should produce >1 chunk.
        assert len(chunks) > 1

    def test_chunk_source_file_tags_non_python_as_source(self) -> None:
        chunks = chunk_source_file("const x = 1;\n", source_path="lib.js")
        for c in chunks:
            assert c.tags == ["chunk", "source"]

    # knight-a(innovative): single-def python still chunks (size-based fallback).
    def test_chunk_source_file_single_python_def_uses_size_based_fallback(self) -> None:
        """One-def Python fails the >=2 threshold and falls back to size-split."""
        src = "def only() -> None:\n    pass\n"
        chunks = chunk_source_file(src, source_path="m.py")
        assert len(chunks) >= 1
        assert all(isinstance(c, VaultEntry) for c in chunks)


class TestChunkSourceMetadata:
    def test_chunk_source_file_metadata_has_chunk_index_and_total(self) -> None:
        src = (
            "class A:\n    pass\n\nclass B:\n    pass\n\nclass C:\n    pass\n"
        )
        chunks = chunk_source_file(src, source_path="m.py")
        total = len(chunks)
        for i, c in enumerate(chunks):
            assert c.metadata["chunk_index"] == i
            assert c.metadata["total_chunks"] == total

    def test_chunk_source_file_entry_type_is_code_chunk(self) -> None:
        chunks = chunk_source_file(
            "class A: pass\nclass B: pass\n", source_path="m.py"
        )
        for c in chunks:
            assert c.entry_type == "code_chunk"

    def test_chunk_source_file_returns_vault_entries(self) -> None:
        chunks = chunk_source_file(
            "class Foo:\n    pass\n\ndef bar() -> None:\n    pass\n",
            source_path="module.py",
        )
        assert isinstance(chunks, list)
        assert len(chunks) >= 1
        for c in chunks:
            assert isinstance(c, VaultEntry)

    def test_chunk_source_file_empty_returns_empty(self) -> None:
        assert chunk_source_file("", source_path="m.py") == []
        assert chunk_source_file("   \n\n\n", source_path="m.py") == []

    # knight-a(innovative): byte-stable hash for source chunks too.
    def test_chunk_source_file_content_hash_is_byte_stable(self) -> None:
        src = "class A:\n    pass\n\nclass B:\n    pass\n"
        chunks = chunk_source_file(src, source_path="m.py")
        for c in chunks:
            assert c.content_hash == _ch(c.content)
