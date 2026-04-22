"""BON-342 W5.3 RED — ArchitectHandler canonical synthesis.

Sage-synthesized from Knight A (Conservative Porter) + Knight B
(Generic-Vocabulary Modernizer).

Decisions locked here:

- **D1 ADOPT `analyst`**: Sage arbitration on the architect generic role.
  - ``AgentRole.ANALYST = "analyst"`` added to ``bonfire.agent.roles``.
  - ``ROLE_DISPLAY["analyst"] = DisplayNames("Analysis Agent", "Architect")``
    added to ``bonfire.naming``.
  - architect handler exposes ``ROLE: AgentRole = AgentRole.ANALYST``.
  - Rationale: the canonical v0.1 subsystem directory is
    ``src/bonfire/analysis/`` — this anchors "analyst" as the profession
    housed by that module. Layer-1 must be profession-neutral (noun),
    and "analyst" is profession-like where "scanner" is tool-like and
    "architect" (Knight B's proposal) IS the gamified display.
- D2 ADOPT: module-level ``ROLE: AgentRole`` constant.
- D3 ADOPT: no ``"Architect"`` title-cased gamified literal in code body.
- Vault/chunker/scanner dependencies remain xfail-gated until the vault
  port ticket (BON-W5.3-vault-port) lands.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from pathlib import Path
from typing import Any

import pytest

# --- v0.1-tolerant imports ---------------------------------------------------

try:
    from bonfire.handlers.architect import ArchitectHandler  # type: ignore[import-not-found]

    _HANDLER_PRESENT = True
except ImportError:  # pragma: no cover
    ArchitectHandler = None  # type: ignore[assignment,misc]
    _HANDLER_PRESENT = False


try:
    from bonfire.vault.memory import InMemoryVaultBackend  # type: ignore[import-not-found]

    _VAULT_PRESENT = True
except ImportError:  # pragma: no cover
    InMemoryVaultBackend = None  # type: ignore[assignment,misc]
    _VAULT_PRESENT = False


try:
    from bonfire.vault.chunker import (  # type: ignore[import-not-found]
        chunk_markdown,
        chunk_source_file,
    )

    _CHUNKER_PRESENT = True
except ImportError:  # pragma: no cover
    chunk_markdown = None  # type: ignore[assignment]
    chunk_source_file = None  # type: ignore[assignment]
    _CHUNKER_PRESENT = False


try:
    from bonfire.vault.scanner import ProjectScanner  # type: ignore[import-not-found]

    _SCANNER_PRESENT = True
except ImportError:  # pragma: no cover
    ProjectScanner = None  # type: ignore[assignment,misc]
    _SCANNER_PRESENT = False


from bonfire.agent.roles import AgentRole
from bonfire.models.envelope import Envelope, TaskStatus
from bonfire.models.plan import StageSpec
from bonfire.naming import ROLE_DISPLAY

_HANDLER_XFAIL = pytest.mark.xfail(
    condition=not _HANDLER_PRESENT,
    reason=("v0.1 gap: bonfire.handlers.architect.ArchitectHandler not yet ported"),
    strict=False,
)

_VAULT_XFAIL = pytest.mark.xfail(
    condition=not _VAULT_PRESENT,
    reason=(
        "v0.1 gap: bonfire.vault.memory.InMemoryVaultBackend not yet ported — "
        "deferred to BON-W5.3-vault-port"
    ),
    strict=False,
)

_CHUNKER_XFAIL = pytest.mark.xfail(
    condition=not _CHUNKER_PRESENT,
    reason=("v0.1 gap: bonfire.vault.chunker not yet ported — deferred to BON-W5.3-vault-port"),
    strict=False,
)

_SCANNER_XFAIL = pytest.mark.xfail(
    condition=not _SCANNER_PRESENT,
    reason=(
        "v0.1 gap: bonfire.vault.scanner.ProjectScanner not yet ported — "
        "deferred to BON-W5.3-vault-port"
    ),
    strict=False,
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


class _FakeVault:
    """VaultBackend fake recording exists/store calls."""

    def __init__(self, *, pre_existing_hashes: set[str] | None = None) -> None:
        self.stored: list[Any] = []
        self.exists_checks: list[str] = []
        self._pre_existing = pre_existing_hashes or set()

    async def exists(self, content_hash: str) -> bool:
        self.exists_checks.append(content_hash)
        return content_hash in self._pre_existing

    async def store(self, entry: Any) -> None:
        self.stored.append(entry)

    async def query(self, query: str, *, limit: int = 5, entry_type: Any = None) -> list[Any]:
        return []

    async def get_by_source(self, source_path: str) -> list[Any]:
        return []


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def simple_project(tmp_path):
    """Minimal project: one Python file + README + __pycache__ noise."""
    src = tmp_path / "src"
    src.mkdir()
    (src / "main.py").write_text(
        '"""Main module."""\n\nclass App:\n    pass\n\ndef run() -> None:\n    pass\n'
    )
    (tmp_path / "README.md").write_text("# Project\n\nDescription.\n")
    (tmp_path / "__pycache__").mkdir()
    (tmp_path / "__pycache__" / "main.cpython-312.pyc").write_bytes(b"\x00")
    return tmp_path


@pytest.fixture
def project_root(tmp_path: Path) -> Path:
    """Slimmer project skeleton used by Knight B tests."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "hello.py").write_text("def greet():\n    return 'hi'\n")
    (tmp_path / "README.md").write_text("# Project\n\nA tiny project.\n")
    return tmp_path


