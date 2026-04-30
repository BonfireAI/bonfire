# Cluster-351 follow-up — Scout report (Psychologist lens)

**UTC stamp:** 20260430T193448Z
**Lens:** Psychologist — caller intent, contract clarity, surprise surface
**Branch:** antawari/cluster-351-scout-psych @ 81c9d21 (origin/v0.1)
**Tickets in scope:** the four follow-ups filed against the cluster-351 surface
(constructor TOML-fallback raise, `pipeline.py:451` envelope.model asymmetry,
per-instance `BonfireSettings()` construction, dead-weight `envelope.model`
assignment in pipeline mode). Generic names used below for brevity:
**T-RAISE / T-ASYM / T-PERI / T-DEAD.**

This report is caller-perspective archaeology only — no source edits, no test
writes. It competes with the Artisan (code-shape) and Machinist (runtime-
mechanics) scouts for synthesis by Sage.

---

## TL;DR

The post-cluster-351 trio (`StageExecutor`, `PipelineEngine`, `WizardHandler`)
each grew a new constructor side-effect: when `settings=None`, the constructor
runs `BonfireSettings()`, which reads `bonfire.toml` from cwd and parses
`BONFIRE_*` env vars. Three independent surprises follow:

1. **Constructor raises now.** Any malformed `bonfire.toml` or any
   `BONFIRE_*` env var that violates a `PipelineConfig` validator
   (negative budget, non-positive turns) raises `ValidationError` from the
   constructor. Callers — including library consumers practicing BYOK,
   integration tests, and downstream framework code — were never warned.
2. **`envelope.model` is a write-only field in pipeline mode** (`pipeline.py:451`).
   `cost/consumer.py:36` reads `event.model` from `DispatchCompleted`, never
   `envelope.model`. The only true field-readers in the entire repo are inside
   `WizardHandler` (its own `review_envelope.model` self-reads) and the
   resolver-precedence chain in `executor.py:273`. The pipeline-mode
   assignment satisfies no consumer. It looks load-bearing; it is not.
3. **No production composition root.** `WizardHandler(...)` is constructed
   only in tests (per `bon-519-sage-20260428T033101Z.md` line 563). The
   per-instance settings construction problem is therefore latent for
   library consumers who wire their own composition root and entirely
   real for the framework's eventual one.

The fixes are easy. The contract documentation is the load-bearing piece —
without it, every BYOK consumer who imports `WizardHandler` discovers the
TOML coupling the same painful way.

---

## A. `envelope.model` consumer map

Field-access readers (NOT `envelope.model_copy`/`model_dump` — those are
Pydantic methods on a Pydantic model whose name happens to be `Envelope`):

| File:line | Read shape | Caller intent (speculation) |
|---|---|---|
| `src/bonfire/handlers/wizard.py:325` | `model=review_envelope.model` (assigning to `DispatchOptions`) | Wizard wrote model into a freshly-built `review_envelope` two lines earlier (line 311–315) and reads it back to populate `DispatchOptions`. Self-feeding. **Caller could read its own local resolver result with the same effect.** Field is load-bearing here ONLY because of the local round-trip, not because anyone downstream needs the field. |
| `src/bonfire/handlers/wizard.py:362` | `model=review_envelope.model` (fail-safe body template) | Render the model name in the parser-fallback review body posted to GitHub. Caller-facing. **This is the one read where the field flowing through the envelope matters** — the Wizard wants the model that was actually dispatched, not what was configured. If `envelope.model` ever drifts from `options.model` in the future, GitHub readers see the wrong number. |
| `src/bonfire/handlers/wizard.py:413` | `review_envelope.model` (log line) | Operational log: which model just ran. Same drift hazard as line 362. |
| `src/bonfire/engine/executor.py:273` | `envelope.model or resolver(...) or self._config.model` | The resolver precedence chain itself. Reads what was put there by `_execute_single_inner` two functions earlier (line 196: `model=stage.model_override or ""`). **Self-feeding** — the executor writes the field then reads it back. Could equally read `stage.model_override` directly without the envelope round-trip; the indirection exists to preserve "envelope as the unit of work" mental model. |

