# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Security pattern catalogue for the Bonfire pre-exec hook.

Public surface — three symbols:
- ``DenyRule`` — frozen slotted dataclass describing one pattern rule.
- ``DEFAULT_DENY_PATTERNS`` — tuple of 37 rules that the hook hard-denies
  (categories C1, C2, C3, C4, C7).
- ``DEFAULT_WARN_PATTERNS`` — tuple of 15 rules the hook warns on but does
  not deny (categories C5, C6). WARN emits a SecurityDenied event whose
  reason is prefixed ``"WARN: "``; the tool call still proceeds.

Action (deny vs warn) is implicit in which tuple a rule lives in — the
dataclass does NOT carry it. All patterns are derived from a curated
pattern catalogue.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

__all__ = ["DEFAULT_DENY_PATTERNS", "DEFAULT_WARN_PATTERNS", "DenyRule"]


@dataclass(frozen=True, slots=True)
class DenyRule:
    """A single pattern rule.

    Attributes:
        rule_id: Stable slug of form ``C<n>.<idx>-<kebab-slug>``.
        category: Threat category (destructive-fs, destructive-git, ...).
        pattern: Pre-compiled regex — matched against normalized + unwrapped
            command segments.
        message: Human-readable reason surfaced to the agent and to the
            SecurityDenied event.
    """

    rule_id: str
    category: str
    pattern: re.Pattern[str]
    message: str


# ---------------------------------------------------------------------------
# C1 destructive-fs (8 DENY)
# ---------------------------------------------------------------------------


_C1_RULES: tuple[DenyRule, ...] = (
    DenyRule(
        rule_id="C1.1-rm-rf-non-temp",
        category="destructive-fs",
        # Exclusion list is anchored at path-segment boundaries.
        # Each ephemeral-dir token (``node_modules``, ``.venv``, ``__pycache__``,
        # ``dist``, ``build``) is bracketed by ``(?:^|/)`` on the left and
        # ``(?:/|\s|$)`` on the right, so:
        #   * ``rm -rf __pycache__-backup/db`` is NOT excused (the dir name
        #     merely starts with the token as a substring — DENY).
        #   * ``rm -rf project/.venv`` IS excused (real ephemeral dir one
        #     path-segment deep — ALLOW).
        # Absolute-path prefixes (``/tmp/``, ``/var/tmp/``, ``$TMPDIR/``, ``./``)
        # remain anchored at the start of the path argument as before.
        pattern=re.compile(
            r"(?:^|[|;&]\s*)rm\s+(?:-[a-zA-Z]*[rRfF][a-zA-Z]*\s+)+"
            r"(?!"
            r"(?:/tmp/|/var/tmp/|\$TMPDIR/|\./)"
            r"|"
            r"(?:[a-zA-Z0-9_./-]*?/)?"
            r"(?:node_modules|\.venv|__pycache__|dist|build)"
            r"(?:/|\s|$)"
            r")"
        ),
        message=("rm -rf outside ephemeral paths is denied. If intended, run manually."),
    ),
    DenyRule(
        rule_id="C1.2-dd-to-device",
        category="destructive-fs",
        pattern=re.compile(r"\bdd\s+.*\bof=/dev/(?:sd[a-z]|nvme|xvd|disk|hda)"),
        message="dd writing to a raw block device is denied.",
    ),
    DenyRule(
        rule_id="C1.3-mkfs-on-device",
        category="destructive-fs",
        pattern=re.compile(r"\bmkfs(?:\.[a-z0-9]+)?\s+/dev/"),
        message="mkfs on a /dev device is denied.",
    ),
    DenyRule(
        rule_id="C1.4-shred",
        category="destructive-fs",
        pattern=re.compile(r"\bshred\s+(?:-[a-zA-Z]*[a-zA-Z]*\s+)*"),
        message="shred irrecoverably overwrites files — denied.",
    ),
    DenyRule(
        rule_id="C1.5-redirect-to-device",
        category="destructive-fs",
        # Match ``> /dev/<real-device>`` — /dev/null, /dev/stderr, /dev/stdout
        # are explicitly NOT in the alternation.
        pattern=re.compile(r">\s*/dev/(?:sd[a-z]|nvme|xvd|hda)"),
        message="Redirecting into a block device is denied.",
    ),
    DenyRule(
        rule_id="C1.6-mv-root",
        category="destructive-fs",
        pattern=re.compile(r"\bmv\s+/(?![a-zA-Z])"),
        message="mv / is catastrophic — denied.",
    ),
    DenyRule(
        rule_id="C1.7-find-delete",
        category="destructive-fs",
        pattern=re.compile(r"\b(?:find|fd)\s+.*-delete\b"),
        message="find/fd -delete is denied — scope too broad.",
    ),
    DenyRule(
        rule_id="C1.8-redirect-overwrite-home",
        category="destructive-fs",
        pattern=re.compile(r"(?<!>)>\s*(?:~|\$HOME)(?:/\.?[a-zA-Z_]+)?\s*$"),
        message="Truncating a home dotfile is denied. Use >> to append.",
    ),
)


