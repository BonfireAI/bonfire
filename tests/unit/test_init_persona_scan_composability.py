# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Contract: ``bonfire init . && bonfire persona set <name> && bonfire scan`` composes.

The W7.M / PR #103 overwrite-defense (the ``_is_init_stub`` predicate at
``bonfire.onboard.config_generator``) currently returns True ONLY for
the exact byte-for-byte ``b"[bonfire]\\n"`` stub (modulo trailing
whitespace). ``bonfire persona set <name>`` runs between ``init`` and
``scan`` and mutates the stub to add a ``persona = "<name>"`` line under
``[bonfire]``. That single-key mutation falls out of stub recognition,
``scan`` refuses to overwrite, and the documented three-step flow
``bonfire init . && bonfire persona set falcor && bonfire scan`` exits
1 on step three.

This file pins the post-fix behavior. The narrow widening: ``_is_init_stub``
recognizes the ``init`` stub PLUS the exact output of ``persona set`` —
``[bonfire]\\npersona = "<escaped-name>"\\n`` — as still-a-stub. The
widening MUST NOT recognize any other single-key shape; the
``test_init_scan_composability.py`` neighbour file's test #15 already
pins that a hand-added ``name = "..."`` key keeps falling into the
overwrite refusal, and that pin must keep passing after the W8.F fix.