**Reads on `event.model`** (cost-event surface, NOT envelope-field):

| File:line | Read shape |
|---|---|
| `src/bonfire/cost/consumer.py:36` | `model=event.model` from `DispatchCompleted` |
| `src/bonfire/cost/analyzer.py:150` | `by_model[d.model]` — `DispatchRecord.model` |

**Critical observation:** The cost ledger's model attribution path goes
`DispatchOptions.model` → `runner.py:192 model=options.model` → `DispatchCompleted` →
`DispatchRecord.model` → `analyzer.model_costs()`. **`envelope.model` is not on
this path.** The ledger never reads it. So T-DEAD is correct in its claim that
the `pipeline.py:451` write is purely cosmetic in pipeline-mode dispatch.

**What downstream consumers think `envelope.model` promises:**
- BYOK callers reading the README "Envelope" section (does not exist) — no
  promise, no contract.
- Hook authors / `wire_consumers` extension authors who subscribe to
  `StageCompleted` — they get the envelope, will check `.model` if doing
  per-model accounting, will be silently wrong in pipeline mode.
- Future retry-strategy authors who route based on which model executed —
  will see `envelope.model` from pipeline-mode runs and assume it is the
  resolved model, when in fact only `executor.py` writes the resolved chain
  back into the envelope (and only via `DispatchOptions.model`, not the
  envelope field; see B for the asymmetry).

---

## B. Constructor-site catalog

### `StageExecutor(...)` — public class, 50+ test sites, 1 integration

`src/`: 0 production sites (none — handlers don't construct executors;
the engine does, internally).

`tests/`:
- `tests/unit/test_engine_executor.py` — **38 sites**, all positional or kw
  on `(backend=, bus=, config=)` plus optional `handlers=`, `vault_advisor=`,
  `project_root=`, `tool_policy=`, `context_builder=`. **Zero** pass `settings=`.
- `tests/unit/test_engine_executor_tool_policy.py` — **22 sites**, same shape, zero `settings=`.
- `tests/integration/test_budget_enforcement.py:256` — 1 site, no `settings=`.

`docs/`: `docs/audit/sage-decisions/bon-337-unified-sage-2026-04-18.md` lists
several reference constructor invocations, none with `settings=`.

**Total constructor surface: 60+ sites, all default-constructing settings via
the BON-617 fallback path. Every one is exposed to the BON-617 surprise.**

### `PipelineEngine(...)` — public engine class

`src/`: 0 production sites (no composition root).

`tests/`:
- `tests/unit/test_engine_pipeline.py` — **6 sites**, none with `settings=`.
- `tests/unit/test_engine_pipeline_tool_policy.py` — **20 sites**, none with `settings=`.
- `tests/integration/test_budget_enforcement.py:122` — 1 site, no `settings=`.
- `tests/integration/test_merge_preflight_pipeline.py:164` — 1 site, no `settings=`.

**Total: 28 sites, all default-construct.**

### `WizardHandler(...)` — public stage handler

`src/`: **0 production sites.** No composition root exists in the public tree
that wires `WizardHandler` (verified per `bon-519-sage-20260428T033101Z.md`
line 563: `grep -rn "WizardHandler(\|BardHandler(\|HeraldHandler(\|ArchitectHandler("` in `src/`
returns zero matches outside class definitions). The composition is the
caller's responsibility. **Every BYOK caller is a fresh blast radius for
T-RAISE.**

`tests/`:
- `tests/unit/test_wizard_handler.py:295` and `:915` — 2 sites, neither passes `settings=`.
- `tests/integration/test_merge_preflight_pipeline.py` — 4 sites all use
  `_StubWizardHandler` (a test double), so they bypass the real constructor.

### Constructor-site bottom line

Three classes, **~90 known constructor sites**, **zero** that pass
`settings=` today. A BYOK caller wiring their own pipeline writes
`PipelineEngine(backend=..., bus=..., config=...)` — that's exactly the shape
the README-equivalent doc would show. Their constructor reads `bonfire.toml`
from cwd silently. They never asked for that. **All 90 sites would break on
malformed TOML or env vars after T-RAISE lands.**

---

## C. Implicit-contract audit

