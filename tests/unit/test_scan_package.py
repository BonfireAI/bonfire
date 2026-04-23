"""BON-341 RED — Knight B (conservative) — bonfire.scan package.

Validates __all__ + import surface per Sage D8.3.

Sage log: docs/audit/sage-decisions/bon-341-sage-20260422T235032Z.md §D8.3.
"""

from __future__ import annotations


class TestScanPackage:
    def test_package_exports_tech_scanner(self):
        from bonfire.scan import TechScanner

        assert TechScanner.__name__ == "TechScanner"

    def test_package_exports_decision_recorder(self):
        from bonfire.scan import DecisionRecorder

        assert DecisionRecorder.__name__ == "DecisionRecorder"

    def test_package_does_not_export_tech_fingerprinter(self):
        import bonfire.scan

        # Old name must be gone post-rename (ADR-001 / D3.4).
        assert not hasattr(bonfire.scan, "TechFingerprinter")
