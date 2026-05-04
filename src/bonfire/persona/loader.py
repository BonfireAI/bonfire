# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 BonfireAI

"""PersonaLoader — two-tier discovery and loading of TOML-based personas.

Discovers persona directories from:
  1. User-installed: ``user_dir/{name}/``  (highest priority)
  2. Built-in:       ``builtin_dir/{name}/``

Each persona directory contains:
  - ``persona.toml`` — required metadata + display_names map
  - ``phrases.toml`` — optional phrase bank keyed by event_type

Two methods split the total/strict responsibilities:
  * :meth:`PersonaLoader.load` — total. Never raises. Falls back through
    ``default`` -> ``minimal`` -> a hardcoded minimal persona.
  * :meth:`PersonaLoader.validate` — strict. Raises
    :class:`PersonaSchemaError` describing the offending field, role,
    or table.
"""

from __future__ import annotations

import logging
import tomllib
from pathlib import Path  # noqa: TC003 — runtime constructor type

from bonfire.agent.roles import AgentRole
from bonfire.persona.base import BasePersona

logger = logging.getLogger(__name__)

_HARDCODED_MINIMAL = BasePersona(name="minimal", phrases={})

_REQUIRED_PERSONA_FIELDS = ("name", "display_name", "description", "version")
_CANONICAL_ROLE_VALUES = frozenset(r.value for r in AgentRole)
_KNOWN_TOPLEVEL_TABLES = frozenset({"persona", "display_names"})


class PersonaSchemaError(ValueError):
    """Raised by :meth:`PersonaLoader.validate` for a malformed persona TOML.

    Inherits from :class:`ValueError` so callers handling generic data-shape
    errors keep working while persona-specific catches get richer context.
    """


