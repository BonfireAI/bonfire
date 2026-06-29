# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""Session state management and JSONL persistence."""

from bonfire.session.handoff_doc import render_handoff
from bonfire.session.persistence import SessionPersistence
from bonfire.session.state import SessionState
from bonfire.session.store import (
    CHECKPOINT_DIR_ENV_VAR,
    DEFAULT_CHECKPOINT_DIR,
    SessionStore,
)

__all__ = [
    "CHECKPOINT_DIR_ENV_VAR",
    "DEFAULT_CHECKPOINT_DIR",
    "SessionPersistence",
    "SessionState",
    "SessionStore",
    "render_handoff",
]
