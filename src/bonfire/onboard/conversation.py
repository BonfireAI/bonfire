# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Falcor conversation engine — scripted 3-question profiling.

Three questions map user responses to profile dimensions via keyword/pattern
matching. Reflections invite correction; short answers are acknowledged
gracefully.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from bonfire.onboard.protocol import (
    ConversationStart,
    FalcorMessage,
    FrontDoorMessage,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = ["ConversationEngine"]


# ---------------------------------------------------------------------------
# Question definitions
# ---------------------------------------------------------------------------

_Q1_TEXT = (
    "The scan sees your tools. I'd rather hear about the work. "
    "Tell me about the last thing you built that you were proud of."
)
_Q2_TEXT = "When you start something entirely new — what happens first?"
_Q3_TEXT = "One more. What do your current tools get wrong about you?"

_QUESTIONS = [_Q1_TEXT, _Q2_TEXT, _Q3_TEXT]

# Short-answer threshold (word count).
_SHORT_THRESHOLD = 3

_BRIEF_REFLECTION = "Brief. That tells me something too."


# ---------------------------------------------------------------------------
# Q1 analysis
# ---------------------------------------------------------------------------


def _analyze_q1(text: str) -> tuple[str, dict[str, str]]:
    """Analyze Q1 answer: process/result/team focus.

    Returns (reflection_text, profile_dimensions).
    """
    lower = text.lower()
    words = lower.split()
    profile: dict[str, str] = {}

    # Team vs solo detection
    team_words = {
        "we",
        "team",
        "together",
        "everyone",
        "group",
        "our",
        "us",
    }
    solo_words = {"i", "me", "my", "myself"}
    team_count = sum(1 for w in words if w.strip(".,!?;:'\"") in team_words)
    solo_count = sum(1 for w in words if w.strip(".,!?;:'\"") in solo_words)

    # Result vs process keywords
    result_kw = {
        "ship",
        "shipped",
        "deploy",
        "deployed",
        "prod",
        "production",
        "launched",
        "released",
        "done",
        "finished",
        "delivered",
    }
    process_kw = {
        "process",
        "iterating",
        "building",
        "learning",
        "journey",
        "evolving",
        "crafting",
        "refining",
        "loved",
    }
    test_kw = {"test", "tests", "testing", "green", "coverage", "tdd"}

    has_result = any(w.strip(".,!?;:'\"") in result_kw for w in words)
    has_process = any(w.strip(".,!?;:'\"") in process_kw for w in words)
    has_test = any(w.strip(".,!?;:'\"") in test_kw for w in words)

    # Goal visibility: in_your_face vs in_the_vision
    in_your_face_kw = {
        "now",
        "urgent",
        "immediate",
        "today",
        "tactical",
        "hands-on",
        "deadline",
    }
    in_the_vision_kw = {
        "vision",
        "dream",
        "imagine",
        "purpose",
        "mission",
        "impact",
        "future",
        "ambition",
    }
    has_in_your_face = any(w.strip(".,!?;:'\"") in in_your_face_kw for w in words)
    has_in_the_vision = any(w.strip(".,!?;:'\"") in in_the_vision_kw for w in words)

    # Determine reflection and profile
    if team_count > solo_count:
        reflection = "The castle stands on many shoulders, then."
        profile["companion_mode"] = "friend"
        profile["energy_type"] = "bonfire"
    elif has_result and not has_process:
        reflection = "You know when it's done. That's rarer than you'd think."
        profile["companion_mode"] = "foe"
        profile["goal_visibility"] = "horizon"
        profile["energy_type"] = "wildfire"
    elif has_process or has_test:
        reflection = "The building mattered more than the building being finished. Noted."
        profile["companion_mode"] = "friend"
        profile["goal_visibility"] = "in_the_process"
        profile["energy_type"] = "pilot_light"
    else:
        # Default: result-oriented
        reflection = "You know when it's done. That's rarer than you'd think."
        profile["companion_mode"] = "friend"
        profile["goal_visibility"] = "horizon"
        profile["energy_type"] = "bonfire"

    # Override goal_visibility if explicit urgency/vision keywords detected
    if has_in_your_face:
        profile["goal_visibility"] = "in_your_face"
    elif has_in_the_vision:
        profile["goal_visibility"] = "in_the_vision"

    # Attention topology from sentence structure
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    avg_words = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
    if len(sentences) >= 3 and avg_words < 10:
        profile["attention_topology"] = "many_tabs"
    elif len(sentences) <= 2 and avg_words > 12:
        profile["attention_topology"] = "deep_tunnel"
    else:
        profile["attention_topology"] = "oscillating"

    return reflection, profile


# ---------------------------------------------------------------------------
# Q2 analysis
# ---------------------------------------------------------------------------


def _analyze_q2(text: str) -> tuple[str, dict[str, str]]:
    """Analyze Q2 answer: planner/explorer/just-go."""
    lower = text.lower()
    words = lower.split()
    profile: dict[str, str] = {}

    plan_kw = {
        "plan",
        "design",
        "architecture",
        "blueprint",
        "outline",
        "spec",
        "diagram",
        "sketch",
        "whiteboard",
        "organize",
    }
    explore_kw = {
        "explore",
        "research",
        "look",
        "read",
        "investigate",
        "survey",
        "browse",
        "study",
        "options",
    }
    justgo_kw = {
        "just",
        "dove",
        "jumped",
        "started",
        "hack",
        "code",
        "coding",
        "write",
        "writing",
        "build",
    }

    has_plan = any(w.strip(".,!?;:'\"") in plan_kw for w in words)
    has_explore = any(w.strip(".,!?;:'\"") in explore_kw for w in words)

    # Prioritize: just-go phrases first (they overlap with others)
    justgo_phrases = [
        "just started",
        "dove in",
        "jumped",
        "code first",
        "start coding",
        "start building",
    ]
    has_justgo_phrase = any(p in lower for p in justgo_phrases)
    has_justgo = any(w.strip(".,!?;:'\"") in justgo_kw for w in words)

    if has_justgo_phrase or (has_justgo and not has_plan and not has_explore):
        reflection = "Code first, questions later. The forges will be busy."
        profile["uncertainty_orientation"] = "just_go"
        profile["energy_type"] = "wildfire"
    elif has_plan:
        reflection = "A blueprint person. The walls go up in order."
        profile["uncertainty_orientation"] = "blueprint"
        profile["energy_type"] = "pilot_light"
    elif has_explore:
        reflection = "You walk the land before you build on it. Wise."
        profile["uncertainty_orientation"] = "show_options"
        profile["energy_type"] = "bonfire"
    else:
        # Default: show_options
        reflection = "You walk the land before you build on it. Wise."
        profile["uncertainty_orientation"] = "show_options"

    # Attention topology reinforcement
    sentences = [s.strip() for s in re.split(r"[.!?]+", text) if s.strip()]
    avg_words = sum(len(s.split()) for s in sentences) / max(len(sentences), 1)
    if len(sentences) >= 3 and avg_words < 10:
        profile["attention_topology"] = "many_tabs"
    elif len(sentences) <= 2 and avg_words > 12:
        profile["attention_topology"] = "deep_tunnel"

    return reflection, profile


# ---------------------------------------------------------------------------
# Q3 analysis
# ---------------------------------------------------------------------------


def _analyze_q3(text: str) -> tuple[str, dict[str, str]]:
    """Analyze Q3 answer: speed/noise/control/understanding."""
    lower = text.lower()
    profile: dict[str, str] = {}

    speed_kw = {
        "slow",
        "fast",
        "speed",
        "quick",
        "wait",
        "waiting",
        "forever",
        "laggy",
        "performance",
    }
    noise_kw = {
        "noise",
        "noisy",
        "loud",
        "clutter",
        "cluttered",
        "notifications",
        "distract",
        "distracting",
        "overwhelming",
    }
    control_kw = {
        "opinionated",
        "control",
        "rigid",
        "flexible",
        "freedom",
        "own",
        "myself",
        "customiz",
        "config",
    }
    understand_kw = {
        "understand",
        "listen",
        "context",
        "know",
        "aware",
        "misunderstand",
        "ignore",
        "ignoring",
    }

    words = lower.split()
    score_speed = sum(1 for w in words if any(w.strip(".,!?;:'\"").startswith(k) for k in speed_kw))
    score_noise = sum(1 for w in words if any(w.strip(".,!?;:'\"").startswith(k) for k in noise_kw))
    score_control = sum(
        1 for w in words if any(w.strip(".,!?;:'\"").startswith(k) for k in control_kw)
    )
    score_understand = sum(
        1 for w in words if any(w.strip(".,!?;:'\"").startswith(k) for k in understand_kw)
    )

    scores = {
        "speed": score_speed,
        "noise": score_noise,
        "control": score_control,
        "understanding": score_understand,
    }
    winner = max(scores, key=lambda k: scores[k])

    if scores[winner] == 0:
        # No signal — default to understanding
        winner = "understanding"

    reflections = {
        "speed": ("Too slow. The fire burns faster than the tools can follow."),
        "noise": ("Too loud. You want the signal without the noise."),
        "control": ("Too opinionated. You'd rather hold the hammer yourself."),
        "understanding": ("They don't listen. That's what we're fixing."),
    }

    pain_map = {
        "speed": "latency",
        "noise": "information_overload",
        "control": "rigidity",
        "understanding": "poor_context",
    }

    profile["pain_point"] = pain_map[winner]

    return reflections[winner], profile


# ---------------------------------------------------------------------------
# Analysis dispatch
# ---------------------------------------------------------------------------

_ANALYZERS: list[Callable[[str], tuple[str, dict[str, str]]]] = [
    _analyze_q1,
    _analyze_q2,
    _analyze_q3,
]


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


@dataclass
class ConversationEngine:
    """Scripted 3-question conversation for profiling."""

    _turn: int = 0  # 0=not started, 1-3=waiting for answer to Q1-Q3
    _profile: dict[str, str] = field(default_factory=dict)

    @property
    def is_complete(self) -> bool:
        """True when all 3 questions have been answered."""
        return self._turn > 3

    @property
    def profile(self) -> dict[str, str]:
        """Accumulated profile dimensions."""
        return dict(self._profile)

    async def start(
        self,
        emit: Callable[[FrontDoorMessage], Awaitable[None]],
    ) -> None:
        """Emit ConversationStart + first question."""
        await emit(ConversationStart())
        await emit(FalcorMessage(text=_QUESTIONS[0], subtype="question"))
        self._turn = 1

    async def handle_answer(
        self,
        text: str,
        emit: Callable[[FrontDoorMessage], Awaitable[None]],
    ) -> None:
        """Process answer: analyze, reflect, ask next or finish."""
        if self._turn == 0:
            msg = "Cannot handle answer before start() has been called."
            raise RuntimeError(msg)
        if self._turn > 3:
            msg = "Conversation is already complete."
            raise RuntimeError(msg)

        question_index = self._turn - 1  # 0-based

        # Short answer detection
        stripped = text.strip()
        word_count = len(stripped.split()) if stripped else 0

        if word_count < _SHORT_THRESHOLD:
            reflection_text = _BRIEF_REFLECTION
            profile_update: dict[str, str] = {}
        else:
            analyzer = _ANALYZERS[question_index]
            reflection_text, profile_update = analyzer(stripped)

        # Emit reflection
        await emit(
            FalcorMessage(
                text=reflection_text,
                subtype="reflection",
            )
        )

        # Accumulate profile
        for k, v in profile_update.items():
            self._profile[k] = v

        # Advance turn
        self._turn += 1

        # Ask next question if not done
        if self._turn <= 3:
            await emit(
                FalcorMessage(
                    text=_QUESTIONS[self._turn - 1],
                    subtype="question",
                )
            )

        # If complete, ensure all expected keys have defaults
        if self._turn > 3:
            self._ensure_complete_profile()

    def _ensure_complete_profile(self) -> None:
        """Fill in any missing profile keys with sensible defaults."""
        defaults = {
            "companion_mode": "friend",
            "goal_visibility": "horizon",
            "energy_type": "bonfire",
            "attention_topology": "oscillating",
            "uncertainty_orientation": "show_options",
            "pain_point": "poor_context",
        }
        for key, default in defaults.items():
            if key not in self._profile:
                self._profile[key] = default
