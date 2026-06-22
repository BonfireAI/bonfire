# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""RED tests for ``bonfire.integrations.document`` — ISM v1 schema contract.

Locks the Pydantic models that back ISM frontmatter:

* :class:`ISMDocument` — top-level frontmatter + body container.
* :class:`ISMCategory` — five-value enum (forge / ticketing / comms / vault / ide).
* :class:`DetectionRule` — discriminated union of:
    - :class:`CommandRule`        (``kind: command``)
    - :class:`EnvVarRule`         (``kind: env_var``)
    - :class:`FileMatchRule`      (``kind: file_match``)
    - :class:`PythonImportRule`   (``kind: python_import``)
* :class:`Credentials`, :class:`Fallback` — optional sub-objects.
* :class:`ISMSchemaError` — exception raised by the loader's strict path.

Spec: ``docs/specs/ism-v1.md`` §3, §4, §7.

These tests must FAIL with ``ModuleNotFoundError`` until the Warrior ships
``src/bonfire/integrations/document.py``. That is the correct RED state.

Each test asserts on a single contract point so per-test progress is
visible test-by-test as the implementation lands.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Helpers — minimal well-formed payloads for happy-path construction
# ---------------------------------------------------------------------------


def _min_command_rule() -> dict:
    return {"kind": "command", "command": "gh"}


def _min_env_var_rule() -> dict:
    return {"kind": "env_var", "name": "GITHUB_TOKEN"}


def _min_file_match_rule() -> dict:
    return {"kind": "file_match", "path": ".git/config"}


def _min_python_import_rule() -> dict:
    return {"kind": "python_import", "module": "lancedb"}


def _min_ism_payload() -> dict:
    """Minimum-required-fields ISMDocument input dict."""
    return {
        "ism_version": 1,
        "name": "github",
        "display_name": "GitHub",
        "category": "forge",
        "summary": "GitHub forge for pull-request lifecycle.",
        "provides": ["pr.open"],
        "detection": [_min_command_rule()],
        "body": "",
    }


# ===========================================================================
# 1. ISMDocument — happy path
# ===========================================================================


class TestISMDocumentHappyPath:
    """Well-formed minimum-required-fields construction succeeds."""

    def test_minimum_required_fields_construct(self) -> None:
        """An ISMDocument with only required fields validates."""
        from bonfire.integrations.document import ISMDocument

        doc = ISMDocument(**_min_ism_payload())
        assert doc.name == "github"
        assert doc.ism_version == 1

    def test_body_field_round_trips(self) -> None:
        """``ISMDocument.body`` carries the raw markdown post-frontmatter."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["body"] = "# GitHub\n\n## Overview\nThe forge.\n"
        doc = ISMDocument(**payload)
        assert doc.body == "# GitHub\n\n## Overview\nThe forge.\n"

    def test_optional_fields_absent_ok(self) -> None:
        """``credentials``, ``fallback``, ``handler_hint`` are all optional."""
        from bonfire.integrations.document import ISMDocument

        doc = ISMDocument(**_min_ism_payload())
        assert doc.credentials is None
        assert doc.fallback is None
        assert doc.handler_hint is None


# ===========================================================================
# 2. ism_version — only 1 accepted in v1
# ===========================================================================


class TestISMVersionRule:
    """``ism_version`` must equal ``1``; future versions are rejected."""

    def test_ism_version_2_rejected(self) -> None:
        """``ism_version: 2`` raises Pydantic ValidationError."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["ism_version"] = 2
        with pytest.raises(ValidationError):
            ISMDocument(**payload)


# ===========================================================================
# 3. name — slug regex ^[a-z][a-z0-9_-]*$
# ===========================================================================


class TestNameSlugRule:
    """``name`` must match the slug regex; uppercase or leading-digit rejected."""

    def test_uppercase_name_rejected(self) -> None:
        """``GitHub`` (uppercase) violates the slug regex."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["name"] = "GitHub"
        with pytest.raises(ValidationError):
            ISMDocument(**payload)

    def test_leading_digit_name_rejected(self) -> None:
        """``1github`` (leading digit) violates the slug regex."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["name"] = "1github"
        with pytest.raises(ValidationError):
            ISMDocument(**payload)

    def test_lower_digit_underscore_hyphen_accepted(self) -> None:
        """``my-tool_2`` satisfies ``^[a-z][a-z0-9_-]*$``."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["name"] = "my-tool_2"
        doc = ISMDocument(**payload)
        assert doc.name == "my-tool_2"


# ===========================================================================
# 4. category — five canonical values
# ===========================================================================


class TestCategoryEnum:
    """``category`` is the closed enum: forge/ticketing/comms/vault/ide."""

    @pytest.mark.parametrize("value", ["forge", "ticketing", "comms", "vault", "ide"])
    def test_canonical_category_accepted(self, value: str) -> None:
        """Each of the five canonical values constructs successfully."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["category"] = value
        doc = ISMDocument(**payload)
        assert doc.category.value == value

    def test_nonsense_category_rejected(self) -> None:
        """A non-canonical category value raises ValidationError."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["category"] = "nonsense"
        with pytest.raises(ValidationError):
            ISMDocument(**payload)

    def test_ism_category_has_five_values(self) -> None:
        """``ISMCategory`` is a 5-value enum."""
        from bonfire.integrations.document import ISMCategory

        values = {member.value for member in ISMCategory}
        assert values == {"forge", "ticketing", "comms", "vault", "ide"}


# ===========================================================================
# 5. provides — non-empty + token regex
# ===========================================================================


class TestProvidesRule:
    """``provides`` must be a non-empty list of valid capability tokens."""

    def test_provides_empty_list_rejected(self) -> None:
        """An empty ``provides`` list raises ValidationError."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["provides"] = []
        with pytest.raises(ValidationError):
            ISMDocument(**payload)

    def test_provides_token_format_enforced(self) -> None:
        """A token that fails ``^[a-z][a-z0-9_.-]*$`` raises ValidationError."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["provides"] = ["PR.OPEN"]  # uppercase — invalid
        with pytest.raises(ValidationError):
            ISMDocument(**payload)


# ===========================================================================
# 6. detection — non-empty list, kind dispatch
# ===========================================================================


class TestDetectionList:
    """``detection`` must be a non-empty list of well-formed rules."""

    def test_detection_empty_list_rejected(self) -> None:
        """An empty ``detection`` list raises ValidationError."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["detection"] = []
        with pytest.raises(ValidationError):
            ISMDocument(**payload)


