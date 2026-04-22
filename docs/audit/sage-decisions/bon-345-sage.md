# BON-345 Sage Synthesis — `persona/` module transfer (W5.6)

**Ticket:** BON-345 (Wave 5.6 — public v0.1 transfer of `bonfire.persona`).
**Base:** `v0.1 @ 9ac260c`.
**Sage worktree:** `antawari/bon-345-sage`.
**Knight-A worktree:** `antawari/bon-345-knight-a` (strict-rename lens — 29 + 26 + 18 + 15 = 88 tests).
**Knight-B worktree:** `antawari/bon-345-knight-b` (schema-strict lens — 32 + 22 + 20 + 19 + 11 = 104 tests).
**Private V1 reference:** `/home/ishtar/Projects/bonfire/src/bonfire/persona/{base,protocol,pool,loader}.py` (hookspec deferred).
**Canonical vocab:** `src/bonfire/naming.py` (`ROLE_DISPLAY`), `src/bonfire/agent/roles.py` (`AgentRole`).

This log arbitrates the six OPEN DECISIONS the Knights flagged, dedupes
convergent tests, preserves each lens's adversarial contribution, and fixes
the canonical file/class list the Warrior must satisfy.

---

## Convergences (locked)

- `PhrasePool` → `PhraseBank` class rename.
- `pool.py` → `phrase_bank.py` module rename.
- `"passelewe"` → `"default"` as the default persona name. Passelewe kept
  as an optional example persona in `builtins/passelewe/`.
- `hookspec.py` deferred entirely. No `PersonaHookSpec`, no `pluggy`
  import, no stale comment in `loader.py`.
- `[display_names]` lives in `persona.toml` (single TOML home).
- All 8 `AgentRole` values required in every built-in's `[display_names]`
  map; missing any raises schema error.
- Minimal safety-net persona — `BasePersona(name="minimal", phrases={})` —
  hardcoded, always returned when discovery fails.

---

## Decision table

| # | Open decision                          | Verdict                                                                 |
|---|----------------------------------------|-------------------------------------------------------------------------|
| D1 | Extras policy on persona TOML          | **Split:** top-level unknown tables → warn + continue; unknown keys in `[display_names]` → strict `PersonaSchemaError` |
| D2 | New public contract surface            | **Adopt all four:** `display_name(role)`, `display_names=` kwarg, `validate(name)`, `PersonaSchemaError` |
| D3 | `load()` no-arg contract               | **Ergonomic:** `PersonaLoader.load()` with no arg returns the `default` persona |
| D4 | `Config.persona` default               | **In scope for BON-345:** Warrior updates `src/bonfire/models/config.py:46` to `persona: str = "default"` |
| D5 | Safety-net name `minimal`              | **Discoverable built-in:** ships as `builtins/minimal/` AND is the hardcoded last-resort fallback |
| D6 | Passelewe distinctness test            | **Deterministic set-comparison on phrase banks** — no RNG sampling       |

---

## Per-decision analysis

### D1 — Extras policy (SPLIT)

**Verdict:** top-level unknown tables accepted with a warning; unknown role
keys inside `[display_names]` rejected strictly with `PersonaSchemaError`
naming the bogus role.

**Rationale:**

- **Top level is user-authored content.** A persona author may add
  `[metadata]`, `[author]`, or `[notes]` sections over time. Rejecting
  bricks the persona on a typo the user considered harmless; warning
  keeps the ship moving while the signal stays visible.
- **Role keys are not user-authored in spirit — they're a shared wire
  contract.** A typo like `reasearcher` would silently drop that role
  from display translation and the operator would never know until the
  CLI printed the professional fallback. Strict rejection with the role
  name in the error message turns a silent failure into a one-line fix.
- Split enforcement matches the sequence-stamping-counter-example
  lesson from BON-338: adversarial per-role parametrized tests prove
  coverage; wrap them with a hard error so they can't be diluted.

**Contract:**
- Unknown top-level table → `logger.warning("unknown persona table %r", name)`, validation continues.
- Unknown key inside `[display_names]` → `raise PersonaSchemaError("unknown role key: {key!r}")`.

