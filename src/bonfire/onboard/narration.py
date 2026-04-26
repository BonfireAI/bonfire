"""Passelewe narration engine for scan discoveries.

Generates deadpan commentary lines that Passelewe speaks between scan
discoveries during the Front Door onboarding theater. Frequency, tone,
and escalation follow the Bastion narrator pattern.
"""

from __future__ import annotations

import random

from bonfire.onboard.protocol import PasseleweMessage, ScanUpdate

__all__ = ["NarrationEngine"]

# ---------------------------------------------------------------------------
# Tier classification sets
# ---------------------------------------------------------------------------

# Values (lowercased) that trigger Tier 3 — always narrate.
TIER_3_VALUES: frozenset[str] = frozenset({"docker", "terraform", "kubectl", "cargo", "go", "rust"})

# Labels (lowercased) that trigger Tier 2 — narrate ~50%.
TIER_2_LABELS: frozenset[str] = frozenset({"framework", "ci", "test config", "mcp"})

# ---------------------------------------------------------------------------
# Line library — keyed by category slug
# ---------------------------------------------------------------------------

_LINES: dict[str, list[str]] = {
    # Languages
    "python": [
        "Python. Naturally. The default tongue.",
        "Python again. The comfortable choice.",
        "Another Python project. No surprises here.",
    ],
    "go": [
        "Go. The quiet pragmatic one.",
        "Go. Concurrency and strong opinions.",
    ],
    "rust": [
        "Rust. Ambitious taste for a forge.",
        "Rust. The compiler will judge you.",
    ],
    "javascript": [
        "JavaScript. Of course it is.",
        "JavaScript. The ubiquitous tongue speaks.",
    ],
    "typescript": [
        "TypeScript. Discipline chosen over freedom.",
        "TypeScript. Types have weight here.",
    ],
    # Frameworks (Tier 2)
    "framework": [
        "FastAPI. Modern taste in frameworks.",
        "Django. The old guard stands firm.",
        "React. Busy hands at the front.",
        "Flask. Minimalism noted and respected.",
        "A framework with opinions. Like everyone.",
        "The architecture takes shape around this.",
    ],
    # CI (Tier 2)
    "ci": [
        "CI configured. The walls are watched.",
        "Automated gates. Discipline lives in pipes.",
        "The pipeline guards the gate well.",
    ],
    # Test config (Tier 2)
    "test_config": [
        "Tests present. That is a good sign.",
        "Testing configured. Trust but verify indeed.",
        "The safety net exists. Wise choice.",
    ],
    # MCP (Tier 2)
    "mcp": [
        "MCP. Extensions of the mind itself.",
        "A server that speaks to servers.",
        "Tools that reach beyond the terminal.",
    ],
    "mcp_escalation": [
        "Another server. The collection only grows.",
        "More extensions. The reach keeps widening.",
        "Yet another one. The web expands.",
    ],
    # Tools — Tier 1 (rare narration)
    "tool_common": [
        "The usual suspects are all here.",
        "Well equipped for the work ahead.",
        "Standard issue. Nothing to report here.",
        "The toolbox fills up as expected.",
        "Familiar tools in familiar places found.",
    ],
    # Tools — Tier 3 (always narrate)
    "docker": [
        "Docker. The forge runs deep here.",
        "Containers. Worlds built within other worlds.",
        "Docker. Isolation elevated to architecture now.",
    ],
    "terraform": [
        "Terraform. Building worlds from declarations.",
        "Infrastructure as intent. Ambitious scope.",
        "Terraform. The ground shifts to plan.",
    ],
    "kubectl": [
        "kubectl. Orchestrating the orchestrators now.",
        "Kubernetes. The fleet awaits its orders.",
        "kubectl. Commanding the armada from here.",
    ],
    "cargo": [
        "Cargo. The Rust supply line runs.",
        "Cargo. All dependencies catalogued and ready.",
    ],
    # Claude memory
    "claude_memory": [
        "The memory runs deep in here.",
        "A well-documented mind. Good instincts.",
        "Context preserved across many sessions here.",
        "Claude remembers. A map of territory.",
    ],
    # Git
    "git": [
        "Clean tree. Discipline speaks through absence.",
        "Changes pending. The work continues still.",
        "Git configured. History matters to someone.",
        "Version control. The ledger of intent.",
    ],
    # Vault / docs
    "vault": [
        "Documentation found. The trail is marked.",
        "The project documents its own existence.",
        "Seeds for the vault. Good material.",
    ],
    # General (fallback) — always available
    "general": [
        "Noted. The ledger grows by one.",
        "Not what I expected to find.",
        "The picture forms piece by piece.",
        "So it goes. One more entry.",
        "The pattern emerges from the noise.",
        "One more piece of the puzzle.",
        "The mosaic grows more complete now.",
        "Filed away for future reference here.",
        "The forge takes note of this.",
        "Another data point. The picture sharpens.",
    ],
    # Escalation (generic repeat)
    "escalation": [
        "Another one. The collection only grows.",
        "More of the same. Remarkably consistent.",
        "A theme develops across these findings.",
        "The pattern repeats itself once more.",
        "Familiar ground. We have been here.",
    ],
}


