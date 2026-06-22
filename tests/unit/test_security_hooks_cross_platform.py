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
    async def test_macos_ssh_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"macOS SSH Write of {path!r} must deny — "
            "trust-triangle credential floor must cover /Users/<u>/.ssh/"
        )

    @pytest.mark.parametrize("path", MACOS_SSH_PATHS)
    @pytest.mark.asyncio
    async def test_macos_ssh_edit_denied(self, path: str) -> None:
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
    async def test_macos_aws_write_denied(self, path: str) -> None:
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
    async def test_macos_aws_edit_denied(self, path: str) -> None:
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
    async def test_macos_gnupg_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"macOS GnuPG Write of {path!r} must deny — "
            "trust-triangle credential floor must cover /Users/<u>/.gnupg/"
        )

    @pytest.mark.parametrize("path", MACOS_GNUPG_PATHS)
    @pytest.mark.asyncio
    async def test_macos_gnupg_edit_denied(self, path: str) -> None:
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
    async def test_macos_dotenv_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"macOS dotenv Write of {path!r} must deny — "
            "tail-segment ``.env`` match (and the new macOS prefix) must "
            "both keep this denied."
        )

    @pytest.mark.parametrize("path", MACOS_DOTENV_PATHS)
    @pytest.mark.asyncio
    async def test_macos_dotenv_edit_denied(self, path: str) -> None:
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
    async def test_windows_ssh_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Windows SSH Write of {path!r} must deny — "
            "trust-triangle credential floor must cover C:\\Users\\<u>\\.ssh\\"
        )

    @pytest.mark.parametrize("path", WINDOWS_SSH_PATHS)
    @pytest.mark.asyncio
    async def test_windows_ssh_edit_denied(self, path: str) -> None:
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
    async def test_windows_aws_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Windows AWS Write of {path!r} must deny — "
            "trust-triangle credential floor must cover C:\\Users\\<u>\\.aws\\"
        )

    @pytest.mark.parametrize("path", WINDOWS_AWS_PATHS)
    @pytest.mark.asyncio
    async def test_windows_aws_edit_denied(self, path: str) -> None:
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
    async def test_windows_ssh_authorized_keys_normalised(self, path: str) -> None:
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
    async def test_macos_cat_secret_denied_at_c4_layer(self, cmd: str) -> None:
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
    async def test_linux_write_still_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Linux regression — Write of {path!r} must STILL deny after "
            "the macOS/Windows extension lands. Pre-existing surface guard."
        )

    @pytest.mark.asyncio
    async def test_linux_cat_ssh_still_denied(self) -> None:
        result = await _run_bash("cat /home/alice/.ssh/id_rsa")
        assert _is_deny(result), (
            "Linux regression — ``cat /home/<u>/.ssh/id_rsa`` C4.1 must "
            "STILL deny after the alternation extension lands."
        )


# ---------------------------------------------------------------------------
# Test #10 — Backslash normalisation must not produce ``//`` artifacts
#
# The canonicalisation step must produce a clean forward-slash form on
# inputs that contain mixed-escape, UNC-style, or odd-length backslash
# runs. A naive two-pass ``replace("\\\\", "/").replace("\\", "/")``
# leaves ``//`` artifacts that bypass ``_HOME_PREFIX_RE`` (which expects a
# single leading ``/``) and silently slip past the credential floor.
#
# Variants exercised below:
#
#   1. Mixed-escape (a JSON-serialising agent doubles every backslash):
#      ``C:\\\\Users\\\\alice\\.ssh\\authorized_keys`` — must DENY.
#   2. Single-escape (raw Windows literal):
#      ``C:\\Users\\alice\\.ssh\\authorized_keys`` — must DENY.
#   3. Forward-slash variant (cross-platform tooling):
#      ``C:/Users/alice/.ssh/authorized_keys`` — must DENY.
#   4. Odd-length run (3 backslashes):
#      ``\\\\\\Users\\alice\\.ssh\\id_rsa`` — the canonicalised form must
#      not produce a ``//Users/...`` artifact that a future regex would
#      have to special-case around.
#   5. UNC path ``\\\\server\\share\\Users\\alice\\.ssh\\id_rsa``: no
#      deny rule currently covers UNC, so the assertion is only that the
#      canonicaliser does not produce a ``/Users/...`` substring that a
#      home-prefix matcher would mistake for an actual home path.
# ---------------------------------------------------------------------------


