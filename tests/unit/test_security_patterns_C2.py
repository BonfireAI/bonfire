"""RED contract tests — Category C2 destructive-git deny patterns.

Sage-canonical (BON-338). Knight-B literal TP/FP rows + Knight-A adversarial
git edges. Per Sage D4 — C2 ships as DENY in v0.1.
"""

from __future__ import annotations

import re

import pytest

from tests.unit.test_security_patterns_module import CANONICAL_DENY_RULE_IDS

try:
    from bonfire.dispatch.security_patterns import (
        DEFAULT_DENY_PATTERNS,
        DenyRule,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    DEFAULT_DENY_PATTERNS = None  # type: ignore[assignment]
    DenyRule = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.security_patterns not importable: {_IMPORT_ERROR}")


CATEGORY_NAME = "destructive-git"


def _rules_in_category() -> list:
    return [r for r in DEFAULT_DENY_PATTERNS if r.category == CATEGORY_NAME]


def _find(rule_id: str):
    for r in DEFAULT_DENY_PATTERNS:
        if r.rule_id == rule_id:
            return r
    available = sorted({r.rule_id for r in DEFAULT_DENY_PATTERNS})
    pytest.fail(f"rule_id {rule_id!r} not in DEFAULT_DENY_PATTERNS: {available}")


class TestCategoryC2Action:
    def test_category_present_in_deny_set(self):
        assert _rules_in_category(), "C2 destructive-git must contribute DENY rules"

    def test_category_absent_from_warn_set(self):
        from bonfire.dispatch.security_patterns import DEFAULT_WARN_PATTERNS

        warn = [r for r in DEFAULT_WARN_PATTERNS if r.category == CATEGORY_NAME]
        assert warn == []

    def test_rule_id_prefix(self):
        for r in _rules_in_category():
            assert r.rule_id.startswith("C2."), r.rule_id

    def test_c2_slugs_match_canonical(self):
        shipped = {r.rule_id for r in _rules_in_category()}
        expected = {s for s in CANONICAL_DENY_RULE_IDS if s.startswith("C2.")}
        assert shipped == expected, f"C2 slug drift. Expected {expected}, got {shipped}"


class TestC2_1_GitResetHard:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git reset --hard HEAD~5",
            "git reset --hard origin/main",
            "git reset --merge",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.1-git-reset-hard")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "git reset",
            "git reset HEAD~1",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C2.1-git-reset-hard")
        assert rule.pattern.search(cmd) is None


class TestC2_2_GitCleanForce:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git clean -fd",
            "git clean -fdx",
            "git clean -f",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.2-git-clean-force")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "git clean -n",
            "git clean --dry-run",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C2.2-git-clean-force")
        assert rule.pattern.search(cmd) is None


class TestC2_3_GitPushForce:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git push -f origin main",
            "git push --force origin main",
            "git push --force",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.3-git-push-force")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "git push --force-with-lease origin feature",
            "git push origin main",
            "git push",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C2.3-git-push-force")
        assert rule.pattern.search(cmd) is None


class TestC2_4_GitBranchDeleteForce:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git branch -D main",
            "git branch -D feature",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.4-git-branch-delete-force")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "git branch -d old-branch",
            "git branch feature",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C2.4-git-branch-delete-force")
        assert rule.pattern.search(cmd) is None


class TestC2_5_GitCheckoutDotPath:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git checkout -- .",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.5-git-checkout-dot")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "git checkout main",
            "git checkout -b feature",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C2.5-git-checkout-dot")
        assert rule.pattern.search(cmd) is None


class TestC2_6_GitRestoreWorktree:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git restore file.py",
            "git restore src/",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.6-git-restore-worktree")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "git restore --staged file.py",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C2.6-git-restore-worktree")
        assert rule.pattern.search(cmd) is None


class TestC2_7_GitStashDropClear:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git stash clear",
            "git stash drop",
            "git stash drop stash@{0}",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.7-git-stash-drop-clear")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "git stash pop",
            "git stash push",
            "git stash list",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C2.7-git-stash-drop-clear")
        assert rule.pattern.search(cmd) is None


class TestC2_8_GitReflogExpire:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git reflog expire --expire=now --all",
            "git update-ref -d refs/heads/main",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.8-git-reflog-expire")
        assert rule.pattern.search(cmd) is not None


class TestC2_9_GitFilterBranch:
    @pytest.mark.parametrize(
        "cmd",
        [
            "git filter-repo --invert-paths",
            "git filter-branch --tree-filter 'rm -rf x' HEAD",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C2.9-git-filter-branch")
        assert rule.pattern.search(cmd) is not None


class TestC2RuleStructure:
    def test_all_rules_are_denyrule(self):
        for r in _rules_in_category():
            assert isinstance(r, DenyRule), r

    def test_all_rules_have_compiled_regex(self):
        for r in _rules_in_category():
            assert isinstance(r.pattern, re.Pattern), r.rule_id

    def test_all_rules_have_message(self):
        for r in _rules_in_category():
            assert r.message