# ---------------------------------------------------------------------------
# C2 destructive-git (9 DENY)
# ---------------------------------------------------------------------------


_C2_RULES: tuple[DenyRule, ...] = (
    DenyRule(
        rule_id="C2.1-git-reset-hard",
        category="destructive-git",
        pattern=re.compile(r"\bgit\s+reset\s+(?:--hard|--merge)\b"),
        message="git reset --hard/--merge discards work — denied.",
    ),
    DenyRule(
        rule_id="C2.2-git-clean-force",
        category="destructive-git",
        pattern=re.compile(r"\bgit\s+clean\s+-[a-zA-Z]*f"),
        message="git clean -f* deletes untracked files — denied. Use git clean -n to preview.",
    ),
    DenyRule(
        rule_id="C2.3-git-push-force",
        category="destructive-git",
        # ``--force`` followed by end-of-word (not the ``-with-lease`` variant).
        pattern=re.compile(r"\bgit\s+push\s+(?:--force(?![-a-zA-Z])|-f\b)"),
        message="Use --force-with-lease instead of --force.",
    ),
    DenyRule(
        rule_id="C2.4-git-branch-delete-force",
        category="destructive-git",
        pattern=re.compile(r"\bgit\s+branch\s+-D\b"),
        message="git branch -D deletes unmerged branches — denied.",
    ),
    DenyRule(
        rule_id="C2.5-git-checkout-dot",
        category="destructive-git",
        pattern=re.compile(r"\bgit\s+checkout\s+--\s+\."),
        message="git checkout -- . discards all uncommitted work — denied.",
    ),
    DenyRule(
        rule_id="C2.6-git-restore-worktree",
        category="destructive-git",
        pattern=re.compile(r"\bgit\s+restore\b(?!.*--staged)"),
        message="git restore (worktree) discards changes — denied. Use --staged to unstage.",
    ),
    DenyRule(
        rule_id="C2.7-git-stash-drop-clear",
        category="destructive-git",
        pattern=re.compile(r"\bgit\s+stash\s+(?:drop|clear)\b"),
        message="git stash drop/clear is irreversible — denied.",
    ),
    DenyRule(
        rule_id="C2.8-git-reflog-expire",
        category="destructive-git",
        pattern=re.compile(r"\bgit\s+(?:update-ref|reflog\s+expire)\b"),
        message="git reflog expire / update-ref can destroy history — denied.",
    ),
    DenyRule(
        rule_id="C2.9-git-filter-branch",
        category="destructive-git",
        pattern=re.compile(r"\bgit\s+filter-(?:branch|repo)\b"),
        message="git filter-branch/filter-repo rewrites history — denied.",
    ),
)


# ---------------------------------------------------------------------------
# C3 pipe-to-shell (5 DENY)
# ---------------------------------------------------------------------------