### D2 — New public contract surface (ADOPT)

**Verdict:** adopt all four additions from Knight B.

1. `BasePersona.display_name(role: AgentRole) -> str` — gamified wins, else professional fallback from `ROLE_DISPLAY`.
2. `BasePersona.__init__(name, phrases, display_names={})` — new optional kwarg carrying role → gamified-name map.
3. `PersonaLoader.validate(name: str) -> None` — strict schema check that raises `PersonaSchemaError`. Distinct from `load()`, which stays total.
4. `PersonaSchemaError(ValueError)` — dedicated exception class.

**Rationale:**

- `display_name(role)` is the **runtime arm** of the three-layer naming
  vocabulary. Without it, the naming module is documentation but not
  enforcement — the persona module is the only layer that has an
  `AgentRole` and a user-facing string at the same moment. This is
  load-bearing for CLI output translation.
- `validate()` vs `load()` is the correct shape: `load()` must be total
  (never raise, the engine depends on getting _something_), `validate()`
  is strict (for `bonfire personas validate` CLI, for CI, for the
  loader to call internally when it wants to know _why_ a malformed
  TOML fell through).
- `PersonaSchemaError(ValueError)` — inheriting from `ValueError` keeps
  callers that catch `ValueError` working, while allowing persona-specific
  catches for richer CLI feedback.
- Knight A's suite is compatible — it just doesn't exercise these
  symbols. Knight B's already-written parametrized adversarials lock
  them hard.

### D3 — `load()` no-arg contract (ERGONOMIC)

**Verdict:** `PersonaLoader.load()` with no arg returns the persona named
`"default"`. Matches Knight A's explicit test and the v1 pattern.

**Rationale:** cleaner caller code (`loader.load()` at bootstrap), aligns
with how `Config.persona` gets resolved. The no-arg form makes the default
an API contract, not a convention.

**Contract:** `def load(self, name: str = "default") -> PersonaProtocol: ...`

### D4 — `Config.persona` default (IN SCOPE)

**Verdict:** Warrior updates `src/bonfire/models/config.py:46` from
`persona: str = "passelewe"` → `persona: str = "default"` as part of
BON-345. Rename-sweep test enforces it.

**Rationale:**

- The rename is incomplete without this line. Leaving `passelewe` pinned
  in the config default contradicts the loader's no-arg default and the
  rename-sweep negative assertion (no `"passelewe"` literal anywhere in
  `src/bonfire/`).