# Build Python strings whose runtime content matches each shape.
# ``r"..."`` keeps backslashes literal; the comment beside each entry
# shows what the canonicaliser sees on the wire.
H1_BACKSLASH_DENY_VARIANTS = [
    # 1. Mixed-escape — JSON-doubled backslashes (a JSON-serialising agent
    #    that double-encodes the separator emits ``\\\\`` for what was
    #    once ``\\``). On the wire that is four backslashes per separator.
    r"C:\\\\Users\\\\alice\.ssh\authorized_keys",
    # 2. Single-escape — raw Windows literal (one backslash per separator
    #    on the wire).
    r"C:\Users\alice\.ssh\authorized_keys",
    # 3. Forward-slash variant.
    "C:/Users/alice/.ssh/authorized_keys",
]


class TestBackslashNormalisationNoDoubleSlashArtifact:
    """Canonicalisation must not leave ``//`` artifacts that bypass the
    home-prefix matcher.
    """

    @pytest.mark.parametrize("path", H1_BACKSLASH_DENY_VARIANTS)
    @pytest.mark.asyncio
    async def test_mixed_and_single_escape_authorized_keys_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Windows variant {path!r} must DENY — canonicalisation must "
            "not leave a ``//`` artifact that bypasses _HOME_PREFIX_RE."
        )

    def test_mixed_escape_canonical_has_no_double_slash(self) -> None:
        # Mixed-escape input — JSON-doubled separators (4 wire backslashes
        # per segment break) plus single backslashes elsewhere. The
        # canonical form must collapse to ``~/.ssh/authorized_keys`` with a
        # single slash everywhere. A buggy two-pass replace would produce
        # ``C://Users//alice/.ssh/authorized_keys``.
        canonical = _mod._canonicalize_write_edit_path(r"C:\\\\Users\\\\alice\.ssh\authorized_keys")
        assert "//" not in canonical, (
            f"Canonical form {canonical!r} must not contain ``//`` "
            "artifacts from the backslash normalisation."
        )
        assert canonical == "~/.ssh/authorized_keys"

    def test_odd_length_backslash_run_has_no_double_slash(self) -> None:
        # Three leading backslashes (an attacker variant) must not collapse
        # to ``//Users/...`` after normalisation.
        canonical = _mod._canonicalize_write_edit_path(r"\\\Users\alice\.ssh\id_rsa")
        assert "//" not in canonical, (
            f"Canonical form {canonical!r} must not contain ``//`` "
            "artifacts from an odd-length backslash run."
        )

    def test_unc_path_does_not_misdetect_as_home(self) -> None:
        # UNC ``\\server\share\Users\alice\.ssh\id_rsa`` — a naive two-pass
        # normalise would yield ``/server/share/Users/alice/.ssh/id_rsa``.
        # No deny rule currently covers UNC, so the assertion is only that
        # the canonicaliser does not produce a leading-``//`` artifact AND
        # does not silently re-tag this path as a home path (``~/...``).
        canonical = _mod._canonicalize_write_edit_path(r"\\server\share\Users\alice\.ssh\id_rsa")
        assert "//" not in canonical, (
            f"Canonical UNC form {canonical!r} must not contain ``//`` artifacts."
        )
        assert not canonical.startswith("~/"), (
            f"Canonical UNC form {canonical!r} must not be misdetected as "
            "a home-prefix — the ``server`` segment is not a user home."
        )