The Knight chose this narrow widening (persona-key-only) over the
broader "stub + at most one key" shape Anta floated, because the broader
shape would regress ``test_init_scan_composability.py::TestQuickstartIntegration::test_quickstart_full_flow_preserves_user_edits_after_init``
(test #15). Flagged in the W8.F Knight handoff for Ishtar's review.

Cross-lane note (OL-3): W8.G is touching ``config_generator.py`` in the
``[bonfire.tools]`` emitter region. These tests do NOT depend on
``[bonfire.tools]`` content. The fully-configured negative canary uses
hand-constructed TOML with no assumptions about tools-section emission.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app
from bonfire.onboard.config_generator import _is_init_stub

runner = CliRunner()


# The exact bytes ``bonfire persona set falcor`` produces when run
# immediately after ``bonfire init .``. Pinned here so a test fails CI
# the day someone changes the persona-set output format without
# updating the widened ``_is_init_stub`` predicate.
EXPECTED_PERSONA_STUB_BYTES = b'[bonfire]\npersona = "falcor"\n'


# ---------------------------------------------------------------------------
# Predicate tests — direct unit tests on ``_is_init_stub``
# ---------------------------------------------------------------------------


class TestIsInitStubAcceptsPersonaKey:
    """``_is_init_stub`` recognizes the post-``persona set`` stub shape.

    The widening: ``[bonfire]\\npersona = "<escaped>"\\n`` (with the
    trailing-whitespace tolerance the predicate already grants the bare
    stub) reads as still-a-stub, so ``scan`` overwrites it cleanly.
    """

    def test_recognizes_persona_falcor_after_init(self, tmp_path: Path) -> None:
        """RED — stub plus the ``persona set falcor`` line reads as a stub.

        This is the canonical W8.F shape: what ``bonfire persona set
        falcor`` emits when invoked right after ``bonfire init .``.
        """
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(EXPECTED_PERSONA_STUB_BYTES)

        assert _is_init_stub(toml_path) is True, (
            "predicate must recognize 'init stub + persona = \"falcor\"' as still-a-stub; "
            "otherwise the documented 'init && persona set && scan' flow exits 1 on scan"
        )

    def test_recognizes_persona_minimal_after_init(self, tmp_path: Path) -> None:
        """RED — widening must accept any persona NAME, not hard-code falcor."""
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(b'[bonfire]\npersona = "minimal"\n')

        assert _is_init_stub(toml_path) is True, (
            "predicate must accept the persona-set output for any builtin persona name, "
            "not just falcor"
        )

    def test_recognizes_persona_with_trailing_whitespace(self, tmp_path: Path) -> None:
        """RED — the trailing-whitespace tolerance the bare stub gets must extend."""
        toml_path = tmp_path / "bonfire.toml"
        # Mirror the predicate's existing CRLF / extra-newline tolerance for the
        # bare stub: an editor or Windows checkout normalising the persona-set
        # output's line endings must still read as a stub.
        toml_path.write_bytes(b'[bonfire]\npersona = "falcor"\n\n')

        assert _is_init_stub(toml_path) is True, (
            "predicate must tolerate trailing whitespace on the persona-stub shape "
            "the same way it tolerates it on the bare stub"
        )


# ---------------------------------------------------------------------------
# Regression canaries — widening must NOT go too far (W7.M defense preserved)
# ---------------------------------------------------------------------------


class TestIsInitStubWideningStaysNarrow:
    """The W8.F widening must NOT recognize fully-configured configs as stubs.

    These tests pin the upper bound on the widening. If the Warrior's
    implementation broadens the predicate to match any "stub + one key"
    or anything similarly loose, these tests fail and the W7.M
    overwrite-defense regresses.
    """

    def test_rejects_fully_configured_config(self, tmp_path: Path) -> None:
        """GREEN canary — a realistic multi-section config is NOT a stub.

        The shape here is what ``generate_config`` emits after a real
        scan: header section + persona + project + git. The post-fix
        predicate must refuse this even though it starts with
        ``[bonfire]``. This is the headline regression canary on
        W7.M / PR #103's overwrite-defense.

        Cross-lane note (OL-3): no assertion on ``[bonfire.tools]``
        emission shape — W8.G is touching that region in parallel.
        This test deliberately omits ``[bonfire.tools]`` from the
        fixture so no behavioral coupling exists.
        """
        toml_path = tmp_path / "bonfire.toml"
        # Multiple sections + multiple keys + realistic comments. Exceeds
        # 64 bytes too — the size gate alone would catch this, but we
        # build the fixture as a real config so the test pins semantic
        # refusal even if a future implementation widens the size cap.
        configured = (
            b"[bonfire]\n"
            b"# Project identity\n"
            b'name = "demo-project"\n'
            b"\n"
            b"[bonfire.persona]\n"
            b"# Derived from conversation\n"
            b'companion_mode = "falcor"\n'
            b"\n"
            b"[bonfire.project]\n"
            b"# Derived from scan: project_structure panel\n"
            b'primary_language = "python"\n'
            b'framework = "fastapi"\n'
            b"\n"
            b"[bonfire.git]\n"
            b"# Derived from scan: git_state panel\n"
            b'remote = "https://github.com/example/demo"\n'
            b'branch = "main"\n'
        )
        toml_path.write_bytes(configured)

        assert _is_init_stub(toml_path) is False, (
            "predicate must refuse a fully-configured bonfire.toml — the W8.F "
            "widening must NOT regress the W7.M / PR #103 overwrite-defense"
        )

    def test_rejects_hand_added_name_key(self, tmp_path: Path) -> None:
        """GREEN canary — a stub with a hand-added ``name`` key is NOT a stub.

        This pins that the widening is persona-specific, not "any single
        key under [bonfire]". Mirrors
        ``test_init_scan_composability.py::TestIsInitStubPredicate::test_is_init_stub_rejects_one_added_key``
        — that test pins the pre-widening behavior; this one pins that
        the post-widening behavior keeps refusing non-persona keys.

        If the Warrior implements a broader widening ("stub + at most
        one key under ``[bonfire]``"), this test fails — flag back to
        the Knight before relaxing.
        """
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(b'[bonfire]\nname = "demo"\n')

        assert _is_init_stub(toml_path) is False, (
            "widening must be persona-specific: a hand-added 'name = \"demo\"' key "
            "is a user customization the W7.M overwrite-defense must still catch"
        )

    def test_rejects_stub_plus_added_section(self, tmp_path: Path) -> None:
        """GREEN canary — a stub plus a second section is NOT a stub.

        Pairs with ``test_is_init_stub_rejects_added_section`` in the
        neighbour file. Pins that even an empty additional section
        falls out of stub recognition. The widening must not extend
        across section boundaries.
        """
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(b'[bonfire]\npersona = "falcor"\n[bonfire.git]\n')

        assert _is_init_stub(toml_path) is False, (
            "predicate must refuse a persona-stub PLUS an additional section — "
            "the widening must stay scoped to the [bonfire] table"
        )

    def test_rejects_persona_plus_extra_key(self, tmp_path: Path) -> None:
        """GREEN canary — the widening allows EXACTLY the persona line.

        ``persona = "falcor"`` plus a second key under ``[bonfire]`` is
        the kind of user edit the W7.M defense must still catch. The
        widening tolerates only the bare persona-set output shape.
        """
        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_bytes(b'[bonfire]\npersona = "falcor"\nname = "demo"\n')

        assert _is_init_stub(toml_path) is False, (
            "widening must reject a persona-set output that has been further "
            "hand-edited; the second key signals real user customization"
        )


# ---------------------------------------------------------------------------
# End-to-end integration — the W8.F headline contract
# ---------------------------------------------------------------------------


class TestInitPersonaSetScanComposes:
    """The documented three-step flow exits 0 at each step.

    From the v0.1 README quickstart shape:

        bonfire init . && bonfire persona set falcor && bonfire scan

    All three steps must succeed when run against a fresh directory.
    This is the W8.F regression-pin: if anyone narrows the
    ``_is_init_stub`` widening in the future, this test catches it
    before the documented flow breaks.
    """

    def test_init_then_persona_set_then_scan_all_succeed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """RED — three-step flow composes end-to-end; scan exits 0.

        Today the third step (``scan``) exits 1 because the
        ``persona set`` output (``[bonfire]\\npersona = "falcor"\\n``)
        is not the bare init stub, and the scan CLI's fail-fast guard
        refuses to overwrite. After the W8.F widening it composes.
        """
        # Step 1: init.
        result_init = runner.invoke(app, ["init", str(tmp_path)])
        assert result_init.exit_code == 0, (
            f"step 1 (init) must succeed; "
            f"got exit_code={result_init.exit_code}, output={result_init.output!r}"
        )

        toml_path = tmp_path / "bonfire.toml"
        assert toml_path.exists(), "init must have created bonfire.toml"

        # Step 2: persona set. chdir into tmp_path so the persona CLI's
        # ``Path.cwd() / "bonfire.toml"`` lookup finds the stub.
        monkeypatch.chdir(tmp_path)
        result_persona = runner.invoke(app, ["persona", "set", "falcor"])
        assert result_persona.exit_code == 0, (
            f"step 2 (persona set) must succeed; "
            f"got exit_code={result_persona.exit_code}, output={result_persona.output!r}"
        )

        # Sanity: persona set produced the byte shape the widened predicate
        # must recognize. Pin against drift in persona-set's output format.
        assert toml_path.read_bytes() == EXPECTED_PERSONA_STUB_BYTES, (
            "persona-set output drifted from b'[bonfire]\\npersona = \"falcor\"\\n'; "
            "update EXPECTED_PERSONA_STUB_BYTES and re-check the predicate widening"
        )

        # Step 3: scan. Mock _run_scan so we don't bind a real socket —
        # the contract here is "scan proceeds past the overwrite guard",
        # not "scan completes a real onboarding conversation".
        with patch("bonfire.cli.commands.scan._run_scan", new_callable=AsyncMock) as mock_run:
            mock_run.return_value = None
            result_scan = runner.invoke(app, ["scan", "--no-browser"])

        assert result_scan.exit_code == 0, (
            f"step 3 (scan) must succeed after init + persona set; "
            f"got exit_code={result_scan.exit_code}, output={result_scan.output!r}"
        )
        assert mock_run.called, (
            "scan must proceed into _run_scan after init + persona set — "
            "the W8.F init-persona-stub contract"
        )
