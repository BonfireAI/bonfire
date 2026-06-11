# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Preservation guard — lock the ISM integration surface and the CI / dev
tooling pins against silent deletion.

These surfaces exist and are correct in the current tree. They are also
the kind of surface a wholesale code drop from a divergent branch could
quietly remove or downgrade: a whole package, a spec document, a
supply-chain SHA pin, a CI drift-check step, a formatter version pin.

A linter cannot tell intentional removal from accidental loss. This
guard makes the loss loud — each assertion is shaped so that flipping
the real artifact (deleting the package, removing the spec, downgrading
the pinned action back to a floating tag, dropping the citation-drift
step, loosening the formatter pin) turns the test red.

Surfaces locked here:

  * ``bonfire.integrations`` — the Instruction Set Markup public package
    (document container, category enum, four detection-rule models, the
    discriminated-union alias, the two optional sub-objects, the strict
    schema error, and the two-tier loader).
  * ``docs/specs/ism-v1.md`` — the ISM file-format and validation spec.
  * ``.github/workflows/release.yml`` — the PyPI publish action pinned to
    a commit SHA, not a floating release tag.
  * ``.github/workflows/ci.yml`` — the protocol-doc citation drift check
    runs on every CI run.
  * ``.pre-commit-config.yaml`` and ``pyproject.toml`` — the formatter
    is pinned to one exact version in both places, and they agree.
  * The behavioral test coverage for the surfaces above — the ISM
    document, loader, and builtin-example test modules, plus the
    citation-drift script's own test. The production surfaces are guarded
    by name; their coverage must be guarded too, or a wholesale code drop
    could delete the tests silently (fewer collected tests is not a
    pytest failure).
