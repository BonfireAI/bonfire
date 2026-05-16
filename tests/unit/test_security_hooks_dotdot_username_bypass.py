# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract — ``_HOME_PREFIX_RE`` refuses ``.`` and ``..`` as the
``[^/]+`` username slot.

Pins a CRITICAL audit finding against
``bonfire/dispatch/security_hooks.py``'s ``_HOME_PREFIX_RE`` regex
(line ~356, pre-fix shape)::

    re.compile(r"^(?:\\$HOME|/home/[^/]+|/Users/[^/]+|[A-Za-z]:/Users/[^/]+)(/|$)")

The ``[^/]+`` username slots happily match the literal segments ``.``
and ``..``. On input ``/home/../etc/sudoers`` the pre-fix code:

1. Matches ``/home/../`` (``..`` consumed as username).
2. Substitutes to ``~/etc/sudoers``.
3. ``_resolve_dot_segments`` sees no ``..`` left to flag as underflow.
4. Canonical ``~/etc/sudoers`` matches NO entry in
   ``WRITE_EDIT_SENSITIVE_PATH_DENY`` (entries are ``/etc/sudoers``,
   ``~/.ssh/...``, etc. — none start with ``~/etc/``).
5. The hook returns ``{}``, the kernel opens the original
   ``/home/../etc/sudoers`` which resolves to ``/etc/sudoers``, and the
   ENTIRE WRITE_EDIT deny floor is silently bypassed.

The same bypass shape voids every deny prefix via ``/home/../``,
``/Users/../``, and ``[A-Za-z]:/Users/../``.

The fix excludes ``.`` and ``..`` from the username slot via negative
lookahead AND re-runs the home-prefix collapse after dot-segment
resolution so cleaned-up paths like ``/home/../home/alice/.ssh/id_rsa``
(which dot-segment cleans to ``/home/alice/.ssh/id_rsa``) get
collapsed to ``~/.ssh/id_rsa`` for the deny scan.

Scope guards:

- Case-fold of the literal ``Users`` segment on lowercase Windows
  inputs (``c:/users/../etc/passwd``) is a SEPARATE issue (the regex
  has literal ``Users`` and only case-folds the drive letter). xfailed
  here as a known canary.
- Windows-system targets like ``D:/Users/../Windows/System32/config/SAM``
  are absent from ``WRITE_EDIT_SENSITIVE_PATH_DENY`` (the deny list
  covers home-credential + POSIX system-state paths, not Windows
  system state). xfailed here as a known canary.
- URL-encoded ``%2e%2e`` is out of scope for v0.1 — canonicalizer does
  not decode percent-escapes. xfailed as a known canary.