@pytest.fixture
def vault() -> Any:
    """Return a real InMemoryVaultBackend if available; else the fake."""
    if InMemoryVaultBackend is not None:
        return InMemoryVaultBackend()
    return _FakeVault()


@pytest.fixture
def architect_envelope() -> Envelope:
    return Envelope(task="Scan project for vault ingestion", context="architect stage")


@pytest.fixture
def architect_stage() -> StageSpec:
    """Architect stage spec.

    D1-locked: stage.role = "analyst" (Sage arbitration).
    """
    return StageSpec(
        name="architect",
        agent_name="scanner",
        role="analyst",
        handler_name="architect",
    )


@pytest.fixture
def handler(vault: Any, project_root: Path) -> Any:
    """Constructed ArchitectHandler. Skipped if handler module not yet ported."""
    if ArchitectHandler is None:
        pytest.skip("ArchitectHandler not yet ported")
    return ArchitectHandler(
        vault=vault,
        project_root=project_root,
        project_name="testproject",
        git_hash="abc123",
    )


# ---------------------------------------------------------------------------
# GENERIC-VOCABULARY DISCIPLINE (D1 + D2 + D3)
# ---------------------------------------------------------------------------


class TestGenericVocabularyDiscipline:
    """Sage D1 decision: architect -> AgentRole.ANALYST."""

    def test_agent_role_has_analyst_member(self) -> None:
        """D1: AgentRole.ANALYST = 'analyst' must exist."""
        assert hasattr(AgentRole, "ANALYST"), (
            "Sage D1: AgentRole.ANALYST must exist. "
            "If Warrior hasn't landed it yet, open BON-W5.3-analyst-role and wire "
            "naming.py + roles.py before the Architect handler can be ported."
        )
        assert AgentRole.ANALYST == "analyst"

    def test_role_display_has_analyst_entry(self) -> None:
        """D1: ROLE_DISPLAY["analyst"] maps to "Analysis Agent" / "Architect"."""
        assert "analyst" in ROLE_DISPLAY, (
            "Sage D1: ROLE_DISPLAY must have an 'analyst' entry mapping to "
            "DisplayNames('Analysis Agent', 'Architect')."
        )
        assert ROLE_DISPLAY["analyst"].gamified == "Architect"
        assert ROLE_DISPLAY["analyst"].professional == "Analysis Agent"

    @_HANDLER_XFAIL
    def test_module_exposes_role_constant_bound_to_analyst(self) -> None:
        """D2: architect.ROLE is AgentRole.ANALYST."""
        import bonfire.handlers.architect as architect_mod

        assert hasattr(architect_mod, "ROLE"), (
            "architect.py must expose a module-level ROLE constant bound to AgentRole.ANALYST."
        )
        assert architect_mod.ROLE is AgentRole.ANALYST
        assert isinstance(architect_mod.ROLE, AgentRole)

    @_HANDLER_XFAIL
    def test_role_constant_value_is_analyst_string(self) -> None:
        """StrEnum value equality: ROLE == 'analyst'."""
        import bonfire.handlers.architect as architect_mod

        assert architect_mod.ROLE == "analyst"

    @_HANDLER_XFAIL
    def test_handler_class_docstring_cites_generic_role_or_architect(self) -> None:
        """Handler class docstring must cite the generic identity.

        Since the handler class is named ``ArchitectHandler`` and its purpose
        is project analysis, the docstring naturally mentions "architect"
        (the file-stem / class name) AND/OR "analyst" (the generic role).
        Either is acceptable for readability; the enum binding locks the
        canonical generic identity elsewhere.
        """
        assert ArchitectHandler.__doc__ is not None
        doc = ArchitectHandler.__doc__.lower()
        assert ("analyst" in doc) or ("architect" in doc), (
            "ArchitectHandler docstring must cite either the generic role "
            "('analyst') or its canonical name ('architect')."
        )

    @_HANDLER_XFAIL
    def test_handler_module_docstring_present(self) -> None:
        """Module docstring present (generic-role citation is encouraged)."""
        import bonfire.handlers.architect as architect_mod

        assert architect_mod.__doc__ is not None
        assert architect_mod.__doc__.strip()

    @_HANDLER_XFAIL
    def test_role_matches_stage_spec_role_field(self, architect_stage: StageSpec) -> None:
        """Integration: stage.role ('analyst') == handler module ROLE."""
        import bonfire.handlers.architect as architect_mod

        assert architect_stage.role == architect_mod.ROLE