# ---------------------------------------------------------------------------
# Test #11 — ``head`` / ``tail`` of a .env file must be denied
#
# The C4.4 rule for ``cat .env`` should broaden to ``cat|head|tail`` so an
# attacker cannot swap the reading verb to leak the same secret.
# ---------------------------------------------------------------------------


DOTENV_READ_VERB_BYPASS = [
    "head .env",
    "tail .env",
    "head .env.local",
    "tail .env.local",
    "head .env.production",
    "tail .env.production",
]


class TestDotenvReadVerbBroadening:
    @pytest.mark.parametrize("cmd", DOTENV_READ_VERB_BYPASS)
    @pytest.mark.asyncio
    async def test_dotenv_read_verb_denied(self, cmd: str) -> None:
        result = await _run_bash(cmd)
        assert _is_deny(result), (
            f"``{cmd}`` must DENY — C4.4 must broaden the reading verb "
            "from ``cat`` to ``cat|head|tail`` so swap-the-verb bypass "
            "is closed."
        )


# ---------------------------------------------------------------------------
# UNC + extended-length Windows path coverage (W8.H)
#
# The slash-collapse step in ``_canonicalize_write_edit_path`` destroys the
# leading ``//`` marker that distinguishes UNC and extended-length forms
# from regular paths. The matcher must detect these shapes BEFORE the
# collapse fires and re-run on the underlying tail so the credential
# floor still triggers.
# ---------------------------------------------------------------------------


UNC_DENY_PATHS = [
    # Plain UNC -> ~/.ssh/id_rsa shape.
    r"\\server\share\Users\alice\.ssh\id_rsa",
    r"\\server\share\Users\alice\.ssh\authorized_keys",
    r"\\fileserver\home\Users\bob\.ssh\id_ed25519",
    # UNC pointing at AWS credentials.
    r"\\server\share\Users\alice\.aws\credentials",
    # UNC pointing at npmrc / pypirc.
    r"\\server\share\Users\alice\.npmrc",
    r"\\server\share\Users\alice\.pypirc",
]


EXTLEN_DENY_PATHS = [
    # Extended-length drive form.
    r"\\?\C:\Users\alice\.ssh\id_rsa",
    r"\\?\C:\Users\alice\.ssh\authorized_keys",
    r"\\?\D:\Users\bob\.aws\credentials",
    r"\\?\C:\Users\alice\.npmrc",
    # Extended-length UNC form.
    r"\\?\UNC\server\share\Users\alice\.ssh\id_rsa",
    r"\\?\UNC\fileserver\home\Users\bob\.aws\credentials",
]


class TestWindowsUNCDeny:
    r"""UNC ``\\server\share\<credential>`` must DENY."""

    @pytest.mark.parametrize("path", UNC_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_unc_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"UNC Write of {path!r} must deny — UNC path strips to the "
            "tail which is a credential path."
        )

    @pytest.mark.parametrize("path", UNC_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_unc_edit_denied(self, path: str) -> None:
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"UNC Edit of {path!r} must deny — UNC path strips to the "
            "tail which is a credential path."
        )


class TestWindowsExtendedLengthDeny:
    r"""Extended-length ``\\?\C:\...`` and ``\\?\UNC\...`` must DENY."""

    @pytest.mark.parametrize("path", EXTLEN_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_extlen_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Extended-length Write of {path!r} must deny — the "
            r"``\\?\`` prefix must not bypass the deny floor."
        )

    @pytest.mark.parametrize("path", EXTLEN_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_extlen_edit_denied(self, path: str) -> None:
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"Extended-length Edit of {path!r} must deny — the "
            r"``\\?\`` prefix must not bypass the deny floor."
        )


# ---------------------------------------------------------------------------
# Modern credential paths (W8.I)
#
# The deny list expanded to cover GitHub CLI, npm, PyPI, cargo, Azure CLI,
# gcloud, and the global git config. Each new prefix gets a plain hit,
# a traversal hit (``..`` escape that lands on the same canonical), and
# a case-fold hit (the case-fold layer kicks in on macOS / Windows; the
# case-fold tests are in TestCaseInsensitiveDeny below). The hits below
# exercise the plain + traversal axes on Linux.
# ---------------------------------------------------------------------------


