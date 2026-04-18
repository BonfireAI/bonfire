"""RED contract tests — Category C6 shell-escape / obfuscation WARN patterns.

Sage-canonical (BON-338). Knight-B literal TP/FP rows. Per Sage D4 — C6
ships as **WARN** (not DENY) in v0.1. High FP rate per Scout-2/338 §6.2 —
calibration-first.

Sage ambiguity #4: C6.6 unicode-lookalike regex scope is DOCUMENTED as
``\\u00a0\\u2000-\\u200f\\u2028-\\u202f\\uff01-\\uff5e`` (NBSP, zero-widths,
fullwidth). Cyrillic lookalikes (U+0440) are a DOCUMENTED blind spot — see
tests/unit/test_security_hooks_blindspots.py.
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
        pytest.fail(
            f"bonfire.dispatch.security_patterns not importable: {_IMPORT_ERROR}"
        )


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
            "C6 shell-escape MUST be WARN-only in v0.1. "
            "Never moved into DEFAULT_DENY_PATTERNS."
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


class TestC6_3_IfsBypass:
    @pytest.mark.parametrize(
        "cmd",
        [
            "cat$IFS/etc/passwd",
            "cat${IFS}/etc/passwd",
            "cat$IFS$9/etc/passwd",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C6.3-ifs-bypass")
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


class TestC6_6_UnicodeLookalike:
    """Ambiguity #4: scope is NBSP + zero-widths + fullwidth. Cyrillic NOT covered."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "\uff52\uff4d -rf /",  # fullwidth
            "cat\u00a0/etc/passwd",  # nbsp
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C6.6-unicode-lookalike")
        assert rule.pattern.search(cmd) is not None

    def test_cyrillic_documented_blindspot(self):
        """Cyrillic 'r' (U+0440) is a DOCUMENTED blind spot per ambiguity #4.

        The C6.6 regex intentionally does NOT cover Cyrillic lookalikes. That
        gap is tracked via xfail in test_security_hooks_blindspots.py.
        """
        rule = _find_warn("C6.6-unicode-lookalike")
        # Cyrillic 'r' is NOT in the lookalike range — this search returns None.
        # If a future Warrior "helpfully" widens the regex, this test catches it.
        cmd = "\u0440m -rf /"
        # Document the behavior: the pattern should NOT match Cyrillic-only cases.
        # (The 'm' is ASCII but the leading 'r' is Cyrillic. Without wider range
        # regex the match is absent.) This is the Sage-locked blind spot.
        assert rule.pattern.search(cmd) is None, (
            "Ambiguity #4 locked: C6.6 does NOT cover Cyrillic lookalikes. "
            "A future Warrior that widens the regex MUST first re-synthesize "
            "with Sage because this loosens the documented v0.1 scope."
        )


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
