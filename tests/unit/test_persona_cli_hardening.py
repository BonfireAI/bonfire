"""RED contract for two persona CLI hardening fixes (issue #79 a+b).

Subject: ``bonfire.cli.commands.persona``.

(a) Escaped-quote rewrite. ``persona set`` rewrites an existing
    ``[bonfire].persona`` value in place with the regex
    ``^persona\\s*=\\s*"[^"]*"``. The ``[^"]*`` character class stops at
    the first ``"`` — including a backslash-*escaped* quote inside a TOML
    basic string. So when the pre-existing value carries an escaped quote
    (which the writer in this very module legitimately emits for hostile
    names), the rewrite matches only the truncated prefix and leaves the
    tail of the old value as garbage, corrupting the file. The fix is a
    quote-aware pattern (``"(?:[^"\\\\]|\\\\.)*"``) that consumes escaped
    quotes as part of the string.

(b) Slug validation parity. ``persona set`` performs no slug validation,
    while ``PersonaLoader.load``/``validate`` reject names that fail the
    slug pattern (path traversal, NUL bytes, whitespace, uppercase, ...)
    and silently fall back to ``minimal``. ``available()`` does NOT
    slug-filter the directory names it returns, so a non-slug directory
    name can be selected via ``set`` yet never load — a set/load parity
    break. ``set`` must use the SAME predicate (``_is_valid_persona_name``)
    as the loader so the two surfaces cannot drift, and WARN the operator
    when the chosen name will not load. The fix is a warning rather than a
    hard refusal because the locked TOML-escape contract
    (``test_persona_cli_toml_escape.py``) requires a hostile/non-slug name
    that is genuinely present in ``available()`` to be written as parseable
    (escaped) TOML, not silently dropped.
"""

from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING

import pytest
from typer.testing import CliRunner

from bonfire.cli.app import app

if TYPE_CHECKING:
    from pathlib import Path

cli_runner = CliRunner()


def _patch_available_with(monkeypatch: pytest.MonkeyPatch, names: list[str]) -> None:
    """Make ``PersonaLoader.available()`` return *names* so ``persona set`` accepts them."""

    def _fake_available(self):
        return list(names)

    monkeypatch.setattr(
        "bonfire.persona.loader.PersonaLoader.available",
        _fake_available,
    )


