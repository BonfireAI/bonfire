"""Contract tests — Category C6 shell-escape / obfuscation WARN patterns.

C6 rules ship as **WARN** (not DENY) in v0.1: they have a high false-positive
rate, so the hook surfaces them for visibility but lets the call through rather
than blocking. Each test pins a true-positive command the rule must flag.

Two former C6 rules — an $IFS space-substitution rule and a Unicode-lookalike
rule — are NOT tested here because they no longer exist. They were structurally
unreachable: the pre-exec hook normalizes commands (NFKC + an explicit
$IFS -> space substitution) before any pattern runs, folding away the exact
tokens those rules matched. Their bypass scenarios are still denied via the
surviving DENY rules; see
tests/unit/test_security_normalize_neutralizes_obfuscation.py.
"""

from __future__ import annotations

import re

import pytest

from tests.unit.test_security_patterns_module import CANONICAL_WARN_RULE_IDS

try:
    from bonfire.dispatch.security_patterns import (
        DEFAULT_DENY_PATTERNS,
        DEFAULT_WARN_PATTERNS,
        DenyRule,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    DEFAULT_DENY_PATTERNS = None  # type: ignore[assignment]
    DEFAULT_WARN_PATTERNS = None  # type: ignore[assignment]
    DenyRule = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.security_patterns not importable: {_IMPORT_ERROR}")


CATEGORY_NAME = "shell-escape"


def _warn_in_category() -> list:
    return [r for r in DEFAULT_WARN_PATTERNS if r.category == CATEGORY_NAME]


def _find_warn(rule_id: str):
    for r in DEFAULT_WARN_PATTERNS:
        if r.rule_id == rule_id:
            return r
    available = sorted({r.rule_id for r in DEFAULT_WARN_PATTERNS})
    pytest.fail(f"rule_id {rule_id!r} not in DEFAULT_WARN_PATTERNS: {available}")


class TestCategoryC6Action:
    """C6 shell-escape ships as WARN, NOT DENY. High FP rate (D4)."""

    def test_category_present_in_warn_set(self):
        assert _warn_in_category(), "C6 shell-escape must contribute WARN rules"

    def test_category_absent_from_deny_set(self):
        deny = [r for r in DEFAULT_DENY_PATTERNS if r.category == CATEGORY_NAME]
        assert deny == [], (
            "C6 shell-escape MUST be WARN-only in v0.1. Never moved into DEFAULT_DENY_PATTERNS."
        )

    def test_rule_id_prefix(self):
        for r in _warn_in_category():
            assert r.rule_id.startswith("C6."), r.rule_id

    def test_c6_slugs_match_canonical(self):
        shipped = {r.rule_id for r in _warn_in_category()}
        expected = {s for s in CANONICAL_WARN_RULE_IDS if s.startswith("C6.")}
        assert shipped == expected


class TestC6_1_Eval:
    @pytest.mark.parametrize(
        "cmd",
        [
            "eval $CMD",
            "eval foo",
            "eval `ls`",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C6.1-eval")
        assert rule.pattern.search(cmd) is not None


class TestC6_2_Base64Decode:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo cm0= | base64 -d | sh",
            "echo cm0= | base64 --decode | bash",
            "base64 -d payload.b64 | eval",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C6.2-base64-decode")
        assert rule.pattern.search(cmd) is not None


class TestC6_4_BraceExpansion:
    @pytest.mark.parametrize(
        "cmd",
        [
            "{cat,/etc/passwd}",
            "{rm,-rf,/}",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C6.4-brace-expansion")
        assert rule.pattern.search(cmd) is not None


class TestC6_5_WildcardPath:
    @pytest.mark.parametrize(
        "cmd",
        [
            "/???/??t /???/p??s??",
            "/*/cat /etc/passwd",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C6.5-wildcard-path")
        assert rule.pattern.search(cmd) is not None


class TestC6_7_AliasFunctionRedef:
    @pytest.mark.parametrize(
        "cmd",
        [
            "alias cd='rm -rf'",
            "alias ls=rm",
            "cd() { rm -rf $@; }",
            "ls () { rm -rf /; }",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C6.7-alias-function-redef")
        assert rule.pattern.search(cmd) is not None


class TestC6_8_NewlineEscape:
    @pytest.mark.parametrize(
        "cmd",
        [
            "rm \\\n-rf /",
            "cat \\\n/etc/passwd",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C6.8-newline-escape")
        assert rule.pattern.search(cmd) is not None


class TestC6RuleStructure:
    def test_all_rules_are_denyrule(self):
        for r in _warn_in_category():
            assert isinstance(r, DenyRule), r

    def test_all_rules_have_compiled_regex(self):
        for r in _warn_in_category():
            assert isinstance(r.pattern, re.Pattern), r.rule_id

    def test_all_rules_have_message(self):
        for r in _warn_in_category():
            assert r.message
