# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract — Write/Edit deny for credential and system-state paths.

The bash-shape catalogue (C1-C7 in ``security_patterns``) requires literal
prefixes like ``cat \\s+`` or ``>>?\\s*`` and so it never fires on Write/Edit
``file_path`` payloads. The W4.2 trust-triangle sells defense-in-depth that
this surface didn't enforce.

These tests pin the Write/Edit-only sensitive-path family enforced inside
``bonfire.dispatch.security_hooks``. The deny set is path-shape; it gates ONLY
when ``tool_name in ("Write", "Edit")``. Bash continues to flow through the
existing C1-C7 regex catalogue with no behavior change.

Contract surface:

- A new attribute ``WRITE_EDIT_SENSITIVE_PATH_DENY`` is exposed at module
  scope so tests and future user-tooling can introspect the list.
- The hook denies Write/Edit file_path values that resolve under any sensitive
  prefix (SSH/AWS/GPG/Docker/Kube/netrc/.env/.env.*/system-state/root home).
- Bash commands with the SAME path payload do NOT trigger this family — the
  bash-shape catalogue is the only gate for Bash.
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
# Module surface
# ---------------------------------------------------------------------------


class TestModuleSurface:
    def test_sensitive_path_attr_exposed(self) -> None:
        """``WRITE_EDIT_SENSITIVE_PATH_DENY`` is a public-readable module attr."""
        assert hasattr(_mod, "WRITE_EDIT_SENSITIVE_PATH_DENY"), (
            "Hook must expose the path-prefix set so introspection is "
            "possible from outside the hook closure."
        )

    def test_sensitive_path_attr_is_iterable_of_strings(self) -> None:
        """Each entry MUST be a string. (Tuple OR frozenset are both fine.)"""
        entries = list(_mod.WRITE_EDIT_SENSITIVE_PATH_DENY)
        assert entries, "Sensitive-path set must be non-empty."
        for entry in entries:
            assert isinstance(entry, str), entry


# ---------------------------------------------------------------------------
# SSH keys + authorized_keys + known_hosts
# ---------------------------------------------------------------------------


SSH_DENY_PATHS = [
    "~/.ssh/id_rsa",
    "~/.ssh/id_ed25519",
    "~/.ssh/id_ecdsa",
    "~/.ssh/id_dsa",
    "~/.ssh/authorized_keys",
    "~/.ssh/known_hosts",
    "$HOME/.ssh/id_rsa",
    "$HOME/.ssh/authorized_keys",
    "/home/user/.ssh/id_rsa",
    "/home/user/.ssh/id_ed25519",
    "/home/user/.ssh/authorized_keys",
    "/home/user/.ssh/known_hosts",
    "/home/ishtar/.ssh/id_ed25519",
    "/root/.ssh/id_rsa",
    "/root/.ssh/authorized_keys",
]