### What docs and code promise to BYOK callers about constructor side effects

**README** (`README.md`):
- Line 109-112: "Bonfire reads `bonfire.toml` from the current working
  directory. Settings priority is: constructor kwargs → environment
  variables (`BONFIRE_` prefix, `__` nested delimiter) → `bonfire.toml` →
  field defaults." — **describes BonfireSettings, not handler constructors.**
- Line 142-145: "The `[models]` section is BYOK: Bonfire passes the
  configured string verbatim to the agent backend. To use a different
  provider, swap the strings to that provider's model identifiers and plug
  in a matching `AgentBackend`."
- Line 191-194: "Four `@runtime_checkable` Protocols define Bonfire's
  pluggable boundaries. The composition root verifies conformance at
  registration time, so any object with the matching shape works — no
  inheritance required." — implies **the caller writes the composition root.**
- Line 209-258: Lists `AgentBackend`, `VaultBackend`, `QualityGate`,
  `StageHandler` protocol shapes. **None of these mention TOML reads or
  environment-variable parsing in any handler/engine constructor.**

**Architecture doc** (`docs/architecture.md`):
- Line 97-98: "CLI entry. `bonfire.cli.app` parses the command and
  instantiates the composition root." — confirms **the CLI is one
  composition root; library callers are expected to roll another.**
- Line 104-107: Describes `PipelineEngine` as "owns the EventBus, the
  CheckpointManager, and the running cost / XP context" — **says nothing
  about owning a TOML reader.**

**CONTRIBUTING.md**: zero matches for "constructor", "init", "raise", "side
effect", "toml", or "BonfireSettings".

**Class docstrings:**
- `PipelineEngine` (`pipeline.py:85-91`): "Executes a WorkflowPlan as a DAG
  with gates, bounces, and budget control. Constructor accepts all
  dependencies via keyword-only arguments." — **"all dependencies"
  promises explicit construction. The post-cluster-351 implicit
  TOML/env read silently violates this.**
- `StageExecutor` (`executor.py:50-55`): "Decoupled from PipelineEngine so
  it can be tested, reused, and composed independently. Never raises — all
  exceptions become failed Envelopes (C19)." — **"never raises" is a
  runtime claim about `execute_single`, but a casual reader will infer
  the class doesn't raise period. The constructor newly does.**
- `WizardHandler` (`wizard.py:241-247`): "Pipeline stage handler for the
  reviewer role. Dispatches a review agent, parses the verdict, and posts
  a structured review to GitHub." — no constructor contract.

### Contract clarity verdict

The implicit contract today, as a reasonable BYOK caller would infer it:

> "These three classes accept their dependencies via keyword arguments.
> Construction is cheap and side-effect-free. Anything that fails will fail
> at runtime through a typed error path."

The post-cluster-351 reality:

> "These three classes will silently read `bonfire.toml` and `BONFIRE_*`
> env vars at construction time when `settings=None` (the default), and
> will raise `pydantic_core.ValidationError` if that read produces an
> invalid `BonfireSettings`. There is no graceful fallback."

**This is a load-bearing contract change. T-RAISE is real.** The fact that
no production site exposes it today is a function of the framework lacking
a public composition root, not a defense.

---

## D. Peer-library survey

What do FastAPI / Click / Typer / Pydantic-settings do for "config can fail
to load"?

**Pydantic-settings (the library Bonfire uses, [docs.pydantic.dev/latest/concepts/pydantic_settings/](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)):**

- `BaseSettings.__init__` raises `ValidationError` on invalid TOML/env data.
  This is the opposite of fail-soft.
