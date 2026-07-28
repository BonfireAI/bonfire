# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""The options the Sage-correction stage dispatches with.

Split out of ``sage_correction_bounce`` because it is a value type, not
handler logic, and because what it has to get right is a contract with a
different module entirely -- ``ClaudeSDKBackend._do_execute``, which reads
eight attributes off whatever it is handed.

It used to be a standalone frozen dataclass carrying five fields, none of
them ``thinking_depth``. The backend read that first, so every Sage
dispatch raised ``AttributeError``; ``execute``'s blanket handler turned it
into a FAILED envelope, and the handler's own ``except`` turned that into a
COMPLETED "escalated" stage. A programming error reported success.

Subclassing :class:`~bonfire.protocols.DispatchOptions` rather than adding
the one missing field is deliberate. The other six absent attributes
included ``cwd`` -- an empty one makes the backend resolve
``setting_sources=["project"]`` and load the *target* repository's
``CLAUDE.md`` into the agent's prompt -- and ``security_hooks``. Patching
``thinking_depth`` alone would have traded a loud crash for a quiet trust
hole.

The contract is pinned in ``tests/unit/test_sage_dispatch_options_contract.py``,
which drives the real backend body rather than asserting on this class, so
an attribute the backend starts reading tomorrow fails there instead of
escalating silently in production.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from bonfire.agent.roles import AgentRole
from bonfire.protocols import DispatchOptions

__all__ = ["SAGE_CORRECTION_ALLOWED_TOOLS", "SageCorrectionDispatchOptions"]

#: Sage correction dispatch is scope-limited to xfail-decorator edits.
#: Immutable so a regression handing back a mutable ``set`` is caught at
#: construction. why: type-driven contract -- wrong tool sets are
#: unrepresentable.
SAGE_CORRECTION_ALLOWED_TOOLS: frozenset[str] = frozenset({"Read", "Edit"})


class SageCorrectionDispatchOptions(DispatchOptions):
    """A ``DispatchOptions`` carrying Sage's frozenset tool discipline.

    Frozen (inherited), so an accidental ``set(allowed_tools)`` cannot pass:
    the sage-correction axiom is "Sage edits xfail decorators only", and a
    frozenset of two members makes wrong tool sets unrepresentable.
    """

    allowed_tools: frozenset[str] = Field(
        default_factory=lambda: SAGE_CORRECTION_ALLOWED_TOOLS,
    )
    role: str = AgentRole.SYNTHESIZER.value
    permission_mode: Literal["default", "acceptEdits", "plan", "dontAsk"] = "dontAsk"
    correction_mode: bool = True
    missing_deps: frozenset[str] = Field(default_factory=frozenset)

    @model_validator(mode="after")
    def _mirror_allowed_tools_into_tools(self) -> SageCorrectionDispatchOptions:
        """Give the backend the tool list it reads.

        ``allowed_tools`` is the Sage-side discipline; ``tools`` is what the
        backend hands the SDK. Unlinked, the correction agent dispatched
        with no tools at all. An explicit ``tools=`` is left alone.
        """
        if not self.tools and self.allowed_tools:
            object.__setattr__(self, "tools", sorted(self.allowed_tools))
        return self