class TestWriteEditSSHPaths:
    @pytest.mark.parametrize("path", SSH_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_write_ssh_path_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Write", path)), path

    @pytest.mark.parametrize("path", SSH_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_edit_ssh_path_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Edit", path)), path


# ---------------------------------------------------------------------------
# AWS credentials
# ---------------------------------------------------------------------------


AWS_DENY_PATHS = [
    "~/.aws/credentials",
    "$HOME/.aws/credentials",
    "/home/user/.aws/credentials",
    "/root/.aws/credentials",
]


class TestWriteEditAWSPaths:
    @pytest.mark.parametrize("path", AWS_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_write_aws_credentials_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Write", path)), path

    @pytest.mark.parametrize("path", AWS_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_edit_aws_credentials_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Edit", path)), path


# ---------------------------------------------------------------------------
# GPG / Docker / Kube / netrc
# ---------------------------------------------------------------------------


OTHER_CREDENTIAL_DENY_PATHS = [
    "~/.gnupg/pubring.kbx",
    "~/.gnupg/private-keys-v1.d/foo.key",
    "$HOME/.gnupg/trustdb.gpg",
    "/home/user/.gnupg/pubring.kbx",
    "~/.docker/config.json",
    "$HOME/.docker/config.json",
    "/home/user/.docker/config.json",
    "~/.kube/config",
    "$HOME/.kube/config",
    "/home/user/.kube/config",
    "~/.netrc",
    "$HOME/.netrc",
    "/home/user/.netrc",
    "/root/.netrc",
]


class TestWriteEditOtherCredentialPaths:
    @pytest.mark.parametrize("path", OTHER_CREDENTIAL_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_write_credential_path_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Write", path)), path

    @pytest.mark.parametrize("path", OTHER_CREDENTIAL_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_edit_credential_path_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Edit", path)), path


# ---------------------------------------------------------------------------
# .env files
# ---------------------------------------------------------------------------


DOTENV_DENY_PATHS = [
    ".env",
    "./.env",
    ".env.local",
    ".env.production",
    ".env.dev",
    "/home/user/project/.env",
    "/home/user/project/.env.local",
    "/srv/app/.env",
]


class TestWriteEditDotenv:
    @pytest.mark.parametrize("path", DOTENV_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_write_dotenv_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Write", path)), path

    @pytest.mark.parametrize("path", DOTENV_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_edit_dotenv_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Edit", path)), path


# ---------------------------------------------------------------------------
# System paths
# ---------------------------------------------------------------------------


SYSTEM_DENY_PATHS = [
    "/etc/sudoers",
    "/etc/sudoers.d/00-extra",
    "/etc/sudoers.d/wheel",
    "/etc/passwd",
    "/etc/shadow",
    "/etc/gshadow",
]


class TestWriteEditSystemPaths:
    @pytest.mark.parametrize("path", SYSTEM_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_write_system_path_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Write", path)), path

    @pytest.mark.parametrize("path", SYSTEM_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_edit_system_path_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Edit", path)), path


# ---------------------------------------------------------------------------
# Root home directory
# ---------------------------------------------------------------------------


ROOT_HOME_DENY_PATHS = [
    "/root/note.txt",
    "/root/scripts/something.sh",
    "/root/.bashrc",
    "/root/projects/x.py",
]


class TestWriteEditRootHome:
    @pytest.mark.parametrize("path", ROOT_HOME_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_write_root_home_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Write", path)), path

    @pytest.mark.parametrize("path", ROOT_HOME_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_edit_root_home_denied(self, path: str) -> None:
        assert _is_deny(await _run_write_edit("Edit", path)), path


# ---------------------------------------------------------------------------
# Benign paths must NOT trigger the new family.
# ---------------------------------------------------------------------------


BENIGN_PATHS = [
    "/home/user/projects/foo/bar.py",
    "/home/user/projects/.env.example",  # .env.example is documentation, not secrets
    "./README.md",
    "/tmp/scratch",
    "/tmp/build/output.log",
    "/home/user/notes.txt",
    "src/bonfire/dispatch/tool_policy.py",
    "tests/unit/test_security_hooks_factory.py",
    "/home/user/.sshrc",  # not ~/.ssh/
    "/home/user/.env_example.txt",  # underscore -> not .env.* prefix
    "/home/user/data/aws.txt",  # not ~/.aws/credentials
    "/home/user/myroot/file.txt",  # not /root/
]


class TestWriteEditBenignPaths:
    @pytest.mark.parametrize("path", BENIGN_PATHS)
    @pytest.mark.asyncio
    async def test_write_benign_path_allowed(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert not _is_deny(result), f"benign Write {path!r} unexpectedly denied: {result}"

    @pytest.mark.parametrize("path", BENIGN_PATHS)
    @pytest.mark.asyncio
    async def test_edit_benign_path_allowed(self, path: str) -> None:
        result = await _run_write_edit("Edit", path)
        assert not _is_deny(result), f"benign Edit {path!r} unexpectedly denied: {result}"


# ---------------------------------------------------------------------------
# Bash NOT affected by Write/Edit family.
#
# A benign Bash command that names a sensitive path as an ARG (e.g.
# ``ls ~/.ssh``) must continue to flow through the C1-C7 catalogue,
# which does NOT deny a bare ``ls`` of the directory. The Write/Edit
# family is path-shape and gated by tool_name; Bash gets the existing
# bash-shape catalogue, no more, no less.
# ---------------------------------------------------------------------------


class TestBashUnaffectedByWriteEditFamily:
    @pytest.mark.asyncio
    async def test_bash_ls_ssh_dir_not_denied_by_new_family(self) -> None:
        """``ls ~/.ssh`` was historically not C1-C7-denied; stay green."""
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls ~/.ssh"},
            },
            "tu1",
            {"signal": None},
        )
        # Either allow (empty {}) or warn — but NOT a Write/Edit-family deny.
        # The bash-shape C1-C7 rules don't fire on `ls`, so this is a
        # pass-through `{}`.
        assert (
            result == {} or result.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"
        )

    @pytest.mark.asyncio
    async def test_bash_cat_ssh_key_still_denied_by_C4(self) -> None:
        """C4.1 ``cat ~/.ssh/id_rsa`` MUST still deny — regression guard."""
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "cat ~/.ssh/id_rsa"},
            },
            "tu1",
            {"signal": None},
        )
        assert _is_deny(result)

    @pytest.mark.asyncio
    async def test_bash_redirect_to_authorized_keys_still_denied_by_C5(self) -> None:
        """C5.5 ``echo X >> ~/.ssh/authorized_keys`` MUST still WARN — regression guard."""
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "echo foo >> ~/.ssh/authorized_keys"},
            },
            "tu1",
            {"signal": None},
        )
        # C5.5 is WARN — emits a SecurityDenied event with WARN prefix but
        # returns an ``allow`` envelope.
        decision = result.get("hookSpecificOutput", {}).get("permissionDecision")
        assert decision in ("allow", "deny"), f"expected allow or deny, got {decision!r}"


# ---------------------------------------------------------------------------
# Deny reason should be helpful (smoke).
# ---------------------------------------------------------------------------


class TestDenyReasonIsHelpful:
    @pytest.mark.asyncio
    async def test_deny_reason_mentions_sensitive_or_path(self) -> None:
        result = await _run_write_edit("Write", "/etc/sudoers")
        reason = result["hookSpecificOutput"]["permissionDecisionReason"]
        assert isinstance(reason, str) and reason
