# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract — Write/Edit + cat deny family across macOS and Windows.

The prior ``WRITE_EDIT_SENSITIVE_PATH_DENY`` (SSH/AWS/GnuPG/etc. prefixes)
plus the C4 ``cat <secret>`` regex family gate the home directory through
the same Linux-only assumption:

    bonfire.dispatch.security_hooks._HOME_PREFIX_RE
        = re.compile(r"^(?:\\$HOME|/home/[^/]+)(/|$)")

    bonfire.dispatch.security_patterns C4.1 / C5.5
        = r"(?:~|\\$HOME|/home/[^/\\s]+)?/?\\.ssh/..."

``$HOME`` and ``~`` are platform-portable; ``/home/<user>/`` is Linux-only.
**macOS** ``/Users/<user>/...`` and **Windows** ``C:\\Users\\<user>\\...`` are
silently invisible to the canonical-prefix collapse, so the trust-triangle
default-allow-list "credential" floor is effectively absent on those two
platforms — even though ``CLAUDE.md`` lists Linux, macOS, Windows as supported.

These tests pin the contract that the canonical-prefix collapse + the C4/C5
``(?:~|\\$HOME|/home/<user>|...)`` alternations MUST also accept:

  - macOS:   ``/Users/<user>/...``
  - Windows: ``C:\\Users\\<user>\\...`` (with ``\\`` or ``\\\\`` or ``/`` separators)

The implementation GREENs these by extending ``_HOME_PREFIX_RE`` and
mirroring the new alternatives into C4.1 / C5.5 / etc. regexes (and
normalising Windows backslashes to forward slashes BEFORE prefix scan +
tail-segment check).

Test inventory:

1. macOS  SSH key Write/Edit deny.
2. macOS  AWS credentials Write/Edit deny.
3. macOS  GnuPG Write/Edit deny.
4. macOS  dotenv Write/Edit deny (NOTE: tail-segment ``.env`` matcher already
   catches this on Linux; included for the macOS path regression-guard. Likely
   GREEN today — captures the case where future work breaks the segment
   fallback while extending the prefix family.)
