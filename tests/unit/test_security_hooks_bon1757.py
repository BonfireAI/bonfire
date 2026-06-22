"""BON-1757 — narrowed broad-except sites in security_hooks stay fail-closed.

Two BLE001 sites were narrowed to typed errors:

  * SITE 1 (``_extract_command``): ``except (UnicodeDecodeError, ValueError)``
    around ``bytes.decode("utf-8", errors="replace")`` — the empty-string
    fail-safe return is preserved.
  * SITE 2 (``build_preexec_hook`` factory): ``except (re.error, TypeError)``
    around ``_compile_user_patterns(...)`` — a bad user-supplied deny pattern
    must still be captured and re-raised into the hook body's fail-CLOSED DENY
    path. It must NEVER turn into an allow and NEVER crash unhandled.

These tests pin the security contract: narrowing the caught type does not
loosen fail-closed semantics.
"""

from __future__ import annotations

import pytest

from bonfire.dispatch.security_hooks import (
    SecurityHooksConfig,
    _extract_command,
    build_preexec_hook,
)


def _bash_event(command: str) -> dict:
    return {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }


class TestSite2DenyPatternFailClosed:
    """A malformed user deny-pattern must DENY (fail-closed), not allow/crash."""

    @pytest.mark.asyncio
    async def test_invalid_regex_open_bracket_denies(self):
        """An invalid regex ``[`` fed through the factory yields a DENY."""
        cfg = SecurityHooksConfig(extra_deny_patterns=["["])
        hook = build_preexec_hook(cfg)

        result = await hook(_bash_event("echo harmless"), "tu", {"signal": None})

        decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
        assert decision == "deny", (
            "A malformed user deny-pattern must fail CLOSED — the narrowed "
            "except (re.error, TypeError) must still capture the compile error "
            "and re-raise it into the hook body's DENY path (BON-1757)."
        )

    @pytest.mark.asyncio
    async def test_invalid_regex_never_allows(self):
        """The broken-pattern path must never produce an allow decision."""
        cfg = SecurityHooksConfig(extra_deny_patterns=[r"([unclosed"])
        hook = build_preexec_hook(cfg)

        result = await hook(_bash_event("ls -la"), "tu", {"signal": None})

        decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
        assert decision != "allow", (
            "A bad user pattern must never become an allow — fail-closed is the "
            "security contract (BON-1757)."
        )

    @pytest.mark.asyncio
    async def test_valid_pattern_still_works(self):
        """A well-formed user pattern still compiles and is enforced."""
        cfg = SecurityHooksConfig(extra_deny_patterns=[r"\bDANGER_TOKEN\b"])
        hook = build_preexec_hook(cfg)

        denied = await hook(_bash_event("run DANGER_TOKEN now"), "tu", {"signal": None})
        assert denied.get("hookSpecificOutput", {}).get("permissionDecision") == "deny", (
            "A valid user deny-pattern must still match and DENY (BON-1757)."
        )


class TestSite1ExtractCommandFailSafe:
    """SITE 1: ``_extract_command`` returns '' on a decode edge case."""

    def test_bytes_command_decodes_with_replacement(self):
        """Invalid UTF-8 bytes decode via errors='replace', not the except path."""
        # 0xff is invalid UTF-8; errors="replace" yields U+FFFD, never raises.
        out = _extract_command("Bash", {"command": b"echo \xff"})
        assert isinstance(out, str)
        assert out.startswith("echo ")

    def test_non_bytes_non_str_command_returns_empty(self):
        """A non-bytes, non-str payload returns '' (fail-safe empty string)."""
        assert _extract_command("Bash", {"command": 12345}) == ""
