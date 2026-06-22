# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED contract tests — W5.E third-party ``CLAUDE.md`` allow-list gate.

The Scout-ratified design (Option D) replaces the hardcoded
``setting_sources=["project"]`` at ``src/bonfire/dispatch/sdk_backend.py``
with a resolver that DENIES project-settings ingestion by default and only
opts in when ONE of the following holds:

1. The dispatch ``cwd`` is empty / ``None`` (the operator dispatched from
   *inside* the bonfire-public tree itself — dogfood ergonomics).
2. The dispatch ``cwd`` contains a co-located ``bonfire.toml`` (the project
   has signaled it is Bonfire-aware).
3. The operator has set ``BONFIRE_TRUST_PROJECT_SETTINGS=1`` in the
   environment (explicit acknowledgement that ingesting a foreign repo's
   ``CLAUDE.md`` / ``.claude/`` settings is intentional).

Default behavior: DENY — ``_resolve_setting_sources`` returns ``[]`` for any
``cwd`` that is a foreign repo with no ``bonfire.toml`` and no opt-in env
override. This stops the SDK from silently lifting a third-party repo's
``CLAUDE.md`` into the dispatched agent's system prompt.

Surface under test:

- ``bonfire.dispatch.sdk_backend._resolve_setting_sources`` — new module-level
  helper, signature ``(cwd: str | None) -> list[str]``.
- ``ClaudeSDKBackend`` ``_do_execute`` — must thread the resolver output into
  ``ClaudeAgentOptions(..., setting_sources=_resolve_setting_sources(options.cwd), ...)``
  instead of the hardcoded ``["project"]``.

Truth table the Warrior must satisfy:

| cwd                                  | bonfire.toml? | env var      | result        |
|--------------------------------------|---------------|--------------|---------------|
| ``""`` / ``None``                    | n/a           | n/a          | ``["project"]`` |
| ``<dir with bonfire.toml>``          | yes           | unset        | ``["project"]`` |
| ``<foreign dir>``                    | no            | unset        | ``[]``          |
| ``<foreign dir>``                    | no            | ``"1"``      | ``["project"]`` |
| ``<foreign dir>``                    | no            | ``"yes"``    | ``[]``          |
| ``<foreign dir>``                    | no            | ``"true"``   | ``[]``          |
| ``<foreign dir>``                    | no            | ``"0"``      | ``[]``          |
| ``<foreign dir with .git/ only>``    | no            | unset        | ``[]``          |

The env var contract is STRICT-``"1"``: any other truthy-looking value is
ignored. This keeps the override decision unambiguous and prevents accidental
opt-in via vague config templating.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from bonfire.models.envelope import Envelope
from bonfire.protocols import DispatchOptions

try:
    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    ClaudeSDKBackend = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module() -> None:
    """Fail every test while ``bonfire.dispatch.sdk_backend`` is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.sdk_backend not importable: {_IMPORT_ERROR}")


@pytest.fixture(autouse=True)
def _scrub_trust_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure ``BONFIRE_TRUST_PROJECT_SETTINGS`` is unset at test start.

    Each test that needs the override sets it explicitly via
    ``monkeypatch.setenv``. This guards against operator-side leakage of
    the override into the test runner.
    """
    monkeypatch.delenv("BONFIRE_TRUST_PROJECT_SETTINGS", raising=False)


# ---------------------------------------------------------------------------
# Helpers — capture ``ClaudeAgentOptions`` kwargs; stub async ``query``
# ---------------------------------------------------------------------------


def _make_capture() -> tuple[dict[str, Any], type]:
    """Return ``(captured_kwargs_dict, FakeClaudeAgentOptions)`` pair."""
    captured: dict[str, Any] = {}

    class _FakeClaudeAgentOptions:
        def __init__(self, **kwargs: Any) -> None:
            captured.update(kwargs)
            for k, v in kwargs.items():
                setattr(self, k, v)

    return captured, _FakeClaudeAgentOptions


