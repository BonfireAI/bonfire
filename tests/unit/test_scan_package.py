"""RED tests — BON-341 W5.2 — `bonfire.scan` package surface.

Sage D2 row 13: ``scan/__init__.py`` re-exports ``TechScanner`` and
``DecisionRecorder``; ``TechFingerprinter`` old name gone.

Adjudication: ``docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md``.
"""

from __future__ import annotations


class TestScanPackageExports:
    def test_package_exports_tech_scanner(self) -> None:
        from bonfire.scan import TechScanner

        assert TechScanner.__name__ == "TechScanner"

    def test_package_exports_decision_recorder(self) -> None:
        from bonfire.scan import DecisionRecorder

        assert DecisionRecorder.__name__ == "DecisionRecorder"

    def test_package_does_not_export_tech_fingerprinter(self) -> None:
        """ADR-001 rename: old name gone."""
        import bonfire.scan as scan_pkg

        assert not hasattr(scan_pkg, "TechFingerprinter")

    # knight-a(innovative): __all__ contains exactly the locked two names.
    def test_package_all_contains_only_locked_names(self) -> None:
        import bonfire.scan as scan_pkg

        # Sage D2 row 13: __all__ = ["TechScanner", "DecisionRecorder"].
        assert hasattr(scan_pkg, "__all__")
        assert set(scan_pkg.__all__) == {"TechScanner", "DecisionRecorder"}