_C3_RULES: tuple[DenyRule, ...] = (
    DenyRule(
        rule_id="C3.1-curl-pipe-shell",
        category="pipe-to-shell",
        pattern=re.compile(
            r"\b(?:curl|wget|fetch)\s+[^|;&]*\|\s*(?:sudo\s+)?"
            r"(?:sh|bash|zsh|dash|ksh|python|python3|perl|ruby|node)\b"
        ),
        message="Piping downloaded content into a shell is denied.",
    ),
    DenyRule(
        rule_id="C3.2-wget-output-pipe-shell",
        category="pipe-to-shell",
        # wget/curl with -O-/-o- (output to stdout) piped into a shell.
        pattern=re.compile(
            r"\b(?:curl|wget)\s+(?:\S+\s+)*-[oO][- ][^|;&]*\|\s*"
            r"(?:sudo\s+)?(?:sh|bash)"
        ),
        message="wget/curl -O- piped to a shell is denied.",
    ),
    DenyRule(
        rule_id="C3.3-bash-process-sub",
        category="pipe-to-shell",
        pattern=re.compile(r"\b(?:bash|sh)\s+<\s*\(\s*curl\b"),
        message="bash <(curl ...) — process-substitution RCE denied.",
    ),
    DenyRule(
        rule_id="C3.4-bash-c-substitution",
        category="pipe-to-shell",
        pattern=re.compile(r"\b(?:bash|sh)\s+-c\s+[\"'][^\"']*\$\(.*(?:curl|wget)"),
        message='bash -c "$(curl ...)" — denied.',
    ),
    DenyRule(
        rule_id="C3.5-dot-source-process-sub",
        category="pipe-to-shell",
        pattern=re.compile(r"\.\s+<\(\s*(?:curl|wget)"),
        message=". <(curl/wget ...) — dot-source of remote script denied.",
    ),
)


# ---------------------------------------------------------------------------
# C4 exfiltration (7 DENY)
# ---------------------------------------------------------------------------


_C4_RULES: tuple[DenyRule, ...] = (
    DenyRule(
        rule_id="C4.1-cat-ssh-private-key",
        category="exfiltration",
        # Extended to cover macOS ``/Users/<u>/`` and Windows
        # ``[A-Za-z]:[\\/]Users[\\/]<u>`` home prefixes, plus the ``head`` /
        # ``tail`` reading verbs (cat is not the only way to leak a private
        # key). Linux ``/home/<u>/`` continues to match.
        pattern=re.compile(
            r"\b(?:cat|head|tail)\s+"
            r"(?:~|\$HOME|/home/[^/\s]+|/Users/[^/\s]+"
            r"|[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)?[\\/]?\.ssh[\\/]"
            r"(?:id_[a-z0-9]+(?!\.pub)\b|authorized_keys)"
        ),
        message="Reading SSH private key / authorized_keys — denied.",
    ),
    DenyRule(
        rule_id="C4.2-cat-aws-credentials",
        category="exfiltration",
        # Extended to cover macOS ``/Users/<u>/`` and Windows
        # ``[A-Za-z]:[\\/]Users[\\/]<u>`` home prefixes.
        pattern=re.compile(
            r"\b(?:cat|head|tail)\s+"
            r"(?:~|\$HOME|/root|/home/[^/\s]+|/Users/[^/\s]+"
            r"|[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)?[\\/]?\.aws[\\/]"
            r"(?:credentials|config)\b"
        ),
        message="Reading AWS credentials — denied.",
    ),
    DenyRule(
        rule_id="C4.3-cat-credential-dotfile",
        category="exfiltration",
        # Extended to cover macOS ``/Users/<u>/`` and Windows
        # ``[A-Za-z]:[\\/]Users[\\/]<u>`` home prefixes. Also extended the
        # suffix alternation to include ``gnupg/<file>`` — the gnupg
        # credential directory was previously only caught by C4.6 (scp).
        pattern=re.compile(
            r"\b(?:cat|head|tail)\s+"
            r"(?:~|\$HOME|/home/[^/\s]+|/Users/[^/\s]+"
            r"|[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)?[\\/]?"
            r"\.(?:netrc|pgpass|docker/config\.json|kube/config|gnupg/\S+)"
        ),
        message="Reading a credential dotfile — denied.",
    ),
    DenyRule(
        rule_id="C4.4-cat-env-file",
        category="exfiltration",
        pattern=re.compile(r"\bcat\s+\.env(?:\.[a-z]+)?\b"),
        message="Reading a .env file — denied.",
    ),
    DenyRule(
        rule_id="C4.5-curl-data-home-file",
        category="exfiltration",
        # curl/wget/nc with -d / --data[-binary|-raw] @<home file>.
        pattern=re.compile(
            r"\b(?:curl|wget|nc|ncat)\s+"
            r"(?:[^|]*?\s)?"
            r"(?:--data(?:[- ](?:binary|raw))?|-d)[= ]?"
            r"\s*@(?:~|\$HOME|/home)"
        ),
        message="curl/wget --data @<home file> — data exfiltration denied.",
    ),
    DenyRule(
        rule_id="C4.6-scp-credential-dir",
        category="exfiltration",
        # scp/rsync/sftp touching .ssh/.aws/.gnupg anywhere in the cmdline.
        # Extended to cover macOS ``/Users/<u>/`` and Windows
        # ``[A-Za-z]:[\\/]Users[\\/]<u>`` home prefixes.
        pattern=re.compile(
            r"\b(?:scp|rsync|sftp)\s+.*"
            r"(?:~|\$HOME|/home/[^/\s]+|/Users/[^/\s]+"
            r"|[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)?[\\/]?"
            r"\.(?:ssh|aws|gnupg)(?:[\\/]|\b)"
        ),
        message="scp/rsync/sftp of credential directory — denied.",
    ),
    DenyRule(
        rule_id="C4.7-nc-send-key",
        category="exfiltration",
        pattern=re.compile(
            r"\b(?:nc|ncat)\s+\S+\s+\d+\s*<\s*[^\s|;&]*\."
            r"(?:ssh|aws|env|pem|key)\b|"
            r"\b(?:nc|ncat)\s+.*<\s*[^\s|;&]*(?:/|\.)\S*"
            r"(?:ssh|aws|env|pem|key|id_rsa|id_ed25519|credentials)"
        ),
        message="nc/ncat piping a credential file over the network — denied.",
    ),
)