async def _empty_query(*, prompt: str = "", options: Any = None):  # type: ignore[no-untyped-def]
    """Async-gen that yields nothing — closes immediately."""
    if False:  # pragma: no cover
        yield None


def _envelope(agent: str = "warrior-agent") -> Envelope:
    return Envelope(task="do work", agent_name=agent, model="claude-opus-4-7")


# ===========================================================================
# 1. Helper surface — ``_resolve_setting_sources`` directly
# ===========================================================================


class TestResolveSettingSourcesHelper:
    """Direct tests for the new module-level resolver.

    The helper is the single seat of policy. Its truth table IS the gate.
    """

    def test_foreign_repo_without_bonfire_toml_returns_empty(
        self,
        tmp_path: Path,
    ) -> None:
        """Default-DENY: foreign cwd with NO ``bonfire.toml`` → ``[]``."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        # Foreign repo — no bonfire.toml present.
        # (Drop a CLAUDE.md so the directory is visibly a "foreign" repo
        # that would otherwise leak its settings.)
        (tmp_path / "CLAUDE.md").write_text("# Foreign repo CLAUDE.md\n")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], (
            "Default-DENY: foreign cwd without ``bonfire.toml`` MUST return "
            f"``[]`` to prevent third-party CLAUDE.md ingestion. Got {result!r}."
        )

    def test_co_located_bonfire_toml_returns_project(self, tmp_path: Path) -> None:
        """Project signal: ``bonfire.toml`` with explicit opt-in → ``["project"]``.

        BON-1043 tightened the gate: file presence ALONE is no longer
        sufficient — the TOML must carry the explicit
        ``[bonfire].trust_project_settings = true`` opt-in. See
        ``tests/dispatch/test_trust_project_settings_key.py`` for the
        BON-1043 contract surface.
        """
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("[bonfire]\ntrust_project_settings = true\n")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == ["project"], (
            "Co-located ``bonfire.toml`` with explicit "
            "``trust_project_settings = true`` is the opt-in signal; "
            f"resolver MUST return ``['project']``. Got {result!r}."
        )

    def test_env_override_returns_project(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Env override: ``BONFIRE_TRUST_PROJECT_SETTINGS=1`` → ``["project"]``."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        # Foreign repo — no bonfire.toml — but operator opted in via env.
        monkeypatch.setenv("BONFIRE_TRUST_PROJECT_SETTINGS", "1")
        result = _resolve_setting_sources(str(tmp_path))
        assert result == ["project"], (
            "``BONFIRE_TRUST_PROJECT_SETTINGS=1`` is the explicit operator "
            f"override; resolver MUST return ``['project']``. Got {result!r}."
        )

    def test_empty_cwd_returns_project(self) -> None:
        """Empty ``cwd`` is the dogfood ergonomics path → ``["project"]``."""
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        # Empty string — caller dispatched from inside bonfire-public itself,
        # where the SDK falls back to the runner's actual cwd. That is by
        # design the Bonfire-aware tree.
        assert _resolve_setting_sources("") == ["project"]
        # ``None`` — same semantic; sdk_backend passes ``options.cwd or None``.
        assert _resolve_setting_sources(None) == ["project"]

    def test_env_override_value_other_than_1_does_not_trust(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Strict ``"1"`` match: ``"yes"``, ``"true"``, ``"0"`` MUST NOT trust.

        Prevents accidental opt-in via vague env templating (e.g. a CI runner
        helpfully sets ``BONFIRE_TRUST_PROJECT_SETTINGS=true`` and silently
        re-enables third-party ingestion).
        """
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        # Foreign repo — no bonfire.toml.
        (tmp_path / "CLAUDE.md").write_text("# Foreign\n")

        for value in ("yes", "true", "TRUE", "True", "0", "", " 1 ", "1\n"):
            monkeypatch.setenv("BONFIRE_TRUST_PROJECT_SETTINGS", value)
            result = _resolve_setting_sources(str(tmp_path))
            assert result == [], (
                f'Strict-``"1"`` lock: env value {value!r} MUST NOT enable trust. Got {result!r}.'
            )

    def test_foreign_repo_with_dotgit_but_no_bonfire_toml_still_denied(
        self,
        tmp_path: Path,
    ) -> None:
        """Bonus negative: ``.git/`` is NOT a Bonfire-awareness signal.

        Only ``bonfire.toml`` (or the env override) opts in. A foreign repo
        that happens to be a git repo still defaults to DENY.
        """
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / ".git").mkdir()
        (tmp_path / "CLAUDE.md").write_text("# Foreign git repo\n")
        # No bonfire.toml.
        result = _resolve_setting_sources(str(tmp_path))
        assert result == [], (
            "``.git/`` directory is NOT a Bonfire opt-in signal; only "
            f"``bonfire.toml`` is. Got {result!r}."
        )

    def test_resolver_returns_fresh_list_each_call(self, tmp_path: Path) -> None:
        """Each call returns an independent list — no shared-mutable state.

        Fixture updated for BON-1043: file presence alone no longer trusts;
        the explicit ``trust_project_settings = true`` key is required.
        """
        from bonfire.dispatch.sdk_backend import _resolve_setting_sources

        (tmp_path / "bonfire.toml").write_text("[bonfire]\ntrust_project_settings = true\n")
        a = _resolve_setting_sources(str(tmp_path))
        b = _resolve_setting_sources(str(tmp_path))
        assert a == b == ["project"]
        assert a is not b, "Resolver MUST return a fresh list each call."


