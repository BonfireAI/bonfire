# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract — BON-1073 security-polish bundle.

Three defense-in-depth consistency gaps surfaced by post-Wave 9 audit:

1. ``C1.1-rm-rf-non-temp`` regex anchor inconsistency.

   The shipped rule uses ``(?:^|[|;&]\\s*)rm\\s+...`` while every other
   deny rule in the catalogue uses a ``\\b`` word boundary. Forms like
   ``/bin/rm -rf /``, ``exec rm -rf /``, ``\\rm -rf /``, and
   ``time rm -rf /`` / ``nice rm -rf /`` / ``command rm -rf /`` are not
   chained or piped — they bypass the C1.1 anchor entirely because the
   character before ``rm`` is a word char (``/`` is non-word but the
   regex requires ``^`` or ``|;&``) or a wrapper that ``_unwrap`` does
   not peel. Switching to ``\\b`` aligns C1.1 with C1.2-C1.7 and closes
   the family.

2. ``WRITE_EDIT_SENSITIVE_PATH_DENY`` expansion.

   Six new entries that the v0.1 floor failed to cover:

   * ``~/.ssh/config`` — host aliases + ProxyCommand vectors.
   * ``~/.config/git/config`` — modern XDG location for the global git
     config; the legacy ``~/.gitconfig`` was already covered but XDG
     installs land here and silently bypassed the floor.
   * ``/etc/cron.d/`` — directory of system cron jobs.
   * ``/etc/systemd/system/`` — systemd unit drop-in directory.
   * ``/usr/local/bin/`` — standard local-binary directory (a Write here
     plants an executable on ``$PATH``).
   * ``/etc/ld.so.preload`` — LD_PRELOAD persistence vector.

   Each entry is tested across the deny-list adversarial matrix:
   literal, ``..``-traversal landing back in prefix, ``//``-double-slash,
   mixed-case (case-fold on case-insensitive filesystems), URL-encoded
   (xfail — canonicalizer does not decode), and tilde-expanded
   ``/home/<user>`` form.

3. ``_safe_resolve_config_path`` symlink-target tightening.

   The MCP-server scanner previously accepted any symlink whose target
   resolved under ``home_dir`` OR ``project_path``. The new rule refuses
   home-directory symlink targets unconditionally: a symlink may resolve
   ONLY to a path under ``project_path`` (the write-floor). A symlink
   whose target lives in ``$HOME`` outside the write-floor — even if the
   symlink itself sits inside the write-floor — is refused and a WARNING
   is logged.

   This closes the bypass where a malicious or compromised symlink in a
   discoverable config location (e.g. ``~/.cursor/mcp.json``) silently
   exfiltrated config from anywhere under ``$HOME`` into the scanner's
   discovered-server set.

