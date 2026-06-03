# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract tests — BON-1032.

Dispatch layer Write/Edit SENSITIVE-PATH coverage + canonicalizer hardening.

Two contracts, both asserted at the *hook* boundary (``build_preexec_hook``)
so the test is robust to where the fix lands (new DenyRule entries in
``security_patterns.py``, a dedicated file_path canonicalizer in
``security_hooks.py``, or both):

H1 — COVERAGE. A ``Write``/``Edit`` whose ``file_path`` points at one of the
     credential / system-state files named in BON-1032 must be DENIED:
       * ~/.npmrc                          (Node package manager rc)
       * ~/.pypirc                         (Python package index rc)
       * gcloud application_default_credentials.json
       * gcloud legacy_credentials/.../adc.json
       * ~/.git-credentials                (git credential helper store)
       * ~/.config/gh/hosts.yml            (GitHub CLI host/token file)
       * ~/.bash_history, ~/.zsh_history   (shell history)
     macOS home prefix (``/Users/<u>/``) is mandatory; the Linux home prefix
     (``/home/<u>/``) and the literal ``~``/``$HOME`` forms must all match.
     Windows analogues are explicitly DEFERRED — NO Windows cases here.

H2 — CANONICALIZER. The Write/Edit file_path must be canonicalized before the
     deny rules run so the following evasions are caught:
       * repeated separators   ``/home/u//.npmrc``
       * relative traversal    ``/home/u/foo/../.npmrc``
       * trailing separator    ``/home/u/.config/gh/hosts.yml/``  (n/a for files;
                               we assert the dir-trailing form on the gcloud dir)
     AND segment-boundary anchoring must PREVENT a prefix-match false positive:
       * ``/home/u/xnpmrc``    (shares the ``npmrc`` suffix but NOT at a path
                               segment boundary) must be ALLOWED, not denied.
       * ``/home/u/notes.txt`` (fully benign) must be ALLOWED.

Every assertion below FAILS on origin/main: the Write/Edit file_path is fed
through the Bash command-regex set, none of which has a rule for these paths
(and the closest existing rules, e.g. C4.2 ``\\bcat\\s+...\\.aws/credentials``,
are ``cat``-anchored so they never fire on a bare path). There is no file_path
canonicalizer at all. So today every credential path below returns ``allow``.
"""

from __future__ import annotations

from typing import Any

import pytest

from bonfire.dispatch.security_hooks import SecurityHooksConfig, build_preexec_hook


def _is_deny(result: dict[str, Any]) -> bool:
    try:
        return (
            result["hookSpecificOutput"]["hookEventName"] == "PreToolUse"
            and result["hookSpecificOutput"]["permissionDecision"] == "deny"
        )
    except (KeyError, TypeError):
        return False


async def _run(tool_name: str, file_path: str) -> dict[str, Any]:
    """Drive the real pre-exec hook for a Write/Edit on ``file_path``."""
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


# ---------------------------------------------------------------------------
# H1 — coverage: credential / system-state file paths must DENY on Write & Edit
# ---------------------------------------------------------------------------

# (label, file_path) — Linux home prefix unless noted.
_DENY_PATHS: tuple[tuple[str, str], ...] = (
    ("npmrc", "/home/user/.npmrc"),
    ("pypirc", "/home/user/.pypirc"),
    (
        "gcloud-adc",
        "/home/user/.config/gcloud/application_default_credentials.json",
    ),
    (
        "gcloud-legacy",
        "/home/user/.config/gcloud/legacy_credentials/user@example.com/adc.json",
    ),
    ("git-credentials", "/home/user/.git-credentials"),
    ("gh-hosts", "/home/user/.config/gh/hosts.yml"),
    ("bash-history", "/home/user/.bash_history"),
    ("zsh-history", "/home/user/.zsh_history"),
)


@pytest.mark.parametrize("label,path", _DENY_PATHS, ids=[p[0] for p in _DENY_PATHS])
@pytest.mark.parametrize("tool", ["Write", "Edit"])
@pytest.mark.asyncio
async def test_credential_path_denied(tool: str, label: str, path: str):
    result = await _run(tool, path)
    assert _is_deny(result), f"{tool} to {path} ({label}) must be DENIED"


# macOS home prefix is mandatory per BON-1032 acceptance criterion 1.
@pytest.mark.parametrize(
    "path",
    [
        "/Users/anta/.npmrc",
        "/Users/anta/.pypirc",
        "/Users/anta/.git-credentials",
        "/Users/anta/.config/gh/hosts.yml",
        "/Users/anta/.config/gcloud/application_default_credentials.json",
        "/Users/anta/.bash_history",
        "/Users/anta/.zsh_history",
    ],
)
@pytest.mark.asyncio
async def test_macos_home_credential_path_denied(path: str):
    assert _is_deny(await _run("Write", path)), f"macOS {path} must be DENIED"


# ``~`` and ``$HOME`` forms must also match (these are the literal strings an
# agent emits when it has not expanded the home dir).
@pytest.mark.parametrize(
    "path",
    [
        "~/.npmrc",
        "~/.pypirc",
        "~/.git-credentials",
        "~/.config/gh/hosts.yml",
        "~/.bash_history",
        "$HOME/.npmrc",
        "$HOME/.zsh_history",
    ],
)
@pytest.mark.asyncio
async def test_tilde_and_home_var_credential_path_denied(path: str):
    assert _is_deny(await _run("Edit", path)), f"{path} must be DENIED"


# ---------------------------------------------------------------------------
# H2 — canonicalizer hardening (evasions must still DENY)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "label,path",
    [
        ("double-slash", "/home/user//.npmrc"),
        ("triple-slash", "/home/user///.git-credentials"),
        ("dotdot-traversal", "/home/user/foo/../.npmrc"),
        ("deep-traversal", "/home/user/a/b/../../.pypirc"),
        ("dot-segment", "/home/user/./.git-credentials"),
        (
            "mixed-traversal-gh",
            "/home/user/.config/gh/../gh/hosts.yml",
        ),
        (
            "double-slash-gcloud",
            "/home/user/.config//gcloud/application_default_credentials.json",
        ),
    ],
)
@pytest.mark.asyncio
async def test_canonicalizer_catches_evasion(label: str, path: str):
    assert _is_deny(await _run("Write", path)), (
        f"canonicalizer must normalize {path} ({label}) and DENY"
    )


# ---------------------------------------------------------------------------
# H2 — segment-boundary anchoring: prefix-match false positives must NOT deny
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/home/user/xnpmrc",  # ends in 'npmrc' but not at a / boundary
        "/home/user/mypypirc",  # ends in 'pypirc' but not at a / boundary
        "/home/user/not-git-credentials-real",
        "/home/user/notes.txt",  # fully benign
        "/home/user/src/history.py",  # contains 'history' but is source
        "/home/user/npmrc.md",  # docs about npmrc, not the rc file
    ],
)
@pytest.mark.asyncio
async def test_benign_lookalike_path_allowed(path: str):
    """Anchoring at path-segment boundaries prevents the prefix over-reach.

    These must NOT be denied. A naive substring/prefix rule would wrongly
    fire on the shared suffix; the segment-anchored rule must let them pass.
    """
    result = await _run("Write", path)
    assert not _is_deny(result), f"{path} is benign and must NOT be denied"