# ---------------------------------------------------------------------------
# Scanner — discovery (Pass 1)
# ---------------------------------------------------------------------------


class TestScannerDiscovery:
    @_SCANNER_XFAIL
    def test_discovers_python_files(self, simple_project) -> None:
        """ProjectScanner.discover() lists Python files."""
        scanner = ProjectScanner(simple_project)
        manifest = scanner.discover()
        python_files = [f for f in manifest.files if f.category == "python"]
        paths = {str(f.path) for f in python_files}
        assert len(python_files) >= 1
        assert any("main.py" in p for p in paths)

    @_SCANNER_XFAIL
    def test_discovers_markdown_files(self, simple_project) -> None:
        scanner = ProjectScanner(simple_project)
        manifest = scanner.discover()
        md_files = [f for f in manifest.files if f.category == "markdown"]
        paths = {str(f.path) for f in md_files}
        assert len(md_files) >= 1
        assert any("README.md" in p for p in paths)

    @_SCANNER_XFAIL
    def test_excludes_pycache(self, simple_project) -> None:
        """__pycache__ dirs are excluded from discovery."""
        scanner = ProjectScanner(simple_project)
        manifest = scanner.discover()
        all_paths = {str(f.path) for f in manifest.files}
        assert not any("__pycache__" in p for p in all_paths)

    @_SCANNER_XFAIL
    def test_manifest_counts_match(self, simple_project) -> None:
        scanner = ProjectScanner(simple_project)
        manifest = scanner.discover()
        assert manifest.total_files == len(manifest.files)
        python_count = sum(1 for f in manifest.files if f.category == "python")
        assert manifest.total_python_source == python_count
        assert manifest.total_files > 0

    @_SCANNER_XFAIL
    def test_empty_dir(self, tmp_path) -> None:
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        assert manifest.files == []
        assert manifest.total_files == 0

    @_SCANNER_XFAIL
    def test_extracts_classes_and_functions(self, simple_project) -> None:
        """extract_signatures returns classes + functions."""
        scanner = ProjectScanner(simple_project)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        all_classes: list[str] = []
        all_functions: list[str] = []
        for sig in sigs:
            all_classes.extend(sig.classes)
            all_functions.extend(sig.functions)
        assert "App" in all_classes
        assert "run" in all_functions

    @_SCANNER_XFAIL
    def test_extracts_imports(self, tmp_path) -> None:
        (tmp_path / "mod.py").write_text("import os\nfrom pathlib import Path\n\ndef f(): pass\n")
        scanner = ProjectScanner(tmp_path)
        manifest = scanner.discover()
        sigs = scanner.extract_signatures(manifest)
        assert len(sigs) >= 1
        assert "os" in sigs[0].imports