class TestDetectionRuleDispatch:
    """The discriminated union dispatches to the right concrete class per ``kind``."""

    def test_command_rule_constructs(self) -> None:
        """``kind: command`` constructs a CommandRule with ``command`` set."""
        from bonfire.integrations.document import CommandRule, ISMDocument

        payload = _min_ism_payload()
        payload["detection"] = [{"kind": "command", "command": "gh"}]
        doc = ISMDocument(**payload)
        rule = doc.detection[0]
        assert isinstance(rule, CommandRule)
        assert rule.command == "gh"

    def test_env_var_rule_constructs(self) -> None:
        """``kind: env_var`` constructs an EnvVarRule with ``name`` set."""
        from bonfire.integrations.document import EnvVarRule, ISMDocument

        payload = _min_ism_payload()
        payload["detection"] = [{"kind": "env_var", "name": "GITHUB_TOKEN"}]
        doc = ISMDocument(**payload)
        rule = doc.detection[0]
        assert isinstance(rule, EnvVarRule)
        assert rule.name == "GITHUB_TOKEN"

    def test_file_match_rule_constructs(self) -> None:
        """``kind: file_match`` constructs a FileMatchRule with ``path`` set."""
        from bonfire.integrations.document import FileMatchRule, ISMDocument

        payload = _min_ism_payload()
        payload["detection"] = [{"kind": "file_match", "path": ".git/config"}]
        doc = ISMDocument(**payload)
        rule = doc.detection[0]
        assert isinstance(rule, FileMatchRule)
        assert rule.path == ".git/config"

    def test_python_import_rule_constructs(self) -> None:
        """``kind: python_import`` constructs a PythonImportRule with ``module`` set."""
        from bonfire.integrations.document import ISMDocument, PythonImportRule

        payload = _min_ism_payload()
        payload["detection"] = [{"kind": "python_import", "module": "lancedb"}]
        doc = ISMDocument(**payload)
        rule = doc.detection[0]
        assert isinstance(rule, PythonImportRule)
        assert rule.module == "lancedb"

    def test_unknown_detection_kind_rejected(self) -> None:
        """A detection rule with ``kind: bogus`` raises ValidationError."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["detection"] = [{"kind": "bogus", "value": "x"}]
        with pytest.raises(ValidationError):
            ISMDocument(**payload)


# ===========================================================================
# 7. display_name + summary — non-empty strings
# ===========================================================================


class TestNonEmptyStringFields:
    """``display_name`` and ``summary`` must be non-empty."""

    def test_display_name_empty_rejected(self) -> None:
        """An empty ``display_name`` raises ValidationError."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["display_name"] = ""
        with pytest.raises(ValidationError):
            ISMDocument(**payload)

    def test_summary_empty_rejected(self) -> None:
        """An empty ``summary`` raises ValidationError."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["summary"] = ""
        with pytest.raises(ValidationError):
            ISMDocument(**payload)


# ===========================================================================
# 8. Frozen-model immutability + extra="forbid"
# ===========================================================================


class TestImmutabilityAndStrictExtras:
    """Frozen models reject mutation; unknown frontmatter keys are rejected."""

    def test_ism_document_is_frozen(self) -> None:
        """Mutating an ISMDocument field raises ValidationError."""
        from bonfire.integrations.document import ISMDocument

        doc = ISMDocument(**_min_ism_payload())
        with pytest.raises(ValidationError):
            doc.name = "other"

    def test_unknown_top_level_key_rejected(self) -> None:
        """Unknown top-level frontmatter keys raise ValidationError (extra='forbid')."""
        from bonfire.integrations.document import ISMDocument

        payload = _min_ism_payload()
        payload["unknown_field"] = "value"
        with pytest.raises(ValidationError):
            ISMDocument(**payload)


# ===========================================================================
# 9. ISMSchemaError — exported, distinguishable
# ===========================================================================


class TestISMSchemaError:
    """``ISMSchemaError`` is the loader's strict-path exception type."""

    def test_ism_schema_error_is_exception_subclass(self) -> None:
        """``ISMSchemaError`` is a subclass of ``Exception`` (catchable)."""
        from bonfire.integrations.document import ISMSchemaError

        assert issubclass(ISMSchemaError, Exception)

    def test_ism_schema_error_carries_message(self) -> None:
        """``ISMSchemaError(msg)`` round-trips its message via ``str(...)``."""
        from bonfire.integrations.document import ISMSchemaError

        err = ISMSchemaError("github: detection list is empty")
        assert "detection" in str(err)
