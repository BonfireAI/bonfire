# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Re-export KnowledgeIngestConsumer into the events.consumers namespace."""

from __future__ import annotations

from bonfire.knowledge.consumer import KnowledgeIngestConsumer

__all__ = ["KnowledgeIngestConsumer"]
