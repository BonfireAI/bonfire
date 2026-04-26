"""RED tests for bonfire.cli.app — BON-348 W6.2 (Knight A, CONSERVATIVE lens). Floor: 3 tests per Sage §D6 Row 2. Verbatim v1 port. No innovations.

Encodes typelock §6 invariants I1, I2, I12. Structural + behavioural guards
that the `dispatch` fossil has been removed from:

- the Typer registry (`app.registered_commands`),
- the CLI invocation surface (`CliRunner` returns non-zero on `dispatch task`),
- the filesystem (`src/bonfire/cli/commands/dispatch.py` does not exist).
"""

from __future__ import annotations

import pathlib

from typer.testing import CliRunner

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
