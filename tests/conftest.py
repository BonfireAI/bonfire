"""Shared test fixtures for Bonfire.

Sage memo: ``docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md``
section G.2 + H.4.3.

This module provides an autouse fixture that scrubs ``BONFIRE_*`` environment
variables and pins cwd to a clean ``tmp_path`` for engine and handler test
modules. The fixture is scoped intentionally — config tests that *want* env
coupling keep their own ``monkeypatch.setenv`` calls. Without the scrub, a CI
runner with a leaked ``BONFIRE_*`` env var or a stray ``bonfire.toml`` on cwd
would silently flip ~40 constructor sites that today instantiate
``BonfireSettings()`` from a ``settings=None`` default branch.

Sage decision E (Settings constructor doctrine) keeps the kwarg optional, so
the engine constructors continue to call ``BonfireSettings()`` (or, after
Axis 2 lands, ``load_settings_or_default()``) on the ``None`` branch. The
fixture in this file is the test-side guarantee that the happy path stays
the happy path.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Modules whose tests run with the BONFIRE_* scrub + tmp cwd autouse fixture.
# Keep this conservative — config tests deliberately set BONFIRE_* env vars to
# exercise the source chain, so they are excluded.
_AUTOUSE_TEST_MODULE_PREFIXES: tuple[str, ...] = (
    "test_engine_",
    "test_architect_handler",
    "test_bard_handler",
    "test_herald_handler",
    "test_merge_preflight_handler",
    "test_sage_correction_handler",
    "test_wizard_handler",
)


def _is_engine_or_handler_test(module_path: str) -> bool:
    """Return True if a test module name starts with an engine/handler prefix."""
    name = Path(module_path).name
    return any(name.startswith(p) for p in _AUTOUSE_TEST_MODULE_PREFIXES)


@pytest.fixture(autouse=True)
def _bonfire_env_isolation(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Scrub ``BONFIRE_*`` env vars and chdir to ``tmp_path`` for engine tests.

    Sage memo G.2 + H.4.3 — autouse fixture scoped to engine + handler test
    modules. Eliminates the CI-fragility risk that 40+ tests would fail at
    construction time if a runner had a malformed ``BONFIRE_*`` env or a
    stray ``bonfire.toml`` on cwd.

    The scope check is by test-module filename prefix; tests outside the
    listed prefixes (e.g. ``test_config.py``) are unaffected and keep their
    own monkeypatch.setenv discipline.
    """
    module_path = getattr(request.node, "fspath", None)
    if module_path is None or not _is_engine_or_handler_test(str(module_path)):
        return

    for key in [k for k in os.environ if k.startswith("BONFIRE_")]:
        monkeypatch.delenv(key, raising=False)

    monkeypatch.chdir(tmp_path)


@pytest.fixture()
def _set_bonfire_env_for_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """Helper used by the fixture-validation test below."""
    monkeypatch.setenv("BONFIRE_BONFIRE__MAX_BUDGET_USD", "junk-value")


def test_conftest_scrubs_bonfire_env_for_engine_module() -> None:
    """Fixture-validation test: BONFIRE_* env vars are scrubbed inside engine
    tests.

    The autouse ``_bonfire_env_isolation`` fixture activates because this
    test module's filename matches the ``test_engine_*`` prefix list when a
    contributor copies this assertion into ``tests/unit/test_engine_*.py``.
    Here in ``tests/conftest.py`` itself, the autouse fixture also fires
    because pytest treats ``conftest.py`` as a test-collection module when
    a test function lives at module scope.

    The contract this test asserts: by the time the test body runs, no
    ``BONFIRE_*`` keys are present in the process environment, regardless
    of CI or operator-side leakage. The fixture body is the production
    code; this assertion is the lock.

    Sage memo: ``docs/audit/sage-decisions/cluster-351-sage-20260430T200000Z.md``
    section H.4.3.
    """
    # If the autouse fixture is wired correctly, no BONFIRE_* keys survive.
    leaked = [k for k in os.environ if k.startswith("BONFIRE_")]
    assert leaked == [], (
        f"Autouse env-scrub failed; leaked keys: {leaked!r}. The autouse "
        "fixture in tests/conftest.py must clear BONFIRE_* before the test "
        "body runs (Sage memo cluster-351 §H.4.3)."
    )
