# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Three-layer naming vocabulary for Bonfire.

Layer 1 (generic): Code identifiers. Python class names, config keys,
    serialized JSONL fields. These are the API contract.
Layer 2 (professional): Default display names. CLI output, docs, website.
    Self-explanatory to strangers.
Layer 3 (gamified): Optional forge-themed display. Activated via persona
    config (--persona forge). Every metaphor teaches the system.

The persona module reads these maps to translate generic -> display.
Code always uses generic names. Display is a persona concern.
"""

from __future__ import annotations

from dataclasses import dataclass

__all__ = [
    "ROLE_DISPLAY",
    "PIPELINE_DISPLAY",
    "GAMIFICATION_DISPLAY",
    "ATMOSPHERE_DISPLAY",
    "TIER_DISPLAY",
    "DisplayNames",
]


@dataclass(frozen=True)
class DisplayNames:
    """Professional and gamified display names for a concept."""

    professional: str
    gamified: str


# ---------------------------------------------------------------------------
# Agent roles
# ---------------------------------------------------------------------------

ROLE_DISPLAY: dict[str, DisplayNames] = {
    "researcher": DisplayNames("Research Agent", "Scout"),
    "tester": DisplayNames("Test Agent", "Knight"),
    "implementer": DisplayNames("Build Agent", "Warrior"),
    "verifier": DisplayNames("Verify Agent", "Assayer"),
    "publisher": DisplayNames("Publish Agent", "Bard"),
    "reviewer": DisplayNames("Review Agent", "Wizard"),
    "closer": DisplayNames("Release Agent", "Herald"),
    "synthesizer": DisplayNames("Synthesis Agent", "Sage"),
    "analyst": DisplayNames("Analysis Agent", "Architect"),
}

# ---------------------------------------------------------------------------
# Pipeline concepts
# ---------------------------------------------------------------------------

PIPELINE_DISPLAY: dict[str, DisplayNames] = {
    "dispatch": DisplayNames("Run", "Stoke"),
    "pipeline": DisplayNames("Pipeline", "The Crucible"),
    "stage": DisplayNames("Stage", "Chamber"),
    "gate": DisplayNames("Quality Gate", "Trial"),
    "retry": DisplayNames("Revision", "Reforge"),
    "envelope": DisplayNames("Context Packet", "Envelope"),
    "workflow": DisplayNames("Workflow", "Battle Plan"),
}

# ---------------------------------------------------------------------------
# Gamification
# ---------------------------------------------------------------------------

GAMIFICATION_DISPLAY: dict[str, DisplayNames] = {
    "quality_score": DisplayNames("Quality Score", "Ember"),
    "token_usage": DisplayNames("Token Usage", "Fuel"),
    "consume": DisplayNames("Token Spend", "Burn"),
    "throughput": DisplayNames("Activity Level", "Heat"),
    "tier": DisplayNames("Proficiency Level", "Heat Color"),
    "checkpoint_restart": DisplayNames("Checkpoint Restart", "Reforge"),
    "pipeline_run": DisplayNames("Build Process", "Forging"),
}

# ---------------------------------------------------------------------------
# Atmosphere / meta
# ---------------------------------------------------------------------------

ATMOSPHERE_DISPLAY: dict[str, DisplayNames] = {
    "engine": DisplayNames("Bonfire Engine", "The Forge"),
    "persona": DisplayNames("Display Theme", "Persona"),
    "knowledge_store": DisplayNames("Knowledge Base", "The Vault"),
    "project_analysis": DisplayNames("Project Analysis", "Survey"),
    "success": DisplayNames("Pass", "Holds"),
    "failure": DisplayNames("Fail", "Cracks"),
}

# ---------------------------------------------------------------------------
# Tier progression
# ---------------------------------------------------------------------------

TIER_DISPLAY: dict[str, DisplayNames] = {
    "tier_1": DisplayNames("Bronze", "Spark"),
    "tier_2": DisplayNames("Silver", "Ember"),
    "tier_3": DisplayNames("Gold", "Flame"),
    "tier_4": DisplayNames("Platinum", "Blaze"),
    "tier_5": DisplayNames("Diamond", "Inferno"),
    "tier_6": DisplayNames("Master", "White Heat"),
}