"""

from __future__ import annotations

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


async def _run_write_edit(tool_name: str, file_path: str) -> dict:
    hook = build_preexec_hook(SecurityHooksConfig())
    return await hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": tool_name,
            "tool_input": {"file_path": file_path},
        },
        "tu1",
        {"signal": None},
    )


def _is_deny(result: dict) -> bool:
    return result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


# ---------------------------------------------------------------------------
# Linux ``/home/../`` bypass — username slot ``..`` traverses upward.
# After dot-segment resolution lands at root, the cleaned path either
# matches a system-state deny prefix (``/etc/sudoers``, ``/root/``)
# directly OR re-collapses through the second home-prefix pass back to
# ``~/...`` form for the credential deny scan.
# ---------------------------------------------------------------------------


LINUX_DOTDOT_USERNAME_CASES = [
    # (case_id, file_path)
    # ``..`` lifts off /home/ and lands on /etc/ — system-state deny.
    ("home_dotdot_etc_sudoers", "/home/../etc/sudoers"),
    ("home_dotdot_etc_shadow", "/home/../etc/shadow"),
    ("home_dotdot_etc_passwd", "/home/../etc/passwd"),
    ("home_dotdot_etc_gshadow", "/home/../etc/gshadow"),
    # ``..`` lifts off and lands on /root/ — root-home deny.
    ("home_dotdot_root_ssh_authkeys", "/home/../root/.ssh/authorized_keys"),
    ("home_dotdot_root_bashrc", "/home/../root/.bashrc"),
    # ``..`` lifts off and re-enters /home/<realuser>/ — credential deny
    # after the second home-prefix pass collapses to ``~/...``.
    ("home_dotdot_home_alice_ssh_id_rsa", "/home/../home/alice/.ssh/id_rsa"),
    ("home_dotdot_home_alice_aws_creds", "/home/../home/alice/.aws/credentials"),
    ("home_dotdot_home_alice_kube", "/home/../home/alice/.kube/config"),
]


class TestLinuxDotDotUsernameBypass:
    """``/home/../X`` shapes — the ``..`` segment was previously eaten
    by ``_HOME_PREFIX_RE``'s ``[^/]+`` username slot, leaving no
    underflow signal for the matcher to refuse on. The fix's negative
    lookahead refuses ``.`` and ``..`` as username; dot-segment
    resolution then collapses ``../`` correctly and either lands on a
    system-state deny prefix or re-enters the home-prefix collapse via
    a second pass.
    """

    @pytest.mark.parametrize(
        "file_path",
        [c[1] for c in LINUX_DOTDOT_USERNAME_CASES],
        ids=[c[0] for c in LINUX_DOTDOT_USERNAME_CASES],
    )
    @pytest.mark.asyncio
    async def test_write_dotdot_username_denied(self, file_path: str) -> None:
        result = await _run_write_edit("Write", file_path)
        assert _is_deny(result), (
            f"Write of {file_path!r} must DENY — ``/home/../`` with "
            "``..`` as the username slot escapes the home prefix and "
            "lands on a credential or system-state target. The pre-fix "
            "regex ate ``..`` as a valid username and the canonical form "
            f"missed every deny prefix. Got {result!r}."
        )

    @pytest.mark.parametrize(
        "file_path",
        [c[1] for c in LINUX_DOTDOT_USERNAME_CASES],
        ids=[c[0] for c in LINUX_DOTDOT_USERNAME_CASES],
    )
    @pytest.mark.asyncio
    async def test_edit_dotdot_username_denied(self, file_path: str) -> None:
        result = await _run_write_edit("Edit", file_path)
        assert _is_deny(result), (
            f"Edit of {file_path!r} must DENY — ``/home/../`` with "
            "``..`` as the username slot escapes the home prefix. "
            f"Got {result!r}."
        )


# ---------------------------------------------------------------------------
# macOS ``/Users/../`` bypass — same shape, different home root literal.
# ---------------------------------------------------------------------------


MACOS_DOTDOT_USERNAME_CASES = [
    ("users_dotdot_etc_sudoers", "/Users/../etc/sudoers"),
    ("users_dotdot_etc_passwd", "/Users/../etc/passwd"),
    ("users_dotdot_users_realuser_aws", "/Users/../Users/realuser/.aws/credentials"),
    ("users_dotdot_users_realuser_ssh", "/Users/../Users/realuser/.ssh/id_rsa"),
    ("users_dotdot_users_realuser_kube", "/Users/../Users/realuser/.kube/config"),
    ("users_dot_dotdot_etc_passwd", "/Users/./../etc/passwd"),
]


class TestMacOSDotDotUsernameBypass:
    """``/Users/../X`` shapes — the macOS analogue of the Linux
    ``/home/../`` bypass. Same regex defect, same fix.
    """

    @pytest.mark.parametrize(
        "file_path",
        [c[1] for c in MACOS_DOTDOT_USERNAME_CASES],
        ids=[c[0] for c in MACOS_DOTDOT_USERNAME_CASES],
    )
    @pytest.mark.asyncio
    async def test_write_dotdot_username_denied(self, file_path: str) -> None:
        result = await _run_write_edit("Write", file_path)
        assert _is_deny(result), (
            f"Write of {file_path!r} must DENY — ``/Users/../`` with "
            "``..`` as the username slot bypasses the credential deny "
            f"floor. Got {result!r}."
        )

    @pytest.mark.parametrize(
        "file_path",
        [c[1] for c in MACOS_DOTDOT_USERNAME_CASES],
        ids=[c[0] for c in MACOS_DOTDOT_USERNAME_CASES],
    )
    @pytest.mark.asyncio
    async def test_edit_dotdot_username_denied(self, file_path: str) -> None:
        result = await _run_write_edit("Edit", file_path)
        assert _is_deny(result), (
            f"Edit of {file_path!r} must DENY — ``/Users/../`` with "
            f"``..`` as the username slot. Got {result!r}."
        )


# ---------------------------------------------------------------------------
# Windows-style ``[A-Za-z]:/Users/../`` bypass.
#
# Only the credential case (``C:/Users/../Users/<u>/.ssh/id_rsa``) is
# closable by the regex fix — the cleaned path re-enters the home
# prefix collapse via the second pass and lands on the ``~/.ssh/id_``
# credential deny prefix.
# ---------------------------------------------------------------------------


WIN_DOTDOT_USERNAME_CASES = [
    ("c_drive_dotdot_users_admin_ssh", "C:/Users/../Users/admin/.ssh/id_rsa"),
    ("c_drive_dotdot_users_admin_authkeys", "C:/Users/../Users/admin/.ssh/authorized_keys"),
    ("c_drive_dotdot_users_admin_aws", "C:/Users/../Users/admin/.aws/credentials"),
]


class TestWindowsDotDotUsernameBypass:
    """``C:/Users/../Users/<u>/...`` — the cleaned path re-enters the
    home-prefix collapse via the second pass and matches a credential
    deny prefix. Windows-style with forward slashes (the canonicalizer
    normalizes backslashes upstream).
    """

    @pytest.mark.parametrize(
        "file_path",
        [c[1] for c in WIN_DOTDOT_USERNAME_CASES],
        ids=[c[0] for c in WIN_DOTDOT_USERNAME_CASES],
    )
    @pytest.mark.asyncio
    async def test_write_dotdot_username_denied(self, file_path: str) -> None:
        result = await _run_write_edit("Write", file_path)
        assert _is_deny(result), (
            f"Write of {file_path!r} must DENY — ``C:/Users/../`` with "
            "``..`` as the username slot bypasses the credential deny "
            f"floor. Got {result!r}."
        )

    @pytest.mark.parametrize(
        "file_path",
        [c[1] for c in WIN_DOTDOT_USERNAME_CASES],
        ids=[c[0] for c in WIN_DOTDOT_USERNAME_CASES],
    )
    @pytest.mark.asyncio
    async def test_edit_dotdot_username_denied(self, file_path: str) -> None:
        result = await _run_write_edit("Edit", file_path)
        assert _is_deny(result), (
            f"Edit of {file_path!r} must DENY — ``C:/Users/../`` with "
            f"``..`` as the username slot. Got {result!r}."
        )


# ---------------------------------------------------------------------------
# Known canaries — defects that are NOT closed by this fix but are
# adjacent to the audit surface. xfail(strict=True) so a future
# remediation flips them GREEN and we notice.
# ---------------------------------------------------------------------------


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Lowercase ``c:/users/...`` does not match _HOME_PREFIX_RE — the "
        "regex has literal ``Users`` and only case-folds the drive letter. "
        "Case-folding the literal ``Users`` segment is a separate Windows "
        "ergonomics fix tracked outside this Probe N+7 C1 change."
    ),
)
@pytest.mark.asyncio
async def test_lowercase_users_dotdot_bypass_is_known_canary() -> None:
    result = await _run_write_edit("Write", "c:/users/../etc/passwd")
    assert _is_deny(result)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Windows system-state paths (e.g. ``Windows/System32/config/SAM``) "
        "are not in WRITE_EDIT_SENSITIVE_PATH_DENY. The deny list covers "
        "home-credential + POSIX system-state. Expanding to Windows system "
        "state is a separate deny-list addition, not part of this Probe "
        "N+7 C1 regex fix."
    ),
)
@pytest.mark.asyncio
async def test_windows_system_dotdot_bypass_is_known_canary() -> None:
    result = await _run_write_edit("Write", "D:/Users/../Windows/System32/config/SAM")
    assert _is_deny(result)


@pytest.mark.xfail(
    strict=True,
    reason=(
        "URL-encoded ``%2e%2e`` is out of scope for v0.1 — the "
        "canonicalizer does not decode percent-escapes. Pins the open "
        "question for a future canonicalizer extension."
    ),
)
@pytest.mark.asyncio
async def test_url_encoded_dotdot_username_bypass_is_known_canary() -> None:
    result = await _run_write_edit("Write", "/home/../%2e%2e/etc/sudoers")
    assert _is_deny(result)


# ---------------------------------------------------------------------------
# Positive shapes — the fix MUST NOT regress legitimate home-prefix
# matching. These paths have valid usernames (not ``.`` or ``..``) and
# must still collapse to ``~/...`` form (or fall through cleanly for
# non-credential targets).
# ---------------------------------------------------------------------------


LEGITIMATE_HOME_CASES = [
    # (case_id, file_path, expected_deny)
    # Legitimate home paths that ARE in the deny list — must still DENY.
    ("home_alice_ssh_id_rsa", "/home/alice/.ssh/id_rsa", True),
    ("home_alice_aws_creds", "/home/alice/.aws/credentials", True),
    ("users_bob_ssh_id_rsa", "/Users/bob/.ssh/id_rsa", True),
    ("c_drive_admin_ssh_id_rsa", "C:/Users/admin/.ssh/id_rsa", True),
    ("home_env_var_ssh_id_rsa", "$HOME/.ssh/id_rsa", True),
    # Legitimate home paths that are NOT in the deny list — must NOT deny.
    ("home_alice_project_file", "/home/alice/projects/foo.py", False),
    ("users_bob_desktop", "/Users/bob/Desktop/file.txt", False),
    ("c_drive_admin_docs", "C:/Users/admin/Documents/file.txt", False),
    ("home_env_var_proj", "$HOME/projects/bar.py", False),
    # Usernames that contain a dot but are not literal ``.`` or ``..``
    # (e.g. ``alice.example``, ``.hidden_user``) — must still match.
    ("home_dotted_username_ssh", "/home/alice.example/.ssh/id_rsa", True),
    ("home_dot_prefixed_username_aws", "/home/.hidden/.aws/credentials", True),
]


class TestLegitimateHomePathsPreservedByFix:
    """The fix's negative lookahead must NOT regress real usernames —
    only literal ``.`` and ``..`` segments are refused.
    """

    @pytest.mark.parametrize(
        "file_path,expected_deny",
        [(c[1], c[2]) for c in LEGITIMATE_HOME_CASES],
        ids=[c[0] for c in LEGITIMATE_HOME_CASES],
    )
    @pytest.mark.asyncio
    async def test_legitimate_home_paths(self, file_path: str, expected_deny: bool) -> None:
        result = await _run_write_edit("Write", file_path)
        actual_deny = _is_deny(result)
        assert actual_deny == expected_deny, (
            f"{file_path!r}: expected deny={expected_deny}, got deny={actual_deny}. "
            f"Result: {result!r}"
        )


# ---------------------------------------------------------------------------
# Direct unit assertions on _canonicalize_write_edit_path so the regex
# behavior is pinned independently of the full hook plumbing.
# ---------------------------------------------------------------------------


CANONICALIZER_CASES = [
    # (case_id, input, expected_canonical, expected_underflowed)
    # ``..`` username on Linux — cleaned to /etc/ form.
    ("home_dotdot_etc_sudoers", "/home/../etc/sudoers", "/etc/sudoers", False),
    ("home_dotdot_root_ssh", "/home/../root/.ssh/id_rsa", "/root/.ssh/id_rsa", False),
    # ``..`` lifts off then re-enters home — second pass collapses to ~/.
    (
        "home_dotdot_home_realuser_ssh",
        "/home/../home/alice/.ssh/id_rsa",
        "~/.ssh/id_rsa",
        False,
    ),
    # ``/Users/../`` analogue.
    ("users_dotdot_etc_passwd", "/Users/../etc/passwd", "/etc/passwd", False),
    (
        "users_dotdot_users_realuser_aws",
        "/Users/../Users/realuser/.aws/credentials",
        "~/.aws/credentials",
        False,
    ),
    # Windows ``C:/Users/../Users/<u>/...``.
    (
        "c_drive_dotdot_users_admin_ssh",
        "C:/Users/../Users/admin/.ssh/id_rsa",
        "~/.ssh/id_rsa",
        False,
    ),
    # Existing cross-user underflow detection must still fire.
    (
        "cross_user_alice_to_bob_ssh",
        "/home/alice/../bob/.ssh/id_rsa",
        "~/bob/.ssh/id_rsa",
        True,
    ),
    # Legitimate within-home traversal must still collapse cleanly.
    (
        "within_home_traversal_alice_ssh",
        "/home/alice/Documents/../.ssh/id_rsa",
        "~/.ssh/id_rsa",
        False,
    ),
]


class TestCanonicalizerWithDotSegmentUsername:
    """Pins ``_canonicalize_write_edit_path_with_underflow`` behavior
    on the ``..`` / ``.`` username slot. Tests the canonicalizer
    directly so the regex defect is pinned independently of the hook.
    """

    @pytest.mark.parametrize(
        "input_path,expected_canonical,expected_underflowed",
        [(c[1], c[2], c[3]) for c in CANONICALIZER_CASES],
        ids=[c[0] for c in CANONICALIZER_CASES],
    )
    def test_canonicalizer(
        self,
        input_path: str,
        expected_canonical: str,
        expected_underflowed: bool,
    ) -> None:
        canon, underflowed = _mod._canonicalize_write_edit_path_with_underflow(input_path)
        assert canon == expected_canonical, (
            f"{input_path!r}: canonical mismatch. expected={expected_canonical!r}, got={canon!r}"
        )
        assert underflowed == expected_underflowed, (
            f"{input_path!r}: underflow mismatch. "
            f"expected={expected_underflowed}, got={underflowed}"
        )