MODERN_CREDENTIAL_DENY_PATHS = [
    # GitHub CLI hosts.yml.
    "~/.config/gh/hosts.yml",
    "/home/alice/.config/gh/hosts.yml",
    # Traversal that lands back on the same target.
    "/home/alice/x/../.config/gh/hosts.yml",
    # npmrc.
    "~/.npmrc",
    "/home/alice/.npmrc",
    "/home/alice/projects/../.npmrc",
    # pypirc.
    "~/.pypirc",
    "/home/alice/.pypirc",
    "/home/alice/Documents/../.pypirc",
    # Cargo credentials (plain + toml variants).
    "~/.cargo/credentials",
    "~/.cargo/credentials.toml",
    "/home/alice/.cargo/credentials",
    "/home/alice/.cargo/credentials.toml",
    "/home/alice/projects/../.cargo/credentials",
    # Azure CLI - any file under the directory.
    "~/.azure/accessTokens.json",
    "~/.azure/azureProfile.json",
    "/home/alice/.azure/accessTokens.json",
    "/home/alice/projects/../.azure/azureProfile.json",
    # gcloud - both ~/.config/gcloud/ and ~/.gcloud/ variants.
    "~/.config/gcloud/application_default_credentials.json",
    "~/.config/gcloud/credentials.db",
    "~/.gcloud/credentials",
    "/home/alice/.config/gcloud/application_default_credentials.json",
    "/home/alice/.gcloud/credentials",
    "/home/alice/x/../.config/gcloud/application_default_credentials.json",
    # Global git config.
    "~/.gitconfig",
    "/home/alice/.gitconfig",
    "/home/alice/projects/../.gitconfig",
]


class TestModernCredentialDeny:
    """New credential prefixes for GitHub CLI / npm / pypi / cargo / azure /
    gcloud / global git config.
    """

    @pytest.mark.parametrize("path", MODERN_CREDENTIAL_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_modern_credential_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Write of {path!r} must deny — modern credential prefix must be in the deny floor."
        )

    @pytest.mark.parametrize("path", MODERN_CREDENTIAL_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_modern_credential_edit_denied(self, path: str) -> None:
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"Edit of {path!r} must deny — modern credential prefix must be in the deny floor."
        )


# ---------------------------------------------------------------------------
# Shell-rc persistence vectors (W8.J)
#
# Writes / appends / edits to shell-rc files establish session-survival
# code. The hook payload only sees the target ``file_path``, so a write
# via ``>`` and an append via ``>>`` are indistinguishable at this layer —
# both are denied by virtue of the prefix match. The Edit-tool form is
# also covered.
# ---------------------------------------------------------------------------


SHELL_RC_DENY_PATHS = [
    # Bash family.
    "~/.bashrc",
    "~/.bash_profile",
    "~/.bash_logout",
    "~/.bash_aliases",
    "~/.profile",
    "/home/alice/.bashrc",
    "/home/alice/.bash_profile",
    "/home/alice/.bash_logout",
    "/home/alice/.bash_aliases",
    "/home/alice/.profile",
    # Zsh family.
    "~/.zshrc",
    "~/.zprofile",
    "~/.zshenv",
    "~/.zlogin",
    "~/.zlogout",
    "/home/alice/.zshrc",
    "/home/alice/.zprofile",
    "/home/alice/.zshenv",
    "/home/alice/.zlogin",
    "/home/alice/.zlogout",
    # Fish config.
    "~/.config/fish/config.fish",
    "/home/alice/.config/fish/config.fish",
    # Traversal variants - kernel resolves to the same target.
    "/home/alice/projects/../.bashrc",
    "/home/alice/x/y/../../.zshrc",
    "/home/alice/Documents/../.config/fish/config.fish",
    # Windows PowerShell profiles - prefix match on the Documents dir.
    "~/Documents/PowerShell/profile.ps1",
    "~/Documents/PowerShell/Microsoft.PowerShell_profile.ps1",
    "~/Documents/WindowsPowerShell/profile.ps1",
    "~/Documents/WindowsPowerShell/Microsoft.PowerShell_profile.ps1",
    "/home/alice/Documents/PowerShell/profile.ps1",
]