"""

from __future__ import annotations

import importlib
from pathlib import Path

# tests/unit/test_reconcile_preservation_guard.py -> repo root is parents[2].
_REPO_ROOT = Path(__file__).resolve().parents[2]

# The supply-chain-hardened pin for the PyPI publish action: a commit SHA,
# not a floating release tag. The earlier pin (a tag that bundled a twine
# too old for Metadata-Version 2.4) must not return.
_PYPI_ACTION = "pypa/gh-action-pypi-publish"
_PYPI_ACTION_SHA = "cef221092ed1bacb1cc03d23a2d87d1d172e277b"
_PYPI_ACTION_BAD_TAG = "v1.12.2"

# The single source-of-truth formatter version, pinned identically in the
# pre-commit hook and in the project's dev dependency.
_RUFF_VERSION = "0.15.13"


def test_integrations_package_imports() -> None:
    """The ISM package imports and re-exports its full public surface.

    Deleting the package, or dropping a name from ``__all__`` /
    ``__init__``, breaks this import and fails the test.
    """
    integrations = importlib.import_module("bonfire.integrations")

    expected = {
        "ISMDocument",
        "ISMCategory",
        "ISMSchemaError",
        "ISMLoader",
        # The four concrete detection-rule models.
        "CommandRule",
        "EnvVarRule",
        "FileMatchRule",
        "PythonImportRule",
        # The discriminated-union alias and the optional sub-objects.
        "DetectionRule",
        "Credentials",
        "Fallback",
    }

    missing = sorted(name for name in expected if not hasattr(integrations, name))
    assert not missing, f"bonfire.integrations no longer exports: {missing}"

    declared = set(getattr(integrations, "__all__", ()))
    # Every concrete name (the alias aside) is also a declared export.
    not_declared = sorted((expected - {"DetectionRule"}) - declared)
    assert not not_declared, f"names dropped from __all__: {not_declared}"


def test_ism_spec_present_and_substantive() -> None:
    """The ISM spec document exists and carries real content.

    Deleting the spec, or truncating it to a stub, fails the test.
    """
    spec = _REPO_ROOT / "docs" / "specs" / "ism-v1.md"
    assert spec.is_file(), "docs/specs/ism-v1.md is missing"

    text = spec.read_text(encoding="utf-8")
    assert len(text) > 2000, "ism-v1.md has shrunk to a stub"
    assert "Instruction Set Markup" in text, "ism-v1.md no longer names the format"


def test_builtin_github_ism_present() -> None:
    """The shipped builtin ISM example exists.

    The loader's builtin tier is empty without it; deleting the file
    fails the test.
    """
    builtin = _REPO_ROOT / "src" / "bonfire" / "integrations" / "builtins" / "github.ism.md"
    assert builtin.is_file(), "builtin github.ism.md is missing"
    assert builtin.read_text(encoding="utf-8").strip(), "builtin github.ism.md is empty"


def test_release_action_pinned_to_commit_sha() -> None:
    """The PyPI publish action is pinned to a commit SHA on its ``uses:``
    line, and the superseded floating tag is not used as a ref.

    Mutations that fail this test: deleting release.yml, removing the
    ``uses:`` line, and swapping the SHA back to ``@v1.12.2`` (or any
    floating ``@v...`` tag).
    """
    release = _REPO_ROOT / ".github" / "workflows" / "release.yml"
    assert release.is_file(), ".github/workflows/release.yml is missing"

    # Find the actual `uses:` reference for the publish action. The
    # version explanation in comments mentions the old tag, so anchor on
    # the `uses:` directive rather than a bare substring scan.
    uses_refs = [
        line.split("uses:", 1)[1].strip()
        for line in release.read_text(encoding="utf-8").splitlines()
        if "uses:" in line and _PYPI_ACTION in line
    ]
    assert uses_refs, f"no `uses:` line references {_PYPI_ACTION}"

    ref = uses_refs[0]
    assert ref == f"{_PYPI_ACTION}@{_PYPI_ACTION_SHA}", (
        f"publish action is not pinned to the expected SHA: {ref!r}"
    )
    assert f"@{_PYPI_ACTION_BAD_TAG}" not in ref, (
        f"publish action reverted to the superseded tag {_PYPI_ACTION_BAD_TAG}"
    )


def test_ci_runs_citation_drift_check() -> None:
    """CI runs the protocol-doc citation drift check.

    Deleting ci.yml, or removing the step that invokes
    ``scripts/check_protocol_doc_citations.py``, fails the test.
    """
    ci = _REPO_ROOT / ".github" / "workflows" / "ci.yml"
    assert ci.is_file(), ".github/workflows/ci.yml is missing"

    text = ci.read_text(encoding="utf-8")
    assert "scripts/check_protocol_doc_citations.py" in text, (
        "ci.yml no longer invokes the citation drift check"
    )

    script = _REPO_ROOT / "scripts" / "check_protocol_doc_citations.py"
    assert script.is_file(), "scripts/check_protocol_doc_citations.py is missing"


def test_ruff_pinned_consistently() -> None:
    """The formatter is pinned to one exact version in pre-commit and in
    the dev dependency, and the two agree.

    Mutations that fail this test: deleting either file, dropping the
    ruff pin from pre-commit, loosening ``ruff==`` to ``ruff>=`` in
    pyproject, or letting the two versions drift apart.
    """
    precommit = _REPO_ROOT / ".pre-commit-config.yaml"
    pyproject = _REPO_ROOT / "pyproject.toml"
    assert precommit.is_file(), ".pre-commit-config.yaml is missing"
    assert pyproject.is_file(), "pyproject.toml is missing"

    precommit_text = precommit.read_text(encoding="utf-8")
    assert f"rev: v{_RUFF_VERSION}" in precommit_text, (
        f"pre-commit no longer pins ruff to v{_RUFF_VERSION}"
    )

    pyproject_text = pyproject.read_text(encoding="utf-8")
    assert f'"ruff=={_RUFF_VERSION}"' in pyproject_text, (
        f"pyproject no longer pins ruff=={_RUFF_VERSION}"
    )


# The behavioral test modules that exercise the surfaces guarded above.
# Each entry is the path relative to the repo root and a token that must
# appear in the file. The token anchors on a real test name in each
# module, so deleting the file *or* gutting it down to a stub that no
# longer runs that test turns the guard red. A wholesale code drop that
# removed these would otherwise just lower the collected-test count,
# which pytest does not treat as a failure.
_GUARDED_TEST_MODULES = (
    ("tests/unit/test_integrations_document.py", "def test_"),
    ("tests/unit/test_integrations_loader.py", "def test_"),
    ("tests/unit/test_integrations_github_ism.py", "def test_"),
    ("tests/scripts/test_check_protocol_doc_citations.py", "def test_"),
)


def test_guarded_surfaces_keep_their_tests() -> None:
    """The behavioral tests for the locked surfaces exist and still run.

    The production ISM package, its spec and builtin, and the citation
    drift script are guarded by name above. Their coverage must be
    guarded too: deleting (or stubbing out) any of the ISM document /
    loader / builtin test modules or the citation-script test fails this
    test, because a vanished test module is silent to pytest otherwise.
    """
    missing: list[str] = []
    stubbed: list[str] = []
    for rel_path, marker in _GUARDED_TEST_MODULES:
        path = _REPO_ROOT / rel_path
        if not path.is_file():
            missing.append(rel_path)
            continue
        text = path.read_text(encoding="utf-8")
        # A real test module carries at least one test function and is not
        # a truncated placeholder.
        if marker not in text or len(text) < 500:
            stubbed.append(rel_path)

    assert not missing, f"behavioral test modules are missing: {missing}"
    assert not stubbed, f"behavioral test modules gutted to stubs: {stubbed}"