# ---------------------------------------------------------------------------
# C7 system-integrity (8 DENY)
# ---------------------------------------------------------------------------


_C7_RULES: tuple[DenyRule, ...] = (
    DenyRule(
        rule_id="C7.1-chmod-recursive-777",
        category="system-integrity",
        pattern=re.compile(r"\bchmod\s+-R\s+777\s+/(?!tmp)"),
        message="chmod -R 777 on system paths — denied.",
    ),
    DenyRule(
        rule_id="C7.2-chown-recursive-root",
        category="system-integrity",
        pattern=re.compile(r"\bchown\s+-R\s+\S+\s+/(?:\s|$)"),
        message="chown -R on / — denied.",
    ),
    DenyRule(
        rule_id="C7.3-crontab-remove",
        category="system-integrity",
        pattern=re.compile(r"\bcrontab\s+-r\b"),
        message="crontab -r wipes the crontab — denied.",
    ),
    DenyRule(
        rule_id="C7.4-fork-bomb",
        category="system-integrity",
        pattern=re.compile(r":\s*\(\s*\)\s*\{.*:\s*\|\s*:.*\}"),
        message="Fork bomb detected — denied.",
    ),
    DenyRule(
        rule_id="C7.5-firewall-flush",
        category="system-integrity",
        pattern=re.compile(r"\biptables\s+-F\b|\bufw\s+(?:disable|reset)\b"),
        message="Firewall flush/disable — denied.",
    ),
    DenyRule(
        rule_id="C7.6-disable-security-service",
        category="system-integrity",
        pattern=re.compile(
            r"\bsystemctl\s+(?:disable|stop|mask)\s+"
            r"(?:ssh|sshd|auditd|firewalld)\b"
        ),
        message="Disabling/stopping a security service — denied.",
    ),
    DenyRule(
        rule_id="C7.7-purge-python-minimal",
        category="system-integrity",
        pattern=re.compile(r"\bapt(?:-get)?\s+(?:purge|remove)\s+.*python[0-9.]*-minimal\b"),
        message="apt purge of python*-minimal breaks the OS — denied.",
    ),
    DenyRule(
        rule_id="C7.8-shutdown",
        category="system-integrity",
        pattern=re.compile(r"\b(?:halt|poweroff|shutdown|reboot|init\s+0)\b"),
        message="Shutdown/reboot command — denied.",
    ),
)


DEFAULT_DENY_PATTERNS: tuple[DenyRule, ...] = (
    _C1_RULES + _C2_RULES + _C3_RULES + _C4_RULES + _C7_RULES
)


# ---------------------------------------------------------------------------
# C5 priv-escalation (7 WARN)
# ---------------------------------------------------------------------------


