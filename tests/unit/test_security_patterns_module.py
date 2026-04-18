"""RED contract tests — module-level invariants for the security pattern catalogue.

Sage-canonical (BON-338). Merges Knight-B's literal contract + Knight-A's
adversarial structural checks. Locks Sage D2 (module shape), D3 (DenyRule
dataclass), D4 (category→action map) + Sage-reconciler ambiguity #1
(CANONICAL_RULE_IDS set is the Warrior's implementation target).

This module owns the SHARED ``CANONICAL_RULE_IDS`` fixture referenced by the
per-category files. Any drift from this set means the Warrior must
re-synthesize with Sage, not rename slugs locally.
"""

from __future__ import annotations

import dataclasses
import re

import pytest

try:
    from bonfire.dispatch import security_patterns as _mod
    from bonfire.dispatch.security_patterns import (
        DEFAULT_DENY_PATTERNS,
        DEFAULT_WARN_PATTERNS,
        DenyRule,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    _mod = None  # type: ignore[assignment]
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


# ---------------------------------------------------------------------------
# CANONICAL RULE IDs — Sage-locked slug table (ambiguity #1)
#
# This set is the Warrior's implementation target. Every id MUST appear as a
# DenyRule.rule_id in either DEFAULT_DENY_PATTERNS or DEFAULT_WARN_PATTERNS.
# The set composition is derived from Scout-2/338 §2 tables with Sage D4
# category→action mapping applied.
#
# DENY (C1+C2+C3+C4+C7): 37 rules.
# WARN (C5+C6): 15 rules.
# Total: 52 rules.
# ---------------------------------------------------------------------------


CANONICAL_DENY_RULE_IDS: frozenset[str] = frozenset({
    # C1 destructive-fs (8)
    "C1.1-rm-rf-non-temp",
    "C1.2-dd-to-device",
    "C1.3-mkfs-on-device",
    "C1.4-shred",
    "C1.5-redirect-to-device",
    "C1.6-mv-root",
    "C1.7-find-delete",
    "C1.8-redirect-overwrite-home",
    # C2 destructive-git (9)
    "C2.1-git-reset-hard",
    "C2.2-git-clean-force",
    "C2.3-git-push-force",
    "C2.4-git-branch-delete-force",
    "C2.5-git-checkout-dot",
    "C2.6-git-restore-worktree",
    "C2.7-git-stash-drop-clear",
    "C2.8-git-reflog-expire",
    "C2.9-git-filter-branch",
    # C3 pipe-to-shell (5)
    "C3.1-curl-pipe-shell",
    "C3.2-wget-output-pipe-shell",
    "C3.3-bash-process-sub",
    "C3.4-bash-c-substitution",
    "C3.5-dot-source-process-sub",
    # C4 exfiltration (7)
    "C4.1-cat-ssh-private-key",
    "C4.2-cat-aws-credentials",
    "C4.3-cat-credential-dotfile",
    "C4.4-cat-env-file",
    "C4.5-curl-data-home-file",
    "C4.6-scp-credential-dir",
    "C4.7-nc-send-key",
    # C7 system-integrity (8)
    "C7.1-chmod-recursive-777",
    "C7.2-chown-recursive-root",
    "C7.3-crontab-remove",
    "C7.4-fork-bomb",
    "C7.5-firewall-flush",
    "C7.6-disable-security-service",
    "C7.7-purge-python-minimal",
    "C7.8-shutdown",
})


CANONICAL_WARN_RULE_IDS: frozenset[str] = frozenset({
    # C5 priv-escalation (7)
    "C5.1-sudo-default",
    "C5.2-su-root",
    "C5.3-write-sudoers",
    "C5.4-chmod-setuid",
    "C5.5-append-authorized-keys",
    "C5.6-write-passwd-shadow",
    "C5.7-usermod-priv-group",
    # C6 shell-escape (8)
    "C6.1-eval",
    "C6.2-base64-decode",
    "C6.3-ifs-bypass",
    "C6.4-brace-expansion",
    "C6.5-wildcard-path",
    "C6.6-unicode-lookalike",
    "C6.7-alias-function-redef",
    "C6.8-newline-escape",
})


CANONICAL_RULE_IDS: frozenset[str] = CANONICAL_DENY_RULE_IDS | CANONICAL_WARN_RULE_IDS


# ---------------------------------------------------------------------------
# D2 — Module exports (Knight-B)
# ---------------------------------------------------------------------------


class TestModuleExports:
    """D2: module exposes exactly three public names."""

    def test_exports_deny_patterns(self):
        assert hasattr(_mod, "DEFAULT_DENY_PATTERNS")

    def test_exports_warn_patterns(self):
        assert hasattr(_mod, "DEFAULT_WARN_PATTERNS")

    def test_exports_denyrule(self):
        assert hasattr(_mod, "DenyRule")

    def test_all_list_contents(self):
        """__all__ includes the three public names (Sage D2 naming lockdown)."""
        names = set(getattr(_mod, "__all__", []) or [])
        expected = {"DEFAULT_DENY_PATTERNS", "DEFAULT_WARN_PATTERNS", "DenyRule"}
        assert expected.issubset(names), (
            f"__all__ must include {expected}, got {names}"
        )

    def test_all_is_exactly_three(self):
        """Sage D2 + Knight-A: ``__all__`` contains exactly three public names."""
        public = {
            name for name in getattr(_mod, "__all__", []) or []
            if not name.startswith("_")
        }
        assert public == {
            "DEFAULT_DENY_PATTERNS",
            "DEFAULT_WARN_PATTERNS",
            "DenyRule",
        }, f"Expected exactly 3 public names, got {public}"


# ---------------------------------------------------------------------------
# D3 — DenyRule dataclass shape (Knight-B + Knight-A)
# ---------------------------------------------------------------------------


class TestDenyRuleDataclass:
    """D3: DenyRule is a frozen slotted dataclass (NOT a Pydantic model)."""

    def test_is_dataclass(self):
        assert dataclasses.is_dataclass(DenyRule), (
            "DenyRule must be a dataclass, not a Pydantic model"
        )

    def test_is_frozen(self):
        rule = DenyRule(
            rule_id="X.1-test",
            category="test",
            pattern=re.compile(r"x"),
            message="test",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            rule.rule_id = "changed"  # type: ignore[misc]

    def test_frozen_on_live_catalogue_entry(self):
        """Knight-A adversarial: a live catalogue entry is tamper-proof."""
        rule = DEFAULT_DENY_PATTERNS[0]
        with pytest.raises((AttributeError, dataclasses.FrozenInstanceError)):
            rule.rule_id = "tampered"  # type: ignore[misc]

    def test_is_slotted(self):
        assert hasattr(DenyRule, "__slots__"), "DenyRule must be slots=True"

    def test_fields_in_exact_order(self):
        """D3 locks the field order: rule_id, category, pattern, message."""
        field_names = [f.name for f in dataclasses.fields(DenyRule)]
        assert field_names == ["rule_id", "category", "pattern", "message"], (
            f"Field order must be exact, got {field_names}"
        )

    def test_has_four_fields(self):
        """Knight-A: exactly four fields — rule_id, category, pattern, message."""
        names = {f.name for f in dataclasses.fields(DenyRule)}
        assert names == {"rule_id", "category", "pattern", "message"}

    def test_field_types(self):
        """Annotations match D3 exactly."""
        hints = {f.name: f.type for f in dataclasses.fields(DenyRule)}
        assert "str" in str(hints["rule_id"])
        assert "str" in str(hints["category"])
        assert "Pattern" in str(hints["pattern"])
        assert "str" in str(hints["message"])


# ---------------------------------------------------------------------------
# Collection-level invariants (Knight-B)
# ---------------------------------------------------------------------------


class TestCatalogueInvariants:
    def test_deny_patterns_is_tuple(self):
        """D2: tuple, not list — enforces immutability at the collection level."""
        assert isinstance(DEFAULT_DENY_PATTERNS, tuple)

    def test_warn_patterns_is_tuple(self):
        assert isinstance(DEFAULT_WARN_PATTERNS, tuple)

    def test_deny_patterns_non_empty(self):
        assert len(DEFAULT_DENY_PATTERNS) > 0

    def test_warn_patterns_non_empty(self):
        assert len(DEFAULT_WARN_PATTERNS) > 0

    def test_all_entries_are_denyrule(self):
        for r in DEFAULT_DENY_PATTERNS:
            assert isinstance(r, DenyRule), (
                f"{r!r} in DEFAULT_DENY_PATTERNS is not a DenyRule"
            )
        for r in DEFAULT_WARN_PATTERNS:
            assert isinstance(r, DenyRule), (
                f"{r!r} in DEFAULT_WARN_PATTERNS is not a DenyRule"
            )

    def test_all_patterns_precompiled(self):
        for r in DEFAULT_DENY_PATTERNS + DEFAULT_WARN_PATTERNS:
            assert isinstance(r.pattern, re.Pattern), (
                f"{r.rule_id}.pattern must be pre-compiled re.Pattern"
            )

    def test_rule_ids_globally_unique(self):
        """No duplicate rule_id across deny + warn — enables unambiguous
        ``pattern_id`` in SecurityDenied events."""
        ids = [r.rule_id for r in DEFAULT_DENY_PATTERNS + DEFAULT_WARN_PATTERNS]
        duplicates = {i for i in ids if ids.count(i) > 1}
        assert not duplicates, f"Duplicate rule ids: {duplicates}"

    def test_rule_id_format(self):
        """Sage D4 — format ``C<category>.<index>-<slug>``."""
        rx = re.compile(r"^C[1-7]\.\d+-[a-z0-9][a-z0-9\-]*$")
        for r in DEFAULT_DENY_PATTERNS + DEFAULT_WARN_PATTERNS:
            assert rx.match(r.rule_id), (
                f"rule_id {r.rule_id!r} must match C<n>.<idx>-<slug>"
            )


# ---------------------------------------------------------------------------
# CANONICAL slug lockdown (ambiguity #1)
# ---------------------------------------------------------------------------


class TestCanonicalRuleIds:
    """Sage-reconciler ambiguity #1: the Warrior MUST implement exactly these
    rule_ids — no rename, no drop, no add beyond this set."""

    def test_deny_set_matches_canonical(self):
        """Every DENY rule_id is canonical and every canonical DENY rule_id ships."""
        shipped = {r.rule_id for r in DEFAULT_DENY_PATTERNS}
        extra = shipped - CANONICAL_DENY_RULE_IDS
        missing = CANONICAL_DENY_RULE_IDS - shipped
        assert not extra, f"Unknown DENY rule_ids shipped: {extra}"
        assert not missing, f"Canonical DENY rule_ids not shipped: {missing}"

    def test_warn_set_matches_canonical(self):
        shipped = {r.rule_id for r in DEFAULT_WARN_PATTERNS}
        extra = shipped - CANONICAL_WARN_RULE_IDS
        missing = CANONICAL_WARN_RULE_IDS - shipped
        assert not extra, f"Unknown WARN rule_ids shipped: {extra}"
        assert not missing, f"Canonical WARN rule_ids not shipped: {missing}"

    def test_total_count_is_52(self):
        """37 DENY + 15 WARN = 52 rules."""
        total = len(DEFAULT_DENY_PATTERNS) + len(DEFAULT_WARN_PATTERNS)
        assert total == 52, (
            f"Canonical catalogue has 37 DENY + 15 WARN = 52 rules; got {total}"
        )

    def test_deny_count_is_37(self):
        assert len(DEFAULT_DENY_PATTERNS) == 37

    def test_warn_count_is_15(self):
        assert len(DEFAULT_WARN_PATTERNS) == 15

    def test_no_rule_outside_canonical(self):
        """Belt-and-suspenders — every rule_id anywhere must be in CANONICAL_RULE_IDS."""
        for r in DEFAULT_DENY_PATTERNS + DEFAULT_WARN_PATTERNS:
            assert r.rule_id in CANONICAL_RULE_IDS, (
                f"Rule_id {r.rule_id!r} is not in the Sage-locked CANONICAL_RULE_IDS."
            )


# ---------------------------------------------------------------------------
# D4 — category→action mapping (Knight-B)
# ---------------------------------------------------------------------------


class TestCategoryActionMap:
    def test_deny_categories_coverage(self):
        """D4: C1, C2, C3, C4, C7 are the DENY categories."""
        deny_categories = {r.category for r in DEFAULT_DENY_PATTERNS}
        required = {
            "destructive-fs",
            "destructive-git",
            "pipe-to-shell",
            "exfiltration",
            "system-integrity",
        }
        assert required.issubset(deny_categories), (
            f"DENY catalogue missing categories: {required - deny_categories}"
        )

    def test_warn_categories_coverage(self):
        """D4: C5 and C6 are the WARN categories."""
        warn_categories = {r.category for r in DEFAULT_WARN_PATTERNS}
        required = {"priv-escalation", "shell-escape"}
        assert required.issubset(warn_categories), (
            f"WARN catalogue missing categories: {required - warn_categories}"
        )

    def test_no_category_overlap(self):
        """A category lives in exactly one of DENY/WARN (D4 action map)."""
        deny_categories = {r.category for r in DEFAULT_DENY_PATTERNS}
        warn_categories = {r.category for r in DEFAULT_WARN_PATTERNS}
        overlap = deny_categories & warn_categories
        assert not overlap, (
            f"Categories must not span DENY and WARN: overlap={overlap}"
        )

    def test_frozen_catalogue(self):
        """Tuple is immutable by construction."""
        assert type(DEFAULT_DENY_PATTERNS) is tuple
        assert type(DEFAULT_WARN_PATTERNS) is tuple