class PersonaLoader:
    """Loads persona definitions from TOML with two-tier discovery."""

    def __init__(self, builtin_dir: Path, user_dir: Path) -> None:
        self._builtin_dir = builtin_dir
        self._user_dir = user_dir

    # ------------------------------------------------------------------
    # Public: load() — total, never raises
    # ------------------------------------------------------------------

    def load(self, name: str = "default") -> BasePersona:
        """Load a persona by name; fall back to minimal on any failure.

        Discovery order: ``user_dir`` first, then ``builtin_dir``. Unknown
        names, malformed TOML, or partial installs all fall through to
        the minimal safety net — first the ``minimal`` built-in if
        present, then a hardcoded ``BasePersona(name='minimal', phrases={})``.

        This method is total. It never raises.
        """
        persona = self._try_load(name)
        if persona is not None:
            return persona

        logger.warning(
            "Persona %r not found or malformed, falling back to minimal",
            name,
        )

        if name != "minimal":
            minimal = self._try_load("minimal")
            if minimal is not None:
                return minimal

        return _HARDCODED_MINIMAL

    # ------------------------------------------------------------------
    # Public: validate() — strict, raises PersonaSchemaError
    # ------------------------------------------------------------------

    def validate(self, name: str) -> None:
        """Strictly validate a persona's schema.

        Raises
        ------
        PersonaSchemaError
            If the persona cannot be found, ``persona.toml`` is missing,
            TOML is malformed, required fields are missing or wrong
            types, ``[display_names]`` is missing/empty/incomplete, or
            contains unknown role keys.

        Unknown top-level tables (e.g. ``[metadata]``, ``[notes]``) are
        accepted with a ``logging.WARNING`` naming the table.
        """
        persona_dir = self._find_persona_dir(name)
        if persona_dir is None:
            raise PersonaSchemaError(f"persona {name!r} not found in user_dir or builtin_dir")

        toml_path = persona_dir / "persona.toml"
        if not toml_path.is_file():
            raise PersonaSchemaError(f"persona {name!r}: persona.toml missing at {toml_path}")

        try:
            with toml_path.open("rb") as f:
                raw = tomllib.load(f)
        except tomllib.TOMLDecodeError as exc:
            raise PersonaSchemaError(
                f"persona {name!r}: persona.toml is malformed TOML: {exc}"
            ) from exc
        except OSError as exc:
            raise PersonaSchemaError(
                f"persona {name!r}: persona.toml could not be read: {exc}"
            ) from exc

        self._validate_raw(name, raw)

    # ------------------------------------------------------------------
    # Public: available() — deduplicated sorted list
    # ------------------------------------------------------------------

    def available(self) -> list[str]:
        """Return a deduplicated, sorted list of persona names."""
        names: set[str] = set()
        for d in (self._builtin_dir, self._user_dir):
            if not d.is_dir():
                continue
            for child in d.iterdir():
                if child.is_dir() and (child / "persona.toml").is_file():
                    names.add(child.name)
        return sorted(names)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _find_persona_dir(self, name: str) -> Path | None:
        """Return the first persona dir with a persona.toml, user-dir wins."""
        for base in (self._user_dir, self._builtin_dir):
            candidate = base / name
            if (candidate / "persona.toml").is_file():
                return candidate
        return None

    def _try_load(self, name: str) -> BasePersona | None:
        """Attempt to load a persona; return None on any failure."""
        persona_dir = self._find_persona_dir(name)
        if persona_dir is None:
            return None
        return self._parse_persona(persona_dir)

    def _parse_persona(self, persona_dir: Path) -> BasePersona | None:
        """Parse a persona directory tolerantly.

        Returns ``None`` for any recoverable failure (malformed TOML,
        missing required sections). Loader fallback takes over.
        """
        persona_toml = persona_dir / "persona.toml"
        try:
            with persona_toml.open("rb") as f:
                raw = tomllib.load(f)
        except (tomllib.TOMLDecodeError, OSError) as exc:
            logger.warning(
                "persona %r: persona.toml is malformed: %s",
                persona_dir.name,
                exc,
            )
            return None

        persona_meta = raw.get("persona")
        if not isinstance(persona_meta, dict):
            logger.warning(
                "persona %r: missing [persona] table",
                persona_dir.name,
            )
            return None

        # Use directory name as the authoritative identity.
        persona_name = persona_dir.name

        display_names_raw = raw.get("display_names", {})
        display_names: dict[str, str] = {}
        if isinstance(display_names_raw, dict):
            for k, v in display_names_raw.items():
                if isinstance(v, str) and v:
                    display_names[k] = v

        phrases: dict[str, list[str]] = {}
        phrases_path = persona_dir / "phrases.toml"
        if phrases_path.is_file():
            try:
                with phrases_path.open("rb") as f:
                    phrases_raw = tomllib.load(f)
                phrases = self._flatten_phrases(phrases_raw)
            except (tomllib.TOMLDecodeError, OSError) as exc:
                logger.warning(
                    "persona %r: phrases.toml is malformed: %s",
                    persona_dir.name,
                    exc,
                )

        return BasePersona(
            name=persona_name,
            phrases=phrases,
            display_names=display_names,
        )

    def _validate_raw(self, name: str, raw: dict) -> None:
        """Apply the strict schema rules to a parsed TOML dict.

        Emits a warning for unknown top-level tables. Raises
        :class:`PersonaSchemaError` for every other shape violation.
        """
        # ---- Warn on unknown top-level tables (D1 lenient arm) --------
        for top_key, top_val in raw.items():
            if top_key in _KNOWN_TOPLEVEL_TABLES:
                continue
            if isinstance(top_val, dict):
                logger.warning(
                    "persona %r: unknown persona table %r — ignored",
                    name,
                    top_key,
                )

        # ---- [persona] required fields + types ------------------------
        persona_meta = raw.get("persona")
        if not isinstance(persona_meta, dict):
            raise PersonaSchemaError(f"persona {name!r}: missing [persona] table")

        for field in _REQUIRED_PERSONA_FIELDS:
            if field not in persona_meta:
                raise PersonaSchemaError(
                    f"persona {name!r}: [persona] is missing required field {field!r}"
                )
            value = persona_meta[field]
            if not isinstance(value, str):
                raise PersonaSchemaError(
                    f"persona {name!r}: [persona].{field} must be a string, "
                    f"got {type(value).__name__}"
                )
            if value == "":
                raise PersonaSchemaError(f"persona {name!r}: [persona].{field} must be non-empty")

        # ---- [display_names] coverage + strict extras rejection -------
        if "display_names" not in raw:
            raise PersonaSchemaError(f"persona {name!r}: [display_names] table is required")
        display_names = raw["display_names"]
        if not isinstance(display_names, dict):
            raise PersonaSchemaError(f"persona {name!r}: [display_names] must be a TOML table")
        if not display_names:
            raise PersonaSchemaError(
                f"persona {name!r}: [display_names] must cover every role; got an empty table"
            )

        provided = set(display_names.keys())
        missing = _CANONICAL_ROLE_VALUES - provided
        if missing:
            missing_list = ", ".join(sorted(missing))
            raise PersonaSchemaError(
                f"persona {name!r}: [display_names] is missing role(s): {missing_list}"
            )

        unknown = provided - _CANONICAL_ROLE_VALUES
        if unknown:
            unknown_list = ", ".join(sorted(unknown))
            raise PersonaSchemaError(
                f"persona {name!r}: [display_names] has unknown role key(s): {unknown_list}"
            )

        for role_key, value in display_names.items():
            if not isinstance(value, str):
                raise PersonaSchemaError(
                    f"persona {name!r}: [display_names].{role_key} must be a "
                    f"string, got {type(value).__name__}"
                )
            if not value.strip():
                raise PersonaSchemaError(
                    f"persona {name!r}: [display_names].{role_key} must be non-empty"
                )

    @staticmethod
    def _flatten_phrases(raw: dict) -> dict[str, list[str]]:
        """Flatten nested TOML sections into dotted event_type keys.

        ``{"stage": {"started": {"phrases": [...]}}}``
        becomes ``{"stage.started": [...]}``.
        """
        result: dict[str, list[str]] = {}
        for category, events in raw.items():
            if not isinstance(events, dict):
                continue
            for event_name, value in events.items():
                if not isinstance(value, dict) or "phrases" not in value:
                    continue
                phrases = value["phrases"]
                if not isinstance(phrases, list):
                    continue
                key = f"{category}.{event_name}"
                result[key] = [p for p in phrases if isinstance(p, str)]
        return result