_C5_RULES: tuple[DenyRule, ...] = (
    DenyRule(
        rule_id="C5.1-sudo-default",
        category="priv-escalation",
        pattern=re.compile(r"^\s*sudo\s+(?!(?:-n\s+)?(?:-l\b|--list\b))"),
        message="sudo privilege escalation.",
    ),
    DenyRule(
        rule_id="C5.2-su-root",
        category="priv-escalation",
        pattern=re.compile(r"^\s*su\s+(?:-|root|-\s+root)"),
        message="su to root.",
    ),
    DenyRule(
        rule_id="C5.3-write-sudoers",
        category="priv-escalation",
        pattern=re.compile(r">>?\s*/etc/sudoers(?:\.d/|$|\s)"),
        message="Writing to /etc/sudoers.",
    ),
    DenyRule(
        rule_id="C5.4-chmod-setuid",
        category="priv-escalation",
        pattern=re.compile(r"\bchmod\s+[ug]\+s\b"),
        message="chmod setuid/setgid bit.",
    ),
    DenyRule(
        rule_id="C5.5-append-authorized-keys",
        category="priv-escalation",
        # Extended to cover macOS ``/Users/<u>/`` and Windows
        # ``[A-Za-z]:[\\/]Users[\\/]<u>`` home prefixes.
        pattern=re.compile(
            r">>?\s*"
            r"(?:~|\$HOME|/home/[^/\s]+|/Users/[^/\s]+"
            r"|[A-Za-z]:[\\/]Users[\\/][^\\/\s]+)?[\\/]?"
            r"\.ssh[\\/]authorized_keys"
        ),
        message="Writing to ~/.ssh/authorized_keys.",
    ),
    DenyRule(
        rule_id="C5.6-write-passwd-shadow",
        category="priv-escalation",
        pattern=re.compile(r">>?\s*/etc/(?:passwd|shadow|group|gshadow)\b"),
        message="Writing to /etc/passwd|shadow|group|gshadow.",
    ),
    DenyRule(
        rule_id="C5.7-usermod-priv-group",
        category="priv-escalation",
        pattern=re.compile(r"\bvisudo\b|\busermod\s+-[aA]G\s+(?:sudo|wheel|admin)\b"),
        message="usermod adding user to privileged group.",
    ),
)


# ---------------------------------------------------------------------------
# C6 shell-escape (8 WARN)
#
# Ambiguity #4 locked: C6.6 covers ONLY
#   U+00A0, U+2000-U+200F, U+2028-U+202F, U+FF01-U+FF5E.
# Cyrillic is a documented blind spot.
# ---------------------------------------------------------------------------


_C6_RULES: tuple[DenyRule, ...] = (
    DenyRule(
        rule_id="C6.1-eval",
        category="shell-escape",
        pattern=re.compile(r"\beval\s+"),
        message="eval hides the real command.",
    ),
    DenyRule(
        rule_id="C6.2-base64-decode",
        category="shell-escape",
        pattern=re.compile(
            r"\bbase64\s+(?:-d|--decode)\b[^\n]*\|\s*"
            r"(?:sh\b|bash\b|eval\b)"
        ),
        message="base64 decode piped to shell/eval — encoded payload.",
    ),
    DenyRule(
        rule_id="C6.3-ifs-bypass",
        category="shell-escape",
        # Covers $IFS, $IFS$9, ${IFS}.
        pattern=re.compile(r"\$(?:IFS(?:\$[0-9])?|\{IFS\})"),
        message="IFS bypass — space-substitution obfuscation.",
    ),
    DenyRule(
        rule_id="C6.4-brace-expansion",
        category="shell-escape",
        pattern=re.compile(r"\{[a-zA-Z]+,[/-]"),
        message="Brace-expansion command — obfuscation.",
    ),
    DenyRule(
        rule_id="C6.5-wildcard-path",
        category="shell-escape",
        pattern=re.compile(r"/\?{2,}/|/\*/"),
        message="Wildcard in command path — evasion.",
    ),
    DenyRule(
        rule_id="C6.6-unicode-lookalike",
        category="shell-escape",
        pattern=re.compile("[\u00a0\u2000-\u200f\u2028-\u202f\uff01-\uff5e]"),
        message="Unicode lookalike character in command.",
    ),
    DenyRule(
        rule_id="C6.7-alias-function-redef",
        category="shell-escape",
        pattern=re.compile(r"\balias\s+\w+=|\b\w+\s*\(\s*\)\s*\{"),
        message="Alias or function redefines a builtin.",
    ),
    DenyRule(
        rule_id="C6.8-newline-escape",
        category="shell-escape",
        pattern=re.compile(r"\\\n"),
        message="Backslash-newline continuation inside command.",
    ),
)


DEFAULT_WARN_PATTERNS: tuple[DenyRule, ...] = _C5_RULES + _C6_RULES
