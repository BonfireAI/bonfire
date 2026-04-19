"""RED contract tests — Category C5 priv-escalation WARN patterns.

Sage-canonical (BON-338). Knight-B literal TP/FP rows + Knight-A sudo FP
boundary. Per Sage D4 — C5 ships as **WARN**, not DENY, in v0.1.
Calibration-first for sudo and friends (legit use for ``sudo apt install``).
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


CATEGORY_NAME = "priv-escalation"


def _warn_in_category() -> list:
    return [r for r in DEFAULT_WARN_PATTERNS if r.category == CATEGORY_NAME]


def _find_warn(rule_id: str):
    for r in DEFAULT_WARN_PATTERNS:
        if r.rule_id == rule_id:
            return r
    available = sorted({r.rule_id for r in DEFAULT_WARN_PATTERNS})
    pytest.fail(f"rule_id {rule_id!r} not in DEFAULT_WARN_PATTERNS: {available}")


class TestCategoryC5Action:
    """C5 priv-escalation ships as WARN, NOT DENY. Calibration-first (D4)."""

    def test_category_present_in_warn_set(self):
        assert _warn_in_category(), "C5 priv-escalation must contribute WARN rules"

    def test_category_absent_from_deny_set(self):
        deny = [r for r in DEFAULT_DENY_PATTERNS if r.category == CATEGORY_NAME]
        assert deny == [], (
            "C5 priv-escalation MUST be WARN-only in v0.1. "
            "Never moved into DEFAULT_DENY_PATTERNS."
        )

    def test_rule_id_prefix(self):
        for r in _warn_in_category():
            assert r.rule_id.startswith("C5."), r.rule_id

    def test_c5_slugs_match_canonical(self):
        shipped = {r.rule_id for r in _warn_in_category()}
        expected = {s for s in CANONICAL_WARN_RULE_IDS if s.startswith("C5.")}
        assert shipped == expected


class TestC5_1_SudoDefault:
    @pytest.mark.parametrize(
        "cmd",
        [
            "sudo rm -rf /",
            "sudo apt install foo",
            "sudo -i",
            "sudo vim /etc/passwd",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C5.1-sudo-default")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "sudo -l",
            "sudo --list",
            "sudo -n -l",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find_warn("C5.1-sudo-default")
        assert rule.pattern.search(cmd) is None


class TestC5_2_SuRoot:
    @pytest.mark.parametrize(
        "cmd",
        [
            "su -",
            "su root",
            "su - root",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C5.2-su-root")
        assert rule.pattern.search(cmd) is not None


class TestC5_3_WriteSudoers:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo 'x' >> /etc/sudoers",
            "echo new > /etc/sudoers",
            "echo >> /etc/sudoers.d/foo",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C5.3-write-sudoers")
        assert rule.pattern.search(cmd) is not None


class TestC5_4_ChmodSetuid:
    @pytest.mark.parametrize(
        "cmd",
        [
            "chmod u+s /bin/bash",
            "chmod g+s /usr/local/bin/priv",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C5.4-chmod-setuid")
        assert rule.pattern.search(cmd) is not None


class TestC5_5_AppendAuthorizedKeys:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo key >> ~/.ssh/authorized_keys",
            "cat pub > ~/.ssh/authorized_keys",
            "echo pub > /home/x/.ssh/authorized_keys",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C5.5-append-authorized-keys")
        assert rule.pattern.search(cmd) is not None


class TestC5_6_WritePasswdShadow:
    @pytest.mark.parametrize(
        "cmd",
        [
            "echo root::0:0:: >> /etc/passwd",
            "echo x > /etc/shadow",
            "echo 'g' >> /etc/group",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C5.6-write-passwd-shadow")
        assert rule.pattern.search(cmd) is not None


class TestC5_7_UsermodPrivGroup:
    @pytest.mark.parametrize(
        "cmd",
        [
            "usermod -aG sudo attacker",
            "usermod -AG wheel attacker",
            "visudo",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find_warn("C5.7-usermod-priv-group")
        assert rule.pattern.search(cmd) is not None


class TestC5RuleStructure:
    def test_all_rules_are_denyrule(self):
        for r in _warn_in_category():
            assert isinstance(r, DenyRule), r

    def test_all_rules_have_compiled_regex(self):
        for r in _warn_in_category():
            assert isinstance(r.pattern, re.Pattern), r.rule_id

    def test_all_rules_have_message(self):
        for r in _warn_in_category():
            assert r.message
