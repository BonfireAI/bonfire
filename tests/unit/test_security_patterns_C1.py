"""RED contract tests — Category C1 destructive-fs deny patterns.

Sage-canonical (BON-338). Merges Knight-B literal TP/FP rows with Knight-A
adversarial rm-rf edge cases. Per Sage D4 — C1 ships as DENY in v0.1.

Rule IDs and patterns match Scout-2/338 §2 table C1 verbatim; the expected
slug set is pinned in ``CANONICAL_DENY_RULE_IDS`` (tests/unit/
test_security_patterns_module.py).
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


CATEGORY_NAME = "destructive-fs"


def _rules_in_category() -> list:
    return [r for r in DEFAULT_DENY_PATTERNS if r.category == CATEGORY_NAME]


def _find(rule_id: str):
    for r in DEFAULT_DENY_PATTERNS:
        if r.rule_id == rule_id:
            return r
    available = sorted({r.rule_id for r in DEFAULT_DENY_PATTERNS})
    pytest.fail(f"rule_id {rule_id!r} not in DEFAULT_DENY_PATTERNS: {available}")


# ---------------------------------------------------------------------------
# D4 — category action assertion
# ---------------------------------------------------------------------------


class TestCategoryC1Action:
    """D4: C1 destructive-fs ships as DENY in v0.1."""

    def test_category_present_in_deny_set(self):
        rules = _rules_in_category()
        assert rules, "C1 destructive-fs must contribute at least one DENY rule"

    def test_category_absent_from_warn_set(self):
        from bonfire.dispatch.security_patterns import DEFAULT_WARN_PATTERNS

        warn_rules = [r for r in DEFAULT_WARN_PATTERNS if r.category == CATEGORY_NAME]
        assert warn_rules == [], "C1 destructive-fs must NOT appear in DEFAULT_WARN_PATTERNS"

    def test_rule_id_prefix(self):
        for r in _rules_in_category():
            assert r.rule_id.startswith("C1."), (
                f"C1 rule id must start with 'C1.', got {r.rule_id!r}"
            )

    def test_c1_slugs_match_canonical(self):
        """Sage ambiguity #1: C1 slug set matches CANONICAL_DENY_RULE_IDS."""
        shipped = {r.rule_id for r in _rules_in_category()}
        expected = {s for s in CANONICAL_DENY_RULE_IDS if s.startswith("C1.")}
        assert shipped == expected, f"C1 slug drift. Expected {expected}, got {shipped}"


# ---------------------------------------------------------------------------
# Scout-2/338 §2 C1 — TP / FP literal rows
# ---------------------------------------------------------------------------


class TestC1_1_RmRfNonTemp:
    """C1.1 — ``rm -rf`` outside ephemeral paths."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "rm -rf ~",
            "rm -rf /",
            "rm -fr /",
            "rm -fr /home/user",
            "rm -Rf /data",
            "rm -rf /etc",
            # Knight-A adversarial
            "rm -rf /home/ishtar",
            "rm -rf /home",
            "rm -rf $HOME",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C1.1-rm-rf-non-temp")
        assert rule.pattern.search(cmd) is not None, f"C1.1 expected to match {cmd!r}"

    @pytest.mark.parametrize(
        "cmd",
        [
            "rm -rf node_modules",
            "rm -rf /tmp/foo",
            "rm -rf ./build",
            "rm -rf .venv",
            "rm -rf __pycache__",
            "rm -rf dist/",
            "rm -n file",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C1.1-rm-rf-non-temp")
        assert rule.pattern.search(cmd) is None, f"C1.1 expected NOT to match {cmd!r}"


class TestC1_2_DdToDevice:
    """C1.2 — ``dd of=/dev/sd*``."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "dd if=/dev/zero of=/dev/sda",
            "dd if=/dev/urandom of=/dev/nvme0n1",
            "dd if=image.iso of=/dev/xvdb",
            "dd if=x of=/dev/hda",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C1.2-dd-to-device")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "dd if=/dev/zero of=./out.img",
            "dd of=/tmp/loop.img",
            "dd if=./x of=./y",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C1.2-dd-to-device")
        assert rule.pattern.search(cmd) is None


class TestC1_3_MkfsOnDevice:
    """C1.3 — ``mkfs`` on a block device."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "mkfs.ext4 /dev/sda",
            "mkfs.xfs /dev/nvme0n1",
            "mkfs /dev/sdb1",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C1.3-mkfs-on-device")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "mkfs.ext4 ./loop.img",
            "mkfs.ext4 /tmp/loop.img",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C1.3-mkfs-on-device")
        assert rule.pattern.search(cmd) is None


class TestC1_4_Shred:
    """C1.4 — ``shred`` (destructive overwrite)."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "shred -u /important/file",
            "shred -fvu ~/secrets.txt",
            "shred /data/payload.bin",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C1.4-shred")
        assert rule.pattern.search(cmd) is not None