- `extra='forbid'` (Bonfire's effective default — pydantic v2 default) raises
  on unknown fields.
- The library author intentionally pushes this to the application boundary
  — *applications* catch and decide; *Bonfire is a library*, so when its
  handler/engine constructor swallows or doesn't swallow `BonfireSettings()`'s
  raise, that decision is binding for every downstream BYOK caller.
- See [Pydantic Settings API ref](https://docs.pydantic.dev/latest/api/pydantic_settings/) — no
  guidance on "should constructors of *consumers* of BaseSettings instances
  default-construct the BaseSettings."

**Typer / Click ([fastapi/typer](https://github.com/fastapi/typer), [click.palletsprojects.com](https://click.palletsprojects.com/)):**

- CLI frameworks; constructors are command-decorator-driven, not
  config-loading-driven.
- They read `~/.config/<app>/...` only at command invocation, never at
  module import. The library does not fail at import time on missing or
  malformed config.

**FastAPI ([fastapi.tiangolo.com](https://fastapi.tiangolo.com/)):**

- FastAPI itself is config-agnostic. It depends on dependency injection;
  `Depends(get_settings)` is the canonical pattern. The settings instance
  is *constructed lazily on first request* with `@lru_cache` — never at
  router declaration time.
- This is the opposite of Bonfire's post-cluster-351 pattern. FastAPI
  routers are pure structural objects; settings are pulled from a DI
  context when needed.

**Lazy-init doctrine ([scientific-python.org/specs/spec-0001/](https://scientific-python.org/specs/spec-0001/), [PEP 810](https://peps.python.org/pep-0810/)):**

- Lazy submodule loading is now scientific Python convention. Errors at
  point of use, not at import.
- The cost: errors no longer fail-fast. The benefit: composition cost
  drops to near-zero.
- Bonfire's library callers want fast composition (no surprise disk reads
  during test setup), so the lazy-init doctrine applies to settings too.

**Principle of Least Surprise ([ardalis.com/principle-of-least-surprise/](https://ardalis.com/principle-of-least-surprise/)):**

- "If a class has insidious dependencies, developers should try to make
  this more apparent by injecting them via the constructor so users of
  the class are explicitly aware of them."
- Bonfire's three classes already accept `settings=` kw — the inject-point
  exists. The default-fallback to `BonfireSettings()` is the surprise
  vector. Injection-without-fallback (raise on `settings=None`) is one
  fix; documented-fallback-with-warning is another.

### Doctrinal alternatives, ranked:

| Option | Surprise level | Migration cost | Verdict |
|---|---|---|---|
| Make `settings` required (no default) | None — caller is forced to think | High — ~90 test sites need updating | Strongest contract; matches FastAPI DI doctrine |
| Default to `BonfireSettings()` and emit stderr warning if TOML fails | Low — caller sees the read happened | Low — wrap call in try/except | Matches the "BON-599 pattern" of fail-soft-with-warning |
| Default to lazy `_settings_factory: Callable[[], BonfireSettings]` lambda | Medium — semantics shift | Medium | Defers cost to first dispatch; fixes T-PERI cleanly |
| Status quo: silent `BonfireSettings()` that raises on bad TOML | High — silent disk read + surprise raise | Zero today | What T-RAISE is reporting |

**Sage-relevant point:** Option 2 (warn-and-fallback) is the doctrinally-
consistent path with how Bonfire treats other "silent fallback" decisions
elsewhere in the codebase. Option 1 (required arg) is the stronger long-term
contract but breaks compatibility for an alpha library that shouldn't yet
be optimizing for back-compat. **Recommend Option 2 short-term, with a
deprecation path to Option 1 for v0.2.**

---

## E. BON-599-pattern alignment (warn-on-fallback)

The cluster-351 follow-up surface includes T-RAISE, which alone is a contract
change. The deeper question is doctrinal consistency: does Bonfire warn when
silently degrading?

**Today's T-RAISE behavior** (post-cluster-351, current `v0.1` HEAD):

```python
# All three: pipeline.py:116, executor.py:92, wizard.py:264
self._settings = settings if settings is not None else _BonfireSettings()
```

If `_BonfireSettings()` raises (malformed TOML, invalid env var), the
exception propagates out of the constructor with no warning, no log, and
no fallback to defaults. The caller gets a raw `pydantic_core.ValidationError`
or `tomllib.TOMLDecodeError` from a constructor they thought was inert.

**Doctrinally-consistent patterns elsewhere in the repo:**

- `wizard.py:_parse_verdict` (line 157+): "Fail-safe: any parse failure
  returns ('request_changes', <reason>) — NEVER fail-open into 'approve'."
  Catch + flag-with-reason. The handler logs and falls back to a safe state.
- `pipeline.py:464-480` (handler dispatch unknown handler): catches the
  unknown-handler condition, returns a `with_error` envelope, emits
  `StageFailed`. Loud fallback.
- `wizard.py:392-405` (post-review failure): catches GH exceptions, logs,
  returns `enriched_envelope.with_error`. Loud fallback.

**The repo's pattern is loud-fail-soft: catch, log to stderr/logger,
proceed with a safe substitute or a typed error envelope.** Silent raise
from a constructor is the exception, not the rule.

### Recommendation for T-RAISE

Pair the catch-and-substitute path with a stderr `logger.warning` per the
doctrinal pattern:

```python
try:
    self._settings = settings if settings is not None else _BonfireSettings()
except (ValidationError, TOMLDecodeError) as exc:
    logger.warning(
        "Failed to load BonfireSettings from bonfire.toml/env (%s); "
        "falling back to schema defaults. Pass settings= explicitly to "
        "suppress this warning.",
        exc,
    )
    self._settings = BonfireSettings.model_construct()  # bypass validation
```

`model_construct` bypasses validation and gets a defaults-only instance,
which is a sensible fallback for the alpha. The warning surfaces the
silent disk read and gives the BYOK caller a remediation path.

---

## F. Recommended caller-facing contract changes

### F1. Class docstring updates

`PipelineEngine.__init__` (`pipeline.py:93`):

```python
def __init__(
    self,
    *,
    backend: AgentBackend,
    bus: EventBus,
    config: PipelineConfig,
    ...
    settings: BonfireSettings | None = None,
) -> None:
    """Initialize the engine.

    Args:
        settings: BonfireSettings instance. If None (default), the
            constructor will load settings from bonfire.toml in the cwd
            and BONFIRE_* environment variables. **This default
            performs disk I/O at construction time.** Pass settings=
            explicitly to avoid the implicit read; pass settings=
            BonfireSettings.model_construct() to bypass validation
            entirely.

    Raises:
        ValidationError: If settings is None AND bonfire.toml or env
            vars contain values that fail PipelineConfig validation
            (negative budget, non-positive max_turns).
        TOMLDecodeError: If settings is None AND bonfire.toml exists
            but is syntactically invalid.
    """
```

Same template for `StageExecutor.__init__` and `WizardHandler.__init__`.

### F2. README: a "Composition" subsection

Add a paragraph between "Per-Role Model Routing" and "Personality":

> ### Composition and Settings
>
> All three pipeline-runtime classes (`PipelineEngine`, `StageExecutor`,
> `WizardHandler`) accept a `settings: BonfireSettings | None`
> keyword. When omitted, the constructor reads `bonfire.toml` and
> `BONFIRE_*` env vars at construction time and raises if the read
> fails validation. **For library callers building their own
> composition root, pass `settings=` explicitly.** The CLI (`bonfire`)
> handles this for you.

### F3. Architecture doc: "Composition" section

Add a short subsection under "Pipeline flow" or "Extension points"
documenting the same constructor side-effect contract. Architecture-doc
is the binding doc for fresh-boot agent sessions per `CLAUDE.md`.

### F4. Exception-type promise

Pin the exception types raised by the constructors to the docstrings
(see F1). Today, the bare propagation can leak any exception
`BonfireSettings()` happens to throw (Pydantic minor versions can
change this). Catching `(ValidationError, TOMLDecodeError, OSError)`
and re-raising as a single `BonfireConfigError` would give callers
one type to catch.

### F5. Default-fallback warning (BON-599-pattern alignment)

See E above — wrap the default-construct in try/except, log a stderr
warning, fall back to `BonfireSettings.model_construct()`. This is the
doctrinal-consistency fix.

---

## G. Top 3 design questions for Sage (PUBLIC contract semantics)

### G1. Should `settings=` become required (no default), or stay optional with a documented surprise?

The default-None path is the surprise vector. The library is alpha — back-
compat is cheap to break. The library is also pre-v0.1.0 publication;
external BYOK callers don't exist yet. Window is open to make `settings=`
required and force every composition root to think about it. Once v0.1.0
ships, this becomes a breaking change.

**Trade-off:** Required-arg is a stronger contract (caller cannot
accidentally read disk in a test fixture). Optional-with-warning is gentler
on the existing 90 test sites.

**Sage call needed:** Pick one. Mixing is the worst option (some classes
require, some don't).

### G2. Is `envelope.model` a public contract or an internal field?

Today the field is read by exactly one *meaningful* downstream surface
(the Wizard fail-safe body, line 362, where it lands in a GitHub review).
Everything else is self-feeding. The cost ledger reads `event.model`,
not `envelope.model`.

If `envelope.model` is **public**: T-DEAD must be fixed (consistency:
pipeline mode and executor mode should both write the resolved model
back into the envelope so the field is reliable). T-ASYM must be fixed
similarly.

If `envelope.model` is **internal** (just a record-keeping field):
T-DEAD is the right fix (delete the assignment), and the Wizard's
read at line 362 should be replaced with `dispatch_result.envelope.model`
(which is what the runner sets via the SDK backend's return path).

**Sage call needed:** Public or internal? Pick. The README does not
mention the field; this is virgin contract territory.

### G3. Should the warn-on-fallback pattern (BON-599-style) extend to constructor-time TOML reads?

The repo's loud-fail-soft pattern (E) treats silent fallbacks as a
liability. Constructor-time TOML reads currently raise silently when the
read fails; the BON-599-style fix is wrap+warn+default. Doing this for
the three new constructors is mechanically cheap.

Doctrinal question: **does the warn-on-fallback policy apply to silent
disk reads, or only to silent value-substitutions?** Today the policy
is documented (in feedback memos) for value-substitution surfaces. Pin
it for I/O surfaces too, or carve out an exception?

**Sage call needed:** Extend the doctrine to I/O-failure substitution,
or scope it tighter. Either way, write it down so the next contributor
hits the same precedent.

---

## Appendix — files cited

- `src/bonfire/engine/pipeline.py` — PipelineEngine, lines 93-116, 451, 506
- `src/bonfire/engine/executor.py` — StageExecutor, lines 49-92, 196, 273
- `src/bonfire/handlers/wizard.py` — WizardHandler, lines 241-265, 311-315, 325, 362, 413
- `src/bonfire/models/config.py` — BonfireSettings, lines 140-180
- `src/bonfire/models/envelope.py` — Envelope.model field, line 76
- `src/bonfire/cost/consumer.py:36` — DispatchCompleted.model reader
- `src/bonfire/cost/analyzer.py:150` — DispatchRecord.model reader
- `src/bonfire/dispatch/runner.py:109,192` — options.model on event emit
- `src/bonfire/dispatch/sdk_backend.py:110` — options.model into SDK
- `README.md` lines 109-145, 189-258
- `docs/architecture.md` lines 97-110, 165-200
- `CONTRIBUTING.md` — silent on constructor side effects
- `docs/audit/sage-decisions/bon-519-sage-20260428T033101Z.md:563` — "no
  production composition root" finding
- `code-synth-bon351.md` — code-synth decision log filed two days ago,
  cited as the Sage memo D10 amendment trail

## Appendix — sources

- [Pydantic Settings — Settings Management](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)
- [Pydantic Settings — API reference](https://docs.pydantic.dev/latest/api/pydantic_settings/)
- [Pydantic — Validation Errors](https://docs.pydantic.dev/latest/errors/validation_errors/)
- [Pydantic — Validating File Data](https://docs.pydantic.dev/latest/examples/files/)
- [Principle of Least Surprise — Ardalis](https://ardalis.com/principle-of-least-surprise/)
- [APIs and the Principle of Least Surprise — DZone](https://dzone.com/articles/apis-and-the-principle-of-least-surprise)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Typer (fastapi/typer)](https://github.com/fastapi/typer)
- [Scientific Python — SPEC 1 Lazy Loading](https://scientific-python.org/specs/spec-0001/)
- [PEP 810 — Explicit Lazy Imports](https://peps.python.org/pep-0810/)
- [Building a Python Library in 2026 — Stephen Lf](https://stephenlf.dev/blog/python-library-in-2026/)
