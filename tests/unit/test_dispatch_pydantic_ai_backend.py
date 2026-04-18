"""RED tests for ``bonfire.dispatch.pydantic_ai_backend`` — W3.2 secondary backend.

Canonical Sage synthesis of Knight-A (resilience) + Knight-B (fidelity).
``PydanticAIBackend`` wraps ``pydantic_ai.Agent.run()`` behind Bonfire's
``AgentBackend`` protocol so that provider-neutral / enrichment LLM calls
flow through the same cost-metering and event-bus surface as every other
dispatch. Sealing the ``AgentBackend`` protocol as truly provider-agnostic
is the core reason this backend ships in public v0.1 despite being light.

Cold-start pattern
~~~~~~~~~~~~~~~~~~
``pydantic_ai.Agent`` is lazy-imported INSIDE ``execute()``, not at module
top level. The module-level ``Agent`` sentinel (``None``) is populated on
first call so ``unittest.mock.patch`` can intercept the name at
``bonfire.dispatch.pydantic_ai_backend.Agent``. Public v0.1 does NOT list
``pydantic_ai`` as a hard runtime dependency — the module loads regardless.

Invariants locked
~~~~~~~~~~~~~~~~~
* **Lazy import.** Module-level ``Agent`` sentinel exists and is patchable.
* **Protocol conformance.** ``isinstance(backend, AgentBackend)`` at runtime.
* **No-arg construction** (``model=""`` default) and ``PydanticAIBackend(model=...)``.
* **Cost metering.** ``usage.total_tokens`` present → positive ``cost_usd``.
  Missing usage → ``cost_usd == 0.0``. ``total_tokens=None`` → ``0.0``.
* **Output mapping.** ``result.output`` becomes ``envelope.result``.
  Empty / ``None`` output does not crash.
* **health_check.** Always ``True`` — readiness is discovered on first call.

Sage scope note
~~~~~~~~~~~~~~~
V1 source does NOT wrap ``execute()`` in try/except — unlike the SDK
backend — so any ``pydantic_ai`` exception DOES escape and is caught by
the runner's exception retry loop. We lock the V1 behavior here; the
runner's ``TestReturnsDispatchResult.test_never_raises_on_unexpected_exception``
covers the downstream safety net.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from bonfire.models.envelope import Envelope
from bonfire.protocols import AgentBackend, DispatchOptions

try:
    from bonfire.dispatch.pydantic_ai_backend import PydanticAIBackend
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    PydanticAIBackend = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test while bonfire.dispatch.pydantic_ai_backend is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.pydantic_ai_backend not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _envelope(task: str = "summarise") -> Envelope:
    return Envelope(task=task, context="some context", agent_name="enricher")


def _mock_run_result(
    *,
    output: str = "output text",
    total_tokens: int | None = 100,
) -> MagicMock:
    result = MagicMock()
    result.output = output
    usage = MagicMock()
    usage.total_tokens = total_tokens
    result.usage = usage
    return result


# ---------------------------------------------------------------------------
# Imports + protocol conformance
# ---------------------------------------------------------------------------


class TestPydanticAIBackendImports:
    """Import + construction patterns required by public v0.1."""

    def test_import_from_module(self):
        from bonfire.dispatch.pydantic_ai_backend import PydanticAIBackend as _P

        assert _P is not None

    def test_construct_with_model_kwarg(self):
        backend = PydanticAIBackend(model="claude-sonnet-4")
        assert backend is not None

    def test_construct_with_no_args(self):
        """Constructor has a default ``model=""`` so callers can defer."""
        backend = PydanticAIBackend()
        assert backend is not None


class TestPydanticAIBackendProtocol:
    """Runtime protocol conformance — ``AgentBackend`` is ``@runtime_checkable``."""

    def test_satisfies_agent_backend_protocol(self):
        backend = PydanticAIBackend(model="test-model")
        assert isinstance(backend, AgentBackend)


# ---------------------------------------------------------------------------
# execute() routes through pydantic_ai.Agent.run()
# ---------------------------------------------------------------------------


class TestExecuteRoutesThroughAgent:
    """execute() delegates to ``Agent.run()`` and returns an Envelope."""

    async def test_calls_agent_run_once(self):
        backend = PydanticAIBackend(model="test-model")
        env = _envelope()
        opts = DispatchOptions(model="test-model", max_turns=1)
        run_result = _mock_run_result(output="pong")

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance

            result = await backend.execute(env, options=opts)

        agent_instance.run.assert_awaited_once()
        assert isinstance(result, Envelope)
        assert result.result == "pong"

    async def test_task_passed_to_agent_run(self):
        """The envelope's task string is the prompt passed to ``Agent.run``."""
        backend = PydanticAIBackend(model="x")
        env = _envelope(task="exact-task-string")
        opts = DispatchOptions(model="x")
        run_result = _mock_run_result()

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance

            await backend.execute(env, options=opts)

        agent_instance.run.assert_awaited_once()
        args, _ = agent_instance.run.call_args
        assert "exact-task-string" in args

    async def test_output_text_is_captured_as_result(self):
        """``result.output`` becomes ``envelope.result``."""
        backend = PydanticAIBackend(model="test-model")
        env = _envelope()
        opts = DispatchOptions(model="test-model")
        run_result = MagicMock()
        run_result.output = "EXPECTED_OUTPUT"
        run_result.usage = None

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance

            result = await backend.execute(env, options=opts)

        assert result.result == "EXPECTED_OUTPUT"


