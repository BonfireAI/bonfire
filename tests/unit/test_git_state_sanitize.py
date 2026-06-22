"""RED tests for bonfire.onboard.scanners.git_state.sanitize_remote_url — BON-912.

Wave-2 leak hardening. Surfaced by the Mirror Path B production-1 run on
2026-05-07 (Security Scout, finding #7).

git remote URLs end up persisted in ``bonfire.toml`` (``[bonfire.git] remote``).
Credential leakage on commit is the failure mode. The current ``sanitize_remote_url``
uses a five-step ``re.sub`` chain that handles only:

  * ``https://user:token@host``
  * ``http://token@host``
  * ``git@host:path``
  * ``ssh://git@host``
  * plain ``https://host``

It does NOT strip:

  * Query-string credentials (``https://github.com/org/repo.git?token=foo``)
  * Port-with-userinfo edge cases (``https://user@host:port/``)
  * The GitHub Apps ``x-access-token:GHSA...@github.com`` credential-helper shape

These tests pin the intended post-fix behaviour: every credential-bearing
shape is stripped, and the host/path normalisation already covered stays
intact (regression guard). The fix (per AC) replaces the regex chain with a
structured ``urllib.parse.urlsplit`` parser.

RED expectation: the query-string, port-with-userinfo, and GHSA-token cases
fail against the current regex-chain implementation — the secret survives
into the returned string.
"""

from __future__ import annotations

import pytest

from bonfire.onboard.scanners.git_state import sanitize_remote_url

# ---------------------------------------------------------------------------
# Credential-bearing URL matrix — every shape must come out with NO secret.
# ---------------------------------------------------------------------------

# Each tuple: (raw_url, expected_sanitized, secret_substring_that_must_not_leak)
_CREDENTIAL_URLS = [
    # --- shapes the current regex chain ALREADY handles (regression guard) ---
    (
        "https://user:ghp_abc123@github.com/org/repo.git",
        "github.com/org/repo",
        "ghp_abc123",
    ),
    (
        "http://ghp_tokenonly@github.com/org/repo.git",
        "github.com/org/repo",
        "ghp_tokenonly",
    ),
    (
        "ssh://git@github.com/org/repo.git",
        "github.com/org/repo",
        # no real secret here, but the userinfo must still be gone
        "git@",
    ),
    # --- shapes the current regex chain MISSES (the BON-912 leak) ---
    # Query-string credential.
    (
        "https://github.com/org/repo.git?token=qstring_secret",
        "github.com/org/repo",
        "qstring_secret",
    ),
    # Query-string credential on an already-suffix-stripped URL.
    (
        "https://github.com/org/repo?access_token=qs_token_2",
        "github.com/org/repo",
        "qs_token_2",
    ),
    # Port-with-userinfo: username only, explicit port.
    (
        "https://portuser@git.example.com:8443/org/repo.git",
        "git.example.com:8443/org/repo",
        "portuser",
    ),
    # Port-with-userinfo: username:password, explicit port.
    (
        "https://puser:ppw_secret@git.example.com:8443/org/repo.git",
        "git.example.com:8443/org/repo",
        "ppw_secret",
    ),
    # GitHub Apps credential-helper shape: x-access-token:GHSA...@host.
    (
        "https://x-access-token:GHSA_abcDEF123token@github.com/org/repo.git",
        "github.com/org/repo",
        "GHSA_abcDEF123token",
    ),
    # GitHub Apps shape without explicit username component.
    (
        "https://ghs_appinstalltoken@github.com/org/repo.git",
        "github.com/org/repo",
        "ghs_appinstalltoken",
    ),
    # Combined: userinfo AND query-string credential on the same URL.
    (
        "https://baduser:badpw@github.com/org/repo.git?token=also_secret",
        "github.com/org/repo",
        "badpw",
    ),
]


@pytest.mark.parametrize(
    ("raw_url", "expected", "secret"),
    _CREDENTIAL_URLS,
    ids=[
        "https_basic_auth",
        "http_token_only",
        "ssh_userinfo",
        "query_string_token",
        "query_string_token_no_suffix",
        "port_with_username",
        "port_with_user_password",
        "ghsa_x_access_token",
        "ghsa_token_only",
        "userinfo_and_query_string",
    ],
)
def test_sanitize_strips_all_credential_shapes(raw_url: str, expected: str, secret: str) -> None:
    """Every credential-bearing URL shape is normalised with NO secret leaked."""
    result = sanitize_remote_url(raw_url)

    assert secret not in result, (
        f"sanitize_remote_url({raw_url!r}) -> {result!r} still contains "
        f"the credential substring {secret!r} — it would be committed into bonfire.toml"
    )
    assert result == expected, (
        f"sanitize_remote_url({raw_url!r}) -> {result!r}, expected {expected!r}"
    )


def test_sanitize_strips_query_string_entirely() -> None:
    """A query string is dropped wholesale — no ``?`` survives into the output.

    The persisted ``remote`` field is a host/path identifier, not a fetch URL;
    a surviving ``?`` is both a credential-leak vector and a normalisation bug.
    """
    result = sanitize_remote_url("https://github.com/org/repo.git?token=leaky")
    assert "?" not in result, f"query string survived sanitisation: {result!r}"
    assert result == "github.com/org/repo"


def test_sanitize_no_credentials_is_unchanged() -> None:
    """A clean URL with no credentials still normalises correctly (regression guard)."""
    assert sanitize_remote_url("https://github.com/org/repo.git") == "github.com/org/repo"
    assert sanitize_remote_url("git@github.com:org/repo.git") == "github.com/org/repo"