class TestEscapedQuoteRewrite:
    """(a) Rewriting a persona value that contains an escaped quote."""

    def test_rewrite_over_escaped_quote_value_stays_parseable(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """An existing escaped-quote persona value is fully replaced, TOML stays valid.

        The seed file holds ``persona = "evil\\"name"`` — exactly the shape
        this module's own writer emits for a hostile name. Setting a fresh
        valid persona over it must replace the WHOLE old value (including
        the bytes after the escaped quote), not just the truncated prefix.
        """
        monkeypatch.chdir(tmp_path)
        _patch_available_with(monkeypatch, ["falcor"])

        toml_path = tmp_path / "bonfire.toml"
        # The escaped-quote value the buggy [^"]* class truncates at.
        toml_path.write_text('[bonfire]\npersona = "evil\\"name"\nmodel = "claude-opus-4"\n')

        result = cli_runner.invoke(app, ["persona", "set", "falcor"])
        assert result.exit_code == 0, (
            f"persona set exit_code {result.exit_code}; output: {result.output!r}"
        )

        raw = toml_path.read_bytes()
        try:
            with toml_path.open("rb") as f:
                data = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            pytest.fail(
                "bonfire.toml failed to parse after rewriting an escaped-quote value. "
                f'This is the [^"]* truncation bug. Raw: {raw!r}; error: {exc}'
            )

        assert data["bonfire"].get("persona") == "falcor", (
            f"persona should be cleanly replaced with 'falcor', got "
            f"{data['bonfire'].get('persona')!r}. Raw: {raw!r}"
        )
        # No orphaned tail of the old escaped value leaked as a new table/key.
        assert set(data.keys()) == {"bonfire"}, (
            f"rewrite leaked extra top-level table(s). Parsed: {data!r}; raw: {raw!r}"
        )
        assert data["bonfire"].get("model") == "claude-opus-4", (
            f"sibling model key clobbered during rewrite. Parsed: {data!r}"
        )

    def test_rewrite_over_escaped_quote_to_hostile_name_roundtrips(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """Escaped-quote value rewritten to ANOTHER escaped-quote name round-trips."""
        monkeypatch.chdir(tmp_path)
        hostile = 'evil\\"two'
        _patch_available_with(monkeypatch, [hostile])

        toml_path = tmp_path / "bonfire.toml"
        toml_path.write_text('[bonfire]\npersona = "evil\\"name"\nmodel = "claude-opus-4"\n')

        result = cli_runner.invoke(app, ["persona", "set", hostile])
        assert result.exit_code == 0, (
            f"persona set exit_code {result.exit_code}; output: {result.output!r}"
        )

        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"].get("persona") == hostile, (
            f"hostile escaped-quote name should round-trip, got {data['bonfire'].get('persona')!r}"
        )
        assert set(data.keys()) == {"bonfire"}


class TestSlugValidationParity:
    """(b) ``persona set`` is slug-aware in parity with the loader.

    The loader (`PersonaLoader.load`/`validate`) rejects names that fail
    the slug pattern and falls back to ``minimal``. ``available()`` does
    NOT slug-filter the persona-directory names it returns, so a non-slug
    directory name can be selected via ``set`` yet never load. Parity here
    means ``set`` uses the SAME predicate (``_is_valid_persona_name``) to
    warn the operator — a warning, not a hard refusal, because the locked
    TOML-escape contract (`test_persona_cli_toml_escape.py`) requires that
    even a hostile/non-slug directory name, when genuinely present in
    ``available()``, be written as parseable (escaped) TOML rather than
    silently dropped. The two surfaces share one predicate, so they cannot
    drift on what "valid" means.
    """

    # Names that fail the loader's slug pattern ^[a-z][a-z0-9_-]*$ and that
    # ``PersonaLoader.load``/``validate`` would refuse.
    _INVALID = [
        "Evil",  # uppercase
        "9lead",  # leading digit
        "-lead",  # leading dash
        "evil.dot",
    ]

    @pytest.mark.parametrize("bad_name", _INVALID)
    def test_set_warns_on_invalid_slug_for_parity(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        bad_name: str,
    ) -> None:
        """A non-slug name (present in available) is written but warned about."""
        monkeypatch.chdir(tmp_path)
        _patch_available_with(monkeypatch, [bad_name])

        # ``--`` ends option parsing so a name beginning with ``-`` is read
        # as the positional argument, not a CLI flag.
        result = cli_runner.invoke(app, ["persona", "set", "--", bad_name])
        # Not a hard refusal — the escape contract requires the write to
        # succeed with parseable TOML.
        assert result.exit_code == 0, (
            f"persona set should write (and warn) for non-slug name {bad_name!r}; "
            f"output: {result.output!r}"
        )
        # Parity signal: the operator is told the loader will reject it.
        assert "not a valid persona name" in result.output, (
            f"persona set must WARN about set/load parity for {bad_name!r}; "
            f"output: {result.output!r}"
        )
        # The written file is still parseable (escape path engaged).
        toml_path = tmp_path / "bonfire.toml"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == bad_name

    @pytest.mark.parametrize("good_name", ["falcor", "minimal", "default", "my-persona_2"])
    def test_set_accepts_valid_slug_without_warning(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        good_name: str,
    ) -> None:
        """A name matching the slug pattern is accepted with no parity warning."""
        monkeypatch.chdir(tmp_path)
        _patch_available_with(monkeypatch, [good_name])

        result = cli_runner.invoke(app, ["persona", "set", good_name])
        assert result.exit_code == 0, (
            f"valid slug {good_name!r} should be accepted; output: {result.output!r}"
        )
        assert "not a valid persona name" not in result.output, (
            f"valid slug {good_name!r} must NOT trigger the parity warning; "
            f"output: {result.output!r}"
        )
        toml_path = tmp_path / "bonfire.toml"
        with toml_path.open("rb") as f:
            data = tomllib.load(f)
        assert data["bonfire"]["persona"] == good_name
