"""Stdlib-only smoke test for v0.1.0 release artifacts (BON-354).

This script is the W9.1 release-artifact gate. It is **deliberately not a
pytest test** — it runs in a clean venv that contains *only* the built
wheel (or sdist) plus its install dependencies, so the venv has no
``pytest``/``ruff``/``coverage`` to lean on. Stdlib only.

Verification list (per scout report
``docs/audit/scout-reports/bon-354-smoke-plan-20260428T203036Z.md`` §2.2):

1. ``import bonfire`` → ``__version__`` non-empty.
2. ``from bonfire.protocols import …`` six public names — no ``ImportError``.
3. ``from bonfire.engine import PipelineEngine, PipelineResult``.
4. Console script ``bonfire`` is on PATH inside the venv.
5. ``bonfire --version`` exits 0 and prints ``bonfire <digit-bearing-version>``.
6. ``bonfire --help`` exits 0 and lists every currently-registered command.
7. ``bonfire init <tmpdir>`` exits 0 and writes ``bonfire.toml`` + ``.bonfire/``.
8. Packaged data file ``bonfire.onboard/ui.html`` is reachable via
   ``importlib.resources``.
9. ``tempfile.TemporaryDirectory`` cleans up the init scratch dir.

Run as either::

    python tests/smoke/smoke_test.py
    python -m tests.smoke.smoke_test

The script exits 0 on full pass with a single ``OK`` summary; any failure
exits 1 with ``FAIL: <reason>`` on stderr.

Subprocess invocations always use list/tuple ``argv`` — never
``shell=True`` — so Bandit's B602 stays green.

Decision-4 scope (BON-354 comment 9503cd7f): no ``bonfire dispatch`` leg.
That is deferred to v0.1.1 / BON-633.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _venv_bindir() -> Path:
    """Return the directory holding the running Python's console scripts.

    On CI this is ``.smoke-wheel/bin/`` (the clean venv into which the wheel
    was installed). The smoke script invokes ``bonfire`` via subprocess, so
    we add this dir to ``PATH`` for the child process — that makes the test
    robust whether or not the operator ``source``-d the venv first.

    Important: do NOT call ``Path.resolve()`` here. ``sys.executable`` is
    typically a symlink inside the venv (``.venv/bin/python`` →
    ``/usr/bin/python3.X``); resolving the symlink would point us at the
    system bindir, which is the opposite of what we want. ``Path.parent``
    on the unresolved path keeps us inside the venv.
    """
    return Path(sys.executable).parent


def _child_env() -> dict[str, str]:
    """Subprocess env with the venv bindir prepended to ``PATH``."""
    env = os.environ.copy()
    env["PATH"] = str(_venv_bindir()) + os.pathsep + env.get("PATH", "")
    # Make Typer/Rich output deterministic and wide enough that command
    # names never wrap mid-row in step 6's --help check.
    env["NO_COLOR"] = "1"
    env["TERM"] = "dumb"
    env["COLUMNS"] = "200"
    return env


def _run(
    argv: list[str] | tuple[str, ...],
    *,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``argv`` with captured text output and the prepared child env."""
    return subprocess.run(  # noqa: S603 — argv is list[str], shell=False.
        list(argv),
        capture_output=True,
        text=True,
        env=env if env is not None else _child_env(),
        check=False,
    )


_PASS: list[str] = []


def _ok(label: str) -> None:
    _PASS.append(label)
    print(f"  ok  {label}")


def _fail(label: str, reason: str) -> None:
    sys.stderr.write(f"FAIL: {label}: {reason}\n")
    sys.exit(1)


# ---------------------------------------------------------------------------
# The nine verifications
# ---------------------------------------------------------------------------


def step1_import_bonfire() -> None:
    """1. ``import bonfire`` → ``__version__`` non-empty string."""
    label = "step1: import bonfire + __version__"
    try:
        import bonfire  # noqa: PLC0415 — runtime import is the test.
    except Exception as exc:  # pragma: no cover — failure path is the gate.
        _fail(label, f"import failed: {exc!r}")
        return
    version = getattr(bonfire, "__version__", None)
    if not isinstance(version, str) or not version:
        _fail(label, f"__version__ is missing or empty: {version!r}")
    _ok(f"{label} = {version!r}")


def step2_protocols_surface() -> None:
    """2. ``from bonfire.protocols import …`` six public names."""
    label = "step2: bonfire.protocols public surface"
    try:
        from bonfire.protocols import (  # noqa: F401, PLC0415
            AgentBackend,
            DispatchOptions,
            QualityGate,
            StageHandler,
            VaultBackend,
            VaultEntry,
        )
    except Exception as exc:
        _fail(label, f"import failed: {exc!r}")
        return
    _ok(label)


