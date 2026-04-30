"""RED tests for ``bonfire.verify`` classifier module surface.

Knight A SPINE — module-shape-only contract. Algorithm coverage is Knight B's
lane (Sage §D-CL.1 lines 100-104, §D-CL.2 lines 130-141): the keystone
``test_classifier.py`` algorithmic suite, the decision-log parser tests, and
the integration suite all live in Knight B's deliverables.

This file pins the *shape* of ``bonfire.verify``:
    - the package is importable;
    - the public exports listed in Sage §A §B File 1 (lines 319, 45) AND
      Sage §D §D1 line 53-63 are present;
    - ``ClassifierVerdict`` is a ``StrEnum`` carrying the three Anta-ratified
      members (``SAGE_UNDER_MARKED``, ``WARRIOR_BUG``, ``AMBIGUOUS``)
      pinned by §A Q1a (lines 51-52);
    - ``BounceClassification`` and ``DeferRecord`` are frozen dataclasses;
    - the classifier callable ``classify_warrior_failure`` is a function
      (pure-function discipline per §A Q1 line 38, §D2 line 78).

Sage memo (canonical):
    docs/audit/sage-decisions/bon-513-sage-CL-20260428T210000Z.md §D-CL.1
    docs/audit/sage-decisions/bon-513-sage-A-20260428T210000Z.md §A Q1, Q1a
    docs/audit/sage-decisions/bon-513-sage-D-20260428T210000Z.md §D1, §D2

Conservative RED idiom: each test imports the symbol it depends on inside
the test body. The missing-impl ``ImportError`` raises through; the
``@pytest.mark.xfail(strict=True, reason=...)`` decorator captures it.
``strict=True`` flips an unexpected pass into a hard failure so a future
Warrior who introduces an empty stub silently doesn't pass these tests.

Per the dispatch contract, this file MUST NOT mention bare ticket IDs in
``src/`` -- this file lives in ``tests/`` and is therefore allowed to
reference BON-513 in module docstring and in xfail reasons.
"""

from __future__ import annotations

import dataclasses
import inspect
from enum import StrEnum

import pytest

# === Knight A SPINE ===

_RED_REASON = (
    "BON-513 not implemented: bonfire.verify package surface is not yet on "
    "disk (Sage §D-CL.1 lines 100-104, §D1 lines 18-23). Knight A pins the "
    "shape; Warrior A scaffolds the module; Warrior B fills the algorithm."
)


# ---------------------------------------------------------------------------
# TestVerifyPackageImport (Sage §D1 lines 18-23, §B line 319)
# ---------------------------------------------------------------------------


class TestVerifyPackageImport:
    """The ``bonfire.verify`` package and its classifier module are
    importable. Sage §A Q1 (c) hybrid (lines 32-35): pure-function
    classifier lives under a NEW ``verify/`` package.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_verify_package_importable(self) -> None:
        """``import bonfire.verify`` succeeds."""
        import bonfire.verify  # noqa: F401  (import-only smoke)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_classifier_module_importable(self) -> None:
        """``import bonfire.verify.classifier`` succeeds."""
        import bonfire.verify.classifier  # noqa: F401

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_classifier_module_has_module_docstring(self) -> None:
        """Sage §D1 line 21: classifier module is documented."""
        import bonfire.verify.classifier as classifier_mod

        assert isinstance(classifier_mod.__doc__, str)
        assert classifier_mod.__doc__.strip(), "classifier module must have a non-empty docstring."


# ---------------------------------------------------------------------------
# TestVerifyPublicSurface (Sage §B line 319, §D1 lines 53-63)
# ---------------------------------------------------------------------------


class TestVerifyPublicSurface:
    """``bonfire.verify`` re-exports exactly the symbols Sage §B line 319
    + §D1 lines 53-63 promise. Knight A pins the surface; Warrior A
    creates the package init.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_classify_warrior_failure_exported(self) -> None:
        """``classify_warrior_failure`` is re-exported from the package."""
        from bonfire.verify import classify_warrior_failure

        assert callable(classify_warrior_failure)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_bounce_classification_exported(self) -> None:
        """``BounceClassification`` is re-exported from the package."""
        from bonfire.verify import BounceClassification

        assert BounceClassification is not None

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_bounce_verdict_exported(self) -> None:
        """``ClassifierVerdict`` is re-exported from the package."""
        from bonfire.verify import ClassifierVerdict

        assert ClassifierVerdict is not None

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_defer_record_exported(self) -> None:
        """``DeferRecord`` is re-exported from the package (Sage §D1 line 61)."""
        from bonfire.verify import DeferRecord

        assert DeferRecord is not None

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_dunder_all_lists_public_symbols(self) -> None:
        """``bonfire.verify.__all__`` enumerates the public exports
        per Sage §D1 lines 53-63.

        The set MUST include the three core symbols ratified by Anta in
        §A: classifier function, classification dataclass, and verdict
        StrEnum. Tolerant superset check (additional symbols allowed for
        forward-compat).
        """
        import bonfire.verify as verify_pkg

        assert hasattr(verify_pkg, "__all__")
        all_names = set(verify_pkg.__all__)
        expected_minimum = {
            "classify_warrior_failure",
            "BounceClassification",
            "ClassifierVerdict",
        }
        assert expected_minimum.issubset(all_names), (
            f"bonfire.verify.__all__ must include {expected_minimum}; got {all_names}."
        )


