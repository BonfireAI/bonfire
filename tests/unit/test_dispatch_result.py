"""RED tests for ``bonfire.dispatch.result`` — W3.2 DispatchResult shape.

Canonical Sage synthesis of Knight-A (resilience) + Knight-B (fidelity).
``DispatchResult`` is the terminal data structure returned by every
``execute_with_retry`` call. Because the runner contract is **never raises**,
the shape of this result is the only debugging surface for consumers. If
the shape drifts, blind retries and cost reconciliation both break in ways
that unit tests of the runner cannot see.

Invariants locked by this suite
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Exactly four public fields: ``envelope``, ``duration_seconds``,
  ``retries``, ``cost_usd``. No stray ``status`` / ``error`` shortcuts —
  callers must read through ``envelope`` (single source of truth).
* Frozen Pydantic v2 model (``ConfigDict(frozen=True)``). Mutation attempts
  raise ``ValidationError``.
* ``envelope`` is the ``bonfire.models.envelope.Envelope`` type — no
  ``Any`` / ``dict`` drift.
* ``retries`` is an int. Floats must fail validation (prevents silent
  half-retry arithmetic).
* ``cost_usd`` and ``duration_seconds`` are floats with no negative guard
  in the result itself — the Envelope validator handles cost non-negativity.
* ``model_dump`` round-trips cleanly through ``model_validate`` (crash-
  recovery / checkpoint persistence depend on this).
* Package re-export: ``from bonfire.dispatch import DispatchResult`` is
  the same object as ``from bonfire.dispatch.result import DispatchResult``.

Public v0.1 surface — matches ``tests/unit/test_envelope.py`` per-file
import shim pattern exactly.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from bonfire.models.envelope import Envelope, ErrorDetail, TaskStatus

try:
    from bonfire.dispatch.result import DispatchResult
except ImportError as _exc:  # pragma: no cover
    _IMPORT_ERROR: Exception | None = _exc
    DispatchResult = None  # type: ignore[assignment,misc]
else:
    _IMPORT_ERROR = None


@pytest.fixture(autouse=True)
def _require_module():
    """Fail every test with the import error while bonfire.dispatch.result is missing."""
    if _IMPORT_ERROR is not None:
        pytest.fail(f"bonfire.dispatch.result not importable: {_IMPORT_ERROR}")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ok_envelope(cost: float = 0.05) -> Envelope:
    base = Envelope(task="resilience check", agent_name="scout")
    return base.with_result("done", cost_usd=cost)


def _failed_envelope(error_type: str = "infrastructure", message: str = "boom") -> Envelope:
    base = Envelope(task="resilience check", agent_name="scout")
    return base.with_error(ErrorDetail(error_type=error_type, message=message))


# ---------------------------------------------------------------------------
# Imports + re-exports
# ---------------------------------------------------------------------------


class TestDispatchResultImports:
    """DispatchResult is importable from the result module AND the package."""

    def test_import_from_result_module(self):
        from bonfire.dispatch.result import DispatchResult as _DR

        assert _DR is not None

    def test_import_from_dispatch_package(self):
        """Package re-export must expose DispatchResult."""
        from bonfire.dispatch import DispatchResult as _DR

        assert _DR is not None

    def test_package_and_module_export_same_class(self):
        """The package re-export is the same class object, not a copy."""
        from bonfire.dispatch import DispatchResult as pkg_cls
        from bonfire.dispatch.result import DispatchResult as mod_cls

        assert pkg_cls is mod_cls


# ---------------------------------------------------------------------------
# Required fields
# ---------------------------------------------------------------------------


class TestDispatchResultFields:
    """DispatchResult has exactly four public fields with locked types."""

    def test_envelope_field_preserved(self):
        env = _ok_envelope(cost=0.10)
        result = DispatchResult(envelope=env, duration_seconds=1.5, retries=0, cost_usd=0.10)
        assert result.envelope is env

    def test_duration_seconds_is_float(self):
        result = DispatchResult(
            envelope=_ok_envelope(),
            duration_seconds=2.5,
            retries=0,
            cost_usd=0.0,
        )
        assert isinstance(result.duration_seconds, float)
        assert result.duration_seconds == pytest.approx(2.5)

    def test_retries_is_int(self):
        result = DispatchResult(
            envelope=_ok_envelope(),
            duration_seconds=1.0,
            retries=3,
            cost_usd=0.0,
        )
        assert isinstance(result.retries, int)
        assert result.retries == 3

    def test_cost_usd_is_float(self):
        result = DispatchResult(
            envelope=_ok_envelope(cost=0.42),
            duration_seconds=1.0,
            retries=0,
            cost_usd=0.42,
        )
        assert isinstance(result.cost_usd, float)
        assert result.cost_usd == pytest.approx(0.42)

    def test_exactly_four_fields(self):
        """The public model_fields set must be exactly the four documented fields.

        A larger surface tempts callers to read fields like ``status`` directly
        instead of going through ``envelope``, which is a documented invariant
        violation (the Envelope is the single source of truth for status).
        """
        expected = {"envelope", "duration_seconds", "retries", "cost_usd"}
        assert set(DispatchResult.model_fields) == expected

    def test_envelope_field_has_envelope_annotation(self):
        """The envelope field must be typed ``Envelope`` — not ``Any`` / ``dict``."""
        anno = DispatchResult.model_fields["envelope"].annotation
        assert anno is Envelope or getattr(anno, "__name__", "") == "Envelope"


# ---------------------------------------------------------------------------
# Frozen invariant
# ---------------------------------------------------------------------------


class TestDispatchResultFrozen:
    """Frozen: attempted mutation raises ValidationError."""

    def test_frozen_retries_rejects_reassignment(self):
        result = DispatchResult(
            envelope=_ok_envelope(),
            duration_seconds=1.0,
            retries=0,
            cost_usd=0.0,
        )
        with pytest.raises(ValidationError):
            result.retries = 5  # type: ignore[misc]

    def test_frozen_envelope_rejects_reassignment(self):
        result = DispatchResult(
            envelope=_ok_envelope(),
            duration_seconds=1.0,
            retries=0,
            cost_usd=0.0,
        )
        with pytest.raises(ValidationError):
            result.envelope = _failed_envelope()  # type: ignore[misc]

    def test_frozen_cost_usd_rejects_reassignment(self):
        result = DispatchResult(
            envelope=_ok_envelope(),
            duration_seconds=1.0,
            retries=0,
            cost_usd=0.0,
        )
        with pytest.raises(ValidationError):
            result.cost_usd = 99.0  # type: ignore[misc]

    def test_frozen_duration_rejects_reassignment(self):
        result = DispatchResult(
            envelope=_ok_envelope(),
            duration_seconds=1.0,
            retries=0,
            cost_usd=0.0,
        )
        with pytest.raises(ValidationError):
            result.duration_seconds = 99.0  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Validation — type drift guards
# ---------------------------------------------------------------------------


class TestDispatchResultValidation:
    """Type validation prevents silent coercion that breaks caller assumptions."""

    def test_rejects_non_envelope(self):
        """``envelope`` must be an Envelope — dict/None are not silently coerced."""
        with pytest.raises(ValidationError):
            DispatchResult(
                envelope="not-an-envelope",  # type: ignore[arg-type]
                duration_seconds=1.0,
                retries=0,
                cost_usd=0.0,
            )

    def test_rejects_none_envelope(self):
        with pytest.raises(ValidationError):
            DispatchResult(
                envelope=None,  # type: ignore[arg-type]
                duration_seconds=1.0,
                retries=0,
                cost_usd=0.0,
            )

    def test_rejects_fractional_retries(self):
        """Retries must be an integer — fractional retry counts are nonsense."""
        with pytest.raises(ValidationError):
            DispatchResult(
                envelope=_ok_envelope(),
                duration_seconds=1.0,
                retries=1.5,  # type: ignore[arg-type]
                cost_usd=0.0,
            )

    def test_all_fields_required(self):
        """No field has a default — every dispatch-result must be explicit."""
        with pytest.raises(ValidationError):
            DispatchResult(envelope=_ok_envelope())  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# Serialisation — checkpoint round-trip
# ---------------------------------------------------------------------------


class TestDispatchResultSerialisation:
    """model_dump + model_validate round-trip cleanly (crash-recovery need)."""

    def test_model_dump_returns_dict(self):
        result = DispatchResult(
            envelope=_ok_envelope(cost=0.10),
            duration_seconds=2.0,
            retries=1,
            cost_usd=0.10,
        )
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["retries"] == 1
        assert dumped["cost_usd"] == pytest.approx(0.10)
        assert dumped["duration_seconds"] == pytest.approx(2.0)
        assert "envelope" in dumped

    def test_model_dump_envelope_is_dict(self):
        result = DispatchResult(
            envelope=_ok_envelope(),
            duration_seconds=1.0,
            retries=0,
            cost_usd=0.0,
        )
        dumped = result.model_dump()
        assert isinstance(dumped["envelope"], dict)

    def test_roundtrip_via_model_validate(self):
        """A dumped result can be rehydrated byte-for-byte."""
        env = _ok_envelope(cost=0.10)
        original = DispatchResult(
            envelope=env,
            duration_seconds=1.25,
            retries=2,
            cost_usd=0.10,
        )
        restored = DispatchResult.model_validate(original.model_dump())
        assert restored.retries == 2
        assert restored.cost_usd == pytest.approx(0.10)
        assert restored.duration_seconds == pytest.approx(1.25)
        assert restored.envelope.status == TaskStatus.COMPLETED
        assert restored.envelope.result == "done"


# ---------------------------------------------------------------------------
# Equality
# ---------------------------------------------------------------------------


class TestDispatchResultEquality:
    """Structurally identical results compare equal (enables test assertions)."""

    def test_equality_of_identical_results(self):
        env = _ok_envelope()
        a = DispatchResult(envelope=env, duration_seconds=1.0, retries=0, cost_usd=0.0)
        b = DispatchResult(envelope=env, duration_seconds=1.0, retries=0, cost_usd=0.0)
        assert a == b

    def test_inequality_on_retry_difference(self):
        env = _ok_envelope()
        a = DispatchResult(envelope=env, duration_seconds=1.0, retries=0, cost_usd=0.0)
        b = DispatchResult(envelope=env, duration_seconds=1.0, retries=1, cost_usd=0.0)
        assert a != b


# ---------------------------------------------------------------------------
# Failure envelope carriage
# ---------------------------------------------------------------------------


class TestDispatchResultFailureCarriage:
    """A failure dispatch must carry the FAILED envelope verbatim — no drift."""

    def test_failed_envelope_preserved(self):
        failed = _failed_envelope("infrastructure", "network down")
        result = DispatchResult(
            envelope=failed,
            duration_seconds=7.0,
            retries=3,
            cost_usd=0.0,
        )
        assert result.envelope.status == TaskStatus.FAILED
        assert result.envelope.error is not None
        assert result.envelope.error.error_type == "infrastructure"
        assert result.envelope.error.message == "network down"

    def test_zero_cost_on_pure_infrastructure_failure(self):
        """All attempts raised before any backend call returned — cost == 0."""
        failed = _failed_envelope("infrastructure", "timeout")
        result = DispatchResult(
            envelope=failed,
            duration_seconds=5.0,
            retries=3,
            cost_usd=0.0,
        )
        assert result.cost_usd == 0.0
