"""RED contract for PersonaLoader name validation.

Subject: ``bonfire.persona.loader.PersonaLoader._find_persona_dir``
concatenates ``base / name`` without validating ``name``. The sister
:class:`bonfire.integrations.loader.ISMLoader` already validates with
``_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_-]*$")``.

Today ``PersonaLoader.load("../../etc/passwd")`` is documented as
"total — never raises" and silently probes whether arbitrary paths
exist, leaking filesystem-existence signal through the
fallback-vs-success path discriminator.

This file pins down the contract that ``PersonaLoader.load`` (still
total) rejects any name not matching the slug pattern, emits a WARNING
log line naming the rejected value, and returns the hardcoded minimal
persona instead.

The Warrior will port the regex (and its rationale) from the sister ISM
loader. The pattern's exact wording is the implementation's call — the
contract is its REJECTION SURFACE.
"""

from __future__ import annotations

import logging

import pytest

from bonfire.persona.base import BasePersona
from bonfire.persona.loader import PersonaLoader

# Names that must be rejected. Each fails the
# ``^[a-z][a-z0-9_-]*$`` pattern the sister ISM loader uses.
_INVALID_NAMES = [
    "../../etc/passwd",  # path traversal
    "..",  # parent dir
    "dir/with/slash",  # forward-slash injection
    "name\x00null",  # NUL byte
    "",  # empty string
    "Name-With-Caps",  # uppercase rejected
    ".dotfile",  # leading dot
    "trailing-slash/",  # trailing slash
    "back\\slash",  # backslash (Windows-style traversal)
    "spaces here",  # whitespace
]


def _make_loader(tmp_path) -> PersonaLoader:
    """Build a loader pointed at empty builtin + user dirs.

    With both dirs empty the loader's only "real" path is its fallback
    chain. Any path-traversal probe that DOES find a hit (e.g. by
    escaping ``tmp_path``) would prove the contract violated.
    """
    builtin = tmp_path / "builtins"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()
    return PersonaLoader(builtin_dir=builtin, user_dir=user)


def _make_loader_with_valid_persona(tmp_path, name: str = "falcor") -> PersonaLoader:
    """Build a loader with a single valid persona in builtin_dir.

    Lets the "valid name still loads" assertion exercise the real
    discovery path without depending on the package's bundled
    builtins (whose location varies with editable install vs wheel).
    """
    builtin = tmp_path / "builtins"
    user = tmp_path / "user"
    builtin.mkdir()
    user.mkdir()

    persona_dir = builtin / name
    persona_dir.mkdir()
    (persona_dir / "persona.toml").write_text(
        f'[persona]\nname = "{name}"\n'
        f'display_name = "{name}"\n'
        'description = "test"\n'
        'version = "1"\n'
        "[display_names]\n"
    )
    return PersonaLoader(builtin_dir=builtin, user_dir=user)


class TestLoadRejectsInvalidNames:
    """``PersonaLoader.load`` rejects invalid names BEFORE the filesystem probe.

    The fingerprint of the fix: invalid input never reaches
    ``_find_persona_dir`` (and never triggers a filesystem ``stat`` /
    ``is_file`` call). Today every invalid name flows through the
    same probe-then-fallback path as a regular not-found name, so an
    attacker can use probe latency / fallback semantics to learn
    whether arbitrary paths exist.
    """

    @pytest.mark.parametrize("name", _INVALID_NAMES)
    def test_load_invalid_name_short_circuits_before_filesystem_probe(
        self,
        tmp_path,
        name: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``_find_persona_dir`` MUST NOT be called for invalid *name*.

        The Warrior's validator runs BEFORE the filesystem probe. We
        assert by replacing ``_find_persona_dir`` with a recording
        spy and asserting it was never invoked with the invalid name.
        Today every name flows through ``_find_persona_dir`` — so this
        is the RED signal until the validator lands.
        """
        loader = _make_loader(tmp_path)

        seen_names: list[str] = []
        real_find = PersonaLoader._find_persona_dir

        def _recording_find(self, candidate: str):
            seen_names.append(candidate)
            return real_find(self, candidate)

        monkeypatch.setattr(PersonaLoader, "_find_persona_dir", _recording_find)

        result = loader.load(name)

        assert name not in seen_names, (
            f"_find_persona_dir was called with the invalid name {name!r}; "
            f"the validator must reject before the probe. Probe sequence: {seen_names!r}"
        )
        # And the safety-net fallback still returns the hardcoded
        # minimal persona — invariant the loader's docstring already
        # promises.
        assert isinstance(result, BasePersona)
        assert result.name == "minimal"

    @pytest.mark.parametrize("name", _INVALID_NAMES)
    def test_load_invalid_name_emits_warning(
        self,
        tmp_path,
        name: str,
        caplog: pytest.LogCaptureFixture,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A WARNING log line names the rejected value AND the rejection reason.

        Today's loader emits a generic "not found or malformed" warning
        for every miss — including invalid input. The contract pins a
        DEDICATED rejection warning that distinguishes
        "name is structurally invalid" from "name not found in either
        dir". The Warrior is free to phrase it ("invalid persona
        name", "rejected", etc.) — what we lock is that the warning's
        text mentions either "invalid" or "reject".
        """
        loader = _make_loader(tmp_path)

        caplog.set_level(logging.WARNING, logger="bonfire.persona.loader")
        loader.load(name)

        warning_records = [r for r in caplog.records if r.levelno >= logging.WARNING]
        assert warning_records, (
            f"PersonaLoader.load({name!r}) must emit at least one WARNING; "
            f"got records: {[r.getMessage() for r in caplog.records]!r}"
        )
        joined = " | ".join(r.getMessage().lower() for r in warning_records)
        assert "invalid" in joined or "reject" in joined, (
            f"WARNING for invalid name must signal the rejection (text "
            f"containing 'invalid' or 'reject'); got: {joined!r}"
        )


class TestLoadValidNameStillSucceeds:
    """Valid names still load normally — the validator is rejection-only."""

    def test_load_valid_name_returns_real_persona(self, tmp_path) -> None:
        """A name passing the slug pattern loads the real persona TOML."""
        loader = _make_loader_with_valid_persona(tmp_path, name="falcor")

        result = loader.load("falcor")
        assert result.name == "falcor"


class TestAvailableSurfaceUnaffected:
    """``PersonaLoader.available`` is the directory-discovery method and
    is NOT in the input-validation contract surface."""

    def test_available_lists_only_well_formed_dirs(self, tmp_path) -> None:
        """``available()`` returns whatever directories are on disk.

        It already implicitly filters by directory-name shape (no
        dotfiles or hidden dirs in the iter loop). What we lock here is
        that the name-validation tightening doesn't accidentally also
        gate ``available()``'s output — discovery is filesystem-derived,
        not user-input-derived.
        """
        loader = _make_loader_with_valid_persona(tmp_path, name="falcor")
        result = loader.available()
        assert "falcor" in result


class TestEmptyAndEdgeCases:
    """Empty string and None-ish inputs."""

    def test_load_empty_string_returns_minimal(self, tmp_path) -> None:
        """The empty string is an invalid slug; load returns minimal."""
        loader = _make_loader(tmp_path)
        result = loader.load("")
        assert result.name == "minimal"
