# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Canonical agent role definitions for Bonfire.

The StrEnum value IS the serialized form IS the config key IS the grep target.
One string, everywhere. No translation layers.

Display names (professional and gamified) live in the naming module,
not here. This module defines the code-layer identity only.
"""

from enum import StrEnum

__all__ = ["AgentRole"]


class AgentRole(StrEnum):
    """Agent roles in the Bonfire pipeline.

    Values are the canonical serialized form -- used in JSONL,
    TOML config, CLI output, and grep patterns.

    Mapping to display names:
        researcher  -> Research Agent  / Scout
        tester      -> Test Agent      / Knight
        implementer -> Build Agent     / Warrior
        verifier    -> Verify Agent    / Cleric
        publisher   -> Publish Agent   / Bard
        reviewer    -> Review Agent    / Wizard
        closer      -> Release Agent   / Steward
        synthesizer -> Synthesis Agent / Sage
        analyst     -> Analysis Agent  / Architect
    """

    RESEARCHER = "researcher"
    TESTER = "tester"
    IMPLEMENTER = "implementer"
    VERIFIER = "verifier"
    PUBLISHER = "publisher"
    REVIEWER = "reviewer"
    CLOSER = "closer"
    SYNTHESIZER = "synthesizer"
    ANALYST = "analyst"