# ---------------------------------------------------------------------------
# TestClassifierVerdictEnum (Sage §A Q1a line 51, §D2 line 83)
# ---------------------------------------------------------------------------


class TestClassifierVerdictEnum:
    """``ClassifierVerdict`` is a StrEnum with the three Anta-ratified members.

    Sage §A Q1a (lines 51-52) ratified by Anta on 2026-04-28: 3-verdict
    classifier (``SAGE_UNDER_MARKED``, ``WARRIOR_BUG``, ``AMBIGUOUS``).
    The third verdict (``AMBIGUOUS``) escalates to Wizard rather than
    auto-bouncing.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_bounce_verdict_is_str_enum(self) -> None:
        """``ClassifierVerdict`` is a ``StrEnum`` (one-string-everywhere
        discipline per ``bonfire.agent.roles`` AgentRole convention)."""
        from bonfire.verify import ClassifierVerdict

        assert issubclass(ClassifierVerdict, StrEnum)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_sage_under_marked_member_present(self) -> None:
        """``ClassifierVerdict.SAGE_UNDER_MARKED`` member exists. Sage §A Q1a."""
        from bonfire.verify import ClassifierVerdict

        assert hasattr(ClassifierVerdict, "SAGE_UNDER_MARKED")

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_warrior_bug_member_present(self) -> None:
        """``ClassifierVerdict.WARRIOR_BUG`` member exists. Sage §A Q1a."""
        from bonfire.verify import ClassifierVerdict

        assert hasattr(ClassifierVerdict, "WARRIOR_BUG")

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_ambiguous_member_present(self) -> None:
        """``ClassifierVerdict.AMBIGUOUS`` member exists. Sage §A Q1a Anta-ratified
        as the third verdict (NOT folded into WARRIOR_BUG)."""
        from bonfire.verify import ClassifierVerdict

        assert hasattr(ClassifierVerdict, "AMBIGUOUS")

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_sage_under_marked_value_is_canonical_string(self) -> None:
        """Verdict value is the snake_case string (StrEnum convention)."""
        from bonfire.verify import ClassifierVerdict

        assert ClassifierVerdict.SAGE_UNDER_MARKED.value == "sage_under_marked"

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_warrior_bug_value_is_canonical_string(self) -> None:
        """``ClassifierVerdict.WARRIOR_BUG`` value is ``'warrior_bug'``."""
        from bonfire.verify import ClassifierVerdict

        assert ClassifierVerdict.WARRIOR_BUG.value == "warrior_bug"

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_ambiguous_value_is_canonical_string(self) -> None:
        """``ClassifierVerdict.AMBIGUOUS`` value is ``'ambiguous'``."""
        from bonfire.verify import ClassifierVerdict

        assert ClassifierVerdict.AMBIGUOUS.value == "ambiguous"


# ---------------------------------------------------------------------------
# TestBounceClassificationDataclass (Sage §D2 line 99)
# ---------------------------------------------------------------------------


class TestBounceClassificationDataclass:
    """``BounceClassification`` is a frozen dataclass.

    Sage §D2 lines 89-106 specify the dataclass shape; full field-shape
    coverage lives in Knight B's classifier-algorithm tests. Knight A
    only pins the *frozen* + *dataclass* property.
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_bounce_classification_is_dataclass(self) -> None:
        """``BounceClassification`` is decorated with ``@dataclass``."""
        from bonfire.verify import BounceClassification

        assert dataclasses.is_dataclass(BounceClassification)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_bounce_classification_is_frozen(self) -> None:
        """Frozen dataclass: instances are immutable.

        Sage §D-CL.7 #6 (BON-519 precedent): every set-shape field on
        Classification is a frozen value type; classifier never returns
        mutable types.
        """
        from bonfire.verify import BounceClassification

        params = getattr(BounceClassification, "__dataclass_params__", None)
        assert params is not None, "BounceClassification must be a dataclass."
        assert params.frozen is True, "BounceClassification must be a frozen dataclass."

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_bounce_classification_carries_verdict_field(self) -> None:
        """The classification result has a ``verdict`` field. Sage §D2 line 100."""
        from bonfire.verify import BounceClassification

        field_names = {f.name for f in dataclasses.fields(BounceClassification)}
        assert "verdict" in field_names, (
            "BounceClassification must expose a 'verdict' field (see Sage memo §D2 line 100)."
        )


