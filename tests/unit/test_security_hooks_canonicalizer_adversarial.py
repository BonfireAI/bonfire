# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract — Write/Edit deny-floor canonicalizer rejects adversarial
path-traversal inputs.

Pins Probe N+4 Scout 1 finding C1: ``_canonicalize_write_edit_path`` in
``bonfire/dispatch/security_hooks.py`` (lines 202-267) silently lets
adversarial path shapes bypass the credential deny floor. The two prior
positive-shape test files
(``test_security_hooks_write_edit_sensitive_paths.py`` and
``test_security_hooks_cross_platform.py``) cover clean shapes only; they
do not assert on ``..`` traversal, ``//`` runs, or mid-path ``./`` —
that is why W7.L (PR #94) shipped this regression.

The bug shape:

- The slash-collapse step (``re.sub(r"/{2,}", "/", s)``) is gated behind
  ``if "\\" in s:``. A pure-POSIX input like ``/home/alice//.ssh/id_rsa``
  never enters the collapse branch.
- The canonicalizer does NOT resolve ``..`` or ``.`` segments. Inputs
  like ``/home/alice/Documents/../.ssh/id_rsa`` reach the deny matcher
  in literal form and miss every deny prefix.

Each input listed below currently canonicalizes to a form that does NOT
start with any entry in ``WRITE_EDIT_SENSITIVE_PATH_DENY``. The hook
returns ``{}``, the kernel opens the credential target at write time,
and the deny floor is silently absent.

These tests deliberately do NOT include the implementation. The W8.A
Warrior will GREEN them by extending ``_canonicalize_write_edit_path``
to normalize redundant separators on POSIX inputs and to collapse ``..``
/ ``.`` path segments before the prefix scan.

Adversarial matrix (per the operating lesson ratified 2026-05-15:
defense-in-depth requires adversarial test cases, not just positive
shapes):

- Traversal: ``<home>/Documents/../<rel>``, ``<home>/x/y/../../<rel>``
- Single-dot: ``<home>/./<rel>``
- Double-separator: ``<home>//<rel>``, ``<home>///<rel>``
- Trailing combos: ``<home>/<dir>/./<file>``, ``<home>/<dir>//<file>``
- xfail (out of W8.A scope, see notes below):
    - Mixed-case: ``<home>/.SSH/<file>`` (W8.M)
    - URL-encoded: ``<home>/%2e%2e/<rel>`` (deferred)

Scope guards:

- Mixed-case (``.SSH/``) is xfailed because Linux is case-sensitive at
  the FS layer; structural case-folding inside the matcher is W8.M and
  must not block this PR.
- URL-encoded (``%2e%2e``) is xfailed because the canonicalizer is not
  required to decode percent-escapes in v0.1; the test pins the open
  question.
- macOS ``/Users/<u>/...`` and Windows ``C:\\Users\\<u>\\...`` prefix
  variants of the same adversarial shapes are NOT covered here —
  ``test_security_hooks_cross_platform.py`` owns the cross-platform
  surface; this file is scoped to the Linux home-credential floor.
- UNC + extended-length Windows path shapes are W8.H (Wave 8.2).

Audit pointer:
``/home/ishtar/Projects/ishtar/grimoire/audits/2026-05-15-bonfire-v0.1-probe-n4-scout-1-security.md``
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


# ---------------------------------------------------------------------------
# Harness — mirrors the two prior positive-shape files so the contract
# vocabulary is identical (build hook, call PreToolUse, check
# permissionDecision).
# ---------------------------------------------------------------------------


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
# Sensitive targets — each tuple is
#   (target_id, home_relative_dir, file_name, has_subfile_under_dotdir)
#
# ``has_subfile_under_dotdir`` flags whether the deny prefix matches the
# directory (True → trailing-mid-dot/double-slash inside the dotdir bypass)
# or the file itself (False → trailing-mid-dot variants for THIS target
# pass through the deny prefix on their own and would not RED).
#
# Targets are deliberately scoped to home-credential paths that reach the
# ``_HOME_PREFIX_RE`` canonicalization step. ``/etc/...`` paths are
# adversarially-bypassable too (probed independently) but are system-state,
# not home-credential — out of W8.A scope.
# ---------------------------------------------------------------------------


SENSITIVE_TARGETS = [
    # id, dotdir (or ""), filename, has_subfile_under_dotdir
    ("ssh_id_rsa", ".ssh", "id_rsa", True),
    ("ssh_authorized_keys", ".ssh", "authorized_keys", True),
    ("aws_credentials", ".aws", "credentials", True),
    ("kube_config", ".kube", "config", True),
    ("docker_config", ".docker", "config.json", True),
    # ``.netrc`` sits directly under $HOME — there is no enclosing dotdir,
    # so trailing-combo variants do not apply (they're filtered below).
    ("netrc", "", ".netrc", False),
    # ``.gnupg/`` is matched as a directory prefix — the trailing-mid-dot
    # variant ``~/.gnupg/./foo`` already STARTS WITH ``~/.gnupg/``, so the
    # current matcher catches it. The leading-traversal/single-dot/
    # double-separator variants still bypass (the FRONT of the path is
    # reshaped, not the trailing segment). Flag has_subfile_under_dotdir
    # False to skip trailing-combo variants for this target.
    ("gnupg_secring", ".gnupg", "secring.gpg", False),
]


# Home prefixes the canonicalizer recognizes on Linux. ``/Users/`` (macOS)
# is out of scope for this file — see test_security_hooks_cross_platform.py.
HOME_PREFIXES = [
    "/home/alice",
    "$HOME",
]


def _build_target_path(prefix: str, dotdir: str, filename: str) -> str:
    """Compose a clean (non-adversarial) path for a sensitive target.

    Used only inside variant builders below — never asserted directly;
    each variant transforms this baseline into an adversarial shape.
    """
    if dotdir:
        return f"{prefix}/{dotdir}/{filename}"
    return f"{prefix}/{filename}"


# ---------------------------------------------------------------------------
# Adversarial variant builders
#
# Each builder takes (prefix, dotdir, filename) and returns the adversarial
# input string. Variants that don't apply to a target (e.g. trailing-combo
# without a dotdir) are filtered at parametrize time.
# ---------------------------------------------------------------------------


def _v_traversal_documents(prefix: str, dotdir: str, filename: str) -> str:
    """``<prefix>/Documents/../<dotdir>/<filename>`` — single-level ``..``."""
    tail = f"{dotdir}/{filename}" if dotdir else filename
    return f"{prefix}/Documents/../{tail}"


def _v_traversal_deep(prefix: str, dotdir: str, filename: str) -> str:
    """``<prefix>/x/y/../../<dotdir>/<filename>`` — two-level ``..``."""
    tail = f"{dotdir}/{filename}" if dotdir else filename
    return f"{prefix}/x/y/../../{tail}"


def _v_single_dot_mid(prefix: str, dotdir: str, filename: str) -> str:
    """``<prefix>/./<dotdir>/<filename>`` — single ``.`` segment at root."""
    tail = f"{dotdir}/{filename}" if dotdir else filename
    return f"{prefix}/./{tail}"


def _v_double_slash(prefix: str, dotdir: str, filename: str) -> str:
    """``<prefix>//<dotdir>/<filename>`` — doubled separator after home."""
    tail = f"{dotdir}/{filename}" if dotdir else filename
    return f"{prefix}//{tail}"


def _v_triple_slash(prefix: str, dotdir: str, filename: str) -> str:
    """``<prefix>///<dotdir>/<filename>`` — tripled separator after home."""
    tail = f"{dotdir}/{filename}" if dotdir else filename
    return f"{prefix}///{tail}"


def _v_trailing_single_dot(prefix: str, dotdir: str, filename: str) -> str:
    """``<prefix>/<dotdir>/./<filename>`` — single ``.`` between dotdir + file.

    Applies only when ``has_subfile_under_dotdir`` is True (otherwise the
    deny prefix already matches and there's no bypass to RED).
    """
    return f"{prefix}/{dotdir}/./{filename}"


def _v_trailing_double_slash(prefix: str, dotdir: str, filename: str) -> str:
    """``<prefix>/<dotdir>//<filename>`` — doubled separator between dotdir + file.

    Same applicability rule as ``_v_trailing_single_dot``.
    """
    return f"{prefix}/{dotdir}//{filename}"


# (variant_id, builder, requires_subfile_under_dotdir)
RED_VARIANTS = [
    ("traversal_documents", _v_traversal_documents, False),
    ("traversal_deep", _v_traversal_deep, False),
    ("single_dot_mid", _v_single_dot_mid, False),
    ("double_slash", _v_double_slash, False),
    ("triple_slash", _v_triple_slash, False),
    ("trailing_single_dot", _v_trailing_single_dot, True),
    ("trailing_double_slash", _v_trailing_double_slash, True),
]


def _red_matrix() -> list[tuple[str, str]]:
    """Cross-product target × prefix × variant for the RED bracket.

    Returns a list of ``(case_id, file_path)`` pairs. Variants requiring a
    sub-file under the dotdir are filtered for targets without one. This
    keeps every emitted case a real RED — no green-by-accident entries.
    """
    cases: list[tuple[str, str]] = []
    for target_id, dotdir, filename, has_subfile in SENSITIVE_TARGETS:
        for prefix in HOME_PREFIXES:
            for variant_id, builder, requires_subfile in RED_VARIANTS:
                if requires_subfile and not has_subfile:
                    continue
                # Prefix label for the test id — strip ``/`` and ``$`` so the
                # pytest -k filter is convenient.
                prefix_label = prefix.replace("/", "_").replace("$", "")
                case_id = f"{target_id}__{prefix_label}__{variant_id}"
                file_path = builder(prefix, dotdir, filename)
                cases.append((case_id, file_path))
    return cases


RED_CASES = _red_matrix()
RED_IDS = [c[0] for c in RED_CASES]
RED_PATHS = [c[1] for c in RED_CASES]


# ---------------------------------------------------------------------------
# RED bracket — these MUST fail today and pass after the Warrior lands the
# canonicalizer fix. Both Write and Edit are exercised because the deny
# floor gates both tool names symmetrically.
# ---------------------------------------------------------------------------


class TestAdversarialCanonicalizationDeniesWrite:
    """Every adversarial input variant of every sensitive target MUST DENY
    when the tool is ``Write``.

    Failure mode on current code: the hook returns ``{}`` and the input
    flows through. The Warrior fixes this by normalizing redundant
    separators on POSIX inputs AND resolving ``.``/``..`` segments before
    the deny-prefix scan.
    """

    @pytest.mark.parametrize("file_path", RED_PATHS, ids=RED_IDS)
    @pytest.mark.asyncio
    async def test_write_adversarial_path_denied(self, file_path: str) -> None:
        result = await _run_write_edit("Write", file_path)
        assert _is_deny(result), (
            f"Adversarial Write of {file_path!r} must DENY — the "
            "canonicalizer must normalize ``//`` / ``..`` / ``./`` "
            "segments before the deny-prefix scan. Currently returns "
            f"{result!r}, which silently bypasses the credential floor."
        )


class TestAdversarialCanonicalizationDeniesEdit:
    """Mirror of TestAdversarialCanonicalizationDeniesWrite for ``Edit``.

    The deny floor is symmetric across Write/Edit; this guard prevents a
    future Warrior from accidentally fixing only one of the two tool
    names.
    """

    @pytest.mark.parametrize("file_path", RED_PATHS, ids=RED_IDS)
    @pytest.mark.asyncio
    async def test_edit_adversarial_path_denied(self, file_path: str) -> None:
        result = await _run_write_edit("Edit", file_path)
        assert _is_deny(result), (
            f"Adversarial Edit of {file_path!r} must DENY — the "
            "canonicalizer must normalize ``//`` / ``..`` / ``./`` "
            "segments before the deny-prefix scan. Currently returns "
            f"{result!r}, which silently bypasses the credential floor."
        )


# ---------------------------------------------------------------------------
# Canonical-form bracket — direct probe of the helper. Catches the bug
# one layer above the hook so a debugging Warrior sees the exact transform
# they need to make.
# ---------------------------------------------------------------------------


CANONICAL_EXPECTATIONS = [
    # (input, expected_canonical_form)
    ("/home/alice/Documents/../.ssh/id_rsa", "~/.ssh/id_rsa"),
    ("/home/alice/x/y/../../.ssh/id_rsa", "~/.ssh/id_rsa"),
    ("/home/alice/./.ssh/id_rsa", "~/.ssh/id_rsa"),
    ("/home/alice//.ssh/id_rsa", "~/.ssh/id_rsa"),
    ("/home/alice///.ssh/id_rsa", "~/.ssh/id_rsa"),
    ("/home/alice/.ssh/./id_rsa", "~/.ssh/id_rsa"),
    ("/home/alice/.ssh//id_rsa", "~/.ssh/id_rsa"),
    ("$HOME/x/../.aws/credentials", "~/.aws/credentials"),
    ("$HOME//.ssh/authorized_keys", "~/.ssh/authorized_keys"),
    ("$HOME/./.netrc", "~/.netrc"),
    ("/home/alice/Documents/../.aws/credentials", "~/.aws/credentials"),
    ("/home/alice/./.netrc", "~/.netrc"),
]


class TestCanonicalFormCollapsesAdversarialSegments:
    """The canonicalizer MUST resolve ``.``/``..`` segments AND collapse
    redundant separators on POSIX inputs.

    These assertions probe the helper directly so a Warrior sees the exact
    transform shape they need. The matcher-layer tests above will GREEN
    automatically once these GREEN.
    """

    @pytest.mark.parametrize(
        ("file_path", "expected"),
        CANONICAL_EXPECTATIONS,
        ids=[c[0] for c in CANONICAL_EXPECTATIONS],
    )
    def test_canonical_form_matches_clean_baseline(self, file_path: str, expected: str) -> None:
        canonical = _mod._canonicalize_write_edit_path(file_path)
        assert canonical == expected, (
            f"Canonical form of {file_path!r} must collapse to {expected!r}. "
            f"Got {canonical!r} — adversarial segments leaked past the "
            "canonicalizer."
        )


# ---------------------------------------------------------------------------
# xfail bracket — variants the Warrior is NOT expected to fix in W8.A.
# These pin the open question so a future ticket (W8.M for mixed-case;
# unspecified for percent-encoding) has a failing test to convert.
# ---------------------------------------------------------------------------


class TestCaseSensitivityIsKnownGap:
    """Linux is case-sensitive at the FS layer, so ``/home/alice/.SSH/id_rsa``
    is technically a distinct path. Structural case-folding inside the
    matcher is W8.M and out of W8.A scope.

    xfail(strict=True) so the test goes RED — and visibly so — the moment
    the W8.M fix lands, prompting a follow-up to flip these to plain
    asserts.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="W8.M: case-insensitive deny-prefix matcher not yet implemented",
    )
    @pytest.mark.asyncio
    async def test_uppercase_ssh_dir_denied(self) -> None:
        result = await _run_write_edit("Write", "/home/alice/.SSH/id_rsa")
        assert _is_deny(result), (
            "Mixed-case ``.SSH/`` must DENY when the matcher gains "
            "case-insensitive prefix comparison (W8.M)."
        )

    @pytest.mark.xfail(
        strict=True,
        reason="W8.M: case-insensitive deny-prefix matcher not yet implemented",
    )
    @pytest.mark.asyncio
    async def test_mixed_case_aws_dir_denied(self) -> None:
        result = await _run_write_edit("Write", "/home/alice/.AWS/credentials")
        assert _is_deny(result), (
            "Mixed-case ``.AWS/`` must DENY when the matcher gains "
            "case-insensitive prefix comparison (W8.M)."
        )


class TestPercentEncodingIsKnownGap:
    """The canonicalizer is not required to decode percent-escapes in v0.1.
    A future ticket may decide to add a decode pass; until then these
    inputs xfail.

    xfail(strict=True) so a future decode pass surfaces these as a green
    signal, prompting conversion to plain asserts.
    """

    @pytest.mark.xfail(
        strict=True,
        reason="v0.1: canonicalizer does not URL-decode percent-escapes",
    )
    @pytest.mark.asyncio
    async def test_percent_encoded_traversal_denied(self) -> None:
        result = await _run_write_edit("Write", "/home/alice/%2e%2e/.ssh/id_rsa")
        assert _is_deny(result), (
            "Percent-encoded ``..`` (``%2e%2e``) must DENY when the "
            "canonicalizer gains a URL-decode pass."
        )

    @pytest.mark.xfail(
        strict=True,
        reason="v0.1: canonicalizer does not URL-decode percent-escapes",
    )
    @pytest.mark.asyncio
    async def test_percent_encoded_separator_denied(self) -> None:
        result = await _run_write_edit("Write", "/home/alice/.ssh%2fid_rsa")
        assert _is_deny(result), (
            "Percent-encoded path separator (``%2f``) must DENY when the "
            "canonicalizer gains a URL-decode pass."
        )


# ---------------------------------------------------------------------------
# Bash-not-affected regression smoke.
#
# The W8.A canonicalizer fix lives behind the Write/Edit gate. Bash
# continues to flow through the C1-C7 catalogue. This smoke check pins
# that contract — a Warrior who accidentally widens the canonicalization
# fix to Bash would regress C1-C7's bash-shape coverage.
# ---------------------------------------------------------------------------


class TestBashUnaffectedByCanonicalizerFix:
    @pytest.mark.asyncio
    async def test_bash_ls_with_traversal_still_passes_through(self) -> None:
        """``ls /home/alice/Documents/..`` is not a bash-shape match for any
        C1-C7 rule and must continue to pass through. The Write/Edit
        canonicalizer fix MUST NOT bleed into Bash.
        """
        hook = build_preexec_hook(SecurityHooksConfig())
        result = await hook(
            {
                "hook_event_name": "PreToolUse",
                "tool_name": "Bash",
                "tool_input": {"command": "ls /home/alice/Documents/.."},
            },
            "tu1",
            {"signal": None},
        )
        # Either {} or a non-deny envelope — but never a Write/Edit-style
        # deny on a bare ``ls``.
        assert (
            result == {} or result.get("hookSpecificOutput", {}).get("permissionDecision") != "deny"
        )
