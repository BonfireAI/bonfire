# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Tests for the cadre subagent-contract surface."""

from __future__ import annotations

import pytest

from bonfire.cadre import (
    CADRE_CONTRACT_VERSION,
    PUBLISHABLE_ROLE_NAMES,
    UnknownCadreRoleError,
    iter_publishable_roles,
    resolve_role_prompt,
)


class TestContractVersion:
    def test_version_is_stamped(self) -> None:
        """Inaugural v1 contract version is a concrete semver string."""
        assert CADRE_CONTRACT_VERSION == "0.1.0"
        # semver shape: three dotted numbers
        parts = CADRE_CONTRACT_VERSION.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()


class TestPublishableRoles:
    def test_full_set(self) -> None:
        """v1 publishes 6 cadre roles plus the catch-all."""
        assert PUBLISHABLE_ROLE_NAMES == (
            "scout-innovative",
            "scout-conservative",
            "knight",
            "warrior",
            "sage",
            "wizard",
            "bonfire-powered",
        )

    def test_dual_scout_split_preserved(self) -> None:
        """Two Scout subagents ship (Innovative + Conservative), not one collapsed `scout`."""
        assert "scout-innovative" in PUBLISHABLE_ROLE_NAMES
        assert "scout-conservative" in PUBLISHABLE_ROLE_NAMES
        # No collapsed `scout` entry exists.
        assert "scout" not in PUBLISHABLE_ROLE_NAMES

    def test_iter_yields_in_order(self) -> None:
        names = list(iter_publishable_roles())
        assert names == list(PUBLISHABLE_ROLE_NAMES)


class TestResolveRolePrompt:
    @pytest.mark.parametrize("role_name", PUBLISHABLE_ROLE_NAMES)
    def test_returns_non_empty_body(self, role_name: str) -> None:
        body = resolve_role_prompt(role_name)
        assert isinstance(body, str)
        assert len(body) > 0

    def test_returns_scout_innovative_body(self) -> None:
        body = resolve_role_prompt("scout-innovative")
        assert "Innovative Scout" in body
        assert "WebSearch" in body

    def test_returns_warrior_body(self) -> None:
        body = resolve_role_prompt("warrior")
        assert "Warrior" in body
        assert "TDD" in body

    def test_returns_wizard_body(self) -> None:
        body = resolve_role_prompt("wizard")
        assert "Wizard" in body
        assert "workflow composer" in body.lower()

    def test_returns_bonfire_powered_body(self) -> None:
        body = resolve_role_prompt("bonfire-powered")
        assert "Bonfire-powered" in body or "Bonfire-Powered" in body

    def test_unknown_role_raises(self) -> None:
        with pytest.raises(UnknownCadreRoleError) as excinfo:
            resolve_role_prompt("nonexistent")
        assert "nonexistent" in str(excinfo.value)
        # Error names the publishable set so callers can recover.
        assert "scout-innovative" in str(excinfo.value)

    def test_unknown_cadre_role_error_subclasses_value_error(self) -> None:
        # Per Python convention: typed errors should subclass standard exception
        # families so generic except-handlers still catch them.
        assert issubclass(UnknownCadreRoleError, ValueError)