Per the defense-in-depth doctrine, deny-list additions need
adversarial-shape coverage (``..``, ``//``, case-fold, encoded). Each
shape pass is parametrized so a future regression on canonicalization
fails on the specific shape, not the literal.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

try:
    from bonfire.dispatch import security_hooks as _hooks_mod
    from bonfire.dispatch.security_hooks import (
        SecurityHooksConfig,
        build_preexec_hook,
    )
    from bonfire.dispatch.security_patterns import DEFAULT_DENY_PATTERNS
    from bonfire.onboard.scanners import mcp_servers as _scanner_mod
    from bonfire.onboard.scanners.mcp_servers import _safe_resolve_config_path
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    _hooks_mod = None  # type: ignore[assignment]
    SecurityHooksConfig = None  # type: ignore[assignment,misc]
    build_preexec_hook = None  # type: ignore[assignment]
    DEFAULT_DENY_PATTERNS = None  # type: ignore[assignment]
    _scanner_mod = None  # type: ignore[assignment]
    _safe_resolve_config_path = None  # type: ignore[assignment]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module() -> None:
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire modules not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# 1. C1.1 rm-regex consistency
# ---------------------------------------------------------------------------


def _find_rule(rule_id: str):
    for r in DEFAULT_DENY_PATTERNS:
        if r.rule_id == rule_id:
            return r
    available = sorted({r.rule_id for r in DEFAULT_DENY_PATTERNS})
    pytest.fail(f"rule_id {rule_id!r} not in DEFAULT_DENY_PATTERNS: {available}")


class TestC11RmRegexConsistency:
    """C1.1 must match ``\\brm`` so wrapper/path forms cannot bypass."""

    @pytest.mark.parametrize(
        "cmd",
        [
            # Absolute-path invocations.
            "/bin/rm -rf /etc",
            "/usr/bin/rm -rf /home/user",
            # exec wrapper (not peeled by _unwrap).
            "exec rm -rf /etc",
            # Backslash escape (interactive-shell alias-bypass shape).
            "\\rm -rf /etc",
            # Process-time wrappers (also not peeled by _unwrap).
            "time rm -rf /etc",
            "nice rm -rf /etc",
            "command rm -rf /etc",
            # Long-flag wrappers.
            "/bin/rm -Rf /home/user",
            "/bin/rm -fr /etc/secrets",
        ],
    )
    def test_bypass_forms_now_match(self, cmd: str) -> None:
        """Each form that previously slipped the (?:^|[|;&]) anchor must DENY."""
        rule = _find_rule("C1.1-rm-rf-non-temp")
        assert rule.pattern.search(cmd) is not None, (
            f"C1.1 must match wrapper/path form {cmd!r} (\\b anchor)"
        )

    @pytest.mark.parametrize(
        "cmd",
        [
            # Ephemeral path exclusions still apply.
            "/bin/rm -rf /tmp/scratch",
            "exec rm -rf node_modules",
            "time rm -rf .venv",
            "command rm -rf __pycache__",
        ],
    )
    def test_ephemeral_exclusions_still_apply(self, cmd: str) -> None:
        """Wrapper + ephemeral path remains a false-positive (allow)."""
        rule = _find_rule("C1.1-rm-rf-non-temp")
        assert rule.pattern.search(cmd) is None, (
            f"C1.1 must NOT match wrapper+ephemeral form {cmd!r}"
        )


# ---------------------------------------------------------------------------
# 2. WRITE_EDIT_SENSITIVE_PATH_DENY expansion
# ---------------------------------------------------------------------------


# New entries added by BON-1073. Each tuple is
#   (deny_prefix, sample_file_under_prefix_or_None)
# When ``sample_file`` is None, the deny prefix IS the file itself
# (e.g. ``~/.ssh/config``); the adversarial matrix below builds shapes
# directly against the prefix.
_NEW_DENY_ENTRIES: tuple[tuple[str, str | None], ...] = (
    ("~/.ssh/config", None),
    ("~/.config/git/config", None),
    ("/etc/cron.d/", "evil_job"),
    ("/etc/systemd/system/", "evil.service"),
    ("/usr/local/bin/", "evil_binary"),
    ("/etc/ld.so.preload", None),
)


def _literal_path(prefix: str, sample: str | None) -> str:
    """Build the literal positive-shape path for ``(prefix, sample)``."""
    if sample is None:
        return prefix
    return prefix + sample


def _home_expanded(path: str) -> str:
    """Replace a leading ``~/`` with ``/home/alice/`` for the tilde-expansion shape."""
    if path.startswith("~/"):
        return "/home/alice/" + path[2:]
    return path


def _dotdot_landing(path: str) -> str:
    """Build a ``..``-traversal shape that lands BACK in the deny prefix.

    For ``/etc/cron.d/evil`` returns ``/etc/cron.d/x/../evil`` —
    after dot-resolution this collapses back to ``/etc/cron.d/evil``.
    For ``~/.ssh/config`` returns ``~/.ssh/x/../config``.
    """
    if "/" not in path.rstrip("/"):
        return path
    head, _, tail = path.rstrip("/").rpartition("/")
    return f"{head}/x/../{tail}"


def _double_slash(path: str) -> str:
    """Insert ``//`` mid-path so the collapse-pass must fire."""
    if "/" not in path:
        return path
    # Inject after the first slash that has a non-slash neighbor on both
    # sides — keeps tilde prefix and absolute anchor intact.
    if path.startswith("~/"):
        head, tail = path[:2], path[2:]
    elif path.startswith("/"):
        head, tail = "/", path[1:]
    else:
        head, tail = "", path
    if "/" in tail:
        left, _, right = tail.partition("/")
        return head + left + "//" + right
    return head + tail + "//"


def _mixed_case(path: str) -> str:
    """Build a mixed-case variant — case-fold must still match on case-insensitive FS."""
    # Capitalize the segment after the first ``/`` so the deny scan sees
    # a visibly different shape from the literal prefix.
    return "".join(c.upper() if i % 2 == 0 else c for i, c in enumerate(path))


def _url_encoded(path: str) -> str:
    """URL-encode the path separators — canonicalizer does not decode (xfail)."""
    return path.replace("/", "%2F")


async def _run_write_edit(file_path: str) -> dict:
    hook = build_preexec_hook(SecurityHooksConfig())
    return await hook(
        {
            "hook_event_name": "PreToolUse",
            "tool_name": "Write",
            "tool_input": {"file_path": file_path},
        },
        "tu1",
        {"signal": None},
    )


def _is_deny(result: dict) -> bool:
    return result.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"


class TestDenyListExpansion:
    """Six new entries x five adversarial shapes — defense-in-depth matrix."""

    @pytest.mark.parametrize("prefix,sample", _NEW_DENY_ENTRIES)
    def test_entry_is_registered(self, prefix: str, sample: str | None) -> None:
        """The literal prefix must appear in WRITE_EDIT_SENSITIVE_PATH_DENY."""
        assert prefix in _hooks_mod.WRITE_EDIT_SENSITIVE_PATH_DENY, (
            f"{prefix!r} must be registered in WRITE_EDIT_SENSITIVE_PATH_DENY"
        )

    @pytest.mark.parametrize("prefix,sample", _NEW_DENY_ENTRIES)
    async def test_literal_shape_is_denied(self, prefix: str, sample: str | None) -> None:
        path = _literal_path(prefix, sample)
        result = await _run_write_edit(path)
        assert _is_deny(result), f"Write to literal {path!r} must be DENIED"

    @pytest.mark.parametrize("prefix,sample", _NEW_DENY_ENTRIES)
    async def test_tilde_expanded_shape_is_denied(self, prefix: str, sample: str | None) -> None:
        """``/home/<user>/.ssh/config`` must canonicalize to ``~/.ssh/config`` and DENY."""
        path = _home_expanded(_literal_path(prefix, sample))
        result = await _run_write_edit(path)
        assert _is_deny(result), f"Write to tilde-expanded {path!r} must be DENIED"

    @pytest.mark.parametrize("prefix,sample", _NEW_DENY_ENTRIES)
    async def test_dotdot_landing_shape_is_denied(self, prefix: str, sample: str | None) -> None:
        """``..`` traversal landing back in the deny prefix must still DENY."""
        path = _dotdot_landing(_literal_path(prefix, sample))
        result = await _run_write_edit(path)
        assert _is_deny(result), f"Write to dot-dot {path!r} must be DENIED"

    @pytest.mark.parametrize("prefix,sample", _NEW_DENY_ENTRIES)
    async def test_double_slash_shape_is_denied(self, prefix: str, sample: str | None) -> None:
        """``//`` double-slash must collapse and DENY."""
        path = _double_slash(_literal_path(prefix, sample))
        result = await _run_write_edit(path)
        assert _is_deny(result), f"Write to double-slash {path!r} must be DENIED"

    @pytest.mark.parametrize("prefix,sample", _NEW_DENY_ENTRIES)
    async def test_mixed_case_denied_on_case_insensitive_fs(
        self,
        prefix: str,
        sample: str | None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """On macOS / Windows the deny scan is case-folded — mixed case must DENY."""
        monkeypatch.setattr(_hooks_mod, "_is_case_insensitive_fs", lambda: True)
        path = _mixed_case(_literal_path(prefix, sample))
        result = await _run_write_edit(path)
        assert _is_deny(result), (
            f"Write to mixed-case {path!r} on case-insensitive FS must be DENIED"
        )

    @pytest.mark.parametrize("prefix,sample", _NEW_DENY_ENTRIES)
    @pytest.mark.xfail(
        strict=True,
        reason=(
            "URL-encoded path separators are NOT decoded by the canonicalizer "
            "in v0.1; pin this open question (consistent with prior "
            "test_security_hooks_canonicalizer_adversarial xfails)."
        ),
    )
    async def test_url_encoded_shape_is_denied(self, prefix: str, sample: str | None) -> None:
        path = _url_encoded(_literal_path(prefix, sample))
        result = await _run_write_edit(path)
        assert _is_deny(result), f"Write to url-encoded {path!r} should be DENIED"


# ---------------------------------------------------------------------------
# 3. _safe_resolve_config_path symlink tightening
# ---------------------------------------------------------------------------


def _make_emit_recorder():
    """Capture emitted ScanUpdate events into a list."""
    events: list = []

    async def emit(event) -> None:
        events.append(event)

    return emit, events


class TestSafeResolveConfigPathHomeRefuse:
    """Symlink targets in ``$HOME`` (outside the write-floor) must be refused.

    BON-1073 tightens the prior policy that allowed symlink targets
    under either ``home_dir`` or ``project_path``. New rule: targets
    must resolve under ``project_path`` only.
    """

    def test_non_symlink_passthrough_unchanged(self, tmp_path: Path) -> None:
        """A direct (non-symlink) file path is returned as-is.

        Sanity: the function only tightens the symlink branch. Direct
        config-file paths under ``$HOME`` (e.g. the literal
        ``~/.config/Claude/claude_desktop_config.json``) must keep working
        — the scanner discovers them by direct path, not by symlink.
        """
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()
        direct = home_dir / ".config" / "Claude" / "claude_desktop_config.json"
        direct.parent.mkdir(parents=True)
        direct.write_text("{}")
        result = _safe_resolve_config_path(direct, home_dir=home_dir, project_path=project_path)
        assert result == direct, "non-symlink direct paths must pass through unchanged"

    def test_symlink_target_under_project_path_is_followed(self, tmp_path: Path) -> None:
        """Symlink whose target lives under the write-floor (project_path) — ALLOW."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()
        # Real config file under the project (write-floor).
        real_target = project_path / "configs" / "mcp.json"
        real_target.parent.mkdir(parents=True)
        real_target.write_text("{}")
        # Symlink sits in home; target is under project.
        config_path = home_dir / ".cursor" / "mcp.json"
        config_path.parent.mkdir(parents=True)
        config_path.symlink_to(real_target)
        result = _safe_resolve_config_path(
            config_path, home_dir=home_dir, project_path=project_path
        )
        assert result is not None, "symlink target under project_path must be followed"
        assert result == real_target.resolve()

    def test_symlink_target_in_home_outside_project_is_refused(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Symlink target under ``$HOME`` but outside write-floor — REFUSE.

        This is the BON-1073 tightening: the prior policy accepted any
        target under ``home_dir``; the new policy refuses anything under
        ``$HOME`` that is not also under ``project_path``. A WARNING is
        logged so operators see the refusal.
        """
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()
        # Real file in home, OUTSIDE the write-floor.
        real_target = home_dir / "dotfiles" / "mcp.json"
        real_target.parent.mkdir(parents=True)
        real_target.write_text("{}")
        config_path = home_dir / ".cursor" / "mcp.json"
        config_path.parent.mkdir(parents=True)
        config_path.symlink_to(real_target)
        caplog.set_level(logging.WARNING, logger="bonfire.onboard.scanners.mcp_servers")
        result = _safe_resolve_config_path(
            config_path, home_dir=home_dir, project_path=project_path
        )
        assert result is None, "symlink target in home but outside write-floor must be REFUSED"
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "refusal must log a WARNING so operators can see the skip"

    def test_symlink_target_outside_both_roots_still_refused(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Pre-existing rule: targets outside both roots remain refused."""
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()
        outside = tmp_path / "outside" / "mcp.json"
        outside.parent.mkdir(parents=True)
        outside.write_text("{}")
        config_path = home_dir / ".cursor" / "mcp.json"
        config_path.parent.mkdir(parents=True)
        config_path.symlink_to(outside)
        caplog.set_level(logging.WARNING, logger="bonfire.onboard.scanners.mcp_servers")
        result = _safe_resolve_config_path(
            config_path, home_dir=home_dir, project_path=project_path
        )
        assert result is None
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings

    async def test_scanner_skips_home_symlink_target(
        self,
        tmp_path: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """End-to-end: scan() must skip configs whose symlink targets home.

        This is the integration-shape contract — what the scanner does
        with the tightened ``_safe_resolve_config_path`` under a real
        discovery walk. The prior test
        ``test_symlink_within_home_is_followed`` asserted the OPPOSITE
        policy and is updated in the same Knight commit.
        """
        home_dir = tmp_path / "home"
        home_dir.mkdir()
        project_path = tmp_path / "proj"
        project_path.mkdir()
        # Real file lives in home, OUTSIDE the project (write-floor).
        real_target = home_dir / "dotfiles" / "zed-settings.json"
        real_target.parent.mkdir(parents=True)
        real_target.write_text(
            json.dumps(
                {
                    "context_servers": {
                        "filesystem": {
                            "command": "npx",
                            "args": [
                                "-y",
                                "@modelcontextprotocol/server-filesystem",
                            ],
                        },
                    },
                }
            )
        )
        config_path = home_dir / ".config" / "zed" / "settings.json"
        config_path.parent.mkdir(parents=True)
        config_path.symlink_to(real_target)
        caplog.set_level(logging.WARNING, logger="bonfire.onboard.scanners.mcp_servers")
        emit, events = _make_emit_recorder()
        await _scanner_mod.scan(project_path, emit, home_dir=home_dir)
        zed_events = [e for e in events if getattr(e, "value", None) == "Zed"]
        assert not zed_events, (
            "scanner must NOT emit events for a symlink whose target is in "
            f"home but outside the write-floor; got: {events!r}"
        )
        warnings = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warnings, "scanner must log a WARNING when refusing a home-target symlink"
