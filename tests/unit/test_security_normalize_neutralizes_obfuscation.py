"""Regression contract — normalization already neutralizes IFS + Unicode obfuscation.

Two shell-escape pattern rules in the catalogue are structurally unreachable:
an ``$IFS``-space-substitution rule and a Unicode-lookalike rule. Both try to
match byte patterns that the hook's Stage-1 normalization has ALREADY folded
away before any pattern is evaluated:

- ``_normalize`` runs ``unicodedata.normalize("NFKC", ...)``, which collapses
  the fullwidth / NBSP / zero-width codepoints the lookalike rule targets into
  their plain-ASCII (or space) equivalents.
- ``_normalize`` then runs an explicit ``$IFS`` -> space substitution, which
  erases the ``$IFS`` / ``${IFS}`` / ``$IFS$9`` tokens the IFS rule targets.

So by the time pattern matching runs, those tokens no longer exist in the
string and the two rules can never fire. Deleting them does NOT weaken the
security surface, because the bypass attempts they nominally guarded are still
caught — by the surviving DENY rules acting on the post-normalization command.

This file is the proof of that claim. It asserts the *behavioral* outcome
(the bypass is still loudly DENIED through the hook) AND the *catalogue*
outcome (the two dead rule_ids are gone, the WARN count drops accordingly).
The behavioral assertions stand independent of which rule fires — they pin the
real contract: obfuscated dangerous commands get a typed deny envelope, not a
silent pass.
"""

from __future__ import annotations

from typing import Any

import pytest

from bonfire.dispatch.security_hooks import (
    SecurityHooksConfig,
    _normalize,
    build_preexec_hook,
)
from bonfire.dispatch.security_patterns import DEFAULT_WARN_PATTERNS

# rule_ids of the two structurally-unreachable rules being removed.
_DEAD_IFS_RULE_ID = "C6.3-ifs-bypass"
_DEAD_UNICODE_RULE_ID = "C6.6-unicode-lookalike"


def _is_deny(result: dict[str, Any]) -> bool:
    """True iff the hook returned a typed PreToolUse *deny* envelope."""
    try:
        out = result["hookSpecificOutput"]
    except (KeyError, TypeError):
        return False
    return out.get("hookEventName") == "PreToolUse" and out.get("permissionDecision") == "deny"


async def _run(cmd: str) -> dict[str, Any]:
    hook = build_preexec_hook(SecurityHooksConfig())
    return await hook(
        {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}},
        "tu-normalize-regression",
        {"signal": None},
    )


class TestNormalizationFoldsAwayTheBypassTokens:
    """Stage-1 normalization erases the exact tokens the dead rules matched."""

    def test_ifs_tokens_are_gone_after_normalize(self):
        """``$IFS`` / ``${IFS}`` / ``$IFS$9`` do not survive normalization.

        The IFS rule's regex (``\\$(?:IFS(?:\\$[0-9])?|\\{IFS\\})``) cannot match
        a string that no longer contains the substring ``$IFS`` or ``${IFS}``.
        """
        for raw in ("cat$IFS/etc/passwd", "cat${IFS}/etc/passwd", "cat$IFS$9/etc/passwd"):
            normalized = _normalize(raw)
            assert "$IFS" not in normalized, raw
            assert "${IFS}" not in normalized, raw

    def test_fullwidth_lookalikes_are_folded_after_normalize(self):
        """NFKC folds fullwidth ``ｒｍ`` -> ASCII ``rm`` and NBSP -> a space.

        After folding, none of the codepoints the lookalike rule scans for
        (NBSP / zero-widths / fullwidth) remain, so the rule has nothing left
        to match.
        """
        lookalike_codepoints = (
            [0x00A0]
            + list(range(0x2000, 0x2010))
            + list(range(0x2028, 0x2030))
            + list(range(0xFF01, 0xFF5F))
        )
        # Fullwidth "rm -rf /" -> ASCII; NBSP between cat and path -> space.
        for raw in ("ｒｍ -rf /", "cat /etc/passwd"):
            normalized = _normalize(raw)
            for cp in lookalike_codepoints:
                assert chr(cp) not in normalized, (raw, hex(cp))


class TestBypassStillDeniedWithoutTheDeadRules:
    """Failure-path proof: the obfuscated dangerous command is still loudly DENIED."""

    @pytest.mark.asyncio
    async def test_ifs_wrapped_credential_read_denied(self):
        """``cat${IFS}~/.ssh/id_rsa`` -> normalize -> ``cat ~/.ssh/id_rsa`` -> DENY.

        The deny is produced by the surviving SSH-private-key exfiltration rule,
        NOT by any IFS-specific rule. This is the typed-failure contract: an
        obfuscated exfil attempt returns a deny envelope, never a silent allow.
        """
        result = await _run("cat${IFS}~/.ssh/id_rsa")
        assert _is_deny(result), result
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason, "a DENY must carry a non-empty, human-readable reason"

    @pytest.mark.asyncio
    async def test_ifs_dollar9_credential_read_denied(self):
        result = await _run("cat$IFS$9~/.ssh/id_rsa")
        assert _is_deny(result), result

    @pytest.mark.asyncio
    async def test_fullwidth_rm_rf_denied(self):
        """Fullwidth ``ｒｍ -rf /`` -> NFKC -> ``rm -rf /`` -> DENY via the rm rule."""
        result = await _run("ｒｍ -rf /")
        assert _is_deny(result), result
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert reason, "a DENY must carry a non-empty, human-readable reason"


class TestDeadRulesAreRemovedFromCatalogue:
    """Catalogue contract: the two unreachable rule_ids no longer ship."""

    def test_ifs_rule_id_absent(self):
        ids = {r.rule_id for r in DEFAULT_WARN_PATTERNS}
        assert _DEAD_IFS_RULE_ID not in ids, (
            f"{_DEAD_IFS_RULE_ID} is structurally unreachable (normalize folds $IFS "
            "away before matching) and must not ship as a live rule"
        )

    def test_unicode_rule_id_absent(self):
        ids = {r.rule_id for r in DEFAULT_WARN_PATTERNS}
        assert _DEAD_UNICODE_RULE_ID not in ids, (
            f"{_DEAD_UNICODE_RULE_ID} is structurally unreachable (NFKC folds the "
            "lookalike codepoints away before matching) and must not ship as a live rule"
        )

    def test_warn_count_dropped_by_two(self):
        """C5 (7) + C6 (6 after removing two dead C6 rules) = 13 WARN rules."""
        assert len(DEFAULT_WARN_PATTERNS) == 13, (
            "Removing the two unreachable C6 rules leaves 13 WARN rules "
            f"(7 priv-escalation + 6 shell-escape); got {len(DEFAULT_WARN_PATTERNS)}"
        )
