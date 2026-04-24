"""Re-export KnowledgeIngestConsumer into the events.consumers namespace."""

from __future__ import annotations

from bonfire.knowledge.consumer import KnowledgeIngestConsumer

__all__ = ["KnowledgeIngestConsumer"]
