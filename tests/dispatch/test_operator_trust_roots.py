# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: only the operator decides which directories may speak to the agent.

``bonfire.dispatch.sdk_backend._resolve_setting_sources(cwd)`` returns
``["project"]`` (load the directory's ``CLAUDE.md`` and ``.claude/``) or ``[]``.

1. ``BONFIRE_TRUST_PROJECT_SETTINGS`` exactly ``"1"`` -> ``["project"]`` for any
   cwd, including empty/``None``. ``"true"``, ``"yes"``, ``"0"`` have no effect.
2. Otherwise the cwd is ``Path(cwd or os.getcwd()).resolve()``. An empty or
   ``None`` cwd is the process cwd, judged like any other (no free trust).
3. ``BONFIRE_TRUST_ROOTS`` is an ``os.pathsep``-separated list. Empty components
   are skipped, absolute components are resolved (realpath). A non-absolute
   component (``.``, ``rel/dir``, ``~``) is ignored and logs a WARNING carrying
   the code ``trust_root_not_absolute``.
4. Trusted iff the resolved cwd equals a resolved root or is inside it by path
   components (``/x/root-evil`` is not inside ``/x/root``).
5. Roots unset, empty or all-relative -> nothing is trusted. Fail closed.
6. The cwd's own ``bonfire.toml`` is never a trust signal. When it carries
   ``[bonfire] trust_project_settings = true`` (literal bool) and the result is
   ``[]``, a WARNING carrying ``trust_toml_ignored`` and ``BONFIRE_TRUST_ROOTS``
   is logged. ``false``, a missing key, the string ``"true"`` or no file log
   nothing of the kind.
7. Each call returns a fresh list.

There is no explicit caller list in this package: ``DispatchOptions`` has no
``setting_sources`` field, so only the env hatch is pinned here.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest

from bonfire.dispatch.sdk_backend import _resolve_setting_sources

TOML_TRUE = "[bonfire]\ntrust_project_settings = true\n"


@pytest.fixture(autouse=True)
def _scrub_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BONFIRE_TRUST_PROJECT_SETTINGS", raising=False)
    monkeypatch.delenv("BONFIRE_TRUST_ROOTS", raising=False)


def _foreign(parent: Path, name: str = "foreign", toml: str | None = TOML_TRUE) -> Path:
    """A directory shaped like a cloned repository carrying its own opt-in."""
    d = parent / name
    d.mkdir(parents=True)
    (d / ".git").mkdir()
    (d / ".claude").mkdir()
    (d / ".claude" / "settings.json").write_text("{}\n")
    if toml is not None:
        (d / "bonfire.toml").write_text(toml)
    return d


def _codes(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]


def _has(caplog: pytest.LogCaptureFixture, code: str) -> bool:
    return any(code in m for m in _codes(caplog))


class TestForeignDirIsNotTrusted:
    def test_own_toml_and_settings_do_not_trust(self, tmp_path: Path) -> None:
        """R1: a foreign repo with its own opt-in and roots unset -> ``[]``."""
        foreign = _foreign(tmp_path)
        assert _resolve_setting_sources(str(foreign)) == []

    def test_empty_roots_value_trusts_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", "")
        assert _resolve_setting_sources(str(_foreign(tmp_path))) == []

    def test_only_separators_trusts_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", os.pathsep * 3)
        assert _resolve_setting_sources(str(_foreign(tmp_path))) == []


class TestRootsTrust:
    def test_dir_in_roots_without_toml_is_trusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R2: a root needs no toml at all."""
        d = _foreign(tmp_path, toml=None)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(d))
        assert _resolve_setting_sources(str(d)) == ["project"]

    def test_subdir_of_root_is_trusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _foreign(tmp_path, "root", toml=None)
        sub = root / "a" / "b"
        sub.mkdir(parents=True)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(root))
        assert _resolve_setting_sources(str(sub)) == ["project"]

    def test_second_root_in_list_works(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        one = _foreign(tmp_path, "one", toml=None)
        two = _foreign(tmp_path, "two", toml=None)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", os.pathsep.join([str(one), str(two)]))
        assert _resolve_setting_sources(str(two)) == ["project"]
        assert _resolve_setting_sources(str(one)) == ["project"]

    def test_empty_components_are_skipped(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        d = _foreign(tmp_path, toml=None)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", os.pathsep.join(["", str(d), ""]))
        assert _resolve_setting_sources(str(d)) == ["project"]

    def test_trust_is_by_path_components_not_string_prefix(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R3: ``root-evil`` is not inside ``root``."""
        (tmp_path / "root").mkdir()
        evil = _foreign(tmp_path, "root-evil")
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(tmp_path / "root"))
        assert _resolve_setting_sources(str(evil)) == []

    def test_parent_of_root_is_not_trusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "outer" / "root"
        root.mkdir(parents=True)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(root))
        assert _resolve_setting_sources(str(tmp_path / "outer")) == []

    def test_fresh_list_each_call(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(tmp_path))
        a = _resolve_setting_sources(str(tmp_path))
        b = _resolve_setting_sources(str(tmp_path))
        assert a == b == ["project"]
        assert a is not b