def step3_engine_surface() -> None:
    """3. ``from bonfire.engine import PipelineEngine, PipelineResult``."""
    label = "step3: bonfire.engine public surface"
    try:
        from bonfire.engine import PipelineEngine, PipelineResult  # noqa: F401, PLC0415
    except Exception as exc:
        _fail(label, f"import failed: {exc!r}")
        return
    _ok(label)


def step4_console_script_on_path() -> None:
    """4. ``shutil.which('bonfire')`` resolves inside this venv."""
    label = "step4: console script `bonfire` on PATH"
    env = _child_env()
    found = shutil.which("bonfire", path=env["PATH"])
    if not found:
        _fail(
            label,
            "shutil.which('bonfire') returned None — `[project.scripts]` "
            "wiring is broken or the wheel was not installed.",
        )
        return
    bindir = str(_venv_bindir())
    if not found.startswith(bindir):
        _fail(
            label,
            f"`bonfire` resolved to {found!r}, expected one inside {bindir!r}.",
        )
    _ok(f"{label} = {found}")


def step5_version_exit_zero() -> None:
    """5. ``bonfire --version`` exits 0 with version-shaped stdout."""
    label = "step5: `bonfire --version` exits 0"
    proc = _run(["bonfire", "--version"])
    if proc.returncode != 0:
        _fail(label, f"exit={proc.returncode} stderr={proc.stderr!r}")
        return
    out = proc.stdout
    if "bonfire" not in out.lower() or not re.search(r"\d", out):
        _fail(label, f"stdout did not contain version-shape text: {out!r}")
    _ok(f"{label} stdout={out.strip()!r}")


def step6_help_lists_commands() -> None:
    """6. ``bonfire --help`` exits 0 and lists every registered command."""
    label = "step6: `bonfire --help` lists registered commands"
    proc = _run(["bonfire", "--help"])
    if proc.returncode != 0:
        _fail(label, f"exit={proc.returncode} stderr={proc.stderr!r}")
        return
    expected = ("init", "scan", "status", "resume", "handoff", "persona", "cost")
    out = proc.stdout
    missing = [name for name in expected if name not in out]
    if missing:
        _fail(label, f"missing command names in --help output: {missing!r}")
    _ok(f"{label} ({', '.join(expected)})")


def step7_init_scaffolds_project() -> tempfile.TemporaryDirectory[str]:
    """7. ``bonfire init <tmpdir>`` exits 0; tmpdir gains ``bonfire.toml`` + ``.bonfire/``."""
    label = "step7: `bonfire init <tmpdir>` scaffolds a project"
    tmp = tempfile.TemporaryDirectory(prefix="bonfire-smoke-init-")
    proc = _run(["bonfire", "init", tmp.name])
    if proc.returncode != 0:
        # Surface both streams; init should be silent on success.
        _fail(
            label,
            f"exit={proc.returncode} stdout={proc.stdout!r} stderr={proc.stderr!r}",
        )
    toml = Path(tmp.name) / "bonfire.toml"
    bonfire_dir = Path(tmp.name) / ".bonfire"
    if not toml.is_file():
        _fail(label, f"{toml} not created")
    if not bonfire_dir.is_dir():
        _fail(label, f"{bonfire_dir} not created")
    _ok(f"{label} at {tmp.name}")
    return tmp


def step8_packaged_data_file() -> None:
    """8. ``bonfire.onboard/ui.html`` resolves via ``importlib.resources``."""
    label = "step8: importlib.resources finds bonfire.onboard/ui.html"
    try:
        resource = files("bonfire.onboard").joinpath("ui.html")
    except Exception as exc:
        _fail(label, f"importlib.resources lookup failed: {exc!r}")
        return
    if not resource.is_file():
        _fail(
            label,
            f"{resource} is not a file — hatchling [tool.hatch.build."
            "targets.wheel] include block likely dropped the data file.",
        )
    _ok(label)


def step9_cleanup(tmp: tempfile.TemporaryDirectory[str]) -> None:
    """9. ``TemporaryDirectory`` cleans up the init scratch dir."""
    label = "step9: tmpdir cleanup"
    name = tmp.name
    tmp.cleanup()
    if Path(name).exists():
        _fail(label, f"{name} still exists after TemporaryDirectory.cleanup()")
    _ok(label)


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------


def main() -> int:
    print(f"BON-354 smoke test — python={sys.executable}")
    print(f"                    venv bindir={_venv_bindir()}")
    print()
    step1_import_bonfire()
    step2_protocols_surface()
    step3_engine_surface()
    step4_console_script_on_path()
    step5_version_exit_zero()
    step6_help_lists_commands()
    tmp = step7_init_scaffolds_project()
    step8_packaged_data_file()
    step9_cleanup(tmp)
    print()
    print(f"OK ({len(_PASS)}/9 verifications passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
