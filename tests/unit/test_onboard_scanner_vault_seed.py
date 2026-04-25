"""RED tests for bonfire.onboard.scanners.vault_seed — BON-349 W6.3 (Knight A, CONSERVATIVE lens).

Sage decision log: docs/audit/sage-decisions/bon-349-sage-20260425T230159Z.md
Floor: 20 tests per Sage §D6 Row 8. Verbatim v1 port. No innovations (conservative lens).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from bonfire.onboard.protocol import ScanUpdate

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _events(emit: AsyncMock) -> list[ScanUpdate]:
    """Extract all ScanUpdate objects from an AsyncMock's call list."""
    return [c.args[0] for c in emit.call_args_list]


def _find(events: list[ScanUpdate], **kwargs) -> list[ScanUpdate]:
    """Filter events by matching field values."""
    result = []
    for e in events:
        if all(getattr(e, k) == v for k, v in kwargs.items()):
            result.append(e)
    return result


# ---------------------------------------------------------------------------
# Key documents
# ---------------------------------------------------------------------------


async def test_detects_claude_md(tmp_path):
    """CLAUDE.md in root is detected."""
    (tmp_path / "CLAUDE.md").write_text("# My Project\n## Section 1\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    count = await scan(tmp_path, emit)

    assert count >= 1
    events = _events(emit)
    assert all(e.panel == "vault_seed" for e in events)
    assert any(e.label == "CLAUDE.md" and e.value == "found" for e in events)


async def test_detects_claude_md_in_dot_claude(tmp_path):
    """CLAUDE.md under .claude/ directory is detected."""
    dot_claude = tmp_path / ".claude"
    dot_claude.mkdir()
    (dot_claude / "CLAUDE.md").write_text("# Config\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    assert any(e.label == "CLAUDE.md" and e.value == "found" for e in events)


async def test_detects_readme(tmp_path):
    """README.md in root is detected."""
    (tmp_path / "README.md").write_text("# Hello\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    assert any(e.label == "README.md" and e.value == "found" for e in events)


# ---------------------------------------------------------------------------
# Architecture docs
# ---------------------------------------------------------------------------


async def test_counts_architecture_docs(tmp_path):
    """Counts files in docs/architecture* and docs/adr/."""
    arch_dir = tmp_path / "docs"
    arch_dir.mkdir()
    (arch_dir / "architecture-design.md").write_text("# Arch\n")
    (arch_dir / "architecture-overview.md").write_text("# Overview\n")

    adr_dir = arch_dir / "adr"
    adr_dir.mkdir()
    (adr_dir / "ADR-001.md").write_text("# ADR 1\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    arch_events = _find(events, label="architecture docs")
    assert len(arch_events) == 1
    assert "3 files" in arch_events[0].value


# ---------------------------------------------------------------------------
# Config files
# ---------------------------------------------------------------------------


async def test_detects_pyproject_toml(tmp_path):
    """pyproject.toml config file is detected."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    config_events = _find(events, label="config")
    values = [e.value for e in config_events]
    assert "pyproject.toml" in values


async def test_detects_package_json(tmp_path):
    """package.json config file is detected."""
    (tmp_path / "package.json").write_text('{"name": "test"}\n')

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    config_events = _find(events, label="config")
    values = [e.value for e in config_events]
    assert "package.json" in values


async def test_detects_multiple_config_files(tmp_path):
    """Multiple config files each get their own event."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "Makefile").write_text("all:\n\techo hi\n")
    (tmp_path / "tsconfig.json").write_text("{}\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    config_events = _find(events, label="config")
    values = {e.value for e in config_events}
    assert "pyproject.toml" in values
    assert "Makefile" in values
    assert "tsconfig.json" in values


# ---------------------------------------------------------------------------
# Test config
# ---------------------------------------------------------------------------


async def test_detects_pytest_in_pyproject(tmp_path):
    """[tool.pytest] section in pyproject.toml is detected as test config."""
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='test'\n\n[tool.pytest.ini_options]\naddopts = '-v'\n"
    )

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    test_events = _find(events, label="test config")
    assert len(test_events) >= 1
    assert any("pyproject.toml" in e.value for e in test_events)


async def test_detects_jest_config(tmp_path):
    """jest.config.js is detected as test config."""
    (tmp_path / "jest.config.js").write_text("module.exports = {};\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    test_events = _find(events, label="test config")
    assert len(test_events) == 1
    assert "jest.config.js" in test_events[0].value


# ---------------------------------------------------------------------------
# CI config
# ---------------------------------------------------------------------------


async def test_detects_github_actions(tmp_path):
    """GitHub Actions workflows are detected as CI config."""
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text("name: CI\n")
    (wf_dir / "deploy.yml").write_text("name: Deploy\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    ci_events = _find(events, label="CI")
    assert len(ci_events) == 1
    assert ci_events[0].value == "GitHub Actions"
    assert "2 workflows" in ci_events[0].detail


async def test_detects_gitlab_ci(tmp_path):
    """.gitlab-ci.yml is detected as CI config."""
    (tmp_path / ".gitlab-ci.yml").write_text("stages:\n  - build\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    ci_events = _find(events, label="CI")
    assert len(ci_events) == 1
    assert ci_events[0].value == "GitLab CI"


async def test_detects_circleci(tmp_path):
    """.circleci/config.yml is detected as CI config."""
    ci_dir = tmp_path / ".circleci"
    ci_dir.mkdir()
    (ci_dir / "config.yml").write_text("version: 2.1\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    ci_events = _find(events, label="CI")
    assert len(ci_events) == 1
    assert ci_events[0].value == "CircleCI"


# ---------------------------------------------------------------------------
# Key directories
# ---------------------------------------------------------------------------


async def test_detects_key_directories(tmp_path):
    """Key directories (src/, tests/, docs/) are detected."""
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "docs").mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    dir_events = _find(events, label="directory")
    values = {e.value for e in dir_events}
    assert "src/" in values
    assert "tests/" in values
    assert "docs/" in values


async def test_ignores_missing_directories(tmp_path):
    """Only existing directories are emitted."""
    (tmp_path / "src").mkdir()
    # lib/, tests/, docs/, app/ do NOT exist

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    dir_events = _find(events, label="directory")
    values = {e.value for e in dir_events}
    assert "src/" in values
    assert "lib/" not in values
    assert "tests/" not in values


# ---------------------------------------------------------------------------
# Project size
# ---------------------------------------------------------------------------


async def test_estimates_project_size(tmp_path):
    """Project size estimation includes file count and LOC estimate."""
    (tmp_path / "src").mkdir()
    for i in range(5):
        (tmp_path / "src" / f"mod{i}.py").write_text("x = 1\n" * 20)

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    size_events = _find(events, label="project size")
    assert len(size_events) == 1
    assert "files" in size_events[0].value
    assert "LOC" in size_events[0].detail


async def test_project_size_excludes_git_and_venv(tmp_path):
    """File count excludes .git/, node_modules/, .venv/, __pycache__/."""
    # Create excluded directories with files
    for excluded in [".git", "node_modules", ".venv", "__pycache__"]:
        d = tmp_path / excluded
        d.mkdir()
        (d / "file.txt").write_text("noise\n")

    # Create one real file
    (tmp_path / "main.py").write_text("print('hello')\n")

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    size_events = _find(events, label="project size")
    assert len(size_events) == 1
    # Should only count main.py and the directories themselves shouldn't inflate count
    # The value should reflect a small number, not 5+ files
    assert "~1 files" in size_events[0].value or "~2 files" in size_events[0].value


# ---------------------------------------------------------------------------
# Edge cases and invariants
# ---------------------------------------------------------------------------


async def test_empty_project_returns_minimal(tmp_path):
    """Empty project still returns at least the project size event."""
    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    count = await scan(tmp_path, emit)

    # At minimum, project size is emitted
    assert count >= 1
    events = _events(emit)
    assert any(e.label == "project size" for e in events)


async def test_panel_always_vault_seed(tmp_path):
    """Every ScanUpdate has panel='vault_seed'."""
    (tmp_path / "README.md").write_text("# Hello\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "src").mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    await scan(tmp_path, emit)

    events = _events(emit)
    assert len(events) > 0
    for event in events:
        assert isinstance(event, ScanUpdate)
        assert event.panel == "vault_seed"


async def test_count_matches_emitted_events(tmp_path):
    """Return value equals number of emit calls."""
    (tmp_path / "README.md").write_text("# Hello\n")
    (tmp_path / "CLAUDE.md").write_text("# Claude\n")
    (tmp_path / "pyproject.toml").write_text("[project]\nname='test'\n")
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    count = await scan(tmp_path, emit)

    assert count == emit.call_count


async def test_full_project(tmp_path):
    """A realistic project structure produces all expected event types."""
    # Key docs
    (tmp_path / "CLAUDE.md").write_text("# Claude\n")
    (tmp_path / "README.md").write_text("# Hello\n")

    # Architecture docs
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "architecture-design.md").write_text("# Arch\n")
    adr = docs / "adr"
    adr.mkdir()
    (adr / "ADR-001.md").write_text("# ADR\n")

    # Config
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname='test'\n\n[tool.pytest.ini_options]\naddopts = '-v'\n"
    )

    # CI
    wf_dir = tmp_path / ".github" / "workflows"
    wf_dir.mkdir(parents=True)
    (wf_dir / "ci.yml").write_text("name: CI\n")

    # Directories
    (tmp_path / "src").mkdir()
    (tmp_path / "tests").mkdir()

    # Source files for LOC
    (tmp_path / "src" / "main.py").write_text("x = 1\n" * 50)

    emit = AsyncMock()
    from bonfire.onboard.scanners.vault_seed import scan

    count = await scan(tmp_path, emit)

    events = _events(emit)
    labels = {e.label for e in events}

    assert "CLAUDE.md" in labels
    assert "README.md" in labels
    assert "architecture docs" in labels
    assert "config" in labels
    assert "test config" in labels
    assert "CI" in labels
    assert "directory" in labels
    assert "project size" in labels
    assert count == emit.call_count
    assert count >= 8  # At least one from each category
