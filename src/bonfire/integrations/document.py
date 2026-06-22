# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""ISM v1 frontmatter schema — Pydantic models for declarative integrations.

Backs the loader's parsing contract. Every model is frozen with
``extra='forbid'``: ISM v1 is a closed schema, additions go through
ISM v2 per ``docs/specs/ism-v1.md`` §12.

The detection-rule discriminated union routes a YAML mapping to the
right concrete class by its ``kind`` field. Unknown kinds, unknown
top-level keys, and unknown sub-object keys all raise
:class:`pydantic.ValidationError` at construction time, which the
loader's strict path wraps in :class:`ISMSchemaError`.

Spec: ``docs/specs/ism-v1.md`` §3, §4, §7.
"""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# Regexes — slug + capability-token shapes (spec §3, §7).
# ---------------------------------------------------------------------------

_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")
_PROVIDES_TOKEN_PATTERN = re.compile(r"^[a-z][a-z0-9_.-]*$")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ISMSchemaError(ValueError):
    """Raised by :meth:`ISMLoader.validate` for a malformed ISM document.

    Inherits from :class:`ValueError` so callers handling generic
    data-shape errors keep working while ISM-specific catches get
    richer context.
    """


# ---------------------------------------------------------------------------
# Category enum (spec §3, §4 — five canonical values)
# ---------------------------------------------------------------------------


class ISMCategory(StrEnum):
    """Closed enum of integration categories per spec §3."""

    FORGE = "forge"
    TICKETING = "ticketing"
    COMMS = "comms"
    VAULT = "vault"
    IDE = "ide"


# ---------------------------------------------------------------------------
# Detection-rule models — discriminated union by ``kind``.
# ---------------------------------------------------------------------------


class CommandRule(BaseModel):
    """Detection probe: invoke a CLI binary and check its exit code.

    Spec §4.1.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["command"]
    command: str
    args: list[str] = Field(default_factory=list)
    expect_exit: int = 0

    @field_validator("command")
    @classmethod
    def _command_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("CommandRule.command must be non-empty")
        return value


class EnvVarRule(BaseModel):
    """Detection probe: read an environment variable.

    Spec §4.2.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["env_var"]
    name: str
    required: bool = False

    @field_validator("name")
    @classmethod
    def _name_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("EnvVarRule.name must be non-empty")
        return value


class FileMatchRule(BaseModel):
    """Detection probe: stat a path and optionally regex-match its content.

    Spec §4.3.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["file_match"]
    path: str
    pattern: str | None = None

    @field_validator("path")
    @classmethod
    def _path_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("FileMatchRule.path must be non-empty")
        return value


class PythonImportRule(BaseModel):
    """Detection probe: ``importlib.util.find_spec(module)``.

    Spec §4.4.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    kind: Literal["python_import"]
    module: str

    @field_validator("module")
    @classmethod
    def _module_non_empty(cls, value: str) -> str:
        if not value:
            raise ValueError("PythonImportRule.module must be non-empty")
        return value


# Discriminated-union type alias. Pydantic uses ``kind`` to route a
# raw dict into the right concrete class and rejects unknown values.
DetectionRule = Annotated[
    CommandRule | EnvVarRule | FileMatchRule | PythonImportRule,
    Field(discriminator="kind"),
]


# ---------------------------------------------------------------------------
# Optional sub-objects (spec §3)
# ---------------------------------------------------------------------------


class Credentials(BaseModel):
    """Welcomer hint — env vars + auth command for credentialed setup."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    env_vars: list[str] = Field(default_factory=list)
    auth_command: str = ""


class Fallback(BaseModel):
    """Welcomer hint — message + install URL when detection fails."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    missing_message: str = ""
    install_url: str = ""


# ---------------------------------------------------------------------------
# Top-level document
# ---------------------------------------------------------------------------


class ISMDocument(BaseModel):
    """Top-level ISM v1 frontmatter + body container.

    Spec §3 lists every field; spec §7 lists every validation rule.
    Frozen and ``extra='forbid'``: unknown frontmatter keys are
    rejected at construction time.

    The ``body`` field carries the raw markdown content found after the
    closing frontmatter delimiter. The loader populates it; manual
    construction supplies it explicitly (default ``""``).
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    ism_version: Literal[1]
    name: str
    display_name: str
    category: ISMCategory
    summary: str
    provides: list[str]
    detection: list[DetectionRule]
    credentials: Credentials | None = None
    fallback: Fallback | None = None
    handler_hint: str | None = None
    body: str = ""

    # ------------------------------------------------------------------
    # Field validators — spec §7 rules 2, 3, 5, 6, 7.
    # ------------------------------------------------------------------

    @field_validator("name")
    @classmethod
    def _name_matches_slug_regex(cls, value: str) -> str:
        if not _NAME_PATTERN.match(value):
            raise ValueError(
                f"name {value!r} must match ^[a-z][a-z0-9_-]*$ (lowercase, starting with a letter)"
            )
        return value

    @field_validator("display_name")
    @classmethod
    def _display_name_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("display_name must be non-empty")
        return value

    @field_validator("summary")
    @classmethod
    def _summary_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("summary must be non-empty")
        return value

    @field_validator("provides")
    @classmethod
    def _provides_non_empty_and_token_shape(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("provides must be a non-empty list of capability tokens")
        for token in value:
            if not isinstance(token, str) or not _PROVIDES_TOKEN_PATTERN.match(token):
                raise ValueError(f"provides token {token!r} must match ^[a-z][a-z0-9_.-]*$")
        return value

    @field_validator("detection")
    @classmethod
    def _detection_non_empty(cls, value: list[DetectionRule]) -> list[DetectionRule]:
        if not value:
            raise ValueError("detection must be a non-empty list of rules")
        return value