- One-line change, no API break for external callers (the semantics they
  get — "the default persona" — don't change), and it keeps the wave
  self-consistent.
- Knight A already has `test_no_passelewe_literal_in_persona_py_sources`
  and `test_no_passelewe_default_in_src_bonfire`; the synthesized
  `test_persona_rename_sweep.py` preserves both, so the Warrior's fix
  is test-driven.

### D5 — Safety-net name (DISCOVERABLE built-in)

**Verdict:** `minimal` ships as a built-in persona at
`src/bonfire/persona/builtins/minimal/` AND is the hardcoded last-resort
fallback when even `minimal/` fails to load.

**Rationale:**

- Knight B's `test_persona_builtin.py` already requires `minimal/` to
  ship (`test_at_least_default_and_minimal_ship`, schema validation,
  "no personality markers" check, "exactly one phrase per event"
  check). These are strong contracts — the persona is load-bearing for
  debug output where personality would be noise.
- Knight A's `test_minimal_safety_net` logic still holds: even if
  `builtins/minimal/` disappears (corrupted install, hostile filesystem),
  the loader returns `BasePersona(name="minimal", phrases={})` rather
  than raising.
- Previous spec worry ("users shouldn't accidentally select `--persona
  minimal`") is overblown: selecting minimal explicitly is a legitimate
  request ("give me structural output with no character"). Discoverable
  is correct.

**Contract:**
- `PersonaLoader.available()` lists `minimal` (and `default`, and
  `passelewe` if shipped).
- `PersonaLoader.load("nonexistent")` → loads `minimal/` built-in if
  present, else hardcoded `BasePersona(name="minimal", phrases={})`.
- Every path logs a warning when the fallback fires.

### D6 — Passelewe distinctness (DETERMINISTIC set-comparison)

**Verdict:** compare the raw phrase banks (dict of lists of strings)
between `default` and `passelewe` by reading their `phrases.toml`
directly. Assert that the flattened phrase sets differ — passelewe must
have phrases `default` does not carry (or vice versa), proving they are
not aliases.

**Rationale:**

- RNG sampling is flaky by construction. A 10-sample run can match in
  all 10 samples when the banks overlap heavily on a high-frequency
  event type, and the test would blame the implementation.
- Set comparison is deterministic, captures the intent ("these are
  distinct voices"), and doesn't rely on the anti-repeat algorithm.
- Canonical assertion: `passelewe_phrases ^ default_phrases` (symmetric
  difference) must be non-empty.

---

## Warrior contract (symbols to implement)

### Module layout

```
src/bonfire/persona/
    __init__.py                   # public exports (see below)
    protocol.py                   # PersonaProtocol (typing.Protocol, @runtime_checkable)
    phrase_bank.py                # PhraseBank (was pool.py / PhrasePool in v1)
    base.py                       # BasePersona (implements PersonaProtocol)
    loader.py                     # PersonaLoader, PersonaSchemaError
    builtins/
        default/
            persona.toml
            phrases.toml
        minimal/
            persona.toml
            phrases.toml
        passelewe/
            persona.toml
            phrases.toml
```

### Public exports (`src/bonfire/persona/__init__.py`)

```python
from bonfire.persona.base import BasePersona
from bonfire.persona.loader import PersonaLoader, PersonaSchemaError
from bonfire.persona.phrase_bank import PhraseBank
from bonfire.persona.protocol import PersonaProtocol

__all__ = [
    "BasePersona",
    "PersonaLoader",
    "PersonaProtocol",
    "PersonaSchemaError",
    "PhraseBank",
]
```

(No `PhrasePool`. No `PersonaHookSpec`. No `pluggy`.)

### Symbol-by-symbol

- `PersonaProtocol` — `typing.Protocol`, `@runtime_checkable`, NOT an
  ABC, exposes `name: str`, `format_event(event) -> str | None`,
  `format_summary(stats: dict) -> str`.

- `PhraseBank(phrases: dict[str, list[str]])`:
  - `select(event_type, ctx, variant: str | None = None) -> str | None`
  - Unknown event type → `None`.
  - Empty list → `None`.
  - Anti-repeat on consecutive `select()` calls for the same event
    type when bank size ≥ 2.
  - `variant="after_failure"` looks up `event_type:after_failure`, falls
    back to `event_type` if the variant bank is missing.
  - Missing placeholder in context must not raise (safe-format).

- `BasePersona(name: str, phrases: dict | None = None, display_names: dict[str, str] | None = None)`:
  - `name: str` property.
  - `format_event(event) -> str | None`.
  - `format_summary(stats) -> str`.
  - `display_name(role: AgentRole) -> str` — returns
    `display_names[role.value]` if present, else
    `naming.ROLE_DISPLAY[role.value].professional`. Never raises for
    any `AgentRole` value.

- `PersonaLoader(builtin_dir: Path, user_dir: Path)`:
  - `load(name: str = "default") -> PersonaProtocol` — total. User dir
    wins on name collision. Malformed TOML logs warning, falls back to
    minimal. Case-sensitive.
  - `validate(name: str) -> None` — strict. Raises
    `PersonaSchemaError` naming the offending field/role/table. Extras
    policy per D1.
  - `available() -> list[str]` — deduplicated, sorted list of persona
    names from both dirs.

- `PersonaSchemaError(ValueError)` — dedicated exception for strict
  validation.

### Built-in TOML requirements

- `default/persona.toml` — `[persona]` with `name="default"`,
  `display_name`, `description`, `version="1.0.0"`. `[display_names]`
  covers all 8 `AgentRole` values using **professional** names
  (`ROLE_DISPLAY[role].professional`).
- `minimal/persona.toml` — same required fields. `[display_names]`
  covers all 8 roles (professional names). `phrases.toml` has exactly
  one phrase per event type, no personality markers
  (sire/milord/chamber/forge/flame/alas/hark/prithee/decree/summon).
- `passelewe/persona.toml` — chamberlain voice. Required fields. Must
  ship a non-empty `[persona].description` OR a leading `#` comment on
  line 1 or 2 (explanatory one-liner). `[display_names]` covers all 8
  roles (free to use gamified names).

### Config update (D4)

`src/bonfire/models/config.py:46` → `persona: str = "default"`.

### Negative grep sweep targets

- `PhrasePool` — not in `src/bonfire/`.
- `from bonfire.persona.pool` / `import bonfire.persona.pool` — not in `src/bonfire/`.
- `pool.py` — not in `src/bonfire/persona/`.
- `hookspec.py` — not in `src/bonfire/persona/`.
- `PersonaHookSpec` — not in `src/bonfire/`.
- `import pluggy` / `from pluggy` — not in any `bonfire.persona.*` module.
- `"passelewe"` / `'passelewe'` string literals — not in `src/bonfire/persona/*.py`, not in `src/bonfire/` Python sources (allowed only inside `builtins/passelewe/persona.toml`).
- `# hookspec` / `hookspec` (case-insensitive) comment — not in `loader.py`.

---

## Dedupe math (runtime test counts, 3 built-ins shipped)

| Bucket                         | Knight A | Knight B | Union raw | Synth | Dedupe |
|--------------------------------|----------|----------|-----------|-------|--------|
| Core (protocol/PhraseBank/Base)| 29       | 32       | 61        | 37    | 39 %   |
| Loader (discovery/fallback)    | 26       | 22       | 48        | 32    | 33 %   |
| Rename sweep                   | 18       | 0        | 18        | 30    | (+ D4 additions) |
| TOML schema                    | 0        | 20       | 20        | 33    | (+ D1 split) |
| Built-in coverage              | 15       | 19       | 34        | 26    | 24 %   |
| Defaults (default/passelewe)   | 15       | 0        | 15        | 19    | (+ minimal + D6) |
| Discovery edge cases           | 0        | 11       | 11        | 11    | 0 %    |
| **Total**                      | **88**   | **104**  | **192**   | **188** | **~32 % after additions** |

Notes:

- Rename-sweep grew vs Knight A raw because Sage D4 added
  `Config.persona` default enforcement (3 tests) and D5 added the
  `minimal/` ships assertion, and role-parametrized tests expand ×3
  (one per shipped builtin: default/minimal/passelewe).
- TOML schema grew vs Knight B raw because D1 added explicit strict-
  reject adversarials and acceptance variants for the extras policy.
- Defaults grew because Sage D5 added a full `TestMinimalPersona`
  class to the real-dir defaults file, and D6 replaced flaky RNG
  sampling with deterministic phrase-bank set-comparison.
- Pure union A+B is 192; after synthesis 188. Dedupe ratio is
  material on the core/loader/built-in buckets where Knights genuinely
  overlapped; additions in the rename-sweep/schema/defaults buckets
  reflect Sage-locked decisions extending coverage, not slack.

---

## Follow-up tickets proposed

1. **`bonfire personas validate` CLI command** — surface
   `PersonaLoader.validate()` as a CLI subcommand so CI and users can
   check a user-authored persona before dropping it in `~/.bonfire/personas/`.
2. **Persona hookspec / pluggy plugin discovery** — revival of the
   deferred hookspec once the third-party persona ecosystem warrants
   it. Blocked on: Bonfire public adoption > threshold.
3. **Atmosphere / tier / gamification display-name methods** —
   `BasePersona.display_name(role)` covers AgentRole but `ROLE_DISPLAY`
   is just one of five maps in `naming.py`. Follow-up to add
   `pipeline_display`, `gamification_display`, etc., driven by CLI
   output needs.
4. **`passelewe` promotion to full chamberlain voice** — current
   builtin TOML is a skeleton for v0.1; full seven-laws-of-passelewe
   phrase coverage is its own authoring ticket post-v0.1.
5. **Persona schema version pin** — add a `schema_version = "1"` field
   and gate `validate()` on it so later waves can evolve the TOML shape
   without breaking v0.1 personas.