# ===========================================================================
# 2. End-to-end wiring — resolver output reaches ``ClaudeAgentOptions``
# ===========================================================================


class TestSdkBackendUsesResolver:
    """``_do_execute`` MUST plumb resolver output into ``ClaudeAgentOptions``.

    These tests use the same fake-options capture pattern as
    ``test_sdk_backend_tool_presence.py`` and ``test_sdk_backend_hooks_wiring.py``.
    """

    async def test_sdk_backend_passes_resolved_setting_sources_for_foreign_cwd(
        self,
        tmp_path: Path,
    ) -> None:
        """Foreign cwd → captured ``setting_sources == []``.

        Replaces the hardcoded ``["project"]`` previously asserted by
        ``test_setting_sources_preserved`` in ``test_sdk_backend_tool_presence.py``
        for the default-DENY case.
        """
        captured, FakeOptions = _make_capture()

        # Foreign cwd — no bonfire.toml.
        foreign = tmp_path / "foreign"
        foreign.mkdir()
        (foreign / "CLAUDE.md").write_text("# Foreign repo\n")

        with (
            patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
            patch("bonfire.dispatch.sdk_backend.query", _empty_query),
        ):
            backend = ClaudeSDKBackend()
            options = DispatchOptions(cwd=str(foreign), tools=["Read"])
            await backend.execute(_envelope(), options=options)

        assert "setting_sources" in captured, (
            "``ClaudeAgentOptions`` MUST still receive a ``setting_sources`` kwarg."
        )
        assert captured["setting_sources"] == [], (
            "Foreign cwd MUST resolve to ``[]`` at the SDK call site. "
            f"Got {captured['setting_sources']!r}."
        )

    async def test_sdk_backend_passes_project_when_co_located(
        self,
        tmp_path: Path,
    ) -> None:
        """Co-located ``bonfire.toml`` cwd → captured ``setting_sources == ["project"]``.

        Also pins that the resolver IS the source of the value — the
        ``["project"]`` result MUST come from a ``_resolve_setting_sources``
        invocation in ``_do_execute``, not from a leftover hardcode.
        """
        captured, FakeOptions = _make_capture()

        aware = tmp_path / "aware"
        aware.mkdir()
        (aware / "bonfire.toml").write_text("[bonfire]\n")

        resolver_calls: list[Any] = []

        # Wrap the (yet-to-exist) resolver so we observe an actual call.
        # If sdk_backend does not call ``_resolve_setting_sources``, the
        # patch target itself is missing and ``patch`` raises AttributeError.
        with patch(
            "bonfire.dispatch.sdk_backend._resolve_setting_sources",
            side_effect=lambda cwd: resolver_calls.append(cwd) or ["project"],
        ):
            with (
                patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
                patch("bonfire.dispatch.sdk_backend.query", _empty_query),
            ):
                backend = ClaudeSDKBackend()
                options = DispatchOptions(cwd=str(aware), tools=["Read"])
                await backend.execute(_envelope(), options=options)

        assert resolver_calls, (
            "``_do_execute`` MUST invoke ``_resolve_setting_sources`` (no "
            "leftover hardcoded ``setting_sources=['project']``)."
        )
        assert resolver_calls[0] == str(aware), (
            f"Resolver MUST receive the dispatch ``cwd`` verbatim. Got {resolver_calls[0]!r}."
        )
        assert captured["setting_sources"] == ["project"], (
            "Resolver output MUST be threaded into ``ClaudeAgentOptions``. "
            f"Got {captured['setting_sources']!r}."
        )

    async def test_sdk_backend_passes_project_when_env_override(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``BONFIRE_TRUST_PROJECT_SETTINGS=1`` cwd → captured ``["project"]``.

        Resolver invocation pinned: a hardcoded ``["project"]`` would not
        consult the env var, so the resolver MUST be the source of the value.
        """
        captured, FakeOptions = _make_capture()

        foreign = tmp_path / "foreign"
        foreign.mkdir()
        (foreign / "CLAUDE.md").write_text("# Foreign\n")
        monkeypatch.setenv("BONFIRE_TRUST_PROJECT_SETTINGS", "1")

        resolver_calls: list[Any] = []

        with patch(
            "bonfire.dispatch.sdk_backend._resolve_setting_sources",
            side_effect=lambda cwd: resolver_calls.append(cwd) or ["project"],
        ):
            with (
                patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
                patch("bonfire.dispatch.sdk_backend.query", _empty_query),
            ):
                backend = ClaudeSDKBackend()
                options = DispatchOptions(cwd=str(foreign), tools=["Read"])
                await backend.execute(_envelope(), options=options)

        assert resolver_calls, "``_do_execute`` MUST invoke ``_resolve_setting_sources``."
        assert captured["setting_sources"] == ["project"], (
            "Resolver output (env-overridden ``['project']``) MUST reach the "
            f"SDK call site. Got {captured['setting_sources']!r}."
        )

    async def test_sdk_backend_passes_project_for_empty_cwd(self) -> None:
        """Empty cwd (dogfood) → captured ``["project"]``.

        The dispatch path passes ``options.cwd or None`` to ``ClaudeAgentOptions``
        elsewhere, but the resolver receives ``options.cwd`` directly. The
        Warrior wires ``_resolve_setting_sources(options.cwd)`` — what the
        resolver sees is the raw ``options.cwd`` value (``""`` for default).
        """
        captured, FakeOptions = _make_capture()

        resolver_calls: list[Any] = []

        with patch(
            "bonfire.dispatch.sdk_backend._resolve_setting_sources",
            side_effect=lambda cwd: resolver_calls.append(cwd) or ["project"],
        ):
            with (
                patch("bonfire.dispatch.sdk_backend.ClaudeAgentOptions", FakeOptions),
                patch("bonfire.dispatch.sdk_backend.query", _empty_query),
            ):
                backend = ClaudeSDKBackend()
                # Default ``cwd=""`` preserves the bonfire-public dogfood path.
                options = DispatchOptions(tools=["Read"])
                await backend.execute(_envelope(), options=options)

        assert resolver_calls, (
            "``_do_execute`` MUST invoke ``_resolve_setting_sources`` even for "
            "the empty-cwd default case."
        )
        assert captured["setting_sources"] == ["project"], (
            "Empty ``cwd`` preserves the in-repo dogfood ergonomics; resolver "
            f"MUST yield ``['project']``. Got {captured['setting_sources']!r}."
        )