class TestShellRcDeny:
    """Writes / edits to shell-rc files (persistence vector) must DENY."""

    @pytest.mark.parametrize("path", SHELL_RC_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_shell_rc_write_denied(self, path: str) -> None:
        # Write tool covers both ``>`` overwrite and ``>>`` append semantics
        # at the hook layer — the payload is the target path; the hook
        # doesn't distinguish open-mode.
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Write to shell-rc target {path!r} must deny — "
            "persistence vector. Append (``>>``) and overwrite (``>``) "
            "both surface as Write at this layer."
        )

    @pytest.mark.parametrize("path", SHELL_RC_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_shell_rc_edit_denied(self, path: str) -> None:
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), f"Edit of shell-rc target {path!r} must deny — persistence vector."


# ---------------------------------------------------------------------------
# Case-insensitive filesystems (W8.M)
#
# macOS HFS+ / APFS and Windows NTFS resolve ``~/.SSH/id_rsa`` and
# ``~/.ssh/id_rsa`` to the same inode. The matcher must case-fold both
# sides on those platforms. POSIX Linux is case-sensitive (correct
# semantics preserved).
#
# Mocks ``sys.platform`` so the test runs deterministically regardless of
# host OS.
# ---------------------------------------------------------------------------


CASE_FOLD_DENY_PATHS = [
    # SSH variants.
    "~/.SSH/id_rsa",
    "~/.Ssh/authorized_keys",
    "/Users/alice/.SSH/id_rsa",
    "/Users/Alice/.SSH/AUTHORIZED_KEYS",
    # AWS variants.
    "~/.AWS/credentials",
    "/Users/alice/.AWS/Credentials",
    # GnuPG variants.
    "~/.GNUPG/secring.gpg",
    "/Users/alice/.Gnupg/private-keys-v1.d/x.key",
    # Docker variants.
    "~/.DOCKER/config.json",
    # netrc.
    "~/.NETRC",
    # Modern credentials.
    "~/.NPMRC",
    "~/.PYPIRC",
    "~/.GITCONFIG",
    "~/.AZURE/accessTokens.json",
    "~/.CARGO/credentials",
    "~/.CONFIG/gh/hosts.yml",
    "~/.CONFIG/gcloud/application_default_credentials.json",
    # Shell-rc.
    "~/.BASHRC",
    "~/.ZSHRC",
    # dotenv tail-match.
    "/Users/alice/project/.ENV",
    "/Users/alice/project/.Env.Local",
]