# ---------------------------------------------------------------------------
# Cost metering
# ---------------------------------------------------------------------------


class TestCostMetering:
    """Usage tokens → envelope ``cost_usd`` (positive or zero)."""

    async def test_cost_positive_when_tokens_present(self):
        backend = PydanticAIBackend(model="m")
        env = _envelope()
        opts = DispatchOptions(model="m")
        run_result = _mock_run_result(output="text", total_tokens=500)

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance
            result = await backend.execute(env, options=opts)

        assert result.cost_usd > 0.0

    async def test_cost_zero_when_usage_absent(self):
        """When ``usage`` is ``None``, the backend must not crash — cost = 0."""
        backend = PydanticAIBackend(model="m")
        env = _envelope()
        opts = DispatchOptions(model="m")
        run_result = MagicMock()
        run_result.output = "ok"
        run_result.usage = None

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance
            result = await backend.execute(env, options=opts)

        assert result.cost_usd == 0.0

    async def test_cost_zero_when_total_tokens_none(self):
        backend = PydanticAIBackend(model="m")
        env = _envelope()
        opts = DispatchOptions(model="m")
        run_result = _mock_run_result(total_tokens=None)

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance
            result = await backend.execute(env, options=opts)

        assert result.cost_usd == 0.0


# ---------------------------------------------------------------------------
# Empty / None output handling
# ---------------------------------------------------------------------------


class TestOutputHandling:
    """Empty or None output must not crash the backend."""

    async def test_empty_string_output_becomes_empty_result(self):
        backend = PydanticAIBackend(model="m")
        env = _envelope()
        opts = DispatchOptions(model="m")
        run_result = _mock_run_result(output="")

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance
            result = await backend.execute(env, options=opts)

        assert isinstance(result, Envelope)
        assert result.result == ""

    async def test_none_output_does_not_crash(self):
        backend = PydanticAIBackend(model="m")
        env = _envelope()
        opts = DispatchOptions(model="m")
        run_result = MagicMock()
        run_result.output = None
        run_result.usage = None

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance
            result = await backend.execute(env, options=opts)

        assert isinstance(result, Envelope)


# ---------------------------------------------------------------------------
# Lazy import
# ---------------------------------------------------------------------------


class TestLazyImport:
    """``Agent`` must be lazy-imported so the module loads without pydantic_ai."""

    def test_agent_sentinel_is_patchable(self):
        """The module-level ``Agent`` name must be reachable for patching."""
        import bonfire.dispatch.pydantic_ai_backend as mod

        # The name must exist — lazy-import pattern requires a module-level
        # sentinel even when pydantic_ai is absent.
        assert hasattr(mod, "Agent")

    async def test_execute_works_when_agent_is_patched(self):
        """If the sentinel is patched to a fake, ``execute()`` must use that fake."""
        backend = PydanticAIBackend(model="m")
        env = _envelope()
        opts = DispatchOptions(model="m")
        run_result = _mock_run_result(output="patched", total_tokens=10)

        with patch("bonfire.dispatch.pydantic_ai_backend.Agent") as agent_cls:
            agent_instance = MagicMock()
            agent_instance.run = AsyncMock(return_value=run_result)
            agent_cls.return_value = agent_instance
            result = await backend.execute(env, options=opts)

        assert result.result == "patched"


# ---------------------------------------------------------------------------
# health_check
# ---------------------------------------------------------------------------


class TestHealthCheck:
    """Health check is a pass-through — the backend is always nominally ready."""

    async def test_health_check_returns_true(self):
        backend = PydanticAIBackend(model="m")
        assert await backend.health_check() is True
