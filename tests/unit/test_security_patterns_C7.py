"""RED contract tests — Category C7 system-integrity deny patterns.

Sage-canonical (BON-338). Knight-B literal TP/FP + Knight-A chmod/fork-bomb/
shutdown matrix. Per Sage D4 — C7 ships as DENY in v0.1.
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
        pytest.fail(
            f"bonfire.dispatch.security_patterns not importable: {_IMPORT_ERROR}"
        )


CATEGORY_NAME = "system-integrity"


def _rules_in_category() -> list:
    return [r for r in DEFAULT_DENY_PATTERNS if r.category == CATEGORY_NAME]


def _find(rule_id: str):
    for r in DEFAULT_DENY_PATTERNS:
        if r.rule_id == rule_id:
            return r
    available = sorted({r.rule_id for r in DEFAULT_DENY_PATTERNS})
    pytest.fail(f"rule_id {rule_id!r} not in DEFAULT_DENY_PATTERNS: {available}")


class TestCategoryC7Action:
    def test_category_present_in_deny_set(self):
        assert _rules_in_category(), "C7 system-integrity must contribute DENY rules"

    def test_category_absent_from_warn_set(self):
        from bonfire.dispatch.security_patterns import DEFAULT_WARN_PATTERNS

        warn = [r for r in DEFAULT_WARN_PATTERNS if r.category == CATEGORY_NAME]
        assert warn == []

    def test_rule_id_prefix(self):
        for r in _rules_in_category():
            assert r.rule_id.startswith("C7."), r.rule_id

    def test_c7_slugs_match_canonical(self):
        shipped = {r.rule_id for r in _rules_in_category()}
        expected = {s for s in CANONICAL_DENY_RULE_IDS if s.startswith("C7.")}
        assert shipped == expected


class TestC7_1_ChmodRecursive777:
    @pytest.mark.parametrize(
        "cmd",
        [
            "chmod -R 777 /",
            "chmod -R 777 /etc",
            "chmod -R 777 /usr",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C7.1-chmod-recursive-777")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "chmod -R 777 /tmp/foo",
            "chmod -R 777 /tmp",  # Knight-A: /tmp is permitted path
            "chmod 644 file",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C7.1-chmod-recursive-777")
        assert rule.pattern.search(cmd) is None


class TestC7_2_ChownRecursiveRoot:
    @pytest.mark.parametrize(
        "cmd",
        [
            "chown -R root:root /",
            "chown -R user:user /",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C7.2-chown-recursive-root")
        assert rule.pattern.search(cmd) is not None


class TestC7_3_CrontabRemove:
    @pytest.mark.parametrize(
        "cmd",
        [
            "crontab -r",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C7.3-crontab-remove")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "crontab -l",
            "crontab -e",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C7.3-crontab-remove")
        assert rule.pattern.search(cmd) is None


class TestC7_4_ForkBomb:
    @pytest.mark.parametrize(
        "cmd",
        [
            ":(){ :|:& };:",
            ":() { : | : & } ; :",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C7.4-fork-bomb")
        assert rule.pattern.search(cmd) is not None


class TestC7_5_FirewallFlush:
    @pytest.mark.parametrize(
        "cmd",
        [
            "iptables -F",
            "ufw disable",
            "ufw reset",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C7.5-firewall-flush")
        assert rule.pattern.search(cmd) is not None


class TestC7_6_DisableSecurityService:
    @pytest.mark.parametrize(
        "cmd",
        [
            "systemctl disable sshd",
            "systemctl stop ssh",
            "systemctl mask auditd",
            "systemctl disable firewalld",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C7.6-disable-security-service")
        assert rule.pattern.search(cmd) is not None


class TestC7_7_PurgePythonMinimal:
    @pytest.mark.parametrize(
        "cmd",
        [
            "apt purge python3-minimal",
            "apt-get remove python-minimal",
            "apt purge python3.12-minimal",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C7.7-purge-python-minimal")
        assert rule.pattern.search(cmd) is not None


class TestC7_8_Shutdown:
    @pytest.mark.parametrize(
        "cmd",
        [
            "shutdown -h now",
            "halt",
            "poweroff",
            "reboot",
            "init 0",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C7.8-shutdown")
        assert rule.pattern.search(cmd) is not None


class TestC7RuleStructure:
    def test_all_rules_are_denyrule(self):
        for r in _rules_in_category():
            assert isinstance(r, DenyRule), r

    def test_all_rules_have_compiled_regex(self):
        for r in _rules_in_category():
            assert isinstance(r.pattern, re.Pattern), r.rule_id

    def test_all_rules_have_message(self):
        for r in _rules_in_category():
            assert r.message