class TestCaseInsensitiveDenyMacOS:
    """On macOS the matcher MUST case-fold both sides."""

    @pytest.mark.parametrize("path", CASE_FOLD_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_case_fold_write_denied_macos(
        self, path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys as _sys

        monkeypatch.setattr(_sys, "platform", "darwin")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"macOS Write of case-variant {path!r} must deny — "
            "HFS+/APFS resolve case-insensitively."
        )

    @pytest.mark.parametrize("path", CASE_FOLD_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_case_fold_edit_denied_macos(
        self, path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys as _sys

        monkeypatch.setattr(_sys, "platform", "darwin")
        result = await _run_write_edit("Edit", path)
        assert _is_deny(result), (
            f"macOS Edit of case-variant {path!r} must deny — HFS+/APFS resolve case-insensitively."
        )


WINDOWS_CASE_FOLD_DENY_PATHS = [
    r"C:\Users\Alice\.SSH\id_rsa",
    r"C:\Users\Alice\.SSH\AUTHORIZED_KEYS",
    r"C:\Users\Alice\.AWS\Credentials",
    r"C:\Users\Alice\.NPMRC",
    r"C:\Users\Alice\.PYPIRC",
    r"C:\Users\Alice\.GITCONFIG",
    r"C:\Users\Alice\Documents\PowerShell\PROFILE.PS1",
    r"C:\Users\Alice\Documents\WindowsPowerShell\PROFILE.PS1",
]


class TestCaseInsensitiveDenyWindows:
    """On Windows the matcher MUST case-fold both sides (NTFS default)."""

    @pytest.mark.parametrize("path", WINDOWS_CASE_FOLD_DENY_PATHS)
    @pytest.mark.asyncio
    async def test_case_fold_write_denied_windows(
        self, path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys as _sys

        monkeypatch.setattr(_sys, "platform", "win32")
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Windows Write of case-variant {path!r} must deny — "
            "NTFS resolves case-insensitively by default."
        )


class TestCaseInsensitiveAllowedOnLinux:
    """POSIX Linux MUST stay case-sensitive — ``~/.SSH/id_rsa`` is a
    DIFFERENT file from ``~/.ssh/id_rsa`` on a case-sensitive filesystem,
    and the matcher MUST NOT false-positive deny it.
    """

    LINUX_NOT_DENIED = [
        # Different case from the deny prefix — on Linux these are
        # separate files. ``.SSH`` directory is legitimate user content.
        "~/.SSH/id_rsa",
        "~/.AWS/credentials",
        "~/.NPMRC",
        "~/.PYPIRC",
        "~/.GITCONFIG",
        "/home/alice/.BASHRC",
        "/home/alice/.ZSHRC",
        # Mixed-case prefix in the middle.
        "~/.Cargo/credentials",
    ]

    @pytest.mark.parametrize("path", LINUX_NOT_DENIED)
    @pytest.mark.asyncio
    async def test_case_variant_allowed_on_linux(
        self, path: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import sys as _sys

        # Force POSIX Linux semantics even if the host happens to be
        # macOS/Windows running the suite. The contract: case-sensitive
        # filesystems require an EXACT match.
        monkeypatch.setattr(_sys, "platform", "linux")
        result = await _run_write_edit("Write", path)
        assert not _is_deny(result), (
            f"Linux Write of case-variant {path!r} must NOT deny — "
            "POSIX Linux is case-sensitive; a different-case filename "
            "is a different file."
        )


# ---------------------------------------------------------------------------
# Linux regression smoke for the new defenses
#
# Every new deny prefix (modern credentials, shell-rc) must STILL fire on
# Linux at the canonical lowercase form. Mirrors the pattern of
# ``TestLinuxRegressionSmoke`` above.
# ---------------------------------------------------------------------------


LINUX_NEW_DEFENSE_DENY_SMOKE = [
    "/home/alice/.config/gh/hosts.yml",
    "/home/alice/.npmrc",
    "/home/alice/.pypirc",
    "/home/alice/.cargo/credentials",
    "/home/alice/.cargo/credentials.toml",
    "/home/alice/.azure/accessTokens.json",
    "/home/alice/.config/gcloud/application_default_credentials.json",
    "/home/alice/.gcloud/credentials",
    "/home/alice/.gitconfig",
    "/home/alice/.bashrc",
    "/home/alice/.zshrc",
    "/home/alice/.profile",
    "/home/alice/.config/fish/config.fish",
]


class TestNewDefenseLinuxSmoke:
    @pytest.mark.parametrize("path", LINUX_NEW_DEFENSE_DENY_SMOKE)
    @pytest.mark.asyncio
    async def test_new_defense_linux_write_denied(self, path: str) -> None:
        result = await _run_write_edit("Write", path)
        assert _is_deny(result), (
            f"Linux Write of {path!r} must deny — new deny prefix "
            "must fire on canonical Linux paths."
        )