# ---------------------------------------------------------------------------
# Chunker
# ---------------------------------------------------------------------------


class TestChunker:
    @_CHUNKER_XFAIL
    def test_chunk_markdown_returns_vault_entries(self) -> None:
        from bonfire.protocols import VaultEntry

        chunks = chunk_markdown("# Title\n\nSome body text.\n", source_path="README.md")
        assert isinstance(chunks, list)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert isinstance(chunk, VaultEntry)

    @_CHUNKER_XFAIL
    def test_chunk_markdown_entry_type_is_code_chunk(self) -> None:
        chunks = chunk_markdown("# Heading\n\nParagraph.\n", source_path="doc.md")
        for chunk in chunks:
            assert chunk.entry_type == "code_chunk"

    @_CHUNKER_XFAIL
    def test_chunk_markdown_each_chunk_has_content_hash(self) -> None:
        chunks = chunk_markdown("# A\n\nContent A.\n\n# B\n\nContent B.\n", source_path="doc.md")
        for chunk in chunks:
            assert chunk.content_hash

    @_CHUNKER_XFAIL
    def test_chunk_source_file_returns_vault_entries(self) -> None:
        from bonfire.protocols import VaultEntry

        chunks = chunk_source_file(
            "class Foo:\n    pass\n\ndef bar() -> None:\n    pass\n",
            source_path="module.py",
        )
        assert isinstance(chunks, list)
        assert len(chunks) >= 1
        for chunk in chunks:
            assert isinstance(chunk, VaultEntry)


# ---------------------------------------------------------------------------
# ArchitectHandler — construction + protocol conformance
# ---------------------------------------------------------------------------


class TestConstruction:
    @_HANDLER_XFAIL
    def test_satisfies_stage_handler_protocol(
        self,
        vault: Any,
        simple_project,
    ) -> None:
        from bonfire.protocols import StageHandler

        handler = ArchitectHandler(
            vault=vault, project_root=simple_project, project_name="testproj"
        )
        assert isinstance(handler, StageHandler)

    @_HANDLER_XFAIL
    def test_handle_signature_matches_stage_handler_protocol(self) -> None:
        """handle(stage, envelope, prior_results) -> Envelope is sealed."""
        sig = inspect.signature(ArchitectHandler.handle)
        params = list(sig.parameters.keys())
        assert params == ["self", "stage", "envelope", "prior_results"]
        assert asyncio.iscoroutinefunction(ArchitectHandler.handle)


# ---------------------------------------------------------------------------
# Happy path — scan & store
# ---------------------------------------------------------------------------