class TestC1_5_RedirectToDevice:
    """C1.5 — ``> /dev/sd*`` overwrites a block device."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo x > /dev/sda",
            "cat payload > /dev/nvme0n1",
            "printf z > /dev/hda",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C1.5-redirect-to-device")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo hi > /dev/null",
            "printf x > /dev/stderr",
            "echo log > /dev/stdout",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C1.5-redirect-to-device")
        assert rule.pattern.search(cmd) is None


class TestC1_6_MvRoot:
    """C1.6 — ``mv /`` — moving / elsewhere is catastrophic."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "mv / /dev/null",
            "mv / /backup",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C1.6-mv-root")
        assert rule.pattern.search(cmd) is not None

    @pytest.mark.parametrize(
        "cmd",
        [
            "mv /tmp/x .",
            "mv /home/user/file .",
            "mv file /tmp/",
        ],
    )
    def test_false_positive(self, cmd: str):
        rule = _find("C1.6-mv-root")
        assert rule.pattern.search(cmd) is None


class TestC1_7_FindDelete:
    """C1.7 — ``find ... -delete``."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "find / -delete",
            "find . -name '*.py' -delete",
            "fd -x -delete",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C1.7-find-delete")
        assert rule.pattern.search(cmd) is not None


class TestC1_8_RedirectOverwriteHome:
    """C1.8 — ``> ~/.something`` overwriting a dotfile."""

    @pytest.mark.parametrize(
        "cmd",
        [
            "echo x > ~/.bashrc",
            ": > ~/.ssh",
        ],
    )
    def test_true_positive(self, cmd: str):
        rule = _find("C1.8-redirect-overwrite-home")
        assert rule.pattern.search(cmd) is not None


# ---------------------------------------------------------------------------
# BON-894 — C1.1 exclusion list is order-sensitive / substring-leaky.
#
# RED regression tests. The current negative-lookahead in C1.1 uses bare
# ``\.venv`` / ``__pycache__`` tokens (substring match, no path-segment
# anchor) and a wildcard-prefixed ``[a-zA-Z0-9_./-]*node_modules``. Two
# concrete defects, both pinned below:
#
#   1. Substring leak — a destructive path that merely STARTS WITH an
#      exclusion token as a substring is wrongly ALLOWED:
#        * ``rm -rf __pycache__-backup/db``  -> should DENY (not a real
#          __pycache__ dir; "__pycache__" is a substring of the dir name)
#        * ``rm -rf node_modules-fake/x``    -> should DENY (same hazard)
#        * ``rm -rf .venv-other/secrets``    -> should DENY (".venv" substr)
#
#   2. Order sensitivity — only tokens at the path START are recognised as
#      ephemeral, so a legitimate nested ephemeral dir is wrongly DENIED:
#        * ``rm -rf project/.venv``          -> should ALLOW (real .venv dir
#          one segment deep)
#        * ``rm -rf node_modules``           -> should ALLOW (already does;
#          regression pin on the path that must stay allowed)
#
# The fix anchors each exclusion at a path-segment boundary
# (``(?:^|/)<token>/``). Until then the asserts below FAIL.
# ---------------------------------------------------------------------------


class TestC1_1_ExclusionListOrderSensitive:
    """BON-894 — C1.1 exclusion tokens must anchor at path-segment boundaries."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # "__pycache__" matched as a bare substring of the leading segment.
            "rm -rf __pycache__-backup/db",
            # wildcard-prefix / substring leak on node_modules.
            "rm -rf node_modules-fake/x",
            # ".venv" matched as a bare substring, not a directory marker.
            "rm -rf .venv-other/secrets",
        ],
    )
    def test_substring_leak_must_deny(self, cmd: str):
        """Paths that merely CONTAIN an exclusion token as a substring must DENY."""
        rule = _find("C1.1-rm-rf-non-temp")
        assert rule.pattern.search(cmd) is not None, (
            f"C1.1 must DENY {cmd!r} — the exclusion token is a substring of "
            "the dir name, not a real ephemeral-path segment"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Legitimate ephemeral dir one path-segment deep — must be ALLOWED.
            "rm -rf project/.venv",
            # Already allowed today — regression pin so the fix keeps it allowed.
            "rm -rf node_modules",
        ],
    )
    def test_legitimate_ephemeral_still_allowed(self, cmd: str):
        """Real dev-workflow rm -rf on ephemeral dirs must stay ALLOWED."""
        rule = _find("C1.1-rm-rf-non-temp")
        assert rule.pattern.search(cmd) is None, (
            f"C1.1 must ALLOW {cmd!r} — legitimate ephemeral-path removal"
        )


# ---------------------------------------------------------------------------
# Structural invariants for every C1 rule (D3 DenyRule contract)
# ---------------------------------------------------------------------------


class TestC1RuleStructure:
    def test_all_rules_are_denyrule(self):
        for r in _rules_in_category():
            assert isinstance(r, DenyRule), f"{r!r} is not a DenyRule instance"

    def test_all_rules_have_compiled_regex(self):
        for r in _rules_in_category():
            assert isinstance(r.pattern, re.Pattern), (
                f"{r.rule_id}.pattern must be a pre-compiled re.Pattern"
            )

    def test_all_rules_have_message(self):
        for r in _rules_in_category():
            assert isinstance(r.message, str) and r.message, (
                f"{r.rule_id} must have a non-empty message"
            )