def _category_key(event: ScanUpdate) -> str:
    """Derive a line-library category key from a scan event."""
    label_lower = event.label.lower()
    value_lower = event.value.lower()

    # Tier 3 specific tools
    for tool in ("docker", "terraform", "kubectl", "cargo"):
        if tool in label_lower or tool in value_lower:
            return tool

    # Languages
    for lang in ("python", "go", "rust", "javascript", "typescript"):
        if lang in label_lower or lang in value_lower:
            return lang

    # Tier 2 by label
    if label_lower == "framework" or "framework" in value_lower:
        return "framework"
    if label_lower == "ci":
        return "ci"
    if label_lower == "test config":
        return "test_config"
    if label_lower == "mcp" or event.panel == "mcp_servers":
        return "mcp"

    # Panels
    if event.panel == "claude_memory":
        return "claude_memory"
    if event.panel == "git_state":
        return "git"
    if event.panel == "vault_seed":
        return "vault"

    return "tool_common"


class NarrationEngine:
    """Generates Passelewe narration for scan discoveries.

    Stateful per session: tracks used lines, discovery count, and
    repeated categories to follow the Bastion narrator pattern.
    """

    def __init__(self) -> None:
        self._used: set[str] = set()
        self._discovery_count: int = 0
        self._seen_categories: dict[str, int] = {}

    def get_tier(self, event: ScanUpdate) -> int:
        """Classify a discovery as Tier 1 (common), 2 (notable), or 3 (surprising)."""
        label_lower = event.label.lower()
        value_lower = event.value.lower()

        # Tier 3: surprising tools (check both label and value)
        if label_lower in TIER_3_VALUES or value_lower in TIER_3_VALUES:
            return 3

        # Tier 2: notable labels
        if label_lower in TIER_2_LABELS:
            return 2

        # Everything else
        return 1

    def should_narrate(self, event: ScanUpdate) -> bool:
        """Decide whether this discovery warrants narration.

        Uses the current ``_discovery_count`` (must be incremented by
        the caller or by ``get_narration``).
        """
        tier = self.get_tier(event)
        if tier == 3:
            return True
        if tier == 2:
            return self._discovery_count % 3 == 0
        # Tier 1
        return self._discovery_count % 4 == 0

    def get_narration(self, event: ScanUpdate) -> PasseleweMessage | None:
        """Get narration for a discovery, or None if skipping.

        Increments discovery count, checks tier frequency, selects a
        line, tracks used lines, and handles escalation on repeated
        categories.  Returns ``PasseleweMessage`` with
        ``subtype="narration"``.
        """
        self._discovery_count += 1

        if not self.should_narrate(event):
            return None

        category = _category_key(event)

        # Track category repetitions
        self._seen_categories[category] = self._seen_categories.get(category, 0) + 1
        is_repeat = self._seen_categories[category] > 1

        line = self._select_line(category, is_repeat)
        if line is None:
            return None  # pragma: no cover — defensive

        self._used.add(line)
        return PasseleweMessage(text=line, subtype="narration")

    def _select_line(self, category: str, is_repeat: bool) -> str | None:
        """Pick an unused line from the category, escalation, or fallback."""
        # On repeat, try escalation pool for this category first
        if is_repeat:
            escalation_key = f"{category}_escalation"
            line = self._pick_unused(escalation_key)
            if line is not None:
                return line
            # Generic escalation
            line = self._pick_unused("escalation")
            if line is not None:
                return line

        # Primary category
        line = self._pick_unused(category)
        if line is not None:
            return line

        # Fallback to general
        line = self._pick_unused("general")
        if line is not None:
            return line

        # Absolute last resort — everything exhausted (very unlikely)
        return f"Discovery number {self._discovery_count}. The forge takes note."

    def _pick_unused(self, key: str) -> str | None:
        """Return a random unused line from the given library key, or None."""
        pool = _LINES.get(key, [])
        available = [line for line in pool if line not in self._used]
        if not available:
            return None
        return random.choice(available)