class TestScanAndStore:
    @_HANDLER_XFAIL
    @_SCANNER_XFAIL
    @_CHUNKER_XFAIL
    @_VAULT_XFAIL
    @pytest.mark.asyncio
    async def test_returns_completed_envelope_with_json_summary(
        self,
        handler: Any,
        architect_stage: StageSpec,
    ) -> None:
        """Happy path: COMPLETED envelope carrying JSON summary in .result."""
        envelope = Envelope(task="scan")
        result = await handler.handle(architect_stage, envelope, {})

        assert result.status is TaskStatus.COMPLETED
        summary = json.loads(result.result)
        assert "total_files" in summary
        assert "entries_stored" in summary
        assert "entries_skipped" in summary

    @_HANDLER_XFAIL
    @_SCANNER_XFAIL
    @_VAULT_XFAIL
    @pytest.mark.asyncio
    async def test_stores_manifest_entry(
        self,
        handler: Any,
        architect_stage: StageSpec,
        vault: Any,
    ) -> None:
        """One project_manifest entry stored."""
        envelope = Envelope(task="scan")
        await handler.handle(architect_stage, envelope, {})

        # Tolerant access — FakeVault uses .stored; real InMemoryVaultBackend
        # may use ._entries. Accept either.
        entries = getattr(vault, "stored", None) or getattr(vault, "_entries", [])
        manifests = [e for e in entries if getattr(e, "entry_type", None) == "project_manifest"]
        assert manifests, "Expected at least one project_manifest entry"

    @_HANDLER_XFAIL
    @_SCANNER_XFAIL
    @_VAULT_XFAIL
    @pytest.mark.asyncio
    async def test_stores_signature_entries(
        self,
        handler: Any,
        architect_stage: StageSpec,
        vault: Any,
    ) -> None:
        """At least one module_signature entry stored for Python sources."""
        envelope = Envelope(task="scan")
        await handler.handle(architect_stage, envelope, {})

        entries = getattr(vault, "stored", None) or getattr(vault, "_entries", [])
        sigs = [e for e in entries if getattr(e, "entry_type", None) == "module_signature"]
        assert sigs, "Expected module_signature entries"

    @_HANDLER_XFAIL
    @_CHUNKER_XFAIL
    @_VAULT_XFAIL
    @pytest.mark.asyncio
    async def test_stores_code_chunks(
        self,
        handler: Any,
        architect_stage: StageSpec,
        vault: Any,
    ) -> None:
        """At least one code_chunk entry stored."""
        envelope = Envelope(task="scan")
        await handler.handle(architect_stage, envelope, {})

        entries = getattr(vault, "stored", None) or getattr(vault, "_entries", [])
        chunks = [e for e in entries if getattr(e, "entry_type", None) == "code_chunk"]
        assert chunks

    @_HANDLER_XFAIL
    @_SCANNER_XFAIL
    @pytest.mark.asyncio
    async def test_skips_already_existing_hashes(
        self,
        architect_stage: StageSpec,
        project_root: Path,
    ) -> None:
        """Pre-existing content-hashes are skipped, not re-stored."""

        class AlwaysExistsVault:
            def __init__(self) -> None:
                self.stored: list[Any] = []
                self.skipped: int = 0

            async def exists(self, content_hash: str) -> bool:
                self.skipped += 1
                return True

            async def store(self, entry: Any) -> None:
                self.stored.append(entry)

        v = AlwaysExistsVault()
        handler = ArchitectHandler(
            vault=v,
            project_root=project_root,
            project_name="testproject",
            git_hash="abc123",
        )
        envelope = Envelope(task="scan")
        result = await handler.handle(architect_stage, envelope, {})

        assert result.status is TaskStatus.COMPLETED
        assert v.stored == [], "No entries should be stored when all hashes exist"
        summary = json.loads(result.result)
        assert summary["entries_stored"] == 0
        assert summary["entries_skipped"] > 0

    @_HANDLER_XFAIL
    @pytest.mark.asyncio
    async def test_dedups_by_content_hash_on_re_scan(
        self,
        vault: Any,
        simple_project,
        architect_envelope: Envelope,
        architect_stage: StageSpec,
    ) -> None:
        """Re-scanning same project must not add duplicate entries."""
        handler = ArchitectHandler(
            vault=vault, project_root=simple_project, project_name="testproj"
        )
        await handler.handle(architect_stage, architect_envelope, {})
        entries_attr = "_entries" if hasattr(vault, "_entries") else "stored"
        count_first = len(getattr(vault, entries_attr))
        envelope2 = Envelope(task="Re-scan", context="architect stage")
        await handler.handle(architect_stage, envelope2, {})
        count_second = len(getattr(vault, entries_attr))
        assert count_second == count_first, "Dedup must prevent duplicate entries"


# ---------------------------------------------------------------------------
# Error handling (contract parity with Bard/Herald/Wizard)
# ---------------------------------------------------------------------------


