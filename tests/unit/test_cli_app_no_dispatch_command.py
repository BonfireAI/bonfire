"""RED tests for bonfire.cli.app dispatch-fossil guard — BON-348 W6.2 (CONTRACT-LOCKED).

Sage memo: docs/audit/sage-decisions/bon-348-sage-20260426T013845Z.md
Adoption-filter: docs/audit/sage-decisions/bon-348-contract-lock-*.md

Floor (3 tests, per Sage §D6 Test file 2): port v1 cli test surface verbatim.
The `dispatch` command was folded into `pipeline run` per BON-370 X1.a (v1 lore).
v0.1 inherits this — no `dispatch.py` file, no `dispatch` registration. Sage §D1
"Other explicit non-goals" LOCKS this: "Do NOT create a `dispatch.py` file."

Adopted innovations (2 drift-guards over floor):

  * test_no_dispatch_alias_registered — parametrize over alternate aliases that
    should NOT be registered: dispatch / dispatchall / Dispatch / DISPATCH /
    dispatchtask. Guards against case-variant or pluralized fossil resurrection.
    Cites Sage §D1 + v1 test_cli_app_no_dispatch_command.py:34-52.

  * test_help_text_excludes_dispatch_word — `bonfire --help` output must not
    mention the word "dispatch" (case-insensitive). Guards against documentation
    residue from v1 — a forgotten epilog string or docstring reference. Cites
    Sage §D1 + v1 cli/app.py.

Encodes typelock §6 invariants I1, I2, I12. Structural + behavioural guards
that the `dispatch` fossil has been removed from:

- the Typer registry (`app.registered_commands`),
- the CLI invocation surface (`CliRunner` returns non-zero on `dispatch task`),
- the filesystem (`src/bonfire/cli/commands/dispatch.py` does not exist).
"""

from __future__ import annotations

import pathlib

import pytest
from typer.testing import CliRunner

# RED import — bonfire.cli.app module does not exist yet (cli.py is a single-file stub)
from bonfire.cli.app import app

runner = CliRunner()


def test_dispatch_not_in_registered_commands() -> None:
    """I2: `bonfire dispatch` must not appear in Typer's registered commands.

    Typer exposes `registered_commands` as a list of `CommandInfo` objects;
    each has a `.name` attribute. A `None` name means Typer derived the name
    from the function — we match on the derived name too for safety.
    """
    for cmd in app.registered_commands:
        # Typer sets `.name` to the explicit override; when None, the derived
        # name is the callback's `__name__`. Both must be checked.
        if cmd.name is not None:
            assert cmd.name != "dispatch", (
                f"`dispatch` is still registered on app (explicit name). Found: {cmd}"
            )
        elif cmd.callback is not None:
            assert cmd.callback.__name__ != "dispatch", (
                f"`dispatch` callback is still registered on app (derived name). "
                f"Found: {cmd.callback.__name__}"
            )


def test_dispatch_command_invocation_fails() -> None:
    """I1: Invoking `bonfire dispatch task` must fail with a non-zero exit.

    Typer's unknown-command error surface varies slightly across versions
    (and can route through `stderr` under `mix_stderr=True`), so we accept a
    UNION of markers: "No such command", "Usage", or "Error". Any of these
    in `result.output` confirms Typer's unknown-command path was hit and
    the runner did NOT fall through to the fossil dispatch callable.

    The key invariant is non-zero exit PLUS one of these markers present —
    stronger than "non-zero exit alone", which would also succeed if
    `dispatch` still ran and crashed with a TypeError traceback.
    """
    result = runner.invoke(app, ["dispatch", "task"])
    assert result.exit_code != 0, (
        f"Expected non-zero exit for unknown `dispatch` command. "
        f"Got exit_code={result.exit_code}, output={result.output!r}"
    )
    output = result.output or ""
    markers = ("No such command", "Usage", "Error")
    assert any(marker in output for marker in markers), (
        f"Expected Typer's unknown-command marker in output (one of {markers!r}); got: {output!r}"
    )


def test_dispatch_py_file_does_not_exist() -> None:
    """I12: `src/bonfire/cli/commands/dispatch.py` must NOT exist on disk.

    Structural guard against fossil resurrection. Computes repo_root from
    this file's location: tests/unit/test_cli_app_no_dispatch_command.py
    → parents[2] = repo root.
    """
    repo_root = pathlib.Path(__file__).resolve().parents[2]
    dispatch_py = repo_root / "src" / "bonfire" / "cli" / "commands" / "dispatch.py"
    assert not dispatch_py.exists(), (
        f"Fossil `dispatch.py` still exists at {dispatch_py}. "
        f"Warrior must delete it to close BON-370 X1.a."
    )


# ---------------------------------------------------------------------------
# Adopted drift-guards (2 — innovations 3 + 4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias",
    [
        "dispatch",
        "dispatchall",
        "Dispatch",
        "DISPATCH",
        "dispatchtask",
    ],
)
def test_no_dispatch_alias_registered(alias: str) -> None:
    """No dispatch-flavored alias is registered on the app.

    Cites Sage §D1 + v1 test_cli_app_no_dispatch_command.py:34-52.

    The floor test `test_dispatch_not_in_registered_commands` only checks
    the literal string "dispatch". This parametrized test extends the guard
    to:
      - `dispatchall` (potential pluralization fossil);
      - `Dispatch` / `DISPATCH` (case-variant fossils);
      - `dispatchtask` (task-suffix fossil — v0/v1 lore had `dispatch task`).

    None should be registered — neither as a command nor as a sub-typer.
    """
    for cmd in app.registered_commands:
        if cmd.name is not None:
            assert cmd.name != alias, (
                f"Fossil alias {alias!r} is registered on app (explicit name). Found: {cmd}"
            )
        elif cmd.callback is not None:
            assert cmd.callback.__name__ != alias, (
                f"Fossil alias {alias!r} is the callback name. "
                f"Found: {cmd.callback.__name__}"
            )

    # Sub-typer groups must also not match
    for grp in app.registered_groups:
        if grp.name is not None:
            assert grp.name != alias, (
                f"Fossil alias {alias!r} is registered as a Typer group. Found: {grp}"
            )


def test_help_text_excludes_dispatch_word() -> None:
    """`bonfire --help` output must not mention 'dispatch' anywhere.

    Cites Sage §D1 + v1 cli/app.py.

    The floor tests verify:
      - dispatch is not registered (registry-level);
      - invocation fails with unknown-command marker (runner-level);
      - dispatch.py file is absent (filesystem-level).

    This adds a USER-SURFACE guard: the help screen seen by an end-user
    running `bonfire --help` must not contain the word "dispatch". Guards
    against documentation residue:
      - a forgotten epilog string in `app = typer.Typer(...)`;
      - a stale docstring reference in main callback;
      - an accidental `app.add_typer(..., name="dispatch")` that registered
        but produced no command.
    """
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0, f"--help should exit zero; got {result.exit_code}"
    # Lowercase comparison — case-insensitive guard
    output_lower = result.output.lower()
    assert "dispatch" not in output_lower, (
        f"`bonfire --help` output mentions 'dispatch' — fossil residue. "
        f"Output: {result.output!r}"
    )
