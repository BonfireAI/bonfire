# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""ISMLoader — two-tier discovery of Instruction Set Markup files.

Discovery order:
  1. ``user_dir/{name}.ism.md``   (highest priority — project override)
  2. ``builtin_dir/{name}.ism.md``  (bundled reference adapter)

Two methods split the total/strict responsibilities, mirroring
:class:`bonfire.persona.PersonaLoader`:
  * :meth:`ISMLoader.load` — total. Returns ``ISMDocument`` or ``None``.
    Logs WARNING on every failure path. Never raises.
  * :meth:`ISMLoader.validate` — strict. Raises
    :class:`ISMSchemaError` describing the first failure.

File-extension discipline: only files whose name ends in ``.ism.md`` are
visible to the loader. Plain ``.md`` files are ignored.

Frontmatter format: a YAML block delimited by lines containing exactly
``---``. Everything between the delimiters is parsed as YAML; everything
after the closing delimiter is preserved as the markdown body and
populated onto :attr:`ISMDocument.body`.

Spec: ``docs/specs/ism-v1.md`` §7, §8.
"""

from __future__ import annotations

import logging
from pathlib import Path  # noqa: TC003 — runtime constructor type

import yaml
from pydantic import ValidationError

from bonfire.integrations.document import ISMDocument, ISMSchemaError

logger = logging.getLogger(__name__)

_ISM_SUFFIX = ".ism.md"
_FRONTMATTER_DELIMITER = "---"


class ISMLoader:
    """Two-tier loader for ISM v1 documents."""

    def __init__(self, builtin_dir: Path, user_dir: Path) -> None:
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir

    # ------------------------------------------------------------------
    # Public: load() — total, never raises
    # ------------------------------------------------------------------

    def load(self, name: str) -> ISMDocument | None:
        """Load an ISM document by name; return ``None`` on any failure.

        Discovery order: ``user_dir`` first, then ``builtin_dir``. Every
        failure mode (missing file, malformed YAML, missing frontmatter,
        schema violation, IO error) returns ``None`` and emits a
        WARNING describing the failure with the integration's name.

        This method is total. It never raises.
        """
        path = self._find_ism_file(name)
        if path is None:
            logger.warning("ISM %r not found in user_dir or builtin_dir", name)
            return None

        try:
            raw_text = path.read_text()
        except OSError as exc:
            logger.warning("ISM %r: could not be read: %s", name, exc)
            return None

        frontmatter_text, body = self._split_frontmatter(raw_text)
        if frontmatter_text is None:
            logger.warning("ISM %r: missing frontmatter delimiters", name)
            return None

        try:
            data = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as exc:
            logger.warning("ISM %r: malformed YAML frontmatter: %s", name, exc)
            return None

        if not isinstance(data, dict):
            logger.warning(
                "ISM %r: frontmatter must be a YAML mapping at the top level",
                name,
            )
            return None

        data["body"] = body

        try:
            return ISMDocument(**data)
        except ValidationError as exc:
            logger.warning("ISM %r: schema violation: %s", name, exc)
            return None

    # ------------------------------------------------------------------
    # Public: validate() — strict, raises ISMSchemaError
    # ------------------------------------------------------------------

    def validate(self, name: str) -> None:
        """Strictly validate an ISM document.

        Raises :class:`ISMSchemaError` describing the first failure
        (missing file, malformed YAML, missing frontmatter, schema
        violation, IO error).
        """
        path = self._find_ism_file(name)
        if path is None:
            raise ISMSchemaError(f"ISM {name!r} not found in user_dir or builtin_dir")

        try:
            raw_text = path.read_text()
        except OSError as exc:
            raise ISMSchemaError(f"ISM {name!r}: could not be read: {exc}") from exc

        frontmatter_text, body = self._split_frontmatter(raw_text)
        if frontmatter_text is None:
            raise ISMSchemaError(
                f"ISM {name!r}: missing frontmatter delimiters (expected lines of exactly '---')"
            )

        try:
            data = yaml.safe_load(frontmatter_text)
        except yaml.YAMLError as exc:
            raise ISMSchemaError(f"ISM {name!r}: malformed YAML frontmatter: {exc}") from exc

        if not isinstance(data, dict):
            raise ISMSchemaError(
                f"ISM {name!r}: frontmatter must be a YAML mapping at the top level"
            )

        data["body"] = body

        try:
            ISMDocument(**data)
        except ValidationError as exc:
            raise ISMSchemaError(f"ISM {name!r}: schema violation: {exc}") from exc

    # ------------------------------------------------------------------
    # Public: available() — deduplicated, sorted union
    # ------------------------------------------------------------------

    def available(self) -> list[str]:
        """Return a deduplicated, sorted list of ISM names from both dirs."""
        names: set[str] = set()
        for d in (self._builtin_dir, self._user_dir):
            if not d.is_dir():
                continue
            for child in d.iterdir():
                if child.is_file() and child.name.endswith(_ISM_SUFFIX):
                    names.add(child.name[: -len(_ISM_SUFFIX)])
        return sorted(names)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_ism_file(self, name: str) -> Path | None:
        """Return the first ``{name}.ism.md`` found; user-dir wins."""
        filename = f"{name}{_ISM_SUFFIX}"
        for base in (self._user_dir, self._builtin_dir):
            candidate = base / filename
            if candidate.is_file():
                return candidate
        return None

    @staticmethod
    def _split_frontmatter(raw_text: str) -> tuple[str | None, str]:
        """Split a markdown text into (frontmatter_yaml, body).

        Frontmatter is delimited by lines containing exactly ``---``.
        Returns ``(None, "")`` if the document has no opening delimiter
        on the first non-empty content line, or no closing delimiter.
        """
        lines = raw_text.splitlines(keepends=True)

        # Find the opening delimiter — must be the first non-blank line
        # to count as a frontmatter block.
        i = 0
        while i < len(lines) and lines[i].strip() == "":
            i += 1
        if i >= len(lines) or lines[i].rstrip("\r\n") != _FRONTMATTER_DELIMITER:
            return None, ""

        opening = i
        # Find the closing delimiter.
        for j in range(opening + 1, len(lines)):
            if lines[j].rstrip("\r\n") == _FRONTMATTER_DELIMITER:
                frontmatter = "".join(lines[opening + 1 : j])
                body = "".join(lines[j + 1 :])
                return frontmatter, body

        return None, ""