5. Windows SSH key Write/Edit deny.
6. Windows AWS credentials Write/Edit deny.
7. Windows backslash/forward-slash/escaped-backslash normalisation.
8. macOS  C4 ``cat /Users/<u>/.ssh/id_rsa`` Bash deny (regex alternation gap).
9. Linux  regression smoke — pre-existing surface still GREEN.
"""

from __future__ import annotations

from typing import Any

import pytest

try:
    from bonfire.dispatch import security_hooks as _mod
    from bonfire.dispatch.security_hooks import (
        SecurityHooksConfig,
        build_preexec_hook,
    )
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    _mod = None  # type: ignore[assignment]
    SecurityHooksConfig = None  # type: ignore[assignment,misc]
    build_preexec_hook = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module() -> None:
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.security_hooks not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Test harness — matches tests/unit/test_security_hooks_write_edit_sensitive_paths.py
# ---------------------------------------------------------------------------


async def _run_tool(tool_name: str, tool_input: dict[str, Any]) -> dict:
    """Build a fresh hook and evaluate a single PreToolUse event."""
    hook = build_preexec_hook(SecurityHooksConfig())
    return await hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": tool_input,
        },
        "tu1",
        {"signal": None},
    )


async def _run_write_edit(tool_name: str, file_path: str) -> dict:
    return await _run_tool(tool_name, {"file_path": file_path})


async def _run_bash(command: str) -> dict:
    return await _run_tool("Bash", {"command": command})


def _is_deny(result: dict) -> bool:
    return result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


# ---------------------------------------------------------------------------
# Test #1 — macOS SSH key deny
# ---------------------------------------------------------------------------


MACOS_SSH_PATHS = [
    "/Users/alice/.ssh/authorized_keys",
    "/Users/alice/.ssh/id_rsa",
    "/Users/alice/.ssh/id_ed25519",
    "/Users/alice/.ssh/id_ecdsa",
    "/Users/alice/.ssh/known_hosts",
]


class TestMacOSSSHDeny:
    """A Write or Edit of an SSH credential under ``/Users/<u>/.ssh/`` denies."""

    @pytest.mark.parametrize("path", MACOS_SSH_PATHS)
    @pytest.mark.asyncio
    async def test_macos_ssh_write_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"macOS SSH Write of {path!r} must deny — "
            "trust-triangle credential floor must cover /Users/<u>/.ssh/"
        )

    @pytest.mark.parametrize("path", MACOS_SSH_PATHS)
    @pytest.mark.asyncio
    async def test_macos_ssh_edit_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"macOS SSH Edit of {path!r} must deny — "
            "trust-triangle credential floor must cover /Users/<u>/.ssh/"
        )


# ---------------------------------------------------------------------------
# Test #2 — macOS AWS credentials deny
# ---------------------------------------------------------------------------


MACOS_AWS_PATHS = [
    "/Users/alice/.aws/credentials",
    "/Users/alice/.aws/config",
]


class TestMacOSAWSDeny:
    @pytest.mark.parametrize("path", MACOS_AWS_PATHS)
    @pytest.mark.asyncio
    async def test_macos_aws_write_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        # Only "credentials" is in the deny list today; "config" depends on
        # whether the implementation extends the deny list. Limit assertion to the
        # canonical "credentials" file.
        if not path.endswith("credentials"):
            pytest.skip("only ~/.aws/credentials is canonically deny")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"macOS AWS Write of {path!r} must deny — "
            "trust-triangle credential floor must cover /Users/<u>/.aws/"
        )

    @pytest.mark.parametrize("path", MACOS_AWS_PATHS)
    @pytest.mark.asyncio
    async def test_macos_aws_edit_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        if not path.endswith("credentials"):
            pytest.skip("only ~/.aws/credentials is canonically deny")
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"macOS AWS Edit of {path!r} must deny — "
            "trust-triangle credential floor must cover /Users/<u>/.aws/"
        )


# ---------------------------------------------------------------------------
# Test #3 — macOS GnuPG deny
# ---------------------------------------------------------------------------


MACOS_GNUPG_PATHS = [
    "/Users/alice/.gnupg/secring.gpg",
    "/Users/alice/.gnupg/pubring.kbx",
    "/Users/alice/.gnupg/private-keys-v1.d/foo.key",
    "/Users/alice/.gnupg/trustdb.gpg",
]


class TestMacOSGnuPGDeny:
    @pytest.mark.parametrize("path", MACOS_GNUPG_PATHS)
    @pytest.mark.asyncio
    async def test_macos_gnupg_write_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"macOS GnuPG Write of {path!r} must deny — "
            "trust-triangle credential floor must cover /Users/<u>/.gnupg/"
        )

    @pytest.mark.parametrize("path", MACOS_GNUPG_PATHS)
    @pytest.mark.asyncio
    async def test_macos_gnupg_edit_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"macOS GnuPG Edit of {path!r} must deny — "
            "trust-triangle credential floor must cover /Users/<u>/.gnupg/"
        )


# ---------------------------------------------------------------------------
# Test #4 — macOS dotenv deny
#
# Note: ``_match_write_edit_sensitive_path`` already has a tail-segment
# match for ``.env`` / ``.env.*`` (case-sensitive, segment-anchored) that runs
# AFTER the canonical-prefix scan. ``rsplit("/", 1)[-1]`` on
# ``/Users/alice/Projects/myrepo/.env`` returns ``.env``, so this case ALREADY
# DENIES today even though the macOS ``/Users/`` prefix never reaches the
# prefix scan. Included here as a regression-guard so the regex rework
# does not accidentally regress the tail-segment fallback.
# ---------------------------------------------------------------------------


MACOS_DOTENV_PATHS = [
    "/Users/alice/Projects/myrepo/.env",
    "/Users/alice/Projects/myrepo/.env.local",
    "/Users/alice/Projects/myrepo/.env.production",
    "/Users/alice/.env",
]


class TestMacOSDotenvDeny:
    @pytest.mark.parametrize("path", MACOS_DOTENV_PATHS)
    @pytest.mark.asyncio
    async def test_macos_dotenv_write_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"macOS dotenv Write of {path!r} must deny — "
            "tail-segment ``.env`` match (and the new macOS prefix) must "
            "both keep this denied."
        )

    @pytest.mark.parametrize("path", MACOS_DOTENV_PATHS)
    @pytest.mark.asyncio
    async def test_macos_dotenv_edit_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"macOS dotenv Edit of {path!r} must deny — "
            "tail-segment ``.env`` match (and the new macOS prefix) must "
            "both keep this denied."
        )


# ---------------------------------------------------------------------------
# Test #5 — Windows SSH key deny
# ---------------------------------------------------------------------------


WINDOWS_SSH_PATHS = [
    r"C:\Users\alice\.ssh\authorized_keys",
    r"C:\Users\alice\.ssh\id_rsa",
    r"C:\Users\alice\.ssh\id_ed25519",
    r"C:\Users\alice\.ssh\known_hosts",
]


class TestWindowsSSHDeny:
    @pytest.mark.parametrize("path", WINDOWS_SSH_PATHS)
    @pytest.mark.asyncio
    async def test_windows_ssh_write_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        # Windows operators set both HOME and USERPROFILE.
        monkeypatch.setenv("HOME", r"C:\Users\alice")
        monkeypatch.setenv("USERPROFILE", r"C:\Users\alice")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Windows SSH Write of {path!r} must deny — "
            "trust-triangle credential floor must cover C:\\Users\\<u>\\.ssh\\"
        )

    @pytest.mark.parametrize("path", WINDOWS_SSH_PATHS)
    @pytest.mark.asyncio
    async def test_windows_ssh_edit_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", r"C:\Users\alice")
        monkeypatch.setenv("USERPROFILE", r"C:\Users\alice")
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"Windows SSH Edit of {path!r} must deny — "
            "trust-triangle credential floor must cover C:\\Users\\<u>\\.ssh\\"
        )


# ---------------------------------------------------------------------------
# Test #6 — Windows AWS credentials deny
# ---------------------------------------------------------------------------


WINDOWS_AWS_PATHS = [
    r"C:\Users\alice\.aws\credentials",
]


class TestWindowsAWSDeny:
    @pytest.mark.parametrize("path", WINDOWS_AWS_PATHS)
    @pytest.mark.asyncio
    async def test_windows_aws_write_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", r"C:\Users\alice")
        monkeypatch.setenv("USERPROFILE", r"C:\Users\alice")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Windows AWS Write of {path!r} must deny — "
            "trust-triangle credential floor must cover C:\\Users\\<u>\\.aws\\"
        )

    @pytest.mark.parametrize("path", WINDOWS_AWS_PATHS)
    @pytest.mark.asyncio
    async def test_windows_aws_edit_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", r"C:\Users\alice")
        monkeypatch.setenv("USERPROFILE", r"C:\Users\alice")
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"Windows AWS Edit of {path!r} must deny — "
            "trust-triangle credential floor must cover C:\\Users\\<u>\\.aws\\"
        )


# ---------------------------------------------------------------------------
# Test #7 — Windows separator normalisation
#
# The same logical path can arrive at the hook in three encodings:
#
#   1. Single backslash:    C:\Users\alice\.ssh\authorized_keys
#   2. Escaped backslash:   C:\\Users\\alice\\.ssh\\authorized_keys
#   3. Forward slash:       C:/Users/alice/.ssh/authorized_keys
#
# All three must DENY. The Warrior canonicalises by normalising backslashes
# to forward slashes BEFORE prefix scan + tail-segment check.
# ---------------------------------------------------------------------------


WINDOWS_NORMALISATION_VARIANTS = [
    # Single backslash (raw literal — Python string contains real \).
    r"C:\Users\alice\.ssh\authorized_keys",
    # Doubled / escaped — what an agent might emit when serialising JSON
    # without a final unescape pass.
    r"C:\\Users\\alice\\.ssh\\authorized_keys",
    # Forward-slash variant (common from cross-platform tooling).
    "C:/Users/alice/.ssh/authorized_keys",
]


class TestWindowsSeparatorNormalisation:
    @pytest.mark.parametrize("path", WINDOWS_NORMALISATION_VARIANTS)
    @pytest.mark.asyncio
    async def test_windows_ssh_authorized_keys_normalised(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", r"C:\Users\alice")
        monkeypatch.setenv("USERPROFILE", r"C:\Users\alice")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Windows separator variant {path!r} must deny — "
            "canonicalisation must accept \\ / \\\\ / and forward-slash forms."
        )


# ---------------------------------------------------------------------------
# Test #8 — macOS C4 ``cat`` Bash bypass
#
# C4.1 in ``security_patterns.py`` line 244:
#     \bcat\s+(?:~|\$HOME|/home/[^/\s]+)?/?\.ssh/...
#
# The alternation is Linux-only. ``cat /Users/alice/.ssh/id_rsa`` on macOS
# does NOT match the regex and slips through. The Warrior must extend the
# alternation to include ``/Users/[^/\s]+`` and ``[A-Z]:[/\\]Users[/\\][^/\\\\s]+``.
# ---------------------------------------------------------------------------


MACOS_CAT_BYPASS = [
    "cat /Users/alice/.ssh/id_rsa",
    "cat /Users/alice/.ssh/id_ed25519",
    "cat /Users/alice/.ssh/authorized_keys",
    "head /Users/alice/.ssh/id_rsa",
    "tail /Users/alice/.ssh/id_ed25519",
    "cat /Users/alice/.aws/credentials",
    "cat /Users/alice/.gnupg/secring.gpg",
]


class TestMacOSCatC4Bypass:
    @pytest.mark.parametrize("cmd", MACOS_CAT_BYPASS)
    @pytest.mark.asyncio
    async def test_macos_cat_secret_denied_at_c4_layer(
        self,
        monkeypatch: pytest.MonkeyPatch,
        cmd: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/Users/alice")
        result = await _run_bash(cmd)
        assert _is_deny(result), (
            f"macOS ``{cmd}`` must deny — C4 regex alternation must "
            "include /Users/<u>/ alongside /home/<u>/"
        )


# ---------------------------------------------------------------------------
# Test #9 — Linux regression smoke
#
# Ensure the regex rework keeps the prior Linux surface intact.
# These all PASS today and must STAY passing after the macOS/Windows fix.
# ---------------------------------------------------------------------------


LINUX_SMOKE_PATHS = [
    "/home/alice/.ssh/authorized_keys",
    "/home/alice/.ssh/id_rsa",
    "/home/alice/.aws/credentials",
    "/home/alice/.gnupg/secring.gpg",
    "~/.ssh/authorized_keys",
    "$HOME/.ssh/id_rsa",
]


class TestLinuxRegressionSmoke:
    @pytest.mark.parametrize("path", LINUX_SMOKE_PATHS)
    @pytest.mark.asyncio
    async def test_linux_write_still_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
        path: str,
    ) -> None:
        monkeypatch.setenv("HOME", "/home/alice")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Linux regression — Write of {path!r} must STILL deny after "
            "the macOS/Windows extension lands. Pre-existing surface guard."
        )

    @pytest.mark.asyncio
    async def test_linux_cat_ssh_still_denied(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("HOME", "/home/alice")
        result = await _run_bash("cat /home/alice/.ssh/id_rsa")
        assert _is_deny(result), (
            "Linux regression — ``cat /home/<u>/.ssh/id_rsa`` C4.1 must "
            "STILL deny after the alternation extension lands."
        )