class TestSymlinksJudgedByRealpath:
    def test_link_outside_roots_pointing_into_root_is_trusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R4a."""
        root = tmp_path / "root"
        (root / "inner").mkdir(parents=True)
        outside = tmp_path / "elsewhere"
        outside.mkdir()
        link = outside / "link"
        link.symlink_to(root / "inner", target_is_directory=True)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(root))
        assert _resolve_setting_sources(str(link)) == ["project"]

    def test_link_inside_root_pointing_out_is_not_trusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R4b: a symlink inside a root cannot smuggle a foreign dir in."""
        root = tmp_path / "root"
        root.mkdir()
        foreign = _foreign(tmp_path / "far")
        link = root / "door"
        link.symlink_to(foreign, target_is_directory=True)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(root))
        assert _resolve_setting_sources(str(link)) == []

    def test_root_given_as_symlink_trusts_its_real_target(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R4c."""
        real = tmp_path / "real"
        real.mkdir()
        link = tmp_path / "rootlink"
        link.symlink_to(real, target_is_directory=True)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(link))
        assert _resolve_setting_sources(str(real)) == ["project"]


class TestRelativeRootsIgnored:
    @pytest.mark.parametrize("spec", [".", "rel/dir", "~"])
    def test_relative_root_trusts_nothing_and_warns(
        self,
        spec: str,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """R5: the process cwd is the relative root's target; still ``[]``."""
        d = tmp_path / "rel" / "dir"
        d.mkdir(parents=True)
        monkeypatch.chdir(d)
        monkeypatch.setenv("HOME", str(d))
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", spec)
        caplog.set_level(logging.WARNING)
        assert _resolve_setting_sources(str(d)) == []
        assert _resolve_setting_sources(None) == []
        assert _has(caplog, "trust_root_not_absolute")

    def test_absolute_root_beside_relative_one_still_trusts(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        d = _foreign(tmp_path, toml=None)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", os.pathsep.join([".", str(d)]))
        caplog.set_level(logging.WARNING)
        assert _resolve_setting_sources(str(d)) == ["project"]
        assert _has(caplog, "trust_root_not_absolute")

    def test_absolute_roots_do_not_warn_about_absoluteness(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(tmp_path))
        caplog.set_level(logging.WARNING)
        assert _resolve_setting_sources(str(tmp_path)) == ["project"]
        assert not _has(caplog, "trust_root_not_absolute")


class TestTomlIsNeverASignal:
    def test_true_toml_untrusted_logs_the_ignore_code(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """R6."""
        caplog.set_level(logging.WARNING)
        assert _resolve_setting_sources(str(_foreign(tmp_path))) == []
        msgs = [m for m in _codes(caplog) if "trust_toml_ignored" in m]
        assert msgs, "an ignored opt-in must be surfaced to the operator"
        assert any("BONFIRE_TRUST_ROOTS" in m for m in msgs)

    @pytest.mark.parametrize(
        "toml",
        [
            "[bonfire]\ntrust_project_settings = false\n",
            "[bonfire]\n",
            '[bonfire]\ntrust_project_settings = "true"\n',
            None,
        ],
        ids=["false", "missing-key", "string-true", "no-file"],
    )
    def test_non_literal_true_logs_nothing(
        self, toml: str | None, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        caplog.set_level(logging.WARNING)
        assert _resolve_setting_sources(str(_foreign(tmp_path, toml=toml))) == []
        assert not _has(caplog, "trust_toml_ignored")


class TestEnvHatch:
    def test_one_trusts_foreign_and_empty_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R8."""
        foreign = _foreign(tmp_path, toml=None)
        monkeypatch.setenv("BONFIRE_TRUST_PROJECT_SETTINGS", "1")
        assert _resolve_setting_sources(str(foreign)) == ["project"]
        assert _resolve_setting_sources("") == ["project"]
        assert _resolve_setting_sources(None) == ["project"]

    @pytest.mark.parametrize("value", ["true", "yes", "0"])
    def test_other_values_have_no_effect(
        self, value: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BONFIRE_TRUST_PROJECT_SETTINGS", value)
        assert _resolve_setting_sources(str(_foreign(tmp_path, toml=None))) == []


class TestEmptyCwdJudgedByRoots:
    def test_unset_roots_empty_and_none_cwd_untrusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """R9."""
        foreign = _foreign(tmp_path, toml=None)
        monkeypatch.chdir(foreign)
        assert _resolve_setting_sources("") == []
        assert _resolve_setting_sources(None) == []

    def test_process_cwd_under_a_root_is_trusted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        foreign = _foreign(tmp_path, toml=None)
        monkeypatch.chdir(foreign)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(foreign))
        assert _resolve_setting_sources("") == ["project"]
        assert _resolve_setting_sources(None) == ["project"]


class TestIntegrationShape:
    def test_untrusted_cwd_with_true_toml_is_empty_and_logged(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """R10."""
        foreign = _foreign(tmp_path)
        monkeypatch.chdir(foreign)
        caplog.set_level(logging.WARNING)
        assert _resolve_setting_sources(str(foreign)) == []
        assert _has(caplog, "trust_toml_ignored")


def _capture_argv(cwd: Path) -> list[str]:
    """Run the real backend, capture the real options, build the real CLI argv."""
    import asyncio
    from unittest.mock import patch

    from claude_agent_sdk._internal.transport.subprocess_cli import SubprocessCLITransport

    from bonfire.dispatch.sdk_backend import ClaudeSDKBackend
    from bonfire.models.envelope import Envelope
    from bonfire.protocols import DispatchOptions

    seen: list[Any] = []

    async def _query(*, prompt: str = "", options: Any = None):  # type: ignore[no-untyped-def]
        seen.append(options)
        if False:  # pragma: no cover
            yield None

    envelope = Envelope(task="t", agent_name="warrior-agent", model="claude-opus-4-7")
    with patch("bonfire.dispatch.sdk_backend.query", _query):
        asyncio.run(
            ClaudeSDKBackend().execute(envelope, options=DispatchOptions(cwd=str(cwd), tools=[]))
        )
    assert seen, "the backend never reached the SDK"
    transport = SubprocessCLITransport(prompt="x", options=seen[0])
    transport._cli_path = "/fake/claude"
    return transport._build_command()


class TestArgvViaSdkTransport:
    def test_untrusted_dir_gets_empty_setting_sources_flag(self, tmp_path: Path) -> None:
        """R7: ``--setting-sources=`` present and empty; a missing flag means CLI defaults."""
        argv = _capture_argv(_foreign(tmp_path))
        flags = [a for a in argv if a.startswith("--setting-sources")]
        assert flags, f"no --setting-sources token at all (CLI defaults load project): {argv!r}"
        assert "--setting-sources=" in argv
        assert "--setting-sources=project" not in argv

    def test_trusted_dir_gets_project_flag(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        foreign = _foreign(tmp_path)
        monkeypatch.setenv("BONFIRE_TRUST_ROOTS", str(tmp_path))
        assert "--setting-sources=project" in _capture_argv(foreign)