# ---------------------------------------------------------------------------
# TestDeferRecordDataclass (Sage §A Q2 line 75, §D2)
# ---------------------------------------------------------------------------


class TestDeferRecordDataclass:
    """``DeferRecord`` is a frozen dataclass per Sage §A Q2 line 75."""

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_defer_record_is_dataclass(self) -> None:
        """``DeferRecord`` is a dataclass."""
        from bonfire.verify import DeferRecord

        assert dataclasses.is_dataclass(DeferRecord)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_defer_record_is_frozen(self) -> None:
        """``DeferRecord`` is frozen (immutable). Sage §A Q2 (DeferRecord
        is a value type, not a mutable container)."""
        from bonfire.verify import DeferRecord

        params = getattr(DeferRecord, "__dataclass_params__", None)
        assert params is not None
        assert params.frozen is True


# ---------------------------------------------------------------------------
# TestClassifyWarriorFailureCallable (Sage §A Q1a line 51, §D2 line 110)
# ---------------------------------------------------------------------------


class TestClassifyWarriorFailureCallable:
    """``classify_warrior_failure`` is callable, sync (pure function),
    and lives in ``bonfire.verify.classifier``.

    Sage §A Q1 line 38 + §D2 line 78: pure-function discipline (no I/O,
    no subprocess). Knight A pins ``inspect.iscoroutinefunction`` is False
    (Knight B exercises the algorithm).
    """

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_classify_warrior_failure_is_callable(self) -> None:
        """The classifier function is callable."""
        from bonfire.verify import classify_warrior_failure

        assert callable(classify_warrior_failure)

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_classify_warrior_failure_is_synchronous(self) -> None:
        """Pure function: NOT a coroutine (sync semantics).

        Sage §A Q1 line 38: 'classifier is pure (no I/O), handler is I/O'.
        A coroutine here would imply hidden I/O.
        """
        from bonfire.verify import classify_warrior_failure

        assert not inspect.iscoroutinefunction(classify_warrior_failure), (
            "classify_warrior_failure MUST be synchronous (pure function); "
            "coroutine signature implies hidden I/O which violates Sage §A Q1."
        )

    @pytest.mark.xfail(strict=True, reason=_RED_REASON)
    def test_classifier_lives_in_classifier_submodule(self) -> None:
        """The function's canonical home is ``bonfire.verify.classifier``."""
        from bonfire.verify import classifier as classifier_mod

        assert hasattr(classifier_mod, "classify_warrior_failure"), (
            "bonfire.verify.classifier must expose classify_warrior_failure "
            "(Sage §D1 line 21 + §D2 line 110)."
        )
