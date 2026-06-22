# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""bonfire.integrations — Instruction Set Markup (ISM) v1.

Declarative third-party integrations for the bonfire pipeline. Each ISM
file is a markdown document with a YAML frontmatter block describing how
bonfire should detect, present, and consume an external tool (a forge, a
ticketing service, a comms target, a vault backend, an IDE surface).

The full file format and validation contract live in
``docs/specs/ism-v1.md``.

Public surface:
    * :class:`ISMDocument` — frontmatter + body container.
    * :class:`ISMCategory` — closed five-value category enum.
    * :class:`CommandRule`, :class:`EnvVarRule`,
      :class:`FileMatchRule`, :class:`PythonImportRule` — concrete
      detection-rule models.
    * :data:`DetectionRule` — discriminated-union type alias over the
      four detection-rule kinds.
    * :class:`Credentials`, :class:`Fallback` — optional sub-objects.
    * :class:`ISMSchemaError` — strict-path exception.
    * :class:`ISMLoader` — two-tier (builtin + user) discovery loader
      mirroring :class:`bonfire.persona.PersonaLoader`.
"""

from bonfire.integrations.document import (
    CommandRule,
    Credentials,
    DetectionRule,
    EnvVarRule,
    Fallback,
    FileMatchRule,
    ISMCategory,
    ISMDocument,
    ISMSchemaError,
    PythonImportRule,
)
from bonfire.integrations.loader import ISMLoader

__all__ = [
    "CommandRule",
    "Credentials",
    "DetectionRule",
    "EnvVarRule",
    "Fallback",
    "FileMatchRule",
    "ISMCategory",
    "ISMDocument",
    "ISMLoader",
    "ISMSchemaError",
    "PythonImportRule",
]
