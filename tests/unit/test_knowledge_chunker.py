"""BON-341 RED — Knight B (conservative) — bonfire.knowledge.chunker.

Covers ``chunk_markdown`` and ``chunk_source_file`` per Sage D8.2/D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations

from bonfire.knowledge.chunker import chunk_markdown, chunk_source_file
from bonfire.knowledge.hasher import content_hash


class TestChunkMarkdown:
    def test_chunk_markdown_splits_by_h1_h3_headers(self):
        md = (
            "# Top\nalpha\n\n"
            "## Sub\nbeta\n\n"
            "### Deep\ngamma\n\n"
            "## Sub Two\ndelta\n"
        )
        entries = chunk_markdown(md, source_path="docs/x.md")
        assert len(entries) >= 2
        assert all(e.entry_type == "code_chunk" for e in entries)

    def test_chunk_markdown_strips_yaml_frontmatter(self):
        md = "---\ntitle: hello\n---\n# Real Content\nbody\n"
        entries = chunk_markdown(md, source_path="docs/x.md")
        assert all("title: hello" not in e.content for e in entries)

    def test_chunk_markdown_empty_returns_empty(self):
        assert chunk_markdown("", source_path="docs/x.md") == []

    def test_chunk_markdown_oversized_section_splits_at_paragraph(self):
        big_paragraph = ("word " * 500).strip()
        md = f"# Only\n{big_paragraph}\n\n{big_paragraph}\n"
        entries = chunk_markdown(md, source_path="docs/big.md", max_chunk_size=200)
        assert len(entries) >= 2

    def test_chunk_markdown_entries_carry_header_chain_metadata(self):
        md = "# Top\n## Sub\n### Deeper\ncontent body\n"
        entries = chunk_markdown(md, source_path="docs/x.md")
        assert len(entries) >= 1
        # header_chain metadata key LOCKED per Sage D8.2.
        assert all("header_chain" in e.metadata for e in entries)
        assert all(isinstance(e.metadata["header_chain"], str) for e in entries)

    def test_chunk_markdown_each_entry_has_content_hash(self):
        md = "# Heading\nbody of text\n"
        entries = chunk_markdown(md, source_path="docs/x.md")
        for entry in entries:
            assert entry.content_hash == content_hash(entry.content)


class TestChunkSourceFile:
    def test_chunk_source_file_splits_python_at_class_and_def(self):
        src = (
            "class Foo:\n"
            "    def bar(self):\n"
            "        return 1\n"
            "\n"
            "def baz():\n"
            "    return 2\n"
        )
        entries = chunk_source_file(src, source_path="module.py")
        assert len(entries) >= 1
        assert all(e.entry_type == "code_chunk" for e in entries)

    def test_chunk_source_file_falls_back_to_size_for_non_python(self):
        text = "line\n" * 2000
        entries = chunk_source_file(text, source_path="notes.txt", max_chunk_size=500)
        assert len(entries) >= 2

    def test_chunk_source_file_tags_python_correctly(self):
        src = "def foo():\n    return 1\n"
        entries = chunk_source_file(src, source_path="m.py")
        assert len(entries) >= 1
        assert "python" in entries[0].tags
        assert "chunk" in entries[0].tags

    def test_chunk_source_file_tags_non_python_as_source(self):
        text = "plain text content\n"
        entries = chunk_source_file(text, source_path="notes.txt")
        assert len(entries) >= 1
        assert "source" in entries[0].tags
        assert "chunk" in entries[0].tags

    def test_chunk_source_file_metadata_has_chunk_index_and_total(self):
        text = "line\n" * 3000
        entries = chunk_source_file(text, source_path="big.txt", max_chunk_size=500)
        assert len(entries) >= 2
        total = len(entries)
        for i, entry in enumerate(entries):
            assert entry.metadata["chunk_index"] == i
            assert entry.metadata["total_chunks"] == total