class TestErrorHandling:
    @_HANDLER_XFAIL
    @_SCANNER_XFAIL
    @pytest.mark.asyncio
    async def test_vault_store_failure_returns_failed_envelope(
        self,
        architect_stage: StageSpec,
        project_root: Path,
    ) -> None:
        """Vault.store raising -> FAILED envelope with RuntimeError type."""

        class ExplodingVault:
            async def exists(self, content_hash: str) -> bool:
                return False

            async def store(self, entry: Any) -> None:
                raise RuntimeError("vault offline")

        handler = ArchitectHandler(
            vault=ExplodingVault(),
            project_root=project_root,
            project_name="testproject",
            git_hash="abc123",
        )
        envelope = Envelope(task="scan")
        result = await handler.handle(architect_stage, envelope, {})

        assert result.status is TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "RuntimeError"

    @_HANDLER_XFAIL
    @_SCANNER_XFAIL
    @pytest.mark.asyncio
    async def test_vault_exists_failure_wraps_in_failed_envelope(
        self,
        simple_project,
        architect_envelope: Envelope,
        architect_stage: StageSpec,
    ) -> None:
        """Vault.exists raising -> FAILED envelope with peer-handler ErrorDetail shape."""

        class ExplodingExistsVault:
            async def store(self, entry: Any) -> str:
                return getattr(entry, "entry_id", "")

            async def query(
                self, query: str, *, limit: int = 5, entry_type: Any = None
            ) -> list[Any]:
                return []

            async def exists(self, content_hash: str) -> bool:
                raise RuntimeError("vault storage unavailable")

            async def get_by_source(self, source_path: str) -> list[Any]:
                return []

        handler = ArchitectHandler(
            vault=ExplodingExistsVault(),
            project_root=simple_project,
            project_name="testproj",
        )
        result = await handler.handle(architect_stage, architect_envelope, {})

        assert result.status == TaskStatus.FAILED
        assert result.error is not None
        assert result.error.error_type == "RuntimeError"
        assert "vault storage unavailable" in result.error.message
        assert result.error.stage_name == architect_stage.name

    @_HANDLER_XFAIL
    @pytest.mark.asyncio
    async def test_nonexistent_project_root_fails_gracefully(
        self,
        architect_stage: StageSpec,
        vault: Any,
        tmp_path: Path,
    ) -> None:
        """Missing project root -> FAILED envelope or zero-file COMPLETED; no crash."""
        missing = tmp_path / "does" / "not" / "exist"
        handler = ArchitectHandler(
            vault=vault,
            project_root=missing,
            project_name="missing",
            git_hash="000",
        )
        envelope = Envelope(task="scan")
        result = await handler.handle(architect_stage, envelope, {})

        assert isinstance(result, Envelope)
        assert result.status in (TaskStatus.FAILED, TaskStatus.COMPLETED)


# ---------------------------------------------------------------------------
# Negative drift guards
# ---------------------------------------------------------------------------


class TestNegativeDriftGuards:
    @_HANDLER_XFAIL
    def test_handler_source_does_not_hardcode_gamified_display(self) -> None:
        """D3: no title-cased ``"Architect"`` string literal in code body."""
        import bonfire.handlers.architect as architect_mod

        src = Path(architect_mod.__file__).read_text()
        lines = src.splitlines()
        offenders: list[tuple[int, str]] = []
        in_docstring = False
        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            if stripped.startswith('"""') or stripped.endswith('"""'):
                in_docstring = not in_docstring
                continue
            if in_docstring or stripped.startswith("#"):
                continue
            if '"Architect"' in line or "'Architect'" in line:
                offenders.append((idx, line))
        assert not offenders, (
            f"ArchitectHandler source must not hardcode a title-cased 'Architect' "
            f"display literal. Use ROLE_DISPLAY[ROLE].gamified. Offenders: {offenders}"
        )


# ---------------------------------------------------------------------------
# Identity Seal invariants
# ---------------------------------------------------------------------------


class TestIdentitySealInvariants:
    @_HANDLER_XFAIL
    def test_handle_signature_matches_stage_handler_protocol(self) -> None:
        sig = inspect.signature(ArchitectHandler.handle)
        params = list(sig.parameters.keys())
        assert params == ["self", "stage", "envelope", "prior_results"]
        assert asyncio.iscoroutinefunction(ArchitectHandler.handle)

    @_HANDLER_XFAIL
    @pytest.mark.asyncio
    async def test_handle_returns_envelope(
        self,
        handler: Any,
        architect_stage: StageSpec,
    ) -> None:
        envelope = Envelope(task="scan")
        result = await handler.handle(architect_stage, envelope, {})
        assert isinstance(result, Envelope)
